"""OAuth router — SHOPLINE install flow.

POST /api/oauth/start    (API-key protected) -> returns the authorize URL for
                          the frontend to redirect the merchant to.
GET  /api/oauth/callback (public — SHOPLINE redirects the browser here) ->
                          verifies signed state, exchanges code, persists store.
"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_optional_merchant
from app.models import ShoplineStore
from app.schemas import OAuthStart
from app.services import shopline_oauth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/oauth", tags=["oauth"])


@router.post("/start")
async def oauth_start(payload: OAuthStart):
    """Return the SHOPLINE authorization URL for a merchant to begin install."""
    handle = payload.shop_handle.strip().lower()
    if not handle or not payload.merchant_id:
        raise HTTPException(status_code=400, detail="shop_handle and merchant_id are required")
    return {"authorize_url": shopline_oauth.build_authorize_url(handle, payload.merchant_id)}


@router.get("/status")
async def oauth_status(store: ShoplineStore = Depends(get_optional_merchant)):
    """Connection status for a merchant. Returns connected=false (200) when no store."""
    if store is None or not store.is_active:
        return {"connected": False}
    return {
        "connected": bool(store.access_token),
        "shop_handle": store.shop_handle,
        "site_url": store.site_url,
        "scopes": store.scopes,
        "token_expires_at": store.token_expires_at.isoformat() if store.token_expires_at else None,
        "connected_at": store.created_at.isoformat() if store.created_at else None,
    }


@router.post("/disconnect")
async def oauth_disconnect(
    store: ShoplineStore = Depends(get_optional_merchant),
    db: Session = Depends(get_db),
):
    """Disconnect a merchant's SHOPLINE store (deactivate + clear tokens)."""
    if store is None:
        return {"disconnected": True, "note": "no store was connected"}
    store.is_active = 0
    store.access_token = None
    store.refresh_token = None
    db.commit()
    logger.info("SHOPLINE store disconnected: merchant=%s", store.merchant_id)
    return {"disconnected": True}


def _callback_finish(success: bool, status_code: int = 200, **params):
    """Redirect to the frontend return URL when configured, else JSON.

    On the browser OAuth path, redirecting is the right UX; JSON is the fallback
    for local/dev testing when no frontend return URL is set.
    """
    if settings.SHOPLINE_FRONTEND_RETURN_URL:
        from urllib.parse import urlencode
        base = settings.SHOPLINE_FRONTEND_RETURN_URL
        sep = "&" if "?" in base else "?"
        return RedirectResponse(url=f"{base}{sep}{urlencode(params)}", status_code=302)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content=params)


def _register_webhooks_bg(merchant_id: str) -> None:
    """Best-effort webhook registration after connect (own DB session, detached)."""
    from app.database import SessionLocal
    from app.services.webhook_manager import register_webhooks
    db = SessionLocal()
    try:
        store = db.query(ShoplineStore).filter(ShoplineStore.merchant_id == merchant_id).first()
        if store and store.access_token:
            register_webhooks(db, store)
    except Exception as e:
        logger.warning("Webhook registration after connect failed for %s: %s", merchant_id, e)
    finally:
        db.close()


@router.get("/callback")
async def oauth_callback(
    background_tasks: BackgroundTasks,
    code: str = Query(..., description="Authorization code from SHOPLINE"),
    customField: Optional[str] = Query(None, description="Signed state token"),
    db: Session = Depends(get_db),
):
    """Handle SHOPLINE's redirect: verify state, exchange code, upsert store."""
    state = shopline_oauth.verify_oauth_state(customField or "")
    if not state:
        return _callback_finish(False, 400, status="error", error="invalid_or_expired_state")

    merchant_id = state["m"]
    handle = state["h"]

    try:
        tokens = shopline_oauth.exchange_code(handle, code)
    except Exception as e:
        logger.error("Token exchange failed for merchant %s (%s): %s", merchant_id, handle, e)
        return _callback_finish(False, 502, status="error", error="token_exchange_failed")

    if not tokens.get("access_token"):
        return _callback_finish(False, 502, status="error", error="no_access_token")

    store = (
        db.query(ShoplineStore)
        .filter(ShoplineStore.merchant_id == merchant_id)
        .first()
    )
    if store is None:
        store = ShoplineStore(merchant_id=merchant_id)
        db.add(store)

    store.shop_handle = handle
    store.site_url = f"https://{handle}.myshopline.com"
    store.access_token = tokens["access_token"]      # hybrid setter encrypts
    store.token_expires_at = tokens["token_expires_at"]
    store.scopes = tokens.get("scope")
    store.is_active = 1

    db.commit()
    logger.info("SHOPLINE store connected: merchant=%s handle=%s", merchant_id, handle)

    # Register webhooks in the background so the redirect isn't delayed.
    background_tasks.add_task(_register_webhooks_bg, merchant_id)

    return _callback_finish(True, 200, status="connected", merchant_id=merchant_id, shop_handle=handle)
