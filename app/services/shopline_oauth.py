"""SHOPLINE OAuth flow.

Confirmed endpoints/spec (developer.shopline.com, 2026-06-11):
  Authorize: https://{handle}.myshopline.com/admin/oauth-web/#/oauth/authorize
             ?appKey=&responseType=code&scope=&redirectUri=&customField=
  Token create:  POST https://{handle}.myshopline.com/admin/oauth/token/create
  Token refresh: POST https://{handle}.myshopline.com/admin/oauth/token/refresh
  Auth headers: appkey, timestamp(ms), sign = HMAC_SHA256(secret, body+ts) hex.
  Response: {"code":200,"data":{"accessToken","expireTime","scope"}}.
  Token lifetime ~10h. No refresh_token is returned — refresh is an
  app-credential-signed call.

CSRF state is carried in `customField` as a signed token (stateless; survives
the cross-site redirect better than a cookie).
"""
import base64
import hmac
import hashlib
import json
import time
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlencode

import httpx

from app.config import settings
from app.utils.signature import signed_headers

# Refresh this many seconds before the real expiry to avoid edge-of-expiry races.
TOKEN_REFRESH_SAFETY_SECONDS = 600  # 10 minutes
DEFAULT_TOKEN_TTL_SECONDS = 10 * 3600  # ~10h per SHOPLINE docs (fallback)
STATE_TTL_SECONDS = 600  # 10 minutes to complete the OAuth round-trip


# ---------------------------------------------------------------------------
# Signed CSRF state (carried via customField)
# ---------------------------------------------------------------------------
def create_oauth_state(merchant_id: str, handle: str) -> str:
    """Create a tamper-proof state token: base64url(payload).hex_sig."""
    payload = {
        "m": merchant_id,
        "h": handle,
        "exp": int(time.time()) + STATE_TTL_SECONDS,
        "n": pysecrets.token_urlsafe(8),
    }
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(settings.SHOPLINE_API_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_oauth_state(state: str) -> Optional[dict]:
    """Verify a state token. Returns the payload dict or None if invalid/expired."""
    if not state or "." not in state:
        return None
    raw, sig = state.rsplit(".", 1)
    expected = hmac.new(settings.SHOPLINE_API_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
def _store_base_url(handle: str) -> str:
    return f"https://{handle}.myshopline.com"


def build_authorize_url(handle: str, merchant_id: str) -> str:
    """Build the merchant-facing authorization URL (with signed state in customField)."""
    state = create_oauth_state(merchant_id, handle)
    params = urlencode(
        {
            "appKey": settings.SHOPLINE_API_KEY,
            "responseType": "code",
            "scope": settings.SHOPLINE_SCOPES,
            "redirectUri": settings.SHOPLINE_OAUTH_REDIRECT_URL,
            "customField": state,
        },
        quote_via=quote,
    )
    # Query lives after the SPA hash fragment, exactly as SHOPLINE documents it.
    return f"{_store_base_url(handle)}/admin/oauth-web/#/oauth/authorize?{params}"


# ---------------------------------------------------------------------------
# Token exchange / refresh
# ---------------------------------------------------------------------------
def _parse_expiry(expire_time) -> datetime:
    """Best-effort parse of SHOPLINE's expireTime into an aware UTC datetime.

    expireTime format isn't fully documented; handle epoch ms, epoch s, or fall
    back to now + ~10h. A safety margin is applied so the scheduler refreshes early.
    """
    now = datetime.now(timezone.utc)
    try:
        val = int(expire_time)
        # Heuristic: ms epochs are ~1e12+, s epochs ~1e9.
        if val > 1_000_000_000_000:
            parsed = datetime.fromtimestamp(val / 1000, tz=timezone.utc)
        elif val > 1_000_000_000:
            parsed = datetime.fromtimestamp(val, tz=timezone.utc)
        else:
            # Treat as a TTL in seconds.
            parsed = now + timedelta(seconds=val)
    except (TypeError, ValueError):
        parsed = now + timedelta(seconds=DEFAULT_TOKEN_TTL_SECONDS)
    return parsed - timedelta(seconds=TOKEN_REFRESH_SAFETY_SECONDS)


def _post_signed(url: str, body: dict, client: Optional[httpx.Client] = None) -> dict:
    """POST a signed JSON body to a SHOPLINE OAuth endpoint and return data dict."""
    body_str = json.dumps(body, separators=(",", ":"))
    headers = signed_headers(body_str, settings.SHOPLINE_API_KEY, settings.SHOPLINE_API_SECRET)
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.post(url, content=body_str, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns_client:
            client.close()

    if data.get("code") not in (200, "200", None):
        raise ValueError(f"SHOPLINE error: {data.get('code')} {data.get('message', '')}")
    return data.get("data", data)


def exchange_code(handle: str, code: str, client: Optional[httpx.Client] = None) -> dict:
    """
    Exchange an authorization code for an access token.

    Returns a normalized dict:
        {"access_token", "token_expires_at" (aware datetime), "scope"}
    """
    url = f"{_store_base_url(handle)}/admin/oauth/token/create"
    data = _post_signed(url, {"code": code}, client=client)
    return {
        "access_token": data.get("accessToken"),
        "token_expires_at": _parse_expiry(data.get("expireTime")),
        "scope": data.get("scope"),
    }


def refresh_access_token(handle: str, client: Optional[httpx.Client] = None) -> dict:
    """
    Refresh the access token for a store (app-credential-signed; no refresh_token).

    ⚠️ Exact request body unconfirmed — sending empty body. Verify at E2E.
    """
    url = f"{_store_base_url(handle)}/admin/oauth/token/refresh"
    data = _post_signed(url, {}, client=client)
    return {
        "access_token": data.get("accessToken"),
        "token_expires_at": _parse_expiry(data.get("expireTime")),
        "scope": data.get("scope"),
    }
