"""HTTP API routes."""

from fastapi import APIRouter

from . import accounts, auth_ms, calendar, events, schedule, status, sync, tju, widgets

api_router = APIRouter(prefix="/api")
api_router.include_router(accounts.router)
api_router.include_router(events.router)
api_router.include_router(widgets.router)
api_router.include_router(sync.router)
api_router.include_router(status.router)
api_router.include_router(calendar.router)
api_router.include_router(auth_ms.router)
api_router.include_router(schedule.router)
api_router.include_router(tju.router)

__all__ = ["api_router"]
