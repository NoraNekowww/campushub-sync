"""APScheduler wiring: periodic background sync."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import Settings, get_settings
from ..timeutil import utcnow
from .sync_engine import get_sync_engine

log = logging.getLogger("campushub.scheduler")

JOB_ID = "campushub-sync"
MS_JOB_ID = "campushub-sync-ms"


class SchedulerService:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._last_error: Optional[str] = None
        self._running = False

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler(timezone=self.settings.timezone)
        first_run = (
            utcnow() + timedelta(seconds=15) if self.settings.sync_on_startup else None
        )
        self._scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(minutes=max(1, self.settings.sync_interval_minutes)),
            id=JOB_ID,
            name="CampusHub background sync",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
            next_run_time=first_run,
        )
        ms_minutes = max(0, int(self.settings.ms_sync_interval_minutes))
        if ms_minutes and self.settings.ms_enabled:
            self._scheduler.add_job(
                self._tick_todo,
                trigger=IntervalTrigger(minutes=max(1, ms_minutes)),
                id=MS_JOB_ID,
                name="CampusHub To Do fast sync",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=120,
                next_run_time=first_run,
            )
        self._scheduler.start()
        log.info(
            "scheduler started — every %d min (first run: %s)%s",
            self.settings.sync_interval_minutes,
            first_run.isoformat(timespec="seconds") if first_run else "after one interval",
            f", To Do every {ms_minutes} min" if (ms_minutes and self.settings.ms_enabled) else "",
        )

    def shutdown(self) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as exc:  # pragma: no cover - shutdown races
                log.debug("scheduler shutdown: %s", exc)
            self._scheduler = None

    # ------------------------------------------------------------------- work
    async def _tick(self) -> None:
        await self._run_tick(trigger="scheduler")

    async def _tick_todo(self) -> None:
        """待办快通道：只刷微软待办，不碰教务（CAS 登录不能这么勤）。"""
        await self._run_tick(trigger="scheduler:todo", sources=["microsoft_todo"])

    async def _run_tick(self, trigger: str, sources: Optional[list[str]] = None) -> None:
        if self._running:
            return
        self._running = True
        try:
            outcome = await get_sync_engine(self.settings).run(trigger=trigger, sources=sources)
            self._last_error = None if outcome.ok else _first_error(outcome)
        except Exception as exc:  # noqa: BLE001 - the job must never die
            self._last_error = f"{type(exc).__name__}: {exc}"
            log.exception("scheduled sync crashed")
        finally:
            self._running = False

    def trigger_now(self) -> None:
        """Queue an immediate tick through the scheduler (non-blocking)."""
        if self._scheduler is None:
            return
        self._scheduler.add_job(
            self._tick,
            id=f"{JOB_ID}-now",
            replace_existing=True,
            misfire_grace_time=60,
        )

    # ----------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "running": bool(self._scheduler and self._scheduler.running),
            "interval_minutes": self.settings.sync_interval_minutes,
            "todo_interval_minutes": (
                max(0, int(self.settings.ms_sync_interval_minutes))
                if self.settings.ms_enabled
                else 0
            ),
            "sync_on_startup": self.settings.sync_on_startup,
            "last_error": self._last_error,
        }
        if self._scheduler is not None:
            job = self._scheduler.get_job(JOB_ID)
            next_run: Optional[datetime] = getattr(job, "next_run_time", None)
            info["next_run"] = next_run.isoformat(timespec="seconds") if next_run else None
            todo_job = self._scheduler.get_job(MS_JOB_ID)
            todo_next: Optional[datetime] = getattr(todo_job, "next_run_time", None)
            info["todo_next_run"] = (
                todo_next.isoformat(timespec="seconds") if todo_next else None
            )
        return info


_scheduler: Optional[SchedulerService] = None


def get_scheduler(settings: Optional[Settings] = None) -> SchedulerService:
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService(settings=settings)
    return _scheduler


def reset_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
    _scheduler = None


def _first_error(outcome) -> Optional[str]:
    for name, info in outcome.connectors.items():
        if not info.get("ok"):
            return f"{name}: {info.get('error')}"
    return outcome.message
