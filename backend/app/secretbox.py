"""Encryption at rest for the credentials the app keeps on users' behalf.

The ``kv`` table used to hold 教务 passwords, 微北洋 tokens, Microsoft refresh
tokens and the registration invite code as plain JSON, so a copied database file
— or any SQL-level leak — handed over real passwords. This module wraps those
values in a self-describing envelope::

    enc1:<keyid>:<fernet-token>

``<fernet-token>`` is a ``cryptography`` Fernet token: AES-128-CBC encrypted and
HMAC-SHA256 *authenticated*, so a tampered row fails loudly instead of decrypting
into garbage. The key is derived with HKDF-SHA256 from a vault secret that is
deliberately **separate** from ``SESSION_SECRET`` — rotating sessions must never
orphan stored credentials, and vice versa.

``<keyid>`` is the first 8 hex chars of SHA-256 over the derived key, which is
what lets us say "the vault key changed" instead of the far more alarming "your
credentials are gone" when someone edits the environment.

Precedence mirrors ``accounts.get_session_secret``: ``CREDENTIAL_KEY``
(env / ``.env``) first, else a generated ``data/credential.key`` with mode 0600.
Losing that secret only loses the *stored* credentials: the users are asked to
paste their 教务/微软 login once more, everything already imported survives.

Rows written before this module carry no ``enc1:`` prefix and stay readable;
``tools/encrypt_kv_secrets.py`` rewrites them in place (idempotent).

Deliberately not encrypted: course/calendar payloads (not secrets) and account
passwords, which stay one-way PBKDF2 hashes in ``accounts.py`` — a password you
can decrypt is a password you can leak.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import Settings, get_settings

__all__ = [
    "PREFIX",
    "SECRET_KEYS",
    "KeyMismatchError",
    "SecretBoxError",
    "decrypt_value",
    "encrypt_value",
    "get_vault_key",
    "is_encrypted",
    "is_secret_key",
    "key_id",
    "reset_caches",
    "self_check",
]

log = logging.getLogger(__name__)

#: Marker every encrypted value starts with (versioned: a future format can ship
#: as ``enc2:`` and still read ``enc1:`` blobs).
PREFIX = "enc1:"

_HKDF_SALT = b"campushub-secretbox-v1"
_HKDF_INFO = b"kv-credential-encryption"
_KEY_FILE = "credential.key"

#: Keys whose values must never sit in the database in the clear. Kept explicit
#: — plus a tail pattern, so a connector added later cannot *silently* opt out —
#: because blanket encryption would also hide payloads we want to grep.
SECRET_KEYS = frozenset(
    {
        "tju.jw_credentials",  # 学号 + 教务系统密码
        "tju.token",  # 微北洋 access token
        "ms.tokens",  # Microsoft access + refresh token
        "ms.device_flow",  # device-code flow state (holds the device code)
        "accounts.invite_code",  # 泄漏 = 陌生注册
    }
)

_SECRET_KEY_RE = re.compile(
    r"(?:^|\.)(credentials?|tokens?|device_flow|secrets?|passw(or)?d|api_key)$",
    re.IGNORECASE,
)

_KEY_CACHE: dict[str, bytes] = {}
_KEY_LOCK = threading.Lock()


class SecretBoxError(RuntimeError):
    """The stored blob cannot be read back."""


class KeyMismatchError(SecretBoxError):
    """The blob was written with a different vault key (usually a changed env)."""


# ------------------------------------------------------------------ key material


def is_secret_key(key: str) -> bool:
    """Should ``key`` (namespace stripped) be stored encrypted?"""
    return key in SECRET_KEYS or bool(_SECRET_KEY_RE.search(key))


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def get_vault_key(settings: Optional[Settings] = None) -> bytes:
    """The derived 32-byte Fernet key (memoised per secret source)."""
    settings = settings or get_settings()
    env_value = (settings.credential_key or "").strip()
    cache_key = "env" if env_value else str(Path(settings.resolve_data_path(_KEY_FILE)))

    with _KEY_LOCK:
        cached = _KEY_CACHE.get(cache_key)
        if cached is not None:
            return cached

        material = env_value
        if not material:
            path = Path(cache_key)
            try:
                if path.is_file():
                    material = path.read_text(encoding="utf-8").strip()
            except OSError:  # pragma: no cover - unreadable volume
                log.warning("could not read %s; generating a volatile vault key", path)
            if not material:
                material = secrets.token_urlsafe(48)
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(material, encoding="utf-8")
                    try:
                        os.chmod(path, 0o600)
                    except OSError:  # pragma: no cover - exotic filesystems
                        pass
                    log.info("generated a new credential vault key at %s", path)
                except OSError:  # pragma: no cover
                    log.warning(
                        "could not persist the credential vault key; stored "
                        "credentials will stop decrypting on restart"
                    )

        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_HKDF_SALT,
            info=_HKDF_INFO,
        ).derive(material.encode("utf-8"))
        _KEY_CACHE[cache_key] = derived
        return derived


def key_id(settings: Optional[Settings] = None) -> str:
    """Short, non-reversible fingerprint of the active vault key."""
    return hashlib.sha256(get_vault_key(settings)).hexdigest()[:8]


def _fernet(settings: Optional[Settings] = None) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(get_vault_key(settings)))


# ------------------------------------------------------------------- encrypt/decrypt


def encrypt_text(plain: str) -> str:
    token = _fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return f"{PREFIX}{key_id()}:{token}"


def decrypt_text(blob: str) -> str:
    if not is_encrypted(blob):
        raise SecretBoxError("value is not encrypted")
    try:
        _, blob_key_id, token = blob.split(":", 2)
    except ValueError:  # pragma: no cover - malformed row
        raise SecretBoxError("malformed encrypted value") from None

    current = key_id()
    if blob_key_id and blob_key_id != current:
        raise KeyMismatchError(
            f"vault key mismatch: value was sealed with key {blob_key_id}, "
            f"current key is {current} (CREDENTIAL_KEY changed, or "
            f"{_KEY_FILE} was replaced)"
        )
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise SecretBoxError(
            "encrypted value failed authentication (tampered, or sealed with "
            "another key)"
        ) from None


def encrypt_value(value: Any) -> str:
    """Seal any JSON-able value into an ``enc1:`` blob."""
    return encrypt_text(json.dumps(value, ensure_ascii=False, default=str))


def decrypt_value(blob: Any, default: Any = None, *, key: str = "") -> Any:
    """Unseal a stored value.

    Plain (pre-vault) rows are returned untouched, and an unreadable blob
    degrades to ``default`` with a loud log line: a rotated vault key must look
    like "nothing saved" to the user, never like a 500 from every request.
    """
    if not is_encrypted(blob):
        return blob
    try:
        return json.loads(decrypt_text(blob))
    except SecretBoxError as exc:
        log.warning("cannot decrypt stored value%s: %s", f" for {key}" if key else "", exc)
        return default


# ---------------------------------------------------------------------- helpers


def self_check(settings: Optional[Settings] = None) -> dict[str, Any]:
    """Round-trip probe used at startup so a broken vault is obvious in the log."""
    probe = "vault-probe"
    try:
        ok = decrypt_text(encrypt_text(probe)) == probe
    except Exception as exc:  # pragma: no cover - only on a broken crypto backend
        log.error("credential vault probe failed: %s", exc)
        return {"ok": False, "key_id": "", "error": str(exc)}
    return {"ok": ok, "key_id": key_id(settings)}


def reset_caches() -> None:
    """Test helper — forget the memoised vault key."""
    with _KEY_LOCK:
        _KEY_CACHE.clear()
