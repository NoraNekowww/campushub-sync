"""``/api/schedule`` — ICS upload fallback and semester configuration."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..config import get_settings
from ..connectors.base import ConnectorError
from ..connectors.tju_schedule import (
    ICS_CONTENT_KEY,
    SEMESTER_KEY,
    TjuScheduleConnector,
    build_semester,
)
from ..db import KVStore
from ..schemas import SimpleResult
from ..security import require_write

router = APIRouter(prefix="/schedule", tags=["schedule"], dependencies=[Depends(require_write)])

MAX_ICS_BYTES = 2 * 1024 * 1024


class SemesterIn(BaseModel):
    name: Optional[str] = None
    start_date: str = Field(description="ISO date of week-1 Monday, e.g. 2026-09-07")
    total_weeks: int = Field(default=16, ge=1, le=30)
    holidays: list[str] = Field(default_factory=list)


@router.get("/semester", response_model=SimpleResult)
async def get_semester() -> SimpleResult:
    settings = get_settings()
    semester = build_semester(settings, KVStore())
    return SimpleResult(ok=True, detail=semester.summary())


@router.put("/semester", response_model=SimpleResult)
async def put_semester(payload: SemesterIn) -> SimpleResult:
    from datetime import date

    try:
        start = date.fromisoformat(payload.start_date.strip()[:10])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid start_date: {exc}") from exc
    store = KVStore()
    store.set(
        SEMESTER_KEY,
        {
            "name": payload.name,
            "start_date": start.isoformat(),
            "total_weeks": payload.total_weeks,
            "holidays": payload.holidays,
        },
    )
    semester = build_semester(get_settings(), store)
    return SimpleResult(
        ok=True,
        message="semester saved",
        detail={"semester": semester.summary(), "week1_monday": semester.start_date.isoformat()},
    )


@router.post("/upload", response_model=SimpleResult)
async def upload_ics(file: UploadFile = File(...)) -> SimpleResult:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="empty file")
    if len(raw) > MAX_ICS_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large (max {MAX_ICS_BYTES} bytes)")
    connector = TjuScheduleConnector(settings=get_settings(), store=KVStore())
    try:
        detail = connector.store_ics(raw, file.filename or "timetable.ics")
    except ConnectorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SimpleResult(ok=True, message="timetable stored — run POST /api/sync", detail=detail)


@router.delete("/upload", response_model=SimpleResult)
async def clear_ics() -> SimpleResult:
    store = KVStore()
    store.delete(ICS_CONTENT_KEY)
    store.delete("tju.ics_filename")
    return SimpleResult(ok=True, message="uploaded timetable removed")


@router.get("/preview", response_model=SimpleResult)
async def preview_schedule(limit: int = 10) -> SimpleResult:
    """Parse the stored timetable without writing to the events table."""
    from ..connectors.tju_schedule import expand_raw, parse_ics

    settings = get_settings()
    store = KVStore()
    content: Optional[str] = store.get(ICS_CONTENT_KEY)
    if not content:
        raise HTTPException(status_code=404, detail="no uploaded timetable — POST /api/schedule/upload")
    try:
        raws = parse_ics(content)
    except ConnectorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rendered: list[dict[str, Any]] = []
    for raw in raws[:limit]:
        for event in expand_raw(raw, tz_name=settings.timezone, horizon_days=settings.horizon_days):
            rendered.append(
                {
                    "title": event.title,
                    "start_utc": event.start_time.isoformat() + "Z",
                    "location": event.location,
                }
            )
            break
    return SimpleResult(
        ok=True,
        detail={"raw_events": len(raws), "expanded_sample": rendered[:limit]},
    )
