"""Meteora DLMM public data API: pool list, single pool, 5m candles. Parsers are pure."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from ..http import SourceError, TTLCache, request_json
from ..metrics import Candle, fee_yield
from ..settings import SOL_MINT

BASE = "https://dlmm.datapi.meteora.ag"
POOLS_TTL = 120.0
CANDLES_TTL = 300.0
WINDOW_SECONDS = 8 * 3600  # 96 five-minute candles (+1 inclusive end) -> under the 100 cap
WINDOWS = 3


@dataclass(frozen=True)
class Token:
    address: str
    symbol: str
    freeze_disabled: bool | None


@dataclass(frozen=True)
class Pool:
    address: str
    name: str
    token_x: Token
    token_y: Token
    bin_step: int
    tvl: float
    volume_24h: float
    fees_24h: float | None
    protocol_fees_24h: float | None
    created_at: int | None  # unix seconds
    blacklisted: bool

    @property
    def target(self) -> Token | None:
        """The non-SOL side, or None when SOL is on neither side."""
        if self.token_y.address == SOL_MINT:
            return self.token_x
        if self.token_x.address == SOL_MINT:
            return self.token_y
        return None

    @property
    def fee_yield(self) -> float | None:
        return fee_yield(self.fees_24h, self.protocol_fees_24h, self.tvl)

    def age_days(self, now: int) -> float | None:
        return None if not self.created_at else max((now - self.created_at) / 86400, 0.0)


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _token(raw: dict[str, Any]) -> Token:
    return Token(
        address=str(raw.get("address") or ""),
        symbol=str(raw.get("symbol") or ""),
        freeze_disabled=raw.get("freeze_authority_disabled"),
    )


def parse_pool(raw: dict[str, Any]) -> Pool:
    created = _f(raw.get("created_at"))
    if created and created > 10_000_000_000:  # milliseconds
        created /= 1000
    window = raw.get("volume") or {}
    return Pool(
        address=str(raw.get("address") or ""),
        name=str(raw.get("name") or ""),
        token_x=_token(raw.get("token_x") or {}),
        token_y=_token(raw.get("token_y") or {}),
        bin_step=int((raw.get("pool_config") or {}).get("bin_step") or 0),
        tvl=_f(raw.get("tvl")) or 0.0,
        volume_24h=_f(window.get("24h")) or 0.0,
        fees_24h=_f((raw.get("fees") or {}).get("24h")),
        protocol_fees_24h=_f((raw.get("protocol_fees") or {}).get("24h")),
        created_at=int(created) if created else None,
        blacklisted=bool(raw.get("is_blacklisted")),
    )


def parse_pools_page(payload: dict[str, Any]) -> tuple[list[Pool], int]:
    pools = [parse_pool(p) for p in payload.get("data") or [] if isinstance(p, dict) and p.get("address")]
    return pools, int(payload.get("pages") or 1)


def parse_candles(payload: dict[str, Any]) -> list[Candle]:
    out: list[Candle] = []
    for row in payload.get("data") or []:
        try:
            out.append(
                Candle(ts=int(row["timestamp"]), close=float(row["close"]), volume=float(row["volume"] or 0))
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


class MeteoraClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._pools_cache = TTLCache(POOLS_TTL)
        self._candles_cache = TTLCache(CANDLES_TTL)
        self._sem = asyncio.Semaphore(4)

    async def get_pools(self, pages: int) -> list[Pool]:
        key = f"pools:{pages}"
        cached = self._pools_cache.get(key)
        if cached is not None:
            return list(cached)
        pools: list[Pool] = []
        for page in range(1, pages + 1):
            payload = await request_json(
                self._client, "meteora_pools", "GET", f"{BASE}/pools",
                params={"page": page, "page_size": 50, "sort_by": "volume_24h:desc"},
            )
            batch, total_pages = parse_pools_page(payload)
            pools.extend(batch)
            if page >= total_pages or not batch:
                break
        self._pools_cache.set(key, pools)
        return pools

    async def get_pool(self, address: str) -> Pool:
        payload = await request_json(self._client, "meteora_pools", "GET", f"{BASE}/pools/{address}")
        if not isinstance(payload, dict) or not payload.get("address"):
            raise SourceError("meteora_pools", "pool tidak ditemukan")
        return parse_pool(payload)

    async def get_candles(self, address: str, now: int) -> list[Candle]:
        """24h of 5m candles in three 8h windows (the API caps ~100 candles per request)."""
        cached = self._candles_cache.get(address)
        if cached is not None:
            return list(cached)

        async def window(i: int) -> list[Candle]:
            end = now - (WINDOWS - 1 - i) * WINDOW_SECONDS
            async with self._sem:
                payload = await request_json(
                    self._client, "meteora_ohlcv", "GET", f"{BASE}/pools/{address}/ohlcv",
                    params={"timeframe": "5m", "start_time": end - WINDOW_SECONDS, "end_time": end},
                )
            return parse_candles(payload)

        parts = await asyncio.gather(*[window(i) for i in range(WINDOWS)])
        candles = [c for part in parts for c in part]
        self._candles_cache.set(address, candles)
        return candles
