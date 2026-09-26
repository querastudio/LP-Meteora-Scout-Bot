import datetime
import html

import config as C
from screener import classify_net_deposit_signal

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


def fmt_usd_signed(v) -> str:
    """Signed short USD format for net flow figures, e.g. -$227K, +$15K, +$1.2M."""
    sign = "-" if v < 0 else "+"
    return f"{sign}{fmt_usd(abs(v))}"


def fmt_usd_or_na(v) -> str:
    return "N/A" if v is None else fmt_usd(v)


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


def _layer3_tag_lines(m: dict, tags: dict) -> str:
    lines = []
    if tags.get("new_pool"):
        lines.append(f"⚠️ Pool Baru — umur {m['pool_age_days']} hari (di bawah {C.NEW_POOL_WARNING_DAYS} hari)")
    momentum = tags.get("momentum")
    if momentum is not None:
        lines.append(f"🔥 Momentum naik — Vol 1h {momentum:.1f}x rata-rata per-jam 24h")
    fee_vs_drawdown = tags.get("fee_vs_drawdown")
    if fee_vs_drawdown is not None:
        lines.append(f"💡 Fee vs Drawdown — Fee/TVL {fee_vs_drawdown:.1f}x drawdown 24h")
    return "\n".join(lines)


def build_alert(result: dict) -> str:
    m, s, sibling, tags = result["metrics"], result["safety"], result.get("sibling"), result.get("tags") or {}
    # Token symbol/name is attacker-controlled on-chain metadata (anyone can mint a token
    # with any name) — HTML-escape it so it can never break Telegram's HTML parser or
    # inject markup into the alert.
    raw_sym = s.get("symbol") or (m["name"].split("-")[0] if m.get("name") else "?")
    sym = html.escape(raw_sym)
    now_wib = now_wib_str()

    meteora = f"https://app.meteora.ag/dlmm/{m['address']}"
    birdeye = f"https://birdeye.so/token/{m['mint_x']}"
    dexscr = html.escape(s.get("dex_url") or f"https://dexscreener.com/solana/{m['mint_x']}", quote=True)

    holders = s.get("holders")
    holders_str = f"{holders:,}" if holders is not None else "N/A"
    top10_pct = s.get("top10_pct")
    top10_str = f"{top10_pct:.1f}%" if top10_pct is not None else "N/A"

    net_deposits_line = ""
    if m.get("net_deposits") is not None:
        _, nd_label = classify_net_deposit_signal(m["net_deposits"], m["fees_tvl_pct"], m["vol_tvl_pct"])
        net_deposits_line = f"📊 Net Deposits    : {fmt_usd_signed(m['net_deposits'])} {nd_label}\n"

    sibling_line = ""
    if sibling:
        if sibling["sibling_count"] > 1:
            sibling_line = (
                f"🏆 Sibling Win     : menang atas {sibling['beaten_siblings']} pool lain "
                f"(vol ratio {sibling['volume_ratio']:.0%}"
                f"{', fallback volume' if sibling['fallback_all_jomplang'] else ''})\n"
            )
        else:
            sibling_line = "🏆 Sibling Win     : satu-satunya pool untuk pair ini\n"

    buys, sells = s.get("buys_24h"), s.get("sells_24h")
    trades_str = f"{buys:,} beli / {sells:,} jual" if buys is not None and sells is not None else "N/A"

    tag_lines = _layer3_tag_lines(m, tags)
    tag_section = f"\n{tag_lines}\n━━━━━━━━━━━━━━━━━━━━━" if tag_lines else ""
    new_pool_prefix = "⚠️ " if tags.get("new_pool") else ""

    return f"""🟢 <b>{new_pool_prefix}POOL ALERT — {sym}/SOL</b>
━━━━━━━━━━━━━━━━━━━━━
🔐 <b>TOKEN SAFETY</b>
━━━━━━━━━━━━━━━━━━━━━
🏷️ Token       : <b>{sym}</b>
💰 MCap        : {fmt_usd(s.get('mcap', 0))} {sig(s.get('mcap', 0), C.MIN_MCAP, C.MAX_MCAP)}
👥 Holders     : {holders_str} {sig(holders, C.MIN_HOLDERS)}
📊 Top 10 %    : {top10_str} {sig(top10_pct, 0, C.MAX_TOP10_PCT)}
🔒 Mint Auth   : {_auth_str(s.get('mint_auth'))}
❄️ Freeze Auth  : {_auth_str(s.get('freeze_auth'))}
━━━━━━━━━━━━━━━━━━━━━
📈 <b>POOL METRICS (CEREBRO)</b>
━━━━━━━━━━━━━━━━━━━━━
🏊 Pool Age        : {fmt_num_or_na(m['pool_age_days'], "{:.0f} hari")}
💧 TVL             : {fmt_usd(m['tvl'])} {sig(m['tvl'], C.MIN_POOL_TVL)}
🔄 Vol/TVL         : {m['vol_tvl_ratio']:.2f}x {sig(m['vol_tvl_ratio'], C.MIN_VOL_TVL_RATIO)}
💸 Fee/TVL         : {m['fees_tvl_pct']:.1f}%/hari {sig(m['fees_tvl_pct'], C.MIN_FEE_TVL_PCT)}
📋 Base Fee/Bin    : {fmt_num_or_na(m['base_fee_pct'])} / bin_step {m['bin_step']} {sig(m['base_fee_pct'], C.MIN_BASE_FEE_PCT)}
{net_deposits_line}{sibling_line}📊 Volume 24h      : {fmt_usd(m['vol_24h'])}
📊 Volume 6h       : {fmt_usd_or_na(s.get('volume_h6'))}
🔁 Trades 24h      : {trades_str}
━━━━━━━━━━━━━━━━━━━━━
🔗 <b>LINKS</b>
━━━━━━━━━━━━━━━━━━━━━
📌 <a href="{meteora}">Meteora</a>  |  <a href="{birdeye}">Birdeye</a>  |  <a href="{dexscr}">DexScreener</a>{tag_section}
⏰ {now_wib} WIB
⚠️ DYOR — bukan financial advice"""


def build_summary(total, passed, fail_layer1, skipped_no_spike, skipped_cooldown, top3) -> str:
    now_wib = now_wib_str()
    top3_txt = "".join(
        f"{i + 1}. {html.escape(r['safety'].get('symbol') or '?')} — Fee/TVL: {r['metrics']['fees_tvl_pct']:.1f}%/hari\n"
        for i, r in enumerate(top3)
    )
    return f"""📊 <b>LP SCOUT — RUN SUMMARY</b>
{now_wib} WIB
🔍 Di-scan          : {total} pool
✅ Lolos (alert)    : {passed}
❌ Gagal Layer 1/2  : {fail_layer1} pasangan token
⏭️ Skip spike gate  : {skipped_no_spike}
🕒 Skip cooldown    : {skipped_cooldown}
🏆 <b>Top Pool:</b>
{top3_txt or "Tidak ada yang lolos."}📡 Running via GitHub Actions ✅"""
