#!/usr/bin/env python3
"""Unit tests for the CEREBRO filter layers (screener.py). Stdlib-only (unittest) so no
extra dependency is needed — run with `python -m unittest test_screener.py` or `python
test_screener.py`."""
import unittest

import config as C
from screener import (
    enrich_layer3_tags,
    filter_pool_layer1,
    is_proven_by_pool_quality,
    select_best_sibling,
)


def make_pool(**overrides) -> dict:
    """A pool that comfortably clears Layer 1 by default; override fields per test."""
    base = {
        "address": "pool1",
        "name": "TOKEN-SOL",
        "mint_x": "TokenMintxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "mint_y": C.SOL_MINT,
        "tvl": 100_000.0,
        "fees_24h": 14_000.0,
        "vol_24h": 700_000.0,
        "fees_tvl_pct": 14.0,
        "vol_tvl_pct": 700.0,
        "vol_tvl_ratio": 7.0,
        "base_fee_pct": 2.0,
        "bin_step": 100,
        "pool_age_days": 13,
        "net_deposits": None,
        "current_price": 1.0,
    }
    base.update(overrides)
    return base


class TestFilterPoolLayer1(unittest.TestCase):
    def test_passes_when_all_metrics_clear_thresholds(self):
        ok, fails = filter_pool_layer1(make_pool())
        self.assertTrue(ok, fails)

    def test_fails_on_low_tvl(self):
        ok, _ = filter_pool_layer1(make_pool(tvl=5_000.0))
        self.assertFalse(ok)

    def test_fails_on_low_vol_tvl_ratio(self):
        ok, _ = filter_pool_layer1(make_pool(vol_tvl_ratio=1.0))
        self.assertFalse(ok)

    def test_fails_on_low_fee_tvl_pct(self):
        ok, _ = filter_pool_layer1(make_pool(fees_tvl_pct=3.0))
        self.assertFalse(ok)

    def test_missing_base_fee_is_skipped_not_failed(self):
        # None (unavailable from any source) must never fail the pool — only a known
        # value below threshold does.
        ok, fails = filter_pool_layer1(make_pool(base_fee_pct=None))
        self.assertTrue(ok, fails)

    def test_pool_age_is_never_a_hard_filter(self):
        # A brand-new pool (age 0) must still pass Layer 1 — age is informational only
        # (see enrich_layer3_tags' "new_pool" tag), never a rejection reason.
        ok, fails = filter_pool_layer1(make_pool(pool_age_days=0))
        self.assertTrue(ok, fails)


class TestSelectBestSibling(unittest.TestCase):
    def test_jomplang_pool_loses_to_higher_volume_sibling(self):
        # Mirrors the CEREBRO case from the Robinhood Chain bot: a thin-volume pool at a
        # higher fee tier ($11K) must lose the sibling selection against a much busier
        # pool at a different tier ($707.8K), because it's lopsided (<50% of max volume)
        # even though it individually clears Layer 1.
        thin_high_fee = make_pool(
            address="thin-high-fee",
            base_fee_pct=2.08,
            vol_24h=11_000.0,
            tvl=50_000.0,
            fees_24h=7_000.0,
            fees_tvl_pct=14.0,
            vol_tvl_pct=22.0,
            vol_tvl_ratio=0.22,  # below MIN_VOL_TVL_RATIO -> also individually fails Layer 1
        )
        busy_lower_fee = make_pool(
            address="busy-lower-fee",
            base_fee_pct=2.1,
            vol_24h=707_800.0,
            tvl=101_700.0,
            fees_24h=15_200.0,
            fees_tvl_pct=14.9,
            vol_tvl_pct=696.0,
            vol_tvl_ratio=6.96,
        )
        winner, info = select_best_sibling([thin_high_fee, busy_lower_fee])
        self.assertIsNotNone(winner)
        self.assertEqual(winner["address"], "busy-lower-fee")
        self.assertEqual(info["sibling_count"], 2)
        self.assertEqual(info["beaten_siblings"], 1)

    def test_non_lopsided_siblings_pick_higher_base_fee(self):
        low_fee = make_pool(address="low-fee", base_fee_pct=1.0, vol_24h=500_000.0)
        high_fee = make_pool(address="high-fee", base_fee_pct=2.0, vol_24h=480_000.0)
        winner, info = select_best_sibling([low_fee, high_fee])
        self.assertEqual(winner["address"], "high-fee")
        self.assertFalse(info["fallback_all_jomplang"])

    def test_all_jomplang_falls_back_to_highest_volume(self):
        # Every candidate is >50% below every other's volume relative to itself in some
        # pairwise sense is impossible with only 2 pools (one is always >=50% of the max
        # since it IS the max) — the fallback path is exercised with 3+ siblings where
        # the winner-by-fee is itself far below the busiest, unrelated pool that failed
        # Layer 1 (and so isn't a selectable candidate), leaving only lopsided passers.
        candidate_a = make_pool(address="a", base_fee_pct=2.0, vol_24h=60_000.0, tvl=15_000.0,
                                 fees_24h=2_100.0, fees_tvl_pct=14.0, vol_tvl_pct=400.0, vol_tvl_ratio=4.0)
        candidate_b = make_pool(address="b", base_fee_pct=1.0, vol_24h=45_000.0, tvl=15_000.0,
                                 fees_24h=2_100.0, fees_tvl_pct=14.0, vol_tvl_pct=300.0, vol_tvl_ratio=3.0)
        huge_failer = make_pool(address="huge-failer", vol_24h=1_000_000.0, fees_tvl_pct=1.0,
                                 vol_tvl_ratio=10.0, tvl=100_000.0, fees_24h=1_000.0)
        winner, info = select_best_sibling([candidate_a, candidate_b, huge_failer])
        self.assertEqual(winner["address"], "a")  # both a, b are candidates but jomplang vs huge_failer
        self.assertTrue(info["fallback_all_jomplang"])

    def test_no_sibling_clearing_layer1_returns_none(self):
        failer = make_pool(tvl=1_000.0)
        winner, info = select_best_sibling([failer])
        self.assertIsNone(winner)
        self.assertIsNone(info)

    def test_empty_list_returns_none(self):
        winner, info = select_best_sibling([])
        self.assertIsNone(winner)
        self.assertIsNone(info)


class TestIsProvenByPoolQuality(unittest.TestCase):
    def test_proven_when_both_thresholds_cleared(self):
        self.assertTrue(is_proven_by_pool_quality(make_pool(vol_tvl_ratio=7.0, fees_tvl_pct=14.0)))

    def test_not_proven_when_vol_tvl_below_bypass_threshold(self):
        self.assertFalse(is_proven_by_pool_quality(make_pool(vol_tvl_ratio=2.0, fees_tvl_pct=14.0)))


class TestEnrichLayer3Tags(unittest.TestCase):
    def test_new_pool_tag_set_for_sub_one_day_pool(self):
        tags = enrich_layer3_tags(make_pool(pool_age_days=0), {})
        self.assertTrue(tags["new_pool"])

    def test_new_pool_tag_absent_for_established_pool(self):
        tags = enrich_layer3_tags(make_pool(pool_age_days=13), {})
        self.assertFalse(tags["new_pool"])

    def test_momentum_tag_set_on_real_spike(self):
        m = make_pool(vol_24h=240_000.0)  # avg hourly = 10,000
        tags = enrich_layer3_tags(m, {"volume_h1": 20_000.0})  # 2x hourly avg
        self.assertIsNotNone(tags["momentum"])
        self.assertAlmostEqual(tags["momentum"], 2.0)

    def test_momentum_tag_dormant_without_dex_data(self):
        tags = enrich_layer3_tags(make_pool(), {})
        self.assertIsNone(tags["momentum"])

    def test_fee_vs_drawdown_dormant_without_price_change(self):
        tags = enrich_layer3_tags(make_pool(), {})
        self.assertIsNone(tags["fee_vs_drawdown"])

    def test_fee_vs_drawdown_computed_when_price_dropped(self):
        m = make_pool(fees_tvl_pct=14.0)
        tags = enrich_layer3_tags(m, {"price_change_24h": -7.0})
        self.assertAlmostEqual(tags["fee_vs_drawdown"], 2.0)


if __name__ == "__main__":
    unittest.main()
