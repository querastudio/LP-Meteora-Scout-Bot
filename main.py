#!/usr/bin/env python3
import asyncio
import collections

import httpx

import config as C
from apis.meteora import get_all_pools, parse_pool_metrics
from apis.telegram_commands import process_commands
from apis.token_safety import get_token_safety
from apis.geckoterminal_pool import get_live_stats
from screener import check_token_safety, enrich_layer3_tags, filter_pool_live, select_best_sibling
from utils.cooldown import clean_old_entries, is_on_cooldown, load_cache, mark_sent, save_cache
from utils.formatter import build_alert, build_summary
from utils.state import load_state, save_state
from utils.token_safety_cache import get_cached_top10, load_cache as load_top10_cache, prune as prune_top10_cache
from utils.token_safety_cache import save_cache as save_top10_cache, set_cached_top10

TELEGRAM_API = f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}"
BATCH_SIZE = 20


async def send_telegram(client: httpx.AsyncClient, text: str):
    try:
        r = await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": C.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Telegram send failed: {e}")


def group_by_token_pair(pools_raw: list[dict]) -> dict[str, list[dict]]:
    """Group parsed X/SOL pool metrics by the non-SOL mint — all sibling bin_step/fee-tier
    pools of the same token pair land in the same bucket. No extra API call needed since
    Meteora has no /pools/groups endpoint (confirmed 400/404 live) — this is done entirely
    from the already-fetched /pools list."""
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for pool_raw in pools_raw:
        m = parse_pool_metrics(pool_raw)
        if m["mint_y"].lower() != C.SOL_MINT.lower():
            continue
        if not m["address"] or not m["mint_x"]:
            continue
        groups[m["mint_x"]].append(m)
    return groups


async def enrich_winner(client: httpx.AsyncClient, m: dict, top10_cache: dict) -> dict:
    """Expensive per-token checks (Birdeye/RPC token safety + DexScreener) — run ONLY on
    the per-pair Layer 2 winner, never on every candidate pool, to keep API usage bounded."""
    cached_top10 = get_cached_top10(top10_cache, m["mint_x"], C.TOP10_CACHE_TTL_HOURS)
    fetch_top10 = C.ENABLE_TOP10_CHECK and cached_top10 is None

    safety = await get_token_safety(
        client,
        m["mint_x"],
        C.HELIUS_API_KEY,
        C.MIN_HOLDERS,
        C.ALCHEMY_API_KEY,
        enable_mint_freeze_check=C.ENABLE_MINT_FREEZE_CHECK,
        enable_top10_check=fetch_top10,
        enable_holders_check=C.ENABLE_HOLDERS_CHECK,
        birdeye_key=C.BIRDEYE_API_KEY,
    )

    if cached_top10 is not None:
        safety["top10_pct"] = cached_top10
    elif safety.get("top10_pct") is not None:
        set_cached_top10(top10_cache, m["mint_x"], safety["top10_pct"])

    # The Meteora datapi already gives us holders/freeze-authority/market-cap on the pool
    # object itself (per-token) — prefer that over the Helius/DexScreener best-effort values.
    if m["target_holders"] is not None:
        safety["holders"] = m["target_holders"]
    if m["target_freeze_disabled"] is not None:
        safety["freeze_auth"] = not m["target_freeze_disabled"]
    if m["target_mcap"]:
        safety["mcap"] = m["target_mcap"]
    safety["symbol"] = safety.get("symbol") or m["target_symbol"]
    safety["name"] = safety.get("name") or m["target_name"]

    return safety


async def fetch_live_stats(client: httpx.AsyncClient, m: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:  # GeckoTerminal's free tier is ~30 req/min; keep calls gentle
        stats = await get_live_stats(client, m["address"], m["mint_x"])
        await asyncio.sleep(1.0)
        return stats


async def main():
    state = load_state()
    cache = clean_old_entries(load_cache())
    top10_cache = prune_top10_cache(load_top10_cache(), max_age_hours=C.TOP10_CACHE_TTL_HOURS * 2)

    async with httpx.AsyncClient(timeout=20) as client:
        await process_commands(client, C.TELEGRAM_BOT_TOKEN, C.TELEGRAM_CHAT_ID, state)
        save_state(state)

        if state.get("paused"):
            print("Bot is paused (send /resume in Telegram to continue). Skipping scan.")
            return

        try:
            pools_raw = await get_all_pools(client, max_pages=C.MAX_POOL_PAGES)
        except Exception as e:
            print(f"Failed to fetch pools: {e}")
            return

        groups = group_by_token_pair(pools_raw)
        total_scanned = sum(len(v) for v in groups.values())

        # Layer 1 (hard filter) + Layer 2 (sibling selection) run cheaply on already-fetched
        # data, no API calls — only the per-pair winner goes on to expensive checks below.
        winners = []
        fail_layer1 = 0
        skipped_cooldown = 0
        for mint_x, siblings in groups.items():
            winner, sibling_info = select_best_sibling(siblings)
            if winner is None:
                fail_layer1 += 1
                continue
            if is_on_cooldown(winner["address"], cache):
                skipped_cooldown += 1
                continue
            winners.append((winner, sibling_info))

        # Stage B: live GeckoTerminal metrics on the best candidates only (free, but rate
        # limited), BEFORE the costly Birdeye/RPC token-safety calls.
        winners.sort(key=lambda w: w[0]["fees_tvl_pct"], reverse=True)
        sem = asyncio.Semaphore(2)
        checked = winners[: C.MAX_LIVE_CHECKS]
        live_results = await asyncio.gather(
            *[fetch_live_stats(client, m, sem) for m, _ in checked], return_exceptions=True
        )
        live_passed = []
        fail_live = 0
        for (m, sibling_info), live in zip(checked, live_results):
            if not isinstance(live, dict):
                fail_live += 1
                continue
            ok, fails = filter_pool_live(live)
            if not ok:
                fail_live += 1
                print(f"[skip] {m['name']} {m['address'][:6]}: {'; '.join(fails)}")
                continue
            live_passed.append((m, sibling_info, live))

        enriched = []
        fail_safety = 0
        for i in range(0, len(live_passed), BATCH_SIZE):
            batch = live_passed[i : i + BATCH_SIZE]
            results = await asyncio.gather(
                *[enrich_winner(client, m, top10_cache) for m, _, _ in batch],
                return_exceptions=True,
            )
            for (m, sibling_info, live), safety in zip(batch, results):
                if not isinstance(safety, dict):
                    continue
                safety_ok, _ = check_token_safety(safety)
                if not safety_ok:
                    fail_safety += 1
                    continue
                # Live per-pool stats take precedence over the token-level DexScreener values.
                safety.update({k: v for k, v in live.items() if v is not None})
                enriched.append({
                    "metrics": m,
                    "safety": safety,
                    "sibling": sibling_info,
                    "live": live,
                    "tags": enrich_layer3_tags(m, live),
                })

        enriched.sort(key=lambda r: r["metrics"]["fees_tvl_pct"], reverse=True)

        alerts_sent = 0
        for result in enriched[: C.MAX_ALERTS_RUN]:
            addr = result["metrics"]["address"]
            await send_telegram(client, build_alert(result))
            mark_sent(addr, cache)
            alerts_sent += 1
            await asyncio.sleep(1)

        await send_telegram(
            client,
            build_summary(total_scanned, len(enriched), fail_layer1, fail_live, fail_safety, skipped_cooldown, enriched[:3]),
        )

    save_cache(cache)
    save_top10_cache(top10_cache)
    print(
        f"Done. Scanned: {total_scanned}, Token pairs: {len(groups)}, "
        f"Winners passed: {len(enriched)}, Alerts sent: {alerts_sent}"
    )


if __name__ == "__main__":
    asyncio.run(main())
