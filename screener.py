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
    """CEREBRO Layer 1 — hard filter applied to every individual pool.

    A field that's unavailable from any data source (None) is SKIPPED, never treated as
    a failure — missing data isn't bad data. Pool age is deliberately NOT checked here;
    it's informational-only (see enrich_layer3_tags()), per the PRD.
    """
    fails = []
    if m["tvl"] < C.MIN_POOL_TVL:
        fails.append(f"❌ TVL ${m['tvl']:,.0f} < ${C.MIN_POOL_TVL:,.0f}")
    if m["vol_tvl_ratio"] < C.MIN_VOL_TVL_RATIO:
        fails.append(f"❌ Vol/TVL {m['vol_tvl_ratio']:.2f}x < {C.MIN_VOL_TVL_RATIO}x")
    if m["fees_tvl_pct"] < C.MIN_FEE_TVL_PCT:
        fails.append(f"❌ Fee/TVL {m['fees_tvl_pct']:.1f}%/hari < {C.MIN_FEE_TVL_PCT}%/hari")
    if m["base_fee_pct"] is not None and m["base_fee_pct"] < C.MIN_BASE_FEE_PCT:
        fails.append(f"❌ Base Fee {m['base_fee_pct']:.2f}% < {C.MIN_BASE_FEE_PCT}%")
    return len(fails) == 0, fails


def is_proven_by_pool_quality(m: dict) -> bool:
    """A pool already proven "kencang" over a full 24h — used to bypass the short-term
    (5-minute) spike gate so a genuinely sustained pool isn't missed just because the
    specific window it got checked in happened to be quiet."""
    return (
        m["vol_tvl_ratio"] >= C.SPIKE_BYPASS_VOL_TVL_RATIO
        and m["fees_tvl_pct"] >= C.SPIKE_BYPASS_FEE_TVL_PCT
    )


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
