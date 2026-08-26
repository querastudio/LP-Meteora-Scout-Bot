import config as C
from apis.meteora import classify_liquidity_shape, parse_pool_metrics


def check_token_safety(s: dict) -> tuple[bool, list[str]]:
    fails = []
    if s.get("mint_auth") is True:
        fails.append("❌ Mint Auth aktif")
    if s.get("freeze_auth") is True:
        fails.append("❌ Freeze Auth aktif")
    if s.get("mcap", 0) < C.MIN_MCAP:
        fails.append("❌ MCap terlalu kecil")
    if s.get("mcap", 0) > C.MAX_MCAP:
        fails.append("❌ MCap terlalu besar")
    if s.get("top10_pct", 100) > C.MAX_TOP10_PCT:
        fails.append("❌ Top 10 terkonsentrasi")
    if s.get("token_age_days", 0) < C.MIN_TOKEN_AGE_DAYS:
        fails.append("❌ Token terlalu baru")
    holders = s.get("holders")
    if holders is not None and holders < C.MIN_HOLDERS:
        fails.append("❌ Holders kurang")
    return len(fails) == 0, fails


def check_pool_metrics(m: dict) -> tuple[bool, list[str]]:
    fails = []
    if m["fees_tvl_pct"] < C.MIN_FEES_TVL_PCT:
        fails.append(f"❌ Fees/TVL {m['fees_tvl_pct']:.1f}%")
    if not (C.MIN_VOL_TVL_PCT <= m["vol_tvl_pct"] <= C.MAX_VOL_TVL_PCT):
        fails.append(f"❌ Vol/TVL {m['vol_tvl_pct']:.0f}%")
    if not (C.MIN_VOLATILITY <= m["volatility"] <= C.MAX_VOLATILITY):
        fails.append(f"❌ Volatility {m['volatility']:.2f}%")
    if m["in_range_pct"] < C.MIN_IN_RANGE_PCT:
        fails.append(f"❌ In Range {m['in_range_pct']:.0f}%")
    if not (C.MIN_POOL_AGE_DAYS <= m["pool_age_days"] <= C.MAX_POOL_AGE_DAYS):
        fails.append(f"❌ Pool age {m['pool_age_days']}d")
    if m["tvl"] < C.MIN_ACTIVE_TVL:
        fails.append("❌ TVL terlalu kecil")
    if m["avg_fees_min"] < C.MIN_AVG_FEES_MIN:
        fails.append("❌ Avg Fees/Min rendah")
    if m["avg_vol_min"] < C.MIN_AVG_VOL_MIN:
        fails.append("❌ Avg Vol/Min rendah")
    if m["total_lps"] < C.MIN_TOTAL_LPS:
        fails.append(f"❌ Total LPs {m['total_lps']}")
    return len(fails) == 0, fails


def check_fee_structure(m: dict) -> tuple[bool, list[str]]:
    fails = []
    if m["bin_step"] > C.MAX_BIN_STEP:
        fails.append(f"❌ Bin Step {m['bin_step']}")
    if not (C.MIN_BASE_FEE_PCT <= m["base_fee_pct"] <= C.MAX_BASE_FEE_PCT):
        fails.append(f"❌ Base Fee {m['base_fee_pct']:.2f}%")
    if m["fees_24h"] < C.MIN_FEES_24H:
        fails.append("❌ 24h Fees rendah")
    if m["fees_tvl_pct"] < C.MIN_FEES_TVL_24H:
        fails.append("❌ 24h Fees/TVL rendah")
    return len(fails) == 0, fails


def run_all_filters(pool_raw: dict, safety: dict, bins: list | None = None) -> dict:
    m = parse_pool_metrics(pool_raw)
    l1_ok, l1_fails = check_token_safety(safety)
    l2_ok, l2_fails = check_pool_metrics(m)
    l3_ok, l3_fails = check_fee_structure(m)

    shape_info = {"shape": "N/A", "position": "N/A", "dominant": "N/A", "ok": True}
    if bins:
        current_bin = int(m["current_price"] / (m["bin_step"] or 1)) if m["bin_step"] else 0
        shape_info = classify_liquidity_shape(bins, current_bin)

    passed = l1_ok and l2_ok and l3_ok and shape_info.get("ok", True)
    return {
        "passed": passed,
        "metrics": m,
        "safety": safety,
        "shape": shape_info,
        "l1_ok": l1_ok,
        "l1_fails": l1_fails,
        "l2_ok": l2_ok,
        "l2_fails": l2_fails,
        "l3_ok": l3_ok,
        "l3_fails": l3_fails,
    }
