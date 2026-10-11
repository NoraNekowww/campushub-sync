"""待办反向同步 + 抓取并发（三条用户需求里的前两条的回归测试）。

- ``task_query``：把「待办里勾掉的」拉回来的过滤器（``lastModifiedDateTime`` 窗口）
- 完成态归属：对面更晚动过就以它为准，本地改过的标题/地点仍受保护
- ``fetch``：十几个清单一轮并发抓，不再串行排队
- ``run(sources=[...])``：待办快通道只刷待办，不碰教务
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.connectors.base import FetchResult
from app.connectors.ms_todo import MSTodoConnector
from app.db import session_scope
from app.models import Event, Source, make_event_id
from app.services.sync_engine import SyncEngine, upsert_events


def _event(*, status: str = "pending", updated: datetime, title: str = "交作业", source_id: str = "t1") -> Event:
    return Event(
        id=make_event_id(Source.microsoft_todo, source_id),
        source=Source.microsoft_todo.value,
        source_id=source_id,
        title=title,
        start_time=datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc),
        is_deadline=True,
        status=status,
        priority=5,
        updated_at=updated,
        completed_at=updated if status == "completed" else None,
    )


# --------------------------------------------------------------------- filter
def test_task_query_pulls_recently_completed(settings):
    conn = MSTodoConnector(settings=settings.model_copy(update={"ms_completed_lookback_days": 14}))
    params = conn.task_query()
    assert params["$top"] == 100
    flt = params["$filter"]
    # 未完成的全部 + 最近动过的（含刚勾掉的）
    assert flt.startswith("(status ne 'completed') or (lastModifiedDateTime ge ")
    assert flt.endswith("Z)")
    # completedDateTime 在 To Do 上是 dateTimeTimeZone，拿去比较会被 400 拒掉
    assert "completedDateTime" not in flt
    assert "$select" not in params


def test_task_query_lookback_zero_keeps_old_behaviour(settings):
    conn = MSTodoConnector(settings=settings.model_copy(update={"ms_completed_lookback_days": 0}))
    assert conn.task_query()["$filter"] == "status ne 'completed'"


def test_task_query_without_filter_when_completed_requested(settings):
    conn = MSTodoConnector(settings=settings.model_copy(update={"ms_include_completed": True}))
    assert "$filter" not in conn.task_query()


# --------------------------------------------------------- completion follows
def test_todo_tick_pulls_back_into_local(settings):
    """待办那边勾掉（更晚动过）⇒ 本地这行也变成已划掉。"""
    local_at = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        upsert_events(session, [_event(updated=local_at)])
    with session_scope() as session:
        row = session.exec(select(Event)).one()
        row.local_override = True  # 用户在客户端动过这行（例如改过标题）
        row.updated_at = local_at
        session.add(row)

    done_at = local_at + timedelta(hours=3)
    with session_scope() as session:
        _created, updated = upsert_events(
            session, [_event(status="completed", updated=done_at, title="交作业（待办里改的名）")]
        )
    assert updated == 1
    with session_scope() as session:
        row = session.exec(select(Event)).one()
    assert row.status == "completed"
    assert row.completed_at == done_at
    assert row.title == "交作业"  # 本地改过的标题依然受保护


def test_stale_external_state_does_not_undo_local_tick(settings):
    """微软那边报的完成态比本地这次编辑还旧 ⇒ 不动它（本地划掉仍然算数）。"""
    with session_scope() as session:
        upsert_events(session, [_event(updated=datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc))])
    ticked_at = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        row = session.exec(select(Event)).one()
        row.status = "completed"
        row.completed_at = ticked_at
        row.local_override = True
        row.updated_at = ticked_at
        session.add(row)

    with session_scope() as session:
        upsert_events(
            session, [_event(status="pending", updated=datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc))]
        )
    with session_scope() as session:
        assert session.exec(select(Event)).one().status == "completed"


def test_newer_external_pending_does_not_undo_local_tick(settings):
    """对面报「未完成」就算是更新的时间戳，也不抹掉本地的划掉。

    本地划掉会立刻推回待办，而推回去本身会让对面的 lastModifiedDateTime 变新；
    若两边互认「更新者胜」，用户刚划掉的会在下一轮同步里被自己推的那次写入抹掉。
    """
    with session_scope() as session:
        upsert_events(session, [_event(updated=datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc))])
    ticked_at = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        row = session.exec(select(Event)).one()
        row.status = "completed"
        row.completed_at = ticked_at
        row.local_override = True
        row.updated_at = ticked_at
        session.add(row)

    with session_scope() as session:
        upsert_events(
            session, [_event(status="pending", updated=ticked_at + timedelta(minutes=1))]
        )
    with session_scope() as session:
        assert session.exec(select(Event)).one().status == "completed"


# ---------------------------------------------------------------- fetch fan-out
def test_fetch_fans_out_over_lists(settings, monkeypatch):
    conn = MSTodoConnector(settings=settings.model_copy(update={"ms_max_concurrency": 4}))
    todo_lists = [{"id": f"list-{index}", "displayName": f"清单{index}"} for index in range(9)]
    state = {"active": 0, "peak": 0}

    async def fake_lists(*, client=None, headers=None):
        return todo_lists

    async def fake_headers():
        return {"Authorization": "Bearer test"}

    async def fake_paged(url, params=None, *, client=None, headers=None):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.01)
        state["active"] -= 1
        return []

    monkeypatch.setattr(conn, "_lists", fake_lists)
    monkeypatch.setattr(conn, "_auth_headers", fake_headers)
    monkeypatch.setattr(conn, "_paged", fake_paged)

    result = asyncio.run(conn.fetch())
    assert state["peak"] > 1  # 并发了，不再一个个排队
    assert state["peak"] <= 4  # 但受 ms_max_concurrency 限制
    assert len(result.detail["lists"]) == 9


# ---------------------------------------------------------------- fast lane
class _StubConnector:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    async def fetch(self) -> FetchResult:
        self.calls += 1
        return FetchResult(events=[], detail={"stub": True})


def test_run_can_restrict_to_one_source(settings):
    todo = _StubConnector("microsoft_todo")
    tju = _StubConnector("tju_schedule")
    engine = SyncEngine(settings=settings, connectors=[todo, tju])

    outcome = asyncio.run(engine.run(trigger="test:todo", sources=["microsoft_todo"]))
    assert outcome.ok is True
    assert todo.calls == 1
    assert tju.calls == 0
    assert set(outcome.connectors) == {"microsoft_todo"}


def test_run_reports_missing_source(settings):
    engine = SyncEngine(settings=settings, connectors=[_StubConnector("tju_schedule")])
    outcome = asyncio.run(engine.run(trigger="test:todo", sources=["microsoft_todo"]))
    assert outcome.ok is True
    assert "microsoft_todo" in (outcome.message or "")


def test_scheduler_registers_todo_fast_lane(settings):
    from app.services.scheduler import MS_JOB_ID, SchedulerService

    config = settings.model_copy(
        update={"ms_sync_interval_minutes": 2, "ms_client_id": "client-id", "sync_on_startup": False}
    )
    service = SchedulerService(settings=config)

    async def boot():
        service.start()
        assert service._scheduler is not None
        assert service._scheduler.get_job(MS_JOB_ID) is not None
        status = service.status()
        assert status["todo_interval_minutes"] == 2
        assert status["interval_minutes"] == config.sync_interval_minutes
        service.shutdown()

    asyncio.run(boot())
