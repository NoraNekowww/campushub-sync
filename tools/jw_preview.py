"""只读预览：把已导入课表生成的事件按课程列出来（周次→日期），不登录、不改数据。

    cd /var/www/schedule/backend && DATA_DIR=/var/www/schedule/data \
      /var/www/schedule/venv/bin/python /var/www/schedule/tools/jw_preview.py [课程名]
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/var/www/schedule/backend")
os.environ.setdefault("DATA_DIR", "/var/www/schedule/data")

from app.api.tju import _connector  # noqa: E402
from app.config import get_settings  # noqa: E402

WANT = sys.argv[1] if len(sys.argv) > 1 else ""

settings = get_settings()
print("horizon_days =", settings.horizon_days, "| total_weeks(settings) =", settings.semester_total_weeks)

conn = _connector()
print("semester =", conn.semester.summary())
fetched = conn._imported_result()
print("events =", len(fetched.events), "| detail =", fetched.detail)

by_title: dict[str, list] = {}
for event in fetched.events:
    by_title.setdefault(str(getattr(event, "title", "")), []).append(event)

for title in sorted(by_title):
    rows = by_title[title]
    if WANT and WANT not in title:
        continue
    print("\n%s  —— %d 场" % (title, len(rows)))
    seen_weeks: list[int] = []
    for event in sorted(rows, key=lambda e: str(getattr(event, "start_time", ""))):
        raw = json.loads(getattr(event, "raw", "") or "{}")
        week = raw.get("week")
        seen_weeks.append(week)
        print(
            "    w%-3s d%s p%s  %s → %s  %s"
            % (
                week,
                raw.get("weekday"),
                raw.get("periods"),
                getattr(event, "start_time", ""),
                getattr(event, "end_time", ""),
                getattr(event, "location", "") or "",
            )
        )
    print("    周次集合: %s" % (sorted(set(seen_weeks)),))
