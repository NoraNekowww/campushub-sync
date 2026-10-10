#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe the WePeiYang open-platform API. Pure stdlib, ASCII-only source.

Usage: python probe_twt.py [label]
Prints one line per probe: label | http status | server header | first bytes of body.
"""
import hashlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP_KEY = "9GTdynvrCm1EKKFfVmTC"
APP_SECRET = "1aVhfAYBFUfqrdlcT621d9d6OzahMI"
BASE = "https://open.twt.edu.cn/api/"
UA = "WePeiYang/3.0.0 (Xiaomi MI 8; Android 29)"
TAG = sys.argv[1] if len(sys.argv) > 1 else "probe"


def signed(params):
    t = str(int(time.time() * 1000))
    p = dict(params)
    p["t"] = t
    raw = APP_KEY + "".join(k + p[k] for k in sorted(p)) + APP_SECRET
    p["sign"] = hashlib.sha1(raw.encode()).hexdigest().upper()
    p["app_key"] = APP_KEY
    return p


def call(path, params=None, token=None, ua=UA, label=""):
    url = BASE + path
    if params is not None:
        url += "?" + urllib.parse.urlencode(signed(params))
    hdrs = {"User-Agent": ua} if ua else {}
    if token is not None:
        hdrs["Authorization"] = "Bearer{%s}" % token
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
            print("%-9s | %-10s | %-14s | %s" % (TAG, label, r.status, r.headers.get("server", "-")), "|", body[:180].replace("\n", " "))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print("%-9s | %-10s | %-14s | %s" % (TAG, label, e.code, e.headers.get("server", "-") if e.headers else "-"), "|", body[:180].replace("\n", " "))
    except Exception as e:  # noqa: BLE001
        print("%-9s | %-10s | ERR %s: %s" % (TAG, label, type(e).__name__, e))


if __name__ == "__main__":
    call("v1/zzz-does-not-exist", {}, label="404probe")
    call("v1/classtable", None, token="dummy", label="nosign")
    call("v1/classtable", {}, token="dummy", label="signed")
    call("v1/auth/token/get", {"twtuname": "0", "twtpasswd": "0"}, ua=None, label="login-curlUA")
    call("v1/auth/token/get", {"twtuname": "0", "twtpasswd": "0"}, label="login-appUA")
    # deliberately wrong signature to see whether the signature is even checked
    try:
        url = BASE + "v1/classtable?t=1&sign=AAAA&app_key=" + APP_KEY
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Authorization": "Bearer{dummy}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            print("%-9s | %-10s | %-14s | %s" % (TAG, "badsign", r.status, r.headers.get("server", "-")), "|", r.read().decode("utf-8", "replace")[:180].replace("\n", " "))
    except urllib.error.HTTPError as e:
        print("%-9s | %-10s | %-14s | %s" % (TAG, "badsign", e.code, "-"), "|", e.read().decode("utf-8", "replace")[:180].replace("\n", " "))
    except Exception as e:  # noqa: BLE001
        print("%-9s | %-10s | ERR %s: %s" % (TAG, "badsign", type(e).__name__, e))
