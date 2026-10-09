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

## Filter design — an alert fires only if ALL of these match

Stage A uses data already in Meteora's `/pools` response (no extra API calls). Stage B
uses GeckoTerminal's free per-pool endpoints and runs only on each token pair's
sibling-selection winner (best `MAX_LIVE_CHECKS` by 24h Fee/TVL), before the costly
Birdeye/RPC token-safety calls.

| Stage | Metric | Rule | Env var | Source |
|---|---|---|---|---|
| A | Pool TVL | ≥ $10,000 | `MIN_POOL_TVL` | Meteora |
| A | 24h volume | ≥ $100,000 | `MIN_VOLUME_24H_USD` | Meteora |
| A | 1h Fee/TVL | ≥ 0.5% (0.005x) | `MIN_FEE_TVL_1H_PCT` | Meteora `fee_tvl_ratio[1h]` |
| A | 24h Fee/TVL | ≥ 10% (0.1x) | `MIN_FEE_TVL_PCT` | Meteora `fee_tvl_ratio[24h]` |
| B | 1h trades (buys+sells) | ≥ 10 | `MIN_TRADES_1H` | GeckoTerminal |
| B | 1h price change | between -30% and +50% | `MIN_/MAX_PRICE_CHANGE_1H_PCT` | GeckoTerminal |
| B | 24h pullback from high | ≤ 30% | `MAX_PULLBACK_24H_PCT` | GeckoTerminal hourly OHLCV (24 candles): (high − latest close) / high |
| B | 5m price change | ≥ -3% | `MIN_PRICE_CHANGE_5M_PCT` | GeckoTerminal |

Stage B is **strict**: if GeckoTerminal can't supply a metric (e.g. a brand-new pool not
yet indexed, or rate-limited), the pool fails rather than being alerted unverified.
Price changes are for the non-SOL token (inverted if GeckoTerminal lists it as quote).

Also applied: **one pool per token pair** (`select_best_sibling`: among Layer-A passers
whose volume is ≥ `SIBLING_JOMPLANG_RATIO` of the busiest sibling, highest base fee wins,
tie-break volume), and the existing **token safety** gate (mint/freeze authority, mcap,
holders, top-10) on the final candidates.

Informational tags (never reject): 🔥 momentum (1h volume ≥ 1.5x hourly average of 24h),
⚠️ Pool Baru (< `NEW_POOL_WARNING_DAYS`), 💡 Fee vs Drawdown.

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
