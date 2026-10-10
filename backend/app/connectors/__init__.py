"""Connector registry."""

from __future__ import annotations

from typing import Optional

from ..config import Settings, get_settings
from ..db import KVStore
from .base import BaseConnector, ConnectorError
from .demo import DemoConnector
from .ms_todo import MSTodoConnector
from .tju_schedule import TjuScheduleConnector

__all__ = [
    "BaseConnector",
    "ConnectorError",
    "DemoConnector",
    "MSTodoConnector",
    "TjuScheduleConnector",
    "build_connectors",
]


def _tju_override(store: "KVStore") -> Optional[str]:
    """The mode the web UI stored (``tju.mode``), normalised to ``None`` if unset."""
    override = store.get("tju.mode")
    if not isinstance(override, str):
        return None
    mode = override.strip().lower()
    return mode if mode and mode not in ("disabled", "off", "none") else None


def build_connectors(
    settings: Optional[Settings] = None, store: Optional[KVStore] = None
) -> list[BaseConnector]:
    """连接器集合。``store`` 传进来就是「这个账号的凭据空间」（多租户）。"""
    settings = settings or get_settings()
    store = store or KVStore()
    override = _tju_override(store)
    connectors: list[BaseConnector] = []

    if settings.demo_mode and not override:
        # Demo mode is exclusive on purpose — but a real import always wins, and
        # then the demo connector is dropped so synthetic rows cannot mix in.
        connectors.append(DemoConnector(settings=settings))
        return connectors

    if settings.ms_enabled:
        connectors.append(MSTodoConnector(settings=settings, store=store))
    if settings.tju_enabled or override:
        connectors.append(TjuScheduleConnector(settings=settings, store=store))
    return connectors
