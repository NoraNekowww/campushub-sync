"""TJU / WePeiyang (微北洋) API client and class-table parser.

Two upstreams exist and they behave very differently. Both facts below were
verified against the live service and cross-checked against the official
client's source (``twtstudio/WePeiYang-Android``):

``open.twt.edu.cn/api`` — the current "open platform".
    Requests must carry a signature built from a public app key:
    ``sign = SHA1(APP_KEY + "".join(name + value for sorted params) + APP_SECRET).upper()``
    together with ``t`` (unix ms) and ``app_key``. The host is reachable **only
    from the campus network**: from anywhere else it answers
    ``302 -> http://network-notice.tju.edu.cn/`` whose body says
    "该网页目前只允许校内访问". So a server outside the campus can *never* pull the
    timetable — a campus-side client (the PWA running in the student's own
    browser) has to do it.

``api.twt.edu.cn`` — the legacy REST API. Globally reachable, but the only
    useful route left is auth (``POST /api/auth/common``), and it requires the
    client-identity headers the official app sends (``ticket`` + ``domain``).
    Without them the gateway answers ``50003 未绑定的url``; with them a bad
    login answers ``40004 用户名或密码错误``.

Nothing in this module writes to disk: callers decide what to persist.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

import httpx

from ..config import Settings, get_settings
from ..timeutil import get_tz
from .base import ConnectorError
from .tju_schedule import (
    CLASSTABLE_KEY,
    IMPORT_META_KEY,
    TERM_START_KEY,
    TOKEN_KEY,
    ClassEntry,
)

log = logging.getLogger("campushub.connectors.tju")

# --------------------------------------------------------------- client identity
# Public constants taken from the official open-source Android client
# (WePeiYang/commons/.../network/ServiceFactory.kt, auth/.../HeaderInterceptor.kt).
OPEN_BASE = "https://open.twt.edu.cn/api"
LEGACY_BASE = "https://api.twt.edu.cn"
APP_KEY = "9GTdynvrCm1EKKFfVmTC"
APP_SECRET = "1aVhfAYBFUfqrdlcT621d9d6OzahMI"
CLIENT_TICKET = "YmFuYW5hLjM3YjU5MDA2M2Q1OTM3MTY0MDVhMmM1YTM4MmIxMTMwYjI4YmY4YTc="
CLIENT_DOMAIN = "weipeiyang.twt.edu.cn"
CLIENT_UA = "WePeiYang/3.0.0 (Linux; Android 12)"

CAMPUS_NOTICE = "network-notice.tju.edu.cn"

# KV keys (single source of truth lives in ``tju_schedule``): ``TOKEN_KEY``,
# ``CLASSTABLE_KEY`` (= the stored ``v1/classtable`` payload), ``IMPORT_META_KEY``,
# ``TERM_START_KEY`` and ``MODE_KEY`` are imported above.


# --------------------------------------------------------------------- errors
class TjuApiError(ConnectorError):
    """A TJU API failure with a machine-readable ``kind``.

    ``kind`` is one of ``bad_credentials``, ``campus_network``,
    ``auth_required``, ``protocol`` or ``network`` — the UI maps these onto
    actionable Chinese hints.
    """

    def __init__(self, message: str, kind: str = "protocol", status: Optional[int] = None,
                 detail: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": str(self), "status": self.status, "detail": self.detail}


KIND_MESSAGES: dict[str, str] = {
    "bad_credentials": "账号或密码错误",
    "campus_network": "该接口仅限校园网访问，需要在你自己的设备（校园网内）发起请求",
    "auth_required": "凭据缺失或已失效，请重新登录",
    "protocol": "接口返回了预期之外的内容（可能是接口变更）",
    "network": "网络不可达",
}


# ------------------------------------------------------------------- signature
def sign_params(params: Optional[Mapping[str, Any]] = None) -> dict[str, str]:
    """Return ``params`` plus ``t`` / ``app_key`` / ``sign``.

    Mirrors ``ServiceFactory.ParamsMap.timeStampAndSignature``: every parameter
    (including ``t``) is sorted by name, concatenated as ``name + value`` and
    wrapped in ``APP_KEY ... APP_SECRET``; the digest is uppercase hex SHA-1.
    """
    payload: dict[str, str] = {str(k): "" if v is None else str(v) for k, v in (params or {}).items()}
    payload["t"] = str(int(time.time() * 1000))
    ordered = "".join(name + payload[name] for name in sorted(payload))
    raw = f"{APP_KEY}{ordered}{APP_SECRET}"
    payload["sign"] = hashlib.sha1(raw.encode("utf-8")).hexdigest().upper()
    payload["app_key"] = APP_KEY
    return payload


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype") or head.startswith("<html") or "<html" in head


def _deep_find(payload: Any, keys: Iterable[str], depth: int = 0) -> Optional[str]:
    if depth > 5 or payload is None:
        return None
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _deep_find(value, keys, depth + 1)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload[:5]:
            found = _deep_find(item, keys, depth + 1)
            if found:
                return found
    return None


def _error_message(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        code = payload.get("error_code")
        message = payload.get("message") or payload.get("msg")
        if code is not None and str(code) not in ("-1", "0", "200"):
            return f"error_code={code} {message or ''}".strip()
    return None


# -------------------------------------------------------------------- parsing
@dataclass
class ClasstableImport:
    """Result of parsing a ``v1/classtable`` payload."""

    term: str = ""
    week: Optional[int] = None
    term_start: Optional[date] = None
    updated_at: Optional[str] = None
    entries: list[ClassEntry] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "week": self.week,
            "term_start": self.term_start.isoformat() if self.term_start else None,
            "updated_at": self.updated_at,
            "courses": len({entry.name for entry in self.entries}),
            "slots": len(self.entries),
            "skipped": self.skipped[:10],
        }


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else default


def _parity(spec: Any) -> Optional[str]:
    """``单周`` -> odd, ``双周`` -> even, ``单双周``/``每周`` -> every week."""
    text = str(spec or "").strip()
    if not text:
        return None
    has_odd = "单" in text
    has_even = "双" in text
    if has_odd and has_even:  # "单双周" means *every* week
        return None
    if has_odd:
        return "odd"
    if has_even:
        return "even"
    lowered = text.lower()
    if "odd" in lowered:
        return "odd"
    if "even" in lowered:
        return "even"
    return None


def _weeks_for(start: Optional[int], end: Optional[int], spec: Any, total_weeks: int) -> set[int]:
    low = start or 1
    high = end or total_weeks
    if low > high:
        low, high = high, low
    if isinstance(spec, (list, tuple, set, frozenset)):
        # An explicit week list (the 教务 payload's ``weekList``) is exact: it can
        # skip weeks that a start/end span plus parity cannot express, e.g.
        # ``[1, 3, 5, 9]``. Clamp to the semester.
        explicit = {num for num in (_as_int(item) for item in spec) if num is not None}
        return {week for week in explicit if 1 <= week <= total_weeks}
    weeks = set(range(max(1, low), min(total_weeks, high) + 1))
    parity = _parity(spec)
    if parity == "odd":
        weeks = {w for w in weeks if w % 2 == 1}
    elif parity == "even":
        weeks = {w for w in weeks if w % 2 == 0}
    return weeks


def parse_classtable(payload: Any, total_weeks: int = 16) -> ClasstableImport:
    """Turn a ``v1/classtable`` payload into :class:`ClassEntry` rows.

    Shape (verified against the official client's own test fixtures)::

        {"error_code": -1, "message": "",
         "data": {"term": "17182", "week": 3, "term_start": 1520179200,
                  "updated_at": "2018-03-20 22:04:07",
                  "data": [{"coursename": "...", "teacher": "...",
                            "week": {"start": "1", "end": "16"},
                            "arrange": [{"week": "单双周", "day": "2",
                                         "start": "9", "end": "11",
                                         "room": "23楼404"}], ...}]}}
    """
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise TjuApiError("课表数据不是 JSON 对象", kind="protocol", detail=str(payload)[:200])

    error = _error_message(payload)
    if error:
        kind = "auth_required" if "token" in error.lower() or "登录" in error else "protocol"
        raise TjuApiError(f"课表接口返回错误：{error}", kind=kind, detail=json.dumps(payload, ensure_ascii=False)[:300])

    data = payload.get("data")
    if isinstance(data, list):  # tolerant: bare list of courses
        data = {"data": data}
    if not isinstance(data, dict):
        raise TjuApiError("课表数据缺少 data 字段", kind="protocol", detail=json.dumps(payload, ensure_ascii=False)[:200])

    courses = data.get("data")
    if isinstance(courses, dict):
        courses = [courses]
    if not isinstance(courses, list):
        raise TjuApiError("课表数据里没有课程列表", kind="protocol")

    result = ClasstableImport(
        term=str(data.get("term") or ""),
        week=_as_int(data.get("week")),
        updated_at=str(data.get("updated_at") or "") or None,
    )
    term_start = _as_int(data.get("term_start"))
    if term_start:
        # Unix seconds (the fixtures use 1520179200 == 2018-03-05 00:00 +08:00).
        try:
            stamp = term_start / 1000 if term_start > 10**11 else term_start
            # Rendered in Beijing time: a UTC host would otherwise land on Sunday.
            result.term_start = datetime.fromtimestamp(stamp, tz=get_tz("Asia/Shanghai")).date()
        except (OverflowError, OSError, ValueError):
            result.term_start = None
    if result.term_start is None and result.week:
        # Derive week 1's Monday from "today is week N".
        today = date.today()
        monday_this_week = today - timedelta(days=today.weekday())
        result.term_start = monday_this_week - timedelta(weeks=result.week - 1)

    for raw_course in courses:
        if not isinstance(raw_course, dict):
            continue
        name = str(raw_course.get("coursename") or raw_course.get("name") or "").strip()
        if not name:
            result.skipped.append(str(raw_course)[:80])
            continue
        teacher = str(raw_course.get("teacher") or "").strip() or None
        week_span = raw_course.get("week") if isinstance(raw_course.get("week"), dict) else {}
        span_start = _as_int(week_span.get("start"), 1)
        span_end = _as_int(week_span.get("end"), total_weeks)
        arrange = raw_course.get("arrange") or raw_course.get("arranges") or []
        if isinstance(arrange, dict):
            arrange = [arrange]
        if not isinstance(arrange, list) or not arrange:
            result.skipped.append(f"{name}:没有排课信息")
            continue
        for slot in arrange:
            if not isinstance(slot, dict):
                continue
            weekday = _as_int(slot.get("day") or slot.get("weekday"))
            start_period = _as_int(slot.get("start"))
            end_period = _as_int(slot.get("end"), start_period)
            if weekday is None or not 1 <= weekday <= 7 or not start_period or not end_period:
                result.skipped.append(f"{name}:排课信息不完整 {slot}")
                continue
            weeks = _weeks_for(span_start, span_end, slot.get("week"), total_weeks)
            if not weeks:
                result.skipped.append(f"{name}:周次为空")
                continue
            result.entries.append(
                ClassEntry(
                    name=name,
                    weekday=weekday,
                    start_period=int(start_period),
                    end_period=int(end_period),
                    weeks=weeks,
                    location=str(slot.get("room") or "").strip() or None,
                    teacher=teacher,
                    # 描述里只留老师：地点卡片自己会显示（`location` 字段），学期每周都一样、
                    # 摆进备注只是噪音。用户 2026-10-13 明确：「官方就留老师相关的就行」。
                    description=f"教师：{teacher}" if teacher else None,
                )
            )
    return result


# --------------------------------------------------------------------- client
class TjuApiClient:
    """Async client for both upstreams. Redirects are never followed, so the
    campus-network gate is detectable instead of silently landing on the
    notice page."""

    def __init__(self, settings: Optional[Settings] = None, base: Optional[str] = None,
                 legacy_base: Optional[str] = None, transport: Any = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport  # tests inject an httpx.MockTransport here
        self.base = (base or getattr(self.settings, "tju_open_base", None) or OPEN_BASE).rstrip("/")
        self.legacy_base = (
            legacy_base or getattr(self.settings, "tju_api_base", None) or LEGACY_BASE
        ).rstrip("/")

    # ------------------------------------------------------------- plumbing
    def _headers(self, token: Optional[str] = None, legacy: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": CLIENT_UA}
        if legacy:
            headers["ticket"] = CLIENT_TICKET
            headers["domain"] = CLIENT_DOMAIN
        if token:
            # No space after "Bearer" — that is what the official client sends.
            headers["Authorization"] = f"Bearer{token}"
        return headers

    async def _request(self, method: str, url: str, *, params: Optional[dict] = None,
                       data: Optional[dict] = None, token: Optional[str] = None,
                       legacy: bool = False) -> httpx.Response:
        timeout = httpx.Timeout(self.settings.http_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                        transport=self.transport) as http:
                return await http.request(method, url, params=params, data=data,
                                          headers=self._headers(token, legacy=legacy))
        except httpx.HTTPError as exc:
            raise TjuApiError(f"请求 {url} 失败：{exc}", kind="network") from exc

    def _guard(self, response: httpx.Response, where: str) -> str:
        """Return the body text, or raise a classified :class:`TjuApiError`."""
        location = response.headers.get("location", "")
        body = response.text or ""
        if response.status_code in (301, 302, 303, 307, 308):
            if CAMPUS_NOTICE in location or CAMPUS_NOTICE in body:
                raise TjuApiError(
                    f"{where}：接口把请求重定向到校园网提示页（{location or CAMPUS_NOTICE}）",
                    kind="campus_network", status=response.status_code, detail=location,
                )
            raise TjuApiError(f"{where}：被重定向到 {location}", kind="protocol",
                              status=response.status_code, detail=location)
        if response.status_code in (401, 403):
            if _looks_like_html(body) or "校内访问" in body or "违规操作" in body:
                raise TjuApiError(f"{where}：接口拒绝校外访问（HTTP {response.status_code}）",
                                  kind="campus_network", status=response.status_code,
                                  detail=body[:200])
            raise TjuApiError(f"{where}：凭据被拒绝（HTTP {response.status_code}）",
                              kind="auth_required", status=response.status_code, detail=body[:200])
        if response.status_code >= 500:
            raise TjuApiError(f"{where}：上游错误 HTTP {response.status_code}", kind="network",
                              status=response.status_code, detail=body[:200])
        if _looks_like_html(body) or (body.strip().startswith("<") and "error_code" not in body):
            raise TjuApiError(f"{where}：返回了网页而不是数据（很可能是校园网限制页）",
                              kind="campus_network", status=response.status_code, detail=body[:200])
        return body

    @staticmethod
    def _json(body: str, where: str) -> Any:
        try:
            return json.loads(body) if body.strip() else {}
        except ValueError as exc:
            raise TjuApiError(f"{where}：响应不是合法 JSON", kind="protocol",
                              detail=body[:200]) from exc

    # --------------------------------------------------------------- login
    async def login_open(self, username: str, password: str) -> str:
        """Log in through the open platform (``v1/auth/token/get``)."""
        params = sign_params({"twtuname": username, "twtpasswd": password})
        response = await self._request("GET", f"{self.base}/v1/auth/token/get", params=params)
        body = self._guard(response, "微北洋登录")
        payload = self._json(body, "微北洋登录")
        error = _error_message(payload)
        if error:
            kind = "bad_credentials" if any(code in error for code in ("30001", "30002", "40004")) else "protocol"
            raise TjuApiError(f"微北洋登录失败：{error}", kind=kind, detail=body[:200])
        token = _deep_find(payload, ("token", "access_token", "jwt"))
        if not token:
            raise TjuApiError("微北洋登录响应里没有 token", kind="protocol", detail=body[:200])
        return token

    async def login_legacy(self, username: str, password: str) -> str:
        """Log in through the legacy API — the only path reachable off-campus."""
        response = await self._request(
            "POST",
            f"{self.legacy_base}/api/auth/common",
            data={"account": username, "password": password},
            legacy=True,
        )
        body = self._guard(response, "微北洋登录（旧接口）")
        payload = self._json(body, "微北洋登录（旧接口）")
        message = str(payload.get("message") or "")
        if str(payload.get("error_code")) in ("-1", "0"):
            token = _deep_find(payload, ("token", "access_token", "jwt", "tokenId"))
            if token:
                return token
            raise TjuApiError("旧接口登录成功但响应里没有 token", kind="protocol", detail=body[:200])
        # Wrong password, unknown account, unknown account *class* — all of these
        # are credential problems, not protocol surprises.
        if str(payload.get("error_code")) in ("40004", "30001", "30002") or any(
            hint in message for hint in ("密码", "不存在", "帐号", "账号", "用户")
        ):
            raise TjuApiError(f"登录被拒绝：{message or payload.get('error_code')}",
                              kind="bad_credentials", detail=body[:200])
        if "未绑定的" in message or "50003" in f"{payload.get('error_code')}":
            raise TjuApiError(f"旧接口未放行该请求：{message}", kind="protocol", detail=body[:200])
        raise TjuApiError(f"登录失败：{message or payload.get('error_code')}", kind="protocol",
                          detail=body[:200])

    async def login(self, username: str, password: str) -> tuple[str, str]:
        """Try the open platform first (campus only), then the legacy API.

        Returns ``(token, source)``.
        """
        try:
            return await self.login_open(username, password), "open"
        except TjuApiError as exc:
            log.info("tju: open-platform login unavailable (%s: %s); falling back to legacy API",
                     exc.kind, exc)
            if exc.kind == "bad_credentials":
                raise
        return await self.login_legacy(username, password), "legacy"

    async def verify_token(self, token: str) -> dict[str, Any]:
        """Check a token against the legacy API (reachable from anywhere)."""
        response = await self._request("GET", f"{self.legacy_base}/api/user/single", token=token, legacy=True)
        body = self._guard(response, "令牌校验")
        payload = self._json(body, "令牌校验")
        error = _error_message(payload)
        if error and "40001" in error:
            raise TjuApiError("令牌无效或已过期", kind="auth_required", detail=body[:200])
        if error:
            raise TjuApiError(f"令牌校验失败：{error}", kind="protocol", detail=body[:200])
        data = payload.get("data") if isinstance(payload, dict) else None
        user = data if isinstance(data, dict) else {}
        return {
            "ok": True,
            "name": str(user.get("realname") or user.get("nickname") or user.get("username") or ""),
            "raw": json.dumps(user, ensure_ascii=False)[:400],
        }

    # ----------------------------------------------------------- class table
    async def fetch_classtable(self, token: str) -> Any:
        params = sign_params({})
        response = await self._request("GET", f"{self.base}/v1/classtable", params=params, token=token)
        body = self._guard(response, "课表接口")
        payload = self._json(body, "课表接口")
        error = _error_message(payload)
        if error:
            kind = "auth_required" if "token" in error.lower() or "登录" in error else "protocol"
            raise TjuApiError(f"课表接口返回错误：{error}", kind=kind, detail=body[:200])
        return payload

    async def fetch_examtable(self, token: str) -> Any:
        params = sign_params({})
        response = await self._request("GET", f"{self.base}/v1/examtable", params=params, token=token)
        return self._json(self._guard(response, "考试接口"), "考试接口")

    async def probe(self) -> dict[str, Any]:
        """Campus-network reachability check (no token needed to see the gate)."""
        try:
            params = sign_params({})
            response = await self._request("GET", f"{self.base}/v1/classtable", params=params)
            body = self._guard(response, "课表接口")
            payload = self._json(body, "课表接口")
            error = _error_message(payload) or ""
            if "token" in error.lower() or "登录" in error:
                return {"reachable": True, "campus": True, "note": "可达，但需要 token"}
            return {"reachable": True, "campus": True, "note": error or "可达"}
        except TjuApiError as exc:
            return {"reachable": exc.kind != "campus_network", "campus": exc.kind != "campus_network",
                    "kind": exc.kind, "note": KIND_MESSAGES.get(exc.kind, str(exc))}
