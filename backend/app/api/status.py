"""``/api/status`` (health, connector state) and ``/api/config`` (UI bootstrap)."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
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
async def app_version() -> dict:
    return {
        "version": "2.7.0",
        "tag": "v2.7.0",
        "title": "CampusHub Android v2.7.0",
        "download_url": "https://nzlab.online/schedule/CampusHub.apk",
        "github_download_url": "https://github.com/NoraNekowww/campushub-sync/releases/latest/download/CampusHub.apk",
        "release_url": "https://github.com/NoraNekowww/campushub-sync/releases/latest",
        "features": [
            "昼间模式课表卡片质感升级：提升温润白色不透明度（0.78~0.88），消除过度透光泛白，统一白透磨砂材质",
            "自定义日程与待办全面应用硬件高斯模糊（16px）与晶体高光微倒角磨砂效果",
            "修复动态滑动视差：回归原生动态视口采样，彻底解决滑动后卡片与背景脱节或固定卡顿的问题",
            "支持用户自定义背景图（本地相册上传智能压缩与直链配置）",
            "课表课程卡片过去时态可视化：已过去与正在上一半的部分动态灰阶覆盖并加入 45° 优雅斜纹",
        ],
    }


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
