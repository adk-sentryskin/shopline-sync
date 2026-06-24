"""GDPR / data-compliance handlers for SHOPLINE (mandatory to publish the app).

SHOPLINE (like Shopify) sends three compliance webhooks:
  - customers/data_request : merchant asks for a customer's stored data
  - customers/redact       : delete a customer's personal data
  - shop/redact            : delete all of a store's data (sent after uninstall)

This app stores product/order/content data keyed by merchant. Customer PII lives
inside ``shopline_orders.raw_data``; deleting the order rows removes it.
"""
import logging

from sqlalchemy.orm import Session

from app.models import (
    ShoplineStore,
    ShoplineProduct,
    ShoplineOrder,
    ShoplineDocument,
    ShoplineWebhook,
)

logger = logging.getLogger(__name__)


def _resolve_store(db: Session, handle: str):
    if not handle:
        return None
    return (
        db.query(ShoplineStore)
        .filter(ShoplineStore.shop_handle == handle)
        .first()
    )


def redact_shop(db: Session, handle: str) -> dict:
    """Delete every record we hold for a store and clear its tokens.

    Triggered by ``shop/redact`` (Shopline sends it after uninstall). Idempotent:
    a missing store is a safe no-op.
    """
    store = _resolve_store(db, handle)
    if store is None:
        logger.info("GDPR shop/redact: no store for handle=%s (noop)", handle)
        return {"status": "ok", "store_found": False}

    mid = store.merchant_id
    deleted = {
        "products": db.query(ShoplineProduct)
        .filter(ShoplineProduct.merchant_id == mid)
        .delete(synchronize_session=False),
        "orders": db.query(ShoplineOrder)
        .filter(ShoplineOrder.merchant_id == mid)
        .delete(synchronize_session=False),
        "documents": db.query(ShoplineDocument)
        .filter(ShoplineDocument.merchant_id == mid)
        .delete(synchronize_session=False),
        "webhooks": db.query(ShoplineWebhook)
        .filter(ShoplineWebhook.store_id == store.id)
        .delete(synchronize_session=False),
    }

    # Deactivate the store and clear sensitive tokens (mirror /disconnect).
    store.is_active = 0
    store.access_token = None
    store.refresh_token = None
    db.commit()

    logger.info("GDPR shop/redact complete: merchant=%s deleted=%s", mid, deleted)
    return {"status": "ok", "store_found": True, "deleted": deleted}


def redact_customer(db: Session, handle: str, order_ids) -> dict:
    """Delete the named customer's order rows (which carry PII in raw_data).

    Triggered by ``customers/redact``. ``order_ids`` is Shopline's
    ``orders_to_redact`` list; with no orders there is nothing of the customer
    we persist, so it's a safe no-op.
    """
    store = _resolve_store(db, handle)
    if store is None:
        logger.info("GDPR customers/redact: no store for handle=%s (noop)", handle)
        return {"status": "ok", "store_found": False, "orders_redacted": 0}

    redacted = 0
    if order_ids:
        ids = [str(o) for o in order_ids]
        redacted = (
            db.query(ShoplineOrder)
            .filter(
                ShoplineOrder.merchant_id == store.merchant_id,
                ShoplineOrder.order_number.in_(ids),
            )
            .delete(synchronize_session=False)
        )
        db.commit()

    logger.info(
        "GDPR customers/redact: merchant=%s orders_redacted=%d",
        store.merchant_id, redacted,
    )
    return {"status": "ok", "store_found": True, "orders_redacted": redacted}


def process_data_request(db: Session, handle: str, payload: dict) -> dict:
    """Acknowledge a ``customers/data_request``.

    We hold no standalone customer profile — any customer data lives in order
    ``raw_data``. Record the request so the store owner can fulfil the export
    within the compliance window; no data is mutated here.
    """
    store = _resolve_store(db, handle)
    customer = (payload or {}).get("customer") or {}
    logger.info(
        "GDPR customers/data_request: handle=%s store_found=%s customer_id=%s email=%s orders=%s",
        handle, store is not None,
        customer.get("id"), customer.get("email"),
        (payload or {}).get("orders_requested"),
    )
    return {"status": "ok", "store_found": store is not None}
