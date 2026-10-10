"""TJU / WePeiyang connector tests.

The class-table fixture below is copied from the official client's own test
data (``WePeiYang-Android`` → ``schedule2/src/test/.../ConstantData.kt``), so the
parser is pinned to the real payload shape rather than to a guess.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.connectors.tju_api import (
    APP_KEY,
    APP_SECRET,
    TjuApiClient,
    TjuApiError,
    parse_classtable,
    sign_params,
)
from app.connectors.tju_schedule import (
    CLASSTABLE_KEY,
    MODE_KEY,
    TjuScheduleConnector,
    build_semester,
    parse_week_spec,
)
from app.db import KVStore

# --------------------------------------------------------------------- fixtures
#: Trimmed but otherwise verbatim from the official client's fixtures.
SAMPLE = {
    "error_code": -1,
    "message": "",
    "data": {
        "term": "17182",
        "data": [
            {
                "classid": "183",
                "courseid": "2111141",
                "coursename": "毛泽东思想和中国特色社会主义理论体系概论",
                "coursetype": "思想政治理论",
                "coursenature": "必修",
                "credit": "6.0",
                "teacher": "吴兆彤",
                "arrange": [{"week": "单双周", "day": "2", "start": "9", "end": "11", "room": "23楼404"}],
                "week": {"start": "1", "end": "16"},
                "college": "马克思主义学院",
                "campus": "卫津路校区",
                "ext": "",
            },
            {
                "classid": "2988",
                "courseid": "2040599",
                "coursename": "通信网1",
                "coursetype": "专业选修",
                "coursenature": "选修",
                "credit": "2.0",
                "teacher": "徐岩",
                "arrange": [
                    {"week": "单周", "day": "4", "start": "3", "end": "4", "room": "26楼B203"},
                    {"week": "双周", "day": "5", "start": "1", "end": "2", "room": "26楼B110"},
                ],
                "week": {"start": "1", "end": "8"},
                "college": "微电子学院",
                "campus": "北洋园校区",
                "ext": "",
            },
        ],
        "week": 3,
        "term_start": 1520179200,  # 2018-03-05 00:00 +08:00, the Monday of week 1
        "updated_at": "2018-03-20 22:04:07",
    },
}


def sample_payload(term_start: date, *, course: str = "高等数学") -> dict:
    """A one-course payload anchored at ``term_start`` (so events are in range)."""
    stamp = int(datetime(term_start.year, term_start.month, term_start.day,
                         tzinfo=timezone(timedelta(hours=8))).timestamp())
    return {
        "error_code": -1,
        "message": "",
        "data": {
            "term": "26271",
            "data": [
                {
                    "classid": "1",
                    "courseid": "9001",
                    "coursename": course,
                    "teacher": "某老师",
                    "credit": "3.0",
                    "arrange": [{"week": "单双周", "day": "1", "start": "1", "end": "2", "room": "26楼A101"}],
                    "week": {"start": "1", "end": "16"},
                }
            ],
            "week": 1,
            "term_start": stamp,
            "updated_at": "2026-09-01 00:00:00",
        },
    }


def mock_client(settings, handler, **kwargs) -> TjuApiClient:
    return TjuApiClient(settings=settings, transport=httpx.MockTransport(handler), **kwargs)


# ------------------------------------------------------------------ signature
def test_signature_matches_open_platform_algorithm(monkeypatch):
    monkeypatch.setattr("app.connectors.tju_api.time.time", lambda: 1_520_000_000.123)
    params = sign_params({"twtuname": "3018216000", "twtpasswd": "secret"})

    assert params["t"] == "1520000000123"
    assert params["app_key"] == APP_KEY
    # Sorted keys: t, twtpasswd, twtuname — each contributes name + value.
    raw = f"{APP_KEY}t1520000000123twtpasswdsecrettwtuname3018216000{APP_SECRET}"
    assert params["sign"] == hashlib.sha1(raw.encode("utf-8")).hexdigest().upper()


def test_signature_of_empty_params_only_carries_timestamp(monkeypatch):
    monkeypatch.setattr("app.connectors.tju_api.time.time", lambda: 1_520_000_000.0)
    params = sign_params({})
    raw = f"{APP_KEY}t1520000000000{APP_SECRET}"
    assert params["sign"] == hashlib.sha1(raw.encode("utf-8")).hexdigest().upper()


# ---------------------------------------------------------------- week parsing
def test_single_double_week_means_every_week():
    """``单双周`` carries both markers — it must NOT be read as odd weeks."""
    weeks, parity = parse_week_spec("单双周", 16)
    assert parity is None
    assert weeks == set(range(1, 17))


@pytest.mark.parametrize(
    "spec,expected",
    [("单周", set(range(1, 17, 2))), ("双周", set(range(2, 17, 2))), ("1-8单", {1, 3, 5, 7})],
)
def test_week_parity(spec, expected):
    weeks, parity = parse_week_spec(spec, 16)
    assert weeks == expected
    assert parity in {"odd", "even"}


# --------------------------------------------------------------------- parser
def test_parse_classtable_from_real_payload():
    parsed = parse_classtable(SAMPLE)

    assert parsed.term == "17182"
    assert parsed.term_start == date(2018, 3, 5)
    assert parsed.week == 3
    assert {entry.name for entry in parsed.entries} == {
        "毛泽东思想和中国特色社会主义理论体系概论",
        "通信网1",
    }
    # Two arrange rows for 通信网1 (odd weeks / even weeks) + one for the 思政课.
    assert len(parsed.entries) == 3

    politics = next(e for e in parsed.entries if e.name.startswith("毛泽东"))
    assert politics.weekday == 2 and (politics.start_period, politics.end_period) == (9, 11)
    assert politics.weeks == set(range(1, 17))
    assert politics.location == "23楼404"
    assert politics.teacher == "吴兆彤"

    odd_slot, even_slot = [e for e in parsed.entries if e.name == "通信网1"]
    assert odd_slot.weeks == {1, 3, 5, 7}
    assert odd_slot.weekday == 4
    assert even_slot.weeks == {2, 4, 6, 8}
    assert even_slot.weekday == 5
    assert parsed.summary()["courses"] == 2


def test_parse_classtable_reports_upstream_errors():
    with pytest.raises(TjuApiError) as excinfo:
        parse_classtable({"error_code": 40001, "message": "未检测到token，请提供token"})
    assert excinfo.value.kind == "auth_required"


def test_parse_classtable_skips_unusable_rows():
    payload = {"data": {"term": "1", "data": [{"coursename": ""}, {"coursename": "X", "arrange": []}]}}
    parsed = parse_classtable(payload)
    assert parsed.entries == []
    assert parsed.skipped


def test_term_start_derived_from_current_week_when_missing():
    payload = {"data": {"term": "1", "week": 1, "data": [
        {"coursename": "X", "arrange": [{"day": "1", "start": "1", "end": "2"}], "week": {"start": "1", "end": "4"}}
    ]}}
    parsed = parse_classtable(payload)
    today = date.today()
    assert parsed.term_start == today - timedelta(days=today.weekday())


# ------------------------------------------------------------- gate handling
def _handler(status: int, body: str = "", headers: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers=headers or {})

    return handler


NOTICE_HTML = "<html><head><title>403</title></head><body>该网页目前只允许校内访问或您正在进行违规操作</body></html>"


@pytest.mark.parametrize(
    "status,body,headers,kind",
    [
        (302, "", {"location": "http://network-notice.tju.edu.cn/"}, "campus_network"),
        (403, NOTICE_HTML, {}, "campus_network"),
        (200, NOTICE_HTML, {}, "campus_network"),
        (401, '{"error_code":40001,"message":"未检测到token"}', {}, "auth_required"),
        (503, "upstream blew up", {}, "network"),
    ],
)
def test_class_table_failures_are_classified(settings, status, body, headers, kind):
    async def run() -> None:
        client = mock_client(settings, _handler(status, body, headers))
        with pytest.raises(TjuApiError) as excinfo:
            await client.fetch_classtable("token-abc")
        assert excinfo.value.kind == kind

    asyncio.run(run())


def test_legacy_login_reports_wrong_password(settings):
    async def run() -> None:
        payload = json.dumps({"error_code": 40004, "message": "用户名或密码错误"}, ensure_ascii=False)
        client = mock_client(settings, _handler(200, payload))
        with pytest.raises(TjuApiError) as excinfo:
            await client.login_legacy("3018216000", "nope")
        assert excinfo.value.kind == "bad_credentials"

    asyncio.run(run())


@pytest.mark.parametrize("message", ["该(类)用户不存在", "帐号不存在", "密码错误"])
def test_legacy_login_treats_unknown_account_as_credentials(settings, message):
    """The live API phrases a bad login in several ways; none is a protocol error."""
    async def run() -> None:
        payload = json.dumps({"error_code": 40004, "message": message}, ensure_ascii=False)
        client = mock_client(settings, _handler(200, payload))
        with pytest.raises(TjuApiError) as excinfo:
            await client.login_legacy("0000000000", "x")
        assert excinfo.value.kind == "bad_credentials"

    asyncio.run(run())


def test_login_falls_back_to_legacy_api_when_campus_gate_blocks(settings):
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "open.twt.edu.cn" in request.url.host:
                return httpx.Response(302, headers={"location": "http://network-notice.tju.edu.cn/"})
            return httpx.Response(200, json={"error_code": -1, "data": {"token": "legacy-token"}})

        token, source = await mock_client(settings, handler).login("3018216000", "pw")
        assert (token, source) == ("legacy-token", "legacy")

    asyncio.run(run())


def test_login_sends_client_identity_headers(settings):
    async def run() -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update({k.lower(): v for k, v in request.headers.items()})
            return httpx.Response(200, json={"error_code": -1, "data": {"token": "t"}})

        await mock_client(settings, handler).login_legacy("u", "p")
        # Without these two the gateway answers "50003 未绑定的url".
        assert seen["ticket"].startswith("YmFuYW5h")
        assert seen["domain"] == "weipeiyang.twt.edu.cn"

    asyncio.run(run())


def test_probe_reports_campus_gate(settings):
    async def run() -> None:
        client = mock_client(settings, _handler(302, "", {"location": "http://network-notice.tju.edu.cn/"}))
        result = await client.probe()
        assert result["campus"] is False
        assert result["reachable"] is False

    asyncio.run(run())


# ------------------------------------------------------------ import pipeline
def test_connector_import_switches_mode_and_anchors_semester(settings):
    store = KVStore()
    connector = TjuScheduleConnector(settings=settings, store=store)
    monday = date.today() - timedelta(days=date.today().weekday())

    meta = connector.store_classtable(sample_payload(monday), source="test")

    assert meta["courses"] == 1
    assert store.get(MODE_KEY) == "imported"
    assert store.get(CLASSTABLE_KEY)["data"]["term"] == "26271"
    # The API's own term_start decides week 1.
    assert connector.semester.start_date == monday
    assert build_semester(settings, store).start_date == monday


def test_imported_mode_produces_events(settings):
    async def run() -> None:
        store = KVStore()
        connector = TjuScheduleConnector(settings=settings, store=store)
        monday = date.today() - timedelta(days=date.today().weekday())
        connector.store_classtable(sample_payload(monday), source="test")

        result = await connector.fetch()

        assert result.detail["mode"] == "imported"
        assert result.events, "expected materialised course events"
        first = result.events[0]
        assert first.source == "tju_schedule"
        assert first.title == "高等数学"
        assert "26楼A101" in (first.location or "")
        # 16 weeks of Monday 1-2节, less anything already past.
        assert all(e.start_time.weekday() == 0 for e in result.events)

    asyncio.run(run())


def test_imported_mode_without_data_is_a_clear_error(settings):
    async def run() -> None:
        connector = TjuScheduleConnector(settings=settings, store=KVStore())
        KVStore().set(MODE_KEY, "imported")
        from app.connectors.base import ConnectorError

        with pytest.raises(ConnectorError):
            await connector.fetch()

    asyncio.run(run())


# ------------------------------------------------------------------- HTTP API
def test_api_status_reports_mode_and_empty_credentials(client, admin_headers):
    body = client.get("/api/tju/status", headers=admin_headers).json()
    detail = body["detail"]
    assert detail["credentials"]["has_token"] is False
    assert detail["endpoints"]["open"].startswith("https://open.twt.edu.cn")


def test_api_import_then_sync_materialises_course_events(client, admin_headers):
    monday = date.today() - timedelta(days=date.today().weekday())
    response = client.post(
        "/api/tju/import",
        headers=admin_headers,
        json={"payload": sample_payload(monday, course="信号与系统"), "run_sync": True},
    )
    assert response.status_code == 200, response.text
    detail = response.json()["detail"]
    assert detail["import"]["courses"] == 1
    assert detail["sync"]["ok"] is True
    assert detail["sync"]["created"] >= 1

    status = client.get("/api/tju/status", headers=admin_headers).json()["detail"]
    assert status["mode"] == "imported"
    assert status["import_meta"]["courses"] == 1

    events = client.get("/api/events?source=tju_schedule", headers=admin_headers).json()
    titles = [item["title"] for item in events["items"]]
    assert any("信号与系统" in title for title in titles)


def test_api_import_accepts_raw_json_text(client, admin_headers):
    monday = date.today() - timedelta(days=date.today().weekday())
    text = json.dumps(sample_payload(monday), ensure_ascii=False)
    response = client.post("/api/tju/import", headers=admin_headers,
                           json={"text": text, "run_sync": False})
    assert response.status_code == 200, response.text
    assert response.json()["detail"]["import"]["slots"] == 1


def test_api_import_rejects_html(client, admin_headers):
    response = client.post("/api/tju/import", headers=admin_headers,
                           json={"text": NOTICE_HTML, "run_sync": False})
    assert response.status_code == 422
    assert "HTML" in json.dumps(response.json(), ensure_ascii=False)


def test_api_sync_without_credentials_explains_itself(client, admin_headers):
    response = client.post("/api/tju/sync", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["detail"]["kind"] == "auth_required"


def test_api_writes_require_authentication(client):
    assert client.post("/api/tju/import", json={}).status_code in (401, 403)
    assert client.post("/api/tju/credentials", json={"mode": "token"}).status_code in (401, 403)


def test_api_clear_import_removes_state(client, admin_headers):
    monday = date.today() - timedelta(days=date.today().weekday())
    client.post("/api/tju/import", headers=admin_headers,
                json={"payload": sample_payload(monday), "run_sync": False})
    assert client.delete("/api/tju/import", headers=admin_headers).status_code == 200
    status = client.get("/api/tju/status", headers=admin_headers).json()["detail"]
    assert status["import_meta"] == {}
    assert KVStore().get(CLASSTABLE_KEY) is None
