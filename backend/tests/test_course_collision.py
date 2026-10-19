import datetime
from app.connectors.tju_schedule import make_event_id, Source, ClassEntry, Semester, PERIOD_TIMES

def test_same_course_different_weekdays_dont_collide():
    """微积分在周二第1-2节和周四第1-2节，不应该产生冲突导致周二被覆盖消失。"""
    sem = Semester(name="2026", start_date=datetime.date(2026, 8, 31), period_times=PERIOD_TIMES)
    tue = ClassEntry(
        name="微积分I",
        weekday=2,
        start_period=1,
        end_period=2,
        weeks={8},
        location="45楼B203",
    )
    thu = ClassEntry(
        name="微积分I",
        weekday=4,
        start_period=1,
        end_period=2,
        weeks={8},
        location="45楼B203",
    )
    tue_events = tue.to_events(sem, now=datetime.datetime(2026, 8, 31, tzinfo=datetime.timezone.utc), horizon_days=120)
    thu_events = thu.to_events(sem, now=datetime.datetime(2026, 8, 31, tzinfo=datetime.timezone.utc), horizon_days=120)
    
    assert len(tue_events) == 1
    assert len(thu_events) == 1
    assert tue_events[0].id != thu_events[0].id
    assert tue_events[0].start_time.weekday() == 1  # 周二 (0-indexed 1)
    assert thu_events[0].start_time.weekday() == 3  # 周四 (0-indexed 3)
