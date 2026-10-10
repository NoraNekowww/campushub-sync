"""End-to-end smoke test for a running CampusHub Sync instance.

Usage (from the repo root):

    ./.venv/Scripts/python.exe tools/smoke_test.py \
        --base http://127.0.0.1:8099 \
        --admin-token "$ADMIN_TOKEN" \
        --subscribe-token "$SUBSCRIBE_TOKEN"

Every check prints PASS/FAIL and the script exits non-zero when anything fails,
so it is safe to use as a post-deploy gate:

    ./tools/smoke_test.py --base https://schedule.nzlab.online ...
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta

import httpx

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((ok, label))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="CampusHub Sync smoke test")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-token", default="")
    parser.add_argument("--subscribe-token", default="")
    parser.add_argument("--skip-write", action="store_true", help="read-only checks only")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    admin = {"X-Admin-Token": args.admin_token} if args.admin_token else {}
    readonly = {"X-Subscribe-Token": args.subscribe_token} if args.subscribe_token else {}
    today = date.today()
    window = {
        "start_date": (today - timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=30)).isoformat(),
        "limit": 500,
    }

    with httpx.Client(base_url=base, timeout=30.0, follow_redirects=True) as client:
        # ------------------------------------------------------------- health
        response = client.get("/api/health")
        payload = response.json() if response.status_code == 200 else {}
        check(
            response.status_code == 200 and payload.get("ok") is True,
            "GET /api/health",
            f"{response.status_code} {payload.get('version', '')}".strip(),
        )

        # --------------------------------------------------------- app shell
        shell = client.get("/")
        check(
            shell.status_code == 200 and "<div id=\"app\">" in shell.text,
            "GET / serves the built PWA",
            f"{shell.status_code} {len(shell.text)} bytes",
        )
        for asset, needle in (
            ("/manifest.webmanifest", "standalone"),
            ("/sw.js", "caches"),
            ("/icons/icon-192.png", None),
            ("/icons/icon-512.png", None),
        ):
            response = client.get(asset)
            ok = response.status_code == 200 and (needle is None or needle in response.text)
            check(ok, f"GET {asset}", f"{response.status_code} {len(response.content)} bytes")

        # ----------------------------------------------------- access control
        anon = client.get("/api/events", params=window)
        check(
            anon.status_code == 200 or anon.status_code == 401,
            "GET /api/events answers (200 with token / 401 without)",
            f"{anon.status_code}",
        )

        events = client.get("/api/events", params=window, headers=admin)
        check(events.status_code == 200, "GET /api/events with the admin token", f"{events.status_code}")
        items: list[dict] = []
        if events.status_code == 200:
            body = events.json()
            items = body.get("items", [])
            check(
                bool(items),
                "agenda is not empty",
                f"{body.get('total', 0)} events in window",
            )
            classes = [i for i in items if not i.get("is_deadline")]
            deadlines = [i for i in items if i.get("is_deadline")]
            check(bool(classes) and bool(deadlines), "both classes and deadlines present",
                  f"{len(classes)} classes / {len(deadlines)} deadlines")
            check(
                all(
                    re.search(r"(Z|[+-]\d{2}:\d{2})$", i.get("start_time", ""))
                    for i in items[:20]
                ),
                "timestamps are timezone-aware (offset or Z)",
                items[0]["start_time"] if items else "",
            )
            first = items[0]
            detail = client.get(f"/api/events/{first['id']}", headers=admin)
            check(detail.status_code == 200, "GET /api/events/{id}", f"{detail.status_code}")

        if args.subscribe_token:
            shared = client.get("/api/events", params=window, headers=readonly)
            check(
                shared.status_code == 200,
                "read-only access via the subscribe token",
                f"{shared.status_code}",
            )
            magic = client.get("/api/events", params={**window, "token": args.subscribe_token})
            check(magic.status_code == 200, "read-only access via ?token= link", f"{magic.status_code}")

        # ------------------------------------------------------------ status
        status = client.get("/api/status", headers=admin)
        check(status.status_code == 200, "GET /api/status", f"{status.status_code}")
        if status.status_code == 200:
            body = status.json()
            check(body.get("ok") is True, "database reports ok")
            check(
                body.get("scheduler", {}).get("running") is True,
                "scheduler is running",
                f"every {body.get('scheduler', {}).get('interval_minutes')} min",
            )
            connectors = body.get("connectors", [])
            check(bool(connectors), "connector status reported", f"{[c['name'] for c in connectors]}")
            check(
                all(c.get("ok") for c in connectors),
                "all connectors healthy",
                ", ".join(f"{c['name']}={c.get('ok')}" for c in connectors),
            )
            counts = body.get("counts") or {}
            if counts:
                check(counts.get("total", 0) > 0, "status counts", str(counts))

        config = client.get("/api/config", headers=admin)
        check(config.status_code == 200, "GET /api/config", f"{config.status_code}")
        if config.status_code == 200:
            cfg = config.json()
            check(
                "subscribe" in cfg and "url" in cfg.get("subscribe", {}),
                "subscription URL exposed for the settings page",
            )

        # ------------------------------------------------------- ical feed
        if args.subscribe_token:
            feed = client.get(
                "/api/subscribe/calendar.ics", params={"token": args.subscribe_token}
            )
            text = feed.text if feed.status_code == 200 else ""
            check(
                feed.status_code == 200 and text.startswith("BEGIN:VCALENDAR"),
                "GET /api/subscribe/calendar.ics",
                f"{feed.status_code} {len(text)} bytes",
            )
            check("BEGIN:VEVENT" in text, "feed contains VEVENTs")
            check("BEGIN:VALARM" in text, "feed contains VALARM reminders")
            check("TRIGGER" in text, "alarms carry a TRIGGER")
            check("CATEGORIES:DDL" in text or "CATEGORIES:课程" in text,
                  "events are categorised (DDL / 课程)")
            etag = feed.headers.get("etag")
            if etag:
                again = client.get(
                    "/api/subscribe/calendar.ics",
                    params={"token": args.subscribe_token},
                    headers={"If-None-Match": etag},
                )
                check(again.status_code == 304, "ETag revalidation returns 304", f"{again.status_code}")
            bad = client.get("/api/subscribe/calendar.ics", params={"token": "wrong-token"})
            check(bad.status_code in (401, 403), "feed rejects a wrong token", f"{bad.status_code}")

        # ------------------------------------------------------ manual sync
        if not args.skip_write and args.admin_token:
            sync = client.post("/api/sync", headers=admin)
            check(sync.status_code == 200, "POST /api/sync", f"{sync.status_code}")
            if sync.status_code == 200:
                body = sync.json()
                check(body.get("ok") is True, "sync reported ok",
                      f"fetched={body.get('fetched')} created={body.get('created')} "
                      f"updated={body.get('updated')} pruned={body.get('pruned')}")

            # status flag round-trip through PATCH
            event_items = client.get("/api/events", params=window, headers=admin).json().get("items", [])
            target = next((i for i in event_items if i.get("is_deadline")), None)
            if target:
                patched = client.patch(
                    f"/api/events/{target['id']}",
                    headers=admin,
                    json={"status": "completed" if target.get("status") != "completed" else "pending"},
                )
                check(patched.status_code == 200, "PATCH /api/events/{id} toggles status",
                      f"{patched.status_code} -> {patched.json().get('status') if patched.status_code == 200 else ''}")
                if patched.status_code == 200:
                    revert = client.patch(
                        f"/api/events/{target['id']}", headers=admin, json={"status": target["status"]}
                    )
                    check(revert.status_code == 200, "status restored after the test")
                if args.subscribe_token:
                    denied = client.patch(
                        f"/api/events/{target['id']}", headers=readonly, json={"status": "pending"}
                    )
                    check(denied.status_code in (401, 403),
                          "read-only token cannot mutate", f"{denied.status_code}")

    failed = [label for ok, label in RESULTS if not ok]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("failed:")
        for label in failed:
            print(f"  - {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
