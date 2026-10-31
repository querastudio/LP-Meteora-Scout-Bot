"""Pure alert decision: alert only when a pool newly reaches (or climbs to) a recommended label,
with a per-pool cooldown; notify once when it falls out of the active list."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .labels import RANK


@dataclass(frozen=True)
class PoolState:
    address: str
    name: str = ""
    label: str = "tolak"  # effective label at the last evaluation (security-gated)
    active: bool = False  # currently recommended (label >= minimal and security not failed)
    alerted_rank: int = 0  # highest rank already announced since the pool last entered the list
    last_alert_at: float | None = None


@dataclass(frozen=True)
class Decision:
    state: PoolState
    kind: str | None  # "new" | "upgrade" | "drop" | None
    suppressed: bool = False  # would have alerted, but the cooldown held it back


def decide(prev: PoolState | None, address: str, name: str, effective_label: str,
           now: float, cooldown_seconds: float) -> Decision:
    state = prev or PoolState(address=address)
    rank = RANK.get(effective_label, 0)

    if rank == 0:
        kind = "drop" if state.alerted_rank > 0 else None
        return Decision(replace(state, name=name, label="tolak", active=False, alerted_rank=0), kind)

    state = replace(state, name=name, label=effective_label, active=True)
    if rank <= state.alerted_rank:
        return Decision(state, None)
    if state.last_alert_at is not None and now - state.last_alert_at < cooldown_seconds:
        return Decision(state, None, suppressed=True)  # alerted_rank unchanged -> retried next scan
    kind = "new" if state.alerted_rank == 0 else "upgrade"
    return Decision(replace(state, alerted_rank=rank, last_alert_at=now), kind)
