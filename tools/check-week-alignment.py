#!/usr/bin/env python3
"""周次对齐自检：学期锚点 / 课表周次换算 / 有没有重复行 —— 一次看全。

用法（服务器上）::

    ssh root@nzlab.online 'cd /var/www/schedule/backend && /var/www/schedule/venv/bin/python -' \\
        < tools/check-week-alignment.py

检查项（任何一项不通过就以非 0 退出）：

1. 学期设置的「第一周周一」是不是个**周一**，且与导入数据的 ``term_start`` 一致 ——
   线上出过设置里留着 2026-07-31（周五）而事件用 2026-08-31 的情况，
   界面显示的周次就会比真实周次差 4-5 周（单双周随之反掉）。
2. 课表周次换算：课表里最早有课的那一周，日期要落在「第一周周一 + (周次-1)*7」。
   2026 秋的实测基准：第一个有课的周 = 教学周 4 = **2026-09-21**（学校迎新的上课日）。
3. 存储的 payload 周次是不是已经减掉教务那一个「报到周」（位图第 5 位 ⇒ 教学周 4）。
4. owner 名下同一天同一门课有没有重复行（旧锚点留下的孤儿行）。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

from sqlmodel import select

from app.connectors.tju_schedule import CLASSTABLE_KEY, SEMESTER_KEY, TERM_START_KEY
from app.db import KVStore, bind_scope, get_session
from app.models import Event

OWNER = 1  # 站长账号
SCHOOL_FIRST_CLASS_DAY = date(2026, 9, 21)  # 2026 秋：8/28-9/20 军训，9/21 上课

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'ok ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    bind_scope(OWNER)
    store = KVStore()
    semester = store.get(SEMESTER_KEY) or {}
    term_start = store.get(TERM_START_KEY)
    payload = store.get(CLASSTABLE_KEY) or {}

    start_raw = semester.get("start_date")
    start = date.fromisoformat(start_raw) if isinstance(start_raw, str) else None
    check("学期设置了第一周周一", start is not None, str(start_raw))
    if start:
        check("第一周周一是周一", start.weekday() == 0, f"{start} = 周{start.isoweekday()}")

    if isinstance(term_start, str) and start_raw:
        check("学期设置与导入数据的 term_start 一致", term_start == start_raw,
              f"term_start={term_start} settings={start_raw}")

    weeks: list[int] = []
    for course in (payload.get("data") or {}).get("data") or []:
        for slot in course.get("arrange") or []:
            value = slot.get("week")
            if isinstance(value, list):
                weeks.extend(int(w) for w in value)
    if not weeks:
        check("课表 payload 里有周次", False, "没读到任何周次")
    else:
        first_week = min(weeks)
        print(f"     payload 里最早出现的课表周次 = {first_week}")
        if start:
            first_day = start + timedelta(days=(first_week - 1) * 7)
            check(
                "第一个有课周的日期 = 学校上课日",
                first_day == SCHOOL_FIRST_CLASS_DAY,
                f"推算 {first_day}，学校迎新口径 {SCHOOL_FIRST_CLASS_DAY}",
            )

    session = next(get_session())
    rows = list(
        session.exec(select(Event).where(Event.source == "tju_schedule", Event.user_id == OWNER))
    )
    visible = [row for row in rows if not row.hidden]
    pairs = Counter((row.start_time.date().isoformat(), row.title) for row in visible)
    dupes = {key: count for key, count in pairs.items() if count > 1}
    check("没有重复的课（同一天同一门课只一条）", not dupes, str(list(dupes.items())[:3]))

    print(f"\n事件: {len(rows)} 条（可见 {len(visible)} / 已划掉删除 {len(rows) - len(visible)}）")
    print("第一个有课周:", SCHOOL_FIRST_CLASS_DAY.isoformat())
    if failures:
        print("\n不通过:", len(failures), "项")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
