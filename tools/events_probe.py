"""Dump (and optionally clean) the deployed CampusHub SQLite DB — server-side, read-only by default.

Usage on the server:
    /var/www/schedule/venv/bin/python /tmp/events_probe.py          # report only
    /var/www/schedule/venv/bin/python /tmp/events_probe.py clean    # drop stale rows
"""

from __future__ import annotations

import sqlite3
import sys

DB = "/var/www/schedule/data/campushub.db"
con = sqlite3.connect(DB)

if "clean" in sys.argv:
    first = con.execute("delete from events where source = 'tju_schedule'").rowcount
    print("删除 tju_schedule（演示课程）行:", first)
    second = con.execute("delete from events where source = 'microsoft_todo' and status = 'completed'").rowcount
    print("删除 microsoft_todo 已完成行:", second)
    con.commit()

print("tables:", [row[0] for row in con.execute("select name from sqlite_master where type='table'")])
print("by source:", con.execute("select source, count(*) from events group by source order by 2 desc").fetchall())
print("--- 前 30 条 (按开始时间) ---")
for row in con.execute("select source, title, start_time, status from events order by start_time limit 30"):
    print("  ", row)
print("--- 统计 ---")
print("total:", con.execute("select count(*) from events").fetchone()[0])
print("range:", con.execute("select min(start_time), max(start_time) from events").fetchone())
print("connector_logs:", con.execute("select * from connector_logs").fetchall()[:12])
