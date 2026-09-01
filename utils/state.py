import json
import os

STATE_FILE = "bot_state.json"

_DEFAULT_STATE = {"paused": False, "last_update_id": 0}


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return dict(_DEFAULT_STATE)
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        return {**_DEFAULT_STATE, **state}
    except Exception:
        return dict(_DEFAULT_STATE)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
