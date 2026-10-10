"""End-to-end API behaviour against the demo connector (no network)."""

from __future__ import annotations

from datetime import date, timedelta

from icalendar import Calendar


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

    assert client.delete(f"/api/events/{body['id']}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/events/{body['id']}", headers=admin_headers).status_code == 404


def test_external_events_cannot_be_deleted(client, admin_headers):
    client.post("/api/sync", headers=admin_headers)
    event = client.get("/api/events", headers=admin_headers).json()["items"][0]
    response = client.delete(f"/api/events/{event['id']}", headers=admin_headers)
    assert response.status_code == 409


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


def test_sync_logs_endpoint(client, admin_headers):
    client.post("/api/sync", headers=admin_headers)
    logs = client.get("/api/sync/logs", headers=admin_headers).json()
    assert logs["runs"][0]["trigger"] == "api"
    assert logs["runs"][0]["connectors"][0]["name"] == "demo"


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
