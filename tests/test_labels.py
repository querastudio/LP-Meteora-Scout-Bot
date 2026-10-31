from lpscout.labels import evaluate, is_recommended
from lpscout.metrics import Metrics
from lpscout.settings import Thresholds

TH = Thresholds()


def m(**kw):
    base = dict(
        fee_yield=0.25, sigma_daily=0.5, lvr=0.03, net_edge=0.22, fee_lvr=8.0,
        activity=0.95, concentration=0.05, pace6h=0.8, candles_15m=96, bad_prints=0,
    )
    base.update(kw)
    return Metrics(**base)


def test_ideal():
    e = evaluate(m(), TH)
    assert (e.label, e.rank, e.missing) == ("ideal", 3, ())


def test_ideal_does_not_need_pace():
    assert evaluate(m(pace6h=0.0), TH).label == "ideal"


def test_bagus_and_what_is_missing_for_ideal():
    e = evaluate(m(fee_yield=0.12, net_edge=0.07), TH)
    assert e.label == "bagus"
    assert any("Fee/TVL" in x for x in e.missing) and any("net edge" in x for x in e.missing)


def test_bagus_needs_pace_so_low_pace_falls_to_tolak_when_not_ideal():
    e = evaluate(m(fee_yield=0.12, net_edge=0.07, pace6h=0.4), TH)
    assert e.label == "tolak"
    assert e.missing == ("laju 6j 40.0% < 50.0%",)


def test_minimal():
    e = evaluate(m(fee_yield=0.06, net_edge=0.03), TH)
    assert e.label == "minimal" and e.rank == 1


def test_tolak_lists_exactly_the_unmet_minimal_requirements():
    e = evaluate(m(fee_yield=0.04, net_edge=0.01, activity=0.8, concentration=0.2, pace6h=0.1), TH)
    assert e.label == "tolak"
    assert len(e.missing) == 5


def test_boundaries():
    assert evaluate(m(fee_yield=0.05, net_edge=0.02, concentration=0.0999), TH).label == "minimal"
    assert evaluate(m(fee_yield=0.05, net_edge=0.02, concentration=0.10), TH).label == "tolak"  # strict <
    assert evaluate(m(fee_yield=0.05, net_edge=0.02, activity=0.90), TH).label == "minimal"


def test_null_metrics_are_missing_not_zero():
    e = evaluate(m(sigma_daily=None, lvr=None, net_edge=None, fee_lvr=None, activity=None,
                   concentration=None, pace6h=None), TH)
    assert e.label == "tolak" and any("tidak tersedia" in x for x in e.missing)


def test_failed_security_is_never_recommended_whatever_the_label():
    for label in ("ideal", "bagus", "minimal"):
        assert not is_recommended(label, "risiko")
        assert is_recommended(label, "ok")
        assert is_recommended(label, "belum terverifikasi")
    assert not is_recommended("tolak", "ok")


def test_thresholds_are_configurable():
    strict = Thresholds()
    strict.set_value("minimal_fee_yield", "0.5")
    assert evaluate(m(fee_yield=0.06, net_edge=0.03), strict).label == "tolak"
