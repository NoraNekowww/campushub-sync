"""Self-hosted image CAPTCHA: SVG challenge + stateless HMAC token.

Why not reCAPTCHA / hCaptcha: both are served from ``google.com`` /
``hcaptcha.com`` and are unreachable from mainland China — the exact problem
this module exists to solve. Cloudflare Turnstile is also flaky there. 极验 and
腾讯云验证码 do work in China but need a paid account and a pair of API keys we
do not have.

So the challenge is rendered by us, with **zero new dependencies**:

* the code is drawn as SVG (per-character rotation + jitter, noise curves and
  specks), so no Pillow / no image library is needed — just text;
* the answer never travels to the client and is never stored server-side: it is
  folded into an HMAC-SHA256 token (key = the same ``SESSION_SECRET`` the login
  cookie uses) together with the expiry, a nonce and the caller's IP.
  Verifying is a signature check, so this stays stateless and multi-worker safe.

Swap-in point: ``issue()`` / ``verify()`` are the only two functions the rest of
the app calls, so a 极验 v4 / 腾讯云 adapter can replace this module wholesale
(``GET /auth/captcha`` would return ``{"provider": ..., "payload": {...}}``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import random
import secrets
import time
from typing import Any, Optional

from . import accounts
from .config import Settings

log = logging.getLogger("campushub.captcha")

#: No ``0``/``O``/``1``/``I``/``L`` — they are the characters people misread, and
#: a captcha that fails honest users is worse than no captcha.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
VERSION = "c1"
TTL_SECONDS = 300
DEFAULT_LENGTH = 4

__all__ = ["ALPHABET", "DEFAULT_LENGTH", "TTL_SECONDS", "issue", "new_code", "render_svg", "verify"]


def new_code(length: int = DEFAULT_LENGTH) -> str:
    rnd = random.SystemRandom()
    return "".join(rnd.choice(ALPHABET) for _ in range(max(1, min(length, 8))))


def _normalise(value: Optional[str]) -> str:
    """Upper-case and drop whitespace — the only fuzziness we allow."""
    return "".join((value or "").split()).upper()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _ip_tag(ip: Optional[str]) -> str:
    """Short, non-reversible tag so the token is bound to the caller."""
    return hashlib.sha256((ip or "-").encode("utf-8")).hexdigest()[:12]


def _sign(settings: Settings, message: str) -> str:
    secret = accounts.get_session_secret(settings)
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64(digest)


def render_svg(code: str, width: int = 148, height: int = 52) -> str:
    """Draw *code* as SVG text with jitter, noise curves and specks.

    The plate carries its own light background so the code stays readable no
    matter which theme the page is in (the app ships both a light and a dark
    palette), and the noise is drawn *behind* the glyphs.
    """
    rnd = random.SystemRandom()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="图形验证码" '
        f'class="campushub-captcha-svg">',
        f'<rect width="{width}" height="{height}" rx="10" fill="#eef2f7"/>',
    ]

    for _ in range(3):
        x1, x2 = rnd.uniform(0, width * 0.35), rnd.uniform(width * 0.65, width)
        y1, y2 = rnd.uniform(6, height - 6), rnd.uniform(6, height - 6)
        cx1, cx2 = rnd.uniform(0, width), rnd.uniform(0, width)
        cy1, cy2 = rnd.uniform(-8, height + 8), rnd.uniform(-8, height + 8)
        colour = rnd.choice(["#93c5fd", "#a5b4fc", "#f9a8d4", "#6ee7b7", "#fcd34d"])
        parts.append(
            f'<path d="M{x1:.1f},{y1:.1f} C{cx1:.1f},{cy1:.1f} {cx2:.1f},{cy2:.1f} {x2:.1f},{y2:.1f}" '
            f'fill="none" stroke="{colour}" stroke-width="{rnd.uniform(1.1, 2.0):.1f}" '
            f'stroke-opacity="0.75" stroke-linecap="round"/>'
        )

    step = (width - 26) / max(1, len(code))
    for index, char in enumerate(code):
        x = 13 + step * (index + 0.5) + rnd.uniform(-1.8, 1.8)
        y = height / 2 + rnd.uniform(-3.5, 3.5)
        size = rnd.uniform(25, 30)
        rotate = rnd.uniform(-26, 26)
        colour = rnd.choice(["#0f172a", "#1e293b", "#334155", "#1d4ed8", "#7c2d12"])
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" transform="rotate({rotate:.1f} {x:.1f} {y:.1f})" '
            f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
            f'font-size="{size:.1f}" font-weight="700" fill="{colour}" '
            f'text-anchor="middle" dominant-baseline="central">{html.escape(char)}</text>'
        )

    for _ in range(22):
        parts.append(
            f'<circle cx="{rnd.uniform(0, width):.1f}" cy="{rnd.uniform(0, height):.1f}" '
            f'r="{rnd.uniform(0.6, 1.5):.1f}" fill="#64748b" fill-opacity="0.45"/>'
        )

    parts.append("</svg>")
    return "".join(parts)


def issue(settings: Settings, ip: Optional[str] = None, length: int = DEFAULT_LENGTH) -> dict[str, Any]:
    """Return ``{token, svg, expires_in, length}`` for a fresh challenge."""
    code = new_code(length)
    expires_at = int(time.time()) + TTL_SECONDS
    nonce = secrets.token_urlsafe(6)
    ip_tag = _ip_tag(ip)
    message = f"{VERSION}.{expires_at}.{nonce}.{ip_tag}.{_normalise(code)}"
    token = f"{VERSION}.{expires_at}.{nonce}.{ip_tag}.{_sign(settings, message)}"
    return {
        "token": token,
        "svg": render_svg(code),
        "expires_in": TTL_SECONDS,
        "length": len(code),
    }


def verify(
    settings: Settings,
    token: Optional[str],
    answer: Optional[str],
    ip: Optional[str] = None,
) -> tuple[bool, str]:
    """Validate an answer against its token → ``(ok, reason)``.

    ``reason`` is a Chinese, user-facing sentence; an empty string means OK.
    """
    submitted = _normalise(answer)
    if not submitted:
        return False, "请输入图形验证码"
    if not token:
        return False, "验证码已失效，请点击图片刷新"

    parts = token.split(".")
    if len(parts) != 5 or parts[0] != VERSION:
        return False, "验证码已失效，请点击图片刷新"
    _, expires_raw, nonce, ip_tag, signature = parts

    expected = _sign(settings, f"{VERSION}.{expires_raw}.{nonce}.{ip_tag}.{submitted}")
    if not hmac.compare_digest(expected, signature):
        return False, "验证码不正确"

    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False, "验证码已失效，请点击图片刷新"
    if expires_at < int(time.time()):
        return False, "验证码已过期，请点击图片刷新"
    if not hmac.compare_digest(ip_tag, _ip_tag(ip)):
        # Catch-all for a token replayed from somewhere else; the message stays
        # generic on purpose (no oracle for which half of the pair was wrong).
        return False, "验证码已失效，请点击图片刷新"

    if not _burn(nonce, expires_at):
        return False, "验证码已使用过，请点击图片刷新"

    return True, ""


# --------------------------------------------------------------------------- #
# single-use bookkeeping
# --------------------------------------------------------------------------- #

USED_PREFIX = "captcha.used."


def _prune(kv: Any) -> set[str]:
    """Nonces still alive inside their TTL; anything stale is dropped."""
    now = int(time.time())
    alive: set[str] = set()
    for key in kv.keys(USED_PREFIX):
        value = kv.get(key)
        if isinstance(value, int) and value >= now:
            alive.add(key[len(USED_PREFIX):])
        else:
            kv.delete(key)
    return alive


def _burn(nonce: str, expires_at: int) -> bool:
    """Mark a challenge as spent → False when it was already used.

    The token is stateless, so single use needs one small piece of state: without
    it, one solved captcha could be replayed for a burst of sign-ups — which is
    exactly what a captcha exists to prevent.
    """
    try:
        from .db import KVStore
    except Exception:  # pragma: no cover - DB unavailable: fail closed on replay only
        return True
    kv = KVStore()
    if nonce in _prune(kv):
        return False
    kv.set(USED_PREFIX + nonce, expires_at)
    return True
