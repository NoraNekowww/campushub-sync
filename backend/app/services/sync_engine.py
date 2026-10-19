"""The sync engine: fetch → normalize → upsert → prune, with an audit trail.

Upsert policy
-------------
* New events are inserted with a deterministic id (``hash(source + source_id)``).
* Existing events are updated field-by-field over :data:`SYNCED_FIELDS`.
* **Local user edits win**: once an event carries ``local_override`` (set by
  ``PATCH /api/events/{id}``), the sync never overwrites its status/title/etc.
  A task you ticked off in CampusHub therefore stays ticked off even though
  Microsoft To Do still reports it as open.
* Duplicate ids inside a single batch collapse (last write wins).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlmodel import Session, col, select

from ..config import Settings, get_settings
from ..db import KVStore, bind_scope, session_scope
from ..models import ConnectorLog, Event, SyncRun, User
from ..timeutil import as_aware, utcnow
from .events import SYNCED_FIELDS, prune_expired, reconcile_source

log = logging.getLogger("campushub.sync")


@dataclass
class SyncOutcome:
    ok: bool
    trigger: str
    run_id: Optional[int] = None
    fetched: int = 0
    created: int = 0
    updated: int = 0
    pruned: int = 0
    duration_ms: int = 0
    message: Optional[str] = None
    connectors: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "run_id": self.run_id,
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "pruned": self.pruned,
            "duration_ms": self.duration_ms,
            "message": self.message,
        }


def _same_value(left: Any, right: Any) -> bool:
    """两个字段值是否等价 —— datetime 先统一成 aware 再比。

    SQLite 存回来的 datetime 是 naive（时区被抹掉），直接 ``!=`` 比一个 aware 值
    永远为真，会让「内容没变」被判成「变了」。
    """
    if isinstance(left, datetime) and isinstance(right, datetime):
        return as_aware(left) == as_aware(right)
    return left == right


def upsert_events(
    session: Session, events: Sequence[Event], user_id: Optional[int] = None
) -> tuple[int, int]:
    """Insert/update a batch. Returns ``(created, updated)``.

    ``user_id`` stamps the rows with their owner (multi-tenancy): new rows get it,
    and rows that predate the migration adopt the first account that syncs them.
    """
    created = updated = 0
    seen: dict[str, Event] = {}
    for incoming in events:
        seen[incoming.id] = incoming  # de-duplicate inside the batch

    for event_id, incoming in seen.items():
        existing = session.get(Event, event_id)
        if existing is None:
            if user_id is not None:
                incoming.user_id = user_id
            session.add(incoming)
            created += 1
            continue
        if existing.user_id is None and user_id is not None:
            existing.user_id = user_id
        if existing.local_override:
            # keep the user's edited/protected columns, refresh the rest
            # 改过时间的日程也算「用户的版本」：教务后面调课、待办那边改期，
            # 都不该把它拽回去（要跟随就再编辑一次）。
            protected = {
                "status",
                "title",
                "description",
                "location",
                "reminder_minutes",
                "completed_at",
                "start_time",
                "end_time",
            }
            # 只有真的改了东西才刷新 updated_at：它决定订阅 feed 里的 DTSTAMP /
            # LAST-MODIFIED —— 每轮同步都变一次的话，手机日历会把整份日程当成
            # 「刚改过」，课上一半又弹一次提醒（也是 X-CAMPUSHUB 的 etag 抖动源）。
            touched = False
            for name in SYNCED_FIELDS:
                if name in protected:
                    continue
                value = getattr(incoming, name)
                if not _same_value(getattr(existing, name), value):
                    setattr(existing, name, value)
                    touched = True
            # 例外：完成状态按「谁最后动」定。用户在微软待办那边勾掉一条日程，
            # 客户端要跟着划掉；而本地划掉会立刻推回待办，所以正常情况两边一致。
            # 只有对面确实更晚动过（lastModifiedDateTime / updated_at 更新）才让
            # 它改这一项，本地改的标题、地点、备注仍然受保护。
            #
            # 只认「对面把它划掉」这一个方向：反过来（对面报未完成）不动本地的
            # 划掉标记 —— 我们推回去的写入本身就会让对面的 lastModifiedDateTime
            # 变新，若两边互认「更新者胜」，本地刚划掉的会被自己推的那次同步抹掉。
            # 要取消划掉，在客户端点一下即可（那会立刻推回待办）。
            if (
                incoming.status == "completed"
                and existing.status != "completed"
                and as_aware(incoming.updated_at) > as_aware(existing.updated_at)
            ):
                log.info("sync: %s marked completed by the source", event_id)
                existing.status = "completed"
                existing.completed_at = incoming.completed_at or utcnow()
                touched = True
            if touched:
                existing.updated_at = utcnow()
        else:
            touched = False
            for name in SYNCED_FIELDS:
                value = getattr(incoming, name)
                if not _same_value(getattr(existing, name), value):
                    setattr(existing, name, value)
                    touched = True
            if not _same_value(existing.status, incoming.status):
                existing.status = incoming.status
                touched = True
            if not _same_value(existing.completed_at, incoming.completed_at):
                existing.completed_at = incoming.completed_at
                touched = True
            # 内容没变就别动 updated_at：订阅 feed 的 DTSTAMP / LAST-MODIFIED 跟着它走，
            # 每轮同步刷新一次的话，手机日历会把整份日程当成「刚改过」→ 重复提醒。
            if touched:
                existing.updated_at = incoming.updated_at
        session.add(existing)
        updated += 1
    return created, updated


class SyncEngine:
    """Runs every configured connector and merges the result into SQLite.

    多租户：每个「连过东西」的账号各跑一遍自己的连接器 —— 连接器拿到的是该账号
    命名空间里的 KV，所以它们天然只读得到自己的教务 / 微软凭据。
    """

    def __init__(self, settings: Optional[Settings] = None, connectors: Optional[list] = None):
        self.settings = settings or get_settings()
        #: 显式注入的连接器（测试 / 单机 CLI）：只跑这一份，不带 user_id
        self.connectors = connectors
        self._lock = asyncio.Lock()

    def _scopes(self) -> list[tuple[Optional[int], list]]:
        """``(user_id, connectors)`` 列表；只有配过凭据的账号才参与同步。"""
        if self.connectors is not None:
            return [(None, self.connectors)]

        from ..connectors import build_connectors

        with session_scope() as session:
            users = session.exec(
                select(User).where(User.is_active == True).order_by(User.id)  # noqa: E712
            ).all()
        scopes: list[tuple[Optional[int], list]] = []
        for user in users:
            store = KVStore(namespace=f"u{user.id}:")
            # 既没连教务也没连微软的账号跳过 —— 否则每轮都刷一屏
            # "no refresh token" 的错误日志，而他们其实什么都没配。
            if not self.settings.demo_mode and not store.keys("ms.") and not store.keys("tju."):
                continue
            scopes.append((user.id, build_connectors(self.settings, store=store)))
        return scopes

    async def run(
        self, trigger: str = "manual", sources: Optional[Sequence[str]] = None
    ) -> SyncOutcome:
        """跑一轮同步。

        ``sources`` 只跑指定名字的连接器（``["microsoft_todo"]``）—— 待办的变化
        小而快，用短间隔单独刷；教务要现场登录 CAS，跟着一起刷就是浪费。
        """
        wanted = {name.strip().lower() for name in sources} if sources else None

        if self._lock.locked():
            log.info("sync already running — skipping %s trigger", trigger)
            return SyncOutcome(ok=False, trigger=trigger, message="sync already in progress")

        async with self._lock:
            # 后台任务可能继承了触发它的请求的 KV 空间；这里显式清回全局，
            # 每个账号的连接器用的是自己那份显式 store（见 _scopes）。
            bind_scope(None)
            started = time.perf_counter()
            outcome = SyncOutcome(ok=True, trigger=trigger)
            run_id = self._open_run(trigger)
            outcome.run_id = run_id

            scopes = self._scopes()
            if wanted is not None:
                scopes = [
                    (user_id, [conn for conn in connectors if conn.name.lower() in wanted])
                    for user_id, connectors in scopes
                ]
            if not any(connectors for _user_id, connectors in scopes):
                # 一个连接器都没有 = 没东西可同步，不算失败；只给一条提示，
                # 免得用户刚注册、还没绑任何账号就看到「同步失败」。
                outcome.message = (
                    f"no {'/'.join(sorted(wanted))} connector enabled"
                    if wanted is not None
                    else "no connector enabled — set MS_CLIENT_ID / TJU_MODE or DEMO_MODE=1"
                )
                self._close_run(run_id, outcome, started)
                return outcome

            for user_id, connectors in scopes:
                for connector in connectors:
                    began = time.perf_counter()
                    label = connector.name if user_id is None else f"{connector.name}#{user_id}"
                    ok = True
                    error: Optional[str] = None
                    fetched = 0
                    try:
                        result = await connector.fetch()
                        fetched = len(result.events)
                        with session_scope() as session:
                            created, updated = upsert_events(session, result.events, user_id)
                            # 声明 reconciles 的连接器：它的抓取就是全集，本次没出现
                            # 的同源旧行要删掉，否则改锚点后新旧两批并排显示像重复。
                            source = getattr(connector, "reconciles", None)
                            if source and result.events:
                                dropped = reconcile_source(
                                    session, source, {item.id for item in result.events}, user_id
                                )
                                if dropped:
                                    log.info("%s: reconciled %s stale row(s)", label, dropped)
                        outcome.created += created
                        outcome.updated += updated
                        outcome.fetched += fetched
                        outcome.connectors[label] = {
                            "ok": True,
                            "fetched": fetched,
                            "created": created,
                            "updated": updated,
                            "detail": result.detail,
                        }
                    except Exception as exc:  # noqa: BLE001 - one source must not kill the run
                        ok = False
                        error = f"{type(exc).__name__}: {exc}"
                        outcome.connectors[label] = {"ok": False, "error": error}
                        log.warning("connector %s failed: %s", label, error)
                        # 某个同学没连微软不该让整轮判失败（别人的还在同步），
                        # 所以只有单机/无归属那一路才真算失败。
                        if user_id is None:
                            outcome.ok = False
                    finally:
                        elapsed_ms = int((time.perf_counter() - began) * 1000)
                        self._log_connector(run_id, label, ok, fetched, error, elapsed_ms)

            if outcome.ok or outcome.fetched:
                with session_scope() as session:
                    outcome.pruned = prune_expired(session, self.settings.event_retention_days)

            outcome.duration_ms = int((time.perf_counter() - started) * 1000)
            self._close_run(run_id, outcome, started)
            log.info(
                "sync[%s] done in %dms — fetched=%d created=%d updated=%d pruned=%d ok=%s",
                trigger,
                outcome.duration_ms,
                outcome.fetched,
                outcome.created,
                outcome.updated,
                outcome.pruned,
                outcome.ok,
            )
            return outcome

    # ------------------------------------------------------------- audit trail
    def _open_run(self, trigger: str) -> Optional[int]:
        with session_scope() as session:
            run = SyncRun(trigger=trigger, started_at=utcnow())
            session.add(run)
            session.flush()
            return run.id

    def _close_run(self, run_id: Optional[int], outcome: SyncOutcome, started: float) -> None:
        if run_id is None:
            return
        with session_scope() as session:
            run = session.get(SyncRun, run_id)
            if run is None:
                return
            run.finished_at = utcnow()
            run.ok = outcome.ok
            run.fetched = outcome.fetched
            run.created = outcome.created
            run.updated = outcome.updated
            run.pruned = outcome.pruned
            run.message = outcome.message or _summarize(outcome)
            session.add(run)

    def _log_connector(
        self,
        run_id: Optional[int],
        name: str,
        ok: bool,
        fetched: int,
        error: Optional[str],
        duration_ms: int,
    ) -> None:
        with session_scope() as session:
            session.add(
                ConnectorLog(
                    run_id=run_id,
                    connector=name,
                    ok=ok,
                    fetched=fetched,
                    error=error,
                    duration_ms=duration_ms,
                    updated_at=utcnow(),
                )
            )

    # ------------------------------------------------------------------ status
    def last_run(self) -> Optional[SyncRun]:
        with session_scope() as session:
            stmt = select(SyncRun).order_by(col(SyncRun.id).desc()).limit(1)
            return session.exec(stmt).first()

    def connector_logs(self, run_id: Optional[int]) -> list[ConnectorLog]:
        if run_id is None:
            return []
        with session_scope() as session:
            stmt = select(ConnectorLog).where(ConnectorLog.run_id == run_id)
            return list(session.exec(stmt).all())

    def last_success_at(self) -> Optional[datetime]:
        with session_scope() as session:
            stmt = (
                select(SyncRun)
                .where(SyncRun.ok == True)  # noqa: E712
                .order_by(col(SyncRun.id).desc())
                .limit(1)
            )
            run = session.exec(stmt).first()
            return as_aware(run.finished_at) if run and run.finished_at else None


def _summarize(outcome: SyncOutcome) -> str:
    failures = [name for name, info in outcome.connectors.items() if not info.get("ok")]
    if failures:
        return "connector errors: " + ", ".join(failures)
    return f"fetched {outcome.fetched} events"


_engine: Optional[SyncEngine] = None


def get_sync_engine(settings: Optional[Settings] = None) -> SyncEngine:
    global _engine
    if _engine is None:
        _engine = SyncEngine(settings=settings)
    return _engine


def reset_sync_engine() -> None:
    global _engine
    _engine = None
