"""Configuration: static env settings plus label/filter thresholds that can be changed at runtime (/set)."""
from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

SOL_MINT = "So11111111111111111111111111111111111111112"

DEFAULT_EXCLUDED_SYMBOLS = (
    "SOL,WSOL,USDC,USDT,USDS,PYUSD,USD1,USDE,DAI,FDUSD,UXD,"
    "BTC,WBTC,CBBTC,ETH,WETH,JUP,JTO,JITOSOL,MSOL,BSOL,JUPSOL,INF,STSOL,BNSOL,HSOL,VSOL,DSOL,BBSOL"
)

# Suggested position size per label, as a % of the user's risk limit.
SIZE_PCT = {"ideal": 100, "bagus": 75, "minimal": 50, "tolak": 0}


@dataclass
class Thresholds:
    """Label thresholds from the 211-pool Meteora backtest (Bid-Ask, -70% range). Fractions, not %."""

    ideal_fee_yield: float = 0.20
    ideal_net_edge: float = 0.10
    ideal_activity: float = 0.90
    ideal_concentration: float = 0.10  # strictly below
    bagus_fee_yield: float = 0.10
    bagus_net_edge: float = 0.05
    bagus_activity: float = 0.90
    bagus_concentration: float = 0.10
    bagus_pace6h: float = 0.50
    minimal_fee_yield: float = 0.05
    minimal_net_edge: float = 0.02
    minimal_activity: float = 0.90
    minimal_concentration: float = 0.10
    minimal_pace6h: float = 0.50
    max_top10_pct: float = 30.0  # security: top-10 holders must hold strictly less than this %
    min_bin_step: int = 80
    min_tvl: float = 10_000.0
    top_n: int = 20  # candidates (highest Fee/TVL) computed in full each scan
    scan_minutes: int = 15
    cooldown_minutes: int = 120

    def set_value(self, key: str, raw: str) -> None:
        """Parse and set one threshold from text; raises ValueError for unknown keys or bad values."""
        names = {f.name: f for f in dataclasses.fields(self)}
        if key not in names:
            raise ValueError(f"parameter tidak dikenal: {key}")
        current = getattr(self, key)
        value = int(raw) if isinstance(current, int) else float(raw)
        if value != value or value < 0:  # NaN or negative
            raise ValueError("nilai harus angka >= 0")
        if key in ("scan_minutes", "top_n") and value < 1:
            raise ValueError("nilai harus >= 1")
        setattr(self, key, value)


def _env_override(th: Thresholds, environ: Mapping[str, str]) -> Thresholds:
    for f in dataclasses.fields(th):
        raw = environ.get(f.name.upper())
        if raw not in (None, ""):
            th.set_value(f.name, str(raw))
    return th


@dataclass
class Settings:
    telegram_bot_token: str
    telegram_owner_id: int
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    db_path: str = "data/lpscout.db"
    scan_pages: int = 6  # pages of 50 pools, sorted by 24h volume
    excluded_symbols: frozenset[str] = field(default_factory=frozenset)
    thresholds: Thresholds = field(default_factory=Thresholds)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        owner = env.get("TELEGRAM_OWNER_ID", "").strip()
        if not token or not owner:
            raise ValueError("TELEGRAM_BOT_TOKEN dan TELEGRAM_OWNER_ID wajib diisi")
        symbols = env.get("EXCLUDED_SYMBOLS") or DEFAULT_EXCLUDED_SYMBOLS
        return cls(
            telegram_bot_token=token,
            telegram_owner_id=int(owner),
            rpc_url=env.get("RPC_URL") or cls.rpc_url,
            db_path=env.get("DB_PATH") or cls.db_path,
            scan_pages=int(env.get("SCAN_PAGES") or cls.scan_pages),
            excluded_symbols=frozenset(s.strip().upper() for s in symbols.split(",") if s.strip()),
            thresholds=_env_override(Thresholds(), env),
        )
