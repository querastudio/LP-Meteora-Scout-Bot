import httpx

PAUSE_COMMANDS = {"/pause", "/stop"}
RESUME_COMMANDS = {"/resume", "/start"}
STATUS_COMMANDS = {"/status"}


def _telegram_api(token: str) -> str:
    return f"https://api.telegram.org/bot{token}"


async def _send_reply(client: httpx.AsyncClient, token: str, chat_id: str, text: str):
    try:
        await client.post(
            f"{_telegram_api(token)}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )
    except Exception as e:
        print(f"Telegram reply failed: {e}")


async def process_commands(client: httpx.AsyncClient, token: str, chat_id: str, state: dict) -> None:
    """Poll Telegram getUpdates for /pause, /resume, /status commands sent by the bot owner
    and update `state` in place. Only processes messages from `chat_id` — commands from any
    other chat are ignored. Advances state['last_update_id'] so updates aren't reprocessed
    on the next run."""
    offset = state.get("last_update_id", 0) + 1
    try:
        r = await client.get(
            f"{_telegram_api(token)}/getUpdates",
            params={"offset": offset, "timeout": 0, "limit": 50},
        )
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:
        print(f"Telegram getUpdates failed: {e}")
        return

    for upd in updates:
        state["last_update_id"] = upd["update_id"]
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        if str(msg.get("chat", {}).get("id")) != str(chat_id):
            continue  # ignore commands from anyone other than the configured chat

        text = (msg.get("text") or "").strip().lower().split("@")[0]  # strip /cmd@BotName

        if text in PAUSE_COMMANDS:
            state["paused"] = True
            await _send_reply(client, token, chat_id, "⏸️ <b>Bot dijeda.</b> Scan otomatis dihentikan sementara.\nKirim /resume untuk melanjutkan.")
        elif text in RESUME_COMMANDS:
            state["paused"] = False
            await _send_reply(client, token, chat_id, "▶️ <b>Bot dilanjutkan.</b> Scan otomatis aktif kembali.")
        elif text in STATUS_COMMANDS:
            status = "⏸️ Paused" if state.get("paused") else "▶️ Running"
            await _send_reply(client, token, chat_id, f"Status bot saat ini: <b>{status}</b>")
