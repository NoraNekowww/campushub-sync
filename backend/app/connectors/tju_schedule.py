"""Tianjin University academic schedule connector.

Two intake paths, per the design brief:

1. **WePeiyang (微北洋 / TWT) API** — ``TJU_MODE=wepeiyang``. Either reuse a
   captured access token (``TJU_ACCESS_TOKEN``) or log in with
   ``TJU_USERNAME``/``TJU_PASSWORD``. *The endpoint paths and JSON field names
   are configuration, not constants*: TJU's private API is undocumented and
   changes between client releases, so every field is looked up through an
   alias table (:data:`FIELD_ALIASES`) instead of being hard-coded. Treat the
   live-API path as unverified until you have run it against your own token.
2. **ICS / static table fallback** — ``TJU_MODE=ics``. Parses an ``.ics``
   exported from any calendar app (or uploaded through
   ``POST /api/schedule/upload``) and expands weekly recurrences itself. This
   path is fully deterministic and is the recommended setup.

Both paths converge on :class:`ClassEntry` / :class:`RawEvent` and produce the
same unified :class:`~app.models.Event` objects.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Optional

from ..db import KVStore
from ..models import Event, Source, make_event_id
from ..timeutil import UTC, as_aware, as_stored, get_tz, utcnow
from .base import AuthRequiredError, ConnectorError, FetchResult, HttpConnector

log = logging.getLogger("campushub.connectors.tju")

ICS_CONTENT_KEY = "tju.ics_content"
ICS_FILENAME_KEY = "tju.ics_filename"
TOKEN_KEY = "tju.token"
SEMESTER_KEY = "tju.semester"
#: Raw ``v1/classtable`` payload imported from the web UI (campus-side fetch).
CLASSTABLE_KEY = "tju.classtable"
IMPORT_META_KEY = "tju.import_meta"
#: Week-1 Monday taken from the API's own ``term_start`` — the real one.
TERM_START_KEY = "tju.term_start"
#: Runtime override for ``TJU_MODE`` so the UI can switch modes without a restart.
MODE_KEY = "tju.mode"

#: Official TJU period slots (卫津路 / 北洋园 share these wall-clock times).
#: 晚上连着上、不设课间：9-10 节合起来正好 18:30–20:00。以前写成 18:00–19:35，
#: 整段早了半小时（2026-10-13 用户对着教务课表指出来的：「51单片机 18:30-20:00，
#: 你写的是 18:00-19:30」）。11-12 节按同样的 45 分钟节奏顺延。
PERIOD_TIMES: dict[int, tuple[str, str]] = {
    1: ("08:30", "09:15"),
    2: ("09:20", "10:05"),
    3: ("10:25", "11:10"),
    4: ("11:15", "12:00"),
    5: ("13:30", "14:15"),
    6: ("14:20", "15:05"),
    7: ("15:25", "16:10"),
    8: ("16:15", "17:00"),
    9: ("18:30", "19:15"),
    10: ("19:15", "20:00"),
    11: ("20:10", "20:55"),
    12: ("20:55", "21:40"),
}

#: Alias table for the private WePeiyang payload — first match wins.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("courseName", "course_name", "name", "course", "title", "coursename"),
    "teacher": ("teacher", "teacherName", "teacher_name", "instructor", "jsxm"),
    "location": ("place", "location", "classroom", "room", "address", "cdmc"),
    "weekday": ("weekDay", "weekday", "dayOfWeek", "week_day", "day", "xqj"),
    "start_period": (
        "startSection",
        "startNode",
        "beginSection",
        "sectionStart",
        "start_section",
        "start",
        "startnode",
    ),
    "end_period": (
        "endSection",
        "endNode",
        "endPeriod",
        "sectionEnd",
        "end_section",
        "endnode",
    ),
    "sections": ("sections", "section", "jcs", "node"),
    "weeks": ("weekStr", "weeks", "week", "weekList", "week_list", "weekRange", "zcd"),
    "term": ("term", "termId", "semester", "semesterId", "xq", "xqid"),
}

CHINESE_WEEKDAYS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7,
    "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7,
}


# --------------------------------------------------------------------- semester
@dataclass
class Semester:
    name: str = "学期"
    start_date: date = field(default_factory=lambda: date.today())
    total_weeks: int = 16
    holidays: set[date] = field(default_factory=set)
    period_times: dict[int, tuple[str, str]] = field(default_factory=lambda: dict(PERIOD_TIMES))
    tz_name: str = "Asia/Shanghai"

    def __post_init__(self) -> None:
        # Week 1 is defined by its Monday.
        if self.start_date.weekday() != 0:
            self.start_date -= timedelta(days=self.start_date.weekday())

    def monday(self, week: int) -> date:
        return self.start_date + timedelta(weeks=max(1, week) - 1)

    def date_for(self, week: int, weekday: int) -> date:
        """``weekday`` is 1..7 with Monday = 1."""
        return self.monday(week) + timedelta(days=max(1, min(7, weekday)) - 1)

    def week_of(self, day: date) -> int:
        return ((day - self.start_date).days // 7) + 1

    def slot(self, start_period: int, end_period: Optional[int] = None) -> tuple[str, str]:
        end_period = end_period or start_period
        start = self.period_times.get(start_period)
        end = self.period_times.get(end_period)
        if not start or not end:
            raise ConnectorError(f"unknown period {start_period}-{end_period}")
        return start[0], end[1]

    def datetimes(self, week: int, weekday: int, start_period: int, end_period: int) -> tuple[datetime, datetime]:
        day = self.date_for(week, weekday)
        start_hhmm, end_hhmm = self.slot(start_period, end_period)
        tz = get_tz(self.tz_name)

        def at(hhmm: str) -> datetime:
            hour, minute = (int(part) for part in hhmm.split(":")[:2])
            return as_stored(datetime.combine(day, time(hour, minute)), assume=tz)

        return at(start_hhmm), at(end_hhmm)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start_date": self.start_date.isoformat(),
            "total_weeks": self.total_weeks,
            "holidays": sorted(d.isoformat() for d in self.holidays),
            "current_week": max(1, self.week_of(date.today())),
        }


def build_semester(settings, kv: Optional[KVStore] = None) -> Semester:
    """Week-1 date priority: imported ``term_start`` → saved semester → settings.

    The imported date comes straight from the timetable API's own
    ``term_start`` field, so it beats anything typed by hand.
    """
    stored: dict[str, Any] = {}
    imported_start: Any = None
    if kv is not None:
        stored = kv.get(SEMESTER_KEY, {}) or {}
        imported_start = kv.get(TERM_START_KEY)
    start_raw = imported_start or stored.get("start_date") or settings.semester_start_date
    start = date.fromisoformat(str(start_raw)[:10]) if start_raw else date.today()
    holidays: set[date] = set()
    for item in list(stored.get("holidays") or []) + list(settings.holiday_list):
        try:
            holidays.add(date.fromisoformat(str(item)[:10]))
        except ValueError:
            log.warning("tju_schedule: ignoring malformed holiday %r", item)
    return Semester(
        name=str(stored.get("name") or settings.semester_name),
        start_date=start,
        total_weeks=int(stored.get("total_weeks") or settings.semester_total_weeks),
        holidays=holidays,
        period_times=settings.period_times or dict(PERIOD_TIMES),
        tz_name=settings.timezone,
    )


# -------------------------------------------------------------- week parsing
_ODD = ("单周", "单", "odd")
_EVEN = ("双周", "双", "even")


def parse_week_spec(spec: str | Iterable[int] | None, total_weeks: int = 16) -> tuple[set[int], Optional[str]]:
    """Parse ``"1-8,10-16"``, ``"1-16周"``, ``"1-16(单)"``, ``"第1-16周"``.

    Returns ``(weeks, parity)`` where parity is ``"odd"``, ``"even"`` or None.
    """
    if spec is None:
        return set(range(1, total_weeks + 1)), None
    if isinstance(spec, (list, tuple, set)):
        return {int(w) for w in spec if str(w).strip().isdigit()}, None

    text = str(spec).strip()
    parity: Optional[str] = None
    # ``单双周`` / ``单双`` carries both markers and means *every* week, so a
    # marker only counts when the opposite one is absent.
    has_odd = any(marker in text for marker in _ODD)
    has_even = any(marker in text for marker in _EVEN)
    if has_odd and not has_even:
        parity = "odd"
    elif has_even and not has_odd:
        parity = "even"

    weeks: set[int] = set()
    for chunk in re.split(r"[,，、;；\s]+", text):
        if not chunk:
            continue
        for match in re.finditer(r"(\d+)\s*(?:[-~至到]\s*(\d+))?", chunk):
            low = int(match.group(1))
            high = int(match.group(2)) if match.group(2) else low
            if low > high:
                low, high = high, low
            weeks.update(range(max(1, low), min(total_weeks, high) + 1))
    if not weeks:
        weeks = set(range(1, total_weeks + 1))
    if parity == "odd":
        weeks = {w for w in weeks if w % 2 == 1}
    elif parity == "even":
        weeks = {w for w in weeks if w % 2 == 0}
    return weeks, parity


def _parse_period(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value)
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def _parse_weekday(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return 7 if value == 0 else value if 1 <= value <= 7 else None
    text = str(value).strip().lower()
    if text.isdigit():
        number = int(text)
        return 7 if number == 0 else number if 1 <= number <= 7 else None
    for key, number in CHINESE_WEEKDAYS.items():
        if key in text:
            return number
    return None


# ------------------------------------------------------------------- entries
@dataclass
class ClassEntry:
    """One weekly class slot (course × weekday × periods × week set)."""

    name: str
    weekday: int
    start_period: int
    end_period: int
    weeks: set[int] = field(default_factory=set)
    location: Optional[str] = None
    teacher: Optional[str] = None
    description: Optional[str] = None

    def to_events(
        self,
        semester: Semester,
        now: Optional[datetime] = None,
        horizon_days: int = 120,
        past_days: int = 1,
    ) -> list[Event]:
        now = as_aware(now) or utcnow()
        horizon = now + timedelta(days=horizon_days)
        floor = now - timedelta(days=past_days)
        events: list[Event] = []
        for week in sorted(self.weeks):
            try:
                start, end = semester.datetimes(week, self.weekday, self.start_period, self.end_period)
            except ConnectorError:
                continue
            if start.date() in semester.holidays:
                continue
            start_aware = as_aware(start)
            if start_aware is None or start_aware > horizon or (end and as_aware(end) < floor):
                continue
            # id 里放**周次**而不是日期：学期锚点一旦修正（比如教务周次换算改了），
            # 日期会变而周次不变 ⇒ 同一行被就地改期，不会留下一份旧日期的孤儿行；
            # 用户划掉/删掉（hidden）和被本地改过的标记也因此能跟着走，不会"复活"。
            source_id = (
                f"{semester.name}:{self.name}:w{week}"
                f":p{self.start_period}-{self.end_period}:{self.location or ''}"
            )
            events.append(
                Event(
                    id=make_event_id(Source.tju_schedule, source_id),
                    source=Source.tju_schedule.value,
                    source_id=source_id,
                    title=self.name,
                    description=self.description
                    or " ".join(filter(None, [self.teacher and f"教师：{self.teacher}"])),
                    start_time=start,
                    end_time=end,
                    is_deadline=False,
                    location=self.location,
                    status="pending",
                    priority=5,
                    updated_at=now,
                    raw=json.dumps(
                        {
                            "week": week,
                            "weekday": self.weekday,
                            "periods": [self.start_period, self.end_period],
                            "teacher": self.teacher,
                            "semester": semester.name,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        return events


# ---------------------------------------------------------------- ICS parsing
@dataclass
class RawEvent:
    summary: str
    start: datetime  # naive local (wall clock as written in the file)
    end: Optional[datetime] = None
    location: Optional[str] = None
    description: Optional[str] = None
    uid: Optional[str] = None
    rrule: Optional[dict[str, Any]] = None


def parse_ics(content: bytes | str) -> list[RawEvent]:
    """Parse an ``.ics`` blob into :class:`RawEvent` items (RFC 5545)."""
    from icalendar import Calendar

    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    try:
        calendar = Calendar.from_ical(text)
    except Exception as exc:
        raise ConnectorError(f"tju_schedule: cannot parse ICS — {exc}") from exc

    raw_events: list[RawEvent] = []
    for component in calendar.walk("VEVENT"):
        summary = str(component.get("SUMMARY") or "").strip()
        if not summary:
            continue
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        start = dtstart.dt
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime.combine(start, time(8, 30))
        dtend = component.get("DTEND")
        end = dtend.dt if dtend is not None else None
        if isinstance(end, date) and not isinstance(end, datetime):
            end = datetime.combine(end, time(10, 5))
        if end is None and component.get("DURATION") is not None:
            end = start + component.get("DURATION").dt
        rrule = component.get("RRULE")
        raw_events.append(
            RawEvent(
                summary=summary,
                start=start.replace(tzinfo=None),
                end=end.replace(tzinfo=None) if end else None,
                location=str(component.get("LOCATION") or "").strip() or None,
                description=str(component.get("DESCRIPTION") or "").strip() or None,
                uid=str(component.get("UID") or "").strip() or None,
                rrule=dict(rrule) if rrule is not None else None,
            )
        )
    if not raw_events:
        log.warning("tju_schedule: ICS contained no usable VEVENT")
    return raw_events


def expand_raw(
    raw: RawEvent,
    tz_name: str = "Asia/Shanghai",
    horizon_days: int = 120,
    past_days: int = 1,
    semester_name: str = "",
) -> list[Event]:
    """Materialise a parsed ICS event, expanding simple weekly/daily RRULEs."""
    tz = get_tz(tz_name)
    now = utcnow()
    horizon = now + timedelta(days=horizon_days)
    floor = now - timedelta(days=past_days)
    duration = (raw.end - raw.start) if raw.end else None

    starts = _expand_rrule(raw.start, raw.rrule, horizon.astimezone(tz).replace(tzinfo=None), tz)
    events: list[Event] = []
    for index, start_local in enumerate(starts):
        start_utc = as_stored(start_local, assume=tz)
        start_aware = as_aware(start_utc)
        if start_aware is None or start_aware > horizon:
            continue
        if duration and start_aware + duration < floor:
            continue
        end_utc = as_stored(start_local + duration, assume=tz) if duration else None
        uid = raw.uid or f"{raw.summary}:{start_local.isoformat()}"
        if index:
            uid = f"{uid}#{start_local.date().isoformat()}"
        source_id = f"{semester_name}:{uid}"
        events.append(
            Event(
                id=make_event_id(Source.tju_schedule, source_id),
                source=Source.tju_schedule.value,
                source_id=source_id,
                title=raw.summary,
                description=raw.description,
                start_time=start_utc,
                end_time=end_utc,
                is_deadline=False,
                location=raw.location,
                status="pending",
                priority=5,
                updated_at=utcnow(),
                raw=json.dumps({"ics": True, "uid": raw.uid}, ensure_ascii=False),
            )
        )
    return events


def _first(value: Any, default: Any = None) -> Any:
    """icalendar hands RRULE parts back as single-item lists (``vRecur``)."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return default if value is None else value


def _expand_rrule(
    start: datetime, rrule: Optional[dict[str, Any]], horizon_local: datetime, tz
) -> list[datetime]:
    if not rrule:
        return [start]
    freq = str(_first(rrule.get("FREQ"), "") or "").upper()
    interval = max(1, int(_first(rrule.get("INTERVAL"), 1) or 1))
    count = int(_first(rrule.get("COUNT"), 0) or 0) or None
    until = _first(rrule.get("UNTIL"))
    until_local: Optional[datetime] = None
    if until is not None:
        until_value = until
        if isinstance(until_value, datetime):
            until_local = until_value.astimezone(tz).replace(tzinfo=None)
        elif isinstance(until_value, date):
            until_local = datetime.combine(until_value, time(23, 59))

    if freq not in {"DAILY", "WEEKLY", "MONTHLY"}:
        return [start]

    out: list[datetime] = []
    current = start
    limit = 400
    while len(out) < limit:
        if until_local and current > until_local:
            break
        if count and len(out) >= count:
            break
        if current > horizon_local:
            break
        out.append(current)
        if freq == "DAILY":
            current = current + timedelta(days=interval)
        elif freq == "WEEKLY":
            current = current + timedelta(weeks=interval)
        else:
            current = _add_months(current, interval)
    return out or [start]


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    import calendar as _calendar

    day = min(value.day, _calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


# --------------------------------------------------------------- WePeiyang
class WePeiyangClient(HttpConnector):
    """Thin client for TJU's private TWT/WePeiyang endpoints (best effort)."""

    name = "tju_wepeiyang"

    def __init__(self, settings=None, store: Optional[KVStore] = None) -> None:
        super().__init__(settings)
        self.store = store or KVStore()

    @property
    def enabled(self) -> bool:
        return True  # the parent connector decides whether it is used

    def _token_from_store(self) -> Optional[str]:
        token = self.store.get(TOKEN_KEY) or {}
        return token.get("access_token") or self.settings.tju_access_token

    async def login(self, username: str, password: str) -> str:
        payload = await self.request_json(
            "POST",
            f"{self.settings.tju_api_base.rstrip('/')}{self.settings.tju_login_path}",
            json={"username": username, "password": password, "telnumber": username},
            accept_status=(200, 201),
        )
        token = _deep_find(payload, ("token", "accessToken", "access_token", "tokenId", "jwt"))
        if not token:
            raise AuthRequiredError(
                "tju_schedule: login response contained no token — check TJU_LOGIN_PATH "
                "and credentials"
            )
        self.store.set(TOKEN_KEY, {"access_token": token, "obtained_at": utcnow().isoformat()})
        return token

    async def fetch_raw(self) -> list[dict[str, Any]]:
        token = self._token_from_store()
        if not token:
            if self.settings.tju_username and self.settings.tju_password:
                token = await self.login(self.settings.tju_username, self.settings.tju_password)
            else:
                raise AuthRequiredError(
                    "tju_schedule: no access token — set TJU_ACCESS_TOKEN or "
                    "TJU_USERNAME/TJU_PASSWORD"
                )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        payload = await self.request_json(
            "GET",
            f"{self.settings.tju_api_base.rstrip('/')}{self.settings.tju_schedule_path}",
            headers=headers,
            params={"week": "", "term": "", "type": 1},
        )
        items = _extract_items(payload)
        if not items:
            raise ConnectorError(
                "tju_schedule: schedule response contained no rows — the field map in "
                "connectors/tju_schedule.py may need updating for your API version"
            )
        return items

    @staticmethod
    def map_items(items: Iterable[dict[str, Any]], semester: Semester) -> list[ClassEntry]:
        entries: list[ClassEntry] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Some payloads nest the real row one level down.
            row: dict[str, Any] = item
            for key in ("course", "detail", "scheduleCell", "data"):
                if isinstance(item.get(key), dict):
                    row = {**item, **item[key]}
                    break
            name = _pick(row, "name")
            weekday = _parse_weekday(_pick(row, "weekday"))
            if not name or weekday is None:
                continue
            start_period = _parse_period(_pick(row, "start_period"))
            end_period = _parse_period(_pick(row, "end_period"))
            sections = _pick(row, "sections")
            if start_period is None and sections:
                parts = re.findall(r"\d+", str(sections))
                start_period = int(parts[0]) if parts else None
                end_period = end_period or (int(parts[-1]) if len(parts) > 1 else start_period)
            if start_period is None:
                continue
            end_period = end_period or start_period
            weeks, _ = parse_week_spec(_pick(row, "weeks"), semester.total_weeks)
            entries.append(
                ClassEntry(
                    name=str(name).strip(),
                    weekday=weekday,
                    start_period=start_period,
                    end_period=end_period,
                    weeks=weeks,
                    location=_string_or_none(_pick(row, "location")),
                    teacher=_string_or_none(_pick(row, "teacher")),
                )
            )
        return entries


def _pick(row: dict[str, Any], kind: str) -> Any:
    for alias in FIELD_ALIASES.get(kind, ()):
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    lowered = {str(key).lower(): value for key, value in row.items()}
    for alias in FIELD_ALIASES.get(kind, ()):
        if alias.lower() in lowered and lowered[alias.lower()] not in (None, ""):
            return lowered[alias.lower()]
    return None


def _string_or_none(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "result", "list", "items", "rows", "schedule"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _extract_items(value)
                if nested:
                    return nested
        # Data keyed by week or weekday: {"1": [...], "2": [...]}
        collected: list[dict[str, Any]] = []
        for value in payload.values():
            if isinstance(value, list):
                collected.extend(item for item in value if isinstance(item, dict))
        return collected
    return []


def _deep_find(payload: Any, keys: tuple[str, ...], depth: int = 0) -> Optional[str]:
    if depth > 4 or payload is None:
        return None
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), str) and payload[key]:
                return payload[key]
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


# ----------------------------------------------------------------- connector
class TjuScheduleConnector(HttpConnector):
    name = "tju_schedule"

    #: 这份抓取就是整学期课表的全集 → 允许同步删掉「本次没再出现」的旧事件
    #: （改学期锚点会让整张课表换日期；不清理就会和旧行并排显示，看起来像重复课）
    reconciles = "tju_schedule"
    label = "天津大学课表"

    def __init__(self, settings=None, store: Optional[KVStore] = None) -> None:
        super().__init__(settings)
        self.store = store or KVStore()
        self.semester = build_semester(self.settings, self.store)

    @property
    def enabled(self) -> bool:
        """A stored override (the web UI sets it after an import) also enables it.

        Without this the sync engine would skip TJU entirely while ``TJU_MODE``
        in ``.env`` still says ``disabled`` — and the imported table would never
        reach the timeline.
        """
        override = self.store.get(MODE_KEY)
        if isinstance(override, str) and override.strip():
            return override.strip().lower() not in ("", "disabled", "off", "none")
        return self.settings.tju_enabled

    @property
    def mode(self) -> str:
        """A stored override (set by the web UI after an import) wins over env."""
        override = self.store.get(MODE_KEY)
        if isinstance(override, str) and override.strip():
            return override.strip().lower()
        return (self.settings.tju_mode or "disabled").strip().lower()

    def _ics_content(self) -> tuple[bytes, str]:
        content = self.store.get(ICS_CONTENT_KEY)
        if content:
            return content.encode("utf-8"), str(self.store.get(ICS_FILENAME_KEY) or "uploaded.ics")
        if self.settings.tju_ics_path:
            path = self.settings.resolve_data_path(self.settings.tju_ics_path)
            if path.exists():
                return path.read_bytes(), path.name
            raise ConnectorError(f"tju_schedule: ICS file not found at {path}")
        raise ConnectorError(
            "tju_schedule: no ICS source — upload one via POST /api/schedule/upload "
            "or set TJU_ICS_PATH"
        )

    async def fetch(self) -> FetchResult:
        mode = self.mode
        if mode == "ics":
            content, filename = self._ics_content()
            raws = parse_ics(content)
            events: list[Event] = []
            for raw in raws:
                events.extend(
                    expand_raw(
                        raw,
                        tz_name=self.settings.timezone,
                        horizon_days=self.settings.horizon_days,
                        semester_name=self.semester.name,
                    )
                )
            return FetchResult(
                events=events,
                detail={"mode": mode, "file": filename, "raw_events": len(raws), "events": len(events)},
            )

        if mode == "wepeiyang":
            client = WePeiyangClient(settings=self.settings, store=self.store)
            items = await client.fetch_raw()
            entries = client.map_items(items, self.semester)
            events = [event for entry in entries for event in entry.to_events(
                self.semester, horizon_days=self.settings.horizon_days
            )]
            return FetchResult(
                events=events,
                detail={"mode": mode, "rows": len(items), "courses": len(entries), "events": len(events)},
            )

        if mode == "imported":
            return self._imported_result()

        raise ConnectorError(f"tju_schedule: unsupported TJU_MODE={mode!r}")

    async def status(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "enabled": self.enabled,
            "mode": self.mode,
            "semester": self.semester.summary(),
        }
        if self.mode == "wepeiyang":
            client = WePeiyangClient(settings=self.settings, store=self.store)
            state["has_token"] = bool(client._token_from_store())
        if self.mode == "ics":
            stored = bool(self.store.get(ICS_CONTENT_KEY))
            path = self.settings.resolve_data_path(self.settings.tju_ics_path) if self.settings.tju_ics_path else None
            state["source"] = (
                f"upload:{self.store.get(ICS_FILENAME_KEY)}"
                if stored
                else (str(path) if path and path.exists() else None)
            )
        state["credentials"] = self.token_info()
        state["import_meta"] = self.import_meta()
        return state

    # ------------------------------------------------------------- credentials
    def stored_token(self) -> Optional[str]:
        data = self.store.get(TOKEN_KEY) or {}
        if isinstance(data, dict):
            return data.get("access_token") or data.get("token")
        return data if isinstance(data, str) else None

    def store_token(self, token: str, source: str = "", account: str = "") -> dict[str, Any]:
        payload = {
            "access_token": token,
            "source": source,
            "account": account,
            "obtained_at": utcnow().isoformat(),
        }
        self.store.set(TOKEN_KEY, payload)
        return self.token_info()

    def token_info(self) -> dict[str, Any]:
        data = self.store.get(TOKEN_KEY)
        data = data if isinstance(data, dict) else {}
        token = self.stored_token() or ""
        return {
            "has_token": bool(token),
            "account": str(data.get("account") or ""),
            "source": str(data.get("source") or ""),
            "obtained_at": str(data.get("obtained_at") or ""),
            "token_hint": f"…{token[-6:]}" if len(token) > 8 else ("已设置" if token else ""),
        }

    def clear_token(self) -> None:
        self.store.delete(TOKEN_KEY)

    # --------------------------------------------------------- class-table import
    def store_classtable(self, payload: Any, source: str = "web",
                         total_weeks: Optional[int] = None) -> dict[str, Any]:
        """Persist a ``v1/classtable`` payload and point ``TJU_MODE`` at it."""
        from .tju_api import parse_classtable

        used_weeks = int(total_weeks) if total_weeks else int(self.semester.total_weeks)
        held = self.store.get(SEMESTER_KEY)
        held = dict(held) if isinstance(held, dict) else {}
        if total_weeks and int(held.get("total_weeks") or 0) != used_weeks:
            # 真实课表可能比设置里的周数长（课表排到第 20 周，设置默认是 16）：
            # 先把总周数落库并重建，否则 parse_classtable 会把多出来的那几周静默截掉。
            held["total_weeks"] = used_weeks
            self.store.set(SEMESTER_KEY, held)
            self.semester = build_semester(self.settings, self.store)
        parsed = parse_classtable(payload, used_weeks)
        self.store.set(CLASSTABLE_KEY, payload)
        if parsed.term_start:
            self.store.set(TERM_START_KEY, parsed.term_start.isoformat())
        # 学期锚点也写回「设置」：以前只写总周数，设置里那个手填/遗留的 start_date
        # （线上实测是个周五 2026-07-31）会继续被界面当成「第 1 周周一」，
        # 于是界面上显示的周次和课程真实日期差好几周（显示第 11 周、其实是第 6 周 ⇒ 单双周反了）。
        anchor = parsed.term_start.isoformat() if parsed.term_start else None
        if anchor and held.get("start_date") != anchor:
            held["start_date"] = anchor
        if not held.get("name") and parsed.term:
            held["name"] = parsed.term
        self.store.set(SEMESTER_KEY, held)
        meta = {**parsed.summary(), "source": source, "imported_at": utcnow().isoformat()}
        self.store.set(IMPORT_META_KEY, meta)
        self.store.set(MODE_KEY, "imported")
        # Week 1 now comes from the API's own term_start.
        self.semester = build_semester(self.settings, self.store)
        return meta

    def import_meta(self) -> dict[str, Any]:
        meta = self.store.get(IMPORT_META_KEY)
        return meta if isinstance(meta, dict) else {}

    def clear_classtable(self) -> None:
        for key in (CLASSTABLE_KEY, IMPORT_META_KEY, TERM_START_KEY, MODE_KEY):
            self.store.delete(key)
        self.semester = build_semester(self.settings, self.store)

    def _imported_result(self) -> FetchResult:
        payload = self.store.get(CLASSTABLE_KEY)
        if not payload:
            raise ConnectorError(
                "tju_schedule: 还没有导入课表数据 — 请在网页端「天津大学课表」完成一次导入"
            )
        from .tju_api import parse_classtable

        parsed = parse_classtable(payload, self.semester.total_weeks)
        events = [
            event
            for entry in parsed.entries
            for event in entry.to_events(self.semester, horizon_days=self.settings.horizon_days)
        ]
        return FetchResult(
            events=events,
            detail={"mode": "imported", **parsed.summary(), "events": len(events)},
        )

    # ---------------------------------------------------------- ingest helpers
    def store_ics(self, content: bytes, filename: str) -> dict[str, Any]:
        raws = parse_ics(content)
        self.store.set(ICS_CONTENT_KEY, content.decode("utf-8", errors="replace"))
        self.store.set(ICS_FILENAME_KEY, filename)
        return {"filename": filename, "events_in_file": len(raws)}

    def clear_ics(self) -> None:
        self.store.delete(ICS_CONTENT_KEY)
        self.store.delete(ICS_FILENAME_KEY)
