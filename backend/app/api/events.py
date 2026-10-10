"""``/api/events`` — unified timeline queries and user edits."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlmodel import Session

from ..config import get_settings
from ..connectors import build_connectors
from ..db import get_session
from ..models import Event, EventStatus, Source, User, make_event_id
from ..schemas import EventListOut, EventOut, EventPatchIn, MsTaskIn
from ..security import require_read, require_write, timeline_owner
from ..services import events as event_service
from ..services.sync_engine import upsert_events
from ..timeutil import as_stored, get_tz, iso_local, parse_iso, utcnow

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


def _as_utc(value: str) -> datetime:
    return parse_iso(value.strip(), assume=get_tz())


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
    source_id = f"custom-{utcnow().timestamp():.0f}-{payload.title[:24]}"
    event = Event(
        id=make_event_id(Source.custom, source_id),
        source=Source.custom.value,
        source_id=source_id,
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
    session.add(event)
    session.commit()
    session.refresh(event)
    return EventOut.from_event(event, tz=get_settings().timezone)


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
            note=payload.note,
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


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: str,
    payload: EventPatchIn,
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> EventOut:
    owned = session.get(Event, event_id)
    if owned is not None and owned.user_id != user.id:
        raise HTTPException(status_code=404, detail="event not found")
    event = event_service.patch_event(
        session,
        event_id,
        status=payload.status.value if payload.status else None,
        title=payload.title,
        description=payload.description,
        location=payload.location,
        reminder_minutes=payload.reminder_minutes,
    )
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    session.commit()
    session.refresh(event)

    # 「划掉」要顺手推回微软待办（异步，失败只提示不回滚）。
    ms_sync = (
        await push_ms_status(event)
        if payload.status is not None and event.source == Source.microsoft_todo.value
        else {}
    )
    out = EventOut.from_event(event, tz=get_settings().timezone)
    if ms_sync:
        out.ms_sync = ms_sync
    return out


@router.delete("/{event_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> None:
    event = session.get(Event, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status_code=404, detail="event not found")
    if event.source != Source.custom.value:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="only locally created events can be deleted; external events reappear on sync",
        )
    session.delete(event)
    session.commit()


@router.get("/{event_id}/debug", include_in_schema=False, dependencies=[Depends(require_write)])
def event_debug(event_id: str, session: Session = Depends(get_session)) -> dict:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return {
        "id": event.id,
        "source": event.source,
        "start_utc": event.start_time.isoformat(),
        "start_local": iso_local(event.start_time, get_settings().timezone),
        "raw": event.raw_dict(),
    }
