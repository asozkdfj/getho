"""Minimal JSON-over-HTTPS client with timeouts, retries and request spacing.

stdlib only (urllib) so the worker image needs no extra HTTP dependency. The
transport is injectable so provider tests run against recorded payloads with
no network access.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """The provider refused or failed the request (not retried any further)."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


# (url, headers, timeout_seconds) -> HttpResponse
Transport = Callable[[str, Mapping[str, str], float], HttpResponse]


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return HttpResponse(
                resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
            )
    except urllib.error.HTTPError as exc:  # non-2xx still carries a body worth reading
        return HttpResponse(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())


class JsonHttpClient:
    def __init__(
        self,
        base_url: str,
        headers: Mapping[str, str],
        *,
        transport: Transport = urllib_transport,
        timeout: float = 15.0,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        min_interval_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("provider base_url must use https")
        self._base_url = base_url.rstrip("/")
        self._headers = dict(headers)  # may contain credentials: never logged
        self._transport = transport
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._min_interval = min_interval_seconds
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self.requests_made = 0

    def __repr__(self) -> str:  # keep credentials out of reprs/tracebacks
        return f"JsonHttpClient(base_url={self._base_url!r})"

    def _throttle(self) -> None:
        if self._last_request_at is None or self._min_interval <= 0:
            return
        wait = self._min_interval - (self._clock() - self._last_request_at)
        if wait > 0:
            self._sleep(wait)

    def get(
        self, path: str, params: Mapping[str, Any] | None = None
    ) -> tuple[Any, Mapping[str, str]]:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self._base_url}{path}" + (f"?{query}" if query else "")
        last_error = "no attempt made"
        for attempt in range(1, self._max_attempts + 1):
            self._throttle()
            self._last_request_at = self._clock()
            self.requests_made += 1
            try:
                resp = self._transport(url, self._headers, self._timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status in RETRYABLE_STATUS:
                    last_error = f"HTTP {resp.status}"
                elif resp.status >= 400:
                    raise ProviderError(f"GET {path} failed with HTTP {resp.status}")
                else:
                    try:
                        return json.loads(resp.body), resp.headers
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"GET {path} returned invalid JSON") from exc
            if attempt < self._max_attempts:
                delay = self._backoff * 2 ** (attempt - 1)
                logger.warning(
                    "GET %s attempt %d failed (%s); retry in %.1fs",
                    path,
                    attempt,
                    last_error,
                    delay,
                )
                self._sleep(delay)
        raise ProviderError(f"GET {path} failed after {self._max_attempts} attempts: {last_error}")
