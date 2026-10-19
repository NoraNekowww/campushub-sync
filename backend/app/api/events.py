"""``/api/events`` — unified timeline queries and user edits."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import get_settings
from ..connectors import build_connectors
from ..connectors.ms_todo import note_with_meta
from ..db import get_session
from ..models import Event, EventStatus, Source, User, make_event_id
from ..schemas import EventListOut, EventOut, EventPatchIn, MsTaskIn
from ..security import require_read, timeline_owner
from ..services import events as event_service
from ..services.sync_engine import upsert_events
from ..timeutil import as_aware, as_stored, get_tz, iso_local, parse_iso, utcnow

log = logging.getLogger("campushub.api.events")

# Reads accept the admin token or the read-only subscribe token; the mutating
# endpoints below re-assert the admin token explicitly.
router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(require_read)])


class EventCreateIn(BaseModel):
    title: str
    start_time: str  # ISO 8601; naive input is read as Asia/Shanghai
    end_time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    is_deadline: bool = False
    reminder_minutes: Optional[int] = None
    priority: int = 5
    repeat_frequency: Optional[str] = None  # None | "day" | "week" | "month"
    repeat_interval: int = 1
    repeat_count: int = 1


def _add_months(dt: datetime, months: int) -> datetime:
    """给 datetime 增加若干个月，月末超出时自动回拨到当月最后一天（如 1/31 + 1月 -> 2/28 或 2/29）。"""
    import calendar
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)
    return dt.replace(year=year, month=month, day=day)


def _as_utc(value: str) -> datetime:
    return parse_iso(value.strip(), assume=get_tz())


def _span_hours(event: Event) -> Optional[float]:
    """日程的时长（小时）；没结束时间给 ``None``。

    待办任务本身不存时长，按约定并进备注的 ``⏱ 1h`` 行（``note_with_meta``）。
    """
    if not event.start_time or not event.end_time:
        return None
    span = (event.end_time - event.start_time).total_seconds() / 3600
    return span if span > 0 else None


@router.get("", response_model=EventListOut, summary="Query the unified timeline")
def list_events(
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD or ISO datetime"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD or ISO datetime"),
    source: Optional[list[str]] = Query(default=None, description="repeatable: microsoft_todo, tju_schedule, custom"),
    status: Optional[str] = Query(default=None, pattern="^(pending|completed)$"),
    is_deadline: Optional[bool] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> EventListOut:
    settings = get_settings()
    sources: Optional[Sequence[str]] = None
    if source:
        flat = [part.strip() for item in source for part in item.split(",") if part.strip()]
        try:
            sources = [Source.parse(item).value for item in flat]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        start, end = event_service.normalize_range(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid date: {exc}") from exc

    rows, total = event_service.query_events(
        session,
        start=start,
        end=end,
        sources=sources,
        status=status,
        is_deadline=is_deadline,
        search=search,
        limit=limit,
        offset=offset,
        user_id=user.id,
    )
    tz = settings.timezone
    return EventListOut(
        items=[EventOut.from_event(row, tz=tz) for row in rows],
        total=total,
        start_date=start_date,
        end_date=end_date,
        sources=list(sources or []),
    )


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> EventOut:
    event = session.get(Event, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status_code=404, detail="event not found")
    return EventOut.from_event(event, tz=get_settings().timezone)


@router.post(
    "",
    response_model=EventOut,
    status_code=http_status.HTTP_201_CREATED,
)
def create_event(
    payload: EventCreateIn,
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> EventOut:
    start = _as_utc(payload.start_time)
    end = _as_utc(payload.end_time) if payload.end_time else None
    if end is not None and end < start:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")

    repeat_freq = payload.repeat_frequency
    repeat_interval = max(1, payload.repeat_interval or 1)
    repeat_count = max(1, min(100, payload.repeat_count or 1))

    events_to_create: list[Event] = []
    base_ts = utcnow().timestamp()
    duration = (end - start) if end else None

    if repeat_freq in ("day", "week", "month") and repeat_count > 1:
        for i in range(repeat_count):
            if repeat_freq == "day":
                cur_start = start + timedelta(days=i * repeat_interval)
            elif repeat_freq == "week":
                cur_start = start + timedelta(days=i * repeat_interval * 7)
            elif repeat_freq == "month":
                cur_start = _add_months(start, i * repeat_interval)
            cur_end = (cur_start + duration) if duration else None

            sid = f"custom-{base_ts:.0f}-{payload.title[:20]}-{i+1}"
            ev = Event(
                id=make_event_id(Source.custom, sid),
                source=Source.custom.value,
                source_id=sid,
                user_id=user.id,
                title=payload.title.strip(),
                description=payload.description,
                start_time=cur_start,
                end_time=cur_end,
                is_deadline=payload.is_deadline,
                location=payload.location,
                status=EventStatus.pending.value,
                priority=max(1, min(9, payload.priority)),
                reminder_minutes=payload.reminder_minutes,
                local_override=True,  # locally authored — sync must never touch it
                updated_at=utcnow(),
                raw=json.dumps(
                    {
                        "origin": "api",
                        "recurrence": {
                            "group_id": f"rec-{base_ts:.0f}",
                            "freq": repeat_freq,
                            "interval": repeat_interval,
                            "index": i + 1,
                            "total": repeat_count,
                        },
                    },
                    ensure_ascii=False,
                ),
            )
            session.add(ev)
            events_to_create.append(ev)
    else:
        sid = f"custom-{base_ts:.0f}-{payload.title[:24]}"
        ev = Event(
            id=make_event_id(Source.custom, sid),
            source=Source.custom.value,
            source_id=sid,
            user_id=user.id,
            title=payload.title.strip(),
            description=payload.description,
            start_time=start,
            end_time=end,
            is_deadline=payload.is_deadline,
            location=payload.location,
            status=EventStatus.pending.value,
            priority=max(1, min(9, payload.priority)),
            reminder_minutes=payload.reminder_minutes,
            local_override=True,  # locally authored — sync must never touch it
            updated_at=utcnow(),
            raw=json.dumps({"origin": "api"}, ensure_ascii=False),
        )
        session.add(ev)
        events_to_create.append(ev)

    session.commit()
    first_event = events_to_create[0]
    session.refresh(first_event)
    return EventOut.from_event(first_event, tz=get_settings().timezone)


# --------------------------------------------------------- 微软待办（反向写入）
def _ms_connector():
    """当前请求账号的微软连接器；没连过就是 ``None``（多租户：看的是这个人的凭据）。"""
    for connector in build_connectors(get_settings()):
        if connector.name == Source.microsoft_todo.value:
            return connector
    return None


def _ms_list_id(event: Event) -> Optional[str]:
    """这条日程在微软那边属于哪个清单（同步时写进 ``raw`` 的）。"""
    raw = event.raw_dict()
    value = raw.get("listId") if isinstance(raw, dict) else None
    return value if isinstance(value, str) and value else None


async def push_ms_status(event: Event) -> dict:
    """把「划掉 / 取消划掉」推回微软待办。

    只回报结果，绝不因为微软出错就回滚本地状态 —— 用户在这儿点的一定算数。
    """
    if event.source != Source.microsoft_todo.value:
        return {}
    connector = _ms_connector()
    if connector is None:
        return {"ok": False, "error": "没有启用微软待办连接器"}
    if not connector.auth_state().get("authorized"):
        return {"ok": False, "error": "微软授权已失效，请去设置里重新连接"}
    list_id = _ms_list_id(event)
    if not list_id:
        return {"ok": False, "error": "这条日程没记住微软清单 id，先跑一次同步"}
    try:
        await connector.set_completed(
            event.source_id, list_id, event.status == EventStatus.completed.value
        )
    except Exception as exc:  # noqa: BLE001 - 反向同步失败只提示，不动本地
        log.warning("ms push failed for %s: %s", event.id, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "error": None}


async def push_ms_edit(
    event: Event, *, title: Optional[str], due: Optional[datetime]
) -> dict:
    """把网页端对一条待办日程的改动推回微软待办。

    地点在待办那边没有字段，所以备注每次都是「正文 + ``📍 地点``」整段重算后再推。
    """
    if event.source != Source.microsoft_todo.value:
        return {}
    connector = _ms_connector()
    if connector is None:
        return {"ok": False, "error": "没有启用微软待办连接器"}
    if not connector.auth_state().get("authorized"):
        return {"ok": False, "error": "微软授权已失效，请去设置里重新连接"}
    list_id = _ms_list_id(event)
    if not list_id:
        return {"ok": False, "error": "这条日程没记住微软清单 id，先跑一次同步"}
    try:
        await connector.update_task(
            event.source_id,
            list_id,
            title=title,
            due=due,
            note=note_with_meta(event.description, event.location, _span_hours(event)),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("ms edit push failed for %s: %s", event.id, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "error": None}


async def push_ms_delete(event: Event) -> dict:
    """把网页端的「删除」推到微软待办（用户点名要的「删除日程同步删微软」）。

    和本地那套软删除（隐藏 + ``local_override``）不一样，这是**远程真删**，
    撤不回来：撤销只把本地这条恢复，微软那边得用户自己重建。所以调用方只在
    ``source == microsoft_todo`` 时调，而且失败也不阻断本地删除 —— 用户在这儿
    点的删除一定要算数，微软那边删不掉只是多留一条废任务。
    """
    if event.source != Source.microsoft_todo.value:
        return {}
    connector = _ms_connector()
    if connector is None:
        return {"ok": False, "error": "没有启用微软待办连接器"}
    if not connector.auth_state().get("authorized"):
        return {"ok": False, "error": "微软授权已失效，请去设置里重新连接"}
    list_id = _ms_list_id(event)
    if not list_id:
        return {"ok": False, "error": "这条日程没记住微软清单 id，没法删远程那条"}
    try:
        await connector.delete_task(event.source_id, list_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("ms delete push failed for %s: %s", event.id, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "error": None}


@router.get("/ms/lists")
async def ms_lists() -> dict:
    """微软待办里的清单（「新建到微软」的下拉用）。"""
    connector = _ms_connector()
    if connector is None or not connector.auth_state().get("authorized"):
        return {"connected": False, "lists": []}
    try:
        lists = await connector.list_options()
    except Exception as exc:  # noqa: BLE001
        log.warning("ms list fetch failed: %s", exc)
        return {"connected": True, "lists": [], "error": f"{type(exc).__name__}: {exc}"}
    return {"connected": True, "lists": lists}


@router.post("/ms/task", response_model=EventOut, status_code=http_status.HTTP_201_CREATED)
async def create_ms_task(
    payload: MsTaskIn,
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> EventOut:
    """在应用里给微软待办新建一条日程，并立刻在本地点亮。

    微软建成功但本地映射失败时返回 502 —— 任务确实已经在待办里了，下一次同步
    会把它拉回来，不需要用户重试。
    """
    settings = get_settings()
    connector = _ms_connector()
    if connector is None:
        raise HTTPException(status_code=400, detail="服务端没有启用微软待办连接器")
    if not connector.auth_state().get("authorized"):
        raise HTTPException(status_code=400, detail="这个账号还没连接微软待办")

    start = payload.start
    if start.tzinfo is None:  # 前端给的是本地墙钟时间
        start = start.replace(tzinfo=ZoneInfo(settings.timezone))
    try:
        todo_list, task = await connector.create_task(
            payload.title,
            due=start,
            list_id=payload.list_id,
            # 待办任务没有地点、也没有时长字段：都并进备注（网页端读回来再摘出去）
            note=note_with_meta(payload.note, payload.location, payload.duration_hours),
            importance=payload.importance,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"微软待办写入失败：{exc}") from exc

    event = connector.task_event(todo_list, task)
    if event is None:
        raise HTTPException(
            status_code=502,
            detail="任务已经建在微软待办里，但没能映射成本地日程（下次同步会拉回来）",
        )
    upsert_events(session, [event], user.id)
    session.commit()
    session.refresh(event)
    return EventOut.from_event(event, tz=settings.timezone)


def _recurrence_group_of(event: Event) -> Optional[str]:
    raw = event.raw_dict()
    if isinstance(raw, dict):
        rec = raw.get("recurrence")
        if isinstance(rec, dict) and rec.get("group_id"):
            return str(rec["group_id"])
    if event.source_id and event.source_id.startswith("custom-"):
        parts = event.source_id.split("-")
        if len(parts) >= 3:
            return f"rec-{parts[1]}"
    return None


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: str,
    payload: EventPatchIn,
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> EventOut:
    """改一条日程：标题 / 时间 / 地点 / 备注 / 划掉 / 隐藏 —— 什么来源都能改。

    若指定了 ``apply_scope`` 为 ``all`` 或 ``future`` 且该日程属于批量生成的重复系列，
    将自动对整个系列或后续日程执行批量修改。
    """
    owned = session.get(Event, event_id)
    if owned is None or owned.user_id != user.id:
        raise HTTPException(status_code=404, detail="event not found")

    start = as_stored(payload.start_time, assume=get_tz()) if payload.start_time else None
    end = as_stored(payload.end_time, assume=get_tz()) if payload.end_time else None
    effective_start = start or as_aware(owned.start_time)
    effective_end = None if payload.clear_end_time else (end or as_aware(owned.end_time))
    if effective_end is not None and effective_end <= effective_start:
        raise HTTPException(status_code=422, detail="结束时间要晚于开始时间")

    group_id = _recurrence_group_of(owned)
    # 批量修改处理
    if payload.apply_scope in ("all", "future") and group_id:
        all_user_events = session.exec(select(Event).where(Event.user_id == user.id)).all()
        siblings = [ev for ev in all_user_events if _recurrence_group_of(ev) == group_id and not ev.hidden]
        if payload.apply_scope == "future":
            siblings = [ev for ev in siblings if ev.start_time >= owned.start_time]

        # 计算时间偏移量（墙钟时刻与时长的变化）
        time_offset: Optional[timedelta] = None
        new_duration: Optional[timedelta] = None
        if start is not None:
            time_offset = as_aware(start) - as_aware(owned.start_time)
            if end is not None:
                new_duration = as_aware(end) - as_aware(start)

        for sib in siblings:
            sib_start = None
            sib_end = None
            if time_offset is not None:
                sib_tz_start = as_aware(sib.start_time) + time_offset
                sib_start = as_stored(sib_tz_start, assume=get_tz())
                if payload.clear_end_time:
                    sib_end = None
                elif new_duration is not None:
                    sib_tz_end = sib_tz_start + new_duration
                    sib_end = as_stored(sib_tz_end, assume=get_tz())
                elif sib.end_time:
                    old_dur = as_aware(sib.end_time) - as_aware(sib.start_time)
                    sib_end = as_stored(sib_tz_start + old_dur, assume=get_tz())

            event_service.patch_event(
                session,
                sib.id,
                status=payload.status.value if payload.status else None,
                title=payload.title,
                description=payload.description,
                location=payload.location,
                reminder_minutes=payload.reminder_minutes,
                hidden=payload.hidden,
                start_time=sib_start,
                end_time=sib_end,
                clear_end_time=payload.clear_end_time,
            )
        session.commit()
        session.refresh(owned)
        return EventOut.from_event(owned, tz=get_settings().timezone)

    event = event_service.patch_event(
        session,
        event_id,
        status=payload.status.value if payload.status else None,
        title=payload.title,
        description=payload.description,
        location=payload.location,
        reminder_minutes=payload.reminder_minutes,
        hidden=payload.hidden,
        start_time=start,
        end_time=end,
        clear_end_time=payload.clear_end_time,
    )
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    session.commit()
    session.refresh(event)

    # 微软待办来源：划掉 / 改标题 / 改时间 / 改备注（地点在备注里）都推回去。
    ms_sync: dict = {}
    if event.source == Source.microsoft_todo.value:
        if payload.status is not None:
            ms_sync = await push_ms_status(event) or ms_sync
        if (
            payload.title is not None
            or start is not None
            or payload.clear_end_time
            or payload.description is not None
            or payload.location is not None
        ):
            ms_sync = await push_ms_edit(event, title=payload.title, due=start) or ms_sync
    out = EventOut.from_event(event, tz=get_settings().timezone)
    if ms_sync:
        out.ms_sync = ms_sync
    return out


@router.delete("/{event_id}", response_model=EventOut)
async def delete_event(
    event_id: str,
    apply_scope: str = Query(default="single", pattern="^(single|all|future)$"),
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> EventOut:
    """删除一条日程。支持批量删除重复任务系列。"""
    owned = session.get(Event, event_id)
    if owned is None or owned.user_id != user.id:
        raise HTTPException(status_code=404, detail="event not found")

    group_id = _recurrence_group_of(owned)
    if apply_scope in ("all", "future") and group_id:
        all_user_events = session.exec(select(Event).where(Event.user_id == user.id)).all()
        siblings = [ev for ev in all_user_events if _recurrence_group_of(ev) == group_id and not ev.hidden]
        if apply_scope == "future":
            siblings = [ev for ev in siblings if ev.start_time >= owned.start_time]
        for sib in siblings:
            event_service.patch_event(session, sib.id, hidden=True)
        session.commit()
        session.refresh(owned)
        return EventOut.from_event(owned, tz=get_settings().timezone)
    """删除一条日程。

    本地对任何来源都走「软删除」（隐藏 + ``local_override``）：时间线、统计、
    订阅日历里立刻消失，同步也不会再把它拉回来，用户还能撤销（``PATCH
    {"hidden": false}``）。

    微软待办来源的额外**真删**远端那条 —— 用户明确要求「删除日程同步删微软」。
    远端删除不可逆，所以响应里带上 ``ms_sync``，前端据此把「撤销」换掉：本地能
    恢复，微软那边恢复不了。远端失败不影响本地删除，只在 ``ms_sync`` 里报错。
    """
    event = session.get(Event, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status_code=404, detail="event not found")
    ms_sync = await push_ms_delete(event)
    event_service.set_hidden(session, event_id, True)
    session.commit()
    session.refresh(event)
    out = EventOut.from_event(event, tz=get_settings().timezone)
    if ms_sync:
        out.ms_sync = ms_sync
    return out


@router.get("/{event_id}/debug", include_in_schema=False, dependencies=[Depends(timeline_owner)])
def event_debug(
    event_id: str,
    owner: User = Depends(timeline_owner),
    session: Session = Depends(get_session),
) -> dict:
    event = session.get(Event, event_id)
    # 这条调试路由原先是管理员专用；写入门放宽后改成「只能看自己时间线里的事件」
    if event is None or (event.user_id is not None and event.user_id != owner.id):
        raise HTTPException(status_code=404, detail="event not found")
    return {
        "id": event.id,
        "source": event.source,
        "start_utc": event.start_time.isoformat(),
        "start_local": iso_local(event.start_time, get_settings().timezone),
        "raw": event.raw_dict(),
    }
