"""Minimal Telegram Bot API client (long-poll with a short timeout, all calls bounded to 10s)."""
from __future__ import annotations

from typing import Any

import httpx

from .http import SourceError, request_json

COMMANDS = [
    ("scan", "Pindai sekarang"),
    ("top", "Hasil scan terakhir"),
    ("pool", "Detail satu pool: /pool <alamat>"),
    ("set", "Lihat/ubah ambang"),
    ("status", "Status bot"),
    ("help", "Bantuan"),
]


class TelegramApi:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self._client = client
        self._base = f"https://api.telegram.org/bot{token}"

    async def _call(self, method: str, body: dict[str, Any]) -> Any:
        payload = await request_json(self._client, "telegram", "POST", f"{self._base}/{method}", json=body)
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise SourceError("telegram", f"{method} ditolak")
        return payload.get("result")

    async def get_updates(self, offset: int | None, poll_seconds: int = 5) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"timeout": poll_seconds, "allowed_updates": ["message"]}
        if offset is not None:
            body["offset"] = offset
        result = await self._call("getUpdates", body)
        return list(result or [])

    async def send(self, chat_id: int, text: str) -> None:
        await self._call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})

    async def set_commands(self) -> None:
        cmds = [{"command": c, "description": d} for c, d in COMMANDS]
        await self._call("setMyCommands", {"commands": cmds})
