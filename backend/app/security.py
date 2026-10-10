"""Access control: shared tokens, account sessions, and the iCal feed token.

Three credentials, three jobs:

* ``ADMIN_TOKEN``      — shared machine secret for ``POST /api/sync``,
  ``PATCH /api/events/{id}``, uploads, and every admin-only route.
* ``SUBSCRIBE_TOKEN``  — the calendar subscription URL, since calendar clients
  cannot send custom headers (the token travels in the query string).
* **account session**  — an HMAC-signed cookie issued by ``/api/auth/login``.
  A signed-in account reads everything; an ``admin``-role account may also
  write, which is what lets the PWA be used from a phone without pasting the
  admin token into a text field.

When *no* token is configured the matching surface stays open so local
development works out of the box; startup logs a loud warning in that case.
"""

from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlmodel import Session

from . import accounts
from .config import get_settings
from .db import get_session, session_scope
from .models import User

log = logging.getLogger("campushub.security")


def _matches(expected: Optional[str], provided: Optional[str]) -> bool:
    if not expected:
        return True  # dev mode
    if not provided:
        return False
    return secrets.compare_digest(expected, provided)


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def session_user(request: Request, session: Optional[Session] = None) -> Optional[User]:
    """Resolve the account cookie on *request* (``None`` when absent/invalid)."""
    settings = get_settings()
    if not settings.accounts_enabled:
        return None
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    try:
        if session is not None:
            return accounts.load_user(session, token, settings)
        with session_scope() as own_session:
            return accounts.load_user(own_session, token, settings)
    except Exception as exc:  # noqa: BLE001 - a broken cookie must not 500
        log.debug("session lookup failed: %s", exc)
        return None


def require_admin(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> None:
    settings = get_settings()
    provided = x_admin_token or _bearer(authorization)
    if not _matches(settings.admin_token, provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_read(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
    x_subscribe_token: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None, description="subscribe token (share links)"),
) -> None:
    """Read-only guard: admin token, subscribe token, or a signed-in account.

    The subscribe token is the "share this calendar" credential, so the PWA can
    run read-only on a device that never sees the admin secret (a ``?token=``
    query parameter also works, which is what makes the magic link in Settings
    convenient on a phone). Mutations only ever accept the admin token or an
    admin-role account.
    """
    settings = get_settings()
    candidates = [x_admin_token, x_subscribe_token, token, _bearer(authorization)]

    # Nothing configured: local development stays open (startup logs a warning).
    if not settings.admin_token and not settings.subscribe_token:
        return

    for candidate in candidates:
        if not candidate:
            continue
        if settings.admin_token and secrets.compare_digest(settings.admin_token, candidate):
            return
        if settings.subscribe_token and secrets.compare_digest(settings.subscribe_token, candidate):
            return

    if session_user(request) is not None:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_write(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> None:
    """Mutating guard: admin token **or** an admin-role account session."""
    settings = get_settings()
    provided = x_admin_token or _bearer(authorization)
    if settings.admin_token and provided and secrets.compare_digest(settings.admin_token, provided):
        return
    user = session_user(request)
    if user is not None and user.is_admin:
        return
    if not settings.admin_token:
        return  # dev mode: no shared secret configured (startup logs a warning)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="admin privileges required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_account(request: Request, session: Session) -> User:
    """Dependency-free helper for routes that need a signed-in account."""
    user = session_user(request, session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要登录",
        )
    return user


def require_admin_account(request: Request, session: Session) -> User:
    user = require_account(request, session)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def current_account(request: Request, session: Session = Depends(get_session)) -> User:
    """Dependency: the signed-in account (401 otherwise).

    Declared as a *dependency* on purpose — FastAPI runs sub-dependencies
    before it validates the request body, so an anonymous caller gets a clean
    401 instead of a pydantic 422.
    """
    return require_account(request, session)


def current_admin(request: Request, session: Session = Depends(get_session)) -> User:
    """Dependency: the signed-in account, which must be an admin (403/401)."""
    return require_admin_account(request, session)


def scope_for_request(request: Request, session: Session) -> Optional[int]:
    """这个请求该用哪个账号的凭据空间（多租户，供 ``main.bind_kv_scope`` 用）。

    登录会话优先；只带共享管理员令牌时落到 owner（老的单机用法继续有效）。
    没身份就返回 ``None`` = 全局空间 —— 注册设置、验证码这类全站数据在这里。
    """
    user = session_user(request, session)
    if user is None:
        settings = get_settings()
        provided = request.headers.get("x-admin-token") or _bearer(
            request.headers.get("authorization")
        )
        if (
            provided
            and settings.admin_token
            and secrets.compare_digest(settings.admin_token, provided)
        ):
            user = accounts.owner(session)
    return user.id if user is not None else None


def timeline_owner(request: Request, session: Session = Depends(get_session)) -> User:
    """Dependency: whose timeline this request touches.

    登录会话优先；只带共享管理员令牌（PWA 里存的那把、或探针脚本）时落到
    ``owner`` —— 多租户之前那份数据的账号，所以老用法不会因为分租户而失效。
    分享用的 subscribe token 不构成身份：匿名 + 分享令牌会被拒，分享链接保持只读。
    """
    user = session_user(request, session)
    if user is not None:
        return user

    settings = get_settings()
    provided = request.headers.get("x-admin-token") or _bearer(
        request.headers.get("authorization")
    )
    is_admin_token = bool(
        settings.admin_token
        and provided
        and secrets.compare_digest(settings.admin_token, provided)
    )
    if is_admin_token or not settings.admin_token:
        owner = accounts.owner(session)
        if owner is not None:
            return owner

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="需要登录：时间线按账号隔离，请先登录或带管理员令牌",
    )


def current_admin_or_token(
    request: Request,
    session: Session = Depends(get_session),
) -> Optional[User]:
    """Dependency: admin via the shared token **or** via an admin account.

    The PWA keeps the shared admin token in ``localStorage`` and sends it as
    ``X-Admin-Token``; the portal instead has a signed-in admin session. Admin
    settings routes accept both, and return the account when there is one
    (``None`` for the shared token, which carries no identity).
    """
    settings = get_settings()
    if is_admin_request(request):
        return session_user(request, session)
    if not settings.admin_token:
        return None  # dev mode: nothing configured, startup logs a warning
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="需要管理员权限",
    )


def verify_subscribe_token(token: Optional[str] = Query(default=None)) -> None:
    settings = get_settings()
    if not _matches(settings.subscribe_token, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid subscription token",
        )


def is_admin_request(request: Request) -> bool:
    """Admin token or admin-role session? Reads the headers directly."""
    settings = get_settings()
    provided = request.headers.get("x-admin-token") or _bearer(request.headers.get("authorization"))
    if settings.admin_token and provided and secrets.compare_digest(settings.admin_token, provided):
        return True
    user = session_user(request)
    return bool(user is not None and user.is_admin)


def warn_about_open_endpoints() -> None:
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("ADMIN_TOKEN", settings.admin_token),
            ("SUBSCRIBE_TOKEN", settings.subscribe_token),
        )
        if not value
    ]
    if missing:
        log.warning(
            "running without %s — do not expose this instance publicly",
            ", ".join(missing),
        )
    if settings.accounts_enabled and settings.registration_open is False:
        log.info("accounts enabled; self-service registration is closed (invite code not set)")
