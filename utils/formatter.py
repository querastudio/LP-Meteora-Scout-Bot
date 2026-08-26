import datetime

import config as C

WIB_OFFSET = datetime.timedelta(hours=8)

_BULAN_ID = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
    7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des",
}


def now_wib_str() -> str:
    now = datetime.datetime.now(datetime.timezone.utc) + WIB_OFFSET
    return f"{now.day:02d} {_BULAN_ID[now.month]} {now.year} | {now.strftime('%H.%M')}"


def fmt_usd(v) -> str:
    v = v or 0
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.2f}"


def sig(v, lo, hi=None, rev=False) -> str:
    if v is None:
        return "⚪"
    ok = (v <= lo if rev else v >= lo) if hi is None else lo <= v <= hi
    return "✅" if ok else "❌"


def fmt_num_or_na(v, fmt="{:.2f}%") -> str:
    return "N/A" if v is None else fmt.format(v)


def _auth_str(val) -> str:
    if val is None:
        return "⚪ Unknown"
    return "✅ Disabled" if not val else "❌ AKTIF"


def build_alert(result: dict) -> str:
    m, s, sh = result["metrics"], result["safety"], result["shape"]
    sym = s.get("symbol") or (m["name"].split("-")[0] if m.get("name") else "?")
    now_wib = now_wib_str()

    meteora = f"https://app.meteora.ag/dlmm/{m['address']}"
    birdeye = f"https://birdeye.so/token/{m['mint_x']}"
    dexscr = s.get("dex_url") or f"https://dexscreener.com/solana/{m['mint_x']}"

    holders = s.get("holders")
    holders_str = f"{holders:,}" if holders is not None else "N/A"

    return f"""🟢 <b>POOL ALERT — {sym}/SOL</b>
━━━━━━━━━━━━━━━━━━━━━
🔐 <b>TOKEN SAFETY</b>
━━━━━━━━━━━━━━━━━━━━━
🏷️ Token       : <b>{sym}</b>
💰 MCap        : {fmt_usd(s.get('mcap', 0))} {sig(s.get('mcap', 0), C.MIN_MCAP, C.MAX_MCAP)}
👥 Holders     : {holders_str} {sig(holders, C.MIN_HOLDERS)}
📊 Top 10 %    : {s.get('top10_pct', 0):.1f}% {sig(s.get('top10_pct', 100), 0, C.MAX_TOP10_PCT)}
🔒 Mint Auth   : {_auth_str(s.get('mint_auth'))}
❄️ Freeze Auth  : {_auth_str(s.get('freeze_auth'))}
📅 Token Age   : {s.get('token_age_days', 0)} hari {sig(s.get('token_age_days', 0), C.MIN_TOKEN_AGE_DAYS)}
━━━━━━━━━━━━━━━━━━━━━
📈 <b>POOL METRICS</b>
━━━━━━━━━━━━━━━━━━━━━
🏊 Pool Age        : {m['pool_age_days']} hari {sig(m['pool_age_days'], C.MIN_POOL_AGE_DAYS, C.MAX_POOL_AGE_DAYS)}
💧 Active TVL      : {fmt_usd(m['tvl'])} {sig(m['tvl'], C.MIN_ACTIVE_TVL)}
💸 Fees/Active TVL : {m['fees_tvl_pct']:.1f}% {sig(m['fees_tvl_pct'], C.MIN_FEES_TVL_PCT)}
🔄 Vol/Active TVL  : {m['vol_tvl_pct']:.0f}% {sig(m['vol_tvl_pct'], C.MIN_VOL_TVL_PCT, C.MAX_VOL_TVL_PCT)}
📉 Volatility      : {fmt_num_or_na(m['volatility'])} {sig(m['volatility'], C.MIN_VOLATILITY, C.MAX_VOLATILITY)}
🎯 In Range %      : {fmt_num_or_na(m['in_range_pct'], "{:.0f}%")} {sig(m['in_range_pct'], C.MIN_IN_RANGE_PCT)}
⚡ Avg Fees/Min    : {fmt_usd(m['avg_fees_min'])} {sig(m['avg_fees_min'], C.MIN_AVG_FEES_MIN)}
📊 Avg Vol/Min     : {fmt_usd(m['avg_vol_min'])} {sig(m['avg_vol_min'], C.MIN_AVG_VOL_MIN)}
👨‍💼 Total LPs       : {m['total_lps'] if m['total_lps'] is not None else "N/A"}
━━━━━━━━━━━━━━━━━━━━━
⚙️ <b>FEE STRUCTURE</b>
━━━━━━━━━━━━━━━━━━━━━
🪜 Bin Step        : {m['bin_step']} {sig(m['bin_step'], C.MIN_BIN_STEP, C.MAX_BIN_STEP)}
📋 Base Fee        : {m['base_fee_pct']:.2f}% {sig(m['base_fee_pct'], C.MIN_BASE_FEE_PCT)}
💰 24h Fees        : {fmt_usd(m['fees_24h'])} {sig(m['fees_24h'], C.MIN_FEES_24H)}
📊 24h Fees/TVL    : {m['fees_tvl_pct']:.1f}% {sig(m['fees_tvl_pct'], C.MIN_FEES_TVL_24H)}
━━━━━━━━━━━━━━━━━━━━━
📊 <b>LIQUIDITY SHAPE</b>
━━━━━━━━━━━━━━━━━━━━━
🗺️ Distribution    : {sh['shape']}
📍 Price vs Liq    : {sh['position']}
━━━━━━━━━━━━━━━━━━━━━
🔗 <b>LINKS</b>
━━━━━━━━━━━━━━━━━━━━━
📌 <a href="{meteora}">Meteora</a>  |  <a href="{birdeye}">Birdeye</a>  |  <a href="{dexscr}">DexScreener</a>
⏰ {now_wib} WIB
⚠️ DYOR — bukan financial advice"""


def build_summary(total, passed, fs, fp, ff, top3) -> str:
    now_wib = now_wib_str()
    top3_txt = "".join(
        f"{i + 1}. {r['safety'].get('symbol', '?')} — Fees/TVL: {r['metrics']['fees_tvl_pct']:.1f}%\n"
        for i, r in enumerate(top3)
    )
    return f"""📊 <b>LP SCOUT — RUN SUMMARY</b>
{now_wib} WIB
🔍 Di-scan   : {total}
✅ Lolos     : {passed}
❌ Safety    : {fs} | Pool: {fp} | Fee: {ff}
🏆 <b>Top Pool:</b>
{top3_txt or "Tidak ada yang lolos."}📡 Running via GitHub Actions ✅"""
