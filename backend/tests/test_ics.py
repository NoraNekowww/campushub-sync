"""ICS intake (parse + expand) and iCalendar export (RFC 5545 round-trip)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from icalendar import Calendar

from app.connectors.tju_schedule import expand_raw, parse_ics
from app.models import Event, Source, make_event_id
from app.services.ics_export import build_calendar, calendar_bytes, feed_etag


def _event(**kwargs) -> Event:
    base = dict(
        id=make_event_id(Source.tju_schedule, "x"),
        source=Source.tju_schedule.value,
        source_id="x",
        title="数据结构",
        description="教师：陈鹏",
        start_time=datetime(2026, 10, 12, 0, 30, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 12, 1, 55, tzinfo=timezone.utc),
        is_deadline=False,
        location="55 教学楼 A406",
        status="pending",
        priority=5,
        updated_at=datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return Event(**base)


def test_parse_ics_extracts_rrules(sample_ics):
    raws = parse_ics(sample_ics)
    assert len(raws) == 2
    first = raws[0]
    assert first.summary == "高等数学"
    assert first.rrule["FREQ"] == ["WEEKLY"] or first.rrule["FREQ"] == "WEEKLY"
    assert first.location == "26 教学楼 301"


def test_expand_weekly_count(sample_ics):
    raw = parse_ics(sample_ics)[0]
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    events = expand_raw(raw, horizon_days=200, past_days=400)
    assert len(events) == 16
    assert events[0].start_time == datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc)
    assert events[0].end_time == datetime(2026, 9, 7, 2, 5, tzinfo=timezone.utc)
    assert events[1].start_time - events[0].start_time == timedelta(days=7)
    assert events[0].source == "tju_schedule"


def test_expand_biweekly_until(sample_ics):
    raw = parse_ics(sample_ics)[1]
    events = expand_raw(raw, horizon_days=800, past_days=400)
    assert len(events) >= 2
    assert all(
        (events[index + 1].start_time - events[index].start_time) == timedelta(days=14)
        for index in range(len(events) - 1)
    )


def test_calendar_export_structure():
    payload = calendar_bytes([_event()], calendar_name="CampusHub 日程")
    text = payload.decode("utf-8")
    assert text.startswith("BEGIN:VCALENDAR")
    assert "PRODID:-//CampusHub Sync//nzlab.online//CN" in text
    assert "X-WR-TIMEZONE:Asia/Shanghai" in text
    assert "BEGIN:VTIMEZONE" in text and "TZID:Asia/Shanghai" in text
    assert "DTSTART;TZID=Asia/Shanghai:20261012T083000" in text
    assert "DTEND;TZID=Asia/Shanghai:20261012T095500" in text
    assert "BEGIN:VALARM" in text and "TRIGGER:-PT10M" in text
    assert "CATEGORIES:课程" in text
    assert "TRANSP:OPAQUE" in text


def test_calendar_export_roundtrip():
    original = _event()
    parsed = Calendar.from_ical(calendar_bytes([original]))
    vevents = [component for component in parsed.walk("VEVENT")]
    assert len(vevents) == 1
    vevent = vevents[0]
    assert str(vevent["UID"]) == original.uid
    assert str(vevent["SUMMARY"]) == "数据结构"
    start = vevent["DTSTART"].dt
    assert start.utcoffset() == timedelta(hours=8)
    assert start.replace(tzinfo=None) == datetime(2026, 10, 12, 8, 30)
    assert str(vevent["X-CAMPUSHUB-SOURCE"]) == "tju_schedule"


def test_calendar_export_deadline_gets_two_alarms():
    deadline = _event(
        id=make_event_id(Source.microsoft_todo, "task-1"),
        source=Source.microsoft_todo.value,
        source_id="task-1",
        title="提交实验报告",
        is_deadline=True,
        start_time=datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc),
        end_time=None,
        reminder_minutes=120,
        priority=1,
    )
    calendar = build_calendar([deadline])
    vevent = [component for component in calendar.walk("VEVENT")][0]
    triggers = [str(alarm["TRIGGER"].to_ical().decode()) for alarm in vevent.walk("VALARM")]
    assert triggers == ["-PT2H", "-P1D"]
    assert str(vevent["TRANSP"]) == "TRANSPARENT"
    # no DTEND -> a 30 minute block is synthesised
    assert vevent["DTEND"].dt.replace(tzinfo=None) == datetime(2026, 10, 20, 23, 30)


def test_calendar_export_escapes_text():
    event = _event(title="高数, 作业; 第3章", description="含换行\n与逗号,")
    text = calendar_bytes([event]).decode("utf-8")
    assert "\\," in text and "\\;" in text and "\\n" in text


def test_feed_etag_changes_with_content():
    first = feed_etag([_event()])
    second = feed_etag([_event(title="另一门课")])
    assert first != second
    assert first.startswith('"') and first.endswith('"')
