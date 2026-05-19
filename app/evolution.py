"""Client for Evolution API - sending messages and parsing webhooks."""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_HEADERS = {
    "apikey": settings.evolution_api_key,
    "Content-Type": "application/json",
}


async def send_text(to: str, text: str) -> bool:
    """Send a text message via Evolution API. Returns True on success."""
    url = f"{settings.evolution_api_url.rstrip('/')}/message/sendText/{settings.evolution_instance}"
    payload = {"number": to, "text": text}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=_HEADERS)
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("Evolution API error %s: %s", exc.response.status_code, exc.response.text)
            return False
        except Exception as exc:
            logger.error("Failed to send message via Evolution API: %s", exc)
            return False


def parse_incoming(payload: dict) -> dict | None:
    """
    Parse an Evolution API webhook payload.
    Returns a normalized dict {remote_jid, text, push_name} or None if not a text message.
    """
    event = payload.get("event", "")
    if event not in ("messages.upsert", "messages.set"):
        return None

    data = payload.get("data", {})
    key = data.get("key", {})

    # Skip messages sent by us
    if key.get("fromMe", False):
        return None

    remote_jid: str = key.get("remoteJid", "")
    if not remote_jid:
        return None

    # Skip group chats if configured
    if settings.ignore_groups and "@g.us" in remote_jid:
        return None

    message = data.get("message", {})
    message_type = data.get("messageType", "")

    if message_type == "conversation":
        text = message.get("conversation", "")
    elif message_type == "extendedTextMessage":
        text = message.get("extendedTextMessage", {}).get("text", "")
    else:
        return None  # not a text message (image, audio, etc.)

    text = text.strip()
    if not text:
        return None

    return {
        "remote_jid": remote_jid,
        "text": text,
        "push_name": data.get("pushName", ""),
    }
