import asyncpg
from typing import Optional
from app.config import settings

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _extract_text(message: dict, message_type: str) -> str:
    """Extract plain text from Evolution API message JSONB."""
    if not message:
        return ""
    if message_type == "conversation":
        return message.get("conversation", "")
    if message_type == "extendedTextMessage":
        return message.get("extendedTextMessage", {}).get("text", "")
    return ""


async def get_agent_messages(limit: int = 200) -> list[str]:
    """
    Fetch messages sent BY the agent (fromMe=true) for personality analysis.
    Returns a list of plain text strings.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT m.message, m."messageType"
        FROM "Message" m
        JOIN "Instance" i ON m."instanceId" = i.id
        WHERE i.name = $1
          AND (m.key->>'fromMe')::boolean = true
          AND m."messageType" IN ('conversation', 'extendedTextMessage')
        ORDER BY m."messageTimestamp" DESC
        LIMIT $2
        """,
        settings.evolution_instance,
        limit,
    )
    texts = []
    for row in rows:
        text = _extract_text(dict(row["message"]) if row["message"] else {}, row["messageType"])
        if text.strip():
            texts.append(text.strip())
    return texts


async def get_chat_history(remote_jid: str, limit: int = 15) -> list[dict]:
    """
    Fetch the last N messages from a specific chat in chronological order.
    Returns list of {role: "user"|"assistant", content: str}.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT m.key, m.message, m."messageType"
        FROM "Message" m
        JOIN "Instance" i ON m."instanceId" = i.id
        WHERE i.name = $1
          AND m.key->>'remoteJid' = $2
          AND m."messageType" IN ('conversation', 'extendedTextMessage')
        ORDER BY m."messageTimestamp" DESC
        LIMIT $3
        """,
        settings.evolution_instance,
        remote_jid,
        limit,
    )
    messages = []
    for row in reversed(rows):  # chronological order
        key = dict(row["key"]) if row["key"] else {}
        from_me = key.get("fromMe", False)
        text = _extract_text(dict(row["message"]) if row["message"] else {}, row["messageType"])
        if text.strip():
            messages.append({
                "role": "assistant" if from_me else "user",
                "content": text.strip(),
            })
    return messages
