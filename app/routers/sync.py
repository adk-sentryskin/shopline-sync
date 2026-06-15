"""Sync router.

`preview` is a live read-only verification: fetch the first page of products
from SHOPLINE using the stored token, no DB writes. The full sync (normalize ->
upsert -> embed) builds on top of this.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_merchant_from_header
from app.models import ShoplineStore
from app.services.shopline_client import ShoplineClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/")
async def sync_info():
    return {"router": "sync", "status": "ok"}


@router.get("/products/preview")
async def preview_products(store: ShoplineStore = Depends(get_merchant_from_header)):
    """Live read-only fetch of products from SHOPLINE (verifies token + endpoint)."""
    client = ShoplineClient(store.shop_handle, store.access_token)
    try:
        raw = client.list_products(limit=5)
    except Exception as e:
        logger.error("SHOPLINE product fetch failed for %s: %s", store.merchant_id, e)
        raise HTTPException(status_code=502, detail=f"SHOPLINE product fetch failed: {e}")
    finally:
        client.close()

    # Response shape isn't fully documented — surface enough to confirm it works
    # without dumping everything. Handle both wrapped and bare shapes.
    products = raw.get("products") or (raw.get("data") or {}).get("products") or []
    sample = [
        {"id": p.get("id"), "title": p.get("title"), "status": p.get("status")}
        for p in products[:5]
    ]
    return {
        "merchant_id": store.merchant_id,
        "handle": store.shop_handle,
        "count_in_page": len(products),
        "sample": sample,
        "top_level_keys": list(raw.keys()),  # helps confirm the real response shape
    }


@router.post("/products")
async def sync_products(
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """Full product pull -> normalize -> upsert -> embed (768d) into shopline_products."""
    from app.services.product_sync import full_sync
    return full_sync(db, store)


@router.get("/orders/preview")
async def preview_orders(store: ShoplineStore = Depends(get_merchant_from_header)):
    """Live read-only fetch of orders (verifies scope + endpoint + response shape)."""
    client = ShoplineClient(store.shop_handle, store.access_token)
    try:
        raw = client.get("/orders.json", params={"limit": 5})
    except Exception as e:
        logger.error("SHOPLINE order fetch failed for %s: %s", store.merchant_id, e)
        raise HTTPException(status_code=502, detail=f"SHOPLINE order fetch failed: {e}")
    finally:
        client.close()
    orders = raw.get("orders") or (raw.get("data") or {}).get("orders") or []
    return {
        "merchant_id": store.merchant_id,
        "count_in_page": len(orders),
        "top_level_keys": list(raw.keys()),
        "first_order_keys": list(orders[0].keys()) if orders else [],
    }


@router.post("/orders")
async def sync_orders(
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """Full order pull -> normalize -> upsert into shopline_orders (no embeddings)."""
    from app.services.order_sync import full_sync
    return full_sync(db, store)


@router.post("/content")
async def sync_content(
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """Blog articles -> embed -> upsert into shopline_documents (doc_type=blog_article)."""
    from app.services.content_sync import full_sync
    return full_sync(db, store)


@router.post("/webhooks/register")
async def register_store_webhooks(
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """(Re)register SHOPLINE webhook subscriptions for this store."""
    from app.services.webhook_manager import register_webhooks
    return register_webhooks(db, store)
