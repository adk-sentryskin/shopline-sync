"""SHOPLINE webhook HMAC verification.

⚠️ KEY DIVERGENCE FROM SHOPIFY:
- Header:   X-Shopline-Hmac-Sha256   (Shopify: X-Shopify-Hmac-SHA256)
- Encoding: base16 hex               (Shopify: base64)
Confirmed against developer.shopline.com (newer API generation, 2026-06-11).

The signing key is SHOPLINE_WEBHOOK_SECRET (often equal to the app secret —
confirm at first real webhook test).
"""
import hmac
import hashlib
from typing import Optional
from app.config import settings


def verify_webhook(data: bytes, hmac_header: Optional[str]) -> bool:
    """
    Verify a SHOPLINE webhook HMAC signature.

    Args:
        data: Raw request body as bytes (verify against the exact bytes received).
        hmac_header: Value of the X-Shopline-Hmac-Sha256 header.

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not hmac_header:
        return False

    calculated_hmac = hmac.new(
        settings.SHOPLINE_WEBHOOK_SECRET.encode("utf-8"),
        data,
        hashlib.sha256,
    ).hexdigest()  # base16 hex — NOT base64

    # Constant-time compare to avoid timing attacks. Case-insensitive because
    # hex encoding is case-insensitive; normalise both sides to lower.
    return hmac.compare_digest(calculated_hmac, hmac_header.strip().lower())


def extract_webhook_topic(headers: dict) -> Optional[str]:
    """
    Extract the webhook topic (e.g. 'product/update') from request headers.

    SHOPLINE sends the topic in the X-Shopline-Topic header.
    """
    return headers.get("x-shopline-topic")
