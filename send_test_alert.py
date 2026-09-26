#!/usr/bin/env python3
"""Send a sample POOL ALERT + summary message to Telegram to preview the format.
Uses fabricated data — not a real scan. Run manually via workflow_dispatch."""
import asyncio

import httpx

import config as C
from utils.formatter import build_alert, build_summary

TELEGRAM_API = f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}"


async def send_telegram(client: httpx.AsyncClient, text: str):
    r = await client.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": C.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    print("Telegram response:", r.status_code, r.text[:300])
    r.raise_for_status()


def fake_result():
    metrics = {
        "address": "5hbf9JP8k5zdrZp9pokPypFQoBse5mGCmW6nqodurGcd",
        "name": "MORTY-SOL",
        "mint_x": "MoRtYxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "mint_y": C.SOL_MINT,
        "tvl": 118800.0,
        "fees_24h": 15200.0,
        "vol_24h": 682000.0,
        "fees_tvl_pct": 12.91,
        "vol_tvl_pct": 574.0,
        "vol_tvl_ratio": 5.74,
        "base_fee_pct": 2.0,
        "bin_step": 100,
        "pool_age_days": 13,
        "net_deposits": -22000.0,
        "current_price": 1.0,
    }
    safety = {
        "symbol": "MORTY",
        "mcap": 654000,
        "holders": 2060,
        "top10_pct": 18.7,
        "mint_auth": False,
        "freeze_auth": False,
        "token_age_days": 5,
        "dex_url": "",
        "volume_h6": 195000.0,
        "buys_24h": 4210,
        "sells_24h": 3860,
    }
    sibling = {
        "sibling_count": 3,
        "volume_ratio": 1.0,
        "beaten_siblings": 2,
        "fallback_all_jomplang": False,
    }
    tags = {"momentum": 1.8, "new_pool": False, "fee_vs_drawdown": 2.3}
    return {"metrics": metrics, "safety": safety, "sibling": sibling, "tags": tags}


def fake_new_pool_result():
    """A second preview case: a pool <1 day old — should show the ⚠️ Pool Baru tag and
    still be alertable, never rejected, per the PRD's acceptance criteria."""
    result = fake_result()
    result["metrics"] = dict(result["metrics"], pool_age_days=0, address="NewPoo1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    result["tags"] = {"momentum": None, "new_pool": True, "fee_vs_drawdown": None}
    result["sibling"] = {"sibling_count": 1, "volume_ratio": 1.0, "beaten_siblings": 0, "fallback_all_jomplang": False}
    return result


async def main():
    async with httpx.AsyncClient(timeout=15) as client:
        result = fake_result()
        await send_telegram(client, build_alert(result))
        await asyncio.sleep(1)
        await send_telegram(client, build_alert(fake_new_pool_result()))
        await asyncio.sleep(1)
        await send_telegram(
            client,
            build_summary(120, 2, 45, 8, 14, [result])
            + "\n\n(contoh notifikasi — data fiktif untuk preview format)",
        )
    print("Test alert sent.")


if __name__ == "__main__":
    asyncio.run(main())
