"""Probe Microsoft Graph To Do endpoints using the token stored in the app KV store.

Server-side only. Prints status codes and short bodies — never tokens/secrets.

Run:  cd /var/www/schedule/backend && /var/www/schedule/venv/bin/python /tmp/graph_probe.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "/var/www/schedule/backend")

from app.db import KVStore  # noqa: E402

BASE = "https://graph.microsoft.com/v1.0"
kv = KVStore()
tokens = kv.get("ms.tokens")
if not isinstance(tokens, dict):
    print("no ms.tokens in KV store")
    raise SystemExit(1)

print("token keys:", sorted(tokens.keys()))
print("account:", kv.get("ms.account"))
at = tokens.get("access_token") or ""
print("access_token length:", len(at))

auth_headers = {"Authorization": f"Bearer {at}", "Accept": "application/json"}


def call(url: str, label: str) -> int:
    req = urllib.request.Request(url, headers=auth_headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(f"[{label}] {resp.status} len={len(body)} :: {body[:400]}")
            return resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(f"[{label}] {exc.code} :: {body[:400]}")
        return exc.code
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] ERR {type(exc).__name__}: {exc}")
        return -1


status = call(f"{BASE}/me", "me")
if status == 401:
    print("--- access token rejected, trying refresh via msal ---")
    try:
        import msal

        from app.config import get_settings

        settings = get_settings()
        app = msal.PublicClientApplication(settings.ms_client_id, authority=f"{settings.ms_authority_host}/{settings.ms_tenant}")
        result = app.acquire_token_by_refresh_token(tokens.get("refresh_token"), scopes=settings.scope_list)
        if "access_token" in result:
            print("refresh OK, scopes:", result.get("scope"))
            at = result["access_token"]
            auth_headers["Authorization"] = f"Bearer {at}"
        else:
            print("refresh failed:", json.dumps({k: v for k, v in result.items() if k != "access_token"}, ensure_ascii=False)[:400])
    except Exception as exc:  # noqa: BLE001
        print("refresh error:", type(exc).__name__, exc)

call(f"{BASE}/me", "me(retry)")

# --- which lists URL shape does Graph accept? ---
call(f"{BASE}/me/todo/lists", "A-no-params")
call(f"{BASE}/me/todo/lists?$top=100", "B-raw-$top")
call(f"{BASE}/me/todo/lists?$select=id,displayName", "C-raw-$select")
call(f"{BASE}/me/todo/lists?$top=100&$select=id,displayName", "D-raw-$top+$select")
call(
    f"{BASE}/me/todo/lists?"
    + urllib.parse.urlencode({"$top": 100, "$select": "id,displayName,wellknownListName"}),
    "E-encoded-$top+$select3",
)
call(f"{BASE}/me/todo/lists?$select=id,displayName,wellknownListName", "F-raw-$select3")
call(f"{BASE}/me/todo/lists?%24top=100&%24select=id%2CdisplayName", "G-manual-%24")
