from lpscout.alerts import decide
from lpscout.store import Store

COOLDOWN = 2 * 3600
A = "POOL1"


def step(prev, label, now):
    return decide(prev, A, "X-SOL", label, now, COOLDOWN)


def test_new_pool_reaching_minimal_alerts_once_and_not_again():
    d = step(None, "minimal", 0)
    assert d.kind == "new" and d.state.active and d.state.alerted_rank == 1
    again = step(d.state, "minimal", 900)
    assert again.kind is None and not again.suppressed


def test_tolak_pool_never_alerts():
    d = step(None, "tolak", 0)
    assert d.kind is None and not d.state.active


def test_climbing_a_label_alerts_after_cooldown_and_not_before():
    d = step(None, "minimal", 0)
    held = step(d.state, "bagus", 900)
    assert held.kind is None and held.suppressed  # upgrade inside the 2h cooldown
    assert held.state.alerted_rank == 1  # still pending, will fire later
    later = step(held.state, "bagus", COOLDOWN + 1)
    assert later.kind == "upgrade" and later.state.alerted_rank == 2


def test_upgrade_outside_cooldown_alerts_immediately():
    d = step(None, "minimal", 0)
    up = step(d.state, "ideal", COOLDOWN + 5)
    assert up.kind == "upgrade" and up.state.label == "ideal"


def test_downgrade_stays_active_without_alert():
    d = step(None, "ideal", 0)
    down = step(d.state, "bagus", COOLDOWN + 10)
    assert down.kind is None and down.state.active and down.state.alerted_rank == 3


def test_drop_to_tolak_notifies_exactly_once_and_clears_active():
    d = step(None, "bagus", 0)
    drop = step(d.state, "tolak", 3600)
    assert drop.kind == "drop" and not drop.state.active
    assert step(drop.state, "tolak", 7200).kind is None


def test_reentry_inside_cooldown_is_suppressed_then_alerts():
    d = step(None, "bagus", 0)
    drop = step(d.state, "tolak", 600)
    back = step(drop.state, "bagus", 1200)
    assert back.kind is None and back.suppressed and back.state.active
    final = step(back.state, "bagus", COOLDOWN + 1)
    assert final.kind == "new"


def test_pool_that_was_never_announced_drops_silently():
    d = step(None, "minimal", 0)
    held = step(replace_alerted(d.state), "minimal", 10)
    assert step(held.state, "tolak", 20).kind is None


def replace_alerted(state):
    from dataclasses import replace
    return replace(state, alerted_rank=0)


def test_security_gated_pool_is_treated_as_tolak_by_callers():
    # callers pass the effective label ("tolak") for pools failing security
    d = step(None, "tolak", 0)
    assert d.kind is None


def test_store_roundtrip():
    s = Store(":memory:")
    assert s.last_scan() is None and s.get_state(A) is None
    result = {"address": A, "name": "X-SOL", "label": "bagus", "recommended": True,
              "security": {"status": "ok"}, "metrics": {"fee_yield": 0.1}}
    sid = s.record_scan("auto", 300, 20, [result], {"rpc": 2}, ts=123.0)
    last = s.last_scan()
    assert last and last["id"] == sid and last["recommended"] == 1 and last["failed"] == {"rpc": 2}
    assert last["results"][0]["address"] == A

    state = step(None, "bagus", 5).state
    s.save_state(state)
    assert s.get_state(A) == state and [x.address for x in s.active_states()] == [A]
    s.save_state(step(state, "tolak", 6).state)
    assert s.active_states() == []

    s.record_alert(A, "new", "bagus", "msg")
    assert s.alert_count() == 1
    s.set_override("min_tvl", "5000")
    s.set_override("min_tvl", "6000")
    assert s.overrides() == {"min_tvl": "6000"}
