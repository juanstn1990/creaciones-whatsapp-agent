import logging
import hmac
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import get_pool, close_pool
from app.evolution import parse_incoming, send_text
from app.agent import get_reply, load_system_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    logger.info("DB pool ready.")
    logger.info("System prompt loaded (%d chars).", len(load_system_prompt()))
    yield
    await close_pool()


app = FastAPI(title="WhatsApp AI Agent", lifespan=lifespan)


def _verify_signature(body: bytes, signature: str) -> bool:
    """Optional HMAC verification for Evolution API webhooks."""
    if not settings.webhook_secret:
        return True
    expected = hmac.new(
        settings.webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _handle_message(remote_jid: str, text: str, push_name: str):
    """Background task: generate reply and send it via Evolution API."""
    try:
        reply = await get_reply(remote_jid, text, push_name)
        await send_text(remote_jid, reply)
    except Exception as exc:
        logger.error("Error handling message from %s: %s", remote_jid, exc)


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    # Optional signature check
    sig = request.headers.get("x-hub-signature-256", "")
    if not _verify_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    incoming = parse_incoming(payload)
    if incoming is None:
        # Not a relevant message — ACK and ignore
        return JSONResponse({"status": "ignored"})

    background_tasks.add_task(
        _handle_message,
        incoming["remote_jid"],
        incoming["text"],
        incoming["push_name"],
    )
    return JSONResponse({"status": "queued"})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/prompt")
async def show_prompt():
    """Show the current system prompt."""
    return {"prompt": load_system_prompt()}
