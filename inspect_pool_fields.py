#!/usr/bin/env python3
"""One-off diagnostic: dump the raw JSON of a single pool from the Meteora datapi /pools
endpoint, to check for fields (top10 holder %, total LPs, volatility, positions, net
deposits) that might exist in the live response but aren't documented in the unofficial
Go client's openapi.json this bot's field-mapping was originally based on."""
import asyncio
import json

import httpx

BASE = "https://dlmm.datapi.meteora.ag"


async def main():
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{BASE}/pools", params={"page": 1, "page_size": 3})
        r.raise_for_status()
        body = r.json()
        pools = body.get("data") or []
        print(f"Got {len(pools)} pools. Top-level keys of pool #1:")
        if pools:
            print(sorted(pools[0].keys()))
            print("\nFull JSON of pool #1:")
            print(json.dumps(pools[0], indent=2))

            addr = pools[0].get("address")
            if addr:
                print(f"\n\n=== Now checking /pools/{addr} (single-pool endpoint) ===")
                r2 = await client.get(f"{BASE}/pools/{addr}")
                print(f"HTTP {r2.status_code}")
                if r2.status_code == 200:
                    single = r2.json()
                    print("Top-level keys:", sorted(single.keys()))
                    # diff against the list-endpoint keys
                    extra = set(single.keys()) - set(pools[0].keys())
                    print("Keys present in single-pool response but NOT in list response:", extra)


if __name__ == "__main__":
    asyncio.run(main())
