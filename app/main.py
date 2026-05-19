import asyncio
import logging
import hmac
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import get_pool, close_pool
from app.evolution import parse_incoming, send_text
from app.agent import get_reply, load_system_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# debounce state: remote_jid → {task, messages, push_name}
_pending: dict[str, dict] = {}
DEBOUNCE_SECONDS = 40


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
        await send_text(remote_jid, reply)
    except Exception as exc:
        logger.error("Error handling message from %s: %s", remote_jid, exc)


async def _debounced_process(remote_jid: str):
    """Wait DEBOUNCE_SECONDS then process all accumulated messages as one."""
    await asyncio.sleep(DEBOUNCE_SECONDS)
    entry = _pending.pop(remote_jid, None)
    if not entry or not entry["messages"]:
        return
    combined = "\n".join(entry["messages"])
    count = len(entry["messages"])
    logger.info("Processing %d message(s) from %s", count, remote_jid)
    await _handle_message(remote_jid, combined, entry["push_name"])


def _schedule(remote_jid: str, text: str, push_name: str):
    """Add message to pending queue, reset the 40s timer."""
    if remote_jid in _pending:
        _pending[remote_jid]["task"].cancel()
        _pending[remote_jid]["messages"].append(text)
        logger.info("Debounce reset for %s (%d msgs)", remote_jid, len(_pending[remote_jid]["messages"]))
    else:
        _pending[remote_jid] = {"messages": [text], "push_name": push_name}
        logger.info("Debounce started for %s", remote_jid)

    task = asyncio.create_task(_debounced_process(remote_jid))
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

    _schedule(incoming["remote_jid"], incoming["text"], incoming["push_name"])
    return JSONResponse({"status": "queued"})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/prompt")
async def show_prompt():
    return {"prompt": load_system_prompt()}
