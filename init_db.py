"""
Database initialization script (fresh install / parity with app-webhook).

Creates the shopline_sync schema and all ORM tables. The grants to
chekout_chatbot and the HNSW vector index are NOT created here — those live in
migrations/001_create_shopline_sync.sql and are applied when the read path is
wired (mirrors how app-webhook applies its 004 vector migration separately).

Usage:  python init_db.py
"""
from app.database import init_db
from app.models import (  # noqa: F401
    ShoplineStore, ShoplineProduct, ShoplineOrder, ShoplineDocument, ShoplineWebhook,
)


if __name__ == "__main__":
    print("Creating shopline_sync schema and tables...")
    init_db()
    print("Done. Tables created:")
    print("- shopline_sync.shopline_stores")
    print("- shopline_sync.shopline_products")
    print("- shopline_sync.shopline_orders")
    print("- shopline_sync.shopline_webhooks")
