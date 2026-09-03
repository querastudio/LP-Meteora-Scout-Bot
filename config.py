import os


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name, "").strip()
    if not val:
        # Unset, or set to "" (e.g. an unconfigured GitHub Actions `vars.*` resolves to
        # an empty string rather than being absent) -> fall back to the default.
        return default
    return val.lower() in ("1", "true", "yes", "on")


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
HELIUS_API_KEY      = os.environ.get("HELIUS_API_KEY", "")
ALCHEMY_API_KEY     = os.environ.get("ALCHEMY_API_KEY", "")
BIRDEYE_API_KEY     = os.environ.get("BIRDEYE_API_KEY", "")  # optional, used for top10_pct

# Feature toggles — matikan salah satu buat hemat kuota RPC (Helius/Alchemy) kalau tidak
# perlu. Kalau dimatikan, filter terkait otomatis di-skip (tidak pernah reject pool),
# bukan bikin bot crash. Semua default ON (perilaku sama seperti sebelum toggle ini ada).
ENABLE_MINT_FREEZE_CHECK = _env_bool("ENABLE_MINT_FREEZE_CHECK", True)  # 1x getAccountInfo/pool
ENABLE_TOP10_CHECK       = _env_bool("ENABLE_TOP10_CHECK", True)        # 2x RPC call/pool
ENABLE_HOLDERS_CHECK     = _env_bool("ENABLE_HOLDERS_CHECK", True)      # s/d 10x RPC call/pool (paling boros)

MIN_MCAP            = int(os.environ.get("MIN_MCAP", 100_000))
MAX_MCAP            = int(os.environ.get("MAX_MCAP", 2_000_000))
MIN_HOLDERS         = int(os.environ.get("MIN_HOLDERS", 1000))
MAX_TOP10_PCT       = float(os.environ.get("MAX_TOP10_PCT", 30.0))
MAX_DEV_HOLD_PCT    = float(os.environ.get("MAX_DEV_HOLD_PCT", 5.0))
MIN_TOKEN_AGE_DAYS  = int(os.environ.get("MIN_TOKEN_AGE_DAYS", 0))

MIN_FEES_TVL_PCT    = float(os.environ.get("MIN_FEES_TVL_PCT", 8.0))
MIN_VOL_TVL_PCT     = float(os.environ.get("MIN_VOL_TVL_PCT", 200.0))
MAX_VOL_TVL_PCT     = float(os.environ.get("MAX_VOL_TVL_PCT", 700.0))
MIN_VOLATILITY      = float(os.environ.get("MIN_VOLATILITY", 2.0))
MAX_VOLATILITY      = float(os.environ.get("MAX_VOLATILITY", 6.0))
MIN_IN_RANGE_PCT    = float(os.environ.get("MIN_IN_RANGE_PCT", 40.0))
MIN_POOL_AGE_DAYS   = int(os.environ.get("MIN_POOL_AGE_DAYS", 0))
MAX_POOL_AGE_DAYS   = int(os.environ.get("MAX_POOL_AGE_DAYS", 20))
MIN_ACTIVE_TVL      = float(os.environ.get("MIN_ACTIVE_TVL", 3000.0))
MIN_AVG_FEES_MIN    = float(os.environ.get("MIN_AVG_FEES_MIN", 0.30))
MIN_AVG_VOL_MIN     = float(os.environ.get("MIN_AVG_VOL_MIN", 20.0))
MIN_TOTAL_LPS       = int(os.environ.get("MIN_TOTAL_LPS", 10))

MIN_BIN_STEP        = int(os.environ.get("MIN_BIN_STEP", 80))
MAX_BIN_STEP        = int(os.environ.get("MAX_BIN_STEP", 125))
MIN_BASE_FEE_PCT    = float(os.environ.get("MIN_BASE_FEE_PCT", 1.0))  # no upper bound
MAX_TOTAL_FEE_PCT   = float(os.environ.get("MAX_TOTAL_FEE_PCT", 3.0))
MIN_FEES_24H        = float(os.environ.get("MIN_FEES_24H", 500.0))
MIN_FEES_TVL_24H    = float(os.environ.get("MIN_FEES_TVL_24H", 8.0))

COOLDOWN_HOURS      = int(os.environ.get("COOLDOWN_HOURS", 6))
MAX_ALERTS_RUN      = int(os.environ.get("MAX_ALERTS_RUN", 5))
MAX_POOL_PAGES      = int(os.environ.get("MAX_POOL_PAGES", 5))  # pages of 1000 pools each

COOLDOWN_FILE       = "cooldown_cache.json"

SOL_MINT = "So11111111111111111111111111111111111111112"
