"""Unified event schema + supporting tables (SQLModel / SQLite)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlmodel import Field, SQLModel


class Source(str, Enum):
    microsoft_todo = "microsoft_todo"
    tju_schedule = "tju_schedule"
    custom = "custom"

    @classmethod
    def parse(cls, value: str | "Source") -> "Source":
        if isinstance(value, Source):
            return value
        try:
            return cls(value)
        except ValueError as exc:  # pragma: no cover - guarded by callers
            raise ValueError(f"unknown source: {value!r}") from exc


class EventStatus(str, Enum):
    pending = "pending"
    completed = "completed"


def make_event_id(source: str | Source, source_id: str) -> str:
    """Stable id = hash(source + source_id) — the dedup key across syncs."""
    raw = f"{Source.parse(source).value}:{source_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(primary_key=True)
    source: str = Field(index=True)
    source_id: str = Field(index=True)

    #: 归属账号（多租户）。NULL = 多租户上线前的历史数据，迁移时判给 owner。
    user_id: Optional[int] = Field(default=None, index=True)

    title: str
    description: Optional[str] = None
    start_time: datetime = Field(index=True)  # naive UTC
    end_time: Optional[datetime] = Field(default=None, index=True)
    is_deadline: bool = Field(default=False, index=True)
    location: Optional[str] = None
    status: str = Field(default=EventStatus.pending.value, index=True)
    priority: int = Field(default=5)  # RFC 5545: 1 (high) .. 9 (low)
    reminder_minutes: Optional[int] = None
    all_day: bool = False
    local_override: bool = Field(default=False, index=True)
    #: 用户「删掉」了这条日程。软删除：不再出现在时间线/订阅日历里，且同步不会把它拉回来
    #: （隐藏时一并置 ``local_override``，见 ``services.events.hide_event``）。
    hidden: bool = Field(default=False, index=True)

    updated_at: datetime
    completed_at: Optional[datetime] = None
    raw: Optional[str] = None  # compact JSON of the source payload

    @property
    def uid(self) -> str:
        return f"{self.id}@campushub.nzlab.online"

    def raw_dict(self) -> dict[str, Any]:
        if not self.raw:
            return {}
        try:
            return json.loads(self.raw)
        except json.JSONDecodeError:
            return {}


class KV(SQLModel, table=True):
    """Small key/value store: token caches, connector cursors, uploads."""

    __tablename__ = "kv"

    key: str = Field(primary_key=True)
    value: str  # JSON encoded
    updated_at: datetime


class SyncRun(SQLModel, table=True):
    """Audit trail of sync runs (also feeds ``/api/status``)."""

    __tablename__ = "sync_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    trigger: str = "manual"
    started_at: datetime
    finished_at: Optional[datetime] = None
    ok: bool = True
    fetched: int = 0
    created: int = 0
    updated: int = 0
    pruned: int = 0
    message: Optional[str] = None


class ConnectorLog(SQLModel, table=True):
    """Per-connector outcome for the most recent run."""

    __tablename__ = "connector_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: Optional[int] = Field(default=None, index=True)
    connector: str = Field(index=True)
    ok: bool = True
    fetched: int = 0
    error: Optional[str] = None
    duration_ms: int = 0
    updated_at: datetime


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class User(SQLModel, table=True):
    """A portal/schedule account.

    Passwords are stored as PBKDF2-HMAC-SHA256 digests (``hashlib`` only — no
    extra dependency); sessions are stateless HMAC-signed cookies.
    """

    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    display_name: Optional[str] = None
    password_hash: str
    role: str = Field(default=UserRole.user.value, index=True)
    is_active: bool = True
    created_at: datetime
    last_login_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_ip: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.admin.value
