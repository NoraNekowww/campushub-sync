"""``/api/subscribe/calendar.ics`` — the RFC 5545 subscription feed."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session, col, select

from ..config import get_settings
from ..db import get_session
from ..models import Event
from ..security import verify_subscribe_token
from ..services import events as event_service
from ..services.ics_export import calendar_bytes, feed_etag
from ..timeutil import utcnow

log = logging.getLogger("campushub.ics")

router = APIRouter(tags=["subscribe"])

CALENDAR_MEDIA_TYPE = "text/calendar; charset=utf-8"


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
    include_completed: bool = Query(default=True),
    session: Session = Depends(get_session),
    _: None = Depends(verify_subscribe_token),
) -> Response:
    settings = get_settings()
    now = utcnow()
    start = now - timedelta(days=days_past)
    end = now + timedelta(days=days_future)

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
    )
    events = [row for row in rows]

    etag = feed_etag(events)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    payload = calendar_bytes(
        events,
        calendar_name=f"{settings.app_name} 日程",
        tz_name=settings.timezone,
    )
    headers = {
        "ETag": etag,
        "Cache-Control": "no-cache, must-revalidate",
        "Content-Disposition": 'attachment; filename="campushub.ics"',
        "X-Event-Count": str(len(events)),
        "X-Generated-At": now.isoformat(timespec="seconds"),
    }
    log.debug("served %d events to %s", len(events), request.client)
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
    rows, _ = event_service.query_events(session, start=now, limit=20)
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
