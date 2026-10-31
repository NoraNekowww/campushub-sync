"""``/api/subscribe/calendar.ics`` — the RFC 5545 subscription feed."""

from __future__ import annotations

import email.utils
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pydantic import BaseModel
from fastapi import HTTPException
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session, col, select

from .. import accounts
from ..config import get_settings
from ..db import get_session
from ..models import Event, EventStatus, User
from ..security import timeline_owner, verify_subscribe_token
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


class SendCalendarEmailRequest(BaseModel):
    email: str
    token: Optional[str] = None
    days_past: int = 7
    days_future: int = 120
    include_completed: bool = False


@router.post("/subscribe/email", summary="发送日历至指定邮箱（专为不支持链接订阅的备用机设计）")
def send_calendar_to_email(
    payload: SendCalendarEmailRequest,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(timeline_owner),
) -> dict:
    settings = get_settings()
    recipient = payload.email.strip()
    if not recipient or "@" not in recipient:
        raise HTTPException(status_code=400, detail="请输入有效的邮箱地址")

    now = utcnow()
    start = now - timedelta(days=payload.days_past)
    end = now + timedelta(days=payload.days_future)
    owner_id = user.id if user else None

    rows, _ = event_service.query_events(
        session,
        start=start,
        end=end,
        sources=None,
        status=None if payload.include_completed else "pending",
        is_deadline=None,
        limit=2000,
        user_id=owner_id,
    )
    events = [row for row in rows]

    ics_content = calendar_bytes(
        events,
        calendar_name=f"{settings.app_name} 日程",
        tz_name=settings.timezone,
    )

    if not settings.smtp_host:
        return {
            "ok": False,
            "smtp_configured": False,
            "event_count": len(events),
            "message": "服务器暂未配置 SMTP 邮件外发服务。备用机可直接点击「下载 .ics 文件」用手机自带日历打开一键导入！",
        }

    # 构造标准 iCalendar 邮件
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"【CampusHub】您的学期课表与日程已生成（共 {len(events)} 项）"
    msg["From"] = settings.smtp_from or settings.smtp_user or "noreply@campushub.local"
    msg["To"] = recipient
    msg["Date"] = email.utils.formatdate(localtime=True)

    text_body = (
        f"您好！\n\n"
        f"这是由 CampusHub 导出的最新课表与待办日程文件（共计 {len(events)} 个日程/课程）。\n"
        f"专为不支持网络链接订阅的备用机或系统邮箱打造。\n\n"
        f"【备用机导入指南】：\n"
        f"1. 在备用机自带的「电子邮件」App 中打开本邮件；\n"
        f"2. 点击附件中的「campushub.ics」或邮件顶部的「添加至日历」；\n"
        f"3. 系统日历将自动为您一键导入所有课程时间与地点！\n\n"
        f"导出时间：{now.strftime('%Y-%m-%d %H:%M:%S')} (UTC)\n"
    )
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    part = MIMEApplication(ics_content, Name="campushub.ics")
    part["Content-Disposition"] = 'attachment; filename="campushub.ics"'
    part["Content-Type"] = 'text/calendar; charset=utf-8; method=PUBLISH; name="campushub.ics"'
    msg.attach(part)

    try:
        if settings.smtp_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_tls:
                    server.starttls()
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        return {
            "ok": True,
            "smtp_configured": True,
            "event_count": len(events),
            "message": f"日历邮件已成功发送至 {recipient}，请在备用机邮箱查收并点击导入！",
        }
    except Exception as exc:
        log.exception("发送日历邮件失败: %s", exc)
        return {
            "ok": False,
            "smtp_configured": True,
            "message": f"邮件发送失败: {exc}。请检查 SMTP 配置，或在备用机上直接点击「下载 .ics 文件」导入。",
        }

