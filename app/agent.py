"""Core agent: in-memory conversation history per session."""
import time
import logging
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent.parent / "system_prompt.txt"

# In-memory sessions: remote_jid → {history: list, last_ts: float}
# Avoids DB contamination between separate conversations.
_sessions: dict[str, dict] = {}
SESSION_TIMEOUT = 4 * 3600  # 4 hours of inactivity = new session

# Keywords that signal the user is starting a brand-new conversation
_RESTART_KEYWORDS = (
    "quiero una cancion", "quiero una canción",
    "hola", "buenas", "buenos dias", "buenos días",
    "buenas noches", "buenas tardes",
)


def load_system_prompt() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"system_prompt.txt not found at {_PROMPT_FILE}")


def _is_restart(text: str) -> bool:
    t = text.strip().lower()
    return any(t.startswith(kw) for kw in _RESTART_KEYWORDS)


def _get_session(remote_jid: str, incoming_text: str) -> list[dict]:
    """Return the conversation history for this session, resetting if needed."""
    now = time.time()
    session = _sessions.get(remote_jid)

    # Reset if: no session, timed out, or user is restarting
    if (
        session is None
        or (now - session["last_ts"]) > SESSION_TIMEOUT
        or _is_restart(incoming_text)
    ):
        _sessions[remote_jid] = {"history": [], "last_ts": now}
        return []

    session["last_ts"] = now
    return session["history"]


def _save_turn(remote_jid: str, user_text: str, assistant_text: str):
    """Append this turn to the in-memory session history."""
    session = _sessions.get(remote_jid)
    if session is None:
        return
    session["history"].append({"role": "user", "content": user_text})
    session["history"].append({"role": "assistant", "content": assistant_text})
    # Keep last 20 messages (10 turns) to avoid context overflow
    session["history"] = session["history"][-20:]


async def get_reply(remote_jid: str, incoming_text: str, push_name: str = "") -> str:
    system_prompt = load_system_prompt()
    if push_name:
        system_prompt += f"\n\nEstás hablando con {push_name}."

    history = _get_session(remote_jid, incoming_text)

    messages = [{"role": "system", "content": system_prompt}]
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
            max_tokens=600,
        )
        reply = response.choices[0].message.content.strip()
        _save_turn(remote_jid, incoming_text, reply)
        logger.info("Reply for %s (%d chars, %d history msgs)", remote_jid, len(reply), len(history))
        return reply
    except Exception as exc:
        logger.error("LLM call failed for %s: %s", remote_jid, exc)
        raise
