"""天大 CAS 直连抓课表 —— 绕开 learning.twt.edu.cn 的 get_classes。

为什么需要它: ``get_classes`` 目前对**任何**凭据都回
``{"code": 201, "data": "学期解析失败"}``（拿假密码试也一样），说明它挂在登录之前的
"学期解析"步骤，是 TWT 后端自己的问题，我们改不了。

官方客户端 WePeiYang-Flutter (lib/classes/network/classes_service.dart) 里还有另一条
链路 ``ClassesService``: 自己走 CAS 登录 + 直接爬教务 eams。本模块是它的服务端移植，
依赖只有 ssl 出口能到 sso.tju.edu.cn / classes.tju.edu.cn（实测海外 VPS 也能到）。

链路::

    1. GET  {CAS}/login                       -> execution / lt (+ JSESSIONID)
    2. GET  {CAS}/code                        -> 验证码图片
    3. POST https://learning.twt.edu.cn/ocr    -> 验证码文本（只发图片，不发密码）
    4. rsa = tju_des.str_enc(学号 + 密码 + lt, "1", "2", "3")   # 本地 DES，不上传密码
    5. POST {CAS}/login                       -> CASTGC 出现即登录成功
    6. POST {EAMS}/dataQuery.action           -> 学期列表 (semesterCalendar)
    7. GET  {EAMS}/courseTableForStd!innerIndex.action -> ids
    8. POST {EAMS}/courseTableForStd!courseTable.action -> 课表 HTML
    9. 解析 HTML -> 与 get_classes 同形状的 payload，交给 jw_eams.convert_classtable
"""

from __future__ import annotations

import copy
import http.cookiejar
import json
import logging
import re
import time
import uuid
from typing import Any, Callable, Optional

import httpx

from .jw_eams import JwEamsError, _int_list
from .tju_des import str_enc

logger = logging.getLogger(__name__)

CAS_BASE = "https://sso.tju.edu.cn/cas"
EAMS_BASE = "https://classes.tju.edu.cn/eams"
OCR_URL = "https://learning.twt.edu.cn/ocr"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 目录里 CAS 的"待填验证码"登录会话，最多留 5 分钟
_PENDING: dict[str, "PendingCaptcha"] = {}
PENDING_TTL = 300.0

_EXEC_RE = re.compile(r'name="execution"\s+value="([^"]+)"')
_LT_RE = re.compile(r'name="lt"\s+value="([^"]+)"')
_MSG_RE = re.compile(r'<div[^>]*id="msg"[^>]*>(.*?)</div>', re.S)
_ERROR_SPAN_RE = re.compile(r'id="errormsghide"[^>]*>(.*?)</span>', re.S)
# 登录成功的页面里才有的精确标记（失败页里是 var remind_strong_pwd = '';）
_REMIND_RE = re.compile(r"var\s+remind_strong_pwd\s*=\s*'true'")
_SEMESTER_RE = re.compile(r'id:(\d+),schoolYear:"(\d+)-(\d+)",name:"(1|2)"')
_SEMESTER_JSON_RE = re.compile(r'\{"id":\s*(\d+)[^{}]*?"schoolYear":\s*"(\d+)-(\d+)"[^{}]*?"name":\s*"(1|2)"')
_IDS_RE = re.compile(r'"ids","([^"]+)"')


class PendingCaptcha:
    """一次 GET {CAS}/login + GET {CAS}/code 的结果，等用户/OCR 填验证码。"""

    __slots__ = ("id", "execution", "lt", "cookies", "image", "created", "attempts")

    def __init__(self, execution: str, lt: str, cookies: Any, image: bytes) -> None:
        self.id = uuid.uuid4().hex
        self.execution = execution
        self.lt = lt
        self.cookies = cookies
        self.image = image
        self.created = time.time()
        self.attempts = 0


def _prune_pending() -> None:
    now = time.time()
    for key in [k for k, v in _PENDING.items() if now - v.created > PENDING_TTL]:
        _PENDING.pop(key, None)


def _take_pending(captcha_id: str) -> Optional[PendingCaptcha]:
    _prune_pending()
    return _PENDING.pop(captcha_id.strip(), None)


def _client(timeout: float, cookies: Optional[httpx.Cookies] = None) -> httpx.AsyncClient:
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": False,
        "headers": {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
    }
    if cookies is not None:
        kwargs["cookies"] = cookies
    return httpx.AsyncClient(**kwargs)


def _snapshot_cookies(client: httpx.AsyncClient) -> list[tuple[str, str, str, str]]:
    return [(c.name, c.value, c.domain or "", c.path or "/") for c in client.cookies.jar]


def _restore_cookies(snapshot: Any) -> httpx.Cookies:
    jar = http.cookiejar.CookieJar()
    for item in snapshot or []:
        if isinstance(item, (list, tuple)) and len(item) == 4:
            name, value, domain, path = item
            cookie = http.cookiejar.Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=domain, domain_specified=bool(domain), domain_initial_dot=False,
                path=path or "/", path_specified=True, secure=True, expires=None,
                discard=True, comment=None, comment_url=None, rest={}, rfc2109=False,
            )
            jar.set_cookie(cookie)
    return httpx.Cookies(jar)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _strip_tags(raw: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _error_text(html: str) -> str:
    """CAS 把失败原因放在 <span id="errormsghide">…</span> 里。"""
    for pattern in (_ERROR_SPAN_RE, _MSG_RE):
        match = pattern.search(html)
        if match:
            message = _strip_tags(match.group(1))
            if message:
                return message
    for phrase in ("验证码错误", "验证码不正确", "验证码已失效", "用户名或密码错误", "密码错误", "用户名不存在", "账号不存在"):
        if phrase in html:
            return phrase
    return ""


async def _open_login(client: httpx.AsyncClient) -> tuple[str, str]:
    response = await client.get(f"{CAS_BASE}/login")
    html = response.text
    execution = _EXEC_RE.search(html)
    lt = _LT_RE.search(html)
    if not execution or not lt:
        raise JwEamsError(
            "拿不到 CAS 登录页的 execution/lt（登录页可能改版了）",
            kind="protocol",
            detail=_strip_tags(html)[:200],
        )
    return execution.group(1), lt.group(1)


async def _captcha_image(client: httpx.AsyncClient) -> bytes:
    response = await client.get(f"{CAS_BASE}/code")
    if response.status_code >= 400 or not response.content:
        raise JwEamsError(
            f"取验证码图片失败（HTTP {response.status_code}）", kind="protocol"
        )
    return response.content


async def ocr_captcha(image: bytes, *, timeout: float = 20.0) -> str:
    """把验证码图片交给 TWT 的 OCR（只发图片，密码不上传）。"""
    files = {"image": ("123.png", image, "image/jpg")}
    try:
        async with _client(timeout) as client:
            response = await client.post(OCR_URL, files=files)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise JwEamsError(f"验证码识别服务不可用：{exc}", kind="captcha") from exc
    if isinstance(payload, dict) and payload.get("code") == 200:
        code = _text(payload.get("data"))
        if code:
            return code
    raise JwEamsError("验证码识别服务没有返回结果", kind="captcha", detail=json.dumps(payload, ensure_ascii=False)[:200])


def _logged_in(html: str) -> bool:
    return bool(_REMIND_RE.search(html))


async def _submit_login(
    client: httpx.AsyncClient,
    *,
    execution: str,
    lt: str,
    username: str,
    password: str,
    code: str,
) -> None:
    """POST 登录表单；失败按 CAS 的说法抛错（验证码 / 账号密码）。"""
    data = {
        "code": code,
        "ul": str(len(username)),
        "pl": str(len(password)),
        "lt": lt,
        "rsa": str_enc(username + password + lt, "1", "2", "3"),
        "execution": execution,
        "_eventId": "submit",
    }
    response = await client.post(f"{CAS_BASE}/login", data=data)
    html = response.text
    ok = response.status_code in (301, 302, 303) or _logged_in(html)
    if not ok and any(c.name == "CASTGC" for c in client.cookies.jar):
        ok = True
    if not ok:
        # 二次确认（沿用官方客户端的判据）: 已登录时再 GET /cas/login 会被 302 走
        try:
            probe = await client.get(f"{CAS_BASE}/login")
            ok = probe.status_code in (301, 302, 303)
        except httpx.HTTPError:
            ok = False
    if ok:
        return
    message = _error_text(html) or f"CAS 返回 HTTP {response.status_code}"
    captcha_like = "验证码" in message
    auth_like = any(word in message for word in ("密码", "账号", "帐号", "用户名", "用户", "不存在", "锁定"))
    kind = "captcha" if captcha_like else ("auth_required" if auth_like else "protocol")
    raise JwEamsError(f"CAS 登录失败：{message}", kind=kind, detail=_strip_tags(html)[:200])


async def start_captcha(*, timeout: float = 20.0) -> tuple[dict[str, Any], bytes]:
    """开一个登录会话并把验证码图片要回来（给用户手动填）。"""
    _prune_pending()
    async with _client(timeout) as client:
        execution, lt = await _open_login(client)
        image = await _captcha_image(client)
        cookies = _snapshot_cookies(client)
    pending = PendingCaptcha(execution, lt, cookies, image)
    _PENDING[pending.id] = pending
    return {"captcha_id": pending.id, "expires_in": int(PENDING_TTL)}, image


async def _login(
    username: str,
    password: str,
    *,
    code: Optional[str] = None,
    captcha_id: Optional[str] = None,
    attempts: int = 3,
    timeout: float = 25.0,
    diagnostics: Optional[dict[str, Any]] = None,
) -> httpx.AsyncClient:
    """拿到一个已登录 CAS 的 client（调用方负责 aclose）。"""
    username = _text(username)
    password = password or ""
    if not username or not password:
        raise JwEamsError("请填写教务账号（学号）和办公网密码", kind="auth_required")

    manual = _text(code)
    pending: Optional[PendingCaptcha] = None
    if captcha_id:
        pending = _take_pending(captcha_id)
        if pending is None:
            raise JwEamsError("验证码会话已过期，请重新获取验证码", kind="captcha")

    client = _client(timeout, _restore_cookies(pending.cookies) if pending else None)
    used: list[str] = []
    last_error: Optional[JwEamsError] = None
    limit = 1 if manual else max(1, attempts)
    try:
        for index in range(limit):
            if pending is not None:
                execution, lt, image = pending.execution, pending.lt, pending.image
            else:
                execution, lt = await _open_login(client)
                image = await _captcha_image(client)

            if manual:
                guess = manual
            else:
                guess = await ocr_captcha(image, timeout=timeout)
            used.append(guess)
            if diagnostics is not None:
                diagnostics["captcha_codes"] = used

            try:
                await _submit_login(
                    client,
                    execution=execution,
                    lt=lt,
                    username=username,
                    password=password,
                    code=guess,
                )
                return client
            except JwEamsError as exc:
                last_error = exc
                # 验证码错 -> 换一张重试；账号密码错 -> 直接放弃，别再试（免得锁号）
                if exc.kind != "captcha" or index == limit - 1:
                    break
                logger.info("CAS 验证码第 %s 次识别被拒，换一张重试", index + 1)
    except Exception:
        await client.aclose()
        raise
    await client.aclose()
    raise last_error or JwEamsError("CAS 登录失败", kind="protocol")


async def _eams_get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    return await client.get(f"{EAMS_BASE}{path}", follow_redirects=True)


async def _eams_post(client: httpx.AsyncClient, path: str, data: dict[str, Any]) -> httpx.Response:
    return await client.post(f"{EAMS_BASE}{path}", data=data, follow_redirects=True)


async def _handshake(client: httpx.AsyncClient) -> str:
    """建立教务会话：这一跳会 302 到 CAS 拿票据再跳回来，必须跟着走完。"""
    response = await _eams_post(client, "/dataQuery.action", {"entityId": ""})
    return response.text


def _parse_semesters(raw: str) -> list[dict[str, Any]]:
    """从学期日历里挖出 (id, schoolYear, name)。JSON 和 JSONP 两种都认。"""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and "schoolYear" in node and str(node.get("name")) in ("1", "2"):
                found.append(
                    {
                        "id": str(node["id"]),
                        "schoolYear": str(node["schoolYear"]),
                        "name": str(node["name"]),
                    }
                )
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    try:
        walk(json.loads(raw))
    except (ValueError, TypeError):
        pass
    if not found:
        for match in _SEMESTER_RE.finditer(raw):
            found.append(
                {"id": match.group(1), "schoolYear": f"{match.group(2)}-{match.group(3)}", "name": match.group(4)}
            )
    unique: list[dict[str, Any]] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique


async def _semester_calendar(client: httpx.AsyncClient) -> tuple[str, list[dict[str, Any]]]:
    response = await _eams_post(client, "/dataQuery.action", {"dataType": "semesterCalendar"})
    raw = response.text
    semesters = _parse_semesters(raw)
    if not semesters and ("本次会话已经被过期" in raw or "登录" in _strip_tags(raw)):
        raise JwEamsError(
            "教务会话没建立起来（CAS 票据没被接受）",
            kind="session",
            detail=_strip_tags(raw)[:200],
        )
    return raw, semesters


async def _current_week(client: httpx.AsyncClient) -> Optional[int]:
    """当前教学周 —— 教务对学生**没有**可靠来源，所以这里几乎总是 None。

    踩过的坑：``courseTableForStd!index.action`` 里有个「选择教学周」下拉，列的是
    ``第1周 … 第25周``（一个都不带 ``selected``）。以前直接搜「第(数字)周」会命中
    第一个选项，于是**恒返回 1** —— 比 None 更糟：整学期会悄悄挪一周。
    现在只在选项真的带 ``selected`` 时才采信。
    """
    for path in ("/courseTableForStd!index.action?projectId=1", "/homeExt.action"):
        try:
            response = await _eams_get(client, path)
        except httpx.HTTPError:
            continue
        match = _WEEK_SELECTED_RE.search(response.text)
        if match:
            return int(match.group(1))
    return None


#: 只有 ``<option selected>第N周</option>`` 才算「当前周」（下拉里不带 selected 的全是幌子）
_WEEK_SELECTED_RE = re.compile(r"<option[^>]*\bselected\b[^>]*>\s*第\s*(\d{1,2})\s*周")


def _term_start_from_week(week: Optional[int], *, today: Any = None) -> Optional[int]:
    """第 N 周的今天 -> 第 1 周周一（epoch 秒，东八区零点）。"""
    if not week or week < 1:
        return None
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8))
    now = today or datetime.now(tz)
    monday = now.date() - timedelta(days=now.weekday()) - timedelta(weeks=week - 1)
    return int(datetime(monday.year, monday.month, monday.day, tzinfo=tz).timestamp())


def pick_semester(semesters: list[dict[str, Any]], *, today: Any = None) -> dict[str, Any]:
    """按官方客户端那套规则挑当前学期（8 月后=秋季，2 月前=上一学年秋季，其余=春季）。"""
    from datetime import date as _date

    now = today or _date.today()
    if now.month > 7:
        want_year, want_name = f"{now.year}-{now.year + 1}", "1"
    elif now.month < 2:
        want_year, want_name = f"{now.year - 1}-{now.year}", "1"
    else:
        want_year, want_name = f"{now.year - 1}-{now.year}", "2"
    for item in semesters:
        if item["schoolYear"] == want_year and item["name"] == want_name:
            return item
    if semesters:
        return semesters[-1]
    raise JwEamsError("教务没返回任何学期（学期解析失败）", kind="protocol")


async def _course_table_html(
    client: httpx.AsyncClient, *, semester_id: str, project_id: int
) -> str:
    await _eams_get(client, f"/courseTableForStd!index.action?projectId={project_id}")
    inner = await _eams_get(client, f"/courseTableForStd!innerIndex.action?projectId={project_id}")
    ids_match = _IDS_RE.search(inner.text)
    if not ids_match:
        return ""
    response = await _eams_post(
        client,
        "/courseTableForStd!courseTable.action",
        {
            "ignoreHead": "1",
            "setting.kind": "std",
            "startWeek": "",
            "semester.id": semester_id,
            "ids": ids_match.group(1),
        },
    )
    return response.text


def _judge_subtitle(first: str, second: str) -> bool:
    """``体育D`` vs ``体育D(体适能)`` 这种带副标题的，算同一门课。"""
    if not first or not second:
        return False
    if not first.startswith(second) or len(first) < len(second):
        return False
    tail = first[len(second):].strip()
    return tail.startswith("(") or tail.startswith("（")


def _name_match(course_name: str, arrange_name: str) -> bool:
    if course_name == arrange_name:
        return True
    return _judge_subtitle(course_name, arrange_name) or _judge_subtitle(arrange_name, course_name)


def _resolve_slot_weeks(
    bitmap_weeks: list[int],
    table_weeks_text: Optional[str],
    total_weeks: int = 25,
) -> list[int]:
    """
    系统级对齐单双周与教学周：
    同时结合 JS 排课位图与课程表格原文中教务明确标注的周次文本（如 "1-16周(单)", "2-16(双)"）。
    不再针对单一学年或新生报到周做硬编码全局偏移，而是由表格语义保障单双周绝对正确。
    """
    if not table_weeks_text:
        return sorted(set(bitmap_weeks))

    from .tju_schedule import parse_week_spec

    text_weeks, parity = parse_week_spec(table_weeks_text, total_weeks=total_weeks)
    if not text_weeks:
        return sorted(set(bitmap_weeks))
    if not bitmap_weeks:
        return sorted(text_weeks)

    # 1. 如果表格明确指定了「单周」或「双周」：
    # 无论位图是否存在偏移，单双周的奇偶性必须以教务表格文字为金标准！
    if parity == "odd":
        if all(w % 2 == 0 for w in bitmap_weeks):
            # 位图被误偏移了 1 周（如 2,4,6... 对应原周 1,3,5...），优先采用表格确切指定的单周集合
            return sorted(text_weeks)
        return sorted(w for w in (set(bitmap_weeks) | text_weeks) if w % 2 == 1)

    if parity == "even":
        if all(w % 2 == 1 for w in bitmap_weeks):
            # 位图被误偏移了 1 周（如 1,3,5... 对应原周 2,4,6...），优先采用表格确切指定的双周集合
            return sorted(text_weeks)
        return sorted(w for w in (set(bitmap_weeks) | text_weeks) if w % 2 == 0)

    # 2. 如果表格周次与位图周次存在系统性差 1（比如表格 1-16，位图算成 2-17 或 0-15）：
    if len(text_weeks) == len(bitmap_weeks):
        diffs = [b - t for b, t in zip(sorted(bitmap_weeks), sorted(text_weeks))]
        if len(set(diffs)) == 1 and diffs[0] != 0:
            return sorted(text_weeks)

    # 3. 常规课程：位图与表格交集，兼具位图的精确节次与表格的学期范围
    merged = set(bitmap_weeks) & text_weeks
    return sorted(merged if merged else (bitmap_weeks or text_weeks))


def _weeks_text(weeks: list[int]) -> str:
    """``[1,2,3,5]`` -> ``"1-3,5"``。"""
    if not weeks:
        return ""
    ordered = sorted({int(w) for w in weeks})
    spans: list[str] = []
    start = prev = ordered[0]
    for week in ordered[1:]:
        if week == prev + 1:
            prev = week
            continue
        spans.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = week
    spans.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ",".join(spans)


_JS_QUOTES = "\"'"
_ACTIVITY_SPLIT = "activity = new TaskActivity("
_INDEX_RE = re.compile(r"index\s*=\s*(\d+)\s*\*\s*unitCount\s*\+\s*(\d+)")


def _split_js_args(raw: str) -> list[str]:
    """按顶层逗号切 JS 实参（引号里的逗号不算，``"45楼,203"`` 不会被切开）。"""
    args: list[str] = []
    buf: list[str] = []
    quote = ""
    for char in raw:
        if quote:
            buf.append(char)
            if char == quote:
                quote = ""
            continue
        if char in _JS_QUOTES:
            quote = char
            buf.append(char)
            continue
        if char == ",":
            args.append("".join(buf).strip())
            buf = []
            continue
        buf.append(char)
    args.append("".join(buf).strip())
    return args


def _js_value(token: str) -> str:
    """去掉 JS 字面量的引号；``null`` / ``undefined`` 一律当空串。"""
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in _JS_QUOTES:
        return token[1:-1]
    return "" if token in ("null", "undefined", "false") else token


#: 教务位图的周次比「教学周」多 1 —— 教务把开学前的**报到/入学教育周**也算成第 1 周。
#:
#: 2026-2027 秋季学期实测：新生 8/27 报到（那一周就是教务的第 1 周 = 8/24 起），
#: 8/28-9/20 军训、**9/21 开始上课**（学校迎新日程），而课表位图里第一个 ``1`` 落在
#: 第 5 位 ⇒ 9/21 = 教学周第 4 周；微北洋/校历说的「第 1 教学周」是 8/31。
#: 不减掉这个 1 的话：整个学期的课都往后挪一周，单双周正好反过来。
EAMS_WEEK_OFFSET = 1


def _parse_js_activities(html: str) -> list[dict[str, Any]]:
    """从课表页的 JS 里抠出排课块（``TaskActivity`` + ``index = 星期*unitCount+节次``）。

    教务的网格单元格是空的，真数据在这些 JS 里::

        activity = new TaskActivity(teacherIds, teacherNames, "45203(01039)",
                    "微积分I", "3964", "45楼B203", "00001111…", null, "", …);
        index =1*unitCount+0; table0.activities[index][…]=activity;
        index =1*unitCount+1; ……

    第 2 个串是教师名（逗号分隔）、第 4 个是课程名、第 6 个是教室、第 7 个是
    53 位周次位图（第 w 位 = 1 表示教务的第 w 周有课，减 ``EAMS_WEEK_OFFSET`` 才是教学周）。
    """
    arranges: list[dict[str, Any]] = []
    for chunk in html.split(_ACTIVITY_SPLIT)[1:]:
        head, sep, tail = chunk.partition(");")
        if not sep:
            continue
        args = [_js_value(item) for item in _split_js_args(head)]
        if len(args) < 7:
            continue
        name = args[3].strip()
        room = args[5].strip()
        bitmap = args[6].strip()
        teachers = [item.strip() for item in args[1].split(",") if item.strip()]
        # 位图第 w 位 = 教务第 w 周；教务把报到/入学教育周算作第 1 周，减 1 才是教学周。
        weeks = [
            index + 1 - EAMS_WEEK_OFFSET
            for index, char in enumerate(bitmap)
            if char == "1" and index + 1 - EAMS_WEEK_OFFSET >= 1
        ]
        # 同一个 activity 可能连着占好几节：紧跟其后的 index 行都算它的，
        # 遇到下一个块开头的 ``var teachers`` 就停。
        body = tail.split("var teachers")[0]
        pairs = [(int(day), int(unit)) for day, unit in _INDEX_RE.findall(body)]
        if not name or not weeks or not pairs:
            continue
        day = pairs[0][0] + 1  # 教务 0-based（0 = 周一）
        units = sorted({unit for row_day, unit in pairs if row_day == pairs[0][0]})
        for run in _consecutive_runs(units):
            arranges.append(
                {
                    "name": name,
                    "day": day,
                    "unit": [run[0] + 1, run[-1] + 1],
                    "weeks": weeks,
                    "teachers": teachers,
                    "room": room,
                }
            )
    arranges.sort(key=lambda item: (item["day"], item["unit"][0], item["name"]))
    return arranges


def _consecutive_runs(units: list[int]) -> list[list[int]]:
    """``[0,1,3]`` -> ``[[0,1],[3]]``（连堂拆成一段，跳节不合并）。"""
    runs: list[list[int]] = []
    for unit in units:
        if runs and unit == runs[-1][-1] + 1:
            runs[-1].append(unit)
        else:
            runs.append([unit])
    return runs


def _parse_course_html(html: str) -> list[dict[str, Any]]:
    """把 ``courseTable.action`` 的 HTML 解析成 get_classes 形状的课程行。"""
    if not html:
        return []
    if "本次会话已经被过期" in html:
        raise JwEamsError("教务会话已过期，请重试", kind="session")

    # ---- 1) JS 排课块: 星期 / 节次 / 周次位图 / 教室 ----
    arranges = _parse_js_activities(html)

    # ---- 2) 表格里的课程行: 学分 / 教师 / 周次 / 教室 ----
    rows: list[dict[str, Any]] = []
    tbody = re.search(r"(?<=<tbody)(.*?)(?=</tbody>)", html, re.S)
    table = tbody.group(1) if tbody else ""
    if table.strip():
        for tr in table.split("</tr><tr>"):
            if "<td" not in tr:
                continue
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(cells) < 9:
                continue
            names = re.findall(r"([^>]+)(?=<)", cells[3])
            cleaned = [re.sub(r"\s+", "", item) for item in names]
            if len(cleaned) >= 2:
                name = f"{cleaned[0]} ({cleaned[1]})"
            elif cleaned:
                name = cleaned[0]
            else:
                name = _strip_tags(cells[3])
            if not name:
                continue
            credit = _strip_tags(cells[4]) or "0.0"
            teachers = [item.strip() for item in cells[5].split(",") if item.strip()]
            campus = ""
            for option in ("北洋园", "卫津路"):
                if option in tr:
                    campus = option
                    break
            weeks_text = re.sub(r"\s+", "", _strip_tags(cells[6]))
            room_html = re.sub(r"<br\s*/?>", "\n", cells[8])
            rooms = [item.strip() for item in _strip_tags(room_html).split("\n") if item.strip()]
            if not rooms:
                rooms = [item for item in re.findall(r"\S+", cells[8]) if item != "<br/>"]
            rows.append(
                {
                    "name": name,
                    "credit": credit,
                    "teachers": teachers,
                    "campus": campus,
                    "weeks": weeks_text,
                    "rooms": rooms,
                }
            )

    # ---- 3) 把排课块挂到课程上（教室优先用排课块自己的，列表里的按序兜底）----
    courses: list[dict[str, Any]] = []
    matched: set[str] = set()
    for row in rows:
        slots: list[dict[str, Any]] = []
        room_index = 0
        for arrange in arranges:
            if not _name_match(row["name"], arrange["name"]):
                continue
            room = arrange["room"] or (
                row["rooms"][room_index] if room_index < len(row["rooms"]) else None
            )
            room_index += 1
            matched.add(arrange["name"])
            slot_weeks = _resolve_slot_weeks(arrange["weeks"], row["weeks"])
            slot = {
                "weekday": arrange["day"],
                "unitList": arrange["unit"],
                "location": room or None,
                "weekList": slot_weeks,
            }
            if slot not in slots:
                slots.append(slot)
        if not slots:
            continue
        courses.append(
            {
                "name": row["name"],
                # 列表表那列「起始周」比网格位图少 1（这版教务自己的 off-by-one），一律以位图为准
                "weeks": (
                    _weeks_text(sorted({week for slot in slots for week in slot["weekList"]}))
                    if slots
                    else row["weeks"]
                ),
                "credit": row["credit"],
                "campus": row["campus"],
                "teacherList": row["teachers"],
                "arrangeList": slots,
            }
        )

    # ---- 4) 列表表没解析出来（或缺行）时，用排课块自己拼 ----
    for arrange in arranges:
        if arrange["name"] in matched:
            continue
        item = None
        for existing in courses:
            if _name_match(existing["name"], arrange["name"]):
                item = existing
                break
        if item is None:
            item = {
                "name": arrange["name"],
                "weeks": _weeks_text(arrange["weeks"]),
                "credit": "",
                "campus": "",
                "teacherList": list(arrange["teachers"]),
                "arrangeList": [],
            }
            courses.append(item)
        if not item["teacherList"]:
            item["teacherList"] = list(arrange["teachers"])
        slot = {
            "weekday": arrange["day"],
            "unitList": arrange["unit"],
            "location": arrange["room"] or None,
            "weekList": arrange["weeks"],
        }
        if slot not in item["arrangeList"]:
            item["arrangeList"].append(slot)

    return courses


async def fetch_classes(
    username: str,
    password: str,
    *,
    code: Optional[str] = None,
    captcha_id: Optional[str] = None,
    attempts: int = 3,
    timeout: float = 25.0,
    diagnostics: bool = False,
    on_login: Optional[Callable[[], None]] = None,
    week: Optional[int] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """CAS 直连抓课表。返回 ``(get_classes 形状的 payload, meta)``。

    ``on_login`` 在 CAS 登录成功那一刻调用（用来先把凭据存下来：就算后面教务
    解析出问题，也不用让用户重填密码）。``week`` 是**调用方指定的当前教学周**
    （探针页 / 设置里填的那个）—— 教务页面给不出，只能这么拿。
    """
    notes: dict[str, Any] = {}
    week_hint = week
    client = await _login(
        username,
        password,
        code=code,
        captcha_id=captcha_id,
        attempts=attempts,
        timeout=timeout,
        diagnostics=notes,
    )
    if on_login is not None:
        try:
            on_login()
            notes["credentials_saved"] = True
        except Exception:  # 存凭据失败不该毁掉这次抓取
            logger.warning("保存教务凭据失败", exc_info=True)
            notes["credentials_saved"] = False
    try:
        handshake = await _handshake(client)
        notes["handshake_head"] = " ".join(handshake[:200].split())
        week = week_hint or await _current_week(client)
        notes["current_week"] = week
        notes["week_source"] = (
            "调用方指定（探针页 / 设置）" if week_hint else ("教务页面" if week else "教务页面拿不到当前周")
        )

        calendar_raw, semesters = await _semester_calendar(client)
        semester = pick_semester(semesters)
        notes["semesters"] = semesters
        notes["semester"] = semester

        courses: list[dict[str, Any]] = []
        tables: list[str] = []
        for project_id in (1, 22):
            html = await _course_table_html(client, semester_id=semester["id"], project_id=project_id)
            if not html:
                continue
            parsed = _parse_course_html(html)
            if parsed:
                tables.append(html)
                courses.extend(parsed)
                notes.setdefault("project_ids", []).append(project_id)
                break  # 学分制课表在 projectId=1；研究生(22)只在 1 空时兜底
    finally:
        await client.aclose()

    if diagnostics:
        notes["calendar_raw"] = calendar_raw[:1500]
        if tables:
            notes["course_table_head"] = tables[0][:1500]
    if not courses:
        raise JwEamsError(
            "教务登录成功，但课表是空的（可能本学期还没排课）",
            kind="empty",
            detail=json.dumps(notes.get("semesters") or [], ensure_ascii=False)[:300],
        )

    term = f'{semester["schoolYear"]} {semester["name"]}'
    week = notes.get("current_week")
    # 开学日: 先看学期日历里有没有日期字段 —— 实测这一版教务**没有**（只有学年/学期的
    # HTML 条），所以这一步几乎总是 None，只能靠调用方给的「第 N 周」反推。
    # 无论哪种都要在 meta 里如实标出来源，否则用户会把推算值当成教务的权威值。
    calendar_start = _find_date(calendar_raw)
    start = calendar_start or _term_start_from_week(week)
    if not start:
        # 系统级学期兜底：如果教务未返回学期开始日期，且没有当前周反推，
        # 则使用当前学年的统一校历开学日（秋季通常为 8 月最后一个周一，春季为 2 月下旬周一），
        # 绝不直接退化为 today，避免新注册用户（如大二老生）将今天误判为第 1 周导致全学期单双周翻转！
        from datetime import date, timedelta
        now_date = date.today()
        if now_date.month >= 8:
            # 秋季学期（8月最后一个周一，2026年即 8月31日）
            candidate = date(now_date.year, 8, 31)
            candidate -= timedelta(days=candidate.weekday())
        elif now_date.month <= 1:
            # 跨年秋季学期
            candidate = date(now_date.year - 1, 8, 31)
            candidate -= timedelta(days=candidate.weekday())
        else:
            # 春季学期（通常 2 月底或 3 月初周一）
            candidate = date(now_date.year, 2, 23)
            candidate -= timedelta(days=candidate.weekday())
        from datetime import datetime, timezone
        tz_beijing = timezone(timedelta(hours=8))
        start = int(datetime(candidate.year, candidate.month, candidate.day, tzinfo=tz_beijing).timestamp())
        notes["term_start_source"] = f"校历系统级基准推算 ({candidate.isoformat()})"
    else:
        notes["term_start_source"] = (
            "教务返回的开学日期"
            if calendar_start
            else (f"按第 {week} 教学周 + 今天推算" if week else None)
        )
    payload: dict[str, Any] = {
        "code": 200,
        "data": {"courses": {"major": courses, "minor": []}},
        "term": term,
        "week": week,
        "termStart": start,
    }
    meta: dict[str, Any] = {
        "term": term,
        "week": week,
        "week_source": notes.get("week_source"),
        "term_start_source": notes.get("term_start_source"),
        "term_start": start,
        "captcha_codes": notes.get("captcha_codes"),
        "semester": semester,
        "semesters": semesters,
        "courses": len({row["name"] for row in courses}),
        "slots": sum(len(row["arrangeList"]) for row in courses),
    }
    if diagnostics:
        meta.update(notes)
    return payload, meta


def _find_date(raw: str) -> Optional[int]:
    """从教务返回里找学期开始日期（epoch 秒）。找不到就 None，交给设置里的值。"""
    for pattern in (
        r'startDate"\s*:\s*"(\d{4})-(\d{2})-(\d{2})',
        r'start_date"\s*:\s*"(\d{4})-(\d{2})-(\d{2})',
        r'startDate:"(\d{4})-(\d{2})-(\d{2})"',
    ):
        match = re.search(pattern, raw)
        if match:
            from datetime import datetime, timedelta, timezone

            stamp = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone(timedelta(hours=8)))
            return int(stamp.timestamp())
    return None


__all__ = [
    "CAS_BASE",
    "EAMS_BASE",
    "OCR_URL",
    "PendingCaptcha",
    "fetch_classes",
    "ocr_captcha",
    "pick_semester",
    "start_captcha",
]
