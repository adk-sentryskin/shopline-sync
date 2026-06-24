"""SHOPLINE product sync: fetch -> normalize -> upsert -> embed.

Mirrors app-webhook/product_sync.py but synchronous (this service is sync, like
the Shopify one's DB layer) and adapted to the real SHOPLINE product schema.
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ShoplineProduct, ShoplineStore
from app.services.shopline_client import ShoplineClient
from app.services.shopline_oauth import ensure_fresh_token

logger = logging.getLogger(__name__)

_embedding_service = None


def get_embedding_service():
    """Lazy-load the embedding service so a missing Vertex config doesn't break sync."""
    global _embedding_service
    if _embedding_service is None and settings.ENABLE_EMBEDDINGS:
        try:
            from app.services.embedding_service import get_embedding_service as _get
            _embedding_service = _get()
        except Exception as e:
            logger.warning("Embedding service unavailable: %s", e)
            _embedding_service = False
    return _embedding_service if _embedding_service is not False else None


def parse_shopline_product(raw: dict) -> dict:
    """Normalize a raw SHOPLINE product into shopline_products columns."""
    return {
        "shopline_product_id": str(raw.get("id")),  # ⚠️ SHOPLINE id is a string
        "title": raw.get("title"),
        "vendor": raw.get("vendor"),
        "product_type": raw.get("product_type"),   # source enum (NORMAL/...)
        "handle": raw.get("handle"),
        "status": raw.get("status"),
        "raw_data": raw,
    }


def upsert_product(
    db: Session,
    store: ShoplineStore,
    raw: dict,
    precomputed_embedding: Optional[List[float]] = None,
) -> None:
    """Insert or update one product (idempotent on merchant_id + shopline_product_id)."""
    data = parse_shopline_product(raw)
    data["store_id"] = store.id
    data["merchant_id"] = store.merchant_id

    embedding = precomputed_embedding
    if embedding is None and settings.ENABLE_EMBEDDINGS:
        svc = get_embedding_service()
        if svc:
            embedding = svc.generate_embedding(svc.prepare_product_text(raw))
    if embedding:
        data["embedding"] = embedding

    update_cols = {
        "store_id": data["store_id"],
        "merchant_id": data["merchant_id"],
        "title": data["title"],
        "vendor": data["vendor"],
        "product_type": data["product_type"],
        "handle": data["handle"],
        "status": data["status"],
        "raw_data": data["raw_data"],
        "is_deleted": 0,
        "synced_at": func.now(),
        "updated_at": func.now(),
    }
    if embedding:
        update_cols["embedding"] = embedding

    stmt = insert(ShoplineProduct).values(**data).on_conflict_do_update(
        index_elements=["merchant_id", "shopline_product_id"],
        set_=update_cols,
    )
    db.execute(stmt)
    db.commit()


def sync_products(db: Session, store: ShoplineStore, products: List[dict]) -> Dict:
    """Upsert a batch of products, batch-embedding them first."""
    stats = {"synced_count": 0, "created_count": 0, "updated_count": 0, "failed_count": 0}

    embeddings_map = {}
    if settings.ENABLE_EMBEDDINGS:
        svc = get_embedding_service()
        if svc:
            texts = [svc.prepare_product_text(p) for p in products]
            ids = [str(p.get("id")) for p in products]
            for pid, emb in zip(ids, svc.generate_embeddings_batch(texts)):
                if emb is not None:
                    embeddings_map[pid] = emb

    for raw in products:
        pid = str(raw.get("id"))
        try:
            existing = (
                db.query(ShoplineProduct.id)
                .filter(
                    ShoplineProduct.merchant_id == store.merchant_id,
                    ShoplineProduct.shopline_product_id == pid,
                )
                .first()
            )
            upsert_product(db, store, raw, precomputed_embedding=embeddings_map.get(pid))
            stats["synced_count"] += 1
            stats["updated_count" if existing else "created_count"] += 1
        except Exception as e:
            stats["failed_count"] += 1
            logger.error("Error syncing SHOPLINE product %s: %s", pid, e)
            db.rollback()

    return stats


def full_sync(db: Session, store: ShoplineStore, page_limit: int = 200, max_pages: int = 100) -> Dict:
    """Fetch ALL products from SHOPLINE (paginated) and sync them.

    ⚠️ SHOPLINE pagination isn't fully documented. We page with limit+page and
    stop when a page returns fewer than `limit`. Verify cursor semantics at scale.
    """
    total = {"status": "completed", "total_products": 0, "synced_count": 0,
             "created_count": 0, "updated_count": 0, "failed_count": 0, "pages_fetched": 0}

    client = ShoplineClient(store.shop_handle, ensure_fresh_token(db, store))
    try:
        # Self-heal store identity (name + primary domain → public.merchants) so
        # already-connected stores get backfilled without a reconnect. Best-effort.
        from app.services import shop_identity
        shop_identity.backfill_from_client(db, store, client)

        page = 1
        while page <= max_pages:
            raw = client.list_products(limit=page_limit, page=page)
            products = raw.get("products") or (raw.get("data") or {}).get("products") or []
            total["pages_fetched"] += 1
            if not products:
                break

            batch = sync_products(db, store, products)
            for k in ("synced_count", "created_count", "updated_count", "failed_count"):
                total[k] += batch[k]
            total["total_products"] += len(products)
            logger.info("SHOPLINE sync page %d: %d/%d", page, batch["synced_count"], len(products))

            if len(products) < page_limit:
                break
            page += 1
    except Exception as e:
        total["status"] = "partial" if total["synced_count"] else "failed"
        total["error"] = str(e)
        logger.error("SHOPLINE full sync error: %s", e)
    finally:
        client.close()

    if total["failed_count"] and not total["synced_count"]:
        total["status"] = "failed"
    elif total["failed_count"]:
        total["status"] = "partial"
    return total
