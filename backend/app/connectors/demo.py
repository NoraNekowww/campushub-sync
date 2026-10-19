"""Synthetic connector used by ``DEMO_MODE=1``.

Lets you (and the test-suite) exercise the whole pipeline — timeline, ICS feed,
PWA — without touching Microsoft or TJU. Data is generated relative to *today*
so the agenda view always has content.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from ..models import Event, Source, make_event_id
from ..timeutil import as_stored, as_aware, get_tz, utcnow
from .base import BaseConnector, FetchResult
from .tju_schedule import PERIOD_TIMES, ClassEntry, Semester

DEMO_COURSES: list[tuple[str, int, int, int, str, str]] = [
    # name, day_offset_from_today, start_period, end_period, location, teacher
    ("高等数学 2A", 0, 1, 2, "26 教学楼 301", "李明"),
    ("大学物理", 0, 3, 4, "12 教学楼 205", "王雪"),
    ("数据结构", 1, 5, 6, "55 教学楼 A406", "陈鹏"),
    ("线性代数", 1, 1, 2, "26 教学楼 208", "李明"),
    ("操作系统", 2, 3, 4, "55 教学楼 B210", "刘婷"),
    ("英语视听说", 2, 7, 8, "33 教学楼 107", "Sarah Johnson"),
    ("计算机网络", 3, 5, 6, "55 教学楼 A302", "赵岩"),
    ("体育（篮球）", 4, 7, 8, "南区体育馆", "张伟"),
    ("数字电路", 4, 1, 2, "12 教学楼 401", "孙宁"),
    ("形势与政策", 5, 9, 10, "综合楼 报告厅", "周涛"),
]

DEMO_TASKS: list[tuple[str, int, str, int]] = [
    ("提交《数据结构》实验一报告", 1, "high", 1),
    ("高数作业 第 3 章", 2, "normal", 2),
    ("操作系统进程调度实验", 4, "high", 3),
    ("英语演讲 PPT 初稿", 6, "normal", 4),
    ("数字电路课程设计选题", 9, "low", 5),
    ("体测预约", 13, "normal", 6),
]


class DemoConnector(BaseConnector):
    name = "demo"
    label = "演示数据"

    @property
    def enabled(self) -> bool:
        return True

    def semester(self) -> Semester:
        return Semester(
            name="2026 秋季学期（演示）",
            start_date=date.today() - timedelta(days=date.today().weekday()),
            total_weeks=max(16, self.settings.semester_total_weeks),
            period_times=self.settings.period_times or dict(PERIOD_TIMES),
            tz_name=self.settings.timezone,
        )

    async def fetch(self) -> FetchResult:
        semester = self.semester()
        now = utcnow()
        events: list[Event] = []

        # --- classes, placed relative to *today* so the agenda is never empty
        # (a fixed Mon–Fri table would vanish on weekends, when everything is past)
        weeks_used: set[int] = set()
        for name, offset, start_period, end_period, location, teacher in DEMO_COURSES:
            day = date.today() + timedelta(days=offset)
            week = semester.week_of(day)
            weeks_used.add(week)
            entry = ClassEntry(
                name=name,
                weekday=day.isoweekday(),
                start_period=start_period,
                end_period=end_period,
                weeks={week},
                location=location,
                teacher=teacher,
            )
            events.extend(entry.to_events(semester, now=now, horizon_days=self.settings.horizon_days))

        # --- deadlines
        tz = get_tz(self.settings.timezone)
        priority_map = {"high": 1, "normal": 5, "low": 9}
        for title, offset_days, importance, index in DEMO_TASKS:
            day = date.today() + timedelta(days=offset_days)
            due_local = datetime.combine(day, time(23, 0))
            due = as_stored(due_local, assume=tz)
            source_id = f"demo-task-{index}"
            completed = offset_days < 0
            events.append(
                Event(
                    id=make_event_id(Source.microsoft_todo, source_id),
                    source=Source.microsoft_todo.value,
                    source_id=source_id,
                    title=title,
                    description="演示数据 — 仅用于本地预览界面。",
                    start_time=due,
                    end_time=None,
                    is_deadline=True,
                    location="任务",
                    status="completed" if completed else "pending",
                    priority=priority_map[importance],
                    reminder_minutes=60,
                    updated_at=now,
                    raw=json.dumps(
                        {"demo": True, "importance": importance, "listId": "demo-list"},
                        ensure_ascii=False,
                    ),
                )
            )
        return FetchResult(
            events=events,
            detail={
                "mode": "demo",
                "weeks": sorted(weeks_used),
                "courses": len(DEMO_COURSES),
                "tasks": len(DEMO_TASKS),
                "events": len(events),
            },
        )

    async def status(self) -> dict[str, Any]:
        return {"enabled": True, "mode": "demo", "semester": self.semester().summary()}
