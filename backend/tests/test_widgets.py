"""Test /api/widgets/today for Android and PWA widgets."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def test_widget_today_endpoint(client, admin_headers):
    # 1. 验证接口可访问
    resp = client.get("/api/widgets/today", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert "date" in data
    assert "weekday" in data
    assert "classes" in data
    assert "deadlines" in data

    # 2. 支持通过 query token 访问（小组件免 Header 调用）
    token = admin_headers.get("X-Admin-Token")
    resp_query = client.get(f"/api/widgets/today?token={token}")
    assert resp_query.status_code == 200
    assert resp_query.json()["ok"] is True

    # 3. 添加一条今日事件，验证小组件能读取到
    tz = ZoneInfo(get_settings().timezone)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    payload = {
        "title": "Widget测试课",
        "start_time": f"{today_str}T14:00:00+08:00",
        "end_time": f"{today_str}T15:30:00+08:00",
        "location": "45楼B101",
    }
    create_resp = client.post("/api/events", json=payload, headers=admin_headers)
    assert create_resp.status_code == 201

    resp_after = client.get(f"/api/widgets/today?token={token}")
    assert resp_after.status_code == 200
    classes = resp_after.json()["classes"]
    assert any(c["title"] == "Widget测试课" and c["location"] == "45楼B101" for c in classes)
