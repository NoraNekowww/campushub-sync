"""CAS 直连链路的排查脚本：逐步打印每一跳的真实响应。

用法（在服务器 backend 目录下）::

    /var/www/schedule/venv/bin/python ../../tools/jw_cas_probe.py [学号] [密码] [--deep]

``--deep`` 会继续走教务 eams 的学期/ids/课表三跳并打印响应头部。
不传凭据时用一对假凭据，只验证"链路能走通、报错说得清"。
"""

from __future__ import annotations

import asyncio
import re
import sys

sys.path.insert(0, ".")

from app.connectors import tju_cas as C  # noqa: E402
from app.connectors.jw_eams import JwEamsError  # noqa: E402
from app.connectors.tju_des import str_enc  # noqa: E402

KEYWORDS = ("错误", "验证码", "密码", "帐号", "账号", "用户名", "不存在", "锁定")


def grep_snippets(text: str, width: int = 130, limit: int = 6) -> None:
    """把失败页面里提到错误原因的地方挖出来（CAS 的文案各处不一样）。"""
    seen = 0
    for keyword in KEYWORDS:
        for match in re.finditer(keyword, text):
            if seen >= limit:
                return
            start = max(0, match.start() - width)
            snippet = " ".join(text[start:match.end() + width].split())
            print("   [%s] %s" % (keyword, snippet))
            seen += 1
            break
    if not seen:
        print("   （页面上找不到错误关键词）")

REMINDS = "remind_strong_pwd = " + chr(39) + "true" + chr(39)


def head(text: str, size: int = 400) -> str:
    return " ".join(text[:size].split())


async def main() -> None:
    args = [item for item in sys.argv[1:] if not item.startswith("--")]
    deep = "--deep" in sys.argv
    username = args[0] if args else "2026000000"
    password = args[1] if len(args) > 1 else "not-the-real-password"

    client = C._client(25)
    try:
        execution, lt = await C._open_login(client)
        print("1) CAS 登录页     : execution=%s… lt=%s…" % (execution[:10], lt[:10]))

        image = await C._captcha_image(client)
        print("2) 验证码图片     : %d bytes" % len(image))

        code = await C.ocr_captcha(image)
        print("3) OCR 识别       : %r" % code)

        rsa = str_enc(username + password + lt, "1", "2", "3")
        print("4) 本地 DES 密文  : %s… (%d hex)" % (rsa[:10], len(rsa)))

        response = await client.post(
            C.CAS_BASE + "/login",
            data={
                "code": code,
                "ul": str(len(username)),
                "pl": str(len(password)),
                "lt": lt,
                "rsa": rsa,
                "execution": execution,
                "_eventId": "submit",
            },
        )
        cookies = [cookie.name for cookie in client.cookies.jar]
        print("5) 登录 POST      : HTTP %s, %d bytes" % (response.status_code, len(response.text)))
        print("   cookies        : %s" % cookies)
        print("   成功标记       : %s" % (REMINDS in response.text))
        print("   CASTGC         : %s" % ("CASTGC" in cookies))
        if "CASTGC" not in cookies:
            print("   错误文案       : %r" % C._error_text(response.text)[:200])
            grep_snippets(response.text)
            index = response.text.find("remind_strong_pwd")
            if index >= 0:
                print("   片段           : %s" % head(response.text[max(0, index - 240):index + 120]))
            return

        if not deep:
            print("   -> 登录成功，加 --deep 继续走教务三跳")
            return

        calendar_raw, semesters = await C._semester_calendar(client)
        print("6) 学期日历       : %d 字节, 解析出 %d 个学期" % (len(calendar_raw), len(semesters)))
        print("   学期           : %s" % semesters)
        print("   响应头部       : %s" % head(calendar_raw, 500))
        if not semesters:
            return
        semester = C.pick_semester(semesters)
        print("   当前学期       : %s" % semester)

        for project_id in (1, 22):
            inner = await client.get(
                "%s/courseTableForStd!innerIndex.action?projectId=%d" % (C.EAMS_BASE, project_id)
            )
            ids_match = C._IDS_RE.search(inner.text)
            print("7) innerIndex p%d : HTTP %s, %d 字节, ids=%s" % (
                project_id, inner.status_code, len(inner.text),
                (ids_match.group(1)[:60] + "…") if ids_match else "无",
            ))
            if not ids_match:
                print("   响应头部       : %s" % head(inner.text, 300))
                continue
            html = await C._course_table_html(client, semester_id=semester["id"], project_id=project_id)
            rows = C._parse_course_html(html)
            print("8) courseTable p%d: %d 字节, 解析出 %d 门课" % (project_id, len(html), len(rows)))
            for row in rows[:5]:
                print("   - %s | 周次=%s | %s | %s" % (
                    row["name"], row["weeks"], row["teacherList"], row["arrangeList"][:2],
                ))
            if rows:
                print("   表格头部       : %s" % head(html, 600))
                break
    except JwEamsError as exc:
        print("!! JwEamsError kind=%s" % exc.kind)
        print("   msg   : %s" % exc)
        print("   detail: %s" % (exc.detail or "")[:400])
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
