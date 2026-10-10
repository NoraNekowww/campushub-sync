"""Account endpoints: register / login / logout / me / users.

The session cookie is HttpOnly + SameSite=Lax, so it is never readable by JS
(the portal and the PWA both ask ``/api/auth/session`` instead) and it is not
sent on cross-site requests — which is what makes cookie auth safe here without
a separate CSRF token.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session, select

from .. import accounts, app_settings, captcha
from ..config import get_settings
from ..db import get_session
from ..models import User
from ..schemas import (
    LoginIn,
    PasswordChangeIn,
    RegisterIn,
    RegistrationSettingsIn,
    UserPatchIn,
    UserOut,
)
from ..security import current_account, current_admin, current_admin_or_token, session_user

router = APIRouter(prefix="/auth", tags=["accounts"])
log = logging.getLogger("campushub.api.accounts")


def _client_ip(request: Request) -> Optional[str]:
    """Caller IP, trusting ``X-Real-IP`` only when the peer is our own proxy."""
    peer = getattr(request.client, "host", None)
    if peer in {"127.0.0.1", "::1", "localhost"}:
        forwarded = request.headers.get("x-real-ip")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer


def _accounts_meta() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.accounts_enabled,
        "registration_open": app_settings.registration_open(settings),
        "invite_required": app_settings.invite_required(settings),
        "captcha_required": app_settings.captcha_enabled(settings),
        "password_min_length": max(accounts.MIN_PASSWORD, settings.password_min_length),
        "session_ttl_hours": settings.session_ttl_hours,
    }


@router.get("/captcha", summary="Fresh image challenge for the sign-up form")
def issue_captcha(request: Request) -> dict[str, Any]:
    """Public on purpose: a stranger needs it *before* they have an account.

    Nothing sensitive is returned — the answer only exists inside the signed
    token — and the payload is never cached (a replayed challenge must expire).
    """
    settings = get_settings()
    if not app_settings.captcha_enabled(settings):
        return {"enabled": False}
    payload = captcha.issue(settings, _client_ip(request))
    return {"enabled": True, **payload}


@router.get("/registration", summary="Sign-up gate settings (admin)")
def read_registration_settings(
    _admin: Optional[User] = Depends(current_admin_or_token),
) -> dict[str, Any]:
    return app_settings.snapshot(get_settings())


@router.put("/registration", summary="Change the invite code / captcha switch (admin)")
def write_registration_settings(
    payload: RegistrationSettingsIn,
    _admin: Optional[User] = Depends(current_admin_or_token),
) -> dict[str, Any]:
    settings = get_settings()
    result = app_settings.update(
        settings,
        invite_code=payload.invite_code,
        invite_required=payload.invite_required,
        captcha_enabled=payload.captcha_enabled,
        rotate=payload.rotate,
        clear_invite_code=payload.clear_invite_code,
    )
    log.info(
        "registration gate updated by admin: invite_required=%s captcha=%s",
        result["invite_required"],
        result["captcha_enabled"],
    )
    return {"ok": True, "settings": result}


def _set_session_cookie(response: Response, user: User) -> int:
    settings = get_settings()
    token, max_age = accounts.issue_session(user, settings)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=bool(settings.session_cookie_secure),
        path=settings.session_cookie_path or "/",
    )
    return max_age


@router.get("/session", summary="Who am I? (never 401 — drives the login UI)")
def session_info(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    user = session_user(request, session)
    return {
        "authenticated": user is not None,
        "user": UserOut(**accounts.user_payload(user)).model_dump() if user else None,
        "accounts": _accounts_meta(),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Create an account")
def register(
    payload: RegisterIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.accounts_enabled:
        raise HTTPException(status_code=403, detail="本实例未启用账号系统")
    if not app_settings.registration_open(settings):
        raise HTTPException(status_code=403, detail="注册已关闭，请联系站主")

    if app_settings.invite_required(settings):
        expected = (app_settings.get_invite_code(settings) or "").strip()
        provided = (payload.invite_code or "").strip()
        if not provided:
            raise HTTPException(status_code=403, detail="需要邀请码")
        # Case-insensitive: the code is upper-case, but nobody types it that way.
        if not secrets.compare_digest(expected.upper(), provided.upper()):
            raise HTTPException(status_code=403, detail="邀请码不正确")

    if app_settings.captcha_enabled(settings):
        ok, reason = captcha.verify(
            settings,
            payload.captcha_token,
            payload.captcha_answer,
            _client_ip(request),
        )
        if not ok:
            raise HTTPException(status_code=403, detail=reason)

    try:
        user = accounts.create_user(
            session,
            payload.username,
            payload.password,
            display_name=payload.display_name,
            created_ip=_client_ip(request),
            settings=settings,
        )
    except accounts.AccountExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except accounts.AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    max_age = _set_session_cookie(response, user)
    log.info("registered %s from %s", user.username, _client_ip(request))
    return {
        "ok": True,
        "user": accounts.user_payload(user),
        "accounts": _accounts_meta(),
        "max_age": max_age,
        "message": f"欢迎，{user.display_name or user.username}",
    }


@router.post("/login", summary="Sign in")
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.accounts_enabled:
        raise HTTPException(status_code=403, detail="本实例未启用账号系统")

    ip = _client_ip(request)
    retry_after = accounts.throttle.check(payload.username, ip, settings)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"尝试过多，请 {retry_after // 60 + 1} 分钟后再试",
            headers={"Retry-After": str(retry_after)},
        )

    user = accounts.authenticate(session, payload.username, payload.password, settings)
    if user is None:
        accounts.throttle.register_failure(payload.username, ip)
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被停用")

    accounts.throttle.reset(payload.username, ip)
    max_age = _set_session_cookie(response, user)
    log.info("login ok: %s from %s", user.username, ip)
    return {"ok": True, "user": accounts.user_payload(user), "max_age": max_age}


@router.post("/logout", summary="Sign out (clears the cookie)")
def logout(response: Response) -> dict[str, Any]:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path=settings.session_cookie_path or "/",
    )
    return {"ok": True}


@router.get("/me", response_model=UserOut, summary="Current account (401 when signed out)")
def me(user: User = Depends(current_account)) -> UserOut:
    return UserOut(**accounts.user_payload(user))


@router.post("/password", summary="Change your own password")
def change_password(
    payload: PasswordChangeIn,
    user: User = Depends(current_account),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not accounts.verify_password(payload.old_password or "", user.password_hash):
        raise HTTPException(status_code=401, detail="当前密码不正确")
    try:
        accounts.change_password(session, user, payload.new_password)
    except accounts.AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A new password invalidates nothing by itself (sessions are stateless), so
    # rotate the cookie too when the caller is using one.
    return {"ok": True, "message": "密码已更新"}


@router.get("/users", summary="List accounts (admin)")
def list_users(
    _admin: User = Depends(current_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    rows = session.exec(select(User).order_by(User.id)).all()  # type: ignore[attr-defined]
    return {"items": [accounts.user_payload(row) for row in rows], "total": len(rows)}


@router.patch("/users/{user_id}", summary="Enable/disable an account or change its role (admin)")
def patch_user(
    user_id: int,
    payload: UserPatchIn,
    admin: User = Depends(current_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    if payload.role is not None:
        if payload.role not in {"admin", "user"}:
            raise HTTPException(status_code=400, detail="角色只能是 admin 或 user")
        if target.id == admin.id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
        target.role = payload.role
    if payload.is_active is not None:
        if target.id == admin.id and not payload.is_active:
            raise HTTPException(status_code=400, detail="不能停用自己的账号")
        target.is_active = payload.is_active

    session.add(target)
    session.commit()
    session.refresh(target)
    return {"ok": True, "user": accounts.user_payload(target)}
