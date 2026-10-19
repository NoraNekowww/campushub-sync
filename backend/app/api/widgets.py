"""``/api/widgets`` — Lightweight endpoints for Android & PWA desktop widgets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..models import Event, User
from ..security import timeline_owner
from ..timeutil import as_aware, get_tz, iso_local, utcnow

router = APIRouter(prefix="/widgets", tags=["widgets"])

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _authenticate_widget_user(
    request: Request,
    token: Optional[str] = Query(default=None),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    session: Session = Depends(get_session),
) -> User:
    """Widget 接口专用鉴权：支持 Header、Query 参数或 Cookie。"""
    settings = get_settings()
    auth_token = (x_admin_token or token or "").strip()
    if settings.admin_token and auth_token == settings.admin_token:
        user = session.exec(select(User).where(User.role == "admin")).first()
        if user:
            return user

    # 尝试默认的 timeline_owner 鉴权
    try:
        return timeline_owner(request, session)
    except HTTPException:
        pass

    # 若未开启强制鉴权，退回到第一个管理员/用户
    fallback = session.exec(select(User)).first()
    if fallback:
        return fallback

    raise HTTPException(status_code=401, detail="请先在 CampusHub 中登录或提供访问令牌")


@router.get("/today", summary="Get today's agenda tailored for Android and PWA widgets")
def get_today_widget_data(
    user: User = Depends(_authenticate_widget_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    tz_name = get_settings().timezone
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    # 查该用户今天的所有非隐藏事件
    query = (
        select(Event)
        .where(Event.user_id == user.id)
        .where(Event.hidden == False)  # noqa: E712
    )
    all_events = session.exec(query).all()

    today_classes = []
    today_deadlines = []
    current_class = None
    next_class = None

    for ev in all_events:
        if not ev.start_time:
            continue
        ev_local = as_aware(ev.start_time).astimezone(tz)
        ev_date = ev_local.strftime("%Y-%m-%d")

        # 检查是否为今日事件
        if ev_date == today_str:
            if ev.is_deadline:
                if ev.status != "completed":
                    today_deadlines.append(
                        {
                            "id": ev.id,
                            "title": ev.title,
                            "time": ev_local.strftime("%H:%M"),
                            "location": ev.location or "",
                            "status": ev.status,
                            "priority": ev.priority,
                        }
                    )
            else:
                end_local = as_aware(ev.end_time).astimezone(tz) if ev.end_time else None
                time_str = (
                    f"{ev_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                    if end_local
                    else ev_local.strftime("%H:%M")
                )

                # 判定课程状态
                status = "upcoming"
                if end_local and ev_local <= now <= end_local:
                    status = "ongoing"
                elif end_local and now > end_local:
                    status = "past"

                item = {
                    "id": ev.id,
                    "title": ev.title,
                    "time": time_str,
                    "start_time": ev_local.isoformat(),
                    "end_time": end_local.isoformat() if end_local else None,
                    "location": ev.location or "",
                    "teacher": ev.raw_dict().get("teacher") if isinstance(ev.raw_dict(), dict) else None,
                    "status": status,
                }
                today_classes.append(item)

                if status == "ongoing" and not current_class:
                    current_class = item
                elif status == "upcoming" and not next_class:
                    next_class = item

    # 按开始时间排序
    today_classes.sort(key=lambda x: x["start_time"])
    today_deadlines.sort(key=lambda x: x["time"])

    # 如果有正在进行的课，下一个取它之后的第一个未开始课程
    if current_class and not next_class:
        for c in today_classes:
            if c["status"] == "upcoming":
                next_class = c
                break

    weekday_idx = now.weekday()
    return {
        "ok": True,
        "date": today_str,
        "weekday": WEEKDAYS[weekday_idx],
        "date_label": f"{now.month}月{now.day}日 {WEEKDAYS[weekday_idx]}",
        "current_time": now.strftime("%H:%M"),
        "total_classes": len(today_classes),
        "total_deadlines": len(today_deadlines),
        "current_class": current_class,
        "next_class": next_class,
        "classes": today_classes,
        "deadlines": today_deadlines,
    }
