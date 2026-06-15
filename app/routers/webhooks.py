"""Webhooks router — STUB (Section 3 will implement processing).

⚠️ SHOPLINE requires the endpoint to ACK 200 within 5 seconds and process
asynchronously. The real handler (Section 3) will verify the base16 HMAC
(X-Shopline-Hmac-Sha256) and enqueue work. For now this only acknowledges.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("/")
async def webhooks_info():
    return {"router": "webhooks", "status": "stub", "implemented": False}


@router.post("/shopline")
async def receive_shopline_webhook():
    # TODO(Section 3): verify_webhook(raw_body, X-Shopline-Hmac-Sha256), ack within 5s,
    # process product/order topics asynchronously.
    return {"status": "received", "processed": False}


# --- GDPR mandatory compliance webhooks (required to publish the SHOPLINE app) ---
# Must be reachable + return 200. Real redaction logic lands with the webhook chunk;
# for now we acknowledge so the app config can be saved and audited.

@router.post("/customers/redact")
async def gdpr_customer_redact():
    """GDPR: customer data deletion request. ACK 200 (processing TODO)."""
    # TODO(Section 3): verify HMAC, delete/anonymize the customer's data, log the request.
    return {"status": "ok"}


@router.post("/shop/redact")
async def gdpr_shop_redact():
    """GDPR: store/shop data deletion request. ACK 200 (processing TODO)."""
    # TODO(Section 3): verify HMAC, purge the store's synced data, deactivate the store.
    return {"status": "ok"}
