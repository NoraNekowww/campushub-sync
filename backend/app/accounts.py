"""Accounts, passwords and stateless session cookies.

Design notes
------------
* **No new dependencies.** Passwords use ``hashlib.pbkdf2_hmac`` (260k rounds,
  SHA-256, 16-byte salt) and the session cookie is a compact HMAC-SHA256 signed
  token — the same primitives the two shared tokens already rely on.
* **Stateless sessions.** The cookie carries ``user id + role + expiry`` and a
  signature, so a restart does not log anyone out and no session table is
  needed. Revocation = bump the secret, disable the account, or short TTLs.
* **SameSite=Lax + HttpOnly.** Every mutating endpoint is POST/PATCH/DELETE,
  which Lax never sends cross-site, so the cookie doubles as CSRF protection
  without a token-in-body dance.
* **Throttling.** Failed logins are counted in memory per ``username|ip`` and
  the window resets on success; a hostile script burns its budget on the first
  few guesses instead of the whole keyspace.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from .config import Settings, get_settings
from .models import User, UserRole
from .timeutil import get_tz, utcnow

log = logging.getLogger("campushub.accounts")

PBKDF2_ROUNDS = 260_000
_SALT_BYTES = 16
SESSION_VERSION = "v1"

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{2,31}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 200

_secret_cache: dict[str, str] = {}
_secret_lock = threading.Lock()


class AccountError(ValueError):
    """Raised for user-facing validation problems (mapped to HTTP 400)."""


class AccountExists(AccountError):
    """Username already taken (mapped to HTTP 409)."""


# --------------------------------------------------------------------- secrets


def get_session_secret(settings: Optional[Settings] = None) -> str:
    """Return the HMAC key for session cookies.

    Precedence: ``SESSION_SECRET`` env/config, then a generated file under the
    data dir (0600). Persisting it matters — otherwise every restart would
    silently invalidate every login.
    """
    settings = settings or get_settings()
    if settings.session_secret:
        return settings.session_secret

    path = Path(settings.resolve_data_path("session.secret"))
    key = str(path)
    with _secret_lock:
        cached = _secret_cache.get(key)
        if cached:
            return cached
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    _secret_cache[key] = value
                    return value
        except OSError:  # pragma: no cover - unreadable volume
            log.warning("could not read %s, generating a volatile session secret", path)

        value = secrets.token_urlsafe(48)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            log.info("generated a new session secret at %s", path)
        except OSError:  # pragma: no cover
            log.warning("could not persist the session secret; logins reset on restart")
        _secret_cache[key] = value
        return value


def reset_secret_cache() -> None:
    """Test helper — drop the memoised session secret."""
    with _secret_lock:
        _secret_cache.clear()


# --------------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ROUNDS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
    except (ValueError, binascii.Error):  # pragma: no cover - corrupted row
        return False
    return hmac.compare_digest(candidate, expected)


def owner(session: Session) -> Optional[User]:
    """历史（多租户之前）数据的归属账号：第一个管理员，退而求其次第一个账号。

    共享管理员令牌访问（PWA 里存的那把）没有会话，就落到这个账号上，所以老用法
    不会因为分租户而失效。
    """
    admin = session.exec(
        select(User).where(User.role == UserRole.admin.value).order_by(User.id).limit(1)
    ).first()
    if admin is not None:
        return admin
    return session.exec(select(User).order_by(User.id).limit(1)).first()


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise AccountError("用户名需为 3-32 位字母、数字、下划线或连字符，且以字母/数字开头")
    return username


def validate_password(password: str, settings: Optional[Settings] = None) -> str:
    settings = settings or get_settings()
    minimum = max(MIN_PASSWORD, int(settings.password_min_length or MIN_PASSWORD))
    if not password or len(password) < minimum:
        raise AccountError(f"密码至少 {minimum} 位")
    if len(password) > MAX_PASSWORD:
        raise AccountError("密码过长")
    if password.isdigit() or password.isalpha():
        raise AccountError("密码需要同时包含字母和数字")
    return password


# ---------------------------------------------------------------------- sessions


@dataclass(frozen=True)
class SessionData:
    user_id: int
    role: str
    expires_at: int


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_session(user: User, settings: Optional[Settings] = None) -> tuple[str, int]:
    """Return ``(cookie_value, max_age_seconds)`` for *user*."""
    settings = settings or get_settings()
    ttl = max(300, int(settings.session_ttl_hours) * 3600)
    expires_at = int(time.time()) + ttl
    payload = f"{SESSION_VERSION}.{user.id}.{user.role}.{expires_at}"
    signature = hmac.new(
        get_session_secret(settings).encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    return f"{payload}.{_b64(signature)}", ttl


def read_session(token: Optional[str], settings: Optional[Settings] = None) -> Optional[SessionData]:
    if not token:
        return None
    settings = settings or get_settings()
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != SESSION_VERSION:
        return None
    _, raw_id, role, raw_exp, raw_sig = parts
    payload = ".".join(parts[:4])
    expected = hmac.new(
        get_session_secret(settings).encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    try:
        provided = _unb64(raw_sig)
    except (binascii.Error, ValueError):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        user_id = int(raw_id)
        expires_at = int(raw_exp)
    except ValueError:
        return None
    if expires_at < int(time.time()):
        return None
    return SessionData(user_id=user_id, role=role, expires_at=expires_at)


def load_user(session: Session, token: Optional[str], settings: Optional[Settings] = None) -> Optional[User]:
    """Resolve a session cookie to an active user (``None`` when invalid)."""
    data = read_session(token, settings)
    if data is None:
        return None
    user = session.get(User, data.user_id)
    if user is None or not user.is_active:
        return None
    # Cheap liveness marker for the admin user list; at most one write a minute.
    now = utcnow()
    if user.last_seen_at is None or (now - user.last_seen_at) > timedelta(minutes=1):
        try:
            user.last_seen_at = now
            session.add(user)
            session.commit()
        except Exception:  # pragma: no cover - never fail a request over telemetry
            session.rollback()
    return user


# ------------------------------------------------------------------------ users


def user_count(session: Session) -> int:
    return len(session.exec(select(User.id)).all())


def get_by_username(session: Session, username: str) -> Optional[User]:
    username = (username or "").strip()
    if not username:
        return None
    return session.exec(select(User).where(User.username == username)).first()


def create_user(
    session: Session,
    username: str,
    password: str,
    *,
    display_name: Optional[str] = None,
    role: Optional[str] = None,
    created_ip: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> User:
    settings = settings or get_settings()
    username = validate_username(username)
    password = validate_password(password, settings)
    if get_by_username(session, username) is not None:
        raise AccountExists("该用户名已被注册")

    if role is None:
        first = user_count(session) == 0
        role = UserRole.admin.value if (first and settings.first_user_is_admin) else UserRole.user.value

    user = User(
        username=username,
        display_name=(display_name or "").strip() or username,
        password_hash=hash_password(password),
        role=role,
        created_at=utcnow(),
        created_ip=created_ip,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    log.info("account created: %s (%s)", user.username, user.role)
    return user


def authenticate(
    session: Session,
    username: str,
    password: str,
    settings: Optional[Settings] = None,
) -> Optional[User]:
    user = get_by_username(session, username)
    if user is None:
        # Burn a hash anyway so a missing user is not obviously faster.
        hash_password(password or "")
        return None
    if not verify_password(password or "", user.password_hash):
        return None
    if not user.is_active:
        return None
    user.last_login_at = utcnow()
    user.last_seen_at = user.last_login_at
    session.add(user)
    session.commit()
    return user


def change_password(session: Session, user: User, new_password: str, settings: Optional[Settings] = None) -> User:
    user.password_hash = hash_password(validate_password(new_password, settings))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def set_active(session: Session, user: User, active: bool) -> User:
    user.is_active = active
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# --------------------------------------------------------------------- throttle


class LoginThrottle:
    """In-memory failed-login counter (good enough for a single-process app)."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _key(self, username: str, ip: Optional[str]) -> str:
        return f"{(username or '').strip().lower()}|{ip or '-'}"

    def check(self, username: str, ip: Optional[str], settings: Optional[Settings] = None):
        settings = settings or get_settings()
        window = max(1, int(settings.login_window_minutes)) * 60
        limit = max(1, int(settings.login_max_attempts))
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(self._key(username, ip), []) if now - t < window]
            self._hits[self._key(username, ip)] = hits
        if len(hits) >= limit:
            retry_after = int(window - (now - hits[0])) + 1
            return retry_after
        return 0

    def register_failure(self, username: str, ip: Optional[str]) -> None:
        key = self._key(username, ip)
        with self._lock:
            self._hits.setdefault(key, []).append(time.time())

    def reset(self, username: str, ip: Optional[str]) -> None:
        with self._lock:
            self._hits.pop(self._key(username, ip), None)


throttle = LoginThrottle()


# --------------------------------------------------------------------- payloads


def user_payload(user: User) -> dict:
    from .timeutil import iso_local

    def label(value):
        return value.astimezone(get_tz()).strftime("%Y-%m-%d %H:%M") if value else None

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "created_at": iso_local(user.created_at),
        "last_login_at": iso_local(user.last_login_at) if user.last_login_at else None,
        # pre-formatted Asia/Shanghai strings for the settings panel
        "created_at_label": label(user.created_at),
        "last_login_label": label(user.last_login_at),
    }
