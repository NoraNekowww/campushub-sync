"""Systemic access-control check.

Instead of trusting a manual audit, this walks the *live* OpenAPI schema and
probes every mutating operation as an anonymous caller. A guarded endpoint
answers 401/403 (or 404/405 before touching anything); anything else —
200, 201, 422, 500 — means the route ran without credentials.

The public account endpoints are the only intentional exceptions.
"""

from __future__ import annotations

import pytest

PUBLIC_MUTATIONS = {
    ("post", "/api/auth/register"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/logout"),
}

MUTATING = {"post", "put", "patch", "delete"}


def mutating_operations(client):
    schema = client.app.openapi()
    for path, operations in schema["paths"].items():
        for method, spec in operations.items():
            if method.lower() in MUTATING:
                yield method.lower(), path, spec.get("summary") or ""


def probe(client, method, path):
    """Call the route anonymously, with a plausible path-id substituted in."""
    target = path.replace("{event_id}", "no-such-event").replace("{user_id}", "99999")
    target = target.replace("{task_id}", "nope").replace("{note_id}", "nope")
    call = getattr(client, method)
    if method == "delete":
        return call(target)
    return call(target, json={})


def test_every_mutating_route_is_guarded(client):
    offenders = []
    checked = 0
    with client as anon:
        for method, path, summary in mutating_operations(anon):
            if (method, path) in PUBLIC_MUTATIONS:
                continue
            checked += 1
            response = probe(anon, method, path)
            if response.status_code not in (401, 403, 404, 405):
                offenders.append(f"{method.upper()} {path} -> {response.status_code} ({summary})")

    assert checked >= 6, f"schema only exposed {checked} mutating routes — probe is not working"
    assert not offenders, "unauthenticated mutations reached the app:\n  " + "\n  ".join(offenders)


def test_account_routes_need_the_right_role(client):
    with client as anon:
        assert anon.get("/api/auth/users").status_code == 401
        assert anon.patch("/api/auth/users/1", json={"is_active": False}).status_code == 401
        assert anon.post("/api/auth/password", json={}).status_code == 401
        assert anon.get("/api/auth/me").status_code == 401

        # reads stay closed to anonymous callers as well
        assert anon.get("/api/events").status_code == 401
        assert anon.post("/api/sync").status_code == 401


def test_admin_token_still_works_without_accounts(client, admin_headers):
    with client as client:
        assert client.post("/api/sync", headers=admin_headers).status_code == 200
        assert client.get("/api/status", headers=admin_headers).status_code == 200


def test_health_is_public(client):
    with client as anon:
        assert anon.get("/api/health").status_code == 200
