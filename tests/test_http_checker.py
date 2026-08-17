from __future__ import annotations

import httpx
import pytest

from mdcheck.http_checker import HttpChecker
from mdcheck.models import Link, LinkType, Status


async def _noop_sleep(_delay: float) -> None:
    return None


def _link(url: str, line: int = 1) -> Link:
    return Link(
        source_file="f.md",
        line=line,
        link_text="text",
        original_target=url,
        normalized_target=url,
        link_type=LinkType.HTTPS,
    )


def _checker(handler, *, retries: int = 1, workers: int = 10) -> HttpChecker:
    transport = httpx.MockTransport(handler)
    return HttpChecker(
        timeout=1,
        workers=workers,
        retries=retries,
        user_agent="mdcheck-test",
        transport=transport,
        sleep_fn=_noop_sleep,
    )


@pytest.mark.asyncio
async def test_200_is_ok():
    def handler(request):
        return httpx.Response(200)

    checker = _checker(handler)
    results = await checker.check_links([_link("https://x.test/ok")])
    assert results[0].status == Status.OK
    assert results[0].http_status == 200


@pytest.mark.asyncio
async def test_204_is_ok():
    def handler(request):
        return httpx.Response(204)

    checker = _checker(handler)
    results = await checker.check_links([_link("https://x.test/nocontent")])
    assert results[0].status == Status.OK
    assert results[0].http_status == 204


@pytest.mark.asyncio
async def test_redirect_to_200_is_ok():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://x.test/end"})
        return httpx.Response(200)

    checker = _checker(handler)
    results = await checker.check_links([_link("https://x.test/start")])
    assert results[0].status == Status.OK
    assert results[0].final_url == "https://x.test/end"


@pytest.mark.asyncio
async def test_redirect_loop_is_error():
    def handler(request):
        return httpx.Response(302, headers={"location": str(request.url)})

    checker = _checker(handler)
    results = await checker.check_links([_link("https://x.test/loop")])
    assert results[0].status == Status.ERROR


@pytest.mark.asyncio
async def test_401_is_warning():
    def handler(request):
        return httpx.Response(401)

    checker = _checker(handler)
    results = await checker.check_links([_link("https://x.test/auth")])
    assert results[0].status == Status.WARNING
    assert results[0].http_status == 401


@pytest.mark.asyncio
async def test_403_is_warning():
    def handler(request):
        return httpx.Response(403)

    checker = _checker(handler)
    results = await checker.check_links([_link("https://x.test/forbidden")])
    assert results[0].status == Status.WARNING


@pytest.mark.asyncio
async def test_404_is_broken():
    def handler(request):
        return httpx.Response(404)

    checker = _checker(handler)
    results = await checker.check_links([_link("https://x.test/missing")])
    assert results[0].status == Status.BROKEN
    assert results[0].http_status == 404


@pytest.mark.asyncio
async def test_429_retries_then_warning():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200)

    checker = _checker(handler, retries=1)
    results = await checker.check_links([_link("https://x.test/limited")])
    assert results[0].status == Status.OK
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_429_exhausted_is_warning():
    def handler(request):
        return httpx.Response(429, headers={"retry-after": "0"})

    checker = _checker(handler, retries=1)
    results = await checker.check_links([_link("https://x.test/limited")])
    assert results[0].status == Status.WARNING
    assert results[0].http_status == 429


@pytest.mark.asyncio
async def test_500_is_broken():
    def handler(request):
        return httpx.Response(500)

    checker = _checker(handler, retries=0)
    results = await checker.check_links([_link("https://x.test/error")])
    assert results[0].status == Status.BROKEN


@pytest.mark.asyncio
async def test_timeout_is_timeout_status():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    checker = _checker(handler, retries=0)
    results = await checker.check_links([_link("https://x.test/slow")])
    assert results[0].status == Status.TIMEOUT


@pytest.mark.asyncio
async def test_dns_failure_is_error():
    import socket

    def handler(request):
        raise httpx.ConnectError("dns fail", request=request) from socket.gaierror()

    checker = _checker(handler, retries=0)
    results = await checker.check_links([_link("https://nonexistent.invalid/")])
    assert results[0].status == Status.ERROR
    assert "DNS" in results[0].message


@pytest.mark.asyncio
async def test_tls_failure_is_error():
    import ssl

    def handler(request):
        raise httpx.ConnectError("tls fail", request=request) from ssl.SSLError()

    checker = _checker(handler, retries=0)
    results = await checker.check_links([_link("https://x.test/tls")])
    assert results[0].status == Status.ERROR
    assert "TLS" in results[0].message


@pytest.mark.asyncio
async def test_head_405_falls_back_to_get():
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200)

    checker = _checker(handler, retries=0)
    results = await checker.check_links([_link("https://x.test/head-unsupported")])
    assert results[0].status == Status.OK
    assert calls == ["HEAD", "GET"]


@pytest.mark.asyncio
async def test_head_404_falls_back_to_get():
    # Regression: some servers (e.g. Figma) answer HEAD with 404 while GET
    # succeeds, not just the 405/501 cases the spec calls out explicitly.
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(404)
        return httpx.Response(200)

    checker = _checker(handler, retries=0)
    results = await checker.check_links([_link("https://x.test/head-lies")])
    assert results[0].status == Status.OK
    assert calls == ["HEAD", "GET"]


@pytest.mark.asyncio
async def test_duplicate_url_requested_once():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200)

    checker = _checker(handler, retries=0)
    links = [_link("https://x.test/dup", line=1), _link("https://x.test/dup", line=2)]
    results = await checker.check_links(links)
    assert calls["n"] == 1
    assert len(results) == 2
    assert all(r.status == Status.OK for r in results)


@pytest.mark.asyncio
async def test_concurrency_limit_respected():
    import asyncio

    max_in_flight = 0
    in_flight = 0
    lock = asyncio.Lock()

    async def slow_response():
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        return httpx.Response(200)

    def handler(request):
        return httpx.Response(200)

    async def async_handler(request):
        return await slow_response()

    transport = httpx.MockTransport(async_handler)
    checker = HttpChecker(
        timeout=2,
        workers=3,
        retries=0,
        user_agent="mdcheck-test",
        transport=transport,
        sleep_fn=_noop_sleep,
    )
    links = [_link(f"https://x.test/{i}", line=i) for i in range(10)]
    results = await checker.check_links(links)

    assert len(results) == 10
    assert max_in_flight <= 3


@pytest.mark.asyncio
async def test_ignore_url_pattern_is_skipped():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    checker = HttpChecker(
        timeout=1,
        workers=5,
        retries=0,
        user_agent="mdcheck-test",
        transport=transport,
        sleep_fn=_noop_sleep,
        ignore_url_patterns=["https://x.test/*"],
    )
    results = await checker.check_links([_link("https://x.test/anything")])
    assert results[0].status == Status.SKIPPED
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_user_agent_and_accept_headers_sent():
    captured = {}

    def handler(request):
        captured["user-agent"] = request.headers.get("user-agent")
        captured["accept"] = request.headers.get("accept")
        return httpx.Response(200)

    checker = _checker(handler, retries=0)
    await checker.check_links([_link("https://x.test/headers")])
    assert captured["user-agent"] == "mdcheck-test"
    assert "text/html" in captured["accept"]


@pytest.mark.asyncio
async def test_no_cookies_or_auth_sent():
    captured = {}

    def handler(request):
        captured["cookie"] = request.headers.get("cookie")
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200)

    checker = _checker(handler, retries=0)
    await checker.check_links([_link("https://x.test/headers")])
    assert captured["cookie"] is None
    assert captured["authorization"] is None
