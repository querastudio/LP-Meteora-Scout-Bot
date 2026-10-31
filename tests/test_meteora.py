import asyncio
import json
from pathlib import Path

import httpx

from lpscout.sources.meteora import MeteoraClient, parse_candles, parse_pool, parse_pools_page

FIX = Path(__file__).parent / "fixtures"
SOL = "So11111111111111111111111111111111111111112"


def load(name):
    return json.loads((FIX / name).read_text())


def test_parse_real_pools_page():
    pools, pages = parse_pools_page(load("pools_page.json"))
    assert pages >= 1 and len(pools) == 4
    p = next(x for x in pools if x.name == "HYPE-SOL")
    assert p.target is not None and p.target.symbol == "HYPE"
    assert p.bin_step > 0 and p.tvl > 0 and p.volume_24h > 0
    assert p.created_at and p.created_at < 10_000_000_000  # seconds, not ms
    assert p.fee_yield is not None and p.fee_yield >= 0
    assert p.age_days(p.created_at + 86400 * 3) == 3


def test_sol_on_either_side_gives_the_other_as_target():
    pools, _ = parse_pools_page(load("pools_page.json"))
    sol_hype = next(x for x in pools if x.name == "SOL-HYPE")
    assert sol_hype.token_x.address == SOL and sol_hype.target is not None
    assert sol_hype.target.symbol == "HYPE"


def test_single_pool_has_same_schema_as_list_item():
    single = parse_pool(load("pool_single.json"))
    listed = parse_pool(load("pools_page.json")["data"][0])
    assert single.address == listed.address and single.bin_step == listed.bin_step


def test_pool_without_sol_has_no_target():
    raw = load("pool_single.json")
    raw["token_x"]["address"] = "A" * 32
    raw["token_y"]["address"] = "B" * 32
    assert parse_pool(raw).target is None


def test_missing_fields_become_none_not_zero_or_crash():
    p = parse_pool({"address": "x", "token_x": {}, "token_y": {}})
    assert p.fees_24h is None and p.fee_yield is None and p.created_at is None
    assert p.age_days(1_800_000_000) is None


def test_parse_real_candles():
    candles = parse_candles(load("ohlcv_8h.json"))
    assert len(candles) > 90 and all(c.close > 0 for c in candles)
    assert candles[1].ts - candles[0].ts == 300


def test_parse_candles_skips_malformed_rows():
    rows = [{"timestamp": 1}, {"timestamp": 2, "close": 1, "volume": None}]
    parsed = parse_candles({"data": rows})
    assert len(parsed) == 1 and parsed[0].volume == 0.0


def test_client_fetches_three_contiguous_8h_windows_and_caches():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=load("ohlcv_8h.json"))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            m = MeteoraClient(c)
            await m.get_candles("ADDR", 1_800_000_000)
            await m.get_candles("ADDR", 1_800_000_000)

    asyncio.run(go())
    assert len(requests) == 3  # second call served from cache
    spans = sorted((int(r.url.params["start_time"]), int(r.url.params["end_time"])) for r in requests)
    assert all(e - s == 8 * 3600 for s, e in spans)
    assert spans[0][1] == spans[1][0] and spans[1][1] == spans[2][0] and spans[2][1] == 1_800_000_000
    assert all(r.url.params["timeframe"] == "5m" for r in requests)


def test_client_pool_list_params_pagination_and_cache():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=load("pools_page.json"))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            m = MeteoraClient(c)
            first = await m.get_pools(2)
            await m.get_pools(2)
            return first

    pools = asyncio.run(go())
    assert len(requests) == 2 and len(pools) == 8
    assert requests[0].url.params["sort_by"] == "volume_24h:desc"
    assert requests[0].url.params["page_size"] == "50"
