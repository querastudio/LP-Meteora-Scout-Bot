"""Scan orchestration: prefilter (cheap) -> top-N by Fee/TVL -> candles -> metrics -> label -> security."""
from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .http import SourceError
from .labels import Evaluation, evaluate, is_recommended
from .metrics import Candle, Metrics, compute_metrics
from .settings import SIZE_PCT, Settings
from .sources.meteora import Pool
from .sources.security import SecurityResult


class PoolSource(Protocol):
    async def get_pools(self, pages: int) -> list[Pool]: ...
    async def get_pool(self, address: str) -> Pool: ...
    async def get_candles(self, address: str, now: int) -> list[Candle]: ...


class SecuritySource(Protocol):
    async def check(
        self, mint: str, meteora_freeze_disabled: bool | None, max_top10_pct: float
    ) -> SecurityResult: ...


@dataclass
class ScanOutcome:
    pools_scanned: int
    candidates: int
    results: list[dict[str, Any]]
    failed: dict[str, int] = field(default_factory=dict)


def prefilter_reason(pool: Pool, settings: Settings) -> str | None:
    """Why a pool is excluded before any candle is fetched, or None when it passes."""
    th = settings.thresholds
    target = pool.target
    if pool.blacklisted:
        return "masuk blacklist"
    if target is None:
        return "tidak berpasangan dengan SOL"
    if target.symbol.upper() in settings.excluded_symbols:
        return f"aset dikecualikan ({target.symbol})"
    if pool.bin_step < th.min_bin_step:
        return f"bin step {pool.bin_step} < {th.min_bin_step}"
    if pool.tvl < th.min_tvl:
        return f"TVL ${pool.tvl:,.0f} < ${th.min_tvl:,.0f}"
    return None


def result_dict(pool: Pool, metrics: Metrics, ev: Evaluation, sec: SecurityResult, now: int,
                note: str | None = None) -> dict[str, Any]:
    target = pool.target
    recommended = is_recommended(ev.label, sec.status)
    return {
        "address": pool.address,
        "name": pool.name,
        "target_symbol": target.symbol if target else "",
        "target_mint": target.address if target else "",
        "bin_step": pool.bin_step,
        "tvl": pool.tvl,
        "age_days": pool.age_days(now),
        "metrics": dataclasses.asdict(metrics),
        "label": ev.label,
        "rank": ev.rank,
        "missing": list(ev.missing),
        "security": {
            "status": sec.status, "reasons": list(sec.reasons), "top10_pct": sec.top10_pct,
            "notes": list(sec.notes),
        },
        "recommended": recommended,
        "effective_label": ev.label if recommended else "tolak",
        "size_pct": SIZE_PCT[ev.label] if recommended else 0,
        "note": note,
    }


NOT_CHECKED = SecurityResult("belum terverifikasi", ("belum dicek",))


class Scanner:
    def __init__(self, pools: PoolSource, security: SecuritySource, settings: Settings) -> None:
        self._pools = pools
        self._security = security
        self._settings = settings
        self._sec_sem = asyncio.Semaphore(3)

    async def scan(self, now: int | None = None, extra_addresses: Iterable[str] = ()) -> ScanOutcome:
        """`extra_addresses` (pools currently on the active list) are always re-evaluated so a pool
        that stopped qualifying is noticed even when it is no longer in the top-N."""
        now = int(time.time()) if now is None else now
        failed: dict[str, int] = {}
        s = self._settings
        pools = await self._pools.get_pools(s.scan_pages)  # a failure here aborts the scan

        passing = [p for p in pools if prefilter_reason(p, s) is None]
        passing.sort(key=lambda p: -1.0 if p.fee_yield is None else p.fee_yield, reverse=True)
        chosen = passing[: s.thresholds.top_n]
        chosen_addrs = {p.address for p in chosen}

        by_addr = {p.address: p for p in pools}
        extras: list[Pool] = []
        for addr in extra_addresses:
            if addr in chosen_addrs:
                continue
            pool = by_addr.get(addr)
            if pool is None:
                try:
                    pool = await self._pools.get_pool(addr)
                except SourceError as e:
                    _count(failed, e.source)
                    continue
            extras.append(pool)

        tasks = [self._evaluate(p, now, failed) for p in chosen + extras]
        results = list(await asyncio.gather(*tasks))
        results.sort(key=lambda r: (-r["rank"], -(r["metrics"]["fee_yield"] or 0.0)))
        return ScanOutcome(len(pools), len(chosen), results, failed)

    async def inspect(self, address: str, now: int | None = None) -> ScanOutcome:
        """Full evaluation of one pool for /pool, including security even when the label is tolak."""
        now = int(time.time()) if now is None else now
        failed: dict[str, int] = {}
        pool = await self._pools.get_pool(address)
        result = await self._evaluate(pool, now, failed, always_security=True)
        return ScanOutcome(1, 1, [result], failed)

    async def _evaluate(self, pool: Pool, now: int, failed: dict[str, int],
                        always_security: bool = False) -> dict[str, Any]:
        s = self._settings
        reason = prefilter_reason(pool, s)
        candles: list[Candle] = []
        if reason is None or always_security:
            try:
                candles = await self._pools.get_candles(pool.address, now)
            except SourceError as e:
                _count(failed, e.source)
        metrics = compute_metrics(candles, pool.fees_24h, pool.protocol_fees_24h, pool.tvl, now)
        ev = evaluate(metrics, s.thresholds)
        if reason is not None:
            ev = Evaluation("tolak", 0, (f"penyaringan: {reason}",) + ev.missing)

        sec = NOT_CHECKED
        target = pool.target
        if target is not None and (ev.rank >= 1 or always_security):
            async with self._sec_sem:
                sec = await self._security.check(target.address, target.freeze_disabled,
                                                 s.thresholds.max_top10_pct)
            for src in sec.failed_sources:
                _count(failed, src)
        return result_dict(pool, metrics, ev, sec, now, note=reason)


def _count(failed: dict[str, int], source: str) -> None:
    failed[source] = failed.get(source, 0) + 1
