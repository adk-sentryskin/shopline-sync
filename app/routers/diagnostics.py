"""Diagnostics — temporary probe to discover SHOPLINE endpoint shapes live.

API-key + X-Merchant-Id protected. Does a read-only GET against the merchant's
own store using the stored token. Used to learn content/pages/policies response
shapes before building their sync. Safe to remove once those are built.
"""
import json
import logging

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_merchant_from_header
from app.models import ShoplineStore
from app.services.shopline_client import ShoplineClient
from app.services.shopline_oauth import ensure_fresh_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/store")
async def store_info(store: ShoplineStore = Depends(get_merchant_from_header)):
    """Show the connected store's granted scopes + token expiry (no token value)."""
    return {
        "merchant_id": store.merchant_id,
        "handle": store.shop_handle,
        "scopes": store.scopes,
        "token_expires_at": store.token_expires_at.isoformat() if store.token_expires_at else None,
        "is_active": store.is_active,
    }


@router.post("/post-probe")
async def post_probe(
    payload: dict,
    path: str = Query(..., description="Admin API path, e.g. /webhooks.json"),
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """POST an arbitrary body to a SHOPLINE Admin API path; return status + body
    (so we can discover the right request shape). Diagnostic — remove later."""
    client = ShoplineClient(store.shop_handle, ensure_fresh_token(db, store))
    try:
        resp = client.post(path, payload)
        return {"path": path, "ok": True, "response": json.dumps(resp)[:1000]}
    except httpx.HTTPStatusError as e:
        return {"path": path, "ok": False, "status": e.response.status_code, "body": e.response.text[:600]}
    except Exception as e:
        return {"path": path, "ok": False, "error": str(e)}
    finally:
        client.close()


@router.get("/probe")
async def probe(
    path: str = Query(..., description="Admin API path relative to /admin/openapi/{version}, e.g. /pages.json"),
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    client = ShoplineClient(store.shop_handle, ensure_fresh_token(db, store))
    try:
        raw = client.get(path)
        return {
            "path": path,
            "ok": True,
            "top_level_keys": list(raw.keys()) if isinstance(raw, dict) else None,
            "snippet": json.dumps(raw)[:1500],
        }
    except httpx.HTTPStatusError as e:
        return {
            "path": path,
            "ok": False,
            "status": e.response.status_code,
            "body": e.response.text[:400],
        }
    except Exception as e:
        return {"path": path, "ok": False, "error": str(e)}
    finally:
        client.close()
