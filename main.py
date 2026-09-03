#!/usr/bin/env python3
import asyncio

import httpx

import config as C
from apis.meteora import get_all_pools, parse_pool_metrics
from apis.telegram_commands import process_commands
from apis.token_safety import get_token_safety
from screener import run_all_filters
from utils.cooldown import clean_old_entries, is_on_cooldown, load_cache, mark_sent, save_cache
from utils.formatter import build_alert, build_summary
from utils.state import load_state, save_state

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


async def process_pool(client: httpx.AsyncClient, pool: dict, cache: dict):
    m = parse_pool_metrics(pool)

    if m["mint_y"].lower() != C.SOL_MINT.lower():
        return None
    if not m["address"] or not m["mint_x"]:
        return None
    if is_on_cooldown(m["address"], cache):
        return None

    # Cheap pre-filter before hitting token-safety / RPC APIs.
    if m["fees_tvl_pct"] < C.MIN_FEES_TVL_PCT * 0.7:
        return None
    if m["tvl"] < C.MIN_ACTIVE_TVL * 0.5:
        return None

    safety = await get_token_safety(
        client,
        m["mint_x"],
        C.HELIUS_API_KEY,
        C.MIN_HOLDERS,
        C.ALCHEMY_API_KEY,
        enable_mint_freeze_check=C.ENABLE_MINT_FREEZE_CHECK,
        enable_top10_check=C.ENABLE_TOP10_CHECK,
        enable_holders_check=C.ENABLE_HOLDERS_CHECK,
        birdeye_key=C.BIRDEYE_API_KEY,
    )

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

    # No bin-level liquidity data is exposed by the new datapi /pools endpoint, so the
    # "Liquidity Shape" bonus check is always skipped (classify_liquidity_shape no-ops on []).
    result = run_all_filters(pool, safety, bins=[])
    return result


async def main():
    state = load_state()
    cache = clean_old_entries(load_cache())

    async with httpx.AsyncClient(timeout=20) as client:
        await process_commands(client, C.TELEGRAM_BOT_TOKEN, C.TELEGRAM_CHAT_ID, state)
        save_state(state)

        if state.get("paused"):
            print("Bot is paused (send /resume in Telegram to continue). Skipping scan.")
            return

        try:
            pools = await get_all_pools(client, max_pages=C.MAX_POOL_PAGES)
        except Exception as e:
            print(f"Failed to fetch pools: {e}")
            return

        passed_results = []
        total_scanned = 0
        fail_safety = fail_pool = fail_fee = 0

        for i in range(0, len(pools), BATCH_SIZE):
            batch = pools[i : i + BATCH_SIZE]
            results = await asyncio.gather(
                *[process_pool(client, p, cache) for p in batch],
                return_exceptions=True,
            )
            for res in results:
                if not isinstance(res, dict):
                    continue
                total_scanned += 1
                if not res["l1_ok"]:
                    fail_safety += 1
                elif not res["l2_ok"]:
                    fail_pool += 1
                elif not res["l3_ok"]:
                    fail_fee += 1
                elif res["passed"]:
                    passed_results.append(res)

        passed_results.sort(key=lambda r: r["metrics"]["fees_tvl_pct"], reverse=True)

        alerts_sent = 0
        for result in passed_results[: C.MAX_ALERTS_RUN]:
            addr = result["metrics"]["address"]
            await send_telegram(client, build_alert(result))
            mark_sent(addr, cache)
            alerts_sent += 1
            await asyncio.sleep(1)

        await send_telegram(
            client,
            build_summary(total_scanned, len(passed_results), fail_safety, fail_pool, fail_fee, passed_results[:3]),
        )

    save_cache(cache)
    print(f"Done. Scanned: {total_scanned}, Passed: {len(passed_results)}, Alerts sent: {alerts_sent}")


if __name__ == "__main__":
    asyncio.run(main())
