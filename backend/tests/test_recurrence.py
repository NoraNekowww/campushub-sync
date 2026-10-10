"""Graph recurrence expansion (weekly/biweekly/monthly/numbered/endDate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.connectors.ms_todo import expand_recurrence

CN = timezone(timedelta(hours=8))
ANCHOR = datetime(2026, 10, 12, 23, 0, tzinfo=CN)  # Monday 23:00 +08:00 -> 15:00 UTC


def test_no_recurrence():
    horizon = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert expand_recurrence(ANCHOR, None, horizon) == []
    assert expand_recurrence(ANCHOR, {}, horizon) == []


def test_weekly_numbered():
    recurrence = {
        "pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["monday"]},
        "range": {"type": "numbered", "startDate": "2026-10-12", "numberOfOccurrences": 4},
    }
    horizon = datetime(2027, 1, 1, tzinfo=timezone.utc)
    occurrences = expand_recurrence(ANCHOR, recurrence, horizon)
    assert len(occurrences) == 4
    assert occurrences[0] == datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    assert occurrences[-1] == datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def test_weekly_end_date_stops_at_horizon():
    recurrence = {
        "pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["monday", "friday"]},
        "range": {"type": "endDate", "startDate": "2026-10-12", "endDate": "2026-10-30"},
    }
    horizon = datetime(2027, 1, 1, tzinfo=timezone.utc)
    occurrences = expand_recurrence(ANCHOR, recurrence, horizon)
    dates = [item.date().isoformat() for item in occurrences]
    assert dates == [
        "2026-10-12",
        "2026-10-16",
        "2026-10-19",
        "2026-10-23",
        "2026-10-26",
        "2026-10-30",
    ]


def test_daily_is_bounded_by_horizon():
    recurrence = {"pattern": {"type": "daily", "interval": 1}, "range": {"type": "noEnd"}}
    horizon = datetime(2026, 10, 20, tzinfo=timezone.utc)
    occurrences = expand_recurrence(ANCHOR, recurrence, horizon)
    assert 0 < len(occurrences) <= 9


def test_monthly_absolute():
    recurrence = {
        "pattern": {"type": "absoluteMonthly", "interval": 1, "dayOfMonth": 31},
        "range": {"type": "numbered", "startDate": "2026-10-12", "numberOfOccurrences": 3},
    }
    horizon = datetime(2027, 6, 1, tzinfo=timezone.utc)
    occurrences = expand_recurrence(ANCHOR, recurrence, horizon)
    # February has no 31st -> clamped to the 28th
    assert [item.date().isoformat() for item in occurrences] == [
        "2026-10-31",
        "2026-11-30",
        "2026-12-31",
    ]


def test_relative_monthly_last_friday():
    recurrence = {
        "pattern": {
            "type": "relativeMonthly",
            "interval": 1,
            "daysOfWeek": ["friday"],
            "index": "last",
        },
        "range": {"type": "numbered", "startDate": "2026-10-01", "numberOfOccurrences": 2},
    }
    horizon = datetime(2027, 6, 1, tzinfo=timezone.utc)
    occurrences = expand_recurrence(ANCHOR, recurrence, horizon)
    assert [item.date().isoformat() for item in occurrences] == ["2026-10-30", "2026-11-27"]
