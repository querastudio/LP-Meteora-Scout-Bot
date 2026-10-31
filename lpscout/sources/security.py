"""Token security: mint/freeze authority and top-10 holder concentration via Solana RPC,
plus optional RugCheck notes. Pure helpers are separate from the I/O client."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..http import SourceError, TTLCache, request_json

RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"
SECURITY_TTL = 6 * 3600.0
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)  # ValueError on invalid characters
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + body


def is_on_curve(pubkey: bytes) -> bool:
    """True when the 32-byte key is a valid ed25519 point (a wallet); False for PDAs."""
    if len(pubkey) != 32:
        return False
    sign = pubkey[31] >> 7
    y = int.from_bytes(pubkey, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    u = (y * y - 1) % _P
    v = (_D * y * y + 1) % _P
    x2 = u * pow(v, _P - 2, _P) % _P
    if x2 == 0:
        return sign == 0
    return pow(x2, (_P - 1) // 2, _P) == 1


def wallet_is_on_curve(address: str) -> bool | None:
    try:
        return is_on_curve(b58decode(address))
    except ValueError:
        return None


@dataclass(frozen=True)
class SecurityResult:
    status: str  # "ok" | "risiko" | "belum terverifikasi"
    reasons: tuple[str, ...] = ()
    top10_pct: float | None = None
    notes: tuple[str, ...] = ()
    failed_sources: tuple[str, ...] = field(default=())


def parse_authorities(result: dict[str, Any] | None) -> tuple[bool | None, bool | None]:
    """(mint_revoked, freeze_revoked) from a getAccountInfo(jsonParsed) result; None = unknown."""
    try:
        info = result["value"]["data"]["parsed"]["info"]  # type: ignore[index]
    except (KeyError, TypeError):
        return None, None
    return info.get("mintAuthority") is None, info.get("freezeAuthority") is None


def top_holders_pct(
    largest: list[dict[str, Any]], owners: dict[str, str], supply_raw: int, top_n: int = 10
) -> float | None:
    """Share of supply held by the top-N wallet owners, ignoring off-curve (PDA) owners such as
    pools, vaults and bonding curves. Accounts of one owner are summed. None if undeterminable."""
    if supply_raw <= 0:
        return None
    by_owner: dict[str, int] = {}
    for acc in largest:
        owner = owners.get(str(acc.get("address")))
        if owner is None:
            return None  # cannot tell wallets from PDAs -> do not guess
        on_curve = wallet_is_on_curve(owner)
        if on_curve is None:
            return None
        if not on_curve:
            continue
        by_owner[owner] = by_owner.get(owner, 0) + int(acc.get("amount") or 0)
    top = sorted(by_owner.values(), reverse=True)[:top_n]
    return sum(top) / supply_raw * 100


def evaluate_security(
    mint_revoked: bool | None,
    freeze_revoked: bool | None,
    top10_pct: float | None,
    max_top10_pct: float,
) -> SecurityResult:
    reasons: list[str] = []
    unknown: list[str] = []
    if mint_revoked is False:
        reasons.append("mint authority aktif")
    elif mint_revoked is None:
        unknown.append("mint authority")
    if freeze_revoked is False:
        reasons.append("freeze authority aktif")
    elif freeze_revoked is None:
        unknown.append("freeze authority")
    if top10_pct is not None and top10_pct >= max_top10_pct:
        reasons.append(f"top 10 holder {top10_pct:.1f}% ≥ {max_top10_pct:g}%")
    elif top10_pct is None:
        unknown.append("top 10 holder")
    if reasons:
        return SecurityResult("risiko", tuple(reasons), top10_pct)
    if unknown:
        why = tuple(f"{u} belum bisa dicek" for u in unknown)
        return SecurityResult("belum terverifikasi", why, top10_pct)
    return SecurityResult("ok", (), top10_pct)


def parse_rugcheck_risks(payload: Any) -> tuple[str, ...]:
    """Names of danger-level risks. Extra info only; never affects the security status."""
    risks = payload.get("risks") if isinstance(payload, dict) else None
    if not isinstance(risks, list):
        return ()
    return tuple(str(r.get("name")) for r in risks if isinstance(r, dict) and r.get("level") == "danger")


class SecurityClient:
    def __init__(self, client: httpx.AsyncClient, rpc_url: str) -> None:
        self._client = client
        self._rpc_url = rpc_url
        self._cache = TTLCache(SECURITY_TTL)

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        payload = await request_json(self._client, "rpc", "POST", self._rpc_url, json=body)
        if not isinstance(payload, dict) or payload.get("error"):
            detail = payload.get("error") if isinstance(payload, dict) else "respons tidak valid"
            raise SourceError("rpc", f"{method}: {detail}")
        return payload.get("result")

    async def check(
        self, mint: str, meteora_freeze_disabled: bool | None, max_top10_pct: float
    ) -> SecurityResult:
        cached = self._cache.get(mint)
        if cached is not None:
            return self._with_freeze_fallback(cached, meteora_freeze_disabled, max_top10_pct)
        failed: list[str] = []

        async def guarded(coro: Any) -> Any:
            try:
                return await coro
            except SourceError as e:
                if e.source not in failed:
                    failed.append(e.source)
                return None

        info, supply, largest, rug = await asyncio.gather(
            guarded(self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])),
            guarded(self._rpc("getTokenSupply", [mint])),
            guarded(self._rpc("getTokenLargestAccounts", [mint])),
            guarded(request_json(self._client, "rugcheck", "GET", RUGCHECK.format(mint=mint))),
        )
        mint_revoked, freeze_revoked = parse_authorities(info)
        top10 = await self._top10(largest, supply, failed)
        base = evaluate_security(mint_revoked, freeze_revoked, top10, max_top10_pct)
        result = SecurityResult(
            base.status, base.reasons, base.top10_pct,
            notes=tuple(f"RugCheck: {n}" for n in parse_rugcheck_risks(rug)),
            failed_sources=tuple(failed),
        )
        if not failed:
            self._cache.set(mint, (mint_revoked, freeze_revoked, top10, result.notes))
        return self._with_freeze_fallback((mint_revoked, freeze_revoked, top10, result.notes),
                                          meteora_freeze_disabled, max_top10_pct, failed)

    async def _top10(self, largest: Any, supply: Any, failed: list[str]) -> float | None:
        try:
            accounts = largest["value"]
            supply_raw = int(supply["value"]["amount"])
        except (KeyError, TypeError, ValueError):
            return None
        if not accounts:
            return None
        try:
            multi = await self._rpc(
                "getMultipleAccounts", [[a["address"] for a in accounts], {"encoding": "jsonParsed"}]
            )
            owners: dict[str, str] = {}
            for acc, value in zip(accounts, multi["value"], strict=True):
                owner = ((value or {}).get("data") or {}).get("parsed", {}).get("info", {}).get("owner")
                if owner:
                    owners[acc["address"]] = owner
        except (SourceError, KeyError, TypeError, ValueError):
            if "rpc" not in failed:
                failed.append("rpc")
            return None
        return top_holders_pct(accounts, owners, supply_raw)

    @staticmethod
    def _with_freeze_fallback(
        data: tuple[bool | None, bool | None, float | None, tuple[str, ...]],
        meteora_freeze_disabled: bool | None,
        max_top10_pct: float,
        failed: list[str] | None = None,
    ) -> SecurityResult:
        mint_revoked, freeze_revoked, top10, notes = data
        if freeze_revoked is None and meteora_freeze_disabled is not None:
            freeze_revoked = meteora_freeze_disabled  # Meteora reports the same fact
        base = evaluate_security(mint_revoked, freeze_revoked, top10, max_top10_pct)
        return SecurityResult(base.status, base.reasons, base.top10_pct, notes, tuple(failed or ()))
