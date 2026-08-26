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
        "base_fee_pct": 2.0,
        "bin_step": 100,
        "pool_age_days": 2,
        "in_range_pct": 50.0,
        "open_positions": 245,
        "in_range_pos": 122,
        "volatility": 2.57,
        "avg_fees_min": 10.65,
        "avg_vol_min": 473.0,
        "total_lps": 196,
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
    }
    shape = {"shape": "Bell / Near-peak ✅", "position": "Harga dekat puncak ✅"}
    return {"metrics": metrics, "safety": safety, "shape": shape}


async def main():
    async with httpx.AsyncClient(timeout=15) as client:
        result = fake_result()
        await send_telegram(client, build_alert(result))
        await asyncio.sleep(1)
        await send_telegram(
            client,
            build_summary(120, 1, 45, 60, 14, [result]) + "\n\n(contoh notifikasi — data fiktif untuk preview format)",
        )
    print("Test alert sent.")


if __name__ == "__main__":
    asyncio.run(main())
