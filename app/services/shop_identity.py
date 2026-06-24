"""Propagate SHOPLINE store identity (name + primary domain) into public.merchants.

The agent-builder reads ``shop_name`` + ``shop_url`` from ``public.merchants`` to
build an agent. SHOPLINE supplies these via ``GET /merchants/shop.json``. We apply
them both on connect (OAuth callback) and on each product sync, so already-connected
stores self-heal without needing to reconnect.
"""
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def apply_shop_identity(db: Session, merchant_id: str, shop_info: dict) -> Optional[str]:
    """Update the merchant row in place with the store's name + primary domain.

    COALESCE keeps current values when SHOPLINE omits a field, so we never blank
    out data the merchant already provided. Does not commit — the caller owns the
    transaction. Returns the resolved customer-facing shop URL (or None).
    """
    shop_name = (shop_info.get("name") or "").strip() or None

    domain = (shop_info.get("domain") or "").strip()
    shop_url = None
    if domain:
        shop_url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"

    db.execute(
        text(
            """
            UPDATE public.merchants
               SET shop_name  = COALESCE(:name, shop_name),
                   shop_url   = COALESCE(:url, shop_url),
                   platform   = 'Shopline',
                   updated_at = now()
             WHERE merchant_id = :mid
            """
        ),
        {"name": shop_name, "url": shop_url, "mid": merchant_id},
    )
    return shop_url


def backfill_from_client(db: Session, store, client) -> Optional[str]:
    """Fetch shop info via an already-authenticated client and apply identity.

    Best-effort: a shop-info failure (e.g. transient 5xx, missing scope) must
    never break the caller (connect or product sync), so errors are swallowed.
    Commits on success. Returns the resolved shop URL (or None).
    """
    try:
        info = client.get_shop_info()
        url = apply_shop_identity(db, store.merchant_id, info)
        if url:
            store.site_url = url
        db.commit()
        logger.info(
            "SHOPLINE identity backfill: merchant=%s name=%s url=%s",
            store.merchant_id, info.get("name"), url,
        )
        return url
    except Exception as e:
        logger.warning(
            "SHOPLINE identity backfill failed for %s: %s", store.merchant_id, e
        )
        return None
