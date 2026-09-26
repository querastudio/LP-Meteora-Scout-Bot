import datetime
from typing import Optional

import httpx

# Meteora migrated the old dlmm-api.meteora.ag/pair/* endpoints (now 404) to a new
# paginated "datapi" service with a different response shape (see /pools, /pools/{address}).
BASE = "https://dlmm.datapi.meteora.ag"

SOL_MINT = "So11111111111111111111111111111111111111112"


async def get_all_pools(client: httpx.AsyncClient, max_pages: int = 5, page_size: int = 1000) -> list[dict]:
    """Fetch pools from the paginated /pools endpoint, newest/highest-volume first (API default sort)."""
    pools: list[dict] = []
    for page in range(1, max_pages + 1):
        r = await client.get(
            f"{BASE}/pools",
            params={"page": page, "page_size": page_size, "filter_by": "is_blacklisted=false"},
        )
        r.raise_for_status()
        body = r.json()
        data = body.get("data") or []
        pools.extend(data)
        if page >= int(body.get("pages") or 1) or not data:
            break
    return pools


async def get_pool_detail(client: httpx.AsyncClient, pool_address: str) -> Optional[dict]:
    try:
        r = await client.get(f"{BASE}/pools/{pool_address}")
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _parse_created_at(created_raw) -> Optional[int]:
    if not created_raw:
        return None
    try:
        ts = float(created_raw)
        if ts > 10_000_000_000:  # looks like milliseconds
            ts /= 1000
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days
    except Exception:
        return None


def parse_pool_metrics(pool: dict) -> dict:
    """Map a PoolResponse (new datapi schema) into the flat metrics dict the rest of the
    bot expects. Meteora's own API has no in-range %, total-LPs, volatility, or bin-level
    active-liquidity data at all (confirmed live, both /pools and /pools/{address}) — see
    README's Phase 2 backlog. base_fee_pct and pool_age_days are None (not 0) when their
    source field is genuinely missing, so filter_pool_layer1() can skip rather than fail.
    """
    token_x = pool.get("token_x") or {}
    token_y = pool.get("token_y") or {}

    x_addr = token_x.get("address", "")
    y_addr = token_y.get("address", "")
    if y_addr.lower() == SOL_MINT.lower():
        sol_token, target_token = token_y, token_x
    elif x_addr.lower() == SOL_MINT.lower():
        sol_token, target_token = token_x, token_y
    else:
        sol_token, target_token = {}, {}

    tvl = float(pool.get("tvl") or 0)
    volume = pool.get("volume") or {}
    fees = pool.get("fees") or {}
    fee_tvl_ratio = pool.get("fee_tvl_ratio") or {}
    pool_config = pool.get("pool_config") or {}

    vol_24h = float(volume.get("24h") or 0)
    fees_24h = float(fees.get("24h") or 0)
    fees_tvl_pct = float(fee_tvl_ratio.get("24h") if fee_tvl_ratio.get("24h") is not None
                          else (fees_24h / tvl * 100 if tvl > 0 else 0))
    vol_tvl_pct = (vol_24h / tvl * 100) if tvl > 0 else 0

    bin_step = int(pool_config.get("bin_step") or 0)
    # None (not 0) when pool_config itself is missing base_fee_pct entirely, so
    # filter_pool_layer1() can skip the base-fee check instead of failing the pool.
    raw_base_fee = pool_config.get("base_fee_pct")
    base_fee_pct = float(raw_base_fee) if raw_base_fee is not None else None

    # net_deposits = total_deposit_usd - total_withdrawal_usd. Not present in the current
    # PoolResponse schema (see apis/meteora.py module docstring re: the datapi migration) —
    # kept as a best-effort lookup in case Meteora adds it later. None -> skip in formatter.
    if pool.get("net_deposits_usd") is not None:
        net_deposits = float(pool["net_deposits_usd"])
    elif pool.get("net_deposit") is not None:
        net_deposits = float(pool["net_deposit"])
    elif pool.get("total_deposit_usd") is not None and pool.get("total_withdrawal_usd") is not None:
        net_deposits = float(pool["total_deposit_usd"]) - float(pool["total_withdrawal_usd"])
    else:
        net_deposits = None

    return {
        "address": pool.get("address", ""),
        "name": pool.get("name", ""),
        "mint_x": target_token.get("address", ""),
        "mint_y": sol_token.get("address", SOL_MINT),
        "tvl": tvl,
        "fees_24h": fees_24h,
        "vol_24h": vol_24h,
        "fees_tvl_pct": fees_tvl_pct,
        "vol_tvl_pct": vol_tvl_pct,
        "vol_tvl_ratio": vol_tvl_pct / 100,  # e.g. 2.0 = 2x/day, same units the PRD tables use
        "base_fee_pct": base_fee_pct,
        "bin_step": bin_step,
        "pool_age_days": _parse_created_at(pool.get("created_at")),
        "net_deposits": net_deposits,
        "current_price": float(pool.get("current_price") or 0),
        # Token metrics the new API already gives us for free (per-token, on the pool object).
        "target_symbol": target_token.get("symbol", ""),
        "target_name": target_token.get("name", ""),
        "target_holders": target_token.get("holders"),
        "target_freeze_disabled": target_token.get("freeze_authority_disabled"),
        "target_mcap": target_token.get("market_cap"),
    }
