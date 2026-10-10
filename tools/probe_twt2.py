#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe WePeiYang open-platform API from the LOCAL network, bypassing proxies.

Prints DNS resolution, response headers, and body for each probe.
"""
import hashlib
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP_KEY = "9GTdynvrCm1EKKFfVmTC"
APP_SECRET = "1aVhfAYBFUfqrdlcT621d9d6OzahMI"
HOST = "open.twt.edu.cn"
BASE = "https://%s/api/" % HOST
UA = "WePeiYang/3.0.0 (Xiaomi MI 8; Android 29)"

print("proxy env:", {k: v for k, v in os.environ.items() if "proxy" in k.lower()} or "none")
try:
    print("DNS %s -> %s" % (HOST, socket.gethostbyname(HOST)))
except Exception as e:  # noqa: BLE001
    print("DNS failed:", e)
try:
    s = socket.create_connection((HOST, 443), timeout=10)
    print("peer:", s.getpeername())
    s.close()
except Exception as e:  # noqa: BLE001
    print("connect failed:", e)

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def signed(params):
    t = str(int(time.time() * 1000))
    p = dict(params)
    p["t"] = t
    raw = APP_KEY + "".join(k + p[k] for k in sorted(p)) + APP_SECRET
    p["sign"] = hashlib.sha1(raw.encode()).hexdigest().upper()
    p["app_key"] = APP_KEY
    return p


def show(label, req, method="GET"):
    print("\n--- %s ---" % label)
    try:
        with OPENER.open(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
            print("status:", r.status)
            for k, v in r.headers.items():
                print("  %s: %s" % (k, v))
            print("body[:600]:", body[:600].replace("\n", " "))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print("status:", e.code)
        for k, v in (e.headers or {}).items():
            print("  %s: %s" % (k, v))
        print("body[:600]:", body[:600].replace("\n", " "))
    except Exception as e:  # noqa: BLE001
        print("ERR", type(e).__name__, e)


q = urllib.parse.urlencode(signed({}))
show("A) signed /v1/classtable (dummy token)",
     urllib.request.Request(BASE + "v1/classtable?" + q,
                            headers={"User-Agent": UA, "Authorization": "Bearer{dummy}"}))
show("B) OPTIONS preflight with Origin",
     urllib.request.Request(BASE + "v1/classtable",
                            headers={"User-Agent": UA, "Origin": "https://nzlab.online",
                                     "Access-Control-Request-Method": "GET",
                                     "Access-Control-Request-Headers": "authorization"}), "OPTIONS")
show("C) signed login with dummy creds",
     urllib.request.Request(BASE + "v1/auth/token/get?" + urllib.parse.urlencode(signed({"twtuname": "0", "twtpasswd": "0"})),
                            headers={"User-Agent": UA, "Origin": "https://nzlab.online"}))
show("D) root host",
     urllib.request.Request("https://%s/" % HOST, headers={"User-Agent": UA}))
