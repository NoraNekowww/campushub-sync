"""订阅 feed 必须稳定：什么都没发生的一轮同步，不该让手机日历以为日程被改过。

``DTSTAMP`` / ``LAST-MODIFIED`` / ``ETag`` 都跟着 ``Event.updated_at`` 走。以前
``upsert_events`` 每轮同步都把它刷成当前时间，于是整份订阅内容每 10 分钟变一次 ——
客户端会把每条日程重新当成「刚更新」，课上一半又弹一次提醒（也就是「每节课都会给我
手机日历加提示，上一半还在提示」）。

改 ``sync_engine.upsert_events`` 里那两个 ``updated_at`` 赋值之前，先看这里。
"""

from app.config import get_settings

FEED = "/api/subscribe/calendar.ics"


def _feed_token() -> str:
    token = get_settings().subscribe_token
    assert token, "测试环境应当设了 SUBSCRIBE_TOKEN"
    return token


def _sync(client, admin_headers) -> None:
    response = client.post("/api/sync", headers=admin_headers)
    assert response.status_code == 200, response.text


def _feed(client) -> str:
    response = client.get(f"{FEED}?token={_feed_token()}")
    assert response.status_code == 200, response.text
    return response.text


def test_feed_unchanged_when_a_sync_finds_nothing_new(client, admin_headers):
    """demo 连接器每轮都给事件一个新的 updated_at；feed 不该因此变样。"""
    _sync(client, admin_headers)
    first = _feed(client)
    assert first.count("BEGIN:VEVENT") > 0

    _sync(client, admin_headers)
    _sync(client, admin_headers)
    assert _feed(client) == first


def test_feed_etag_stable_across_idle_syncs(client, admin_headers):
    _sync(client, admin_headers)
    url = f"{FEED}?token={_feed_token()}"
    etag = client.get(url).headers.get("etag")
    assert etag

    _sync(client, admin_headers)
    assert client.get(url).headers.get("etag") == etag
    # 客户端按这个 validator 轮询：内容没变就该拿 304，而不是又一份"新"内容
    assert client.get(url, headers={"If-None-Match": etag}).status_code == 304


def test_classes_carry_no_alarm(client, admin_headers):
    """「课表不带提醒，只留 DDL 的」（2026-10-13）——课表事件一个闹钟都不该挂。"""
    _sync(client, admin_headers)
    text = _feed(client)
    class_blocks = [block for block in text.split("BEGIN:VEVENT")[1:] if "CATEGORIES:课程" in block]
    assert class_blocks, "demo 连接器应当产出课表事件"

    for block in class_blocks:
        assert "BEGIN:VALARM" not in block, block
