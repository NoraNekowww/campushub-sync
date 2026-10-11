"""Timezone parsing, week specs, period maths."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.connectors.tju_schedule import (
    PERIOD_TIMES,
    ClassEntry,
    Semester,
    parse_week_spec,
)
from app.timeutil import as_aware, as_stored, parse_graph_datetime, utcnow

CN = timezone(timedelta(hours=8))


def test_parse_graph_datetime_windows_tz():
    parsed = parse_graph_datetime({"dateTime": "2026-10-12T23:00:00.0000000", "timeZone": "China Standard Time"})
    assert parsed == datetime(2026, 10, 12, 15, 0, 0, tzinfo=timezone.utc)


def test_parse_graph_datetime_utc():
    parsed = parse_graph_datetime({"dateTime": "2026-10-12T15:00:00Z", "timeZone": "UTC"})
    assert parsed == datetime(2026, 10, 12, 15, 0, 0, tzinfo=timezone.utc)


def test_parse_graph_datetime_empty():
    assert parse_graph_datetime(None) is None
    assert parse_graph_datetime({"timeZone": "UTC"}) is None


def test_as_stored_roundtrip():
    stored = as_stored(datetime(2026, 10, 12, 8, 30), assume=CN)
    assert stored == datetime(2026, 10, 12, 0, 30, tzinfo=timezone.utc)
    assert as_aware(stored) == stored


@pytest.mark.parametrize(
    "spec,expected_weeks",
    [
        ("1-16", set(range(1, 17))),
        ("1-8,10-12", set(range(1, 9)) | {10, 11, 12}),
        ("1-16周", set(range(1, 17))),
        ("第3-5周", {3, 4, 5}),
        ("1,3,5", {1, 3, 5}),
    ],
)
def test_parse_week_spec(spec, expected_weeks):
    weeks, parity = parse_week_spec(spec, total_weeks=16)
    assert weeks == expected_weeks
    assert parity is None


def test_parse_week_spec_parity():
    odd, parity = parse_week_spec("1-16单周", total_weeks=16)
    assert parity == "odd"
    assert odd == {1, 3, 5, 7, 9, 11, 13, 15}
    even, parity = parse_week_spec("2-16 双周", total_weeks=16)
    assert parity == "even"
    assert even == {2, 4, 6, 8, 10, 12, 14, 16}


def test_semester_aligns_to_monday():
    semester = Semester(name="测试", start_date=date(2026, 9, 9))  # a Wednesday
    assert semester.start_date == date(2026, 9, 7)
    assert semester.monday(1) == date(2026, 9, 7)
    assert semester.date_for(2, 1) == date(2026, 9, 14)
    assert semester.date_for(2, 7) == date(2026, 9, 20)
    assert semester.week_of(date(2026, 9, 21)) == 3


def test_semester_period_slot():
    semester = Semester(name="测试", start_date=date(2026, 9, 7))
    start, end = semester.datetimes(1, 1, 1, 2)
    assert start == datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc)  # 08:30 +08:00
    assert end == datetime(2026, 9, 7, 2, 5, tzinfo=timezone.utc)


def test_class_entry_to_events_respects_weeks_and_holidays():
    semester = Semester(
        name="2026 秋",
        start_date=date(2026, 9, 7),
        holidays={date(2026, 9, 14)},
        period_times=PERIOD_TIMES,
    )
    entry = ClassEntry(name="数据结构", weekday=1, start_period=1, end_period=2, weeks={1, 2, 3})
    now = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
    events = entry.to_events(semester, now=now, horizon_days=365)
    # week 2 Monday is a holiday -> dropped
    assert len(events) == 2
    assert events[0].start_time == datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc)
    assert events[1].start_time == datetime(2026, 9, 21, 0, 30, tzinfo=timezone.utc)
    assert all(event.is_deadline is False for event in events)
    assert events[0].source == "tju_schedule"
    assert len({event.id for event in events}) == 2


def test_utcnow_is_aware():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.tzinfo.utcoffset(now) == timedelta(0)


# ---------------------------------------------------------------- 教务周次换算
CAS_TABLE_HTML = """\
activity = new TaskActivity("1", "杨志群(副教授)", "45203(01039)", "微积分I", "3964",
  "45楼B203", "00001111111111111111000000000000000000000000000000000", null, "", "", "");
index =1*unitCount+0; table0.activities[index][0]=activity;
index =1*unitCount+1; table0.activities[index][0]=activity;
"""


def test_eams_bitmap_position_5_is_teaching_week_4():
    """教务位图第 1 位是开学前的报到周位 ⇒ 第 5 位 = 教学周第 4 周。"""
    from app.connectors.tju_cas import EAMS_WEEK_OFFSET, _parse_js_activities

    assert EAMS_WEEK_OFFSET == 1
    arranges = _parse_js_activities(CAS_TABLE_HTML)
    assert len(arranges) == 1
    assert arranges[0]["weeks"] == list(range(4, 20))
    assert arranges[0]["day"] == 2 and arranges[0]["unit"] == [1, 2]  # JS 里 day=1 是周二


def test_first_class_lands_on_the_school_start_date():
    """2026 秋：第 1 教学周 = 8/31，第一个有课的周 = 9/21（学校迎新的上课日）。"""
    from app.connectors.tju_cas import _parse_js_activities

    weeks = set(_parse_js_activities(CAS_TABLE_HTML)[0]["weeks"])
    entry = ClassEntry(name="微积分I", weekday=1, start_period=1, end_period=2, weeks=weeks)
    semester = Semester(name="2026-2027 1", start_date=date(2026, 8, 31), period_times=PERIOD_TIMES)
    events = entry.to_events(
        semester, now=datetime(2026, 8, 31, tzinfo=timezone.utc), horizon_days=365
    )
    days = sorted(event.start_time.date() for event in events)
    assert days[0] == date(2026, 9, 21)
    assert days[-1] == date(2027, 1, 4)


def test_event_id_ignores_the_anchor_so_reanchor_redates_in_place():
    """改学期锚点只改日期、不改 id —— 否则库里会多出一份旧日期的孤儿行。"""
    entry = ClassEntry(name="微积分I", weekday=1, start_period=1, end_period=2, weeks={4})
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    shifted = Semester(name="2026-2027 1", start_date=date(2026, 8, 24), period_times=PERIOD_TIMES)
    right = Semester(name="2026-2027 1", start_date=date(2026, 8, 31), period_times=PERIOD_TIMES)
    first = entry.to_events(shifted, now=now, horizon_days=365)[0]
    second = entry.to_events(right, now=now, horizon_days=365)[0]
    assert first.id == second.id
    assert first.start_time.date() == date(2026, 9, 14)
    assert second.start_time.date() == date(2026, 9, 21)


def test_import_writes_term_start_back_into_semester_settings(settings):
    """导入的 term_start 要写回学期设置，否则设置里那个手填的 start_date 继续生效。"""
    from app.connectors.tju_schedule import SEMESTER_KEY, TjuScheduleConnector
    from app.db import KVStore

    store = KVStore()
    store.set(SEMESTER_KEY, {"name": "2026", "start_date": "2026-07-31", "total_weeks": 16})
    payload = {
        "error_code": -1,
        "data": {
            "term": "2026-2027 1",
            "week": 6,
            "term_start": 1788105600,  # 2026-08-31 00:00 +08:00
            "data": [
                {
                    "coursename": "微积分I",
                    "teacher": "杨志群(副教授)",
                    "arrange": [
                        {"day": 1, "start": 1, "end": 2, "room": "45楼B203", "week": [4, 5, 6]}
                    ],
                    "week": {"start": 4, "end": 6},
                }
            ],
        },
    }
    TjuScheduleConnector(settings).store_classtable(payload, source="jw", total_weeks=20)
    stored = KVStore().get(SEMESTER_KEY)
    assert stored["start_date"] == "2026-08-31"
    assert stored["total_weeks"] == 20
    assert stored["name"] == "2026"  # 用户起的名字不动
