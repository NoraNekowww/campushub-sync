#!/usr/bin/env python3
"""Local probe for the Weibeiyang class-table backend.

Why this exists
---------------
The Weibeiyang (WeiBeiYang) Android/iOS app does not read the timetable from
open.twt.edu.cn at all. It hands the *office-network* credentials
(classes.tju.edu.cn, i.e. EAMS / CAS) to twt's own backend:

    POST https://learning.twt.edu.cn/get_classes
         form-data: username=<student id>, passwd=<office-network password>
      -> {"code":200,"data":{"courses":{"major":[...],"minor":[...]},
                             "exams":[...],"gpa":{...}}}

That endpoint is reachable from anywhere (verified from a Los Angeles VPS with
throw-away credentials), so the timetable can be fetched server-side without a
campus network, a browser, or a VPN.

This script is a throw-away verification harness: it serves a form on
http://127.0.0.1:8099, forwards the credentials to the endpoint server-side
(so the browser never hits a CORS wall) and writes the raw answer to
jw_probe_out.json next to this file.

Standard library only. Run:  python tools/jw_probe.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
OUT = HERE / "jw_probe_out.json"
TARGET = "https://learning.twt.edu.cn/get_classes"
PORT = 8099
BOUNDARY_PREFIX = "----campushubprobe"

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>CampusHub Sync - JW probe</title>
<style>
 body{font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;padding:28px;
      background:#0f172a;color:#e2e8f0}
 h1{font-size:17px;margin:0 0 4px}
 p.hint{color:#94a3b8;margin:0 0 18px;font-size:13px}
 label{display:block;margin:12px 0 4px;font-size:13px;color:#cbd5e1}
 input{width:320px;padding:8px 10px;border-radius:8px;border:1px solid #334155;
       background:#1e293b;color:#e2e8f0;font-size:14px}
 button{margin-top:18px;padding:9px 18px;border:0;border-radius:8px;background:#6366f1;
        color:#fff;font-size:14px;cursor:pointer}
 pre{background:#020617;border:1px solid #1e293b;border-radius:8px;padding:14px;
     max-height:460px;overflow:auto;font-size:12px;white-space:pre-wrap;word-break:break-all}
 code{background:#1e293b;padding:1px 5px;border-radius:5px;font-size:12px}
</style></head><body>
<h1>CampusHub Sync &middot; 教务课表接口探测</h1>
<p class="hint">填的是 <code>classes.tju.edu.cn</code> 的那套账号密码（和微北洋可能不一样）。
只写进本机内存，并把接口原始返回存到 <code>tools/jw_probe_out.json</code>。</p>
%s
</body></html>
"""

FORM = """<form method="post" action="/go">
<label>教务账号 / 学号</label>
<input name="username" autocomplete="off" placeholder="30212xxxxx" required>
<label>教务密码（办公网密码）</label>
<input name="password" type="password" autocomplete="off" required>
<button type="submit">提交并抓取课表</button>
</form>"""


def build_multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = BOUNDARY_PREFIX + uuid.uuid4().hex
    out: list[bytes] = []
    for name, value in fields.items():
        out.append(("--%s\r\n" % boundary).encode())
        out.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
        out.append(value.encode("utf-8"))
        out.append(b"\r\n")
    out.append(("--%s--\r\n" % boundary).encode())
    return b"".join(out), boundary


def call_backend(username: str, password: str) -> tuple[int, str]:
    body, boundary = build_multipart({"username": username, "passwd": password})
    req = urllib.request.Request(
        TARGET,
        data=body,
        method="POST",
        headers={
            "Content-Type": "multipart/form-data; boundary=%s" % boundary,
            "User-Agent": "WePeiYang/Flutter",
            "Accept": "application/json, text/plain, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - report anything to the page
        return 0, "request failed: %r" % (exc,)


def summarise(raw: str) -> str:
    try:
        data = json.loads(raw)
    except ValueError:
        return "<pre>%s</pre>" % (raw[:4000].replace("&", "&amp;").replace("<", "&lt;"),)
    pretty = json.dumps(data, ensure_ascii=False, indent=2)
    head = ""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        payload = data["data"]
        courses = payload.get("courses") or {}
        head = ("<p>courses: major=%s minor=%s &middot; exams=%s &middot; gpa=%s</p>" % (
            len(courses.get("major") or []),
            len(courses.get("minor") or []),
            len(payload.get("exams") or []),
            "yes" if payload.get("gpa") else "no",
        ))
    return head + "<pre>%s</pre>" % pretty.replace("&", "&amp;").replace("<", "&lt;")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def _send(self, html: str, code: int = 200) -> None:
        payload = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self._send(PAGE % FORM)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        username = (fields.get("username") or [""])[0].strip()
        password = (fields.get("password") or [""])[0]
        if not username or not password:
            self._send(PAGE % '<p style="color:#f87171">账号和密码都要填。</p>' + FORM, 400)
            return
        status, raw = call_backend(username, password)
        OUT.write_text(
            json.dumps({"upstream_status": status, "raw": raw}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        note = ("<p>upstream HTTP <b>%s</b> &middot; 原始返回已存到 "
                "<code>%s</code></p>" % (status, OUT.name))
        back = ('<p><a style="color:#818cf8" href="/">再来一次</a></p>')
        self._send(PAGE % (note + summarise(raw) + back))

    def log_message(self, fmt: str, *args: object) -> None:
        print("[jw_probe] " + fmt % args, flush=True)


if __name__ == "__main__":
    print("serving http://127.0.0.1:%d/  ->  %s" % (PORT, TARGET), flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
