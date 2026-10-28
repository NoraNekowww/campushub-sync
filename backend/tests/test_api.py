"""End-to-end API behaviour against the demo connector (no network)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from icalendar import Calendar

from app import accounts
from app.api import events as events_api
from app.config import get_settings
from app.connectors.ms_todo import MSTodoConnector
from app.db import session_scope
from app.models import Event
from app.timeutil import utcnow


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_events_require_admin_token(client):
    assert client.get("/api/events").status_code == 401
    assert client.get("/api/events", headers={"X-Admin-Token": "nope"}).status_code == 401


def test_sync_then_query_timeline(client, admin_headers):
    sync = client.post("/api/sync", headers=admin_headers)
    assert sync.status_code == 200, sync.text
    payload = sync.json()
    assert payload["ok"] is True
    assert payload["fetched"] > 0
    assert payload["created"] == payload["fetched"]

    response = client.get("/api/events", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 10
    items = body["items"]
    assert any(item["is_deadline"] for item in items)
    assert any(not item["is_deadline"] for item in items)
    sources = {item["source"] for item in items}
    assert sources == {"microsoft_todo", "tju_schedule"}

    # timestamps are rendered in Asia/Shanghai
    assert all(item["start_time"].endswith("+08:00") for item in items)

    # ordering: earliest first
    starts = [item["start_time"] for item in items]
    assert starts == sorted(starts)

    # filters
    deadlines = client.get("/api/events?is_deadline=true", headers=admin_headers).json()
    assert all(item["is_deadline"] for item in deadlines["items"])
    classes = client.get("/api/events?source=tju_schedule", headers=admin_headers).json()
    assert all(item["source"] == "tju_schedule" for item in classes["items"])
    search = client.get(
        "/api/events?search=数据结构", headers=admin_headers
    ).json()
    assert search["items"] and all("数据结构" in item["title"] for item in search["items"])

    today = date.today().isoformat()
    windowed = client.get(
        f"/api/events?start_date={today}&end_date={(date.today() + timedelta(days=1)).isoformat()}",
        headers=admin_headers,
    ).json()
    assert all(item["start_time"][:10] in {today, (date.today() + timedelta(days=1)).isoformat()} for item in windowed["items"])


def test_second_sync_updates_instead_of_duplicating(client, admin_headers):
    client.post("/api/sync", headers=admin_headers)
    first = client.get("/api/events", headers=admin_headers).json()
    client.post("/api/sync", headers=admin_headers)
    second = client.get("/api/events", headers=admin_headers).json()
    assert second["total"] == first["total"]
    assert all(item["id"] for item in second["items"])


def test_patch_completion_is_sticky_across_sync(client, admin_headers):
    client.post("/api/sync", headers=admin_headers)
    events = client.get("/api/events?is_deadline=true", headers=admin_headers).json()["items"]
    target = events[0]

    patched = client.patch(
        f"/api/events/{target['id']}", json={"status": "completed"}, headers=admin_headers
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "completed"
    assert patched.json()["local_override"] is True

    assert client.patch("/api/events/does-not-exist", json={"status": "completed"}, headers=admin_headers).status_code == 404

    client.post("/api/sync", headers=admin_headers)
    after = client.get(f"/api/events/{target['id']}", headers=admin_headers).json()
    assert after["status"] == "completed"


def test_custom_event_lifecycle(client, admin_headers):
    created = client.post(
        "/api/events",
        json={
            "title": "小组会",
            "start_time": "2026-10-15T19:00:00",
            "end_time": "2026-10-15T20:30:00",
            "location": "55 教 A406",
            "is_deadline": False,
            "reminder_minutes": 30,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "custom"
    assert body["start_time"] == "2026-10-15T19:00:00+08:00"

    bad = client.post(
        "/api/events",
        json={"title": "时间倒置", "start_time": "2026-10-15T19:00:00", "end_time": "2026-10-15T18:00:00"},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # 删掉 = 软删除（从日历里拿掉，可撤销），不是物理删
    deleted = client.delete(f"/api/events/{body['id']}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["hidden"] is True
    assert client.get(f"/api/events/{body['id']}", headers=admin_headers).json()["hidden"] is True
    listing = client.get("/api/events", headers=admin_headers).json()
    assert all(item["id"] != body["id"] for item in listing["items"])

    restored = client.patch(
        f"/api/events/{body['id']}", json={"hidden": False}, headers=admin_headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["hidden"] is False
    listing = client.get("/api/events", headers=admin_headers).json()
    assert any(item["id"] == body["id"] for item in listing["items"])


def test_external_event_delete_is_a_permanent_local_hide(client, admin_headers):
    """右滑删掉课表/待办来的日程：本地隐藏，且下一次同步不会把它拉回来。"""
    client.post("/api/sync", headers=admin_headers)
    event = client.get("/api/events", headers=admin_headers).json()["items"][0]
    assert event["source"] != "custom"

    response = client.delete(f"/api/events/{event['id']}", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["hidden"] is True

    client.post("/api/sync", headers=admin_headers)
    listed = {item["id"] for item in client.get("/api/events", headers=admin_headers).json()["items"]}
    assert event["id"] not in listed

    # 撤销：恢复后又能看见
    assert (
        client.patch(
            f"/api/events/{event['id']}", json={"hidden": False}, headers=admin_headers
        ).status_code
        == 200
    )
    listed = {item["id"] for item in client.get("/api/events", headers=admin_headers).json()["items"]}
    assert event["id"] in listed


def test_status_and_config(client, admin_headers):
    client.post("/api/sync", headers=admin_headers)
    status = client.get("/api/status", headers=admin_headers)
    assert status.status_code == 200
    body = status.json()
    assert body["ok"] is True
    assert body["last_sync"]["ok"] is True
    assert body["counts"]["total"] > 0
    assert body["connectors"][0]["name"] == "demo"
    assert body["scheduler"]["running"] is False  # disabled in tests

    config = client.get("/api/config", headers=admin_headers).json()
    assert config["auth_required"] is True
    assert config["subscribe"]["token" if "token" in config["subscribe"] else "url"].startswith("http")
    assert config["subscribe"]["url"].endswith("/api/subscribe/calendar.ics?token=test-sub")
    # the webcal variant must swap the scheme, never nest it ("webcal://http://")
    webcal = config["subscribe"]["webcal"]
    assert webcal.startswith("webcal://")
    assert "webcal://http" not in webcal
    assert webcal.endswith("/api/subscribe/calendar.ics?token=test-sub")
    assert "demo" in config["connectors"]


def test_calendar_feed_requires_token_and_emits_ics(client, admin_headers):
    client.post("/api/sync", headers=admin_headers)

    assert client.get("/api/subscribe/calendar.ics").status_code == 403
    assert client.get("/api/subscribe/calendar.ics?token=wrong").status_code == 403

    response = client.get("/api/subscribe/calendar.ics?token=test-sub")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "attachment" in response.headers["content-disposition"]
    etag = response.headers["etag"]
    assert int(response.headers["x-event-count"]) > 0

    parsed = Calendar.from_ical(response.content)
    vevents = list(parsed.walk("VEVENT"))
    assert len(vevents) == int(response.headers["x-event-count"])
    assert any(component.walk("VALARM") for component in vevents)
    categories = [
        component.get("CATEGORIES").to_ical().decode()
        for component in vevents
        if component.get("CATEGORIES") is not None
    ]
    assert "DDL" in categories and "课程" in categories

    # conditional request
    cached = client.get(
        "/api/subscribe/calendar.ics?token=test-sub", headers={"If-None-Match": etag}
    )
    assert cached.status_code == 304


def _feed(client, **params):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    url = "/api/subscribe/calendar.ics?token=test-sub"
    if query:
        url = f"{url}&{query}"
    response = client.get(url)
    assert response.status_code == 200, response.text
    return Calendar.from_ical(response.content)


def _feed_ids(calendar, status=None):
    """feed 里出现的事件 id（可按 STATUS 过滤）。"""
    ids = set()
    for component in calendar.walk("VEVENT"):
        if status is not None and str(component.get("STATUS")) != status:
            continue
        ids.add(str(component["X-CAMPUSHUB-ID"]))
    return ids


def test_completed_and_deleted_events_leave_the_feed(client, admin_headers):
    """划掉的、删掉的日程都不该出现在订阅出去的日历里。

    划掉/删掉只发一条 ``STATUS:CANCELLED`` 墓碑（同一个 UID），客户端才会把它从
    手机日历里删掉 —— 订阅源里单纯「不再出现」的条目，有些客户端会一直留着。
    """
    # start_time 采用动态相对于当前测试时间的未来时刻，避免写死历史日期导致超出 calendar.ics 的 days_past (7天) 窗口
    from datetime import datetime, timezone, timedelta
    test_start = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    created = client.post(
        "/api/events",
        json={
            "title": "交实验报告",
            "start_time": test_start,
            "is_deadline": True,
            "reminder_minutes": 60,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    assert event_id in _feed_ids(_feed(client), "CONFIRMED")

    # 划掉 → 默认不再出现在日历里，并回一条墓碑
    done = client.patch(
        f"/api/events/{event_id}", json={"status": "completed"}, headers=admin_headers
    )
    assert done.status_code == 200, done.text
    calendar = _feed(client)
    assert event_id not in _feed_ids(calendar, "CONFIRMED")
    assert event_id in _feed_ids(calendar, "CANCELLED")

    # 勾回来 → 又出现
    client.patch(
        f"/api/events/{event_id}", json={"status": "pending"}, headers=admin_headers
    )
    assert event_id in _feed_ids(_feed(client), "CONFIRMED")

    # 划掉后「还想留在日历里」：显式 include_completed=true
    client.patch(
        f"/api/events/{event_id}", json={"status": "completed"}, headers=admin_headers
    )
    assert event_id in _feed_ids(_feed(client, include_completed="true"), "CONFIRMED")

    # 删掉（软删除）→ 同样撤下，并且能撤销
    client.delete(f"/api/events/{event_id}", headers=admin_headers)
    calendar = _feed(client)
    assert event_id not in _feed_ids(calendar, "CONFIRMED")
    assert event_id in _feed_ids(calendar, "CANCELLED")

    client.patch(
        f"/api/events/{event_id}",
        json={"hidden": False, "status": "pending"},
        headers=admin_headers,
    )
    assert event_id in _feed_ids(_feed(client), "CONFIRMED")


def test_feed_only_exports_the_owners_events(client, admin_headers):
    """订阅令牌是站长自己的：别人的课表不该混进他的手机日历。"""
    client.post("/api/sync", headers=admin_headers)
    mine = _feed_ids(_feed(client))
    assert mine, "站长自己的日程应该在 feed 里"

    with session_scope() as session:
        other = accounts.create_user(session, "lzy", "another-good-one")
        session.add(
            Event(
                id="other-account-event",
                source="tju_schedule",
                source_id="other-1",
                title="别人的课",
                start_time=datetime.now(timezone.utc) + timedelta(days=1),
                status="pending",
                priority=5,
                updated_at=datetime.now(timezone.utc),
                user_id=other.id,
            )
        )
        session.commit()

    ids = _feed_ids(_feed(client))
    assert "other-account-event" not in ids
    assert mine <= ids  # 自己的还在（没被别人的顶掉）


def test_sync_logs_endpoint(client, admin_headers):
    client.post("/api/sync", headers=admin_headers)
    logs = client.get("/api/sync/logs", headers=admin_headers).json()
    assert logs["runs"][0]["trigger"] == "api"
    # 连接器名按账号加后缀（demo#1），多租户之后不再是无主的 "demo"
    assert logs["runs"][0]["connectors"][0]["name"].startswith("demo")


def test_schedule_upload_and_semester(client, admin_headers, sample_ics):
    upload = client.post(
        "/api/schedule/upload",
        files={"file": ("timetable.ics", sample_ics, "text/calendar")},
        headers=admin_headers,
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["detail"]["events_in_file"] == 2

    preview = client.get("/api/schedule/preview", headers=admin_headers)
    assert preview.status_code == 200
    assert preview.json()["detail"]["raw_events"] == 2

    semester = client.put(
        "/api/schedule/semester",
        json={"name": "2026 秋", "start_date": "2026-09-07", "total_weeks": 16, "holidays": ["2026-10-01"]},
        headers=admin_headers,
    )
    assert semester.status_code == 200
    detail = semester.json()["detail"]["semester"]
    assert detail["start_date"] == "2026-09-07" and detail["total_weeks"] == 16

    assert client.delete("/api/schedule/upload", headers=admin_headers).status_code == 200


def test_ms_auth_endpoints_report_missing_client_id(client, admin_headers):
    status = client.get("/api/auth/ms/status", headers=admin_headers)
    assert status.status_code == 200
    assert status.json()["detail"]["authorized"] is False
    started = client.post("/api/auth/ms/device/start", headers=admin_headers)
    assert started.status_code == 400  # MS_CLIENT_ID not configured in tests


def test_ms_task_puts_location_in_note_and_reads_it_back(client, admin_headers, monkeypatch):
    """网页端建待办：地点并进备注（微软那边看得见），本地读回来仍是一个独立地点。"""
    captured: dict = {}
    real = MSTodoConnector(get_settings())

    class FakeConnector:
        """假的微软连接器：只把 note 原样收进 body，像 Graph 那样返回任务。"""

        def auth_state(self):
            return {"authorized": True}

        async def create_task(self, title, *, due, list_id=None, note=None, importance=None):
            captured["note"] = note
            task = {
                "id": "t1",
                "title": title,
                "dueDateTime": {
                    "dateTime": due.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
                        "%Y-%m-%dT%H:%M:%S.0000000"
                    ),
                    "timeZone": "Asia/Shanghai",
                },
                "body": {"content": note or "", "contentType": "text"},
                "status": "notStarted",
                "importance": importance or "normal",
                "lastModifiedDateTime": "2026-10-10T00:00:00Z",
            }
            return {"id": "l1", "displayName": "任务"}, task

        def task_event(self, todo_list, task):
            return real.task_event(todo_list, task)

    monkeypatch.setattr(events_api, "_ms_connector", lambda: FakeConnector())

    soon = (utcnow() + timedelta(days=3)).astimezone(ZoneInfo("Asia/Shanghai"))
    response = client.post(
        "/api/events/ms/task",
        headers=admin_headers,
        json={
            "title": "交作业",
            "start": soon.strftime("%Y-%m-%dT%H:%M:%S"),
            "location": "45楼B203",
            "note": "带教材",
        },
    )
    assert response.status_code == 201, response.text
    assert captured["note"] == "📍 45楼B203\n带教材"
    body = response.json()
    assert body["location"] == "45楼B203"
    assert body["description"] == "带教材"


# --------------------------------------------------- 改自己的日程（任何来源）
def _class_event(client, admin_headers):
    """同步一次，取一条教务课表事件出来。"""
    client.post("/api/sync", headers=admin_headers)
    items = client.get("/api/events?source=tju_schedule", headers=admin_headers).json()["items"]
    assert items, "demo 连接器应该产出课表事件"
    return items[0]


def test_edit_class_event_time_note_place_sticks(client, admin_headers):
    """课表也能改（调课 / 换教室 / 加备注），而且下次同步不会把它冲回去。"""
    target = _class_event(client, admin_headers)
    moved = (date.today() + timedelta(days=1)).isoformat()

    patched = client.patch(
        f"/api/events/{target['id']}",
        headers=admin_headers,
        json={
            "title": "数据结构（改到明天）",
            "start_time": f"{moved}T13:30:00",
            "end_time": f"{moved}T15:05:00",
            "location": "55楼A101",
            "description": "记得带笔记本",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["title"] == "数据结构（改到明天）"
    assert body["location"] == "55楼A101"
    assert body["description"] == "记得带笔记本"
    assert body["start_time"] == f"{moved}T13:30:00+08:00"
    assert body["end_time"] == f"{moved}T15:05:00+08:00"
    assert body["local_override"] is True

    # 再同步一次：教务那边的原值不该把用户改的时间 / 地点 / 备注抹掉
    client.post("/api/sync", headers=admin_headers)
    after = client.get(f"/api/events/{target['id']}", headers=admin_headers).json()
    assert after["start_time"] == f"{moved}T13:30:00+08:00"
    assert after["location"] == "55楼A101"
    assert after["description"] == "记得带笔记本"


def test_edit_event_validates_and_can_clear_end_time(client, admin_headers):
    """结束时间不能早于开始时间；``end_time`` 传 null 是「不改」，清空得用 clear_end_time。"""
    target = _class_event(client, admin_headers)

    bad = client.patch(
        f"/api/events/{target['id']}",
        headers=admin_headers,
        json={"start_time": "2026-10-20T15:00:00", "end_time": "2026-10-20T14:00:00"},
    )
    assert bad.status_code == 422

    cleared = client.patch(
        f"/api/events/{target['id']}",
        headers=admin_headers,
        json={"start_time": "2026-10-20T15:00:00", "clear_end_time": True},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["end_time"] is None
    assert cleared.json()["start_time"] == "2026-10-20T15:00:00+08:00"


def test_edit_ms_task_pushes_changes_back(client, admin_headers, monkeypatch):
    """改待办日程（标题 / 时间 / 地点 / 备注）→ 推回微软待办，备注按 📍 行整段重算。"""
    pushed: dict = {}

    class FakeConnector:
        def auth_state(self):
            return {"authorized": True}

        async def update_task(
            self, source_id, list_id, *, title=None, due=None, note=None, importance=None
        ):
            pushed.update(
                {
                    "source_id": source_id,
                    "list_id": list_id,
                    "title": title,
                    "due": due,
                    "note": note,
                }
            )
            return {"id": source_id}

        async def set_completed(self, source_id, list_id, done):  # 没改状态就不该推这个
            raise AssertionError("没改完成状态时不该推 set_completed")

    monkeypatch.setattr(events_api, "_ms_connector", lambda: FakeConnector())

    client.post("/api/sync", headers=admin_headers)
    tasks = client.get("/api/events?source=microsoft_todo", headers=admin_headers).json()["items"]
    assert tasks
    target = tasks[0]

    response = client.patch(
        f"/api/events/{target['id']}",
        headers=admin_headers,
        json={
            "title": "交作业（改）",
            "start_time": "2026-10-20T09:00:00",
            "location": "45楼B203",
            "description": "带教材",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["ms_sync"]["ok"] is True
    assert pushed["title"] == "交作业（改）"
    assert pushed["list_id"] == "demo-list"
    assert pushed["note"] == "📍 45楼B203\n带教材"
    assert pushed["due"].astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M") == (
        "2026-10-20 09:00"
    )


def test_delete_ms_task_also_deletes_it_remotely(client, admin_headers, monkeypatch):
    """删掉一条待办 → 本地隐藏的同时，微软那边那条也真删（用户点名要的）。"""
    deleted: list[tuple[str, str]] = []

    class FakeConnector:
        def auth_state(self):
            return {"authorized": True}

        async def delete_task(self, source_id, list_id):
            deleted.append((source_id, list_id))
            return {}

    monkeypatch.setattr(events_api, "_ms_connector", lambda: FakeConnector())

    client.post("/api/sync", headers=admin_headers)
    target = client.get("/api/events?source=microsoft_todo", headers=admin_headers).json()["items"][0]

    response = client.delete(f"/api/events/{target['id']}", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["hidden"] is True
    assert response.json()["ms_sync"]["ok"] is True
    assert deleted and deleted[0][1] == "demo-list"  # 删的是这条待办所在的清单

    # 撤回来：本地能恢复（微软那边删了就删了，这是明说的取舍）
    restored = client.patch(
        f"/api/events/{target['id']}", json={"hidden": False}, headers=admin_headers
    )
    assert restored.status_code == 200
    assert restored.json()["hidden"] is False


def test_delete_ms_task_survives_remote_failure(client, admin_headers, monkeypatch):
    """微软那边删失败，本地删除照样生效 —— 用户点的删除不能因为远端报错就作废。"""

    class BombConnector:
        def auth_state(self):
            return {"authorized": True}

        async def delete_task(self, source_id, list_id):
            raise RuntimeError("graph 503")

    monkeypatch.setattr(events_api, "_ms_connector", lambda: BombConnector())

    client.post("/api/sync", headers=admin_headers)
    target = client.get("/api/events?source=microsoft_todo", headers=admin_headers).json()["items"][0]

    response = client.delete(f"/api/events/{target['id']}", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["hidden"] is True
    assert response.json()["ms_sync"]["ok"] is False
    assert "RuntimeError" in response.json()["ms_sync"]["error"]


def test_delete_class_event_never_touches_microsoft(client, admin_headers, monkeypatch):
    """课表来源的删除不该碰微软 —— 连连接器都不该去构造。"""

    def explode():  # pragma: no cover - 被调到就是失败
        raise AssertionError("非待办来源的删除不该碰微软连接器")

    monkeypatch.setattr(events_api, "_ms_connector", explode)

    target = _class_event(client, admin_headers)
    response = client.delete(f"/api/events/{target['id']}", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["hidden"] is True
    assert not response.json().get("ms_sync")


def test_create_custom_event_with_recurrence(client, admin_headers):
    """支持添加自定义重复任务：每 N 天/周/月重复一次，共生成 N 条日程。"""
    # 1. 按周重复 3 次（每 2 周重复一次）
    payload_week = {
        "title": "双周组会",
        "start_time": "2026-10-15T14:00:00+08:00",
        "end_time": "2026-10-15T16:00:00+08:00",
        "location": "55楼B204",
        "repeat_frequency": "week",
        "repeat_interval": 2,
        "repeat_count": 3,
    }
    resp = client.post("/api/events", json=payload_week, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["title"] == "双周组会"
    assert created["location"] == "55楼B204"

    # 查询这批生成的事件
    query = client.get("/api/events?search=双周组会", headers=admin_headers)
    assert query.status_code == 200
    items = sorted(query.json()["items"], key=lambda x: x["start_time"])
    assert len(items) == 3
    # 间隔正好是 14 天 (2 周)
    d1 = datetime.fromisoformat(items[0]["start_time"])
    d2 = datetime.fromisoformat(items[1]["start_time"])
    d3 = datetime.fromisoformat(items[2]["start_time"])
    assert (d2 - d1).days == 14
    assert (d3 - d2).days == 14
    # 每次的时长保持为 2 小时
    e1 = datetime.fromisoformat(items[0]["end_time"])
    assert (e1 - d1).total_seconds() == 7200

    # 2. 按月重复 4 次（每 1 个月）
    payload_month = {
        "title": "月度汇报",
        "start_time": "2026-10-31T09:00:00+08:00",
        "repeat_frequency": "month",
        "repeat_interval": 1,
        "repeat_count": 4,
    }
    resp_m = client.post("/api/events", json=payload_month, headers=admin_headers)
    assert resp_m.status_code == 201, resp_m.text
    query_m = client.get("/api/events?search=月度汇报", headers=admin_headers)
    items_m = sorted(query_m.json()["items"], key=lambda x: x["start_time"])
    assert len(items_m) == 4
    # 检查月末自动对齐（10/31 -> 11/30 -> 12/31 -> 01/31）
    dates = [x["start_time"][:10] for x in items_m]
    assert dates == ["2026-10-31", "2026-11-30", "2026-12-31", "2027-01-31"]


def test_batch_update_and_delete_recurring_events(client, admin_headers):
    """批量修改与批量删除：支持仅改当前、改当前及后续、改全系列。"""
    # 1. 先生成 4 次周任务
    payload = {
        "title": "项目例会",
        "start_time": "2026-11-02T14:00:00+08:00",
        "end_time": "2026-11-02T15:30:00+08:00",
        "location": "老会议室",
        "repeat_frequency": "week",
        "repeat_interval": 1,
        "repeat_count": 4,
    }
    client.post("/api/events", json=payload, headers=admin_headers)
    query = client.get("/api/events?search=项目例会", headers=admin_headers)
    items = sorted(query.json()["items"], key=lambda x: x["start_time"])
    assert len(items) == 4
    # 检查 recurrence 元数据正确透传
    assert items[0]["recurrence"]["total"] == 4
    assert items[1]["recurrence"]["index"] == 2

    # 2. 从第 2 个任务开始批量修改：地点改为「新会议室B203」，时间由 14:00 改为 16:00
    target = items[1]
    patch_payload = {
        "title": "项目例会(改)",
        "location": "新会议室B203",
        "start_time": "2026-11-09T16:00:00+08:00",
        "end_time": "2026-11-09T17:30:00+08:00",
        "apply_scope": "future",  # 当前及后续
    }
    p_resp = client.patch(f"/api/events/{target['id']}", json=patch_payload, headers=admin_headers)
    assert p_resp.status_code == 200, p_resp.text

    # 再次查询验证
    query2 = client.get("/api/events?search=项目例会", headers=admin_headers)
    items2 = sorted(query2.json()["items"], key=lambda x: x["start_time"])
    assert len(items2) == 4

    # 第 1 个保持原样：标题不加(改)，地点是老会议室，时间是 14:00
    assert items2[0]["title"] == "项目例会"
    assert items2[0]["location"] == "老会议室"
    assert items2[0]["start_time"].endswith("14:00:00+08:00")

    # 第 2、3、4 个全部批量改为了新地点，且时间全部平移到了 16:00
    for it in items2[1:]:
        assert it["title"] == "项目例会(改)"
        assert it["location"] == "新会议室B203"
        assert it["start_time"].endswith("16:00:00+08:00")
        assert it["end_time"].endswith("17:30:00+08:00")

    # 3. 批量删除：从第 3 个任务开始批量删除（future）
    del_target = items2[2]
    d_resp = client.delete(f"/api/events/{del_target['id']}?apply_scope=future", headers=admin_headers)
    assert d_resp.status_code == 200, d_resp.text

    # 查询可见日程：只剩前 2 个，后 2 个被批量软删除隐藏
    query3 = client.get("/api/events?search=项目例会", headers=admin_headers)
    items3 = [it for it in query3.json()["items"] if not it["hidden"]]
    assert len(items3) == 2


