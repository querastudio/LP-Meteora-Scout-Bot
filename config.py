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

# --- Layer 1: hard filter per-pool (CEREBRO criteria) ------------------------------
# Derived from the CEREBRO-USDG case study on the sibling Robinhood Chain (Uniswap) bot:
# a genuinely profitable pool with TVL ~$100K, Vol/TVL ~7x/day, Fee/TVL ~14-15%/day,
# base fee 2%, age 13 days. These are the minimums a Meteora DLMM pool must clear
# individually before it's even considered as a sibling-selection candidate. A field
# that's unavailable from every data source is SKIPPED for that pool, never treated as
# a failure — see filter_pool_layer1() in screener.py.
MIN_POOL_TVL        = float(os.environ.get("MIN_POOL_TVL", 10_000.0))
MIN_VOL_TVL_RATIO   = float(os.environ.get("MIN_VOL_TVL_RATIO", 2.0))     # vol_24h / tvl, e.g. 2.0 = 2x/day
MIN_FEE_TVL_PCT     = float(os.environ.get("MIN_FEE_TVL_PCT", 10.0))     # fees_24h / tvl, %/day
MIN_BASE_FEE_PCT    = float(os.environ.get("MIN_BASE_FEE_PCT", 2.0))

# Pool age is explicitly NOT a hard filter (PRD: a pool <1 day old still gets alerted,
# just with a "⚠️ Pool Baru" warning tag instead of being rejected) — see enrich_layer3_tags().
NEW_POOL_WARNING_DAYS = int(os.environ.get("NEW_POOL_WARNING_DAYS", 1))

# --- Layer 2: sibling-pool selection (per token pair, not per pool) -----------------
# Meteora often has several pools for the same token pair at different bin_step values
# (the DLMM equivalent of Uniswap fee tiers). A candidate whose volume is this lopsided
# ("jomplang") vs. the busiest sibling is skipped from the priority list even if it
# individually cleared Layer 1 — it's fragmented liquidity, not real depth. Mirrors the
# CEREBRO 2.08%/$11K-vs-2.1%/$707.8K case from the Robinhood Chain bot.
SIBLING_JOMPLANG_RATIO = float(os.environ.get("SIBLING_JOMPLANG_RATIO", 0.5))

# --- Layer 3: informational tags (never reject a pool) ------------------------------
MOMENTUM_RATIO_THRESHOLD = float(os.environ.get("MOMENTUM_RATIO_THRESHOLD", 1.5))  # vol_1h vs hourly-avg-of-24h

# --- Final gate before sending: short-term (5-minute) volume spike ------------------
# Kept deliberately loose: validation on the Robinhood Chain bot showed a $50K floor +
# 3x multiplier was far too strict — a $100K-TVL pool like CEREBRO almost never clears
# $50K inside a single 5-minute window even while genuinely "kencang".
SPIKE_FLOOR_USD          = float(os.environ.get("SPIKE_FLOOR_USD", 7_500.0))
SPIKE_MULTIPLIER         = float(os.environ.get("SPIKE_MULTIPLIER", 1.5))
# Bypass: a pool already proven "kencang" over a full 24h (high Vol/TVL AND Fee/TVL)
# skips the 5-minute check entirely, so it's never missed just because the specific
# 5-minute window it got checked in happened to be quiet.
SPIKE_BYPASS_VOL_TVL_RATIO = float(os.environ.get("SPIKE_BYPASS_VOL_TVL_RATIO", 5.0))   # 500%/day
SPIKE_BYPASS_FEE_TVL_PCT   = float(os.environ.get("SPIKE_BYPASS_FEE_TVL_PCT", 10.0))    # %/day

COOLDOWN_HOURS      = int(os.environ.get("COOLDOWN_HOURS", 6))
MAX_ALERTS_RUN      = int(os.environ.get("MAX_ALERTS_RUN", 5))
MAX_POOL_PAGES      = int(os.environ.get("MAX_POOL_PAGES", 5))  # pages of 1000 pools each

COOLDOWN_FILE       = "cooldown_cache.json"

SOL_MINT = "So11111111111111111111111111111111111111112"
