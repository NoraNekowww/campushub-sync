"""Connector framework: error taxonomy, resilient HTTP, and the base contract."""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import httpx

from ..config import Settings, get_settings

log = logging.getLogger("campushub.connectors")


# --------------------------------------------------------------------- errors
class ConnectorError(RuntimeError):
    """Any connector failure. ``retryable`` guides the sync engine."""

    retryable = False


class AuthRequiredError(ConnectorError):
    """No usable credentials — the user must (re)authorise."""

    retryable = False


class UpstreamUnavailable(ConnectorError):
    retryable = True


class RateLimitedError(ConnectorError):
    retryable = True

    def __init__(self, message: str, retry_after: float = 5.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class FetchResult:
    """What a connector returns for one sync pass."""

    events: list[Any] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    name: str = "base"
    label: str = "Base"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return False

    @abstractmethod
    async def fetch(self) -> FetchResult:
        """Return the current state of this source as unified events."""

    async def status(self) -> dict[str, Any]:
        """Cheap, network-free summary used by ``/api/status``."""
        return {"enabled": self.enabled}


class HttpConnector(BaseConnector):
    """Adds a retrying, rate-limit aware ``httpx`` request helper.

    Retries transient failures with exponential backoff + jitter, honours
    ``Retry-After``, and lets subclasses refresh credentials once on HTTP 401.
    """

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.http_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": "CampusHub-Sync/1.0 (+https://nzlab.online)"},
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        on_unauthorized: Optional[Callable[[], Any]] = None,
        accept_status: tuple[int, ...] = (200, 201, 202, 204),
        client: Optional[httpx.AsyncClient] = None,
    ) -> httpx.Response:
        attempts = max(1, self.settings.http_max_retries)
        refreshed = False
        own_client = client is None
        http = client or self._client()
        try:
            for attempt in range(1, attempts + 1):
                try:
                    response = await http.request(
                        method, url, headers=headers, params=params, json=json, data=data
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt >= attempts:
                        raise UpstreamUnavailable(f"{self.name}: {exc}") from exc
                    await self._backoff(attempt, f"network error: {exc}")
                    continue

                if response.status_code in accept_status:
                    return response

                if response.status_code in (401, 403):
                    if on_unauthorized and not refreshed:
                        refreshed = True
                        await _maybe_await(on_unauthorized())
                        continue
                    raise AuthRequiredError(
                        f"{self.name}: upstream rejected credentials "
                        f"(HTTP {response.status_code})"
                    )

                if response.status_code in (429, 503):
                    retry_after = _retry_after(response)
                    if attempt >= attempts:
                        raise RateLimitedError(
                            f"{self.name}: rate limited (HTTP {response.status_code})",
                            retry_after=retry_after,
                        )
                    await self._backoff(attempt, f"HTTP {response.status_code}", retry_after)
                    continue

                if 500 <= response.status_code < 600:
                    if attempt >= attempts:
                        raise UpstreamUnavailable(
                            f"{self.name}: HTTP {response.status_code} {url}"
                        )
                    await self._backoff(attempt, f"HTTP {response.status_code}")
                    continue

                raise ConnectorError(
                    f"{self.name}: HTTP {response.status_code} for {url} — "
                    f"{response.text[:300]}"
                )
            raise UpstreamUnavailable(f"{self.name}: exhausted retries for {url}")
        finally:
            if own_client:
                await http.aclose()

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self.request(method, url, **kwargs)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError(f"{self.name}: invalid JSON from {url}") from exc

    async def _backoff(self, attempt: int, reason: str, retry_after: float | None = None) -> None:
        delay = retry_after if retry_after else min(30.0, 0.8 * 2 ** (attempt - 1))
        delay += random.uniform(0, 0.4)
        log.warning("%s: %s — retrying in %.1fs (attempt %d)", self.name, reason, delay, attempt)
        await asyncio.sleep(delay)


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After")
    if not raw:
        return 0.0
    try:
        return min(120.0, float(raw))
    except ValueError:
        return 5.0


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def describe_dt(value: datetime) -> str:
    return value.astimezone().isoformat(timespec="minutes")


def within_days(value: datetime, days: int, now: Optional[datetime] = None) -> bool:
    reference = now or datetime.now(value.tzinfo)
    return value <= reference + timedelta(days=days)
