import pytest

from lpscout.settings import Settings, Thresholds


def test_from_env_requires_token_and_owner():
    with pytest.raises(ValueError):
        Settings.from_env({})


def test_from_env_reads_overrides():
    s = Settings.from_env({
        "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_ID": "42", "SCAN_MINUTES": "5",
        "IDEAL_FEE_YIELD": "0.3", "EXCLUDED_SYMBOLS": "foo, Bar",
    })
    assert s.telegram_owner_id == 42 and s.thresholds.scan_minutes == 5
    assert s.thresholds.ideal_fee_yield == 0.3 and s.excluded_symbols == {"FOO", "BAR"}


def test_set_value_validates():
    th = Thresholds()
    bad = [("nope", "1"), ("min_tvl", "abc"), ("min_tvl", "-5"), ("scan_minutes", "0"), ("min_tvl", "nan")]
    for key, raw in bad:
        with pytest.raises(ValueError):
            th.set_value(key, raw)
    th.set_value("scan_minutes", "10")
    assert th.scan_minutes == 10
