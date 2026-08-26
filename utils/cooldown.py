import datetime
import json
import os

from config import COOLDOWN_FILE, COOLDOWN_HOURS


def load_cache() -> dict:
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    try:
        with open(COOLDOWN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache: dict):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def is_on_cooldown(addr: str, cache: dict) -> bool:
    ts = cache.get(addr)
    if not ts:
        return False
    try:
        sent_at = datetime.datetime.fromisoformat(ts)
    except Exception:
        return False
    hours = (datetime.datetime.now(datetime.timezone.utc) - sent_at).total_seconds() / 3600
    return hours < COOLDOWN_HOURS


def mark_sent(addr: str, cache: dict):
    cache[addr] = datetime.datetime.now(datetime.timezone.utc).isoformat()


def clean_old_entries(cache: dict) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    cleaned = {}
    for k, v in cache.items():
        try:
            sent_at = datetime.datetime.fromisoformat(v)
        except Exception:
            continue
        if (now - sent_at).total_seconds() < COOLDOWN_HOURS * 3600:
            cleaned[k] = v
    return cleaned
