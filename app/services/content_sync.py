"""SHOPLINE content (blog articles) sync -> shopline_documents (doc_type=blog_article).

Confirmed live (2026-06-11) against chekoutai-dev:
  GET /store/blogs.json                      -> {"blogs":[{id,title,handle,...}]}
  GET /store/blogs/{blog_id}/articles.json   -> {"blogs":[{id,title,digest,custom_url{url},...}]}
  (note: the article list reuses the "blogs" key; body isn't returned in the list
  — we use title + digest for v1; full-body via the article detail call is a TODO.)
Requires the read_content scope.
"""
import logging
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models import ShoplineStore
from app.services.shopline_client import ShoplineClient
from app.services.shopline_oauth import ensure_fresh_token
from app.services.document_sync import sync_documents, strip_html

logger = logging.getLogger(__name__)


def _normalize_article(raw: dict) -> dict:
    digest = strip_html(raw.get("digest"))
    url_path = (raw.get("custom_url") or {}).get("url")
    return {
        "doc_type": "blog_article",
        "source_id": raw.get("id"),
        "title": raw.get("title"),
        "content": digest,  # TODO: enrich with full body via article detail endpoint
        "url": url_path,
        "raw_data": raw,
    }


def full_sync(db: Session, store: ShoplineStore) -> Dict:
    """List blogs -> list each blog's articles -> embed + upsert as documents."""
    total = {"status": "completed", "blogs": 0, "articles": 0,
             "synced_count": 0, "failed_count": 0}
    client = ShoplineClient(store.shop_handle, ensure_fresh_token(db, store))
    try:
        blogs_resp = client.get("/store/blogs.json")
        blogs = blogs_resp.get("blogs") or []
        total["blogs"] = len(blogs)

        docs: List[dict] = []
        for blog in blogs:
            blog_id = blog.get("id")
            if not blog_id:
                continue
            arts_resp = client.get(f"/store/blogs/{blog_id}/articles.json")
            # SHOPLINE reuses the "blogs" key for the article list.
            articles = arts_resp.get("blogs") or arts_resp.get("articles") or []
            for art in articles:
                docs.append(_normalize_article(art))

        total["articles"] = len(docs)
        stats = sync_documents(db, store, docs)
        total["synced_count"] = stats["synced_count"]
        total["failed_count"] = stats["failed_count"]
    except Exception as e:
        total["status"] = "partial" if total["synced_count"] else "failed"
        total["error"] = str(e)
        logger.error("SHOPLINE content sync error: %s", e)
    finally:
        client.close()
    return total
