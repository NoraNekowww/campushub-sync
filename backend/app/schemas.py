"""Pydantic boundary models (API request/response shapes)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import Event, EventStatus, Source
from .timeutil import iso_local


class EventOut(BaseModel):
    """Event rendered for clients: local (Asia/Shanghai) ISO 8601 timestamps."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source: Source
    source_id: str
    title: str
    description: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    is_deadline: bool
    location: Optional[str] = None
    status: EventStatus
    priority: int
    reminder_minutes: Optional[int] = None
    all_day: bool = False
    local_override: bool = False
    #: 用户划掉/删掉（软删除）的日程：不再出现在时间线与订阅日历里
    hidden: bool = False
    updated_at: datetime
    completed_at: Optional[datetime] = None
    periods: Optional[list[int]] = None  # 真实节次 [起, 止]（1 起），教务事件才有
    #: 「划掉」有没有成功推回微软待办：``{"ok": bool, "error": str | None}``
    ms_sync: Optional[dict[str, Any]] = None

    @classmethod
    def from_event(cls, event: Event, tz: str = "Asia/Shanghai") -> "EventOut":
        def local(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            rendered = iso_local(value, tz)
            return datetime.fromisoformat(rendered) if rendered else None

        return cls(
            id=event.id,
            source=Source.parse(event.source),
            source_id=event.source_id,
            title=event.title,
            description=event.description,
            start_time=local(event.start_time),  # type: ignore[arg-type]
            end_time=local(event.end_time),
            is_deadline=event.is_deadline,
            location=event.location,
            status=EventStatus(event.status),
            priority=event.priority,
            reminder_minutes=event.reminder_minutes,
            all_day=event.all_day,
            local_override=event.local_override,
            hidden=bool(event.hidden),
            updated_at=local(event.updated_at),  # type: ignore[arg-type]
            completed_at=local(event.completed_at),
            periods=_periods_from_raw(event.raw_dict()),
        )


def _periods_from_raw(raw: Any) -> Optional[list[int]]:
    """``raw["periods"]`` → ``[起, 止]``（教务事件的真实节次）。

    前端以前用「时长 ÷ 45 分钟」猜节数，含课间休息的第 1-4 节（08:30-12:00 = 210 分钟）
    会被算成 5 节 —— 这里把真实节次透出去，让界面不再猜。
    """
    if not isinstance(raw, dict):
        return None
    value = raw.get("periods")
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        start, end = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    if start < 1 or end < start:
        return None
    return [start, end]


class EventListOut(BaseModel):
    items: list[EventOut]
    total: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sources: list[str] = Field(default_factory=list)


class EventPatchIn(BaseModel):
    status: Optional[EventStatus] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    reminder_minutes: Optional[int] = None
    #: 软删除开关：``true`` = 从日历里拿掉（等同 DELETE），``false`` = 恢复（撤销）
    hidden: Optional[bool] = None


class MsTaskIn(BaseModel):
    """在应用里直接给微软待办新建一条日程。"""

    title: str
    #: 本地墙钟时间；没带时区就按 settings.timezone 解释
    start: datetime
    note: Optional[str] = None
    list_id: Optional[str] = None  # 不填 = 这个微软账号里的第一个清单
    importance: Optional[str] = None  # low / normal / high


class SyncTriggerOut(BaseModel):
    ok: bool
    run_id: Optional[int] = None
    fetched: int = 0
    created: int = 0
    updated: int = 0
    pruned: int = 0
    duration_ms: int = 0
    message: Optional[str] = None


class ConnectorStatus(BaseModel):
    name: str
    enabled: bool
    ok: bool = True
    detail: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    last_run: Optional[datetime] = None
    fetched: int = 0


class CountsOut(BaseModel):
    total: int = 0
    pending: int = 0
    completed: int = 0
    deadlines: int = 0
    classes: int = 0
    next_7_days: int = 0
    by_source: dict[str, int] = Field(default_factory=dict)


class StatusOut(BaseModel):
    app: str
    version: str
    ok: bool
    server_time: datetime
    timezone: str
    database: dict[str, Any]
    scheduler: dict[str, Any]
    last_sync: Optional[dict[str, Any]] = None
    connectors: list[ConnectorStatus] = Field(default_factory=list)
    counts: CountsOut = Field(default_factory=CountsOut)


class DeviceFlowOut(BaseModel):
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    device_code: str
    expires_in: int
    interval: int
    message: str


class DeviceFlowPollOut(BaseModel):
    state: str  # pending | authorized | expired | error
    account: Optional[str] = None
    message: Optional[str] = None


class SimpleResult(BaseModel):
    ok: bool
    message: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)


class UserOut(BaseModel):
    """Account rendered for the UI (never carries the password hash)."""

    id: int
    username: str
    display_name: Optional[str] = None
    role: str = "user"
    is_admin: bool = False
    is_active: bool = True
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class RegisterIn(BaseModel):
    """Loose on purpose: format rules live in ``accounts.validate_*`` so a bad
    username answers HTTP 400 with a readable Chinese message rather than a
    pydantic 422 envelope."""

    username: str = Field(max_length=64)
    password: str = Field(max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=64)
    invite_code: Optional[str] = Field(default=None, max_length=200)
    captcha_token: Optional[str] = Field(default=None, max_length=400)
    captcha_answer: Optional[str] = Field(default=None, max_length=16)


class RegistrationSettingsIn(BaseModel):
    """Admin edit of the sign-up gate (all optional; only sent fields change)."""

    invite_code: Optional[str] = Field(default=None, max_length=200)
    invite_required: Optional[bool] = None
    captcha_enabled: Optional[bool] = None
    rotate: bool = False
    clear_invite_code: bool = False


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


class PasswordChangeIn(BaseModel):
    old_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class UserPatchIn(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
