"""``/api/status`` (health, connector state) and ``/api/config`` (UI bootstrap)."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from .. import __version__
from ..config import get_settings
from ..connectors import build_connectors
from ..db import get_session, healthcheck, session_scope
from ..models import Event, Source, User
from ..schemas import ConnectorStatus, StatusOut
from ..security import is_admin_request, require_read, timeline_owner
from ..services import events as event_service
from ..services.scheduler import get_scheduler
from ..services.sync_engine import get_sync_engine
from ..timeutil import iso_local, utcnow

router = APIRouter(tags=["status"])

_STARTED_AT = time.time()


@router.get("/version", summary="Version check for in-app update notification")
async def app_version() -> JSONResponse:
    return JSONResponse(
        content={
            "version": "2.8.4",
            "tag": "v2.8.4",
            "title": "CampusHub Android v2.8.4",
            "download_url": "https://nzlab.online/schedule/CampusHub.apk",
            "github_download_url": "https://github.com/NoraNekowww/campushub-sync/releases/latest/download/CampusHub.apk",
            "release_url": "https://github.com/NoraNekowww/campushub-sync/releases/latest",
            "features": [
                "日程粘贴自动识别：在标题栏粘贴一段话（如「11月20日 09:00-11:00 在46楼A202 上电子技术实验」），下方即出现「自动识别」按钮，一键抽取出标题、日期、时间、时长、地点并回填表单",
                "识别能力离线可用：日期支持'明天/下周三/11月20日/2026-11-20'，时间支持'下午3点到5点/14:00-15:35/9点半'，地点支持'在46楼A202/地点：图书馆三楼'，其余内容自动整理为标题与备注",
                "课程详情卡片视觉优化：时间与地点展示字号显著加大加粗，配合现代圆角底衬与等宽排版，一眼看清教室与起止时刻",
                "修复重复日程创建与同步：支持多端离线秒存预展开与后台批处理映射，确保按天/周/月重复任务完整生成",
                "优化课表与线性表缓存协同机制：确保离线新建/批量变更日程在周课表中即时双向联动呈现",
                "教务校历教学周绝对对齐：根治学期开学日基准漂移，杜绝单双周反转与特定周次课程丢失",
            ],
        },
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/health", summary="Liveness probe (no auth, no secrets)")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": get_settings().app_name,
        "version": __version__,
        "uptime_seconds": int(time.time() - _STARTED_AT),
    }


@router.get("/status", response_model=StatusOut, dependencies=[Depends(require_read)])
async def status(
    session: Session = Depends(get_session), user: User = Depends(timeline_owner)
) -> StatusOut:
    settings = get_settings()
    engine = get_sync_engine(settings)
    last = engine.last_run()
    logs = {log.connector: log for log in engine.connector_logs(last.id if last else None)}

    connectors: list[ConnectorStatus] = []
    # 引擎默认不再自己持有连接器（多租户下每个账号各一份），这里按**当前请求
    # 的凭据空间**现建一份，状态卡片才会显示「你」连没连教务/微软。
    for connector in engine.connectors or build_connectors(settings):
        entry = ConnectorStatus(name=connector.name, enabled=connector.enabled)
        try:
            detail = await connector.status()
            entry.detail = detail
            entry.enabled = bool(detail.get("enabled", entry.enabled))
        except Exception as exc:  # noqa: BLE001 - status must never 500
            entry.ok = False
            entry.error = f"{type(exc).__name__}: {exc}"
        log = logs.get(connector.name)
        if log is not None:
            entry.ok = entry.ok and log.ok
            entry.error = entry.error or log.error
            entry.fetched = log.fetched
        connectors.append(entry)

    last_sync = (
        {
            "id": last.id,
            "ok": last.ok,
            "trigger": last.trigger,
            "started_at": iso_local(last.started_at, settings.timezone),
            "finished_at": iso_local(last.finished_at, settings.timezone) if last.finished_at else None,
            "fetched": last.fetched,
            "created": last.created,
            "updated": last.updated,
            "pruned": last.pruned,
            "message": last.message,
        }
        if last
        else None
    )

    return StatusOut(
        app=settings.app_name,
        version=__version__,
        ok=healthcheck().get("ok", False),
        server_time=utcnow(),
        timezone=settings.timezone,
        database=healthcheck(),
        scheduler=get_scheduler().status(),
        last_sync=last_sync,
        connectors=connectors,
        counts=event_service.event_counts(session, user_id=user.id),
    )


@router.get("/config", dependencies=[Depends(require_read)], summary="UI bootstrap payload")
async def config(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    engine = get_sync_engine(settings)
    # 现建连接器：拿到的是**当前请求账号**的凭据空间（中间件已绑定），
    # 所以这是「你」的教务/微软连接状态，而不是全站共用的那一份。
    connectors = build_connectors(settings)
    tju_status: dict[str, Any] = {}
    ms_status: dict[str, Any] = {}
    for connector in connectors:
        try:
            detail = await connector.status()
        except Exception as exc:  # noqa: BLE001
            detail = {"error": str(exc)}
        if connector.name == "tju_schedule":
            tju_status = detail
        elif connector.name == "microsoft_todo":
            ms_status = detail

    sources = sorted(
        {row for row in session.exec(_distinct_sources()).all() if row}
    )
    return {
        "app": settings.app_name,
        "version": __version__,
        "timezone": settings.timezone,
        "demo_mode": settings.demo_mode,
        "auth_required": bool(settings.admin_token),
        "accounts": {
            "enabled": settings.accounts_enabled,
            "registration_open": settings.registration_open,
            "invite_required": bool(settings.registration_invite_code),
        },
        "viewer": {"admin": is_admin_request(request)},
        "subscribe": {
            "configured": bool(settings.subscribe_token),
            "url": _subscribe_url(settings),
            "webcal": _subscribe_url(settings, scheme="webcal"),
            "filename": "campushub.ics",
        },
        "sync": {
            "interval_minutes": settings.sync_interval_minutes,
            "retention_days": settings.event_retention_days,
            "horizon_days": settings.horizon_days,
        },
        "connectors": [connector.name for connector in connectors],
        "sources_seen": sources,
        "microsoft_todo": ms_status,
        "tju_schedule": tju_status,
    }


def _distinct_sources():
    from sqlmodel import select

    return select(Event.source).distinct()


def subscribe_url(settings=None, scheme: str = "https", token: Optional[str] = None) -> str:
    settings = settings or get_settings()
    token = token if token is not None else (settings.subscribe_token or "")
    base = settings.public_base_url.rstrip("/")
    # swap the scheme instead of prefixing it — `public_base_url` may be plain
    # http on a private VPS, and "webcal://http://host/..." is not a valid URI
    if scheme != "https":
        base = f"{scheme}://{base.split('://', 1)[-1]}"
    query = f"?token={token}" if token else ""
    return f"{base}/api/subscribe/calendar.ics{query}"


_subscribe_url = subscribe_url
