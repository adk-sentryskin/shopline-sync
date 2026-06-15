"""SHOPLINE Admin API request signing.

Confirmed against developer.shopline.com (2026-06-11):
    sign = HMAC_SHA256(app_secret, request_body + timestamp_ms)  -> hex lowercase
The `appkey`, `timestamp` (ms) and `sign` go in the request headers.
"""
import hmac
import hashlib
import time


def current_timestamp_ms() -> str:
    """Current time as a millisecond epoch string (SHOPLINE expects ms)."""
    return str(int(time.time() * 1000))


def compute_request_sign(body: str, timestamp_ms: str, secret: str) -> str:
    """
    Compute the SHOPLINE request signature.

    Args:
        body: The exact request body string that will be sent (JSON-serialized).
        timestamp_ms: Millisecond epoch timestamp string (same value sent in header).
        secret: The app secret (SHOPLINE_API_SECRET).

    Returns:
        Lowercase hex HMAC-SHA256 digest of (body + timestamp_ms).
    """
    source = (body + timestamp_ms).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), source, hashlib.sha256).hexdigest()


def signed_headers(body: str, app_key: str, secret: str) -> dict:
    """Build the appkey/timestamp/sign headers for a signed request body."""
    ts = current_timestamp_ms()
    return {
        "Content-Type": "application/json",
        "appkey": app_key,
        "timestamp": ts,
        "sign": compute_request_sign(body, ts, secret),
    }
