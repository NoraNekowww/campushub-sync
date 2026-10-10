"""RFC 5545 iCalendar feed generation (VEVENT + VTIMEZONE + VALARM)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Iterable, Optional

from icalendar import Alarm, Calendar
from icalendar import Event as ICalEvent
from icalendar import Timezone, TimezoneStandard

from ..models import Event, Source
from ..timeutil import as_aware, get_tz

PRODID = "-//CampusHub Sync//nzlab.online//CN"
DEADLINE_BLOCK = timedelta(minutes=30)
CLASS_LEAD = 10  # minutes before a class
DEADLINE_LEAD = 60  # fallback lead time for deadlines without an explicit reminder

SOURCE_LABELS = {
    Source.microsoft_todo.value: "Microsoft To Do",
    Source.tju_schedule.value: "天津大学课表",
    Source.custom.value: "自定义",
}


def _timezone_component(tz_name: str = "Asia/Shanghai") -> Timezone:
    """China has had no DST since 1991 — a single STANDARD rule is exact."""
    tz = Timezone()
    tz.add("TZID", tz_name)
    standard = TimezoneStandard()
    standard.add("DTSTART", datetime(1970, 1, 1, 0, 0, 0))
    standard.add("TZOFFSETFROM", timedelta(hours=8))
    standard.add("TZOFFSETTO", timedelta(hours=8))
    standard.add("TZNAME", "CST")
    tz.add_component(standard)
    return tz


def _description(event: Event) -> str:
    parts = [event.description] if event.description else []
    label = SOURCE_LABELS.get(event.source, event.source)
    parts.append(f"来源：{label}")
    if event.location and event.is_deadline:
        parts.append(f"清单：{event.location}")
    return "\n".join(part for part in parts if part)


def _alarms(event: Event) -> list[Alarm]:
    alarms: list[Alarm] = []
    lead = event.reminder_minutes
    if event.is_deadline:
        leads = [lead if lead is not None else DEADLINE_LEAD]
        if lead is not None and lead > 90:  # also warn the day before
            leads.append(24 * 60)
        if lead is None:
            leads.append(24 * 60)
    else:
        leads = [lead if lead is not None else CLASS_LEAD]

    for minutes in sorted({int(m) for m in leads if m and m > 0}):
        alarm = Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("DESCRIPTION", event.title)
        alarm.add("TRIGGER", -timedelta(minutes=minutes))
        alarms.append(alarm)
    return alarms


def event_to_vevent(
    event: Event, tz_name: str = "Asia/Shanghai", *, cancelled: bool = False
) -> ICalEvent:
    """一条 VEVENT。

    ``cancelled=True`` 生成「撤下」墓碑：``STATUS:CANCELLED`` + 不挂闹钟。
    用户删掉或刚划掉的日程在订阅日历里发这一条，客户端才会把已经取过的条目删掉 ——
    订阅源里单纯「不再出现」的条目，不少客户端会一直留着。
    """
    tz = get_tz(tz_name)
    start = as_aware(event.start_time)
    assert start is not None
    start_local = start.astimezone(tz)
    end = as_aware(event.end_time)
    if end is not None:
        end_local = end.astimezone(tz)
        if end_local <= start_local:
            end_local = start_local + DEADLINE_BLOCK
    else:
        end_local = start_local + DEADLINE_BLOCK

    component = ICalEvent()
    component.add("UID", event.uid)
    component.add("SUMMARY", event.title)
    component.add("DTSTAMP", as_aware(event.updated_at) or start)
    component.add("DTSTART", start_local)
    component.add("DTEND", end_local)
    component.add("LAST-MODIFIED", as_aware(event.updated_at) or start)
    if event.location and not event.is_deadline:
        component.add("LOCATION", event.location)
    elif event.location and event.is_deadline:
        component.add("LOCATION", event.location)
    description = _description(event)
    if description:
        component.add("DESCRIPTION", description)
    component.add("CATEGORIES", ["DDL"] if event.is_deadline else ["课程"])
    if cancelled:
        component.add("STATUS", "CANCELLED")
        component.add("SEQUENCE", 1)
    else:
        # RFC 5545 只给 VEVENT 定义了 TENTATIVE/CONFIRMED/CANCELLED —— 已完成的日程
        # 用 CONFIRMED（"COMPLETED" 是 VTODO 的状态，放进 VEVENT 是无效值，客户端会
        # 当成坏条目丢掉），真实状态另放 X-CAMPUSHUB-STATUS。
        component.add("STATUS", "CONFIRMED")
        component.add("X-CAMPUSHUB-STATUS", event.status)
    component.add("PRIORITY", int(event.priority or 5))
    component.add("TRANSP", "TRANSPARENT" if event.is_deadline else "OPAQUE")
    component.add("X-CAMPUSHUB-SOURCE", event.source)
    component.add("X-CAMPUSHUB-ID", event.id)
    if not cancelled:
        for alarm in _alarms(event):
            component.add_component(alarm)
    return component


def build_calendar(
    events: Iterable[Event],
    *,
    calendar_name: str = "CampusHub 日程",
    tz_name: str = "Asia/Shanghai",
    now: Optional[datetime] = None,
    tombstones: Iterable[Event] = (),
) -> Calendar:
    calendar = Calendar()
    calendar.add("PRODID", PRODID)
    calendar.add("VERSION", "2.0")
    calendar.add("CALSCALE", "GREGORIAN")
    calendar.add("METHOD", "PUBLISH")
    calendar.add("X-WR-CALNAME", calendar_name)
    calendar.add("X-WR-TIMEZONE", tz_name)
    calendar.add("X-WR-RELCALID", "campushub-sync")
    calendar.add_component(_timezone_component(tz_name))
    for event in events:
        calendar.add_component(event_to_vevent(event, tz_name=tz_name))
    for event in tombstones:
        calendar.add_component(event_to_vevent(event, tz_name=tz_name, cancelled=True))
    return calendar


def calendar_bytes(
    events: Iterable[Event],
    *,
    calendar_name: str = "CampusHub 日程",
    tz_name: str = "Asia/Shanghai",
    tombstones: Iterable[Event] = (),
) -> bytes:
    return build_calendar(
        events, calendar_name=calendar_name, tz_name=tz_name, tombstones=tombstones
    ).to_ical()


def feed_etag(events: Iterable[Event]) -> str:
    """Validator over the feed's *content* — any change flips it.

    Used for ``If-None-Match`` handling so calendar clients can poll cheaply.
    """
    digest = hashlib.sha256()
    count = 0
    for event in events:
        count += 1
        digest.update(
            "|".join(
                (
                    event.id,
                    event.start_time.isoformat(),
                    (event.end_time.isoformat() if event.end_time else ""),
                    event.updated_at.isoformat() if as_aware(event.updated_at) else "",
                    event.status,
                    "hidden" if event.hidden else "shown",
                    event.title,
                )
            ).encode("utf-8")
        )
        digest.update(b"\n")
    digest.update(f"count={count}".encode())
    return '"' + digest.hexdigest()[:32] + '"'
