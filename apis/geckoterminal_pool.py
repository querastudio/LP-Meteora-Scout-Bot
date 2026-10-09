"""Per-pool live stats from GeckoTerminal (free API): price change windows, trade counts,
volume windows and the 24h high. Keyed by the Meteora pool address, so the numbers describe
this exact pool rather than the token's best pair across all DEXes."""
import httpx

BASE = "https://api.geckoterminal.com/api/v2/networks/solana"


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _invert_pct(pct):
    """% change of base price -> % change of the inverse (quote-denominated) price."""
    if pct is None or pct <= -100:
        return None
    return (1 / (1 + pct / 100) - 1) * 100


async def get_pool_stats(client: httpx.AsyncClient, pool_address: str, target_mint: str) -> dict:
    """Returns {} on any failure. price_change_* are for the TARGET token (the non-SOL side),
    inverted when GeckoTerminal lists the target as the pool's quote token."""
    try:
        r = await client.get(f"{BASE}/pools/{pool_address}")
        r.raise_for_status()
        data = r.json().get("data") or {}
        attrs = data.get("attributes") or {}
        base_id = (((data.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id", "")
        target_is_base = base_id.endswith(target_mint) if base_id else True

        pc = attrs.get("price_change_percentage") or {}
        pcs = {k: _f(pc.get(k)) for k in ("m5", "h1", "h24")}
        if not target_is_base:
            pcs = {k: _invert_pct(v) for k, v in pcs.items()}

        h1 = (attrs.get("transactions") or {}).get("h1") or {}
        h24 = (attrs.get("transactions") or {}).get("h24") or {}
        vol = attrs.get("volume_usd") or {}
        trades_1h = (h1["buys"] + h1["sells"]) if h1.get("buys") is not None and h1.get("sells") is not None else None
        return {
            "price_change_5m": pcs["m5"],
            "price_change_1h": pcs["h1"],
            "price_change_24h": pcs["h24"],
            "trades_1h": trades_1h,
            "buys_24h": h24.get("buys"),
            "sells_24h": h24.get("sells"),
            "volume_m5": _f(vol.get("m5")),
            "volume_h1": _f(vol.get("h1")),
            "volume_h6": _f(vol.get("h6")),
        }
    except Exception:
        return {}


async def get_pullback_24h_pct(client: httpx.AsyncClient, pool_address: str, target_mint: str) -> float | None:
    """(24h high - latest close) / 24h high * 100, from 24 hourly candles priced in USD for the
    target token. None when candles are unavailable."""
    try:
        r = await client.get(
            f"{BASE}/pools/{pool_address}/ohlcv/hour",
            params={"aggregate": 1, "limit": 24, "token": target_mint},
        )
        r.raise_for_status()
        candles = ((r.json().get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        if not candles:
            return None
        newest = max(candles, key=lambda c: c[0])
        high = max(float(c[2]) for c in candles)
        if high <= 0:
            return None
        return max(0.0, (high - float(newest[4])) / high * 100)
    except Exception:
        return None


async def get_live_stats(client: httpx.AsyncClient, pool_address: str, target_mint: str) -> dict:
    stats = await get_pool_stats(client, pool_address, target_mint)
    stats["pullback_24h_pct"] = await get_pullback_24h_pct(client, pool_address, target_mint)
    return stats
