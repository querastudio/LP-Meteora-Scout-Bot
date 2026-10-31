import asyncio

import httpx
import pytest

from lpscout.http import SourceError, TTLCache, request_json


async def no_sleep(_: float) -> None:
    return None


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_retries_429_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429 if len(calls) < 3 else 200, json={"ok": True})

    async def go():
        async with client_for(handler) as c:
            return await request_json(c, "x", "GET", "https://e/x", sleep=no_sleep)

    assert run(go()) == {"ok": True} and len(calls) == 3


def test_gives_up_after_retries_on_5xx():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    async def go():
        async with client_for(handler) as c:
            await request_json(c, "src", "GET", "https://e/x", retries=2, sleep=no_sleep)

    with pytest.raises(SourceError) as e:
        run(go())
    assert e.value.source == "src" and len(calls) == 3


def test_4xx_fails_fast_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    async def go():
        async with client_for(handler) as c:
            await request_json(c, "src", "GET", "https://e/x", sleep=no_sleep)

    with pytest.raises(SourceError):
        run(go())
    assert len(calls) == 1


def test_timeout_is_retried_and_reported():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    async def go():
        async with client_for(handler) as c:
            await request_json(c, "src", "GET", "https://e/x", retries=1, sleep=no_sleep)

    with pytest.raises(SourceError, match="ReadTimeout"):
        run(go())


def test_non_json_body_is_a_source_error():
    async def go():
        async with client_for(lambda r: httpx.Response(200, text="<html>")) as c:
            await request_json(c, "src", "GET", "https://e/x", sleep=no_sleep)

    with pytest.raises(SourceError):
        run(go())


def test_ttl_cache_expires():
    now = [0.0]
    cache = TTLCache(10, clock=lambda: now[0])
    cache.set("k", 1)
    now[0] = 9
    assert cache.get("k") == 1
    now[0] = 11
    assert cache.get("k") is None
