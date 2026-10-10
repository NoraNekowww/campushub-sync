"""取 TaskActivity_New_Ext.js（教务用它把周次位图渲染成"(第n周-第m周)"）。

    DATA_DIR=/var/www/schedule/data /var/www/schedule/venv/bin/python ../../tools/jw_get_js.py
"""

from __future__ import annotations

import asyncio
import io
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATA_DIR", "/var/www/schedule/data")

from app.connectors import tju_cas as C  # noqa: E402
from app.db import KVStore  # noqa: E402

OUT = "/tmp/jw_dump"


async def main() -> None:
    creds = KVStore().get("tju.jw_credentials") or {}
    user, pwd = creds.get("username") or "", creds.get("password") or ""
    if not (user and pwd):
        raise SystemExit("库里没有凭据")
    client = await C._login(user, pwd, attempts=3, timeout=30)
    print("登录 OK")
    path = "/static/scripts/course/TaskActivity_New_Ext.js?v4.28"
    resp = await C._eams_get(client, path)
    text = resp.text
    print("%s -> %d bytes" % (path, len(text)))
    os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(OUT, "TaskActivity_New_Ext.js"), "w", encoding="utf-8").write(text)
    print("\n=== 含 '周' / week 的行 ===")
    for line in text.splitlines():
        low = line.lower()
        if "周" in line or "week" in low:
            print("  ", " ".join(line.split())[:200])


asyncio.run(main())
