"""Async processing of received SHOPLINE webhooks.

Runs in a FastAPI BackgroundTask (after the 5s ack), so it opens its OWN DB
session rather than the request-scoped one. Routes by topic to the existing
product/order sync logic, processing from the webhook payload directly.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update

from app.database import SessionLocal
from app.models import ShoplineStore, ShoplineProduct

logger = logging.getLogger(__name__)


def _resolve_store(db, handle: Optional[str]) -> Optional[ShoplineStore]:
    if not handle:
        return None
    return (
        db.query(ShoplineStore)
        .filter(ShoplineStore.shop_handle == handle, ShoplineStore.is_active == 1)
        .first()
    )


def _extract_product(payload: dict) -> Optional[dict]:
    # SHOPLINE may wrap the resource (e.g. {"product": {...}}) or send it bare.
    return payload.get("product") or (payload if payload.get("id") else None)


def _soft_delete_product(db, store: ShoplineStore, product_id: str) -> int:
    stmt = (
        update(ShoplineProduct)
        .where(
            ShoplineProduct.merchant_id == store.merchant_id,
            ShoplineProduct.shopline_product_id == str(product_id),
        )
        .values(is_deleted=1, deleted_at=datetime.now(timezone.utc))
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def process_webhook(topic: Optional[str], handle: Optional[str], payload: dict) -> None:
    """Dispatch a verified webhook to the right handler. Never raises (it runs
    detached) — logs failures so SHOPLINE retries don't depend on our crash."""
    if not topic:
        logger.warning("Webhook with no topic; skipping")
        return

    db = SessionLocal()
    try:
        store = _resolve_store(db, handle)
        if store is None:
            logger.warning("Webhook for unknown/inactive store handle=%s topic=%s", handle, topic)
            return

        if topic in ("products/create", "products/update"):
            from app.services.product_sync import sync_products
            product = _extract_product(payload)
            if not product:
                logger.warning("product webhook missing product body (topic=%s)", topic)
                return
            stats = sync_products(db, store, [product])
            logger.info("Webhook %s processed: %s", topic, stats)

        elif topic == "products/delete":
            pid = payload.get("id") or (payload.get("product") or {}).get("id")
            n = _soft_delete_product(db, store, pid) if pid else 0
            logger.info("Webhook %s soft-deleted %d product(s) id=%s", topic, n, pid)

        elif topic.startswith("orders/"):
            from app.services.order_sync import upsert_order
            order = payload.get("order") or (payload if payload.get("id") else None)
            if order:
                upsert_order(db, store, order)
                logger.info("Webhook %s upserted order", topic)
            else:
                logger.warning("order webhook missing order body (topic=%s)", topic)

        else:
            logger.info("Unhandled webhook topic: %s", topic)

    except Exception as e:
        # Detached task — log and swallow. (Idempotent upserts make SHOPLINE retries safe.)
        logger.error("Error processing webhook topic=%s handle=%s: %s", topic, handle, e)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
