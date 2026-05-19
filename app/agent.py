"""Core agent: builds context, calls Moonshot, returns reply."""
import logging
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings
from app.db import get_chat_history

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent.parent / "system_prompt.txt"


def load_system_prompt() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"system_prompt.txt not found at {_PROMPT_FILE}")


async def get_reply(remote_jid: str, incoming_text: str, push_name: str = "") -> str:
    """
    Given an incoming message, build context from DB history and return
    a reply that matches the agent's personality defined in system_prompt.txt.
    """
    system_prompt = load_system_prompt()
    history = await get_chat_history(remote_jid, limit=settings.history_limit)

    if push_name:
        system_prompt += f"\n\nEstás hablando con {push_name}."

    # Build message list: history + new message
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": incoming_text})

    client = AsyncOpenAI(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
    )

    try:
        response = await client.chat.completions.create(
            model=settings.moonshot_model,
            messages=messages,
            temperature=0.7,
            max_tokens=512,
        )
        reply = response.choices[0].message.content.strip()
        logger.info("Reply generated for %s (%d chars)", remote_jid, len(reply))
        return reply
    except Exception as exc:
        logger.error("LLM call failed for %s: %s", remote_jid, exc)
        raise
