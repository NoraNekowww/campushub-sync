"""天津大学教务 (office-network) timetable — the path the official app uses.

The 微北洋 mobile clients (Android/iOS only, no web client) no longer touch
``open.twt.edu.cn/api/v1/classtable``. They POST the *office-network* creds to
the TWT backend, which does the CAS login + CAPTCHA itself and returns a
normalised timetable:

    POST https://learning.twt.edu.cn/get_classes    (multipart/form-data)
        username=<student id>   passwd=<office-network password>
    -> {"code": 200, "data": {"courses": {"major": [...], "minor": [...]},
                              "exams": [...], "gpa": {...}, ...}}

Each course object is exactly the shape the official Flutter client parses
(``Course.fromJson`` in WePeiYang-Flutter)::

    {"name": "...", "classId": "...", "courseId": "...", "credit": "3.0",
     "campus": "...", "weeks": "1-16", "teacherList": ["张老师"],
     "arrangeList": [{"name": "...", "location": "23楼404", "weekday": 2,
                      "weekList": [1, 3, 5], "unitList": [9, 11],
                      "teacherList": [...]}]}

This module fetches that payload and rewrites it into the ``v1/classtable``
shape that :func:`app.connectors.tju_api.parse_classtable` consumes, so the
existing import -> timeline pipeline is reused unchanged.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

ENDPOINT = "https://learning.twt.edu.cn/get_classes"
SOURCE = "jw"

_RANGE = re.compile(r"(\d+)\s*(?:[-~—－至到]\s*(\d+))?")
_DIGITS = re.compile(r"\d+")
_SPLIT = re.compile(r"[,，、;；/\s]+")


class JwEamsError(Exception):
    """Raised for anything the 教务 endpoint (or its payload) does wrong."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "protocol",
        detail: Optional[str] = None,
        status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.detail = detail
        self.status = status

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": str(self), "detail": self.detail, "status": self.status}


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _int_list(value: Any) -> list[int]:
    """``[1,3,5]`` / ``"1,3,5"`` / ``"1-3周"`` -> ``[1, 3, 5]`` (order kept, deduped)."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        out: list[int] = []
        for item in value:
            num = _as_int(item)
            if num is not None and num not in out:
                out.append(num)
        return out
    out = []
    for num in (int(token) for token in _DIGITS.findall(str(value))):
        if num not in out:
            out.append(num)
    return out


def parse_week_span(value: Any) -> tuple[Optional[int], Optional[int]]:
    """``"1-16周"`` -> ``(1, 16)``; ``"3"`` -> ``(3, 3)``; ``"1,3,5-9"`` -> ``(1, 9)``."""
    weeks = _int_list(value)
    if not weeks:
        return None, None
    return min(weeks), max(weeks)


def _row_iter(payload: Any) -> list[dict[str, Any]]:
    """Pull the course objects out of whatever bucket the backend used."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    courses = data.get("courses")
    rows: list[dict[str, Any]] = []
    if isinstance(courses, dict):
        for key in ("major", "minor"):  # the official client's two buckets
            bucket = courses.get(key)
            if isinstance(bucket, list):
                rows.extend(row for row in bucket if isinstance(row, dict))
        if not rows:  # tolerate any other bucket name
            for bucket in courses.values():
                if isinstance(bucket, list):
                    rows.extend(row for row in bucket if isinstance(row, dict))
    elif isinstance(courses, list):
        rows = [row for row in courses if isinstance(row, dict)]
    elif isinstance(data.get("data"), list):
        rows = [row for row in data["data"] if isinstance(row, dict)]
    return rows


def _teacher_names(row: dict[str, Any]) -> list[str]:
    raw = row.get("teacherList") or row.get("teachers") or row.get("teacher") or []
    if isinstance(raw, str):
        raw = [part for part in _SPLIT.split(raw) if part]
    names: list[str] = []
    for item in raw if isinstance(raw, (list, tuple, set)) else [raw]:
        name = _text(item)
        if name and name not in names:
            names.append(name)
    return names


def _slot(raw: dict[str, Any], weeks_text: str) -> Optional[dict[str, Any]]:
    """One ``arrangeList`` entry -> one ``v1/classtable`` slot."""
    day = _as_int(raw.get("weekday") or raw.get("day") or raw.get("dayOfWeek") or raw.get("xqj"))
    units = raw.get("unitList") or raw.get("units") or raw.get("sections") or []
    if isinstance(units, str):
        units = _int_list(units)
    has_units = isinstance(units, (list, tuple)) and len(units) > 0
    start = _as_int(units[0]) if has_units else _as_int(raw.get("start") or raw.get("startSection"))
    if has_units and len(units) >= 2:
        end = _as_int(units[-1])
    else:
        end = _as_int(raw.get("end") or raw.get("endSection"), start)
    if day is None or not 1 <= day <= 7 or not start or not end:
        return None
    week_list = _int_list(raw.get("weekList") or raw.get("weeks"))
    return {
        "day": day,
        "start": start,
        "end": end,
        "room": _text(raw.get("location") or raw.get("room") or raw.get("roomName")) or None,
        # an explicit week list is exact; otherwise hand over the course's
        # "1-16"/"单周" text and let parse_classtable work out the parity.
        "week": week_list or weeks_text or None,
    }


def convert_classtable(
    payload: Any,
    *,
    term: str = "",
    week: Any = None,
    term_start: Any = None,
) -> dict[str, Any]:
    """Rewrite a ``get_classes`` payload into the ``v1/classtable`` shape."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise JwEamsError("教务返回的不是 JSON 对象", detail=str(payload)[:200])

    rows = _row_iter(payload)
    if not rows:
        raise JwEamsError(
            "教务返回里没有课程（学期可能还没开始，或接口结构变了）",
            kind="empty",
            detail=json.dumps(shape_report(payload), ensure_ascii=False),
        )

    courses: list[dict[str, Any]] = []
    for row in rows:
        name = _text(row.get("name") or row.get("courseName") or row.get("coursename"))
        if not name:
            continue
        teacher = "、".join(_teacher_names(row)) or None
        weeks_text = _text(row.get("weeks") or row.get("weekStr") or row.get("week"))
        span_start, span_end = parse_week_span(weeks_text)
        arranges = row.get("arrangeList") or row.get("arrange") or row.get("arranges") or []
        if isinstance(arranges, dict):
            arranges = [arranges]
        if not isinstance(arranges, list):
            continue
        for raw_slot in arranges:
            if not isinstance(raw_slot, dict):
                continue
            slot = _slot(raw_slot, weeks_text)
            if slot is None:
                continue
            course: dict[str, Any] = {"coursename": name, "teacher": teacher, "arrange": [slot]}
            if span_start and span_end:
                course["week"] = {"start": span_start, "end": span_end}
            credit = _text(row.get("credit"))
            if credit:
                course["credit"] = credit
            campus = _text(row.get("campus"))
            if campus:
                course["campus"] = campus
            courses.append(course)

    if not courses:
        raise JwEamsError(
            "解析不出任何时段（周次/星期/节次缺失）",
            detail=json.dumps(shape_report(payload), ensure_ascii=False),
        )

    return {
        "error_code": -1,
        "message": "",
        "data": {
            "term": term or "",
            "week": _as_int(week),
            "term_start": term_start,
            "data": courses,
        },
    }


def _deep_first(node: Any, keys: tuple[str, ...], depth: int = 0) -> Any:
    """First value found for any of ``keys`` (case-insensitive) in a nested dict."""
    if depth > 3 or not isinstance(node, dict):
        return None
    wanted = {key.lower() for key in keys}
    for key, value in node.items():
        if str(key).lower() in wanted and value not in (None, "", [], {}):
            return value
    for value in node.values():
        found = _deep_first(value, keys, depth + 1)
        if found is not None:
            return found
    return None


def shape_report(payload: Any) -> dict[str, Any]:
    """Small structural summary — enough to fix a mapping without dumping data."""
    report: dict[str, Any] = {"type": type(payload).__name__}
    if not isinstance(payload, dict):
        return report
    report["top_keys"] = sorted(str(key) for key in payload)[:40]
    report["code"] = payload.get("code")
    data = payload.get("data")
    report["data_type"] = type(data).__name__
    if isinstance(data, str):
        report["message"] = _text(data)[:200]
    if isinstance(data, dict):
        report["data_keys"] = sorted(str(key) for key in data)[:40]
        courses = data.get("courses")
        if isinstance(courses, dict):
            report["buckets"] = {
                str(key): (len(value) if isinstance(value, list) else type(value).__name__)
                for key, value in courses.items()
            }
    rows = _row_iter(payload)
    report["course_count"] = len(rows)
    if rows:
        first = rows[0]
        report["course_keys"] = sorted(str(key) for key in first)[:30]
        report["sample_course"] = {
            key: first.get(key) for key in ("name", "weeks", "credit", "campus") if first.get(key) is not None
        }
        arranges = first.get("arrangeList") or first.get("arrange") or []
        if isinstance(arranges, list) and arranges and isinstance(arranges[0], dict):
            report["arrange_keys"] = sorted(str(key) for key in arranges[0])[:30]
            report["sample_arrange"] = {
                key: arranges[0].get(key)
                for key in ("weekday", "unitList", "weekList", "location", "name")
                if arranges[0].get(key) is not None
            }
    return report


def _to_epoch(value: Any) -> Optional[int]:
    """Epoch seconds/ms or an ISO-ish date -> epoch seconds."""
    if value in (None, ""):
        return None
    number = _as_int(value)
    if number:
        return number // 1000 if number > 10**11 else number
    text = _text(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            stamp = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        return int(stamp.replace(tzinfo=timezone(timedelta(hours=8))).timestamp())
    return None


def discover(payload: dict[str, Any]) -> dict[str, Any]:
    """Best-effort semester metadata for the converted payload (term / week 1)."""
    return {
        "term": _text(_deep_first(payload, ("term", "termCode", "termName", "semester", "xq"))),
        "week": _as_int(_deep_first(payload, ("week", "weekNum", "currentWeek", "nowWeek", "zc"))),
        "term_start": _to_epoch(
            _deep_first(payload, ("termStart", "term_start", "startDate", "start_date", "startTime", "xqStart"))
        ),
    }


async def fetch_classes(
    username: str,
    password: str,
    *,
    timeout: float = 30.0,
    endpoint: str = ENDPOINT,
) -> dict[str, Any]:
    """POST office-network credentials to the 教务 endpoint; return the raw JSON."""
    username = _text(username)
    if not username or not password:
        raise JwEamsError("请填写教务账号（学号）和办公网密码", kind="auth_required")

    headers = {
        "User-Agent": "campushub-sync/1.0 (+timetable-import)",
        "Accept": "application/json, text/plain, */*",
    }
    # The official client sends multipart form data (dio FormData), so do the same.
    files = {"username": (None, username), "passwd": (None, password)}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.post(endpoint, files=files)
    except httpx.HTTPError as exc:
        raise JwEamsError(f"连接教务接口失败：{exc}", kind="network", detail=str(exc)[:300]) from exc

    if response.status_code >= 400:
        raise JwEamsError(
            f"教务接口返回 HTTP {response.status_code}",
            kind="protocol",
            status=response.status_code,
            detail=response.text[:300],
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise JwEamsError(
            "教务接口没有返回 JSON（可能需要校园网，或接口已经改了）",
            kind="protocol",
            detail=response.text[:300],
        ) from exc

    code = _as_int(payload.get("code")) if isinstance(payload, dict) else None
    if code != 200:
        raw_message = payload.get("data") if isinstance(payload.get("data"), str) else payload.get("message")
        hint = _text(raw_message) or "未知错误"
        auth_words = ("密码", "账号", "帐号", "登录", "用户", "凭证")
        raise JwEamsError(
            f"教务接口拒绝了这次登录：{hint}",
            kind="auth_required" if any(word in hint for word in auth_words) else "protocol",
            detail=json.dumps(payload, ensure_ascii=False)[:300],
        )
    return payload
