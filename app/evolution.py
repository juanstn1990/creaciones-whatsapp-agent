"""Client for Evolution API - sending messages and parsing webhooks."""
import logging
from collections import deque
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_HEADERS = {
    "apikey": settings.evolution_api_key,
    "Content-Type": "application/json",
}

# Register texts we are about to send so we can filter our own webhook events.
# We add the text BEFORE the HTTP call to avoid race conditions.
_sent_texts: deque = deque(maxlen=200)


async def assign_label(remote_jid: str, label_id: str) -> bool:
    """Assign a label to a chat in Evolution API."""
    number = remote_jid.split("@")[0]
    url = f"{settings.evolution_api_url.rstrip('/')}/label/handleLabel/{settings.evolution_instance}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                url,
                json={"number": number, "labelId": label_id, "action": "add"},
                headers=_HEADERS,
            )
            resp.raise_for_status()
            logger.info("Label %s assigned to %s", label_id, remote_jid)
            return True
        except Exception as exc:
            logger.error("Failed to assign label %s to %s: %s", label_id, remote_jid, exc)
            return False


async def send_text(to: str, text: str) -> bool:
    """Send a text message via Evolution API. Returns True on success."""
    # Register BEFORE sending — Evolution API webhook can arrive faster than our HTTP response
    _sent_texts.append(text.strip())

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
    if not isinstance(key, dict):
        return None

    # Filter by fromMe field (bool, string, or int)
    from_me = key.get("fromMe", False)
    if isinstance(from_me, str):
        from_me = from_me.lower() == "true"
    if from_me:
        logger.debug("Ignoring fromMe message")
        return None

    remote_jid: str = key.get("remoteJid", "")
    if not remote_jid:
        return None

    if settings.ignore_groups and "@g.us" in remote_jid:
        return None

    message = data.get("message", {})
    if not isinstance(message, dict):
        return None
    message_type = data.get("messageType", "")

    if message_type == "conversation":
        text = message.get("conversation", "")
    elif message_type == "extendedTextMessage":
        text = message.get("extendedTextMessage", {}).get("text", "")
    else:
        return None

    text = text.strip()
    if not text:
        return None

    # Filter our own messages by text match (catches race condition with fromMe)
    if text in _sent_texts:
        logger.debug("Ignoring own message (text match): %.40s", text)
        return None

    return {
        "remote_jid": remote_jid,
        "text": text,
        "push_name": data.get("pushName", ""),
    }
