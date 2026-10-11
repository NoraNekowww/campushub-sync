"""端到端自检：在微软待办那边勾掉一条日程，客户端要跟着划掉。

这条链路不能靠「我们自己 PATCH 本地」来验证（那是另一个方向）。所以：
1. 走我们自己的创建路径在待办里建一条任务（和 App 的「新建待办」一样）
2. 同步一次 → 本地应有一行 pending
3. 把本地那行标记成「用户改过」（local_override=True，时间戳设成昨天）
4. **直接经 Graph 把待办任务标成 completed** —— 等价于你在手机上勾掉它
5. 再同步一次 → 本地必须变成 completed，而且本地改过的标题不能被覆盖
6. 收尾：删掉待办任务和本地那一行
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlmodel import select

from app.connectors.ms_todo import MSTodoConnector
from app.db import session_scope
from app.models import Event
from app.services.sync_engine import SyncEngine
from app.timeutil import utcnow

TITLE = "[自检] 待办勾掉要同步回客户端"


async def pick_connector() -> MSTodoConnector:
    engine = SyncEngine()
    for _user_id, connectors in engine._scopes():
        for item in connectors:
            if item.name == "microsoft_todo" and isinstance(item, MSTodoConnector):
                try:
                    await item.list_options()
                except Exception:  # noqa: BLE001
                    continue
                return item
    raise SystemExit("no usable microsoft_todo connector")


def failed(step: str, detail: str) -> None:
    print(f"FAIL {step}: {detail}")
    raise SystemExit(1)


async def main() -> None:
    conn = await pick_connector()
    engine = SyncEngine()
    ok: list[str] = []

    todo_list, task = await conn.create_task(TITLE, due=utcnow() + timedelta(days=1))
    list_id, task_id = todo_list["id"], task["id"]
    print(f"1) 待办里建好了任务：{task['title'][:24]}… (list={todo_list.get('displayName')})")
    ok.append("create")

    await engine.run(trigger="selfcheck:create", sources=["microsoft_todo"])
    with session_scope() as session:
        row = session.exec(select(Event).where(Event.source_id.contains(task_id))).first()
        if row is None:
            failed("2) 首次同步", "本地没有生成对应事件")
        event_id, local_title = row.id, row.title
        if row.status != "pending":
            failed("2) 首次同步", f"新任务的状态是 {row.status}")
        # 假装用户在客户端改过这行：这样「对面更晚动过」这条规则才真的被考到
        row.local_override = True
        row.title = f"{TITLE}（我改过的标题）"
        row.updated_at = utcnow() - timedelta(days=1)
        session.add(row)
    print(f"2) 首次同步 OK：本地 {event_id[:12]}… pending，已标成「本地改过」")
    ok.append("fetch")

    # 直接经 Graph 勾掉 = 你在手机上勾掉它
    await conn.set_completed(task_id, list_id, True)
    await asyncio.sleep(2)
    print("3) 已直接经 Graph 把待办任务标成 completed（模拟手机端勾掉）")
    ok.append("tick-remote")

    await engine.run(trigger="selfcheck:tick", sources=["microsoft_todo"])
    with session_scope() as session:
        row = session.exec(select(Event).where(Event.id == event_id)).first()
        if row is None:
            failed("4) 第二次同步", "本地事件不见了")
        if row.status != "completed":
            failed("4) 第二次同步", f"本地还是 {row.status} —— 待办里的勾选没同步过来")
        if row.title != f"{TITLE}（我改过的标题）":
            failed("4) 第二次同步", f"本地标题被覆盖成 {row.title!r}")
        print(f"4) 第二次同步 OK：本地已 completed，本地标题仍受保护（{row.title[:20]}…）")
    ok.append("pull-back")

    # 收尾：把自检留下的东西清干净
    await conn._send("DELETE", f"{conn.settings.graph_base_url.rstrip('/')}/me/todo/lists/{list_id}/tasks/{task_id}")
    with session_scope() as session:
        row = session.exec(select(Event).where(Event.id == event_id)).first()
        if row is not None:
            session.delete(row)
    print("5) 已清理（待办任务 + 本地事件）")

    print(f"\nPASS 待办勾掉 → 客户端划掉：{' / '.join(ok)}")


asyncio.run(main())
