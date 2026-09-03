import datetime
import json
import os

CACHE_FILE = "token_safety_cache.json"


def load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _age_hours(ts: str) -> float | None:
    try:
        dt = datetime.datetime.fromisoformat(ts)
    except Exception:
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600


def get_cached_top10(cache: dict, mint: str, ttl_hours: float) -> float | None:
    """Return a still-fresh cached top10_pct for `mint`, or None if missing/expired.

    Slow-moving data (holder concentration doesn't meaningfully change minute to minute)
    doesn't need re-fetching on every 5-minute scan — this is what keeps Birdeye CU usage
    (35 CU/call) sane instead of burning the free tier in ~1 hour.
    """
    entry = cache.get(mint)
    if not entry or entry.get("top10_pct") is None:
        return None
    age = _age_hours(entry.get("top10_ts", ""))
    if age is None or age > ttl_hours:
        return None
    return entry["top10_pct"]


def set_cached_top10(cache: dict, mint: str, value: float):
    entry = cache.setdefault(mint, {})
    entry["top10_pct"] = value
    entry["top10_ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()


def prune(cache: dict, max_age_hours: float) -> dict:
    pruned = {}
    for mint, entry in cache.items():
        age = _age_hours(entry.get("top10_ts", ""))
        if age is not None and age <= max_age_hours:
            pruned[mint] = entry
    return pruned
