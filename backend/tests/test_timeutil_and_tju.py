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
