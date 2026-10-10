"""真实导入 + **不推微软**地预览生成的事件（验证周次/星期/日期落点）。

    cd /var/www/schedule/backend && DATA_DIR=/var/www/schedule/data \
      /var/www/schedule/venv/bin/python /var/www/schedule/tools/jw_import_try.py 5
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, "/var/www/schedule/backend")
os.environ.setdefault("DATA_DIR", "/var/www/schedule/data")

WEEK = int(sys.argv[1]) if len(sys.argv) > 1 else 5
SYNC = len(sys.argv) > 2 and sys.argv[2] == "sync"

from app.api.tju import _connector, _jw_import  # noqa: E402
from app.db import KVStore  # noqa: E402


def ev_str(event) -> str:
    start = getattr(event, "start", None) or getattr(event, "start_time", None)
    end = getattr(event, "end", None) or getattr(event, "end_time", None)
    return "%s → %s  %-28s %s" % (start, end, getattr(event, "title", ""), getattr(event, "location", "") or "")


async def run() -> None:
    creds = KVStore().get("tju.jw_credentials") or {}
    if not creds.get("username"):
        raise SystemExit("no saved credentials")
    result = await _jw_import(
        creds["username"],
        creds["password"],
        save=False,
        run_sync=SYNC,
        total_weeks=None,
        via="cas",
        week=WEEK,
    )
    detail = result.detail or {}
    disc = detail.get("discovered") or {}
    print("message           :", result.message)
    print("week / source     :", disc.get("week"), "|", disc.get("week_source"))
    print("term_start_source :", detail.get("term_start_source"))
    print("warning           :", detail.get("warning"))
    print("semester          :", detail.get("semester"))
    print("import meta       :", detail.get("import"))


def preview() -> None:
    fetched = _connector()._imported_result()
    events = sorted(
        fetched.events,
        key=lambda e: str(getattr(e, "start", None) or getattr(e, "start_time", "")),
    )
    print("\n生成事件总数 :", len(events))
    print("fetch detail :", fetched.detail)
    for event in events[:6]:
        print("   ", ev_str(event))
    by_title: dict[str, list] = {}
    for event in events:
        by_title.setdefault(str(getattr(event, "title", "")), []).append(event)
    print()
    for name in ("微积分I", "英语听说", "英语读写译", "51单片机", "健康教育"):
        rows = by_title.get(name) or []
        if rows:
            print("  %-10s %2d 场 | 首 %s | 末 %s" % (
                name, len(rows), ev_str(rows[0])[:19], ev_str(rows[-1])[:19],
            ))


asyncio.run(run())
preview()
