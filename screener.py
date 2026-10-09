import config as C


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
    top10_pct = s.get("top10_pct")
    if top10_pct is not None and top10_pct > C.MAX_TOP10_PCT:
        fails.append("❌ Top 10 terkonsentrasi")
    if s.get("token_age_days", 0) < C.MIN_TOKEN_AGE_DAYS:
        fails.append("❌ Token terlalu baru")
    holders = s.get("holders")
    if holders is not None and holders < C.MIN_HOLDERS:
        fails.append("❌ Holders kurang")
    return len(fails) == 0, fails


def filter_pool_layer1(m: dict) -> tuple[bool, list[str]]:
    """Stage A: pool metrics already present in the Meteora /pools response (no extra API
    call). A 1h fee/TVL that Meteora doesn't report is treated as unverified and fails."""
    fails = []
    if m["tvl"] < C.MIN_POOL_TVL:
        fails.append(f"❌ TVL ${m['tvl']:,.0f} < ${C.MIN_POOL_TVL:,.0f}")
    if m["vol_24h"] < C.MIN_VOLUME_24H_USD:
        fails.append(f"❌ Volume 24h ${m['vol_24h']:,.0f} < ${C.MIN_VOLUME_24H_USD:,.0f}")
    fee_1h = m.get("fees_tvl_1h_pct")
    if fee_1h is None or fee_1h < C.MIN_FEE_TVL_1H_PCT:
        fails.append(f"❌ Fee/TVL 1h {fee_1h if fee_1h is not None else 'N/A'} < {C.MIN_FEE_TVL_1H_PCT}%")
    if m["fees_tvl_pct"] < C.MIN_FEE_TVL_PCT:
        fails.append(f"❌ Fee/TVL 24h {m['fees_tvl_pct']:.1f}% < {C.MIN_FEE_TVL_PCT}%")
    return len(fails) == 0, fails


def filter_pool_live(live: dict) -> tuple[bool, list[str]]:
    """Stage B: live GeckoTerminal metrics. Strict — a metric that couldn't be fetched
    fails, so an alert only fires when every criterion was actually verified."""
    fails = []

    def need(key, label):
        v = live.get(key)
        if v is None:
            fails.append(f"❌ {label} tidak tersedia")
        return v

    trades = need("trades_1h", "Trades 1h")
    if trades is not None and trades < C.MIN_TRADES_1H:
        fails.append(f"❌ Trades 1h {trades} < {C.MIN_TRADES_1H}")
    pc1h = need("price_change_1h", "Price change 1h")
    if pc1h is not None and not (C.MIN_PRICE_CHANGE_1H_PCT <= pc1h <= C.MAX_PRICE_CHANGE_1H_PCT):
        fails.append(f"❌ Price change 1h {pc1h:.1f}% di luar [{C.MIN_PRICE_CHANGE_1H_PCT}%, {C.MAX_PRICE_CHANGE_1H_PCT}%]")
    pullback = need("pullback_24h_pct", "Pullback 24h")
    if pullback is not None and pullback > C.MAX_PULLBACK_24H_PCT:
        fails.append(f"❌ Pullback 24h {pullback:.1f}% > {C.MAX_PULLBACK_24H_PCT}%")
    pc5m = need("price_change_5m", "Price change 5m")
    if pc5m is not None and pc5m < C.MIN_PRICE_CHANGE_5M_PCT:
        fails.append(f"❌ Price change 5m {pc5m:.1f}% < {C.MIN_PRICE_CHANGE_5M_PCT}%")
    return len(fails) == 0, fails


def select_best_sibling(pools: list[dict]) -> tuple[dict | None, dict | None]:
    """CEREBRO Layer 2 — pick at most one winner among sibling pools of the same token pair.

    `pools` must be ALL sibling pools for the pair (including ones that fail Layer 1 —
    they're still used as volume comparables). Returns (winner_metrics, selection_info),
    or (None, None) if no sibling clears Layer 1.

    Selection: pools within SIBLING_JOMPLANG_RATIO of the busiest sibling's volume are
    "not lopsided" and compete on base_fee/bin_step (tie-break: volume). Pools that are
    all lopsided relative to each other fall back to a straight volume comparison,
    ignoring bin_step, among the Layer-1 passers.
    """
    if not pools:
        return None, None

    max_volume_sibling = max((p["vol_24h"] for p in pools), default=0.0)
    candidates = [p for p in pools if filter_pool_layer1(p)[0]]
    if not candidates:
        return None, None

    def volume_ratio(p: dict) -> float:
        return (p["vol_24h"] / max_volume_sibling) if max_volume_sibling > 0 else 1.0

    non_jomplang = [p for p in candidates if volume_ratio(p) >= C.SIBLING_JOMPLANG_RATIO]

    if non_jomplang:
        winner = max(non_jomplang, key=lambda p: (p["base_fee_pct"] or 0, p["vol_24h"]))
        fallback = False
    else:
        winner = max(candidates, key=lambda p: p["vol_24h"])
        fallback = True

    info = {
        "sibling_count": len(pools),
        "volume_ratio": volume_ratio(winner),
        "beaten_siblings": len(pools) - 1,
        "fallback_all_jomplang": fallback,
    }
    return winner, info


def enrich_layer3_tags(m: dict, dex: dict) -> dict:
    """CEREBRO Layer 3 — informational tags shown on the alert, never a reason to reject.

    - momentum: volume_h1 vs the token's own hourly-average-of-24h ("volume deras naik").
    - new_pool: pool age < NEW_POOL_WARNING_DAYS ("⚠️ Pool Baru" instead of a reject).
    - fee_vs_drawdown: Fee/TVL vs 24h price drawdown, when price-change data exists.
    Any tag whose source data is missing stays dormant (None) rather than being forced.
    """
    tags: dict = {"momentum": None, "new_pool": False, "fee_vs_drawdown": None}

    vol_h1 = dex.get("volume_h1")
    vol_24h = m.get("vol_24h")
    if vol_h1 is not None and vol_24h:
        avg_hourly = vol_24h / 24
        if avg_hourly > 0:
            ratio = vol_h1 / avg_hourly
            if ratio >= C.MOMENTUM_RATIO_THRESHOLD:
                tags["momentum"] = ratio

    age = m.get("pool_age_days")
    if age is not None and age < C.NEW_POOL_WARNING_DAYS:
        tags["new_pool"] = True

    price_change_24h = dex.get("price_change_24h")
    if price_change_24h is not None and price_change_24h < 0:
        drawdown = abs(price_change_24h)
        if drawdown > 0:
            tags["fee_vs_drawdown"] = m["fees_tvl_pct"] / drawdown

    return tags


def classify_net_deposit_signal(net_deposits: float, fees_tvl_pct: float, vol_tvl_pct: float) -> tuple[str, str]:
    """
    Returns (signal, label) berdasarkan konteks pool.

    net_deposits: nilai dolar (negatif = withdrawal > deposit)
    fees_tvl_pct: Fees/Active TVL dalam persen
    vol_tvl_pct: Volume/Active TVL dalam persen

    Logika:
    - Net deposits negatif + fees & vol masih tinggi → BULLISH (less competition, pool masih produktif)
    - Net deposits negatif + fees & vol rendah       → BEARISH (semua keluar, pool sepi)
    - Net deposits positif                           → NEUTRAL (likuiditas masih masuk)
    """
    if net_deposits >= 0:
        return ("neutral", "➡️ Net Deposit Positif")

    # Net deposit negatif — cek apakah pool masih produktif
    if fees_tvl_pct >= 8.0 and vol_tvl_pct >= 200.0:
        return ("bullish", "📉➡️📈 Net Withdraw tapi Pool Masih Aktif (less competition)")
    else:
        return ("bearish", "⚠️ Net Withdraw + Volume/Fees Sepi")
