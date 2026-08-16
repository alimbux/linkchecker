"""Asynchronous HTTP/HTTPS link validation with retries and redirects."""

from __future__ import annotations

import asyncio
import datetime
import fnmatch
import re
import socket
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx

from mdcheck.models import Link, LinkResult, Status

MAX_REDIRECTS = 5
MAX_BODY_BYTES = 64 * 1024
BACKOFF_BASE = 0.2
MAX_BACKOFF = 5.0
DEFAULT_ACCEPT = "text/html,application/xhtml+xml,*/*"


@dataclass
class _Outcome:
    status: Status
    http_status: int | None = None
    message: str | None = None
    final_url: str | None = None
    elapsed_ms: float | None = None
    retryable: bool = False
    retry_after: float | None = None


def url_matches_ignore(url: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(url, pattern):
            return True
        try:
            if re.search(pattern, url):
                return True
        except re.error:
            continue
    return False


def _parse_retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    value = value.strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    delta = (dt - datetime.datetime.now(datetime.UTC)).total_seconds()
    return max(delta, 0.0)


def _classify_response(resp: httpx.Response) -> _Outcome:
    code = resp.status_code
    final_url = str(resp.url)
    if 200 <= code < 400:
        return _Outcome(Status.OK, http_status=code, final_url=final_url)
    if code in (401, 403):
        return _Outcome(
            Status.WARNING,
            http_status=code,
            final_url=final_url,
            message=resp.reason_phrase or "authentication or access required",
        )
    if code in (404, 410):
        return _Outcome(
            Status.BROKEN,
            http_status=code,
            final_url=final_url,
            message=resp.reason_phrase or "Not Found",
        )
    if code == 429:
        return _Outcome(
            Status.WARNING,
            http_status=code,
            final_url=final_url,
            message="Too Many Requests",
            retryable=True,
            retry_after=_parse_retry_after(resp),
        )
    if 400 <= code < 500:
        return _Outcome(
            Status.BROKEN,
            http_status=code,
            final_url=final_url,
            message=resp.reason_phrase or f"HTTP {code}",
        )
    if code in (502, 503, 504):
        return _Outcome(
            Status.BROKEN,
            http_status=code,
            final_url=final_url,
            message=resp.reason_phrase or f"HTTP {code}",
            retryable=True,
            retry_after=_parse_retry_after(resp),
        )
    if 500 <= code < 600:
        return _Outcome(
            Status.BROKEN,
            http_status=code,
            final_url=final_url,
            message=resp.reason_phrase or f"HTTP {code}",
        )
    return _Outcome(
        Status.ERROR,
        http_status=code,
        final_url=final_url,
        message=f"unexpected status code {code}",
    )


def _classify_exception(exc: Exception) -> _Outcome:
    if isinstance(exc, httpx.TooManyRedirects):
        return _Outcome(Status.ERROR, message="redirect limit exceeded or redirect loop")
    if isinstance(exc, httpx.TimeoutException):
        return _Outcome(Status.TIMEOUT, message="request timed out", retryable=True)
    if isinstance(exc, httpx.ConnectError):
        cause = exc.__cause__ or exc.__context__
        if isinstance(cause, socket.gaierror):
            return _Outcome(Status.ERROR, message="DNS resolution failed", retryable=True)
        if isinstance(cause, ssl.SSLError):
            return _Outcome(Status.ERROR, message=f"TLS error: {cause}")
        text = str(exc).lower()
        if "ssl" in text or "certificate" in text:
            return _Outcome(Status.ERROR, message=f"TLS error: {exc}")
        return _Outcome(Status.ERROR, message=f"connection error: {exc}", retryable=True)
    transient_network_errors = (
        httpx.RemoteProtocolError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.NetworkError,
    )
    if isinstance(exc, transient_network_errors):
        return _Outcome(Status.ERROR, message=f"network error: {exc}", retryable=True)
    if isinstance(exc, httpx.InvalidURL):
        return _Outcome(Status.INVALID, message="malformed URL")
    if isinstance(exc, httpx.HTTPError):
        return _Outcome(Status.ERROR, message=str(exc) or exc.__class__.__name__)
    return _Outcome(Status.ERROR, message=str(exc) or exc.__class__.__name__)


class HttpChecker:
    def __init__(
        self,
        *,
        timeout: float = 5.0,
        workers: int = 10,
        retries: int = 1,
        user_agent: str = "mdcheck",
        ignore_url_patterns: list[str] | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout = httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout)
        self.workers = max(1, workers)
        self.retries = max(0, retries)
        self.user_agent = user_agent
        self.ignore_url_patterns = ignore_url_patterns or []
        self._sleep = sleep_fn or asyncio.sleep
        self._transport = transport

    async def _get_streamed(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        request = client.build_request("GET", url)
        response = await client.send(request, stream=True)
        try:
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total >= MAX_BODY_BYTES:
                    break
        finally:
            await response.aclose()
        return response

    async def _check_one(self, client: httpx.AsyncClient, url: str) -> _Outcome:
        attempt = 0
        while True:
            start = time.monotonic()
            try:
                resp = await client.head(url)
                if resp.status_code in (405, 501):
                    resp = await self._get_streamed(client, url)
            except httpx.HTTPError as exc:
                outcome = _classify_exception(exc)
            except Exception as exc:  # noqa: BLE001 - one bad URL must not abort the scan
                outcome = _Outcome(Status.ERROR, message=str(exc) or exc.__class__.__name__)
            else:
                outcome = _classify_response(resp)
            outcome.elapsed_ms = (time.monotonic() - start) * 1000

            if outcome.retryable and attempt < self.retries:
                if outcome.retry_after is not None:
                    delay = outcome.retry_after
                else:
                    delay = BACKOFF_BASE * (2**attempt)
                delay = min(delay, MAX_BACKOFF)
                await self._sleep(delay)
                attempt += 1
                continue
            return outcome

    async def check_links(self, links: list[Link]) -> list[LinkResult]:
        if not links:
            return []

        unique_targets: dict[str, list[int]] = {}
        for idx, link in enumerate(links):
            unique_targets.setdefault(link.normalized_target, []).append(idx)

        outcomes: dict[str, _Outcome] = {}
        to_fetch = []
        for url in unique_targets:
            if url_matches_ignore(url, self.ignore_url_patterns):
                outcomes[url] = _Outcome(Status.SKIPPED, message="ignored by --ignore-url pattern")
            else:
                to_fetch.append(url)

        if to_fetch:
            semaphore = asyncio.Semaphore(self.workers)
            limits = httpx.Limits(
                max_connections=self.workers, max_keepalive_connections=self.workers
            )
            headers = {"User-Agent": self.user_agent, "Accept": DEFAULT_ACCEPT}

            async with httpx.AsyncClient(
                timeout=self.timeout,
                limits=limits,
                headers=headers,
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                transport=self._transport,
            ) as client:

                async def worker(url: str) -> None:
                    async with semaphore:
                        outcomes[url] = await self._check_one(client, url)

                await asyncio.gather(*(worker(u) for u in to_fetch))

        results: list[LinkResult | None] = [None] * len(links)
        for url, idxs in unique_targets.items():
            outcome = outcomes[url]
            for idx in idxs:
                results[idx] = LinkResult.from_link(
                    links[idx],
                    outcome.status,
                    http_status=outcome.http_status,
                    message=outcome.message,
                    final_url=outcome.final_url,
                    elapsed_ms=outcome.elapsed_ms,
                )
        return results  # type: ignore[return-value]
