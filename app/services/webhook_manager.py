"""Register/track SHOPLINE webhook subscriptions for a store.

Confirmed live (2026-06-16):
  POST /admin/openapi/{ver}/webhooks.json
    body {"webhook": {"topic": "...", "address": "...", "api_version": "v20240601"}}
  GET  /admin/openapi/{ver}/webhooks.json -> {"webhooks": [{id, topic, address, ...}]}
  ⚠️ Topics are PLURAL (products/update, orders/create), not singular.
  ⚠️ Webhook api_version is v20240601 (a supported subscription version), NOT the
     Admin API version. orders/update + products/inventory_update are NOT subscribable.
Registration is idempotent: it adopts existing subscriptions for our address.
"""
import logging
from typing import Dict, List

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ShoplineStore, ShoplineWebhook
from app.services.shopline_client import ShoplineClient

logger = logging.getLogger(__name__)

# Webhook subscription version (distinct from SHOPLINE_API_VERSION).
WEBHOOK_API_VERSION = "v20240601"

# Subscribable topics we want (PLURAL, confirmed valid).
WEBHOOK_TOPICS = [
    "products/create",
    "products/update",
    "products/delete",
    "orders/create",
    "orders/cancelled",
    "orders/fulfilled",
]


def _callback_address() -> str:
    return f"{settings.app_url}/api/webhooks/shopline"


def _list_existing(client: ShoplineClient) -> List[dict]:
    try:
        resp = client.get("/webhooks.json")
        return resp.get("webhooks") or []
    except Exception as e:
        logger.warning("Could not list existing SHOPLINE webhooks: %s", e)
        return []


def register_webhooks(db: Session, store: ShoplineStore) -> Dict:
    """Subscribe the store to WEBHOOK_TOPICS (idempotent) and persist them."""
    address = _callback_address()
    result = {"registered": [], "adopted": [], "failed": [], "address": address}
    client = ShoplineClient(store.shop_handle, store.access_token)
    try:
        existing = _list_existing(client)
        by_topic = {w.get("topic"): w for w in existing if w.get("address") == address}

        for topic in WEBHOOK_TOPICS:
            try:
                if topic in by_topic:
                    _track(db, store, topic, by_topic[topic].get("id"))
                    result["adopted"].append(topic)
                    continue
                resp = client.post("/webhooks.json", {
                    "webhook": {"topic": topic, "address": address, "api_version": WEBHOOK_API_VERSION}
                })
                sub = resp.get("webhook") or resp
                _track(db, store, topic, sub.get("id"))
                result["registered"].append(topic)
            except Exception as e:
                logger.warning("Failed to register SHOPLINE webhook %s for %s: %s",
                               topic, store.merchant_id, e)
                result["failed"].append(topic)
    finally:
        client.close()
    logger.info("SHOPLINE webhook registration for %s: %d new, %d adopted, %d failed",
                store.merchant_id, len(result["registered"]), len(result["adopted"]), len(result["failed"]))
    return result


def _track(db: Session, store: ShoplineStore, topic: str, subscription_id) -> None:
    existing = (
        db.query(ShoplineWebhook)
        .filter(ShoplineWebhook.merchant_id == store.merchant_id, ShoplineWebhook.topic == topic)
        .first()
    )
    sub_id = str(subscription_id) if subscription_id is not None else None
    if existing:
        if sub_id:
            existing.subscription_id = sub_id
        existing.status = "active"
    else:
        db.add(ShoplineWebhook(
            store_id=store.id, merchant_id=store.merchant_id,
            topic=topic, subscription_id=sub_id, status="active",
        ))
    db.commit()
