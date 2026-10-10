"""``/api/tju`` — connect a real 微北洋 (TJU WePeiyang) account.

Why this splits in two halves
-----------------------------
* **Credentials** work server-side. The legacy auth endpoint
  (``POST api.twt.edu.cn/api/auth/common``) is reachable from anywhere once the
  official client-identity headers are sent, and answers ``40004 用户名或密码错误``
  for a wrong password — verified against the live service. So we can log the
  user in, keep the token, and report credential problems precisely.
* **The timetable**: ``open.twt.edu.cn`` is dead off-campus (every request gets
  ``302 -> network-notice.tju.edu.cn``). The path that actually works — and the
  one the official clients use — is ``POST learning.twt.edu.cn/get_classes``
  with the *office-network* credentials: TWT's own backend does the CAS login
  and returns normalised JSON. ``/jw/import`` uses it server-side, converts the
  payload to the ``v1/classtable`` shape and reuses the import pipeline below;
  ``/jw/probe`` serves the credential form. The legacy browser-capture flow
  (``POST /api/tju/import``) still works for anything already captured.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..connectors.base import ConnectorError
from ..connectors.jw_eams import (
    ENDPOINT as JW_ENDPOINT,
    JwEamsError,
    convert_classtable as jw_convert_classtable,
    discover as jw_discover,
    fetch_classes as jw_fetch_classes,
    shape_report as jw_shape_report,
)
from ..connectors.tju_api import KIND_MESSAGES, TjuApiClient, TjuApiError
from ..connectors.tju_cas import fetch_classes as cas_fetch_classes
from ..connectors.tju_cas import start_captcha as cas_start_captcha
from ..connectors.tju_schedule import MODE_KEY, SEMESTER_KEY, TERM_START_KEY, TjuScheduleConnector
from ..db import KVStore
from ..schemas import SimpleResult
from ..security import require_read, require_write
from ..services.sync_engine import get_sync_engine
from ..timeutil import utcnow

router = APIRouter(prefix="/tju", tags=["tju"])

logger = logging.getLogger(__name__)


class CredentialsIn(BaseModel):
    mode: str = Field(default="password", description="password | token")
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    verify: bool = True


class ImportIn(BaseModel):
    """Either a parsed object or the raw text the browser pasted."""

    payload: Any = None
    text: Optional[str] = None
    source: str = "web"
    total_weeks: Optional[int] = None
    run_sync: bool = True


def _connector() -> TjuScheduleConnector:
    return TjuScheduleConnector(settings=get_settings(), store=KVStore())


def _client() -> TjuApiClient:
    return TjuApiClient(settings=get_settings())


def _campus_hint(detail: dict[str, Any]) -> str:
    kind = str(detail.get("kind") or "")
    return KIND_MESSAGES.get(kind, str(detail.get("message") or ""))


def _apply_import(payload: Any, source: str, total_weeks: Optional[int]) -> tuple[dict[str, Any], int]:
    """Store the class table, drop leftover demo rows, rebuild the engine.

    Returns ``(import_meta, demo_rows_removed)``. The engine caches its
    connector list, and demo mode is exclusive — so it has to be rebuilt once a
    real source takes over, otherwise the imported table never reaches the
    timeline.
    """
    from ..db import session_scope
    from ..services.events import purge_demo_events
    from ..services.sync_engine import reset_sync_engine

    connector = _connector()
    meta = connector.store_classtable(payload, source=source, total_weeks=total_weeks)
    with session_scope() as session:
        removed = purge_demo_events(session)
    reset_sync_engine()
    return meta, removed


# ------------------------------------------------------------------- status
@router.get("/status", response_model=SimpleResult, dependencies=[Depends(require_read)])
async def tju_status(probe: bool = False) -> SimpleResult:
    """Everything the settings page needs: mode, credentials, import, gate."""
    settings = get_settings()
    connector = _connector()
    detail: dict[str, Any] = await connector.status()
    detail["endpoints"] = {
        "open": settings.tju_open_base,
        "legacy": settings.tju_api_base,
        "mode_env": settings.tju_mode,
        "mode_override": KVStore().get(MODE_KEY),
    }
    if probe:
        detail["probe"] = await _client().probe()
    return SimpleResult(ok=True, detail=detail)


# -------------------------------------------------------------- credentials
@router.post("/credentials", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def set_credentials(payload: CredentialsIn) -> SimpleResult:
    """Log in with 学号/密码 (or accept a pasted token) and store the token."""
    connector = _connector()
    client = _client()
    mode = (payload.mode or "password").strip().lower()

    try:
        if mode == "token":
            token = (payload.token or "").strip()
            if len(token) < 8:
                raise TjuApiError("请粘贴有效的 token", kind="auth_required")
            who = ""
            verified = False
            if payload.verify:
                info = await client.verify_token(token)
                who = str(info.get("name") or "")
                verified = True
            info = connector.store_token(token, source="token", account=payload.username or who)
            return SimpleResult(
                ok=True,
                message="令牌已保存" + (f"（{who}）" if who else ""),
                detail={"credentials": info, "verified": verified, "source": "token"},
            )

        username = (payload.username or "").strip()
        password = payload.password or ""
        if not username or not password:
            raise HTTPException(status_code=422, detail="请填写学号和密码，或改用 token 模式")
        token, source = await client.login(username, password)
        info = connector.store_token(token, source=source, account=username)
        note = "（校园网内登录成功）" if source == "open" else "（通过公网可用的旧接口登录成功）"
        return SimpleResult(
            ok=True,
            message=f"登录成功，凭据已保存{note}",
            detail={"credentials": info, "source": source, "account": username},
        )
    except TjuApiError as exc:
        raise HTTPException(
            status_code=400,
            detail={"kind": exc.kind, "message": _campus_hint(exc.as_dict()), "raw": str(exc)},
        ) from exc


@router.delete("/credentials", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def clear_credentials() -> SimpleResult:
    _connector().clear_token()
    return SimpleResult(ok=True, message="凭据已删除")


# -------------------------------------------------------- server-side fetch
@router.post("/sync", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def tju_sync() -> SimpleResult:
    """Try to pull the class table from the server.

    Off-campus this reports ``campus_network`` — that is expected, and the UI
    then offers the browser-side path.
    """
    settings = get_settings()
    connector = _connector()
    token = connector.stored_token() or settings.tju_access_token
    if not token:
        return SimpleResult(
            ok=False,
            message="还没有微北洋凭据 — 请在上面填学号密码（或粘贴 token）保存",
            detail={"kind": "auth_required"},
        )
    try:
        payload = await _client().fetch_classtable(token)
    except TjuApiError as exc:
        info = exc.as_dict()
        return SimpleResult(ok=False, message=_campus_hint(info), detail=info)
    meta, demo_removed = _apply_import(payload, "server", None)
    outcome = await get_sync_engine(settings).run(trigger="tju-import")
    return SimpleResult(
        ok=True,
        message=f"从服务器抓取成功：{meta['courses']} 门课",
        detail={
            "import": meta,
            "demo_rows_removed": demo_removed,
            "sync": {"created": outcome.created, "updated": outcome.updated,
                     "pruned": outcome.pruned, "ok": outcome.ok},
        },
    )


# ------------------------------------------------------------------- import
@router.post("/import", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def tju_import(payload: ImportIn) -> SimpleResult:
    """Store a class-table payload fetched by the browser (campus network) or pasted."""
    raw: Any = payload.payload if payload.payload is not None else payload.text
    if raw is None or raw == "":
        raise HTTPException(status_code=422, detail="没有收到课表数据")

    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{"):
            try:
                raw = json.loads(text)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"JSON 解析失败：{exc}") from exc
        elif "<" in text[:200]:
            raise HTTPException(
                status_code=422,
                detail="收到的是网页 HTML，不是课表 JSON — 请用「在浏览器内抓取」，"
                       "或打开签名链接后复制接口返回的 JSON",
            )

    connector = _connector()
    try:
        meta, demo_removed = _apply_import(raw, payload.source, payload.total_weeks)
    except (TjuApiError, ConnectorError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"课表解析失败：{exc}") from exc

    detail: dict[str, Any] = {
        "import": meta,
        "semester": connector.semester.summary(),
        "demo_rows_removed": demo_removed,
    }
    if payload.run_sync:
        outcome = await get_sync_engine(get_settings()).run(trigger="tju-import")
        detail["sync"] = {
            "ok": outcome.ok,
            "created": outcome.created,
            "updated": outcome.updated,
            "pruned": outcome.pruned,
            "message": outcome.message,
        }
    return SimpleResult(ok=True, message=f"已导入 {meta['courses']} 门课 / {meta['slots']} 个时段", detail=detail)


@router.delete("/import", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def clear_import(keep_mode: bool = False) -> SimpleResult:
    connector = _connector()
    connector.clear_classtable()
    if keep_mode:
        KVStore().set(MODE_KEY, "ics")
    return SimpleResult(ok=True, message="已清除导入的课表（下次同步会清掉对应课程事件）")


# ------------------------------------------------- 教务 (办公网) 直接抓取课表
# The real path the official 微北洋 clients use: POST the *office-network*
# credentials to ``learning.twt.edu.cn/get_classes`` and let TWT's backend do
# the CAS login. The result is normalised into the same ``v1/classtable`` shape
# the browser-capture flow produces, so the whole import pipeline is reused.
JW_CREDS_KEY = "tju.jw_credentials"
JW_LAST_KEY = "tju.jw_last_import"


class JwImportIn(BaseModel):
    username: str
    password: str
    save: bool = True
    run_sync: bool = True
    total_weeks: Optional[int] = None
    # auto = 先试 CAS 直连，失败再退到 TWT get_classes；cas = 只用直连
    via: str = "auto"
    captcha: Optional[str] = None       # 手动填的验证码（配合 /jw/captcha）
    captcha_id: Optional[str] = None
    #: 当前教学周。教务页面拿不到，得由用户给一个锚点（留空则整学期按"今天=第1周"排，会偏移）
    week: Optional[int] = None


def _term_start_source(semester: dict[str, Any]) -> Optional[str]:
    """学期起始日是从哪来的（用来判断要不要提醒用户会整体偏移）。None = 没有锚点。"""
    if semester.get("term_start_source"):
        # 连接器已经如实标过来源（教务返回 / 按第 N 周推算），优先用它
        return str(semester["term_start_source"])
    if semester.get("term_start"):
        return "教务返回的开学日期"
    if semester.get("week"):
        return f"按当前第 {semester['week']} 教学周 + 今天推算"
    kv = KVStore()
    if kv.get(TERM_START_KEY):
        return "上次导入保存的开学日期"
    stored = kv.get(SEMESTER_KEY) or {}
    if stored.get("start_date"):
        return "已保存的学期设置"
    if get_settings().semester_start_date:
        return "设置里的第一周周一"
    return None


def _max_week(payload: Any) -> Optional[int]:
    """payload 里出现过的最大教学周。

    用途：学期总周数不能只看设置里的默认值（16），这里课表有排到第 20 周的课 ——
    用 16 会把第 17-20 周直接截掉。两种形状都认：
    ``data.courses.major[].arrangeList[].weekList``（CAS 直连）和
    ``week:{start,end}`` / ``arrange[].week``（v1 classtable）。
    """
    best: Optional[int] = None

    def bump(value: Any) -> None:
        nonlocal best
        if isinstance(value, int) and not isinstance(value, bool):
            best = value if best is None else max(best, value)
        elif isinstance(value, str) and value.strip().isdigit():
            bump(int(value.strip()))

    try:
        courses = payload["data"]["courses"]["major"]
    except (KeyError, TypeError):
        return None
    for course in courses or []:
        if not isinstance(course, dict):
            continue
        span = course.get("week")
        if isinstance(span, dict):
            bump(span.get("start"))
            bump(span.get("end"))
        for number in re.findall(r"\d+", str(course.get("weeks") or "")):
            bump(number)
        slots = list(course.get("arrangeList") or []) + list(course.get("arrange") or [])
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            week_spec = slot.get("week")
            if isinstance(week_spec, (list, tuple, set)):
                for week in week_spec:
                    bump(week)
            elif isinstance(week_spec, str):
                for number in re.findall(r"\d+", week_spec):
                    bump(number)
            for week in slot.get("weekList") or []:
                bump(week)
    return best


def _jw_http_error(exc: JwEamsError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"kind": exc.kind, "message": str(exc), "detail": exc.detail, "status": exc.status},
    )


async def _jw_import(
    username: str,
    password: str,
    *,
    save: bool,
    run_sync: bool,
    total_weeks: Optional[int],
    via: str = "auto",
    captcha: Optional[str] = None,
    captcha_id: Optional[str] = None,
    week: Optional[int] = None,
) -> SimpleResult:
    mode = (via or "auto").strip().lower()
    raw: Any = None
    cas_error: Optional[JwEamsError] = None
    semester: dict[str, Any] = {}
    route: dict[str, Any] = {}

    def _remember() -> None:
        # CAS 登录成功就先落盘：之后即使教务解析失败，/jw/refresh 也能直接复跑
        KVStore().set(
            JW_CREDS_KEY,
            {"username": username, "password": password, "saved_at": utcnow().isoformat(timespec="seconds")},
        )

    if mode in ("auto", "cas"):
        try:
            raw, cas_meta = await cas_fetch_classes(
                username,
                password,
                code=captcha,
                captcha_id=captcha_id,
                on_login=_remember if save else None,
                week=week,
            )
            semester = {
                "term": cas_meta.get("term") or "",
                "week": cas_meta.get("week"),
                "week_source": cas_meta.get("week_source"),
                "term_start_source": cas_meta.get("term_start_source"),
                "term_start": cas_meta.get("term_start"),
            }
            route = {
                "via": "cas",
                "terms": cas_meta.get("term"),
                "courses": cas_meta.get("courses"),
                "slots": cas_meta.get("slots"),
                "semester": cas_meta.get("semester"),
                "semesters": cas_meta.get("semesters"),
                "captcha_codes": cas_meta.get("captcha_codes"),
            }
        except JwEamsError as exc:
            cas_error = exc
            # 账号密码错/验证码错是确定结论，别再拿同一份凭据去问 TWT
            if mode == "cas" or exc.kind in ("auth_required", "captcha"):
                raise _jw_http_error(exc) from exc
            logger.warning("CAS 直连失败（%s）：%s —— 退回 TWT get_classes", exc.kind, exc)
            raw = None

    if raw is None:
        try:
            raw = await jw_fetch_classes(username, password)
            semester = jw_discover(raw)
            route = {"via": "twt"}
        except JwEamsError as exc:
            if cas_error is not None:
                raise _jw_http_error(
                    JwEamsError(
                        f"CAS 直连失败：{cas_error}；TWT 旧接口也失败：{exc}",
                        kind=cas_error.kind,
                        detail=f"cas={cas_error.detail or ''} | twt={exc.detail or ''}"[:300],
                    )
                ) from exc
            raise _jw_http_error(exc) from exc

    try:
        payload = jw_convert_classtable(
            raw,
            term=semester["term"],
            week=semester["week"],
            term_start=semester["term_start"],
        )
    except JwEamsError as exc:
        raise _jw_http_error(exc) from exc

    if total_weeks is None:
        # 学期总周数对齐真实课表：设置里的默认值是 16，而这里排到第 20 周 ——
        # 用 16 会把第 17-20 周的课静默截掉。只升不降（不低于设置里的值）。
        found = _max_week(raw)
        total_weeks = max(found, get_settings().semester_total_weeks) if found else None
    try:
        meta, demo_removed = _apply_import(payload, "jw", total_weeks)
    except (TjuApiError, ConnectorError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"课表解析失败：{exc}") from exc

    names: list[str] = []
    for entry in payload["data"]["data"]:
        name = str(entry.get("coursename") or "").strip()
        if name and name not in names:
            names.append(name)

    now = utcnow().isoformat(timespec="seconds")
    if save:
        KVStore().set(JW_CREDS_KEY, {"username": username, "password": password, "saved_at": now})
    KVStore().set(
        JW_LAST_KEY,
        {"at": now, "courses": meta.get("courses"), "slots": meta.get("slots"), "term": semester["term"]},
    )

    detail: dict[str, Any] = {
        "import": meta,
        "semester": _connector().semester.summary(),
        "demo_rows_removed": demo_removed,
        "discovered": semester,
        "route": route,
        "captcha_used": (route or {}).get("captcha_codes"),
        "course_names": names[:40],
        "shape": jw_shape_report(raw),
        "term_start_source": _term_start_source(semester),
    }
    if detail["term_start_source"] is None:
        detail["warning"] = (
            "没有学期起始日（教务不返回开学时间）：请在探针页填「当前教学周」，"
            "或在设置里填「第一周周一」——否则课表会按今天当第 1 周排，整体偏移。"
        )
    if run_sync:
        outcome = await get_sync_engine(get_settings()).run(trigger="tju-jw")
        detail["sync"] = {
            "ok": outcome.ok,
            "created": outcome.created,
            "updated": outcome.updated,
            "pruned": outcome.pruned,
            "message": outcome.message,
        }
    return SimpleResult(
        ok=True,
        message=f"教务课表导入成功：{meta['courses']} 门课 / {meta['slots']} 个时段",
        detail=detail,
    )


@router.post("/jw/import", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def jw_import(body: JwImportIn) -> SimpleResult:
    """Server-side fetch of the real 教务 timetable (the official app's path)."""
    return await _jw_import(
        body.username,
        body.password,
        save=body.save,
        run_sync=body.run_sync,
        total_weeks=body.total_weeks,
        via=body.via,
        captcha=body.captcha,
        captcha_id=body.captcha_id,
        week=body.week,
    )


@router.post("/jw/captcha", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def jw_captcha() -> SimpleResult:
    """One CAS captcha image, for when the OCR server guesses wrong."""
    try:
        meta, image = await cas_start_captcha()
    except JwEamsError as exc:
        raise _jw_http_error(exc) from exc
    return SimpleResult(
        ok=True,
        message="验证码已取回：把图里的 4 个字符填进“验证码”框，再提交导入（5 分钟内有效）",
        detail={
            "captcha_id": meta["captcha_id"],
            "expires_in": meta["expires_in"],
            "image": "data:image/jpeg;base64," + base64.b64encode(image).decode(),
        },
    )


@router.get("/jw/status", response_model=SimpleResult, dependencies=[Depends(require_read)])
async def jw_status() -> SimpleResult:
    """Whether office-network credentials are held (values are never returned)."""
    saved = KVStore().get(JW_CREDS_KEY) or {}
    return SimpleResult(
        ok=True,
        detail={
            "endpoint": JW_ENDPOINT,
            "credentials_saved": bool(saved.get("username")),
            "username": saved.get("username") or "",
            "saved_at": saved.get("saved_at") or "",
            "last_import": KVStore().get(JW_LAST_KEY) or {},
        },
    )


@router.post("/jw/refresh", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def jw_refresh() -> SimpleResult:
    """Re-fetch with the saved credentials — no password re-entry needed."""
    saved = KVStore().get(JW_CREDS_KEY) or {}
    if not saved.get("username") or not saved.get("password"):
        raise HTTPException(status_code=422, detail="还没有保存教务凭据，请先在页面上导入一次")
    return await _jw_import(
        str(saved["username"]),
        str(saved["password"]),
        save=False,
        run_sync=True,
        total_weeks=None,
        week=None,
    )


@router.delete("/jw/credentials", response_model=SimpleResult, dependencies=[Depends(require_write)])
async def jw_forget() -> SimpleResult:
    KVStore().delete(JW_CREDS_KEY)
    return SimpleResult(ok=True, message="已删除保存的教务凭据（已导入的课表保留）")


# The form below lets the credentials be entered without a frontend build. It is
# same-origin with the API, so it authorises the POST the same way the PWA does:
# the shared token the PWA keeps in localStorage (web/src/api.js TOKEN_KEY) is
# echoed back as X-Admin-Token, with an account session cookie as the fallback.
# Open: https://nzlab.online/schedule/api/tju/jw/probe
JW_PROBE_PAGE = r"""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>导入教务课表 · CampusHub</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:680px;margin:24px auto;padding:0 16px;line-height:1.6}
 label{display:block;margin:14px 0 4px;font-weight:600}
 input,select{width:100%;padding:9px;font-size:16px;box-sizing:border-box;border:1px solid #b6b6b6;border-radius:6px}
 button{margin-top:12px;padding:11px 18px;font-size:16px;border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer}
 button.ghost{background:#e5e7eb;color:#111}
 button[disabled]{opacity:.55;cursor:default}
 #status{margin-top:18px;font-weight:600}
 .hint{color:#555;font-size:13.5px}
 pre{white-space:pre-wrap;word-break:break-word;background:#f6f8fa;padding:12px;border-radius:6px;font-size:12.5px;max-height:52vh;overflow:auto}
 #capwrap{margin-top:10px}
 #capimg{border:1px solid #ccc;border-radius:4px;height:52px;vertical-align:middle}
 .ok{color:#137333}.bad{color:#b3261e}
</style>
</head>
<body>
<h1>导入教务课表</h1>
<p>填 <b>教务账号（学号）</b> 和 <b>办公网密码</b>（登 <code>classes.tju.edu.cn</code> 的那一套，不是微北洋密码）。凭据只发到本服务器；服务器自己走 CAS 登录 <code>sso.tju.edu.cn</code>，再直接爬教务的课表 —— 就是微北洋客户端里的那条直连链路。</p>
<p class="hint">（TWT 的 <code>get_classes</code> 现在对任何凭据都回「学期解析失败」，所以默认不再走它。）</p>
<form id="f">
  <label for="u">教务账号（学号）</label>
  <input id="u" name="username" autocomplete="username" required>
  <label for="p">办公网密码</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>

  <details>
    <summary>验证码（自动识别失败时才需要点开）</summary>
    <p class="hint">默认用 OCR 自动识别，识别错会自动换一张重试。这里手动取一张填上，成功率最高。</p>
    <button type="button" class="ghost" id="getcap">获取验证码图片</button>
    <div id="capwrap" hidden>
      <div><img id="capimg" alt="验证码"></div>
      <label for="code">图里的 4 个字符</label>
      <input id="code" autocomplete="off" placeholder="例如 a3fk">
      <p class="hint" id="capinfo"></p>
    </div>
  </details>

  <label for="week">当前教学周（可选，但强烈建议填）</label>
  <input id="week" type="number" min="1" max="30" step="1" placeholder="例如 5 —— 看微北洋首页的「第 N 周」">
  <p class="hint">教务不返回「现在第几周」。不填的话，整张课表会按「今天 = 第 1 周」去排 —— 日期会整体偏移。</p>

  <label for="via">抓取链路</label>
  <select id="via">
    <option value="cas">CAS 直连教务（默认，推荐）</option>
    <option value="auto">先 CAS，失败再退回 TWT 旧接口</option>
  </select>

  <button type="submit">提交并抓取课表</button>
</form>
<details id="auth">
  <summary>授权状态（打不开就点这里）</summary>
  <p id="authInfo">检测中…</p>
  <label for="t">手动粘贴 ADMIN_TOKEN（只在自动检测失败时需要）</label>
  <input id="t" autocomplete="off" placeholder="留空 = 用自动检测到的凭据">
</details>
<div id="status"></div>
<pre id="out"></pre>
<script>
const form = document.getElementById('f');
const statusBox = document.getElementById('status');
const out = document.getElementById('out');
const target = location.href.replace(/\/probe.*$/, '/import');
const capTarget = location.href.replace(/\/probe.*$/, '/captcha');
const TOKEN_KEY = 'campushub.adminToken';
const tokenField = document.getElementById('t');
const authInfo = document.getElementById('authInfo');
let captchaId = '';

function storedToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (error) { return ''; }
}
function authHeaders() {
  const manual = (tokenField.value || '').trim();
  const token = manual || storedToken();
  return token ? {'X-Admin-Token': token, 'X-Subscribe-Token': token} : {};
}
function describeAuth() {
  if ((tokenField.value || '').trim()) return '将使用你下面粘贴的 token。';
  if (storedToken()) return '已读到本站 localStorage 里 PWA 保存的 token，提交时会自动带上。';
  return '没找到 token，也没有登录账号 —— 先在 https://nzlab.online/schedule/ 登录，或把 ADMIN_TOKEN 粘到下面。';
}
authInfo.textContent = describeAuth();
tokenField.addEventListener('input', function () { authInfo.textContent = describeAuth(); });

document.getElementById('getcap').addEventListener('click', async (event) => {
  const button = event.target;
  button.disabled = true;
  try {
    const response = await fetch(capTarget, {method: 'POST', headers: Object.assign({'Content-Type': 'application/json'}, authHeaders()), credentials: 'include'});
    const data = await response.json().catch(() => ({detail: '响应不是 JSON'}));
    if (!response.ok) {
      document.getElementById('capinfo').textContent = '取验证码失败：' + JSON.stringify(data.detail || data);
      return;
    }
    captchaId = (data.detail && data.detail.captcha_id) || '';
    document.getElementById('capimg').src = (data.detail && data.detail.image) || '';
    document.getElementById('capwrap').hidden = false;
    document.getElementById('capinfo').textContent = '验证码 5 分钟内有效；看不清就再点一次「获取验证码图片」。';
  } catch (error) {
    document.getElementById('capinfo').textContent = String(error);
  }
  button.disabled = false;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  statusBox.textContent = '正在抓取（约 5–20 秒：CAS 登录 + 验证码）…';
  out.textContent = '';
  const code = (document.getElementById('code').value || '').trim();
  try {
    const response = await fetch(target, {
      method: 'POST',
      headers: Object.assign({'Content-Type': 'application/json'}, authHeaders()),
      credentials: 'include',
      body: JSON.stringify({
        username: document.getElementById('u').value.trim(),
        password: document.getElementById('p').value,
        save: true,
        run_sync: true,
        via: document.getElementById('via').value,
        week: Number(document.getElementById('week').value) || null,
        captcha: code || null,
        captcha_id: code && captchaId ? captchaId : null
      })
    });
    const data = await response.json().catch(() => ({detail: '响应不是 JSON'}));
    if (response.ok) {
      statusBox.textContent = '✅ ' + (data.message || '成功');
      statusBox.className = 'ok';
    } else {
      const detail = data.detail || data;
      const message = (detail && detail.message) || JSON.stringify(detail);
      const kind = (detail && detail.kind) || '';
      let extra = '';
      if (response.status === 401) extra = '（未授权：先在 PWA 登录，或粘贴 ADMIN_TOKEN）';
      else if (kind === 'auth_required') extra = '（账号或密码不对 —— CAS 的原话见下面 detail）';
      else if (kind === 'captcha') extra = '（验证码没认对：点「获取验证码图片」手动填一次）';
      else if (kind === 'network') extra = '（服务器连不上 SSO/教务）';
      statusBox.className = 'bad';
      statusBox.textContent = '❌ 失败（HTTP ' + response.status + '）' + extra + ' ' + message;
    }
    out.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    statusBox.className = 'bad';
    statusBox.textContent = '❌ 请求失败';
    out.textContent = String(error);
  }
  button.disabled = false;
});
</script>
</body>
</html>
"""


@router.get("/jw/probe", response_class=HTMLResponse, include_in_schema=False)
async def jw_probe_page() -> HTMLResponse:
    """Credential form for the 教务 import — no frontend build required."""
    return HTMLResponse(JW_PROBE_PAGE)
