"""线上自检：① 课表事件现在带 teacher/week；② 调度器报了整轮 + 待办两个间隔。"""

from __future__ import annotations

import json
import urllib.request

from sqlmodel import select

from app.db import session_scope
from app.models import Event
from app.schemas import EventOut


def main() -> None:
    with session_scope() as session:
        row = session.exec(
            select(Event).where(Event.source == "tju_schedule").order_by(Event.start_time)
        ).first()
        if row is None:
            print("FAIL 库里没有课表事件")
            raise SystemExit(1)
        payload = EventOut.from_event(row).model_dump(mode="json")
    print(
        "课表事件字段：",
        json.dumps(
            {
                key: payload[key]
                for key in ("title", "start_time", "end_time", "location", "periods", "teacher", "week", "source")
            },
            ensure_ascii=False,
        ),
    )
    missing = [key for key in ("teacher", "week", "periods") if payload.get(key) in (None, "", [])]
    if missing:
        print(f"FAIL 缺少字段：{missing}")
        raise SystemExit(1)
    print("OK 课表事件带上了 periods / teacher / week")

    # 本机 API：拿状态里的调度间隔（token 从 .env 读，不打印）
    token = ""
    with open("/var/www/schedule/.env", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("ADMIN_TOKEN="):
                token = line.split("=", 1)[1].strip()
    request = urllib.request.Request(
        "http://127.0.0.1:8010/api/status", headers={"X-Admin-Token": token, "X-Subscribe-Token": token}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        status = json.loads(response.read())
    scheduler = status.get("scheduler") or {}
    print(
        "调度器：",
        json.dumps(
            {
                key: scheduler.get(key)
                for key in ("running", "interval_minutes", "todo_interval_minutes", "next_run", "last_run")
            },
            ensure_ascii=False,
        ),
    )
    if not scheduler.get("todo_interval_minutes"):
        print("FAIL 待办快通道没生效（todo_interval_minutes 为空）")
        raise SystemExit(1)
    print("OK 整轮 + 待办快通道都在跑")


main()
