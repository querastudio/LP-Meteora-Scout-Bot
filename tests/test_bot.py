import asyncio

import pytest
from helpers import NOW, FakePools, FakeSecurity, make_pool, make_settings

from lpscout.bot import HELP, Bot
from lpscout.http import SourceError
from lpscout.scanner import Scanner
from lpscout.store import Store

ADDR = "Fda9TrEhZD5Jx2jQJiFKPGTKxS2xxzt1mBynxHYtkPV6"


class FakeApi:
    def __init__(self):
        self.sent: list[str] = []
        self.fail_send = False
        self.polls: list[list[dict]] = []
        self.offsets: list[int | None] = []
        self.commands_set = False

    async def get_updates(self, offset, poll_seconds=5):
        self.offsets.append(offset)
        if self.polls:
            return self.polls.pop(0)
        await asyncio.sleep(10)
        return []

    async def send(self, chat_id, text):
        if self.fail_send:
            raise SourceError("telegram", "down")
        assert chat_id == 1
        self.sent.append(text)

    async def set_commands(self):
        self.commands_set = True


def msg(text, sender=1, uid=1):
    return {"update_id": uid, "message": {"from": {"id": sender}, "text": text}}


class Env:
    def __init__(self, pools=None, **settings):
        default = [make_pool("GOOD", address=ADDR, fees=15_000.0)]
        self.pools = FakePools(pools if pools is not None else default)
        self.security = FakeSecurity()
        self.settings = make_settings(**settings)
        self.store = Store(":memory:")
        self.api = FakeApi()
        self.clock_now = [float(NOW)]
        scanner = Scanner(self.pools, self.security, self.settings)
        self.bot = Bot(self.settings, self.store, scanner, self.api, clock=lambda: self.clock_now[0])

    def cmd(self, text, sender=1):
        asyncio.run(self.bot.handle_update(msg(text, sender)))
        return self.api.sent[-1] if self.api.sent else None


def test_only_the_owner_gets_answers():
    env = Env()
    assert env.cmd("/help", sender=999) is None and env.cmd("/scan", sender=999) is None
    assert env.api.sent == [] and env.pools.candle_calls == []


def test_help_start_and_unknown():
    env = Env()
    assert env.cmd("/help") == HELP and env.cmd("/start") == HELP
    n = len(env.api.sent)
    assert env.cmd("/bogus") == HELP and len(env.api.sent) == n  # unknown: silence
    assert env.cmd("hello") == HELP


def test_command_with_bot_suffix_is_understood():
    assert Env().cmd("/help@lp_scout_bot") == HELP


def test_top_before_any_scan():
    assert "/scan" in Env().cmd("/top")


def test_scan_reports_and_top_shows_it_without_touching_alert_state():
    env = Env()
    out = env.cmd("/scan")
    assert "⭐ IDEAL GOOD-SOL" in out and f"https://app.meteora.ag/dlmm/{ADDR}" in out
    assert env.store.last_scan()["kind"] == "manual"
    assert env.store.active_states() == []  # a manual scan must not swallow the next scheduled alert
    assert env.cmd("/top") == out


def test_pool_command_validates_and_inspects():
    env = Env()
    assert "Pakai" in env.cmd("/pool") and "Pakai" in env.cmd("/pool not-an-address!")
    detail = env.cmd(f"/pool {ADDR}")
    assert "GOOD-SOL" in detail and "Keamanan" in detail
    assert "Tidak bisa" in env.cmd("/pool " + "B" * 44)


def test_set_lists_changes_persists_and_rejects_garbage():
    env = Env()
    assert "min_tvl = 10000.0" in env.cmd("/set")
    assert env.cmd("/set min_tvl 25000").startswith("✅") and env.settings.thresholds.min_tvl == 25000
    assert env.store.overrides() == {"min_tvl": "25000"}
    for bad in ("/set min_tvl abc", "/set nope 1", "/set min_tvl", "/set min_tvl -1"):
        assert "Ditolak" in env.cmd(bad) or "Pakai" in env.cmd(bad)
    # a restart re-applies the saved overrides
    fresh = make_settings()
    Bot(fresh, env.store, Scanner(env.pools, env.security, fresh), env.api)
    assert fresh.thresholds.min_tvl == 25000


def test_slow_command_says_still_processing_then_delivers():
    env = Env()
    env.bot.command_timeout = 0.05
    real_scan = env.bot.scanner.scan

    async def slow_scan(*a, **kw):
        await asyncio.sleep(0.2)
        return await real_scan(*a, **kw)

    env.bot.scanner.scan = slow_scan
    asyncio.run(env.bot.handle_update(msg("/scan")))
    assert "Masih memproses" in env.api.sent[0] and "IDEAL" in env.api.sent[1]


def test_scan_while_one_is_running_is_refused():
    env = Env()

    async def go():
        async with env.bot._scan_lock:
            await env.bot.handle_update(msg("/scan"))

    asyncio.run(go())
    assert "sedang berjalan" in env.api.sent[0]


def test_failed_pool_list_is_reported_and_status_shows_the_error():
    env = Env()

    async def boom(pages):
        raise SourceError("meteora_pools", "HTTP 503")

    env.pools.get_pools = boom
    assert "Scan gagal" in env.cmd("/scan")
    assert "meteora_pools" in env.cmd("/status")


def test_status_lists_last_scan_and_failed_sources():
    env = Env()
    env.pools.fail_candles = {"pool_GOOD_100"}  # no matching address -> no effect
    env.security.failed = ("rpc",)
    env.cmd("/scan")
    status = env.cmd("/status")
    assert "Scan terakhir:" in status and "Dipindai: 1 pool" in status and "rpc×1" in status
    assert "interval 15 mnt" in status


def test_scheduled_scan_alerts_once_then_stays_quiet_then_announces_drop():
    env = Env()
    asyncio.run(env.bot.scan_and_alert())
    assert len(env.api.sent) == 1 and "⭐ IDEAL GOOD-SOL · baru lolos" in env.api.sent[0]
    env.clock_now[0] += 900
    asyncio.run(env.bot.scan_and_alert())
    assert len(env.api.sent) == 1  # same label, no duplicate
    env.pools.pools[0] = make_pool("GOOD", address=ADDR, fees=100.0)  # stops qualifying
    env.clock_now[0] += 900
    asyncio.run(env.bot.scan_and_alert())
    assert len(env.api.sent) == 2 and "keluar dari daftar aktif" in env.api.sent[1]
    env.clock_now[0] += 900
    asyncio.run(env.bot.scan_and_alert())
    assert len(env.api.sent) == 2  # drop announced only once
    assert env.store.active_states() == [] and env.store.alert_count() == 2


def test_failed_security_pool_never_alerts():
    env = Env()
    env.security.status = "risiko"
    asyncio.run(env.bot.scan_and_alert())
    assert env.api.sent == []


def test_reentry_inside_cooldown_is_held_back_then_sent():
    env = Env()
    asyncio.run(env.bot.scan_and_alert())  # alert #1
    good = env.pools.pools[0]
    env.pools.pools[0] = make_pool("GOOD", address=ADDR, fees=100.0)
    env.clock_now[0] += 600
    asyncio.run(env.bot.scan_and_alert())  # drop
    env.pools.pools[0] = good
    env.clock_now[0] += 600
    asyncio.run(env.bot.scan_and_alert())  # back, 20 min after the first alert: inside the 2h cooldown
    assert len(env.api.sent) == 2
    env.clock_now[0] += 2 * 3600
    asyncio.run(env.bot.scan_and_alert())
    assert len(env.api.sent) == 3 and "baru lolos" in env.api.sent[2]


def test_alert_that_could_not_be_sent_is_retried_next_scan():
    env = Env()
    env.api.fail_send = True
    asyncio.run(env.bot.scan_and_alert())
    assert env.api.sent == [] and env.store.alert_count() == 0
    env.api.fail_send = False
    env.clock_now[0] += 900
    asyncio.run(env.bot.scan_and_alert())
    assert len(env.api.sent) == 1


def test_scheduler_runs_a_scan_and_sets_the_next_one():
    env = Env()
    env.bot.next_scan_at = 0

    async def stop(_):
        raise asyncio.CancelledError

    env.bot._sleep = stop
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(env.bot.run_scheduler())
    assert env.store.last_scan()["kind"] == "auto"
    assert env.bot.next_scan_at == NOW + 15 * 60


def test_polling_drops_backlog_and_handles_new_commands():
    env = Env()
    env.api.polls = [[{"update_id": 5}], [msg("/help", uid=6)]]

    async def go():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(env.bot.run_polling(), 0.3)

    asyncio.run(go())
    assert env.api.offsets[:3] == [-1, 6, 7]
    assert env.api.sent == [HELP]


def test_startup_registers_the_command_menu():
    env = Env()
    env.bot.run_polling = lambda: asyncio.sleep(0)  # type: ignore[method-assign]
    env.bot.run_scheduler = lambda: asyncio.sleep(0)  # type: ignore[method-assign]
    asyncio.run(env.bot.run())
    assert env.api.commands_set
