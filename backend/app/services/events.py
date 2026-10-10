"""Event queries and mutations shared by the API and the sync engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Sequence

from sqlmodel import Session, col, func, select

from ..models import Event, EventStatus, Source
from ..timeutil import as_aware, day_bounds, utcnow

SYNCED_FIELDS = (
    "source",
    "source_id",
    "title",
    "description",
    "start_time",
    "end_time",
    "is_deadline",
    "location",
    "priority",
    "reminder_minutes",
    "all_day",
    "raw",
)


def normalize_range(
    start_date: Optional[str], end_date: Optional[str]
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Accept ``YYYY-MM-DD`` or full ISO datetimes; return aware-UTC bounds."""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    if start_date:
        text = start_date.strip()
        start = day_bounds(date.fromisoformat(text[:10]))[0] if len(text) <= 10 else _parse_dt(text)
    if end_date:
        text = end_date.strip()
        end = day_bounds(date.fromisoformat(text[:10]))[1] if len(text) <= 10 else _parse_dt(text)
    return start, end


def _parse_dt(text: str) -> datetime:
    """Naive datetimes in query params are read as Asia/Shanghai wall clock."""
    from ..timeutil import get_tz, parse_iso

    if text.endswith("Z") or "+" in text[10:] or "-" in text[10:]:
        return parse_iso(text, assume=get_tz())
    return parse_iso(text, assume=get_tz())


def query_events(
    session: Session,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    sources: Optional[Sequence[str]] = None,
    status: Optional[str] = None,
    is_deadline: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
    user_id: Optional[int] = None,
) -> tuple[list[Event], int]:
    conditions = []
    if user_id is not None:
        conditions.append(col(Event.user_id) == user_id)
    if start is not None:
        conditions.append(col(Event.start_time) >= start)
    if end is not None:
        conditions.append(col(Event.start_time) < end)
    if sources:
        conditions.append(col(Event.source).in_(list(sources)))
    if status:
        conditions.append(Event.status == status)
    if is_deadline is not None:
        conditions.append(Event.is_deadline == is_deadline)
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(col(Event.title).ilike(needle))

    total = session.exec(select(func.count()).select_from(Event).where(*conditions)).one()
    stmt = (
        select(Event)
        .where(*conditions)
        .order_by(col(Event.start_time).asc(), col(Event.is_deadline).desc())
        .limit(max(1, min(limit, 2000)))
        .offset(max(0, offset))
    )
    return list(session.exec(stmt).all()), int(total or 0)


def patch_event(
    session: Session,
    event_id: str,
    *,
    status: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    reminder_minutes: Optional[int] = None,
) -> Optional[Event]:
    """User edits are sticky: ``local_override`` stops the next sync clobbering them."""
    event = session.get(Event, event_id)
    if event is None:
        return None
    changed = False
    if status is not None:
        event.status = EventStatus(status).value
        event.completed_at = utcnow() if event.status == EventStatus.completed.value else None
        changed = True
    for field, value in (
        ("title", title),
        ("description", description),
        ("location", location),
        ("reminder_minutes", reminder_minutes),
    ):
        if value is not None and getattr(event, field) != value:
            setattr(event, field, value)
            changed = True
    if changed:
        event.local_override = True
        event.updated_at = utcnow()
        session.add(event)
    return event


def event_counts(session: Session, user_id: Optional[int] = None) -> dict[str, int]:
    now = utcnow()
    scope = [col(Event.user_id) == user_id] if user_id is not None else []
    horizon = now + timedelta(days=7)

    def count(*conditions) -> int:
        return int(session.exec(select(func.count()).select_from(Event).where(*scope, *conditions)).one() or 0)

    return {
        "total": count(),
        "pending": count(Event.status == EventStatus.pending.value),
        "completed": count(Event.status == EventStatus.completed.value),
        "deadlines": count(Event.is_deadline == True),  # noqa: E712
        "classes": count(Event.is_deadline == False),  # noqa: E712
        "next_7_days": count(col(Event.start_time) >= now, col(Event.start_time) < horizon),
        "by_source": {
            source.value: count(Event.source == source.value) for source in Source
        },
    }


DEMO_MARKER = "（演示）"


def purge_demo_events(session: Session) -> int:
    """Delete rows produced by the demo connector.

    Demo rows share a ``source`` value with real ones, but their ``source_id``
    carries the marker ``（演示）`` — that is how they are told apart once a real
    source (an imported 微北洋 table, a live ICS upload) takes over.
    """
    stmt = select(Event).where(col(Event.source_id).contains(DEMO_MARKER))
    rows = list(session.exec(stmt).all())
    for row in rows:
        session.delete(row)
    return len(rows)


def claim_orphan_events(session: Session, user_id: int) -> int:
    """多租户迁移：把 ``user_id IS NULL`` 的历史事件判给 owner（幂等）。"""
    rows = session.exec(select(Event).where(col(Event.user_id).is_(None))).all()
    for row in rows:
        row.user_id = user_id
        session.add(row)
    return len(rows)


def reconcile_source(
    session: Session, source: str, keep_ids: set[str], user_id: Optional[int] = None
) -> int:
    """Delete rows of ``source`` that this fetch no longer produces.

    Event ids are content-derived, so a corrected学期锚点 re-dates the whole
    timetable: without this, yesterday's rows would sit next to today's as
    duplicates. Rows the user edited locally (``local_override``) are kept — a
    personal change is never silently dropped. ``user_id`` keeps one account's
    sync from deleting another account's rows (they share the source name).
    """
    removed = 0
    conditions = [col(Event.source) == source]
    if user_id is not None:
        conditions.append(col(Event.user_id) == user_id)
    rows = session.exec(select(Event).where(*conditions)).all()
    for row in rows:
        if row.id in keep_ids or row.local_override:
            continue
        session.delete(row)
        removed += 1
    return removed


def prune_expired(session: Session, retention_days: int) -> int:
    """Drop externally-sourced events that ended more than N days ago."""
    cutoff = utcnow() - timedelta(days=retention_days)
    stmt = select(Event).where(
        Event.is_deadline == True,  # noqa: E712  deadlines are keyed on start_time
        col(Event.start_time) < cutoff,
        col(Event.source) != Source.custom.value,
    )
    stale = list(session.exec(stmt).all())
    # classes: compare on end_time (falling back to start_time)
    stmt2 = select(Event).where(
        Event.is_deadline == False,  # noqa: E712
        col(Event.source) != Source.custom.value,
    )
    for event in session.exec(stmt2).all():
        reference = as_aware(event.end_time or event.start_time)
        if reference and reference < cutoff:
            stale.append(event)

    seen: set[str] = set()
    removed = 0
    for event in stale:
        if event.id in seen:
            continue
        seen.add(event.id)
        session.delete(event)
        removed += 1
    return removed
