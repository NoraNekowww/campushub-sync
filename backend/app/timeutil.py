"""Timezone helpers.

Storage convention: **every datetime in Python is timezone-aware UTC**. SQLModel
maps ``datetime`` columns to its ``UTCDateTime`` type, which rejects naive values
and writes a naive-UTC representation into SQLite (SQLite has no tz support), then
re-attaches UTC on the way out. So the invariant is simple:

* build values with :func:`as_stored` / :func:`parse_iso` / :func:`combine`
  (all return aware UTC, converting +08:00 wall clocks when needed),
* render them for humans with :func:`iso_local` / :func:`to_local`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
CN_OFFSET = timezone(timedelta(hours=8))


@lru_cache(maxsize=8)
def get_tz(name: str = "Asia/Shanghai"):
    """ZoneInfo when the tz database is present, fixed +08:00 otherwise."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return CN_OFFSET


def local_tz(name: str = "Asia/Shanghai"):
    return get_tz(name)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------- store
def as_stored(dt: datetime, assume: timezone | ZoneInfo | None = UTC) -> datetime:
    """Aware UTC for persistence. Naive input is interpreted using ``assume``."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume or UTC)
    return dt.astimezone(UTC)


def as_aware(dt: datetime | None, assume: timezone | ZoneInfo | None = UTC) -> datetime | None:
    """Re-attach UTC to a value read back from the database."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=assume or UTC)
    return dt


def to_local(dt: datetime | None, tz_name: str = "Asia/Shanghai") -> datetime | None:
    aware = as_aware(dt)
    return aware.astimezone(get_tz(tz_name)) if aware else None


# --------------------------------------------------------------------- parse
def parse_iso(value: str, assume: timezone | ZoneInfo | None = UTC) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return as_stored(parsed, assume=assume)


def parse_graph_datetime(node: dict | str | None, default_tz: str = "UTC") -> datetime | None:
    """Parse a Graph ``dateTimeTimeZone`` (``{dateTime, timeZone}``) into UTC.

    Several Graph surfaces — notably ``/me/todo/lists/{id}/tasks`` — return some
    timestamps (``lastModifiedDateTime``, ``createdDateTime``) as a **plain ISO
    string** while ``dueDateTime``/``completedDateTime`` are the usual
    ``dateTimeTimeZone`` object. Accept both shapes; naive strings are read as
    UTC, which is what Graph emits for those fields.
    """
    if not node:
        return None
    if isinstance(node, str):
        text = node.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = datetime.fromisoformat(text.split(".")[0])
            return as_stored(parsed, assume=UTC)
        return as_stored(parsed)
    raw = node.get("dateTime")
    if not raw:
        return None
    tz_name = node.get("timeZone") or default_tz
    text = raw.strip()
    if text.endswith("Z") or "+" in text[10:] or "-" in text[10:]:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return as_stored(parsed)
    naive = datetime.fromisoformat(text.split(".")[0])
    if tz_name.upper() in {"UTC", "GMT", "Z"}:
        return as_stored(naive, assume=UTC)
    try:
        return as_stored(naive, assume=get_tz(tz_name))
    except Exception:  # unknown tz id -> treat as local wall clock
        return as_stored(naive, assume=get_tz())


def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip()[:10])


# ---------------------------------------------------------------------- misc
def combine(day: date, hhmm: str, tz_name: str = "Asia/Shanghai") -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":")[:2])
    return as_stored(datetime.combine(day, time(hour, minute)), assume=get_tz(tz_name))


def day_bounds(day: date, tz_name: str = "Asia/Shanghai") -> tuple[datetime, datetime]:
    """Aware-UTC bounds covering 00:00–24:00 local time on ``day``."""
    start = combine(day, "00:00", tz_name)
    return start, start + timedelta(days=1)


def iso_local(dt: datetime | None, tz_name: str = "Asia/Shanghai") -> str | None:
    aware = to_local(dt, tz_name)
    return aware.isoformat(timespec="seconds") if aware else None
