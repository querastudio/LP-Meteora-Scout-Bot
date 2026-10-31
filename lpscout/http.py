"""HTTP helper: timeout, retry with backoff on 429/5xx/transport errors, and a small TTL cache."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

DEFAULT_TIMEOUT = 10.0
MAX_RETRY_AFTER = 5.0


class SourceError(Exception):
    """A data source failed after retries."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source


class TTLCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        stored_at, value = item
        if self._clock() - stored_at > self.ttl:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (self._clock(), value)


async def request_json(
    client: httpx.AsyncClient,
    source: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 3,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Return parsed JSON. Retries 429, 5xx and transport errors with exponential backoff;
    other 4xx fail immediately. Raises SourceError when the source cannot be read."""
    last = "unknown error"
    for attempt in range(retries + 1):
        delay = 0.5 * (2**attempt)
        try:
            r = await client.request(method, url, params=params, json=json, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                retry_after = r.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = min(float(retry_after), MAX_RETRY_AFTER)
            elif r.status_code >= 400:
                raise SourceError(source, f"HTTP {r.status_code}")
            else:
                try:
                    return r.json()
                except ValueError as e:
                    raise SourceError(source, "respons bukan JSON") from e
        except httpx.TransportError as e:  # includes timeouts
            last = type(e).__name__
        if attempt < retries:
            await sleep(delay)
    raise SourceError(source, f"gagal setelah {retries + 1} percobaan ({last})")
