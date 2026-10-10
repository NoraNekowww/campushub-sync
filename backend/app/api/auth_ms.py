"""``/api/auth/ms`` — Microsoft device-code authorisation for To Do."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import get_settings
from ..connectors.base import AuthRequiredError, ConnectorError
from ..connectors.ms_todo import MSTodoConnector
from ..schemas import DeviceFlowOut, DeviceFlowPollOut, SimpleResult
from ..security import require_write

router = APIRouter(prefix="/auth/ms", tags=["auth"], dependencies=[Depends(require_write)])


def _connector() -> MSTodoConnector:
    connector = MSTodoConnector(settings=get_settings())
    if not connector.settings.ms_client_id:
        raise HTTPException(
            status_code=400,
            detail="MS_CLIENT_ID is not configured — create an app registration first",
        )
    return connector


@router.get("/status", response_model=SimpleResult)
async def auth_status() -> SimpleResult:
    connector = MSTodoConnector(settings=get_settings())
    return SimpleResult(ok=True, detail=connector.auth_state())


@router.post("/device/start", response_model=DeviceFlowOut)
async def device_start() -> DeviceFlowOut:
    connector = _connector()
    try:
        flow = await connector.start_device_flow()
    except (ConnectorError, AuthRequiredError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DeviceFlowOut(**flow)


@router.post("/device/poll", response_model=DeviceFlowPollOut)
async def device_poll() -> DeviceFlowPollOut:
    connector = _connector()
    try:
        result = await connector.poll_device_flow()
    except (ConnectorError, AuthRequiredError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DeviceFlowPollOut(
        state=result.get("state", "pending"),
        account=result.get("account"),
        message=result.get("message"),
    )


@router.delete("/tokens", response_model=SimpleResult)
async def forget_tokens() -> SimpleResult:
    connector = MSTodoConnector(settings=get_settings())
    connector.forget_tokens()
    return SimpleResult(ok=True, message="stored Microsoft tokens removed")
