"""Pure label classification (ideal / bagus / minimal / tolak) and recommendation gating."""
from __future__ import annotations

from dataclasses import dataclass

from .metrics import Metrics
from .settings import Thresholds

RANK = {"tolak": 0, "minimal": 1, "bagus": 2, "ideal": 3}
TIERS = ("ideal", "bagus", "minimal")  # best first


@dataclass(frozen=True)
class Evaluation:
    label: str
    rank: int
    missing: tuple[str, ...]  # unmet requirements of the next tier up (minimal when label is "tolak")


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _check(name: str, value: float | None, bound: float, *, at_least: bool) -> str | None:
    """Return a human-readable shortfall, or None when the requirement is met."""
    if value is None:
        return f"{name} tidak tersedia"
    if at_least:
        return None if value >= bound else f"{name} {_pct(value)} < {_pct(bound)}"
    return None if value < bound else f"{name} {_pct(value)} ≥ {_pct(bound)} (harus di bawah)"


def tier_shortfalls(tier: str, m: Metrics, th: Thresholds) -> list[str]:
    def g(suffix: str) -> float:
        return float(getattr(th, f"{tier}_{suffix}"))

    checks = [
        _check("Fee/TVL", m.fee_yield, g("fee_yield"), at_least=True),
        _check("net edge", m.net_edge, g("net_edge"), at_least=True),
        _check("aktivitas", m.activity, g("activity"), at_least=True),
        _check("konsentrasi", m.concentration, g("concentration"), at_least=False),
    ]
    if tier != "ideal":
        checks.append(_check("laju 6j", m.pace6h, g("pace6h"), at_least=True))
    return [c for c in checks if c is not None]


def evaluate(m: Metrics, th: Thresholds) -> Evaluation:
    for i, tier in enumerate(TIERS):
        if not tier_shortfalls(tier, m, th):
            missing = () if i == 0 else tuple(tier_shortfalls(TIERS[i - 1], m, th))
            return Evaluation(tier, RANK[tier], missing)
    return Evaluation("tolak", 0, tuple(tier_shortfalls("minimal", m, th)))


def is_recommended(label: str, security_status: str) -> bool:
    """A pool failing security ("risiko") is never recommended, whatever its label."""
    return RANK.get(label, 0) >= 1 and security_status != "risiko"
