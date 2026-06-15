"""Shared knowledge-document upsert + embedding for shopline_documents.

Used by content (blogs), pages, and policies syncs. Each caller builds a list of
normalized doc dicts and hands them here for batch-embedding + idempotent upsert
(on merchant_id + doc_type + source_id).
"""
import logging
import re
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ShoplineDocument, ShoplineStore

logger = logging.getLogger(__name__)

_embedding_service = None


def get_embedding_service():
    global _embedding_service
    if _embedding_service is None and settings.ENABLE_EMBEDDINGS:
        try:
            from app.services.embedding_service import get_embedding_service as _get
            _embedding_service = _get()
        except Exception as e:
            logger.warning("Embedding service unavailable: %s", e)
            _embedding_service = False
    return _embedding_service if _embedding_service is not False else None


def strip_html(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def doc_text(doc: dict) -> str:
    """Embedding text for a knowledge doc: title + content."""
    parts = []
    if doc.get("title"):
        parts.append(doc["title"])
    if doc.get("content"):
        parts.append(doc["content"])
    return "\n".join(parts)[:20000]


def upsert_document(db: Session, store: ShoplineStore, doc: dict,
                    precomputed_embedding: Optional[List[float]] = None) -> None:
    """Upsert one doc dict: {doc_type, source_id, title, content, url, raw_data}."""
    data = {
        "store_id": store.id,
        "merchant_id": store.merchant_id,
        "doc_type": doc["doc_type"],
        "source_id": str(doc["source_id"]),
        "title": doc.get("title"),
        "content": doc.get("content"),
        "url": doc.get("url"),
        "raw_data": doc.get("raw_data"),
    }
    if precomputed_embedding:
        data["embedding"] = precomputed_embedding

    update_cols = {k: data[k] for k in
                   ("store_id", "title", "content", "url", "raw_data")}
    update_cols["is_deleted"] = 0
    update_cols["synced_at"] = func.now()
    update_cols["updated_at"] = func.now()
    if precomputed_embedding:
        update_cols["embedding"] = precomputed_embedding

    stmt = insert(ShoplineDocument).values(**data).on_conflict_do_update(
        index_elements=["merchant_id", "doc_type", "source_id"],
        set_=update_cols,
    )
    db.execute(stmt)
    db.commit()


def sync_documents(db: Session, store: ShoplineStore, docs: List[dict]) -> Dict:
    """Batch-embed and upsert a list of normalized docs."""
    stats = {"synced_count": 0, "failed_count": 0, "total": len(docs)}
    if not docs:
        return stats

    embeddings = [None] * len(docs)
    svc = get_embedding_service()
    if svc:
        embeddings = svc.generate_embeddings_batch([doc_text(d) for d in docs])

    for doc, emb in zip(docs, embeddings):
        try:
            upsert_document(db, store, doc, precomputed_embedding=emb)
            stats["synced_count"] += 1
        except Exception as e:
            stats["failed_count"] += 1
            logger.error("Error upserting %s doc %s: %s", doc.get("doc_type"), doc.get("source_id"), e)
            db.rollback()
    return stats
