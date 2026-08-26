import datetime
from typing import Optional

import httpx

BASE = "https://dlmm-api.meteora.ag"


async def get_all_pools(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(f"{BASE}/pair/all")
    r.raise_for_status()
    return r.json()


async def get_pool_detail(client: httpx.AsyncClient, pool_address: str) -> Optional[dict]:
    try:
        r = await client.get(f"{BASE}/pair/{pool_address}")
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _parse_created_at(created_raw) -> int:
    if not created_raw:
        return 0
    try:
        if isinstance(created_raw, (int, float)):
            ts = created_raw / 1000 if created_raw > 10_000_000_000 else created_raw
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        else:
            dt = datetime.datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days
    except Exception:
        return 0


def parse_pool_metrics(pool: dict) -> dict:
    tvl = float(pool.get("liquidity") or pool.get("tvl") or 0)
    fees_24h = float(pool.get("fees_24h") or (pool.get("fees") or {}).get("hour_24") or 0)
    vol_24h = float(pool.get("trade_volume_24h") or pool.get("volume_24h") or 0)
    base_fee = float(pool.get("base_fee_percentage") or 0)
    bin_step = int(pool.get("bin_step") or 0)

    fees_tvl = (fees_24h / tvl * 100) if tvl > 0 else 0
    vol_tvl = (vol_24h / tvl * 100) if tvl > 0 else 0

    pool_age_days = _parse_created_at(
        pool.get("created_at") or pool.get("pool_created_at") or pool.get("createdAt")
    )

    open_pos = int(pool.get("open_positions") or 0)
    in_range = int(pool.get("in_range_positions") or 0)
    in_range_pct = (in_range / open_pos * 100) if open_pos > 0 else 0

    volatility = float(pool.get("volatility") or pool.get("volatility_accumulator") or 0)
    avg_fees_min = float(pool.get("avg_fee_per_minute") or (fees_24h / 1440 if fees_24h else 0))
    avg_vol_min = float(pool.get("avg_volume_per_minute") or (vol_24h / 1440 if vol_24h else 0))
    total_lps = int(pool.get("total_lps") or pool.get("lp_count") or 0)

    return {
        "address": pool.get("address") or pool.get("pubkey", ""),
        "name": pool.get("name", ""),
        "mint_x": pool.get("mint_x", ""),
        "mint_y": pool.get("mint_y", ""),
        "tvl": tvl,
        "fees_24h": fees_24h,
        "vol_24h": vol_24h,
        "fees_tvl_pct": fees_tvl,
        "vol_tvl_pct": vol_tvl,
        "base_fee_pct": base_fee,
        "bin_step": bin_step,
        "pool_age_days": pool_age_days,
        "in_range_pct": in_range_pct,
        "open_positions": open_pos,
        "in_range_pos": in_range,
        "volatility": volatility,
        "avg_fees_min": avg_fees_min,
        "avg_vol_min": avg_vol_min,
        "total_lps": total_lps,
        "current_price": float(pool.get("current_price") or 0),
    }


def classify_liquidity_shape(bins: list[dict], current_bin_id: int) -> dict:
    if not bins:
        return {"shape": "Unknown", "position": "N/A", "dominant": "N/A", "ok": True}

    bins_sorted = sorted(bins, key=lambda b: float(b.get("liquidity", 0)), reverse=True)
    total_liq = sum(float(b.get("liquidity", 0)) for b in bins)
    if total_liq == 0:
        return {"shape": "Empty", "position": "N/A", "dominant": "N/A", "ok": True}

    bin_ids = [b["bin_id"] for b in bins]
    peak_bin = bins_sorted[0]["bin_id"]
    spread = max(bin_ids) - min(bin_ids) if len(bin_ids) > 1 else 1
    distance = abs(peak_bin - current_bin_id)
    ratio = distance / spread if spread > 0 else 0

    if ratio < 0.10:
        shape, pos = "Concentrated ✅", "Di zona likuiditas tertinggi ✅"
    elif ratio < 0.30:
        shape, pos = "Bell / Near-peak ✅", "Dekat puncak likuiditas ✅"
    elif ratio < 0.50:
        shape, pos = "Spread lebar 🟡", "Agak jauh dari puncak 🟡"
    else:
        shape, pos = "Far from price ❌", "Mayoritas likuiditas jauh ❌"

    dominant = "Balanced ✅" if current_bin_id == peak_bin else (
        "Token-heavy" if current_bin_id < peak_bin else "SOL-heavy"
    )
    return {"shape": shape, "position": pos, "dominant": dominant, "ok": ratio < 0.50}
