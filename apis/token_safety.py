import asyncio
import datetime

import httpx

TIMEOUT = 15


def _rpc_endpoints(helius_key: str, alchemy_key: str = "") -> list[str]:
    """Ordered list of Solana RPC endpoints to try: Alchemy -> Helius -> public fallback.

    Alchemy is tried first (primary provider). Helius is kept as a fallback so a bad/test
    HELIUS_API_KEY (or none at all) never blocks these checks — it only gets used if Alchemy
    is unavailable or fails.
    """
    urls = []
    if alchemy_key:
        urls.append(f"https://solana-mainnet.g.alchemy.com/v2/{alchemy_key}")
    if helius_key:
        urls.append(f"https://mainnet.helius-rpc.com/?api-key={helius_key}")
    urls.append("https://api.mainnet-beta.solana.com")
    return urls


async def _rpc_post(client: httpx.AsyncClient, payload: dict, helius_key: str, alchemy_key: str = "") -> dict | None:
    """POST an RPC payload, falling through Alchemy -> Helius -> public RPC on failure."""
    for url in _rpc_endpoints(helius_key, alchemy_key):
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                continue
            return data
        except Exception:
            continue
    return None


async def check_mint_freeze(
    client: httpx.AsyncClient, mint: str, helius_key: str, alchemy_key: str = "", enabled: bool = True
) -> dict:
    if not enabled or (not helius_key and not alchemy_key):
        # Disabled (feature toggle) or no RPC key available -> can't verify, treat as
        # "unknown" (caller skips this filter).
        return {"mint_auth": None, "freeze_auth": None}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [mint, {"encoding": "jsonParsed"}],
    }
    data = await _rpc_post(client, payload, helius_key, alchemy_key)
    if data is None:
        return {"mint_auth": None, "freeze_auth": None}
    info = (
        data.get("result", {})
        .get("value", {})
        .get("data", {})
        .get("parsed", {})
        .get("info", {})
    )
    return {
        "mint_auth": info.get("mintAuthority") is not None,
        "freeze_auth": info.get("freezeAuthority") is not None,
    }


async def get_holders_count(
    client: httpx.AsyncClient, mint: str, helius_key: str, target: int, enabled: bool = True
) -> int | None:
    """Best-effort holder count via Helius DAS getTokenAccounts.

    This is a Helius-specific RPC extension (not standard Solana RPC / DAS core spec), so
    there is no Alchemy or public-RPC fallback for it — returns None when no Helius key is
    configured, and the caller then skips the holders filter rather than failing the pool.
    Stops paginating once `target` is reached to keep the call cheap. This is by far the
    most RPC-expensive check (up to 10 paginated calls per token), so it can be disabled
    independently via the `enabled` flag.
    """
    if not enabled or not helius_key:
        return None
    url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    total = 0
    cursor = None
    try:
        for _ in range(10):  # hard cap on pages to bound latency
            params = {"mint": mint, "limit": 1000, "options": {"showZeroBalance": False}}
            if cursor:
                params["cursor"] = cursor
            r = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": "getTokenAccounts", "params": params},
            )
            result = r.json().get("result") or {}
            accounts = result.get("token_accounts") or []
            total += len(accounts)
            if total >= target:
                return total
            cursor = result.get("cursor")
            if not cursor or not accounts:
                break
        return total
    except Exception:
        return None


async def get_dexscreener_data(client: httpx.AsyncClient, mint: str) -> dict:
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    try:
        r = await client.get(url)
        pairs = r.json().get("pairs") or []
        if not pairs:
            return {}
        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"] or pairs
        best = max(sol_pairs, key=lambda p: float((p.get("volume") or {}).get("h24") or 0))
        created_at = best.get("pairCreatedAt")
        age_days = 0
        if created_at:
            dt = datetime.datetime.fromtimestamp(created_at / 1000, tz=datetime.timezone.utc)
            age_days = (datetime.datetime.now(datetime.timezone.utc) - dt).days
        return {
            "mcap": float(best.get("marketCap") or 0),
            "fdv": float(best.get("fdv") or 0),
            "token_age_days": age_days,
            "symbol": (best.get("baseToken") or {}).get("symbol", ""),
            "name": (best.get("baseToken") or {}).get("name", ""),
            "dex_url": best.get("url", ""),
            "volume_24h": float((best.get("volume") or {}).get("h24") or 0),
        }
    except Exception:
        return {}


async def get_geckoterminal_data(client: httpx.AsyncClient, mint: str) -> dict:
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}"
    try:
        r = await client.get(url)
        attrs = r.json().get("data", {}).get("attributes", {})
        mcap = float(attrs.get("market_cap_usd") or attrs.get("fdv_usd") or 0)
        return {"mcap": mcap, "symbol": attrs.get("symbol", ""), "name": attrs.get("name", "")}
    except Exception:
        return {}


async def get_top10_pct(
    client: httpx.AsyncClient, mint: str, helius_key: str, alchemy_key: str = "", enabled: bool = True
) -> float | None:
    if not enabled:
        return None
    try:
        data = await _rpc_post(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [mint, {"commitment": "confirmed"}],
            },
            helius_key,
            alchemy_key,
        )
        if data is None:
            return 100.0
        accounts = data.get("result", {}).get("value", [])[:10]
        top10 = sum(float(a.get("uiAmount") or 0) for a in accounts)

        supply_data = await _rpc_post(
            client,
            {"jsonrpc": "2.0", "id": 2, "method": "getTokenSupply", "params": [mint]},
            helius_key,
            alchemy_key,
        )
        if supply_data is None:
            return 100.0
        supply = float(supply_data.get("result", {}).get("value", {}).get("uiAmount") or 1)
        return round(top10 / supply * 100, 2) if supply > 0 else 100.0
    except Exception:
        return 100.0


async def get_token_safety(
    client: httpx.AsyncClient,
    mint: str,
    helius_key: str,
    min_holders: int,
    alchemy_key: str = "",
    enable_mint_freeze_check: bool = True,
    enable_top10_check: bool = True,
    enable_holders_check: bool = True,
) -> dict:
    dex, gecko, auth, top10, holders = await asyncio.gather(
        get_dexscreener_data(client, mint),
        get_geckoterminal_data(client, mint),
        check_mint_freeze(client, mint, helius_key, alchemy_key, enable_mint_freeze_check),
        get_top10_pct(client, mint, helius_key, alchemy_key, enable_top10_check),
        get_holders_count(client, mint, helius_key, min_holders, enable_holders_check),
        return_exceptions=True,
    )
    dex = dex if isinstance(dex, dict) else {}
    gecko = gecko if isinstance(gecko, dict) else {}
    auth = auth if isinstance(auth, dict) else {"mint_auth": None, "freeze_auth": None}
    top10 = top10 if isinstance(top10, float) else None
    holders = holders if isinstance(holders, int) else None

    return {
        "mint": mint,
        "symbol": dex.get("symbol") or gecko.get("symbol", ""),
        "name": dex.get("name") or gecko.get("name", ""),
        "mcap": dex.get("mcap") or gecko.get("mcap", 0),
        "fdv": dex.get("fdv", 0),
        "token_age_days": dex.get("token_age_days", 0),
        "holders": holders,
        "top10_pct": top10,
        "mint_auth": auth.get("mint_auth"),
        "freeze_auth": auth.get("freeze_auth"),
        "volume_24h": dex.get("volume_24h", 0),
        "dex_url": dex.get("dex_url", ""),
    }
