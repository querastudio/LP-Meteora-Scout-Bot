import asyncio

from helpers import NOW, FakePools, FakeSecurity, busy_candles, make_pool, make_settings

from lpscout.scanner import Scanner, prefilter_reason


def run(coro):
    return asyncio.run(coro)


def scan(pools, settings=None, security=None, extras=(), **kw):
    fp = FakePools(pools, **kw)
    sec = security or FakeSecurity()
    scanner = Scanner(fp, sec, settings or make_settings())
    outcome = run(scanner.scan(NOW, extra_addresses=extras))
    return outcome, fp, sec


def test_prefilter_reasons():
    s = make_settings()
    assert prefilter_reason(make_pool(), s) is None
    assert "blacklist" in prefilter_reason(make_pool(blacklisted=True), s)
    assert "bin step" in prefilter_reason(make_pool(bin_step=50), s)
    assert "TVL" in prefilter_reason(make_pool(tvl=9_000), s)
    assert "dikecualikan" in prefilter_reason(make_pool(symbol="USDC"), s)
    assert "dikecualikan" in prefilter_reason(make_pool(symbol="jup"), s)  # case-insensitive
    no_sol = make_pool()
    object.__setattr__(no_sol, "token_y", no_sol.token_x)
    assert "SOL" in prefilter_reason(no_sol, s)


def test_sol_on_either_side_is_accepted():
    assert prefilter_reason(make_pool(sol_first=True), make_settings()) is None


def test_only_top_n_by_fee_yield_get_candles_and_excluded_never_do():
    pools = [make_pool(symbol=f"T{i}", fees=1_000.0 * (i + 1)) for i in range(5)]
    pools.append(make_pool(symbol="USDC", fees=999_999.0))
    pools.append(make_pool(symbol="LOW", bin_step=20, fees=999_999.0))
    outcome, fp, _ = scan(pools, make_settings(top_n=3))
    assert outcome.pools_scanned == 7 and outcome.candidates == 3
    assert sorted(fp.candle_calls) == sorted(["pool_T4_100", "pool_T3_100", "pool_T2_100"])


def test_good_pool_is_recommended_with_size_and_json_ready_result():
    outcome, _, _ = scan([make_pool(fees=15_000.0)])  # fee yield 30%, flat price, even volume
    r = outcome.results[0]
    assert r["label"] == "ideal" and r["recommended"] and r["size_pct"] == 100
    assert r["metrics"]["activity"] == 1.0 and r["security"]["status"] == "ok"
    import json
    json.dumps(r)  # must be storable as-is


def test_security_only_checked_for_pools_that_reach_a_label():
    good, bad = make_pool("GOOD", fees=15_000.0), make_pool("BAD", fees=100.0)
    outcome, _, sec = scan([good, bad])
    assert sec.calls == ["mint_GOOD"]
    bad_r = next(r for r in outcome.results if r["name"] == "BAD-SOL")
    assert bad_r["label"] == "tolak" and bad_r["missing"]


def test_failed_security_is_never_recommended_even_with_ideal_metrics():
    outcome, _, _ = scan([make_pool(fees=15_000.0)], security=FakeSecurity("risiko"))
    r = outcome.results[0]
    assert r["label"] == "ideal" and not r["recommended"] and r["effective_label"] == "tolak"
    assert r["size_pct"] == 0


def test_unverified_security_is_recommended_but_marked():
    outcome, _, _ = scan([make_pool(fees=15_000.0)], security=FakeSecurity("belum terverifikasi"))
    r = outcome.results[0]
    assert r["recommended"] and r["security"]["status"] == "belum terverifikasi"


def test_candle_failure_is_counted_and_gives_null_metrics_not_a_crash():
    outcome, _, _ = scan([make_pool("A", fees=15_000.0), make_pool("B", fees=14_000.0)],
                         fail_candles={"pool_A_100"})
    assert outcome.failed == {"meteora_ohlcv": 1}
    a = next(r for r in outcome.results if r["name"] == "A-SOL")
    assert a["label"] == "tolak" and a["metrics"]["activity"] is None
    assert any("tidak tersedia" in x for x in a["missing"])
    assert next(r for r in outcome.results if r["name"] == "B-SOL")["recommended"]


def test_security_source_failures_are_aggregated():
    outcome, _, _ = scan([make_pool(fees=15_000.0)], security=FakeSecurity("ok", failed=("rpc", "rugcheck")))
    assert outcome.failed == {"rpc": 1, "rugcheck": 1}


def test_results_sorted_by_rank_then_fee_yield():
    pools = [make_pool("MIN", fees=3_500.0), make_pool("TOP", fees=15_000.0), make_pool("MID", fees=6_500.0)]
    outcome, _, _ = scan(pools)
    assert [r["label"] for r in outcome.results] == ["ideal", "bagus", "minimal"]


def test_active_pool_outside_top_n_is_still_reevaluated():
    pools = [make_pool("A", fees=20_000.0), make_pool("B", fees=15_000.0)]
    outcome, _, _ = scan(pools, make_settings(top_n=1), extras=["pool_B_100"])
    assert {r["name"] for r in outcome.results} == {"A-SOL", "B-SOL"}


def test_active_pool_failing_prefilter_is_reported_as_tolak_with_reason():
    pools = [make_pool("A", fees=20_000.0), make_pool("B", tvl=2_000.0)]
    outcome, fp, _ = scan(pools, extras=["pool_B_100"])
    b = next(r for r in outcome.results if r["name"] == "B-SOL")
    assert b["label"] == "tolak" and "penyaringan" in b["missing"][0]
    assert "pool_B_100" not in fp.candle_calls  # cheap: no candles for a pool that fails prefilter


def test_inspect_returns_security_and_shortfalls_even_for_rejected_pool():
    pool = make_pool("Z", fees=100.0, tvl=3_000.0)
    fp, sec = FakePools([pool]), FakeSecurity()
    outcome = run(Scanner(fp, sec, make_settings()).inspect("pool_Z_100", NOW))
    r = outcome.results[0]
    assert r["label"] == "tolak" and sec.calls == ["mint_Z"] and r["note"]
    assert busy_candles() and any("penyaringan" in x for x in r["missing"])
