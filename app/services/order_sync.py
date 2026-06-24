"""SHOPLINE order sync: fetch -> normalize -> upsert into shopline_orders.

No embeddings (orders power order-status lookups + analytics, not semantic
search). Idempotent on (merchant_id, order_number).
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ShoplineOrder, ShoplineStore
from app.services.shopline_client import ShoplineClient
from app.services.shopline_oauth import ensure_fresh_token

logger = logging.getLogger(__name__)


def parse_shopline_order(raw: dict) -> dict:
    """Normalize a raw SHOPLINE order. Field names per the Admin REST order
    schema (GET /admin/openapi/<version>/orders.json): the order total lives in
    `current_total_price`; `name` is the human order number. Older fallbacks kept
    for resilience to shape drift."""
    order_number = raw.get("name") or raw.get("order_number") or raw.get("id")
    total = raw.get("current_total_price") or raw.get("total_price") or raw.get("totalPrice")
    currency = raw.get("currency") or raw.get("currency_code")
    fin_status = raw.get("financial_status") or raw.get("financialStatus")
    return {
        "order_number": str(order_number) if order_number is not None else None,
        "total_price": total,
        "currency": currency,
        "financial_status": fin_status,
        "raw_data": raw,
    }


def upsert_order(db: Session, store: ShoplineStore, raw: dict) -> None:
    data = parse_shopline_order(raw)
    if not data["order_number"]:
        logger.warning("Skipping SHOPLINE order with no identifiable order_number")
        return
    data["store_id"] = store.id
    data["merchant_id"] = store.merchant_id

    update_cols = {
        "store_id": data["store_id"],
        "total_price": data["total_price"],
        "currency": data["currency"],
        "financial_status": data["financial_status"],
        "raw_data": data["raw_data"],
        "updated_at": func.now(),
    }
    stmt = insert(ShoplineOrder).values(**data).on_conflict_do_update(
        index_elements=["merchant_id", "order_number"],
        set_=update_cols,
    )
    db.execute(stmt)
    db.commit()


def full_sync(db: Session, store: ShoplineStore, page_limit: int = 100, max_pages: int = 100) -> Dict:
    """Fetch all orders (paginated) and upsert them.

    SHOPLINE's orders.json caps `limit` at 100 (a higher value 422s with
    "limit: the query result max size is 100"), so page_limit must stay <= 100.
    """
    total = {"status": "completed", "total_orders": 0, "synced_count": 0,
             "failed_count": 0, "pages_fetched": 0}
    client = ShoplineClient(store.shop_handle, ensure_fresh_token(db, store))
    try:
        page = 1
        while page <= max_pages:
            raw = client.get("/orders.json", params={"limit": page_limit, "page": page})
            orders = raw.get("orders") or (raw.get("data") or {}).get("orders") or []
            total["pages_fetched"] += 1
            if not orders:
                break
            for o in orders:
                try:
                    upsert_order(db, store, o)
                    total["synced_count"] += 1
                except Exception as e:
                    total["failed_count"] += 1
                    logger.error("Error syncing SHOPLINE order: %s", e)
                    db.rollback()
            total["total_orders"] += len(orders)
            if len(orders) < page_limit:
                break
            page += 1
    except Exception as e:
        total["status"] = "partial" if total["synced_count"] else "failed"
        total["error"] = str(e)
        logger.error("SHOPLINE order full sync error: %s", e)
    finally:
        client.close()
    return total
