"""Telegram bot: owner-only commands, scheduled scans and alert delivery."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .alerts import decide
from .formatter import (
    FOOTER,
    alert_message,
    drop_message,
    pool_detail,
    settings_message,
    top_message,
    ts_utc,
)
from .http import SourceError
from .labels import RANK
from .scanner import Scanner
from .settings import Settings
from .store import Store

log = logging.getLogger("lpscout.bot")
ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
COMMAND_TIMEOUT = 25.0
LABEL_BY_RANK = {v: k for k, v in RANK.items()}

HELP = (
    "LP Scout Meteora (Solana) — hanya memindai & merekomendasikan, tidak membuat transaksi.\n\n"
    "/scan — pindai sekarang\n"
    "/top — hasil scan terakhir\n"
    "/pool <alamat> — detail satu pool + syarat yang kurang\n"
    "/set — lihat ambang · /set <nama> <nilai> — ubah\n"
    "/status — waktu scan terakhir & sumber data yang gagal\n"
    "/help — bantuan"
)


class Api(Protocol):
    async def get_updates(self, offset: int | None, poll_seconds: int = 5) -> list[dict[str, Any]]: ...
    async def send(self, chat_id: int, text: str) -> None: ...
    async def set_commands(self) -> None: ...


class Bot:
    def __init__(self, settings: Settings, store: Store, scanner: Scanner, api: Api,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.settings = settings
        self.store = store
        self.scanner = scanner
        self.api = api
        self.clock = clock
        self._sleep = sleep
        self.command_timeout = COMMAND_TIMEOUT
        self.started_at = clock()
        self.next_scan_at = clock()
        self.last_error: str | None = None
        self._scan_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._apply_overrides()

    @property
    def owner(self) -> int:
        return self.settings.telegram_owner_id

    def _apply_overrides(self) -> None:
        for key, value in self.store.overrides().items():
            try:
                self.settings.thresholds.set_value(key, value)
            except ValueError:
                log.warning("override_ignored", extra={"key": key})

    # ---------------------------------------------------------------- updates
    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        sender = (message.get("from") or {}).get("id")
        if sender != self.owner:
            return  # silently ignore everyone else
        text = str(message.get("text") or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        command = parts[0].split("@")[0].lower()
        args = parts[1:]
        handlers: dict[str, Callable[[list[str]], Awaitable[str]]] = {
            "/start": self._help, "/help": self._help, "/scan": self._scan, "/top": self._top,
            "/pool": self._pool, "/set": self._set, "/status": self._status,
        }
        handler = handlers.get(command)
        if handler is None:
            return
        await self._respond(handler(args))

    async def _respond(self, work: Awaitable[str]) -> None:
        """Run a command with a 25s limit: on timeout say so, then deliver the result when ready."""
        task = asyncio.ensure_future(work)
        try:
            text = await asyncio.wait_for(asyncio.shield(task), self.command_timeout)
        except TimeoutError:
            await self._send("⏳ Masih memproses — sumber data lambat. Hasil dikirim begitu selesai.")
            try:
                text = await task
            except Exception as e:
                log.exception("command_failed")
                text = f"Gagal: {type(e).__name__}. Coba lagi nanti."
        except Exception as e:
            log.exception("command_failed")
            text = f"Gagal: {type(e).__name__}. Coba lagi nanti."
        await self._send(text)

    async def _send(self, text: str) -> bool:
        try:
            await self.api.send(self.owner, text)
            return True
        except SourceError as e:
            log.warning("send_failed", extra={"source": e.source})
            return False

    # --------------------------------------------------------------- commands
    async def _help(self, args: list[str]) -> str:
        return HELP

    async def _top(self, args: list[str]) -> str:
        return top_message(self.store.last_scan())

    async def _scan(self, args: list[str]) -> str:
        if self._scan_lock.locked():
            return "Scan sedang berjalan. Hasilnya akan masuk ke /top sebentar lagi."
        async with self._scan_lock:
            try:
                active = [s.address for s in self.store.active_states()]
                outcome = await self.scanner.scan(int(self.clock()), extra_addresses=active)
            except SourceError as e:
                self.last_error = str(e)
                return f"Scan gagal: {e}"
            self.last_error = None
            self.store.record_scan("manual", outcome.pools_scanned, outcome.candidates,
                                   outcome.results, outcome.failed)
            return top_message(self.store.last_scan())

    async def _pool(self, args: list[str]) -> str:
        if not args or not ADDRESS_RE.match(args[0]):
            return "Pakai: /pool <alamat pool Meteora DLMM>"
        try:
            outcome = await self.scanner.inspect(args[0], int(self.clock()))
        except SourceError as e:
            return f"Tidak bisa mengambil pool: {e}"
        return pool_detail(outcome.results[0])

    async def _set(self, args: list[str]) -> str:
        th = self.settings.thresholds
        if not args:
            return settings_message(th)
        if len(args) != 2:
            return "Pakai: /set <nama> <nilai>"
        try:
            th.set_value(args[0], args[1])
        except ValueError as e:
            return f"Ditolak: {e}"
        self.store.set_override(args[0], args[1])
        if args[0] == "scan_minutes":
            self.next_scan_at = min(self.next_scan_at, self.clock() + th.scan_minutes * 60)
        return f"✅ {args[0]} = {getattr(th, args[0])}"

    async def _status(self, args: list[str]) -> str:
        last = self.store.last_scan()
        th = self.settings.thresholds
        lines = ["📟 Status LP Scout"]
        if last is None:
            lines.append("Scan terakhir: belum ada")
        else:
            failed = ", ".join(f"{k}×{v}" for k, v in sorted(last["failed"].items())) or "tidak ada"
            lines += [
                f"Scan terakhir: {ts_utc(last['ts'])} ({last['kind']})",
                f"Dipindai: {last['pools_scanned']} pool · dihitung {last['candidates']} · "
                f"direkomendasikan {last['recommended']}",
                f"Sumber gagal: {failed}",
            ]
        if self.last_error:
            lines.append(f"Error scan terakhir: {self.last_error}")
        eta = max(int(self.next_scan_at - self.clock()), 0)
        lines += [
            f"Scan berikutnya: ~{eta // 60} mnt {eta % 60} dtk · interval {th.scan_minutes} mnt",
            f"Alert terkirim: {self.store.alert_count()} · aktif: {len(self.store.active_states())}",
            f"Aktif sejak: {ts_utc(self.started_at)}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------- scheduling
    async def scan_and_alert(self) -> None:
        """One scheduled scan: record it, then alert on newly recommended/upgraded pools."""
        async with self._scan_lock:
            started = self.clock()
            try:
                active = [s.address for s in self.store.active_states()]
                outcome = await self.scanner.scan(int(self.clock()), extra_addresses=active)
            except SourceError as e:
                self.last_error = str(e)
                log.error("scan_failed", extra={"error": str(e)})
                return
            self.last_error = None
            self.store.record_scan("auto", outcome.pools_scanned, outcome.candidates,
                                   outcome.results, outcome.failed)
            sent = 0
            now = self.clock()
            cooldown = self.settings.thresholds.cooldown_minutes * 60
            for r in outcome.results:
                prev = self.store.get_state(r["address"])
                d = decide(prev, r["address"], r["name"], r["effective_label"], now, cooldown)
                if d.kind in ("new", "upgrade"):
                    before = LABEL_BY_RANK.get(prev.alerted_rank) if prev else None
                    text = alert_message(r, d.kind, before)
                    if not await self._send(text):
                        continue  # keep the old state so the next scan retries this alert
                    self.store.record_alert(r["address"], d.kind, r["label"], text, now)
                    sent += 1
                elif d.kind == "drop":
                    text = drop_message(r["name"], r["address"], r["missing"])
                    if not await self._send(text):
                        continue
                    self.store.record_alert(r["address"], "drop", "tolak", text, now)
                self.store.save_state(d.state)
            log.info("scan_done", extra={
                "pools_scanned": outcome.pools_scanned, "candidates": outcome.candidates,
                "recommended": sum(1 for r in outcome.results if r["recommended"]),
                "alerts": sent, "failed_sources": outcome.failed,
                "seconds": round(self.clock() - started, 1),
            })

    async def run_scheduler(self) -> None:
        while True:
            now = self.clock()
            if now >= self.next_scan_at:
                try:
                    await self.scan_and_alert()
                except Exception:
                    log.exception("scheduler_error")
                self.next_scan_at = self.clock() + self.settings.thresholds.scan_minutes * 60
            await self._sleep(min(max(self.next_scan_at - self.clock(), 0.0), 15.0))

    async def run_polling(self) -> None:
        offset: int | None = None
        try:  # drop any backlog so old commands are not replayed after a restart
            backlog = await self.api.get_updates(-1, 0)
            if backlog:
                offset = int(backlog[-1]["update_id"]) + 1
        except SourceError:
            pass
        while True:
            try:
                updates = await self.api.get_updates(offset)
            except SourceError as e:
                log.warning("poll_failed", extra={"error": str(e)})
                await self._sleep(5)
                continue
            for u in updates:
                offset = int(u["update_id"]) + 1
                task = asyncio.create_task(self._safe_handle(u))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _safe_handle(self, update: dict[str, Any]) -> None:
        try:
            await self.handle_update(update)
        except Exception:
            log.exception("update_failed")

    async def run(self) -> None:
        try:
            await self.api.set_commands()
        except SourceError as e:
            log.warning("set_commands_failed", extra={"error": str(e)})
        log.info("bot_started", extra={"owner": self.owner, "footer": FOOTER[:20]})
        await asyncio.gather(self.run_polling(), self.run_scheduler())

