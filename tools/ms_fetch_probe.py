"""Run the real MSTodoConnector.fetch() on the server and print a traceback + field shapes.

Server-side diagnostic. Prints no tokens.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback

sys.path.insert(0, "/var/www/schedule/backend")

from app.connectors.ms_todo import MSTodoConnector  # noqa: E402
from app.config import get_settings  # noqa: E402


async def main() -> None:
    settings = get_settings()
    conn = MSTodoConnector(settings)
    state = conn.auth_state()
    print("auth:", {k: state.get(k) for k in ("authorized", "account", "expires_in")})
    print("list_id_list:", repr(settings.list_id_list))
    try:
        result = await conn.fetch()
        print("OK events:", len(result.events))
        for ev in result.events[:15]:
            print("  -", ev.start_time, "|", ev.title, "|", ev.location, "|", ev.status)
        print("detail:", json.dumps(result.detail, ensure_ascii=False)[:500])
        return
    except Exception:
        print("!!! fetch() raised:")
        traceback.print_exc()

    print("=== 字段类型诊断 ===")
    try:
        lists = await conn._lists()
        print("lists:", len(lists), [(str(x.get("id"))[:10], x.get("displayName")) for x in lists])
        base = settings.graph_base_url.rstrip("/")
        for lst in lists[:2]:
            tasks = await conn._paged(f"{base}/me/todo/lists/{lst['id']}/tasks", {"$top": 100})
            print(f"tasks in {lst.get('displayName')}:", len(tasks))
            for task in tasks[:3]:
                print("  keys:", sorted(task))
                for field in ("dueDateTime", "body", "recurrence", "completedDateTime", "reminderDateTime", "importance", "status"):
                    value = task.get(field)
                    print(f"    {field}: {type(value).__name__} = {json.dumps(value, ensure_ascii=False)[:140] if value is not None else None}")
    except Exception:
        traceback.print_exc()


asyncio.run(main())
