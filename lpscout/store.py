"""SQLite persistence: scan history, per-pool label history, alert state/cooldown, runtime settings."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any

from .alerts import PoolState

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    pools_scanned INTEGER NOT NULL,
    candidates INTEGER NOT NULL,
    recommended INTEGER NOT NULL,
    failed_json TEXT NOT NULL,
    results_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pool_labels (
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    ts REAL NOT NULL,
    address TEXT NOT NULL,
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    security TEXT NOT NULL,
    metrics_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pool_labels_addr ON pool_labels(address, ts);
CREATE TABLE IF NOT EXISTS pool_state (
    address TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    active INTEGER NOT NULL,
    alerted_rank INTEGER NOT NULL,
    last_alert_at REAL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    address TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # --- scans
    def record_scan(self, kind: str, pools_scanned: int, candidates: int, results: list[dict[str, Any]],
                    failed: dict[str, int], ts: float | None = None) -> int:
        ts = time.time() if ts is None else ts
        recommended = sum(1 for r in results if r.get("recommended"))
        with self._db:
            cur = self._db.execute(
                "INSERT INTO scans(ts, kind, pools_scanned, candidates, recommended,"
                " failed_json, results_json) VALUES (?,?,?,?,?,?,?)",
                (ts, kind, pools_scanned, candidates, recommended, json.dumps(failed), json.dumps(results)),
            )
            scan_id = int(cur.lastrowid or 0)
            self._db.executemany(
                "INSERT INTO pool_labels(scan_id, ts, address, name, label, security, metrics_json)"
                " VALUES (?,?,?,?,?,?,?)",
                [(scan_id, ts, r["address"], r["name"], r["label"], r["security"]["status"],
                  json.dumps(r["metrics"])) for r in results],
            )
        return scan_id

    def last_scan(self) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {
            "id": row["id"], "ts": row["ts"], "kind": row["kind"],
            "pools_scanned": row["pools_scanned"], "candidates": row["candidates"],
            "recommended": row["recommended"], "failed": json.loads(row["failed_json"]),
            "results": json.loads(row["results_json"]),
        }

    # --- alert state
    def get_state(self, address: str) -> PoolState | None:
        row = self._db.execute("SELECT * FROM pool_state WHERE address=?", (address,)).fetchone()
        return None if row is None else _state(row)

    def active_states(self) -> list[PoolState]:
        return [_state(r) for r in self._db.execute("SELECT * FROM pool_state WHERE active=1")]

    def save_state(self, s: PoolState) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO pool_state(address, name, label, active, alerted_rank, last_alert_at)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET name=excluded.name,"
                " label=excluded.label, active=excluded.active, alerted_rank=excluded.alerted_rank,"
                " last_alert_at=excluded.last_alert_at",
                (s.address, s.name, s.label, int(s.active), s.alerted_rank, s.last_alert_at),
            )

    def record_alert(self, address: str, kind: str, label: str, text: str, ts: float | None = None) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO alerts(ts, address, kind, label, text) VALUES (?,?,?,?,?)",
                (time.time() if ts is None else ts, address, kind, label, text),
            )

    def alert_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])

    # --- settings overrides (/set)
    def overrides(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._db.execute("SELECT key, value FROM settings")}

    def set_override(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO settings(key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def _state(row: sqlite3.Row) -> PoolState:
    return PoolState(
        address=row["address"], name=row["name"], label=row["label"], active=bool(row["active"]),
        alerted_rank=row["alerted_rank"], last_alert_at=row["last_alert_at"],
    )
