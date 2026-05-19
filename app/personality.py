"""
Builds a personality/style system prompt from the agent's own past messages.
Cached in memory and refreshed every personality_ttl seconds.
"""
import time
import logging
from openai import AsyncOpenAI
from app.config import settings
from app.db import get_agent_messages

logger = logging.getLogger(__name__)

_cache: dict = {"profile": None, "built_at": 0.0}

_ANALYSIS_PROMPT = """Eres un experto en comunicación y análisis de estilo.

A continuación tienes una muestra de mensajes enviados por un agente de atención al cliente vía WhatsApp.
Tu tarea es describir con precisión su estilo de comunicación para que otro agente pueda imitarlo perfectamente.

MENSAJES DE MUESTRA:
{samples}

Analiza y describe:
1. Tono general (formal/informal/mixto)
2. Uso de emojis (frecuencia, cuáles usa más)
3. Longitud típica de respuestas
4. Frases o expresiones recurrentes
5. Cómo saluda y se despide
6. Cómo maneja situaciones difíciles o quejas
7. Idioma y modismos específicos

Responde con un system prompt en primera persona que capture exactamente ese estilo,
comenzando con "Eres un agente de atención al cliente de..."
El system prompt debe ser práctico y directamente usable."""

_FALLBACK_PROFILE = """Eres un agente de atención al cliente amable y profesional que responde por WhatsApp.
Sé claro, conciso y empático. Responde siempre en español.
Si no sabes algo, sé honesto y ofrece buscar la información."""


async def build_personality_profile() -> str:
    """Analyze past agent messages and return a system prompt that mirrors the style."""
    messages = await get_agent_messages(limit=settings.personality_sample)

    if len(messages) < 10:
        logger.warning(
            "Not enough agent messages (%d) to build personality. Using fallback.", len(messages)
        )
        return _FALLBACK_PROFILE

    # Use up to 100 diverse samples to keep the prompt size manageable
    samples = messages[:100]
    sample_text = "\n".join(f"- {m}" for m in samples)

    client = AsyncOpenAI(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
    )

    try:
        response = await client.chat.completions.create(
            model=settings.moonshot_model,
            messages=[
                {"role": "user", "content": _ANALYSIS_PROMPT.format(samples=sample_text)}
            ],
            temperature=0.3,
            max_tokens=800,
        )
        profile = response.choices[0].message.content.strip()
        logger.info("Personality profile built from %d messages.", len(messages))
        return profile
    except Exception as exc:
        logger.error("Failed to build personality profile: %s", exc)
        return _FALLBACK_PROFILE


async def get_personality() -> str:
    """Return cached personality profile, rebuilding if expired."""
    now = time.time()
    if _cache["profile"] is None or (now - _cache["built_at"]) > settings.personality_ttl:
        logger.info("Rebuilding personality profile...")
        _cache["profile"] = await build_personality_profile()
        _cache["built_at"] = now
    return _cache["profile"]


def invalidate_cache():
    """Force personality profile to be rebuilt on next request."""
    _cache["built_at"] = 0.0
