"""Runtime configuration.

Every knob is settable through environment variables (see ``.env.example``).
List-like values are kept as comma separated *strings* and exposed as parsed
properties, which avoids pydantic's JSON-decoding of list env vars and keeps
``docker-compose`` overrides trivial.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- general
    app_name: str = "CampusHub Sync"
    debug: bool = False
    data_dir: Path = Path("data")
    database_url: Optional[str] = None
    timezone: str = "Asia/Shanghai"

    # Shared secrets. When unset the corresponding API is left open (dev mode)
    # and a warning is logged at startup — never run a public host that way.
    admin_token: Optional[str] = None
    subscribe_token: Optional[str] = None
    cors_origins: str = ""

    # ------------------------------------------------- accounts / access control
    # Self-service accounts layered on top of the two shared tokens: a signed-in
    # user gets read access from the *session cookie* (so the PWA works on a
    # phone without pasting a token), while writes still need the admin token or
    # an admin-role account.
    enable_accounts: bool = True
    session_secret: Optional[str] = None  # unset = generate + persist in data_dir
    # Key for encrypting stored *credentials* (教务密码 / 微软令牌 / 邀请码) at
    # rest. Kept separate from SESSION_SECRET on purpose: rotating sessions must
    # not orphan the credentials users pasted in. Unset = generate + persist
    # data/credential.key (0600). Losing it only means users re-enter a password.
    credential_key: Optional[str] = None
    session_ttl_hours: int = 24 * 14
    session_cookie_name: str = "campushub_session"
    session_cookie_path: str = "/"
    session_cookie_secure: bool = False  # set true behind HTTPS on the public host
    registration_invite_code: Optional[str] = None  # required to register when set
    captcha_enabled: bool = True  # self-hosted SVG captcha gates /auth/register
    allow_open_registration: bool = False  # true = anyone may register
    first_user_is_admin: bool = True
    login_max_attempts: int = 8  # per username+IP window
    login_window_minutes: int = 15
    password_min_length: int = 8

    # ------------------------------------------------------------ sync engine
    sync_interval_minutes: int = 10
    # 待办快通道：待办里的勾选/取消勾选变化小、抓得快，用更短的间隔单独刷，
    # 于是「手机上勾掉」不用等整轮（含教务登录）跑完。0 = 关掉快通道。
    # 别调太密：一轮 = 每个清单一次 Graph 请求，几十次/分钟会吃到 429 限流
    # （被限流后要等 Retry-After，反而更慢），5 分钟稳。
    ms_sync_interval_minutes: int = 5
    sync_on_startup: bool = True
    enable_scheduler: bool = True
    public_base_url: str = "https://schedule.nzlab.online"
    event_retention_days: int = 30
    horizon_days: int = 120
    max_events_per_source: int = 5000
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3
    demo_mode: bool = False  # serve synthetic data offline (UI dev / smoke tests)

    # ------------------------------------------------------ Microsoft To Do
    ms_client_id: Optional[str] = None
    ms_client_secret: Optional[str] = None
    ms_tenant: str = "common"
    ms_authority_host: str = "https://login.microsoftonline.com"
    ms_scopes: str = "Tasks.ReadWrite offline_access"
    ms_list_ids: str = ""  # empty = every list in the account
    ms_include_completed: bool = False
    # 待办里勾掉的日程要能在客户端显示成「已划掉」，所以完成态也得回拉；
    # 但不回拉全部历史（那要翻很多页），只看最近这么多天动过的。
    ms_completed_lookback_days: int = 14
    # 清单数量可能十几个，每个清单一次 Graph 请求 —— 并发抓，别排队。
    ms_max_concurrency: int = 6
    ms_include_undue: bool = False
    graph_base_url: str = "https://graph.microsoft.com/v1.0"

    # --------------------------------------------------- TJU academic schedule
    tju_mode: str = "disabled"  # disabled | wepeiyang | imported | ics | demo
    tju_api_base: str = "https://api.twt.edu.cn"
    tju_open_base: str = "https://open.twt.edu.cn/api"
    tju_login_path: str = "/api/v1/auth/login"
    tju_schedule_path: str = "/api/v1/schedule"
    tju_access_token: Optional[str] = None
    tju_username: Optional[str] = None
    tju_password: Optional[str] = None
    tju_ics_path: Optional[str] = None  # relative to data_dir when not absolute

    semester_name: str = "2026 秋季学期"
    semester_start_date: Optional[str] = None  # ISO date of week-1 Monday
    semester_total_weeks: int = 16
    semester_holidays: str = ""
    period_times_json: Optional[str] = None  # override the default period slots

    # ------------------------------------------------------------- properties
    @property
    def scope_list(self) -> list[str]:
        return _split(self.ms_scopes)

    @property
    def list_id_list(self) -> list[str]:
        return _split(self.ms_list_ids)

    @property
    def cors_origin_list(self) -> list[str]:
        return _split(self.cors_origins)

    @property
    def holiday_list(self) -> list[str]:
        return _split(self.semester_holidays)

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        path = (self.data_dir / "campushub.db").resolve()
        return f"sqlite:///{path.as_posix()}"

    @property
    def period_times(self) -> Optional[dict[int, tuple[str, str]]]:
        """Parse ``period_times_json`` into ``{period: ("HH:MM", "HH:MM")}``."""
        if not self.period_times_json:
            return None
        raw: Any = json.loads(self.period_times_json)
        parsed: dict[int, tuple[str, str]] = {}
        for key, value in raw.items():
            if isinstance(value, (list, tuple)) and len(value) == 2:
                parsed[int(key)] = (str(value[0]), str(value[1]))
        return parsed or None

    @property
    def ms_enabled(self) -> bool:
        return bool(self.ms_client_id)

    @property
    def tju_enabled(self) -> bool:
        return self.tju_mode.lower() not in {"", "disabled", "none", "off"}

    @property
    def accounts_enabled(self) -> bool:
        return bool(self.enable_accounts)

    @property
    def registration_open(self) -> bool:
        """Registration needs *some* gate: an invite code or an explicit opt-in."""
        if not self.accounts_enabled:
            return False
        return bool(self.registration_invite_code or self.allow_open_registration)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def resolve_data_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.data_dir / path)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def override_settings(**kwargs: Any) -> Settings:
    """Test helper: rebuild the cached settings with overrides applied."""
    get_settings.cache_clear()
    settings = Settings(**kwargs)
    get_settings.cache_clear()
    return settings
