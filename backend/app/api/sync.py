"""``/api/sync`` — manual synchronisation trigger."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..schemas import SyncTriggerOut
from ..security import require_write
from ..services.sync_engine import get_sync_engine

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post(
    "",
    response_model=SyncTriggerOut,
    dependencies=[Depends(require_write)],
    summary="Run every connector now",
)
async def trigger_sync() -> SyncTriggerOut:
    settings = get_settings()
    outcome = await get_sync_engine(settings).run(trigger="api")
    return SyncTriggerOut(
        ok=outcome.ok,
        run_id=outcome.run_id,
        fetched=outcome.fetched,
        created=outcome.created,
        updated=outcome.updated,
        pruned=outcome.pruned,
        duration_ms=outcome.duration_ms,
        message=outcome.message
        or ", ".join(
            f"{name}:{'ok' if info.get('ok') else 'error'}" for name, info in outcome.connectors.items()
        )
        or None,
    )


@router.get("/logs", dependencies=[Depends(require_write)])
def sync_logs(limit: int = 10) -> dict:
    engine = get_sync_engine(get_settings())
    last = engine.last_run()
    runs = []
    if last is not None:
        runs.append(
            {
                "id": last.id,
                "trigger": last.trigger,
                "ok": last.ok,
                "started_at": str(last.started_at),
                "finished_at": str(last.finished_at) if last.finished_at else None,
                "fetched": last.fetched,
                "created": last.created,
                "updated": last.updated,
                "pruned": last.pruned,
                "message": last.message,
                "connectors": [
                    {
                        "name": log.connector,
                        "ok": log.ok,
                        "fetched": log.fetched,
                        "error": log.error,
                        "duration_ms": log.duration_ms,
                    }
                    for log in engine.connector_logs(last.id)
                ],
            }
        )
    return {"runs": runs, "limit": limit}
