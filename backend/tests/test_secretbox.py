"""The credential vault: round-trips, tamper detection and KV integration."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from app import secretbox
from app.config import get_settings
from app.db import KV, KVStore, init_db, session_scope
from app.timeutil import utcnow


def _refresh_settings() -> None:
    for name in ("cache_clear", "clear"):
        clear = getattr(get_settings, name, None)
        if callable(clear):
            clear()
            return


@pytest.fixture()
def vault(monkeypatch):
    """Point the vault at a throwaway secret so tests never touch ``data/``."""
    monkeypatch.setenv("CREDENTIAL_KEY", "unit-test-vault-secret")
    _refresh_settings()
    secretbox.reset_caches()
    init_db(get_settings())
    yield secretbox.key_id()
    secretbox.reset_caches()
    monkeypatch.delenv("CREDENTIAL_KEY", raising=False)
    _refresh_settings()


def _raw(key: str) -> str:
    with session_scope() as session:
        row = session.get(KV, key)
        assert row is not None, f"{key} not written"
        return row.value


def test_round_trip_carries_version_and_key_id(vault):
    blob = secretbox.encrypt_value({"username": "3019", "password": "hunter2"})

    assert blob.startswith(secretbox.PREFIX)
    assert blob.split(":", 2)[1] == vault
    assert secretbox.decrypt_value(blob) == {"username": "3019", "password": "hunter2"}


def test_same_plaintext_seals_differently(vault):
    """A fresh IV per write — otherwise equal rows would be visible as equal."""
    first = secretbox.encrypt_value({"password": "hunter2"})
    second = secretbox.encrypt_value({"password": "hunter2"})

    assert first != second
    assert secretbox.decrypt_value(first) == secretbox.decrypt_value(second)


def test_tampering_is_detected(vault):
    blob = secretbox.encrypt_value({"password": "hunter2"})
    head, key_id, token = blob.split(":", 2)
    flipped = "A" if token[10] != "A" else "B"
    tampered = f"{head}:{key_id}:{token[:10]}{flipped}{token[11:]}"

    with pytest.raises(secretbox.SecretBoxError):
        secretbox.decrypt_text(tampered)
    # …and a stored tampered row degrades to "nothing saved" instead of a 500.
    assert secretbox.decrypt_value(tampered, {}, key="tju.jw_credentials") == {}


def test_key_mismatch_is_named_not_silent(vault, monkeypatch):
    blob = secretbox.encrypt_value({"password": "hunter2"})

    monkeypatch.setenv("CREDENTIAL_KEY", "a-different-vault-secret")
    _refresh_settings()
    secretbox.reset_caches()

    with pytest.raises(secretbox.KeyMismatchError):
        secretbox.decrypt_text(blob)
    # …and the store degrades to "nothing saved" instead of raising at the user.
    assert secretbox.decrypt_value(blob, {}, key="tju.jw_credentials") == {}


def test_plaintext_rows_from_before_the_vault_still_read(vault):
    with session_scope() as session:
        session.add(
            KV(
                key="tju.jw_credentials",
                value=json.dumps({"username": "3019", "password": "legacy"}),
                updated_at=utcnow(),
            )
        )

    assert KVStore().get("tju.jw_credentials") == {"username": "3019", "password": "legacy"}


def test_kv_store_encrypts_secret_keys(vault):
    store = KVStore()
    store.set("tju.jw_credentials", {"username": "3019", "password": "hunter2"})

    raw = _raw("tju.jw_credentials")
    assert "hunter2" not in raw
    assert "3019" not in raw
    assert json.loads(raw).startswith(secretbox.PREFIX)
    assert store.get("tju.jw_credentials") == {"username": "3019", "password": "hunter2"}


def test_kv_store_leaves_ordinary_payloads_readable(vault):
    store = KVStore()
    store.set("tju.semester", {"name": "2026 秋季学期", "total_weeks": 20})

    raw = _raw("tju.semester")
    assert json.loads(raw)["name"] == "2026 秋季学期"  # greppable on purpose
    assert store.get("tju.semester")["total_weeks"] == 20


def test_secret_classification(vault):
    for key in (
        "tju.jw_credentials",
        "tju.token",
        "ms.tokens",
        "ms.device_flow",
        "accounts.invite_code",
        "u1:ms.tokens",
        "future_connector.credentials",
        "whatever.password",
    ):
        assert secretbox.is_secret_key(key), key

    for key in (
        "tju.semester",
        "tju.classtable",
        "tju.ics_content",
        "tju.import_meta",
        "ms.account",
        "tju.term_start",
    ):
        assert not secretbox.is_secret_key(key), key


def test_self_check_reports_the_active_key(vault):
    probe = secretbox.self_check(get_settings())

    assert probe["ok"] is True
    assert probe["key_id"] == vault
