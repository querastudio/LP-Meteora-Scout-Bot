"""Shared fakes for scanner/bot tests."""
from lpscout.http import SourceError
from lpscout.metrics import Candle, window_start
from lpscout.settings import SOL_MINT, Settings
from lpscout.sources.meteora import Pool, Token
from lpscout.sources.security import SecurityResult

NOW = 1_800_000_400


def make_settings(**kw) -> Settings:
    s = Settings(
        telegram_bot_token="t", telegram_owner_id=1,
        excluded_symbols=frozenset({"USDC", "JUP"}),
    )
    for k, v in kw.items():
        s.thresholds.set_value(k, str(v))
    return s


def make_pool(symbol="AAA", address=None, bin_step=100, tvl=50_000.0, fees=12_000.0, protocol=0.0,
              freeze=True, blacklisted=False, sol_first=False, created_at=NOW - 5 * 86400) -> Pool:
    addr = address or f"pool_{symbol}_{bin_step}"
    tok = Token(address=f"mint_{symbol}", symbol=symbol, freeze_disabled=freeze)
    sol = Token(address=SOL_MINT, symbol="SOL", freeze_disabled=True)
    x, y = (sol, tok) if sol_first else (tok, sol)
    return Pool(address=addr, name=f"{symbol}-SOL", token_x=x, token_y=y, bin_step=bin_step, tvl=tvl,
                volume_24h=500_000.0, fees_24h=fees, protocol_fees_24h=protocol, created_at=created_at,
                blacklisted=blacklisted)


def busy_candles(price=lambda i: 1.0, volume=lambda i: 300.0) -> list[Candle]:
    t0 = window_start(NOW)
    return [Candle(ts=t0 + i * 300, close=price(i // 3), volume=volume(i // 3) / 3) for i in range(96 * 3)]


class FakePools:
    def __init__(self, pools, candles=None, fail_candles=()):
        self.pools = pools
        self.candles = candles or {}
        self.fail_candles = set(fail_candles)
        self.candle_calls: list[str] = []

    async def get_pools(self, pages):
        return list(self.pools)

    async def get_pool(self, address):
        for p in self.pools:
            if p.address == address:
                return p
        raise SourceError("meteora_pools", "pool tidak ditemukan")

    async def get_candles(self, address, now):
        self.candle_calls.append(address)
        if address in self.fail_candles:
            raise SourceError("meteora_ohlcv", "HTTP 503")
        return self.candles.get(address, busy_candles())


class FakeSecurity:
    def __init__(self, status="ok", failed=()):
        self.status = status
        self.failed = tuple(failed)
        self.calls: list[str] = []

    async def check(self, mint, meteora_freeze_disabled, max_top10_pct):
        self.calls.append(mint)
        reasons = ("freeze authority aktif",) if self.status == "risiko" else ()
        return SecurityResult(self.status, reasons, 12.0, failed_sources=self.failed)
