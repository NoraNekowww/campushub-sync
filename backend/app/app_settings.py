"""Runtime-mutable registration settings (invite code / captcha), stored in KV.

``config.Settings`` is a pydantic ``BaseSettings`` read from env and cached with
``lru_cache``, so the站主 cannot change the registration gate without editing
``.env`` and restarting the service. These three knobs are exactly the ones a
live instance wants to tune (share a code, rotate it, switch to the captcha), so
they live in the ``kv`` table instead and *override* the env value when set.

Resolution order everywhere: **KV override → env/config → built-in default.**
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Optional

from .config import Settings
from .db import KVStore

log = logging.getLogger("campushub.app_settings")

INVITE_CODE_KEY = "accounts.invite_code"
INVITE_REQUIRED_KEY = "accounts.invite_required"
CAPTCHA_ENABLED_KEY = "accounts.captcha_enabled"

#: Same unambiguous alphabet the captcha uses — no 0/O/1/I/L to mistype.
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_INVITE_BODY = 8


def new_invite_code(prefix: str = "TJU") -> str:
    """A shareable invite code, e.g. ``TJU-7K4M9QZX``."""
    body = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(_INVITE_BODY))
    return f"{prefix}-{body}"


def _store() -> KVStore:
    """全站设置（注册门等）始终在**全局**空间，不跟账号走。"""
    return KVStore("")


def _tri_state(key: str) -> Optional[bool]:
    value = _store().get(key, None)
    return bool(value) if isinstance(value, bool) else None


def get_invite_code(settings: Settings) -> Optional[str]:
    """KV first, then ``REGISTRATION_INVITE_CODE`` from the environment."""
    override = _store().get(INVITE_CODE_KEY, None)
    if isinstance(override, str) and override.strip():
        return override.strip()
    return settings.registration_invite_code


def invite_required(settings: Settings) -> bool:
    """Is the invite code enforced? Explicit KV flag → env → "any code set"."""
    flag = _tri_state(INVITE_REQUIRED_KEY)
    if flag is not None:
        return flag
    return bool(get_invite_code(settings))


def captcha_enabled(settings: Settings) -> bool:
    """Is the image captcha enforced? Defaults to **on** — it is the door."""
    flag = _tri_state(CAPTCHA_ENABLED_KEY)
    if flag is not None:
        return flag
    return bool(getattr(settings, "captcha_enabled", True))


def registration_open(settings: Settings) -> bool:
    """Can a stranger sign up at all?

    With the captcha on, the captcha *is* the gate, so registration is open even
    when no invite code exists — that is the whole point of replacing the code
    with a challenge.
    """
    if not settings.accounts_enabled:
        return False
    return bool(
        invite_required(settings)
        or captcha_enabled(settings)
        or settings.allow_open_registration
    )


def snapshot(settings: Settings) -> dict[str, Any]:
    """Everything the admin UI (and the sign-up form) needs to render."""
    code = get_invite_code(settings)
    return {
        "invite_code": code,
        "invite_required": invite_required(settings),
        "captcha_enabled": captcha_enabled(settings),
        "allow_open_registration": settings.allow_open_registration,
        "accounts_enabled": settings.accounts_enabled,
        "registration_open": registration_open(settings),
        "captcha_provider": "builtin-svg",
        "source": {
            "invite_code": "kv" if _store().get(INVITE_CODE_KEY, None) else "env",
            "invite_required": "kv" if _tri_state(INVITE_REQUIRED_KEY) is not None else "derived",
            "captcha_enabled": "kv" if _tri_state(CAPTCHA_ENABLED_KEY) is not None else "env",
        },
    }


def update(
    settings: Settings,
    *,
    invite_code: Optional[str] = None,
    invite_required: Optional[bool] = None,
    captcha_enabled: Optional[bool] = None,
    rotate: bool = False,
    clear_invite_code: bool = False,
) -> dict[str, Any]:
    """Apply admin edits. Only the arguments that are not ``None`` change."""
    store = _store()

    if rotate:
        store.set(INVITE_CODE_KEY, new_invite_code())
        store.set(INVITE_REQUIRED_KEY, True)  # a fresh code is meant to be used
        log.info("invite code rotated by admin")
    elif clear_invite_code:
        store.set(INVITE_CODE_KEY, None)
        store.set(INVITE_REQUIRED_KEY, False)
        log.info("invite code cleared by admin")
    elif invite_code is not None:
        cleaned = invite_code.strip()
        store.set(INVITE_CODE_KEY, cleaned or None)
        if cleaned:
            store.set(INVITE_REQUIRED_KEY, True)

    if invite_required is not None:
        store.set(INVITE_REQUIRED_KEY, bool(invite_required))
        if invite_required and not get_invite_code(settings):
            # Asking for a code nobody has is a trap — mint one.
            store.set(INVITE_CODE_KEY, new_invite_code())

    if captcha_enabled is not None:
        store.set(CAPTCHA_ENABLED_KEY, bool(captcha_enabled))

    return snapshot(settings)
