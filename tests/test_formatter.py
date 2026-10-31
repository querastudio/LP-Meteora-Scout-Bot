import asyncio
import json

from helpers import NOW, FakePools, FakeSecurity, make_pool, make_settings

from lpscout.formatter import (
    FOOTER,
    MAX_CHARS,
    alert_message,
    drop_message,
    pool_block,
    pool_detail,
    top_message,
)
from lpscout.scanner import Scanner


def results(pools, security=None):
    outcome = asyncio.run(Scanner(FakePools(pools), security or FakeSecurity(), make_settings()).scan(NOW))
    return json.loads(json.dumps(outcome.results))  # same round trip as the store


def scan_dict(res):
    return {"ts": NOW, "pools_scanned": 300, "candidates": 20, "results": res}


def test_alert_has_the_agreed_layout():
    r = results([make_pool("HI", fees=15_000.0)])[0]
    lines = alert_message(r, "new").splitlines()
    assert lines[0] == "⭐ IDEAL HI-SOL · baru lolos"
    assert lines[1].startswith("Fee/TVL 30.0%/hari · net edge ") and "fee/LVR" in lines[1] and "σ" in lines[1]
    assert lines[2].startswith("Aktivitas 100% · konsentrasi 1.0% · laju 6j 100%")
    assert lines[2].endswith("TVL $50.000 · umur 5.0 hari")
    assert lines[3] == "Keamanan: ok · Ukuran: 100% batas risiko"
    assert lines[4] == "https://app.meteora.ag/dlmm/pool_HI_100"
    assert lines[-1] == FOOTER and "Bid-Ask" in FOOTER


def test_upgrade_alert_names_previous_label():
    r = results([make_pool("HI", fees=15_000.0)])[0]
    assert alert_message(r, "upgrade", "bagus").splitlines()[0] == "⭐ IDEAL HI-SOL · naik dari BAGUS"


def test_unknown_values_render_as_na_not_zero():
    r = results([make_pool("HI", fees=15_000.0)])[0]
    r["metrics"].update(sigma_daily=None, net_edge=None, fee_lvr=None)
    r["age_days"] = None
    block = pool_block(r)
    assert "net edge n/a" in block and "σ n/a" in block and "umur n/a" in block


def test_risk_pool_block_says_not_recommended_and_why():
    r = results([make_pool("HI", fees=15_000.0)], FakeSecurity("risiko"))[0]
    assert "tidak direkomendasikan" in pool_block(r) and "freeze authority aktif" in pool_block(r)


def test_top_message_stays_within_limit_and_notes_overflow():
    res = results([make_pool(f"T{i}", fees=15_000.0 + i) for i in range(30)])
    msg = top_message(scan_dict(res), limit=30)
    assert len(msg) <= MAX_CHARS and msg.endswith(FOOTER) and "pool lagi" in msg
    assert msg.startswith("🛰 LP Scout Solana · ") and "Lolos: Ideal 20 / Bagus 0 / Minimal 0" in msg


def test_top_message_without_results_lists_nearest_with_missing_conditions():
    res = results([make_pool("A", fees=100.0), make_pool("B", fees=200.0)])
    msg = top_message(scan_dict(res))
    assert "Tidak ada pool yang lolos" in msg and "A-SOL" in msg and "Fee/TVL" in msg


def test_top_message_before_any_scan():
    assert "/scan" in top_message(None)


def test_pool_detail_lists_shortfalls_and_prefilter_note():
    r = results([make_pool("A", fees=100.0)])[0]
    r["note"] = "TVL $3,000 < $10,000"
    text = pool_detail(r)
    assert "Penyaringan awal: tidak lolos" in text and "• " in text and len(text) <= MAX_CHARS


def test_drop_message():
    assert "keluar dari daftar aktif" in drop_message("A-SOL", "ADDR", ["Fee/TVL 1.0% < 5.0%"])


def test_plain_text_only_so_hostile_names_are_harmless():
    r = results([make_pool("<b>x&", fees=15_000.0)])[0]
    assert "<b>x&-SOL" in alert_message(r, "new")  # sent without parse_mode, so shown literally
