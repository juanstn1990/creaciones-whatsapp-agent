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

# Store IDs of messages we sent so we can filter our own webhook events
_sent_ids: deque = deque(maxlen=200)


async def send_text(to: str, text: str) -> bool:
    """Send a text message via Evolution API. Returns True on success."""
    url = f"{settings.evolution_api_url.rstrip('/')}/message/sendText/{settings.evolution_instance}"
    payload = {"number": to, "text": text}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=_HEADERS)
            resp.raise_for_status()
            # Store the sent message ID so we can ignore its webhook event
            data = resp.json()
            msg_id = (data.get("key") or {}).get("id") or data.get("id", "")
            if msg_id:
                _sent_ids.append(msg_id)
                logger.debug("Sent message id=%s", msg_id)
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

    # Primary filter: skip by tracked sent message IDs (most reliable)
    msg_id = key.get("id", "")
    if msg_id and msg_id in _sent_ids:
        logger.debug("Ignoring own message id=%s", msg_id)
        return None

    # Secondary filter: fromMe field (handles bool, string, int)
    from_me = key.get("fromMe", False)
    if isinstance(from_me, str):
        from_me = from_me.lower() == "true"
    if from_me:
        logger.debug("Ignoring fromMe message id=%s", msg_id)
        return None

    remote_jid: str = key.get("remoteJid", "")
    if not remote_jid:
        return None

    # Skip group chats if configured
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

    return {
        "remote_jid": remote_jid,
        "text": text,
        "push_name": data.get("pushName", ""),
    }
