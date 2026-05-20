import asyncio
import logging
import hmac
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import get_pool, close_pool, get_chat_history
from app.evolution import parse_incoming, send_text
from app.agent import get_reply, load_system_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# debounce state: remote_jid → {task, messages, push_name}
_pending: dict[str, dict] = {}


async def _get_debounce(remote_jid: str) -> int:
    """
    Return debounce seconds based on the current conversation step:
      - Asking for name or age      →  10s
      - Asking what to say          →  30s  (people send several messages)
      - Asking for genre            →  10s
      - Default / first contact     →  15s
    """
    try:
        history = await get_chat_history(remote_jid, limit=4)
        for msg in reversed(history):
            if msg["role"] == "assistant":
                t = msg["content"].lower()
                if any(k in t for k in ["como se llama", "cuantos años"]):
                    return 10
                if "que le quieres decir" in t:
                    return 30
                if "genero musical" in t:
                    return 10
                if "femenina o masculina" in t:
                    return 10
                break
    except Exception:
        pass
    return 15


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    logger.info("DB pool ready.")
    logger.info("System prompt loaded (%d chars).", len(load_system_prompt()))
    yield
    await close_pool()


app = FastAPI(title="WhatsApp AI Agent", lifespan=lifespan)


def _verify_signature(body: bytes, signature: str) -> bool:
    if not settings.webhook_secret:
        return True
    expected = hmac.new(
        settings.webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _handle_message(remote_jid: str, text: str, push_name: str):
    try:
        reply = await get_reply(remote_jid, text, push_name)
        parts = [p.strip() for p in reply.split("|||") if p.strip()]
        for part in parts:
            await send_text(remote_jid, part)
            if len(parts) > 1:
                await asyncio.sleep(1.5)
    except Exception as exc:
        logger.error("Error handling message from %s: %s", remote_jid, exc)


async def _debounced_process(remote_jid: str, delay: int):
    await asyncio.sleep(delay)
    entry = _pending.pop(remote_jid, None)
    if not entry or not entry["messages"]:
        return
    combined = "\n".join(entry["messages"])
    logger.info("Processing %d msg(s) from %s after %ds", len(entry["messages"]), remote_jid, delay)
    await _handle_message(remote_jid, combined, entry["push_name"])


async def _schedule(remote_jid: str, text: str, push_name: str):
    """Add message to pending queue with dynamic debounce time."""
    delay = await _get_debounce(remote_jid)

    if remote_jid in _pending:
        _pending[remote_jid]["task"].cancel()
        _pending[remote_jid]["messages"].append(text)
        logger.info("Debounce reset for %s (%ds, %d msgs)", remote_jid, delay, len(_pending[remote_jid]["messages"]))
    else:
        _pending[remote_jid] = {"messages": [text], "push_name": push_name}
        logger.info("Debounce started for %s (%ds)", remote_jid, delay)

    task = asyncio.create_task(_debounced_process(remote_jid, delay))
    _pending[remote_jid]["task"] = task


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()

    sig = request.headers.get("x-hub-signature-256", "")
    if not _verify_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    incoming = parse_incoming(payload)
    if incoming is None:
        return JSONResponse({"status": "ignored"})

    asyncio.create_task(_schedule(incoming["remote_jid"], incoming["text"], incoming["push_name"]))
    return JSONResponse({"status": "queued"})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/prompt")
async def show_prompt():
    return {"prompt": load_system_prompt()}
