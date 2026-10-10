"""Sync engine semantics: upsert, sticky local overrides, dedup, pruning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.db import session_scope
from app.models import Event, Source, make_event_id
from app.services.events import prune_expired
from app.services.sync_engine import SyncEngine, upsert_events


def _task(title: str, *, status: str = "pending", start: datetime | None = None, source_id: str = "t1") -> Event:
    return Event(
        id=make_event_id(Source.microsoft_todo, source_id),
        source=Source.microsoft_todo.value,
        source_id=source_id,
        title=title,
        start_time=start or datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc),
        is_deadline=True,
        status=status,
        priority=5,
        updated_at=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
    )


def test_upsert_inserts_then_updates():
    with session_scope() as session:
        created, updated = upsert_events(session, [_task("第一次")])
    assert (created, updated) == (1, 0)

    with session_scope() as session:
        created, updated = upsert_events(session, [_task("第二次改名")])
    assert (created, updated) == (0, 1)

    with session_scope() as session:
        rows = list(session.exec(select(Event)).all())
    assert len(rows) == 1
    assert rows[0].title == "第二次改名"


def test_upsert_deduplicates_batch():
    batch = [_task("任务", source_id="dup"), _task("任务（覆盖）", source_id="dup")]
    with session_scope() as session:
        created, _ = upsert_events(session, batch)
    assert created == 1
    with session_scope() as session:
        assert session.exec(select(Event)).one().title == "任务（覆盖）"


def test_local_completion_is_sticky():
    with session_scope() as session:
        upsert_events(session, [_task("交作业")])
    with session_scope() as session:
        event = session.exec(select(Event)).one()
        event.status = "completed"
        event.local_override = True
        event.completed_at = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)
        session.add(event)

    # Microsoft still reports the task as open — the local tick must survive.
    with session_scope() as session:
        created, updated = upsert_events(session, [_task("交作业（改标题）")])
    assert (created, updated) == (0, 1)
    with session_scope() as session:
        event = session.exec(select(Event)).one()
    assert event.status == "completed"
    assert event.title == "交作业"  # user-visible field protected
    assert event.completed_at == datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)


def test_external_status_updates_without_override():
    with session_scope() as session:
        upsert_events(session, [_task("交作业")])
    with session_scope() as session:
        upsert_events(session, [_task("交作业", status="completed")])
    with session_scope() as session:
        assert session.exec(select(Event)).one().status == "completed"


def test_prune_removes_old_events_only():
    old = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        upsert_events(
            session,
            [
                _task("陈旧 DDL", start=old, source_id="old"),
                _task("新 DDL", start=datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc), source_id="new"),
            ],
        )
    with session_scope() as session:
        removed = prune_expired(session, retention_days=30)
    assert removed == 1
    with session_scope() as session:
        remaining = [row.source_id for row in session.exec(select(Event)).all()]
    assert remaining == ["new"]


def test_prune_keeps_recent_past_deadline():
    start = datetime.now(timezone.utc) - timedelta(days=3)
    with session_scope() as session:
        upsert_events(session, [_task("三天前", start=start, source_id="recent")])
    with session_scope() as session:
        assert prune_expired(session, retention_days=30) == 0


def test_engine_without_connectors_reports_hint(settings):
    engine = SyncEngine(settings=settings, connectors=[])
    import asyncio

    outcome = asyncio.run(engine.run(trigger="test"))
    # 没配任何连接器是「没事可做」，不是失败：记一条提示，但 run 仍然算成功
    assert outcome.ok is True
    assert "connector" in (outcome.message or "")
    assert outcome.fetched == 0
    assert outcome.run_id is not None
    # the run is still recorded for /api/status
    last = engine.last_run()
    assert last is not None and last.ok is True
