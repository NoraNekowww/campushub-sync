"""``/api/subscribe/calendar.ics`` — the RFC 5545 subscription feed."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session, col, select

from .. import accounts
from ..config import get_settings
from ..db import get_session
from ..models import Event, EventStatus
from ..security import verify_subscribe_token
from ..services import events as event_service
from ..services.ics_export import calendar_bytes, feed_etag
from ..timeutil import utcnow

log = logging.getLogger("campushub.ics")

router = APIRouter(tags=["subscribe"])

CALENDAR_MEDIA_TYPE = "text/calendar; charset=utf-8"

#: 「撤下」墓碑保留窗口：用户删掉 / 刚划掉的日程，在这段时间内会以
#: ``STATUS:CANCELLED`` 再发一次（同一个 UID），让已经订阅的客户端把它从
#: 手机日历里删掉。单纯「不再出现」的条目，不少客户端会一直留着。
TOMBSTONE_DAYS = 45


@router.get(
    "/subscribe/calendar.ics",
    summary="iCalendar feed for native calendar apps",
    response_class=Response,
    responses={200: {"content": {CALENDAR_MEDIA_TYPE: {}}}},
)
def calendar_feed(
    request: Request,
    token: Optional[str] = Query(default=None, description="SUBSCRIBE_TOKEN"),
    days_past: int = Query(default=7, ge=0, le=90),
    days_future: int = Query(default=120, ge=1, le=730),
    source: Optional[list[str]] = Query(default=None),
    include_completed: bool = Query(
        default=False,
        description="把划掉（已完成）的日程也放进日历；默认不放",
    ),
    session: Session = Depends(get_session),
    _: None = Depends(verify_subscribe_token),
) -> Response:
    settings = get_settings()
    now = utcnow()
    start = now - timedelta(days=days_past)
    end = now + timedelta(days=days_future)

    # 订阅令牌是站长自己的，所以这里只导出站长名下的日程：多租户之后别人的课表
    # 不该混进他的手机日历。单机模式（还没建账号）就按无归属处理。
    owner = accounts.owner(session)
    owner_id = owner.id if owner else None

    sources = None
    if source:
        sources = [part.strip() for item in source for part in item.split(",") if part.strip()]

    rows, _total = event_service.query_events(
        session,
        start=start,
        end=end,
        sources=sources,
        status=None if include_completed else "pending",
        is_deadline=None,
        limit=2000,
        user_id=owner_id,
    )
    events = [row for row in rows]

    # 「撤下」墓碑：用户删掉的（hidden）和默认不放的「已划掉」日程，用同一个 UID 再发
    # 一条 STATUS:CANCELLED，客户端才会把它从手机日历里删掉。
    ghosts, _ = event_service.query_events(
        session,
        start=now - timedelta(days=TOMBSTONE_DAYS),
        end=end,
        sources=sources,
        status=None,
        is_deadline=None,
        limit=2000,
        user_id=owner_id,
        include_hidden=True,
    )
    visible_ids = {row.id for row in events}
    tombstones = [
        row
        for row in ghosts
        if row.id not in visible_ids
        and (
            row.hidden
            or (not include_completed and row.status == EventStatus.completed.value)
        )
    ]

    etag = feed_etag([*events, *tombstones])
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    payload = calendar_bytes(
        events,
        calendar_name=f"{settings.app_name} 日程",
        tz_name=settings.timezone,
        tombstones=tombstones,
    )
    headers = {
        "ETag": etag,
        "Cache-Control": "no-cache, must-revalidate",
        "Content-Disposition": 'attachment; filename="campushub.ics"',
        "X-Event-Count": str(len(events)),
        "X-Cancelled-Count": str(len(tombstones)),
        "X-Generated-At": now.isoformat(timespec="seconds"),
    }
    log.debug(
        "served %d events (+%d cancelled) to %s", len(events), len(tombstones), request.client
    )
    return Response(content=payload, media_type=CALENDAR_MEDIA_TYPE, headers=headers)


@router.get("/subscribe/preview", summary="Human-readable feed summary (token protected)")
def preview(
    request: Request,
    token: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    _: None = Depends(verify_subscribe_token),
) -> dict:
    settings = get_settings()
    now = utcnow()
    owner = accounts.owner(session)
    rows, _ = event_service.query_events(
        session,
        start=now,
        limit=20,
        status="pending",
        user_id=owner.id if owner else None,
    )
    return {
        "calendar": f"{settings.app_name} 日程",
        "timezone": settings.timezone,
        "upcoming": [
            {
                "title": row.title,
                "start": row.start_time.isoformat(),
                "source": row.source,
                "is_deadline": row.is_deadline,
            }
            for row in rows
        ],
    }
