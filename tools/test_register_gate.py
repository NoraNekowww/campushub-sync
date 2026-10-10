"""End-to-end test of the sign-up gate (captcha replacing the invite code).

Run on the server:  venv/bin/python tools/test_register_gate.py
(ADMIN_TOKEN comes from the environment; the probe account is removed again.)
"""

import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010/api"
ADMIN = os.environ.get("ADMIN_TOKEN", "").strip()
PROBE = "zz_register_gate_probe"
PASSWORD = "Probe-Passw0rd-2026"
DB = os.environ.get("CAMPUSHUB_DB", "/var/www/schedule/data/campushub.db")


def call(path, payload=None, method=None, admin=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if admin:
        req.add_header("X-Admin-Token", ADMIN)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except ValueError:
            pass
        return error.code, body


def mask(payload):
    """Never echo the invite code (or any token) to the terminal."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    for field in ("invite_code", "token", "captcha_token"):
        if out.get(field):
            out[field] = f"<{len(str(out[field]))} chars>"
    return out


def settings_of(payload):
    """PUT /auth/registration answers ``{ok, settings}``; GET answers flat."""
    if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
        return payload["settings"]
    return payload or {}


def solve(svg):
    return "".join(re.findall(r">([A-Z2-9])</text>", svg))


def main():
    assert ADMIN, "ADMIN_TOKEN missing from the environment"
    failures = []

    def check(label, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {label}{(' — ' + str(detail)) if detail else ''}")
        if not ok:
            failures.append(label)

    status, gate = call("/auth/registration", admin=True)
    print("admin GET /auth/registration:", status, mask(gate))
    check("管理员能读注册设置", status == 200)

    status, _ = call("/auth/registration")
    check("非管理员读注册设置被拒", status == 403, status)

    # The captcha replaces the invite code: registration stays open through it.
    status, gate = call("/auth/registration", {"invite_required": False}, method="PUT", admin=True)
    print("PUT invite_required=false:", status, mask(gate))
    check("能关掉邀请码", status == 200 and settings_of(gate).get("invite_required") is False, mask(gate))

    status, session = call("/auth/session")
    accounts = (session or {}).get("accounts", {}) if isinstance(session, dict) else {}
    check("注册开放", accounts.get("registration_open") is True, accounts.get("registration_open"))
    check("验证码成为门槛", accounts.get("captcha_required") is True)

    # no captcha at all → rejected
    status, body = call(
        "/auth/register",
        {"username": PROBE, "password": PASSWORD, "invite_code": None},
        method="POST",
    )
    check("无验证码不能注册", status in (400, 403), f"{status} {body}")

    # wrong answer → rejected, with an honest reason
    status, challenge = call("/auth/captcha")
    status, body = call(
        "/auth/register",
        {
            "username": PROBE,
            "password": PASSWORD,
            "captcha_token": challenge.get("token"),
            "captcha_answer": "ZZZZ",
        },
        method="POST",
    )
    check("答错验证码不能注册", status in (400, 403) and "验证码" in json.dumps(body, ensure_ascii=False), f"{status} {body}")

    # right answer → account created, then cleaned up
    status, challenge = call("/auth/captcha")
    answer = solve(challenge.get("svg", ""))
    print("captcha answer decoded from the SVG:", "<%d chars>" % len(answer))
    status, body = call(
        "/auth/register",
        {
            "username": PROBE,
            "password": PASSWORD,
            "display_name": "gate probe",
            "captcha_token": challenge.get("token"),
            "captcha_answer": answer,
        },
        method="POST",
    )
    check("答对验证码可注册", status == 201, f"{status} {body}")

    # same challenge replayed → refused (single use window is bound to the token)
    status, body = call(
        "/auth/register",
        {
            "username": PROBE + "_2",
            "password": PASSWORD,
            "captcha_token": challenge.get("token"),
            "captcha_answer": answer,
        },
        method="POST",
    )
    check("同一验证码不能重复用", status in (400, 403), f"{status} {body}")

    # invite code path still works when switched back on
    status, gate = call("/auth/registration", {"invite_required": True}, method="PUT", admin=True)
    status, body = call(
        "/auth/register",
        {"username": PROBE + "_3", "password": PASSWORD, "invite_code": "definitely-wrong",
         "captcha_token": None, "captcha_answer": None},
        method="POST",
    )
    check("开着邀请码时错码被拒", status in (400, 403), f"{status} {body}")
    status, gate = call("/auth/registration", {"invite_required": False}, method="PUT", admin=True)

    removed = 0
    if os.path.exists(DB):
        connection = sqlite3.connect(DB, timeout=15)
        try:
            cursor = connection.execute(
                "DELETE FROM users WHERE username LIKE ?", (PROBE + "%",)
            )
            removed = cursor.rowcount
            connection.commit()
        finally:
            connection.close()
    print(f"cleanup: removed {removed} probe account(s)")

    print()
    print("FAILURES:", failures if failures else "none")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
