"""FastAPI application factory.

One process serves both the API and the built PWA (``web/dist``), so the whole
thing sits behind a single Nginx server block on ``schedule.nzlab.online``.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, accounts
from .api import api_router
from .config import get_settings
from .db import bind_scope, init_db, session_scope
from .security import scope_for_request, warn_about_open_endpoints
from .secretbox import self_check
from .services.scheduler import get_scheduler

log = logging.getLogger("campushub")


def configure_logging(debug: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)


def find_web_dist() -> Path | None:
    """Locate the built frontend: env override, repo layout, then container."""
    candidates = []
    if os.getenv("WEB_DIST"):
        candidates.append(Path(os.getenv("WEB_DIST", "")))
    here = Path(__file__).resolve()
    candidates += [
        here.parents[2] / "web" / "dist",  # repo: backend/app/main.py -> <root>/web/dist
        Path("/app/web/dist"),  # container image layout
    ]
    for candidate in candidates:
        try:
            if candidate.is_dir() and (candidate / "index.html").is_file():
                return candidate
        except OSError:
            continue
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.debug)
    settings.ensure_dirs()
    init_db(settings)
    warn_about_open_endpoints()
    vault = self_check(settings)
    if vault["ok"]:
        log.info("credential vault ready (key id %s)", vault["key_id"])
    else:  # pragma: no cover - only with a broken crypto backend
        log.error("credential vault self-check FAILED: %s", vault.get("error"))
    if settings.enable_scheduler:
        get_scheduler(settings).start()
    else:
        log.info("scheduler disabled (ENABLE_SCHEDULER=false)")
    log.info("%s v%s ready on %s", settings.app_name, __version__, settings.db_url)
    try:
        yield
    finally:
        get_scheduler().shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Self-hosted schedule & deadline aggregator — Microsoft To Do + TJU "
            "academic schedule, unified into one timeline and one iCalendar feed."
        ),
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def bind_kv_scope(request: Request, call_next):
        """每个 /api 请求都把凭据空间绑到当前账号（多租户）。

        放在中间件而不是各路由的依赖里，是为了让教务导入 / 微软授权 / 同步这些
        老代码一行都不用改：它们里面每一处 ``KVStore()`` 自动变成该账号自己的键。
        """
        if request.url.path.startswith("/api"):
            try:
                with session_scope() as session:
                    bind_scope(scope_for_request(request, session))
            except Exception:  # 绑定失败就退回全局空间，绝不能因此让接口 500
                log.debug("kv scope bind failed", exc_info=True)
                bind_scope(None)
        return await call_next(request)

    app.include_router(api_router)

    @app.get("/api", include_in_schema=False)
    async def api_index() -> dict:
        return {
            "app": settings.app_name,
            "version": __version__,
            "endpoints": [
                "GET  /api/events",
                "GET  /api/events/{id}",
                "POST /api/events",
                "PATCH /api/events/{id}",
                "POST /api/sync",
                "GET  /api/status",
                "GET  /api/config",
                "GET  /api/subscribe/calendar.ics?token=…",
                "GET  /api/auth/session",
                "POST /api/auth/register",
                "POST /api/auth/login",
                "POST /api/auth/logout",
                "GET  /api/auth/me",
                "GET  /api/auth/storage",
                "POST /api/auth/storage/optimize",
                "GET  /api/version",
                "POST /api/schedule/upload",
            ],
        }

    @app.get("/api/version", summary="Version check for in-app update notification")
    async def app_version() -> JSONResponse:
        return JSONResponse(
            content={
                "version": "2.8.5",
                "tag": "v2.8.5",
                "title": "CampusHub Android v2.8.5",
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

    dist = find_web_dist()
    if dist is not None:
        index_file = dist / "index.html"
        log.info("serving PWA from %s", dist)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str, request: Request):
            if full_path.startswith("api/") or full_path == "api":
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (dist / full_path).resolve()
            if dist in candidate.parents or candidate == dist:
                if candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(index_file)
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> dict:
            return {
                "app": settings.app_name,
                "version": __version__,
                "hint": "frontend not built — run `npm install && npm run build` in web/",
                "api": "/api",
            }

    return app


app = create_app()
