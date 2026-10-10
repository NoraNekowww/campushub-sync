"""Probe: does per-account isolation actually hold? (run on the server)

1. make a second account (student) directly in the DB if missing
2. log in over HTTP to get a session cookie
3. GET /api/events + /api/status  -> must be *empty*, not the owner's 136 rows
4. POST /api/events              -> a student must be able to create their own
5. GET /api/config               -> 200, and connectors show as unconnected
"""

from __future__ import annotations

import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/var/www/schedule/backend")

# 会话 cookie 是 httpOnly + Secure（浏览器走 https ✓），明文 http 不会带回来，
# 所以探针走公网 https（nginx /schedule/api/ -> app /api/）。
BASE = "https://nzlab.online/schedule"
USERNAME = "stu_probe"
PASSWORD = "Probe!2026x"

from app import accounts  # noqa: E402
from app.db import session_scope  # noqa: E402


def make_user() -> int:
    with session_scope() as session:
        user = accounts.get_by_username(session, USERNAME)
        if user is None:
            try:
                user = accounts.create_user(session, USERNAME, PASSWORD)
            except TypeError as exc:  # learn the real signature instead of guessing
                print("create_user signature mismatch:", exc)
                raise SystemExit(2)
        return user.id


AUTH: dict[str, str] = {}


def main() -> int:
    uid = make_user()
    print(f"probe account: #{uid} {USERNAME}")

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"}
        headers.update(AUTH)
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            resp = opener.open(req, timeout=25)
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:300].decode(errors="replace")

    status, body = call("POST", "/api/auth/login", {"username": USERNAME, "password": PASSWORD})
    print(f"login: HTTP {status} keys={sorted(body) if isinstance(body, dict) else body}")
    if isinstance(body, dict):
        token = body.get("token") or body.get("access_token") or body.get("session")
        if token:
            # 会话 cookie 带 Secure，明文 http 不会发回来；有 token 就用 Bearer。
            AUTH["Authorization"] = f"Bearer {token}"
        else:
            # 浏览器路径：httpOnly 会话 cookie，https 下 jar 会自动带上。
            print("session cookies:", [c.name for c in jar])

    status, body = call("GET", "/api/events?limit=5")
    total = body.get("total") if isinstance(body, dict) else body
    print(f"events: HTTP {status} total={total}   <-- must be 0, not 136")

    status, body = call("GET", "/api/status")
    counts = body.get("counts") if isinstance(body, dict) else body
    print(f"status: HTTP {status} counts={counts}")

    status, body = call("GET", "/api/config")
    conn = body.get("connectors") if isinstance(body, dict) else body
    print(f"config: HTTP {status} connectors={conn}")
    if isinstance(body, dict):
        print("  tju:", json.dumps(body.get("tju_schedule") or {}, ensure_ascii=False)[:120])
        print("  ms :", json.dumps(body.get("microsoft_todo") or {}, ensure_ascii=False)[:120])

    status, body = call("POST", "/api/events", {
        "title": "冒烟：我的自定义日程", "date": "2026-10-20",
        "start_time": "2026-10-20T19:00:00", "end_time": "2026-10-20T20:00:00",
        "location": "", "description": "probe",
    })
    print(f"create: HTTP {status} id={(body or {}).get('id') if isinstance(body, dict) else body}")
    if isinstance(body, dict) and body.get("id"):
        print("delete:", call("DELETE", f"/api/events/{body['id']}")[0])

    # and the probe must NOT be able to touch the owner's rows
    status, _ = call("DELETE", "/api/events/does-not-exist")
    print(f"delete foreign/absent: HTTP {status}  (404 expected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
