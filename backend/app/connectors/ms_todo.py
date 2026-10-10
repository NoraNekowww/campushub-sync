"""Microsoft To Do connector.

Auth model
----------
Runtime credentials live in ``data/ms_token.json`` (mode 0600, atomic write):

    {"access_token": ..., "refresh_token": ..., "expires_at": <epoch>, "account": ...}

* The device-code flow is *initiated* with MSAL (``PublicClientApplication.
  initiate_device_flow``), which is what produces the user code shown in chat.
* Polling for the token is done by this module against the documented RFC 8628
  device-code grant, so a poll is non-blocking for the web request that asks for
  it (MSAL's own ``acquire_token_by_device_flow`` blocks until the user acts).
* Refresh uses the RFC 6749 ``refresh_token`` grant and rotates the stored
  refresh token when Microsoft returns a new one.

Graph data is mapped onto the unified :class:`~app.models.Event` and recurring
tasks are expanded (bounded by ``HORIZON_DAYS``) so a single weekly task shows
up as individual deadlines on the timeline.
"""

from __future__ import annotations

import asyncio
import base64
import calendar
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from ..db import KVStore
from ..models import Event, EventStatus, Source, make_event_id
from ..timeutil import UTC, as_aware, parse_graph_datetime, utcnow
from .base import AuthRequiredError, ConnectorError, FetchResult, HttpConnector

log = logging.getLogger("campushub.connectors.ms_todo")

DEVICE_FLOW_KEY = "ms.device_flow"
TOKEN_KEY = "ms.tokens"
ACCOUNT_KEY = "ms.account"

IMPORTANCE_PRIORITY = {"high": 1, "normal": 5, "low": 9}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_INDEX = {name: idx for idx, name in enumerate(WEEKDAYS)}
RELATIVE_INDEX = {"first": 0, "second": 1, "third": 2, "fourth": 3, "last": -1}
MAX_OCCURRENCES = 366
_HTML_TAG = re.compile(r"<[^>]+>")


def _plain_text(body: dict | None) -> Optional[str]:
    if not body:
        return None
    content = (body.get("content") or "").strip()
    if not content:
        return None
    if (body.get("contentType") or "").lower() == "html":
        content = _HTML_TAG.sub("", content)
        content = (
            content.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
    return " ".join(content.split()) or None


class MSTodoConnector(HttpConnector):
    name = "microsoft_todo"
    label = "Microsoft To Do"

    def __init__(self, settings=None, store: Optional[KVStore] = None) -> None:
        super().__init__(settings)
        self.store = store or KVStore()
        self._msal_app = None

    # ------------------------------------------------------------- MSAL setup
    @property
    def authority(self) -> str:
        host = (self.settings.ms_authority_host or "").rstrip("/")
        return f"{host}/{self.settings.ms_tenant or 'common'}"

    @property
    def token_url(self) -> str:
        return f"{self.authority}/oauth2/v2.0/token"

    def _msal(self):
        """MSAL public client — used for device-flow *initiation* only."""
        if self._msal_app is None:
            client_id = self.settings.ms_client_id
            if not client_id:
                raise AuthRequiredError("MS_CLIENT_ID is not configured")
            try:
                import msal
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise ConnectorError("msal is not installed") from exc
            self._msal_app = msal.PublicClientApplication(
                client_id,
                authority=self.authority,
            )
        return self._msal_app

    # ------------------------------------------------------------ token store
    def _tokens(self) -> dict[str, Any]:
        return self.store.get(TOKEN_KEY, {}) or {}

    def _store_tokens(self, payload: dict[str, Any], account: str | None = None) -> dict[str, Any]:
        tokens = self._tokens()
        tokens.update(
            {
                "access_token": payload.get("access_token") or tokens.get("access_token"),
                "refresh_token": payload.get("refresh_token") or tokens.get("refresh_token"),
                "expires_at": time.time() + int(payload.get("expires_in", 3600)) - 60,
                "scope": payload.get("scope", tokens.get("scope")),
                "account": account or tokens.get("account"),
                "obtained_at": time.time(),
            }
        )
        self.store.set(TOKEN_KEY, tokens)
        if tokens.get("account"):
            self.store.set(ACCOUNT_KEY, {"username": tokens["account"]})
        return tokens

    def auth_state(self) -> dict[str, Any]:
        tokens = self._tokens()
        expires_at = float(tokens.get("expires_at") or 0)
        return {
            "authorized": bool(tokens.get("refresh_token") or tokens.get("access_token")),
            "account": tokens.get("account"),
            "expires_in": int(max(0, expires_at - time.time())) if expires_at else None,
            "scopes": self.settings.scope_list,
            "authority": self.authority,
        }

    def forget_tokens(self) -> None:
        self.store.delete(TOKEN_KEY)
        self.store.delete(DEVICE_FLOW_KEY)

    # ----------------------------------------------------------- device flow
    async def start_device_flow(self) -> dict[str, Any]:
        app = self._msal()
        flow = await asyncio.to_thread(
            lambda: app.initiate_device_flow(scopes=self.settings.scope_list)
        )
        if "user_code" not in flow:
            raise ConnectorError(
                flow.get("error_description") or flow.get("error") or "device flow failed"
            )
        flow["started_at"] = time.time()
        self.store.set(DEVICE_FLOW_KEY, flow)
        return {
            "user_code": flow["user_code"],
            "verification_uri": flow.get("verification_uri", "https://microsoft.com/devicelogin"),
            "verification_uri_complete": flow.get("verification_uri_complete"),
            "device_code": flow["device_code"],
            "expires_in": int(flow.get("expires_in", 900)),
            "interval": int(flow.get("interval", 5)),
            "message": flow.get("message", ""),
        }

    async def poll_device_flow(self) -> dict[str, Any]:
        """One non-blocking poll of the device-code grant."""
        flow = self.store.get(DEVICE_FLOW_KEY)
        if not flow:
            return {"state": "error", "message": "no device flow in progress"}
        started_at = float(flow.get("started_at") or 0)
        if started_at and time.time() - started_at > float(flow.get("expires_in", 900)):
            self.store.delete(DEVICE_FLOW_KEY)
            return {"state": "expired", "message": "device code expired — start again"}

        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self.settings.ms_client_id,
            "device_code": flow["device_code"],
        }
        response = await self._token_request(payload, tolerate_pending=True)
        if response.get("error") == "authorization_pending":
            return {"state": "pending", "message": "waiting for you to approve the code"}
        if response.get("error") == "slow_down":
            flow["interval"] = int(flow.get("interval", 5)) + 5
            self.store.set(DEVICE_FLOW_KEY, flow)
            return {"state": "pending", "message": "slow down requested by Microsoft"}
        if response.get("error"):
            self.store.delete(DEVICE_FLOW_KEY)
            return {
                "state": "error",
                "message": response.get("error_description") or response["error"],
            }
        if not response.get("access_token"):
            return {"state": "pending", "message": "still pending"}

        account = self._account_from_id_token(response.get("id_token"))
        self._store_tokens(response, account=account)
        self.store.delete(DEVICE_FLOW_KEY)
        log.info("microsoft_todo: authorised as %s", account or "unknown account")
        return {"state": "authorized", "account": account}

    async def _token_request(self, payload: dict[str, Any], tolerate_pending: bool) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.post(self.token_url, data=payload)
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code >= 400 and not tolerate_pending:
                raise AuthRequiredError(
                    f"microsoft_todo: token endpoint error {response.status_code}: "
                    f"{body.get('error_description') or response.text[:200]}"
                )
            return body

    @staticmethod
    def _account_from_id_token(id_token: str | None) -> Optional[str]:
        if not id_token:
            return None
        try:
            payload = id_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return claims.get("preferred_username") or claims.get("upn") or claims.get("email")
        except Exception:  # pragma: no cover - malformed token from upstream
            return None

    # ---------------------------------------------------------------- refresh
    async def _refresh(self, force: bool = False) -> str:
        tokens = self._tokens()
        access = tokens.get("access_token")
        if access and not force and float(tokens.get("expires_at") or 0) > time.time():
            return access
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise AuthRequiredError(
                "microsoft_todo: no refresh token — run the device-code flow "
                "(POST /api/auth/ms/device/start)"
            )
        body = await self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": self.settings.ms_client_id,
                "refresh_token": refresh_token,
                "scope": " ".join(self.settings.scope_list),
            },
            tolerate_pending=False,
        )
        if not body.get("access_token"):
            self.forget_tokens()
            raise AuthRequiredError(
                "microsoft_todo: refresh rejected ("
                + str(body.get("error_description") or body.get("error") or "unknown")
                + ") — re-authorise with the device-code flow"
            )
        tokens = self._store_tokens(body)
        return tokens["access_token"]

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._refresh()
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ------------------------------------------------------------- Graph API
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = await self._auth_headers()

        async def on_unauthorized() -> None:
            """Force one token refresh, then let the request layer retry."""
            token = await self._refresh(force=True)
            headers["Authorization"] = f"Bearer {token}"

        return await self.request_json(
            "GET", url, headers=headers, params=params, on_unauthorized=on_unauthorized
        ) or {}

    async def _send(
        self, method: str, url: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """写入 Graph（POST / PATCH）—— 反向同步走这里。"""
        headers = await self._auth_headers()
        headers["Content-Type"] = "application/json"

        async def on_unauthorized() -> None:
            """Force one token refresh, then let the request layer retry."""
            token = await self._refresh(force=True)
            headers["Authorization"] = f"Bearer {token}"

        return await self.request_json(
            method, url, headers=headers, json=payload, on_unauthorized=on_unauthorized
        ) or {}

    # ------------------------------------------------------------- writes
    async def list_options(self) -> list[dict[str, str]]:
        """给 UI 用的清单下拉：``[{"id": ..., "name": ...}]``。"""
        return [
            {"id": item["id"], "name": item.get("displayName") or "Tasks"}
            for item in await self._lists()
            if item.get("id")
        ]

    async def resolve_list(self, list_id: Optional[str] = None) -> dict[str, Any]:
        """挑一个清单：指定的 > 账号里第一个。"""
        lists = await self._lists()
        if list_id:
            for item in lists:
                if item.get("id") == list_id:
                    return item
            raise ConnectorError(f"microsoft_todo: 找不到清单 {list_id}")
        if not lists:
            raise ConnectorError("microsoft_todo: 这个微软账号里没有任何待办清单")
        return lists[0]

    async def create_task(
        self,
        title: str,
        due: Optional[datetime] = None,
        list_id: Optional[str] = None,
        note: Optional[str] = None,
        importance: Optional[str] = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """在微软待办里新建一条任务，返回 ``(清单, 任务)``。

        带 due 时同时设提醒（To Do 的常规行为），这样手机上真的会响。
        """
        todo_list = await self.resolve_list(list_id)
        base = self.settings.graph_base_url.rstrip("/")
        body: dict[str, Any] = {"title": title}
        if due is not None:
            local = due.astimezone(ZoneInfo(self.settings.timezone))
            stamp = local.replace(tzinfo=None).isoformat(timespec="seconds")
            body["dueDateTime"] = {"dateTime": stamp, "timeZone": self.settings.timezone}
            body["reminderDateTime"] = {"dateTime": stamp, "timeZone": self.settings.timezone}
            body["isReminderOn"] = True
        if note:
            body["body"] = {"content": note, "contentType": "text"}
        if importance in {"low", "normal", "high"}:
            body["importance"] = importance

        task = await self._send("POST", f"{base}/me/todo/lists/{todo_list['id']}/tasks", body)
        log.info(
            "microsoft_todo: created task %s in list %r",
            task.get("id"),
            todo_list.get("displayName"),
        )
        return todo_list, task

    async def set_completed(self, source_id: str, list_id: str, done: bool) -> dict[str, Any]:
        """把某条任务标成完成 / 未完成。

        ``source_id`` 是本地事件的来源 id：``<taskId>`` 或 ``<taskId>#2026-10-20``
        （重复任务展开出的某一次）。
        """
        task_id = source_id.split("#", 1)[0]
        payload: dict[str, Any] = {"status": "completed" if done else "notStarted"}
        if done:
            now = datetime.now(ZoneInfo(self.settings.timezone))
            payload["completedDateTime"] = {
                "dateTime": now.replace(tzinfo=None).isoformat(timespec="seconds"),
                "timeZone": self.settings.timezone,
            }
        base = self.settings.graph_base_url.rstrip("/")
        task = await self._send("PATCH", f"{base}/me/todo/lists/{list_id}/tasks/{task_id}", payload)
        log.info("microsoft_todo: task %s -> %s", task_id, payload["status"])
        return task

    def task_event(
        self, todo_list: dict[str, Any], task: dict[str, Any]
    ) -> Optional[Event]:
        """把刚建好的任务转成本地事件，复用同步时的映射，保证两边长得一样。"""
        horizon = datetime.now(ZoneInfo(self.settings.timezone)) + timedelta(
            days=self.settings.horizon_days
        )
        events = self.normalize_task(task, todo_list, horizon)
        return events[0] if events else None

    async def _paged(self, url: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: Optional[str] = url
        next_params = params
        guard = 0
        while next_url and guard < 50:
            guard += 1
            page = await self._get(next_url, next_params)
            items.extend(page.get("value") or [])
            next_url = page.get("@odata.nextLink")
            next_params = None  # nextLink already carries the query string
            if len(items) >= self.settings.max_events_per_source:
                log.warning("microsoft_todo: pagination cap reached (%d items)", len(items))
                break
        return items

    async def _lists(self) -> list[dict[str, Any]]:
        base = self.settings.graph_base_url.rstrip("/")
        chosen = set(self.settings.list_id_list)
        # NOTE: Graph's To Do RequestBroker rejects *any* ``$select`` on this
        # endpoint with ``400 invalidRequest / RequestBroker--ParseUri`` —
        # verified against the live service (``$top`` alone returns 200 and the
        # full list objects; raw ``$``, ``%24`` and urlencoded variants all 400).
        # So ask for the whole object and pick fields locally.
        lists = await self._paged(f"{base}/me/todo/lists", {"$top": 100})
        if chosen:
            filtered = [item for item in lists if item.get("id") in chosen]
            missing = chosen - {item.get("id") for item in lists}
            if missing:
                log.warning("microsoft_todo: configured list ids not found: %s", ", ".join(sorted(missing)))
            return filtered
        return lists

    # ------------------------------------------------------------------ fetch
    @property
    def enabled(self) -> bool:
        return self.settings.ms_enabled

    async def fetch(self) -> FetchResult:
        base = self.settings.graph_base_url.rstrip("/")
        horizon = utcnow() + timedelta(days=self.settings.horizon_days)
        events: list[Event] = []
        lists = await self._lists()
        per_list: dict[str, int] = {}

        for todo_list in lists:
            list_id = todo_list.get("id")
            if not list_id:
                continue
            # ``$select`` is rejected by the To Do RequestBroker (see ``_lists``),
            # so ask for every field and let the normaliser ignore what it needs.
            params: dict[str, Any] = {"$top": 100}
            if not self.settings.ms_include_completed:
                params["$filter"] = "status ne 'completed'"
            try:
                tasks = await self._paged(f"{base}/me/todo/lists/{list_id}/tasks", params)
            except ConnectorError as exc:
                log.warning("microsoft_todo: list %s failed: %s", list_id, exc)
                continue
            count = 0
            for task in tasks:
                for event in self.normalize_task(task, todo_list, horizon):
                    events.append(event)
                    count += 1
            per_list[todo_list.get("displayName") or list_id] = count

        detail = {
            "lists": per_list,
            "events": len(events),
            "horizon_days": self.settings.horizon_days,
            "account": self.auth_state().get("account"),
        }
        return FetchResult(events=events, detail=detail)

    async def status(self) -> dict[str, Any]:
        state = self.auth_state()
        state["enabled"] = self.enabled
        state["lists"] = self.settings.list_id_list or "all"
        return state

    # -------------------------------------------------------------- mapping
    def normalize_task(
        self, task: dict[str, Any], todo_list: dict[str, Any], horizon: datetime
    ) -> list[Event]:
        due = parse_graph_datetime(task.get("dueDateTime"))
        if due is None and not self.settings.ms_include_undue:
            return []
        task_id = task.get("id") or ""
        if not task_id:
            return []

        anchor = due or parse_graph_datetime(task.get("createdDateTime")) or utcnow()
        reminder = parse_graph_datetime(task.get("reminderDateTime"))
        reminder_minutes = (
            max(0, int((as_aware(anchor) - as_aware(reminder)).total_seconds() // 60))
            if reminder
            else None
        )
        status = (
            EventStatus.completed.value
            if (task.get("status") or "").lower() == "completed"
            else EventStatus.pending.value
        )
        completed_at = parse_graph_datetime(task.get("completedDateTime"))
        priority = IMPORTANCE_PRIORITY.get((task.get("importance") or "normal").lower(), 5)
        description = _plain_text(task.get("body"))
        list_name = todo_list.get("displayName")
        updated_at = parse_graph_datetime(task.get("lastModifiedDateTime")) or utcnow()

        def build(source_id: str, when: datetime, note: Optional[str] = None) -> Event:
            return Event(
                id=make_event_id(Source.microsoft_todo, source_id),
                source=Source.microsoft_todo.value,
                source_id=source_id,
                title=task.get("title") or "(untitled task)",
                description=note or description,
                start_time=when,
                end_time=None,
                is_deadline=True,
                location=list_name,
                status=status,
                priority=priority,
                reminder_minutes=reminder_minutes,
                all_day=False,
                updated_at=updated_at,
                completed_at=completed_at,
                raw=json.dumps(
                    {
                        "list": list_name,
                        "listId": todo_list.get("id"),
                        "importance": task.get("importance"),
                        "recurrence": task.get("recurrence"),
                    },
                    ensure_ascii=False,
                ),
            )

        occurrences = expand_recurrence(anchor, task.get("recurrence"), horizon)
        if not occurrences:
            return [build(task_id, anchor)]
        out: list[Event] = []
        for index, when in enumerate(occurrences):
            uid = task_id if index == 0 else f"{task_id}#{when.date().isoformat()}"
            note = description
            if index == 0 and task.get("recurrence"):
                note = " ".join(filter(None, [description, "(recurring series)"]))
            out.append(build(uid, when, note))
        return out


# --------------------------------------------------------------- recurrence
def expand_recurrence(
    anchor: datetime, recurrence: dict[str, Any] | None, horizon: datetime
) -> list[datetime]:
    """Expand a Graph ``patternedRecurrence`` into concrete UTC datetimes.

    Returns ``[]`` when the task does not recur or nothing falls inside the
    horizon. Bounded by :data:`MAX_OCCURRENCES` to protect the database from a
    unbounded daily task.
    """
    if not recurrence:
        return []
    pattern = recurrence.get("pattern") or {}
    rng = recurrence.get("range") or {}
    kind = (pattern.get("type") or "").lower()
    if not kind:
        return []

    start_aware = as_aware(anchor)
    assert start_aware is not None
    local = start_aware.astimezone(_tz_from(rng.get("recurrenceTimeZone") or "UTC"))
    interval = max(1, int(pattern.get("interval") or 1))
    time_of_day = local.timetz()

    range_start = rng.get("startDate")
    if range_start:
        try:
            start_date = date.fromisoformat(str(range_start)[:10])
        except ValueError:
            start_date = local.date()
        if start_date > local.date():
            local = datetime.combine(start_date, local.timetz().replace(tzinfo=local.tzinfo))
    end_limit: Optional[date] = None
    wants_max = rng.get("numberOfOccurrences")
    if (rng.get("type") or "").lower() == "enddate" and rng.get("endDate"):
        try:
            end_limit = date.fromisoformat(str(rng["endDate"])[:10])
        except ValueError:
            end_limit = None

    def emit() -> Iterable[datetime]:
        if kind == "daily":
            day = local.date()
            while True:
                yield datetime.combine(day, time_of_day).astimezone(UTC)
                day += timedelta(days=interval)

        elif kind == "weekly":
            days = [d.lower() for d in (pattern.get("daysOfWeek") or []) if d]
            indexes = sorted(WEEKDAY_INDEX[d] for d in days if d in WEEKDAY_INDEX) or [local.weekday()]
            week_start = local.date() - timedelta(days=local.weekday())
            while True:
                for idx in indexes:
                    day = week_start + timedelta(days=idx)
                    if day >= local.date():
                        yield datetime.combine(day, time_of_day).astimezone(UTC)
                week_start += timedelta(weeks=interval)

        elif kind in {"absolutemonthly", "monthly"}:
            day = int(pattern.get("dayOfMonth") or local.day)
            year, month = local.year, local.month
            while True:
                last = calendar.monthrange(year, month)[1]
                if local.date() <= date(year, month, min(day, last)):
                    yield datetime.combine(
                        date(year, month, min(day, last)), time_of_day
                    ).astimezone(UTC)
                month += interval
                year, month = year + (month - 1) // 12, (month - 1) % 12 + 1

        elif kind == "relativemonthly":
            days = [d.lower() for d in (pattern.get("daysOfWeek") or []) if d]
            wanted = WEEKDAY_INDEX[days[0]] if days and days[0] in WEEKDAY_INDEX else local.weekday()
            which = RELATIVE_INDEX.get((pattern.get("index") or "first").lower(), 0)
            year, month = local.year, local.month
            while True:
                day = _nth_weekday(year, month, wanted, which)
                if day and local.date() <= day:
                    yield datetime.combine(day, time_of_day).astimezone(UTC)
                month += interval
                year, month = year + (month - 1) // 12, (month - 1) % 12 + 1

        elif kind in {"absoluteyearly", "yearly"}:
            month = int(pattern.get("month") or local.month)
            day = int(pattern.get("dayOfMonth") or local.day)
            year = local.year
            while True:
                last = calendar.monthrange(year, month)[1]
                if local.date() <= date(year, month, min(day, last)):
                    yield datetime.combine(
                        date(year, month, min(day, last)), time_of_day
                    ).astimezone(UTC)
                year += interval

        else:  # pragma: no cover - unknown pattern type
            return

    out: list[datetime] = []
    for when in emit():
        if when > horizon:
            break
        out.append(when)
        if len(out) >= (int(wants_max) if wants_max else MAX_OCCURRENCES):
            break
        if end_limit and when.date() > end_limit:
            out.pop()
            break
    return out


def _nth_weekday(year: int, month: int, weekday: int, which: int) -> Optional[date]:
    days = [
        d
        for d in range(1, calendar.monthrange(year, month)[1] + 1)
        if date(year, month, d).weekday() == weekday
    ]
    if not days:
        return None
    index = which if which >= 0 else len(days) + which
    return date(year, month, days[index]) if 0 <= index < len(days) else None


def _tz_from(name: str):
    from ..timeutil import get_tz

    try:
        return get_tz(name)
    except Exception:  # pragma: no cover
        return UTC
