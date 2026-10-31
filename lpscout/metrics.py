"""Pure pool metrics from 24h of candles (no I/O)."""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

BUCKET_SECONDS = 900  # 15 minutes
BUCKETS_PER_DAY = 96
MIN_CANDLES = 16  # fewer 15m candles than this -> candle-derived metrics are null
BAD_PRINT_DEVIATION = 0.70
SIX_HOURS_BUCKETS = 24


@dataclass(frozen=True)
class Candle:
    ts: int  # unix seconds, start of the candle
    close: float
    volume: float  # USD


@dataclass(frozen=True)
class Metrics:
    fee_yield: float | None  # (fees - protocol fees) / TVL, per day
    sigma_daily: float | None
    lvr: float | None
    net_edge: float | None
    fee_lvr: float | None
    activity: float | None
    concentration: float | None
    pace6h: float | None
    candles_15m: int
    bad_prints: int


def window_start(now: int) -> int:
    """Start of the 96-bucket (24h) window whose last bucket contains `now`."""
    return (now // BUCKET_SECONDS - (BUCKETS_PER_DAY - 1)) * BUCKET_SECONDS


def fee_yield(fees_24h: float | None, protocol_fees_24h: float | None, tvl: float | None) -> float | None:
    if fees_24h is None or not tvl or tvl <= 0:
        return None
    return (fees_24h - (protocol_fees_24h or 0.0)) / tvl


def aggregate_15m(candles: Iterable[Candle], now: int) -> list[Candle]:
    """Merge 5m candles into the 96 fifteen-minute buckets ending at the bucket containing `now`.

    A bucket's close is its last 5m close and its volume the sum. Duplicate timestamps (window
    borders) are de-duplicated; candles with a non-positive/invalid close are dropped.
    """
    t0 = window_start(now)
    unique: dict[int, Candle] = {}
    for c in candles:
        if c.close is None or not math.isfinite(c.close) or c.close <= 0:
            continue
        unique[c.ts] = c
    buckets: dict[int, list[Candle]] = {}
    for ts in sorted(unique):
        k = (ts - t0) // BUCKET_SECONDS
        if 0 <= k < BUCKETS_PER_DAY:
            buckets.setdefault(k, []).append(unique[ts])
    return [
        Candle(
            ts=t0 + k * BUCKET_SECONDS,
            close=xs[-1].close,
            volume=sum(max(x.volume or 0.0, 0.0) for x in xs),
        )
        for k, xs in sorted(buckets.items())
    ]


def clean_bad_prints(candles: list[Candle]) -> tuple[list[Candle], int]:
    """Replace a candle whose close deviates > 70% from BOTH neighbours by the neighbours' mean."""
    out = list(candles)
    fixed = 0
    for i in range(1, len(candles) - 1):
        prev_c, cur, next_c = candles[i - 1].close, candles[i].close, candles[i + 1].close
        if abs(cur / prev_c - 1) > BAD_PRINT_DEVIATION and abs(cur / next_c - 1) > BAD_PRINT_DEVIATION:
            out[i] = Candle(ts=candles[i].ts, close=(prev_c + next_c) / 2, volume=candles[i].volume)
            fixed += 1
    return out, fixed


def compute_metrics(
    candles_5m: Iterable[Candle],
    fees_24h: float | None,
    protocol_fees_24h: float | None,
    tvl: float | None,
    now: int,
) -> Metrics:
    fy = fee_yield(fees_24h, protocol_fees_24h, tvl)
    c15, bad = clean_bad_prints(aggregate_15m(candles_5m, now))
    if len(c15) < MIN_CANDLES:
        return Metrics(fy, None, None, None, None, None, None, None, len(c15), bad)

    returns = [math.log(c15[i].close / c15[i - 1].close) for i in range(1, len(c15))]
    sigma = statistics.stdev(returns) * math.sqrt(BUCKETS_PER_DAY)
    lvr = sigma**2 / 8

    volumes = [c.volume for c in c15]
    total = sum(volumes)
    cutoff = window_start(now) + (BUCKETS_PER_DAY - SIX_HOURS_BUCKETS) * BUCKET_SECONDS
    last6 = sum(c.volume for c in c15 if c.ts >= cutoff)
    return Metrics(
        fee_yield=fy,
        sigma_daily=sigma,
        lvr=lvr,
        net_edge=None if fy is None else fy - lvr,
        fee_lvr=fy / lvr if fy is not None and lvr > 0 else None,
        activity=sum(1 for v in volumes if v > 0) / BUCKETS_PER_DAY,
        concentration=max(volumes) / total if total > 0 else None,
        pace6h=last6 * 4 / total if total > 0 else None,
        candles_15m=len(c15),
        bad_prints=bad,
    )

