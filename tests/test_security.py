import asyncio
import json
import random

import httpx

from lpscout.sources.security import (
    SecurityClient,
    b58decode,
    evaluate_security,
    is_on_curve,
    parse_authorities,
    parse_rugcheck_risks,
    top_holders_pct,
    wallet_is_on_curve,
)

P = 2**255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + out


def rfc8032_on_curve(b: bytes) -> bool:
    """Independent reference (RFC 8032 recover_x, square root via exponent (p+3)/8)."""
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    sign = b[31] >> 7
    if y >= P:
        return False
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return sign == 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * pow(2, (P - 1) // 4, P) % P
    return (x * x - x2) % P == 0


def keys(on_curve: bool, n: int, seed: int) -> list[str]:
    rnd = random.Random(seed)
    out: list[str] = []
    while len(out) < n:
        b = rnd.randbytes(32)
        if rfc8032_on_curve(b) == on_curve:
            out.append(b58encode(b))
    return out


WALLETS = keys(True, 4, 1)
PDAS = keys(False, 2, 2)


def test_is_on_curve_matches_independent_reference():
    rnd = random.Random(7)
    seen = set()
    for _ in range(300):
        b = rnd.randbytes(32)
        assert is_on_curve(b) == rfc8032_on_curve(b)
        seen.add(is_on_curve(b))
    assert seen == {True, False}


def test_b58_roundtrip_and_bad_input():
    assert b58decode(WALLETS[0]) == b58decode(b58encode(b58decode(WALLETS[0])))
    assert len(b58decode(WALLETS[0])) == 32
    assert wallet_is_on_curve(WALLETS[0]) is True and wallet_is_on_curve(PDAS[0]) is False
    assert wallet_is_on_curve("0OIl") is None  # not base58


def test_top_holders_ignores_pdas_and_sums_per_owner():
    largest = [{"address": f"acc{i}", "amount": str(a)} for i, a in enumerate([600, 100, 50, 30])]
    owners = {"acc0": PDAS[0], "acc1": WALLETS[0], "acc2": WALLETS[1], "acc3": WALLETS[0]}
    assert top_holders_pct(largest, owners, 1000) == 18.0  # (100+30) + 50, pool PDA excluded
    assert top_holders_pct(largest, owners, 1000, top_n=1) == 13.0


def test_top_holders_unknown_owner_is_none_not_a_guess():
    assert top_holders_pct([{"address": "a", "amount": "5"}], {}, 100) is None
    assert top_holders_pct([{"address": "a", "amount": "5"}], {"a": WALLETS[0]}, 0) is None


def test_parse_authorities():
    ok = {"value": {"data": {"parsed": {"info": {"mintAuthority": None, "freezeAuthority": None}}}}}
    bad = {"value": {"data": {"parsed": {"info": {"mintAuthority": "X", "freezeAuthority": "Y"}}}}}
    assert parse_authorities(ok) == (True, True)
    assert parse_authorities(bad) == (False, False)
    assert parse_authorities(None) == (None, None)
    assert parse_authorities({"value": None}) == (None, None)


def test_evaluate_security():
    assert evaluate_security(True, True, 12.0, 30).status == "ok"
    assert evaluate_security(False, True, 12.0, 30).status == "risiko"
    assert evaluate_security(True, False, 12.0, 30).status == "risiko"
    assert evaluate_security(True, True, 30.0, 30).status == "risiko"  # must be strictly below
    assert evaluate_security(True, True, None, 30).status == "belum terverifikasi"
    assert evaluate_security(None, None, None, 30).status == "belum terverifikasi"
    # a known failure wins over unknowns
    assert evaluate_security(False, None, None, 30).status == "risiko"


def test_rugcheck_notes_only_danger_and_tolerate_garbage():
    payload = {
        "risks": [
            {"name": "Mutable metadata", "level": "warn"},
            {"name": "Top 10 holders", "level": "danger"},
        ]
    }
    assert parse_rugcheck_risks(payload) == ("Top 10 holders",)
    assert parse_rugcheck_risks("nope") == () and parse_rugcheck_risks({"risks": 3}) == ()


# --- client, with JSON-RPC payloads shaped per the Solana RPC spec (real RPC is unreachable from CI sandbox)
def rpc_handler(mint_auth=None, freeze_auth=None, largest_error=False, rugcheck_status=200, log=None):
    accounts = [{"address": f"acc{i}", "amount": str(a), "decimals": 6} for i, a in enumerate([600, 100, 50])]
    owners = [PDAS[0], WALLETS[0], WALLETS[1]]

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(str(request.url))
        if "rugcheck" in request.url.host:
            risks = {"risks": [{"name": "Low liquidity", "level": "danger"}]}
            return httpx.Response(rugcheck_status, json=risks)
        body = json.loads(request.content)
        method = body["method"]
        if method == "getAccountInfo":
            info = {"mintAuthority": mint_auth, "freezeAuthority": freeze_auth}
            return httpx.Response(200, json={"result": {"value": {"data": {"parsed": {"info": info}}}}})
        if method == "getTokenSupply":
            return httpx.Response(200, json={"result": {"value": {"amount": "1000", "decimals": 6}}})
        if method == "getTokenLargestAccounts":
            if largest_error:
                return httpx.Response(200, json={"error": {"code": -32001, "message": "Unable to complete"}})
            return httpx.Response(200, json={"result": {"value": accounts}})
        if method == "getMultipleAccounts":
            value = [{"data": {"parsed": {"info": {"owner": o}}}} for o in owners]
            return httpx.Response(200, json={"result": {"value": value}})
        return httpx.Response(400)

    return handler


def check(handler, meteora_freeze=None, max_pct=30.0, repeat=1):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            s = SecurityClient(c, "https://rpc.example")
            r = None
            for _ in range(repeat):
                r = await s.check("MINT", meteora_freeze, max_pct)
            return r

    return asyncio.run(go())


def test_client_ok_and_pda_excluded():
    r = check(rpc_handler())
    assert r.status == "ok" and r.top10_pct == 15.0  # the 600-unit PDA is ignored, not counted as 75%
    assert r.notes == ("RugCheck: Low liquidity",)  # extra info, does not change status


def test_client_authority_active_is_risk():
    assert check(rpc_handler(mint_auth="Auth")).status == "risiko"
    assert check(rpc_handler(freeze_auth="Auth")).status == "risiko"


def test_client_concentrated_top10_is_risk():
    r = check(rpc_handler(), max_pct=10.0)
    assert r.status == "risiko" and "top 10" in r.reasons[0]


def test_client_rpc_failure_is_unverified_not_blocking_and_reports_source():
    r = check(rpc_handler(largest_error=True))
    assert r.status == "belum terverifikasi" and "rpc" in r.failed_sources and r.top10_pct is None


def test_client_rugcheck_failure_does_not_block():
    r = check(rpc_handler(rugcheck_status=403))
    assert r.status == "ok" and "rugcheck" in r.failed_sources


def test_client_caches_successful_checks_but_applies_current_threshold():
    log: list[str] = []
    r = check(rpc_handler(log=log), repeat=2)
    assert r.status == "ok" and len(log) == 5  # 5 requests once; second check fully cached
