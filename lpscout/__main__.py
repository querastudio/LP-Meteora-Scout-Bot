from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx

from . import logging_setup
from .bot import Bot
from .scanner import Scanner
from .settings import Settings
from .sources.meteora import MeteoraClient
from .sources.security import SecurityClient
from .store import Store
from .telegram import TelegramApi


async def main() -> None:
    settings = Settings.from_env()
    logging_setup.setup()
    store = Store(settings.db_path)
    async with httpx.AsyncClient(headers={"User-Agent": "lpscout/2.0"}) as client:
        scanner = Scanner(MeteoraClient(client), SecurityClient(client, settings.rpc_url), settings)
        bot = Bot(settings, store, scanner, TelegramApi(client, settings.telegram_bot_token))
        try:
            await bot.run()
        finally:
            store.close()
            logging.getLogger("lpscout").info("bot_stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
