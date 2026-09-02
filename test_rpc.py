#!/usr/bin/env python3
"""Manual RPC connectivity check — verifies which RPC provider actually answers requests
and prints the raw result. Run via workflow_dispatch (test_rpc input), independent of the
bot's pause state and cooldown. Uses USDC's mint as a well-known, always-valid test token."""
import asyncio

import httpx

import config as C
from apis.token_safety import _rpc_endpoints, check_mint_freeze, get_top10_pct

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _mask(url: str) -> str:
    if "api-key=" in url:
        return url.split("api-key=")[0] + "api-key=***"
    if "/v2/" in url:
        return url.split("/v2/")[0] + "/v2/***"
    return url


async def main():
    print("RPC endpoint order (first = tried first):")
    for url in _rpc_endpoints(C.HELIUS_API_KEY, C.ALCHEMY_API_KEY):
        print(" -", _mask(url))

    async with httpx.AsyncClient(timeout=15) as client:
        print("\nchecking mint/freeze authority for USDC...")
        auth = await check_mint_freeze(client, USDC_MINT, C.HELIUS_API_KEY, C.ALCHEMY_API_KEY, enabled=True)
        print("  result:", auth)

        print("\nchecking top-10 holder % for USDC...")
        top10 = await get_top10_pct(client, USDC_MINT, C.HELIUS_API_KEY, C.ALCHEMY_API_KEY, enabled=True)
        print("  result:", top10)

    if auth.get("mint_auth") is None and auth.get("freeze_auth") is None:
        print("\n⚠️  Both RPC providers failed (result is None) — check your API keys.")
    else:
        print("\n✅ RPC call succeeded — got a real answer back.")


if __name__ == "__main__":
    asyncio.run(main())
