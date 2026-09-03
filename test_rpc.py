#!/usr/bin/env python3
"""Manual RPC connectivity check — probes each RPC provider individually and prints the raw
HTTP status + response body for every call, so failures are visible instead of silently
swallowed by the normal fallback chain. Run via workflow_dispatch (test_rpc input),
independent of the bot's pause state and cooldown. Uses USDC's mint as a well-known,
always-valid test token."""
import asyncio
import json

import httpx

import config as C
from apis.token_safety import _rpc_endpoints

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _mask(url: str) -> str:
    if "api-key=" in url:
        return url.split("api-key=")[0] + "api-key=***"
    if "/v2/" in url:
        return url.split("/v2/")[0] + "/v2/***"
    return url


async def probe(client: httpx.AsyncClient, label: str, url: str, payload: dict):
    print(f"\n--- {label} -> {_mask(url)}")
    try:
        r = await client.post(url, json=payload)
        print(f"    HTTP {r.status_code}")
        try:
            body = r.json()
        except Exception:
            print(f"    (non-JSON body) {r.text[:300]}")
            return
        if "error" in body:
            print(f"    RPC error: {json.dumps(body['error'])[:300]}")
        else:
            print(f"    OK: {json.dumps(body.get('result'))[:300]}")
    except httpx.HTTPStatusError as e:
        print(f"    HTTP error: {e}")
    except Exception as e:
        print(f"    Exception: {type(e).__name__}: {e}")


async def main():
    endpoints = _rpc_endpoints(C.HELIUS_API_KEY, C.ALCHEMY_API_KEY)
    print("RPC endpoint order (first = tried first):")
    for url in endpoints:
        print(" -", _mask(url))

    largest_payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenLargestAccounts",
        "params": [USDC_MINT, {"commitment": "confirmed"}],
    }
    supply_payload = {"jsonrpc": "2.0", "id": 2, "method": "getTokenSupply", "params": [USDC_MINT]}
    account_payload = {
        "jsonrpc": "2.0", "id": 3,
        "method": "getAccountInfo",
        "params": [USDC_MINT, {"encoding": "jsonParsed"}],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        for i, url in enumerate(endpoints):
            label = f"endpoint #{i + 1}"
            await probe(client, f"{label} getAccountInfo", url, account_payload)
            await probe(client, f"{label} getTokenLargestAccounts", url, largest_payload)
            await probe(client, f"{label} getTokenSupply", url, supply_payload)

    print("\nDone. Look above for the first endpoint where getTokenLargestAccounts/getTokenSupply return 'OK' with real data.")


if __name__ == "__main__":
    asyncio.run(main())
