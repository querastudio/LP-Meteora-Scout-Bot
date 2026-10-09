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

# Berapa lama nilai top10_pct per-token di-cache sebelum di-fetch ulang dari Birdeye.
# Distribusi holder jarang berubah drastis dalam hitungan menit — cache ini yang bikin
# kuota gratis Birdeye (30.000 CU/bulan, 35 CU/call) cukup dipakai walau scan tiap 5 menit.
TOP10_CACHE_TTL_HOURS = float(os.environ.get("TOP10_CACHE_TTL_HOURS", 12.0))

MIN_MCAP            = int(os.environ.get("MIN_MCAP", 100_000))
MAX_MCAP            = int(os.environ.get("MAX_MCAP", 2_000_000))
MIN_HOLDERS         = int(os.environ.get("MIN_HOLDERS", 1000))
MAX_TOP10_PCT       = float(os.environ.get("MAX_TOP10_PCT", 30.0))
MAX_DEV_HOLD_PCT    = float(os.environ.get("MAX_DEV_HOLD_PCT", 5.0))
MIN_TOKEN_AGE_DAYS  = int(os.environ.get("MIN_TOKEN_AGE_DAYS", 0))

# --- Pool entry criteria (ALL must match, otherwise no alert) ------------------------
# Mirrors the screener's "Enter" action filters. Stage A uses only data already in the
# Meteora /pools response (free, no extra API call); stage B uses GeckoTerminal per-pool
# data and runs only on each token pair's sibling-selection winner.
# Stage A (Meteora):
MIN_POOL_TVL        = float(os.environ.get("MIN_POOL_TVL", 10_000.0))        # pool.tvl_usd >= $10K
MIN_VOLUME_24H_USD  = float(os.environ.get("MIN_VOLUME_24H_USD", 100_000.0))  # pool.volume_usd[24h] >= $100K
MIN_FEE_TVL_1H_PCT  = float(os.environ.get("MIN_FEE_TVL_1H_PCT", 0.5))       # fee_tvl_ratio[1h] >= 0.005x (0.5%)
MIN_FEE_TVL_PCT     = float(os.environ.get("MIN_FEE_TVL_PCT", 10.0))         # fee_tvl_ratio[24h] >= 0.1x (10%)
# Stage B (GeckoTerminal). Unknown data FAILS these checks (strict): an alert should only
# fire when the metric is actually verified.
MIN_TRADES_1H           = int(os.environ.get("MIN_TRADES_1H", 10))                  # pool.tx_count[1h] >= 10
MIN_PRICE_CHANGE_1H_PCT = float(os.environ.get("MIN_PRICE_CHANGE_1H_PCT", -30.0))   # 1h price change >= -30%
MAX_PRICE_CHANGE_1H_PCT = float(os.environ.get("MAX_PRICE_CHANGE_1H_PCT", 50.0))    # 1h price change <= 50%
MAX_PULLBACK_24H_PCT    = float(os.environ.get("MAX_PULLBACK_24H_PCT", 30.0))       # 24h pullback from high <= 30%
MIN_PRICE_CHANGE_5M_PCT = float(os.environ.get("MIN_PRICE_CHANGE_5M_PCT", -3.0))    # 5m price change >= -3%
MAX_LIVE_CHECKS         = int(os.environ.get("MAX_LIVE_CHECKS", 12))  # cap GeckoTerminal calls/run (free tier ~30/min)

# Pool age is informational only: pools under this many days get a "Pool Baru" tag.
NEW_POOL_WARNING_DAYS = int(os.environ.get("NEW_POOL_WARNING_DAYS", 1))

# Sibling selection: pools of the same token pair at different bin_step. A candidate whose
# volume is below this fraction of the busiest sibling is "jomplang" and skipped.
SIBLING_JOMPLANG_RATIO = float(os.environ.get("SIBLING_JOMPLANG_RATIO", 0.5))

# Informational tag: 1h volume vs hourly average of 24h.
MOMENTUM_RATIO_THRESHOLD = float(os.environ.get("MOMENTUM_RATIO_THRESHOLD", 1.5))

COOLDOWN_HOURS      = int(os.environ.get("COOLDOWN_HOURS", 6))
MAX_ALERTS_RUN      = int(os.environ.get("MAX_ALERTS_RUN", 5))
MAX_POOL_PAGES      = int(os.environ.get("MAX_POOL_PAGES", 5))  # pages of 1000 pools each

COOLDOWN_FILE       = "cooldown_cache.json"

SOL_MINT = "So11111111111111111111111111111111111111112"
