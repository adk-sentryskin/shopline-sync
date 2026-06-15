"""SHOPLINE webhook receiver.

⚠️ SHOPLINE requires a 200 ACK within 5 seconds → we verify + ack immediately
and process in a BackgroundTask. HMAC is base16 hex (X-Shopline-Hmac-Sha256).

CAPTURE MODE: while settings.WEBHOOK_VERIFY_STRICT is False, we log the full
headers + a body preview and ACK even on HMAC failure — used to learn the exact
header names + confirm SHOPLINE_WEBHOOK_SECRET from the first real webhook. Flip
WEBHOOK_VERIFY_STRICT=True (and set the real secret) before production.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request

from app.config import settings
from app.services.webhook_processor import process_webhook
from app.utils.webhook_verification import verify_webhook, extract_webhook_topic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _extract_handle(headers: dict, payload: dict) -> Optional[str]:
    """Resolve the store handle from headers (preferred) or payload."""
    dom = headers.get("x-shopline-shop-domain") or headers.get("x-shopline-handle")
    if dom:
        return dom.split(".myshopline.com")[0].strip().lower()
    h = payload.get("handle") or payload.get("shop_handle")
    return h.strip().lower() if isinstance(h, str) else None


@router.get("/")
async def webhooks_info():
    return {"router": "webhooks", "verify_strict": settings.WEBHOOK_VERIFY_STRICT}


@router.post("/shopline")
async def receive_shopline_webhook(request: Request, background_tasks: BackgroundTasks):
    """Verify HMAC, ACK 200 within 5s, then process asynchronously."""
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    hmac_header = headers.get("x-shopline-hmac-sha256")
    topic = extract_webhook_topic(headers)

    valid = verify_webhook(raw, hmac_header)

    # Capture/diagnostic logging (cheap; invaluable for confirming the real shape).
    logger.info(
        "SHOPLINE webhook received topic=%s hmac_valid=%s headers=%s body=%s",
        topic, valid,
        {k: v for k, v in headers.items() if k.startswith("x-shopline")},
        raw[:300],
    )

    if settings.WEBHOOK_VERIFY_STRICT and not valid:
        # Still 200 (don't leak verification details); just don't process.
        logger.warning("Rejected webhook (invalid HMAC) topic=%s", topic)
        return {"status": "ok"}

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("Webhook body not JSON (topic=%s)", topic)
        return {"status": "ok"}

    handle = _extract_handle(headers, payload)
    background_tasks.add_task(process_webhook, topic, handle, payload)
    return {"status": "ok"}


# --- GDPR mandatory compliance webhooks (required to publish the app) ---
@router.post("/customers/redact")
async def gdpr_customer_redact():
    """GDPR: customer data deletion. ACK 200 (processing TODO)."""
    return {"status": "ok"}


@router.post("/shop/redact")
async def gdpr_shop_redact():
    """GDPR: store data deletion. ACK 200 (processing TODO)."""
    return {"status": "ok"}
