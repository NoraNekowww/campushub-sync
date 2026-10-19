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
    include_hidden: bool = False,
) -> tuple[list[Event], int]:
    """时间线/订阅日历的查询入口。

    ``hidden``（用户右滑删掉 / 划掉后要移除的）默认不出现在任何列表里；
    只有订阅日历为了给客户端「撤下」墓碑（``STATUS:CANCELLED``）才显式带上它。
    """
    conditions = []
    if not include_hidden:
        conditions.append(col(Event.hidden) == False)  # noqa: E712
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
    hidden: Optional[bool] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    clear_end_time: bool = False,
) -> Optional[Event]:
    """User edits are sticky: ``local_override`` stops the next sync clobbering them.

    ``start_time`` / ``end_time`` 也在受保护字段里（见 ``sync_engine.upsert_events``）：
    改过时间的课/待办，之后同步不会再把它拽回教务或待办那边的原值。
    ``end_time`` 传 ``None`` 表示「不改」，要清空得用 ``clear_end_time``。
    """
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
    if start_time is not None:
        value = as_aware(start_time)
        if event.start_time != value:
            event.start_time = value
            changed = True
    if clear_end_time:
        if event.end_time is not None:
            event.end_time = None
            changed = True
    elif end_time is not None:
        value = as_aware(end_time)
        if event.end_time != value:
            event.end_time = value
            changed = True
    if hidden is not None and bool(hidden) != bool(event.hidden):
        event.hidden = bool(hidden)
        changed = True
    if changed:
        event.local_override = True
        event.updated_at = utcnow()
        session.add(event)
    return event


def set_hidden(session: Session, event_id: str, hidden: bool = True) -> Optional[Event]:
    """软删除 / 恢复。

    「删除」对来源是外部的事件（课表、微软待办）不能真删 —— 下一次同步会把它原样
    拉回来。所以这里做的是：隐藏 + ``local_override``（同步的受保护字段，见
    ``sync_engine.upsert_events``），于是它从时间线和订阅日历里消失，并且同步
    也再不会把它挖出来。用户后悔时 ``set_hidden(..., False)`` 就恢复。
    """
    return patch_event(session, event_id, hidden=hidden)


def event_counts(session: Session, user_id: Optional[int] = None) -> dict[str, int]:
    now = utcnow()
    scope = [col(Event.hidden) == False]  # noqa: E712  # 软删除的不计入任何统计
    if user_id is not None:
        scope.append(col(Event.user_id) == user_id)
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
        if row.id in keep_ids or row.local_override or row.hidden:
            continue  # 用户改过的、或他自己删掉（隐藏）的都留着
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
