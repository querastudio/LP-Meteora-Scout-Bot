# LP Scout Bot — Meteora DLMM (Solana)

Scans Meteora DLMM X/SOL pools every 5 minutes and sends Telegram alerts for pools worth
providing liquidity to. Runs on GitHub Actions (`.github/workflows/lp_scout.yml`), with an
external cron-job.org pinger to work around GitHub's native `schedule:` cron being
unreliable.

## Architecture

- `apis/meteora.py` — fetches pools from Meteora's `datapi` REST API
  (`https://dlmm.datapi.meteora.ag`) and maps the raw `PoolResponse` schema into a flat
  metrics dict (`parse_pool_metrics`).
- `apis/token_safety.py` — per-token checks: DexScreener (volume windows, txns, price
  change), GeckoTerminal (mcap fallback), on-chain RPC (mint/freeze authority via
  Alchemy → Helius → public RPC fallback chain), Birdeye (top-10 holder concentration).
- `screener.py` — the CEREBRO filter layers (see below).
- `main.py` — orchestration: fetch → group by token pair → Layer 1 + Layer 2 (cheap, no
  API calls) → expensive per-token checks on the winner only → spike gate → Layer 3 tags
  → send.
- `utils/formatter.py` — builds the Telegram HTML alert + run-summary messages.
- `send_test_alert.py` — sends fabricated preview alerts (`workflow_dispatch` only).
- `test_screener.py` — unit tests for the filter layers (stdlib `unittest`, no extra deps).

## Filter design — CEREBRO criteria

Named after the CEREBRO-USDG case study on the sibling Robinhood Chain (Uniswap V3/V4)
bot: a genuinely profitable pool with TVL ~$100K, Vol/TVL ~7x/day, Fee/TVL ~14-15%/day,
2% base fee, age 13 days, volume still accelerating. The design principle throughout:
**a field unavailable from any data source is skipped for that one check, never treated
as a failure** — missing data isn't bad data.

### Layer 1 — hard filter, per individual pool (`screener.filter_pool_layer1`)

| Metric | Minimum | Env var | Notes |
|---|---|---|---|
| TVL | ≥ $10,000 | `MIN_POOL_TVL` | |
| Volume 24h / TVL | ≥ 2x/day | `MIN_VOL_TVL_RATIO` | |
| Fee 24h / TVL | ≥ 10%/day | `MIN_FEE_TVL_PCT` | |
| Base fee (Meteora's `pool_config.base_fee_pct`) | ≥ 2% | `MIN_BASE_FEE_PCT` | Skipped if the field is missing, not just zero |

Pool age is **not** a hard filter. A pool under `NEW_POOL_WARNING_DAYS` (default 1 day)
old still passes and gets alerted — just with a "⚠️ Pool Baru" tag (Layer 3), never a
rejection.

Active-liquidity (bin-level) Fee/TVL was investigated as a more accurate alternative to
whole-pool Fee/TVL, but **Meteora's `datapi` API exposes no bin-level or active-liquidity
data at all** (confirmed live on both `/pools` and `/pools/{address}` — same schema,
neither has anything like `in_range_pct`, `total_lps`, `volatility`, or a bin-array
endpoint). See Phase 2 backlog below.

### Layer 2 — sibling-pool selection, per token pair (`screener.select_best_sibling`)

Meteora often lists several pools for the same token pair at different `bin_step` values
(the DLMM equivalent of Uniswap fee tiers). For each pair:

1. Collect ALL sibling pools (including ones that fail Layer 1 — used only as volume
   comparables).
2. `max_volume_sibling` = highest 24h volume among all siblings.
3. A Layer-1 passer with `volume_ratio` (its volume / max_volume_sibling) below
   `SIBLING_JOMPLANG_RATIO` (default 0.5) is "jomplang" (lopsided) and dropped from the
   priority list.
4. Among the non-lopsided candidates, pick the highest base fee / bin_step, tie-break on
   volume.
5. If every candidate is lopsided, fall back to the highest-volume Layer-1 passer,
   ignoring bin_step.
6. Only that one winner per token pair is ever considered for an alert.

There's no `/pools/groups` endpoint to fetch siblings server-side (confirmed 400/404
live) — grouping is done client-side from the same bulk `/pools` fetch used for
scanning, so it costs no extra API calls.

### Layer 3 — informational tags, never a rejection reason (`screener.enrich_layer3_tags`)

- 🔥 **Momentum naik** — volume 1h vs. the token's own hourly-average-of-24h, shown when
  the ratio clears `MOMENTUM_RATIO_THRESHOLD` (default 1.5x).
- ⚠️ **Pool Baru** — pool age < `NEW_POOL_WARNING_DAYS`.
- 💡 **Fee vs Drawdown** — Fee/TVL vs. 24h price drawdown, when DexScreener's
  `priceChange.h24` is available and negative. Dormant (not shown) otherwise.

### Final gate — short-term volume spike (`main.passes_spike_gate`)

Before sending, the pool's 5-minute volume (DexScreener's finest granularity — Meteora
itself has no `5m` window) must be:

- ≥ `SPIKE_FLOOR_USD` (default $7,500 — deliberately low; a $50K floor was validated as
  far too strict on the Robinhood Chain bot, since a $100K-TVL pool rarely clears $50K in
  a single 5-minute window even while genuinely active), **and**
- ≥ `SPIKE_MULTIPLIER`x (default 1.5x) the token's own average 5-minute volume
  (`volume_h1 / 12` as the baseline).

**Bypass**: a pool already proven "kencang" over a full 24h — `Vol/TVL ≥
SPIKE_BYPASS_VOL_TVL_RATIO` (default 5x/day) **and** `Fee/TVL ≥
SPIKE_BYPASS_FEE_TVL_PCT` (default 10%/day) — skips this check entirely
(`screener.is_proven_by_pool_quality`), so a proven pool is never missed just because the
specific window it got checked in happened to be quiet.

### Token safety (separate axis, applied only to the Layer 2 winner)

Mint/freeze authority, market cap range, holder count, top-10 concentration
(`screener.check_token_safety`) — unchanged from the bot's original design, but now runs
**only on each pair's Layer 2 winner** instead of every candidate pool, since it's the
expensive part (Birdeye/RPC calls).

## Phase 2 backlog (confirmed unavailable, not attempted)

- **Bin-level / active-liquidity data.** No endpoint on Meteora's `datapi` exposes
  per-bin liquidity or active-bin position — whole-pool TVL is the only TVL figure
  available for Fee/TVL.
- **`in_range_pct` / `open_positions` / `total_lps` / `volatility`.** Present in some
  third-party tools' UI (e.g. a screenshot the user shared showing "Total LPs",
  "Volatility", "Positions Created") but not reproducible from Meteora's own API, Jupiter,
  Birdeye, or DexScreener in live testing — likely computed by that tool from its own
  historical/on-chain indexing, not a public API field.
- **`/pools/groups` sibling endpoint.** Returns 400/404 live; sibling grouping is done
  client-side instead (see Layer 2).

## Environment variables

See `config.py` for the full list with inline comments; all CEREBRO thresholds above have
a corresponding env var with the same default shown in the table.
