import math
import statistics

from lpscout.metrics import (
    BUCKET_SECONDS,
    Candle,
    aggregate_15m,
    clean_bad_prints,
    compute_metrics,
    fee_yield,
    window_start,
)

NOW = 1_800_000_000 + 400  # inside a 15m bucket


def five_minute_series(price=lambda i: 1.0, volume=lambda i: 100.0, buckets=96):
    """Three 5m candles per 15m bucket across the whole 24h window."""
    t0 = window_start(NOW)
    out = []
    for i in range(buckets * 3):
        out.append(Candle(ts=t0 + i * 300, close=price(i // 3), volume=volume(i // 3) / 3))
    return out


def test_fee_yield_subtracts_protocol_fees():
    assert fee_yield(1000.0, 100.0, 9000.0) == 0.1
    assert fee_yield(None, 0.0, 9000.0) is None
    assert fee_yield(10.0, 0.0, 0.0) is None


def test_busy_even_pool_has_full_activity_and_low_concentration():
    m = compute_metrics(five_minute_series(), 5000.0, 500.0, 20_000.0, NOW)
    assert m.candles_15m == 96
    assert m.activity == 1.0
    assert math.isclose(m.concentration or 0, 1 / 96)
    assert math.isclose(m.pace6h or 0, 1.0)
    assert m.sigma_daily == 0.0 and m.lvr == 0.0
    assert m.fee_lvr is None  # lvr == 0 -> undefined, not infinity
    assert math.isclose(m.net_edge or 0, 0.225)


def test_single_giant_candle_means_high_concentration():
    vol = lambda i: 1_000_000.0 if i == 40 else 10.0  # noqa: E731
    m = compute_metrics(five_minute_series(volume=vol), 100.0, 0.0, 1000.0, NOW)
    assert (m.concentration or 0) > 0.99


def test_sparse_activity():
    vol = lambda i: 100.0 if i % 4 == 0 else 0.0  # noqa: E731
    m = compute_metrics(five_minute_series(volume=vol), 100.0, 0.0, 1000.0, NOW)
    assert m.activity == 0.25


def test_too_little_data_gives_null_not_zero():
    m = compute_metrics(five_minute_series(buckets=15), 100.0, 0.0, 1000.0, NOW)
    # 15 buckets only exist at the start of the window; the metrics must be null.
    assert m.candles_15m == 15
    assert m.sigma_daily is None and m.activity is None and m.concentration is None
    assert m.pace6h is None and m.net_edge is None and m.lvr is None
    assert m.fee_yield == 0.1  # not candle-derived, still available


def test_exactly_min_candles_is_enough():
    m = compute_metrics(five_minute_series(buckets=16), 100.0, 0.0, 1000.0, NOW)
    assert m.candles_15m == 16 and m.activity == 16 / 96


def test_sigma_and_lvr_formula():
    # Alternating +1%/-1% moves: returns are known, so sigma = stdev(returns) * sqrt(96).
    prices = [1.0]
    for i in range(1, 96):
        prices.append(prices[-1] * (1.01 if i % 2 else 1 / 1.01))
    m = compute_metrics(five_minute_series(price=lambda i: prices[i]), 100.0, 0.0, 1000.0, NOW)
    returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, 96)]
    expected = statistics.stdev(returns) * math.sqrt(96)
    assert math.isclose(m.sigma_daily or 0, expected)
    assert math.isclose(m.lvr or 0, expected**2 / 8)
    assert math.isclose(m.fee_lvr or 0, 0.1 / (expected**2 / 8))


def test_bad_print_is_replaced_by_neighbour_mean():
    c = [Candle(i * BUCKET_SECONDS, p, 1.0) for i, p in enumerate([1.0, 1.0, 3.0, 1.0, 1.0])]
    cleaned, fixed = clean_bad_prints(c)
    assert fixed == 1 and cleaned[2].close == 1.0


def test_one_sided_jump_is_a_real_move_not_a_bad_print():
    c = [Candle(i * BUCKET_SECONDS, p, 1.0) for i, p in enumerate([1.0, 1.0, 3.0, 3.0, 3.0])]
    _, fixed = clean_bad_prints(c)
    assert fixed == 0


def test_bad_print_does_not_inflate_sigma():
    spike = lambda i: 5.0 if i == 50 else 1.0  # noqa: E731
    m = compute_metrics(five_minute_series(price=spike), 100.0, 0.0, 1000.0, NOW)
    assert m.bad_prints == 1 and m.sigma_daily == 0.0


def test_aggregation_uses_last_close_and_sums_volume_and_dedupes_borders():
    t0 = window_start(NOW)
    raw = [
        Candle(t0, 1.0, 10.0), Candle(t0 + 300, 2.0, 20.0), Candle(t0 + 600, 3.0, 30.0),
        Candle(t0 + 600, 3.0, 30.0),  # duplicate from overlapping request windows
        Candle(t0 - 300, 9.0, 99.0),  # before the window
    ]
    out = aggregate_15m(raw, NOW)
    assert len(out) == 1 and out[0].close == 3.0 and out[0].volume == 60.0


def test_invalid_closes_are_dropped():
    t0 = window_start(NOW)
    out = aggregate_15m([Candle(t0, 0.0, 5.0), Candle(t0 + 300, float("nan"), 5.0)], NOW)
    assert out == []


def test_last_six_hours_pace():
    vol = lambda i: 200.0 if i >= 72 else 100.0  # noqa: E731
    m = compute_metrics(five_minute_series(volume=vol), 100.0, 0.0, 1000.0, NOW)
    total = 72 * 100 + 24 * 200
    assert math.isclose(m.pace6h or 0, 24 * 200 * 4 / total)
