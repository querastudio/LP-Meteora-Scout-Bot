"""Plain-text Telegram messages (no parse_mode, so token names can never break formatting)."""
from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from .settings import Thresholds

MAX_CHARS = 3500
FOOTER = "Setup: Bid-Ask, SOL saja, range -70%. Ambang dari backtest, bukan jaminan."
LABEL_TEXT = {"ideal": "⭐ IDEAL", "bagus": "✅✅ BAGUS", "minimal": "✅ MINIMAL", "tolak": "❌ TOLAK"}
NA = "n/a"


def _pct(v: float | None, digits: int = 1) -> str:
    return NA if v is None else f"{v * 100:.{digits}f}%"


def _usd(v: float | None) -> str:
    return NA if v is None else "$" + f"{v:,.0f}".replace(",", ".")


def _times(v: float | None) -> str:
    return NA if v is None else f"{v:.1f}×"


def _security_line(r: dict[str, Any]) -> str:
    sec = r["security"]
    text = sec["status"]
    if sec["status"] == "risiko":
        text += " (" + "; ".join(sec["reasons"]) + ")"
    elif sec["status"] == "belum terverifikasi" and sec["top10_pct"] is not None:
        text += f" · top 10 {sec['top10_pct']:.1f}%"
    size = f"{r['size_pct']}% batas risiko" if r["recommended"] else "tidak direkomendasikan"
    return f"Keamanan: {text} · Ukuran: {size}"


def pool_block(r: dict[str, Any], suffix: str = "") -> str:
    m = r["metrics"]
    age = NA if r["age_days"] is None else f"{r['age_days']:.1f} hari"
    sigma = _pct(m["sigma_daily"])
    lines = [
        f"{LABEL_TEXT[r['label']]} {r['name']}{suffix}",
        f"Fee/TVL {_pct(m['fee_yield'])}/hari · net edge {_pct(m['net_edge'])} · "
        f"fee/LVR {_times(m['fee_lvr'])} · σ {sigma}",
        f"Aktivitas {_pct(m['activity'], 0)} · konsentrasi {_pct(m['concentration'])} · "
        f"laju 6j {_pct(m['pace6h'], 0)} · TVL {_usd(r['tvl'])} · umur {age}",
        _security_line(r),
    ]
    if r["security"]["notes"]:
        lines.append("; ".join(r["security"]["notes"]))
    lines.append(f"https://app.meteora.ag/dlmm/{r['address']}")
    return "\n".join(lines)


def alert_message(r: dict[str, Any], kind: str, prev_label: str | None = None) -> str:
    suffix = " · baru lolos" if kind == "new" else f" · naik dari {(prev_label or '?').upper()}"
    return f"{pool_block(r, suffix)}\n\n{FOOTER}"


def drop_message(name: str, address: str, missing: list[str]) -> str:
    why = "; ".join(missing[:3]) or "tidak lagi memenuhi syarat"
    return f"⬇️ {name} keluar dari daftar aktif (label sekarang: TOLAK)\nKurang: {why}\nhttps://app.meteora.ag/dlmm/{address}"


def _fit(header: str, blocks: list[str], footer: str) -> str:
    out = header
    shown = 0
    for b in blocks:
        extra = "\n\n" + b
        remaining = len(blocks) - shown - 1
        reserve = len(footer) + (len(f"\n\n… +{remaining} pool lagi") if remaining else 0) + 4
        if len(out) + len(extra) + reserve > MAX_CHARS:
            break
        out += extra
        shown += 1
    if shown < len(blocks):
        out += f"\n\n… +{len(blocks) - shown} pool lagi"
    return out + "\n\n" + footer


def ts_utc(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")


def top_message(scan: dict[str, Any] | None, limit: int = 8) -> str:
    if scan is None:
        return "Belum ada hasil scan. Kirim /scan untuk memindai sekarang."
    rec = [r for r in scan["results"] if r["recommended"]]
    counts = {k: sum(1 for r in rec if r["label"] == k) for k in ("ideal", "bagus", "minimal")}
    header = (
        f"🛰 LP Scout Solana · {ts_utc(scan['ts'])}\n"
        f"Dipindai: {scan['pools_scanned']} pool · Dihitung: {scan['candidates']} · "
        f"Lolos: Ideal {counts['ideal']} / Bagus {counts['bagus']} / Minimal {counts['minimal']}"
    )
    if not rec:
        near = [r for r in scan["results"] if not r["recommended"]][:3]
        lines = [header, "", "Tidak ada pool yang lolos. Tiga terdekat dan yang kurang:"]
        for r in near:
            why = "; ".join(r["missing"][:3]) or "keamanan gagal"
            lines.append(f"• {r['name']} — {why}")
        return "\n".join(lines) + "\n\n" + FOOTER
    return _fit(header, [pool_block(r) for r in rec[:limit]], FOOTER)


def pool_detail(r: dict[str, Any]) -> str:
    parts = [pool_block(r)]
    if r["note"]:
        parts.append(f"Penyaringan awal: tidak lolos — {r['note']}")
    if r["missing"]:
        bullets = "\n".join(f"• {x}" for x in r["missing"])
        parts.append("Syarat yang kurang untuk tingkat berikutnya:\n" + bullets)
    m = r["metrics"]
    parts.append(f"Candle 15m: {m['candles_15m']}/96 · bad print dibersihkan: {m['bad_prints']}")
    return "\n\n".join(parts)[: MAX_CHARS - len(FOOTER) - 4] + "\n\n" + FOOTER


def settings_message(th: Thresholds) -> str:
    rows = [f"{f.name} = {getattr(th, f.name)}" for f in dataclasses.fields(th)]
    return "Ambang saat ini (ubah: /set <nama> <nilai>):\n" + "\n".join(rows)
