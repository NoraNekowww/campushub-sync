"""端到端探针：在应用里给微软待办新建日程 → 划掉 → 回读微软确认 → 清理。

在服务器上跑（用 owner 的管理员令牌走公网 https，因为会话 cookie 是 Secure）：

    cd /var/www/schedule/backend && /var/www/schedule/venv/bin/python /tmp/t_ms_write.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE = "https://nzlab.online/schedule/api"
sys.path.insert(0, "/var/www/schedule/backend")
TZ = "Asia/Shanghai"


def load_token() -> str:
    """从服务端 .env 取管理员令牌（只用于本探针，不打印）。"""
    with open("/var/www/schedule/.env", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


HEADERS = {"X-Admin-Token": load_token(), "Content-Type": "application/json"}


def call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:400]


async def verify_and_clean(event_id: str) -> None:
    """直接问微软：那条任务是不是真的完成了，然后删掉测试任务。"""
    from app.config import get_settings
    from app.connectors import build_connectors
    from app.db import bind_scope, session_scope
    from app.models import Event

    bind_scope(1)  # owner 账号
    settings = get_settings()
    with session_scope() as session:
        row = session.get(Event, event_id)
        raw = row.raw_dict() if row is not None else {}
        source_id = row.source_id if row is not None else ""
    list_id = raw.get("listId") if isinstance(raw, dict) else None
    print("local raw listId:", list_id, "| source_id:", source_id)
    if not (list_id and source_id):
        print("!! 本地没记住清单 id —— 反向推送会失败")
        return

    connector = next(c for c in build_connectors(settings) if c.name == "microsoft_todo")
    base = settings.graph_base_url.rstrip("/")
    task_id = source_id.split("#", 1)[0]
    url = f"{base}/me/todo/lists/{list_id}/tasks/{task_id}"
    task = await connector._get(url)
    print("微软端状态:", task.get("status"), "| completedDateTime:", task.get("completedDateTime"))

    await connector._send("DELETE", url)
    print("已删除微软端的测试任务")

    with session_scope() as session:
        row = session.get(Event, event_id)
        if row is not None:
            session.delete(row)
    print("已删除本地测试日程")


async def main() -> int:
    status, lists = call("GET", "/events/ms/lists")
    print("GET /events/ms-lists ->", status, lists)
    if status != 200 or not isinstance(lists, dict) or not lists.get("connected"):
        return 1

    start = (datetime.now(ZoneInfo(TZ)) + timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )
    status, event = call(
        "POST",
        "/events/ms/task",
        {
            "title": "【测试】Hermes 反向写入",
            "start": start.isoformat(),
            "note": "campushub-sync 的测试日程，会自动删除",
            "importance": "normal",
        },
    )
    shown = {k: event.get(k) for k in ("id", "source", "status", "title")} if isinstance(event, dict) else event
    print("POST /events/ms-task ->", status, shown)
    if status != 201 or not isinstance(event, dict):
        return 1
    event_id = event["id"]

    status, patched = call("PATCH", f"/events/{event_id}", {"status": "completed"})
    got = {k: patched.get(k) for k in ("status", "ms_sync")} if isinstance(patched, dict) else patched
    print("PATCH 划掉 ->", status, got)
    status, again = call("GET", f"/events/{event_id}")
    print("GET 回读本地状态 ->", status, again.get("status") if isinstance(again, dict) else again)

    await verify_and_clean(event_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
