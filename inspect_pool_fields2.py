#!/usr/bin/env python3
"""One-off diagnostic #2: check whether DexScreener exposes finer-grained volume/txns data
(m5, h6, txns buys/sells) that Meteora's own API doesn't have, and whether Meteora has a
/pools/groups endpoint for fetching all sibling pools of a token pair in one call."""
import asyncio
import json

import httpx

METEORA_BASE = "https://dlmm.datapi.meteora.ag"
SOL_MINT = "So11111111111111111111111111111111111111112"


async def main():
    async with httpx.AsyncClient(timeout=20) as client:
        # 1) Get a real, active X/SOL pool's target mint to probe DexScreener with.
        r = await client.get(f"{METEORA_BASE}/pools", params={"page": 1, "page_size": 20})
        r.raise_for_status()
        pools = (r.json().get("data") or [])
        target_mint = None
        pool_name = None
        for p in pools:
            tx, ty = (p.get("token_x") or {}), (p.get("token_y") or {})
            if ty.get("address", "").lower() == SOL_MINT.lower():
                target_mint = tx.get("address")
                pool_name = p.get("name")
                break
            if tx.get("address", "").lower() == SOL_MINT.lower():
                target_mint = ty.get("address")
                pool_name = p.get("name")
                break
        print(f"Using target mint {target_mint} ({pool_name}) for DexScreener probe\n")

        if target_mint:
            print("=== DexScreener /latest/dex/tokens/{mint} ===")
            r2 = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{target_mint}")
            print(f"HTTP {r2.status_code}")
            pairs = (r2.json().get("pairs") or [])
            sol_pairs = [p for p in pairs if p.get("chainId") == "solana"] or pairs
            if sol_pairs:
                best = max(sol_pairs, key=lambda p: float((p.get("volume") or {}).get("h24") or 0))
                print("Top-level keys of best pair:", sorted(best.keys()))
                print("\nvolume:", json.dumps(best.get("volume"), indent=2))
                print("\npriceChange:", json.dumps(best.get("priceChange"), indent=2))
                print("\ntxns:", json.dumps(best.get("txns"), indent=2))
                print("\nliquidity:", json.dumps(best.get("liquidity"), indent=2))
            else:
                print("No pairs returned.")

        # 2) Check Meteora /pools/groups endpoints for sibling-pool grouping.
        print("\n\n=== Meteora /pools/groups ===")
        try:
            r3 = await client.get(f"{METEORA_BASE}/pools/groups", params={"page": 1, "page_size": 3})
            print(f"HTTP {r3.status_code}")
            print(r3.text[:1500])
        except Exception as e:
            print(f"Exception: {e}")

        if target_mint:
            lexical = "-".join(sorted([target_mint, SOL_MINT]))
            print(f"\n=== Meteora /pools/groups/{lexical} ===")
            try:
                r4 = await client.get(f"{METEORA_BASE}/pools/groups/{lexical}")
                print(f"HTTP {r4.status_code}")
                print(r4.text[:2000])
            except Exception as e:
                print(f"Exception: {e}")

            # 3) Sanity-check: how many sibling pools does this mint have just within the
            # already-fetched pool universe (no extra API call needed)?
            print(f"\n=== Sibling count for {target_mint} within first 5 pages of /pools ===")
            all_pools = []
            for page in range(1, 6):
                rp = await client.get(f"{METEORA_BASE}/pools", params={"page": page, "page_size": 1000})
                data = rp.json().get("data") or []
                all_pools.extend(data)
                if page >= int(rp.json().get("pages") or 1):
                    break
            siblings = [
                p for p in all_pools
                if target_mint in ((p.get("token_x") or {}).get("address"), (p.get("token_y") or {}).get("address"))
            ]
            print(f"Found {len(siblings)} sibling pool(s) across {len(all_pools)} total pools fetched.")
            for p in siblings:
                pc = p.get("pool_config") or {}
                print(f"  - {p.get('name')} | bin_step={pc.get('bin_step')} base_fee={pc.get('base_fee_pct')} "
                      f"tvl={p.get('tvl')} vol24h={(p.get('volume') or {}).get('24h')}")


if __name__ == "__main__":
    asyncio.run(main())
