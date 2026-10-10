"""线上实测：删掉一条日程 → 它从订阅日历（ICS）里消失，并回一条「撤下」墓碑。

只挑 feed 里本来就有的那条（STATUS:CONFIRMED），跑完立刻撤销，站长数据原样不动。
用法（令牌都在服务器 .env 里，不从命令行传）：

    ssh host 'cd /var/www/schedule && venv/bin/python -' < tools/check-feed-hide.py
"""

from __future__ import annotations

import json
import re
import urllib.request

ENV = "/var/www/schedule/.env"
API = "http://127.0.0.1:8010/api"


def env(key: str) -> str:
    with open(ENV, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


ADMIN = env("ADMIN_TOKEN")
SUB = env("SUBSCRIBE_TOKEN")


def call(path: str, method: str = "GET", body=None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        method=method,
        data=data,
        headers={"X-Admin-Token": ADMIN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode() or "{}")


def feed() -> tuple[str, str, str]:
    req = urllib.request.Request(f"{API}/subscribe/calendar.ics?token={SUB}")
    with urllib.request.urlopen(req) as res:
        return (
            res.headers.get("X-Event-Count", "?"),
            res.headers.get("X-Cancelled-Count", "?"),
            res.read().decode(),
        )


def entries(raw: str) -> dict[str, str]:
    """ICS 里每条 VEVENT 的 (X-CAMPUSHUB-ID → STATUS)。"""
    found: dict[str, str] = {}
    for chunk in raw.split("BEGIN:VEVENT")[1:]:
        block = chunk.split("END:VEVENT")[0]
        ident = re.search(r"X-CAMPUSHUB-ID:(.+)", block)
        status = re.search(r"STATUS:(\w+)", block)
        if ident:
            found[ident.group(1).strip()] = status.group(1) if status else ""
    return found


def main() -> int:
    visible, cancelled, raw = feed()
    print(f"起点：可见 {visible} 条，墓碑 {cancelled} 条")
    listed = entries(raw)

    target = next(
        (
            item
            for item in call("/events?limit=200")["items"]
            if listed.get(item["id"]) == "CONFIRMED"
        ),
        None,
    )
    if target is None:
        print("feed 里没有可测的条目，放弃")
        return 1
    ident = target["id"]
    print(f"选中：source={target['source']} deadline={target['is_deadline']} 起点STATUS={listed[ident]}")

    hidden = call(f"/events/{ident}", method="DELETE")
    visible2, cancelled2, raw2 = feed()
    after = entries(raw2)
    print(f"删除后：可见 {visible2} 条，墓碑 {cancelled2} 条，该条 STATUS={after.get(ident)}")
    print(f"        DELETE 返回 hidden={hidden.get('hidden')}（软删除，行还在）")

    back = call(f"/events/{ident}", method="PATCH", body={"hidden": False})
    visible3, cancelled3, raw3 = feed()
    restored = entries(raw3)
    print(f"撤销后：可见 {visible3} 条，墓碑 {cancelled3} 条，该条 STATUS={restored.get(ident)}")
    print(f"        PATCH 返回 hidden={back.get('hidden')}")

    ok = (
        listed[ident] == "CONFIRMED"
        and after.get(ident) == "CANCELLED"
        and restored.get(ident) == "CONFIRMED"
        and int(visible2) == int(visible) - 1
        and int(cancelled2) == int(cancelled) + 1
        and int(visible3) == int(visible)
    )
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
