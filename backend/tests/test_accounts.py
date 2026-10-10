"""Account / session tests: registration gate, cookie reads, revocation."""

from __future__ import annotations

import pytest

INVITE = "let-me-in-2026"


@pytest.fixture()
def accounts_env(monkeypatch):
    """Turn self-service accounts on with an invite code."""
    monkeypatch.setenv("ENABLE_ACCOUNTS", "true")
    monkeypatch.setenv("REGISTRATION_INVITE_CODE", INVITE)
    monkeypatch.setenv("ALLOW_OPEN_REGISTRATION", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    yield INVITE
    get_settings.cache_clear()


def make_client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


def register(client, username="alice", password="correct-horse", **extra):
    body = {"username": username, "password": password, **extra}
    return client.post("/api/auth/register", json=body)


# --------------------------------------------------------------- registration
def test_registration_needs_the_invite_code(accounts_env):
    with make_client() as client:
        assert register(client).status_code == 403
        assert register(client, invite_code="nope").status_code == 403


def test_first_account_becomes_admin(accounts_env):
    with make_client() as client:
        response = register(client, invite_code=INVITE)
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["user"]["username"] == "alice"
        assert payload["user"]["is_admin"] is True
        assert payload["accounts"]["registration_open"] is True

        second = register(client, username="bob", password="another-good-one", invite_code=INVITE)
        assert second.status_code == 201
        assert second.json()["user"]["is_admin"] is False


def test_username_and_password_rules(accounts_env):
    with make_client() as client:
        assert register(client, username="ab", invite_code=INVITE).status_code == 400
        assert register(client, username="bad name", invite_code=INVITE).status_code == 400
        assert register(client, password="short", invite_code=INVITE).status_code == 400

        assert register(client, invite_code=INVITE).status_code == 201
        assert register(client, invite_code=INVITE).status_code == 409


# -------------------------------------------------------------------- session
def test_cookie_session_unlocks_reads(accounts_env):
    with make_client() as anon:
        assert anon.get("/api/events").status_code == 401

    with make_client() as client:
        register(client, invite_code=INVITE)
        # no shared token anywhere: the cookie alone must authorise reads
        events = client.get("/api/events")
        assert events.status_code == 200, events.text
        assert "items" in events.json()

        me = client.get("/api/auth/session")
        assert me.status_code == 200
        body = me.json()
        assert body["authenticated"] is True
        assert body["user"]["username"] == "alice"


def test_login_rejects_a_bad_password(accounts_env):
    with make_client() as client:
        register(client, invite_code=INVITE)
        client.post("/api/auth/logout")
        assert client.get("/api/events").status_code == 401

        assert client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong-one"}
        ).status_code == 401
        ok = client.post("/api/auth/login", json={"username": "alice", "password": "correct-horse"})
        assert ok.status_code == 200
        assert client.get("/api/events").status_code == 200


def test_logout_clears_the_cookie(accounts_env):
    with make_client() as client:
        register(client, invite_code=INVITE)
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/events").status_code == 401
        assert client.get("/api/auth/session").json()["authenticated"] is False


def test_deactivated_account_loses_access(accounts_env):
    with make_client() as admin:
        register(admin, invite_code=INVITE)
        # second account lives on its own client: two logins must not share a jar
        with make_client() as bob_client:
            assert register(
                bob_client, username="bob", password="another-good-one", invite_code=INVITE
            ).status_code == 201
        users = admin.get("/api/auth/users").json()["items"]
        bob = next(u for u in users if u["username"] == "bob")

        patched = admin.patch(f"/api/auth/users/{bob['id']}", json={"is_active": False})
        assert patched.status_code == 200

        with make_client() as blocker:
            assert blocker.post(
                "/api/auth/login", json={"username": "bob", "password": "another-good-one"}
            ).status_code == 401


def test_only_admins_see_the_member_list(accounts_env):
    with make_client() as admin:
        register(admin, invite_code=INVITE)  # first account → the admin
        with make_client() as bob_client:
            register(bob_client, username="bob", password="another-good-one", invite_code=INVITE)

            assert admin.get("/api/auth/users").status_code == 200
            assert bob_client.get("/api/auth/users").status_code == 403
            # a plain member reads the timeline but cannot mutate it
            assert bob_client.get("/api/events").status_code == 200
            assert bob_client.post("/api/sync").status_code == 401


def test_admin_session_can_write(accounts_env):
    with make_client() as client:
        register(client, invite_code=INVITE)
        assert client.get("/api/config").json()["viewer"]["admin"] is True
        assert client.post("/api/sync").status_code == 200


def test_password_change(accounts_env):
    with make_client() as client:
        register(client, invite_code=INVITE)
        bad = client.post(
            "/api/auth/password",
            json={"old_password": "nope-nope", "new_password": "brand-new-pass"},
        )
        assert bad.status_code == 401
        ok = client.post(
            "/api/auth/password",
            json={"old_password": "correct-horse", "new_password": "brand-new-pass"},
        )
        assert ok.status_code == 200

        client.post("/api/auth/logout")
        assert client.post(
            "/api/auth/login", json={"username": "alice", "password": "correct-horse"}
        ).status_code == 401
        assert client.post(
            "/api/auth/login", json={"username": "alice", "password": "brand-new-pass"}
        ).status_code == 200


def test_open_registration_can_be_enabled(accounts_env, monkeypatch):
    monkeypatch.setenv("ALLOW_OPEN_REGISTRATION", "true")
    monkeypatch.delenv("REGISTRATION_INVITE_CODE", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    with make_client() as client:
        assert client.get("/api/auth/session").json()["accounts"]["registration_open"] is True
        assert register(client, username="carol", password="open-door-policy").status_code == 201


def test_accounts_can_be_disabled(accounts_env, monkeypatch):
    monkeypatch.setenv("ENABLE_ACCOUNTS", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    with make_client() as client:
        body = client.get("/api/auth/session").json()
        assert body["accounts"]["enabled"] is False
        assert client.post(
            "/api/auth/register", json={"username": "dave", "password": "irrelevant-here"}
        ).status_code == 403
