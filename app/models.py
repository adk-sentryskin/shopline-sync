from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Numeric, ForeignKey, UniqueConstraint
)
from sqlalchemy.sql import func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.utils.encryption import get_encryption


def _decrypt(value):
    """Decrypt a stored token; return None if missing or undecryptable."""
    if not value:
        return None
    try:
        return get_encryption().decrypt(value)
    except Exception:
        # Corrupted ciphertext or rotated key — treat as absent rather than crash.
        return None


def _encrypt(value):
    """Encrypt a plaintext token for storage; None stays None."""
    if not value:
        return None
    return get_encryption().encrypt(value)


class ShoplineStore(Base):
    __tablename__ = "shopline_stores"
    __table_args__ = {"schema": "shopline_sync"}

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(String(255), unique=True, index=True, nullable=False)
    shop_handle = Column(String(255), unique=True, nullable=False)  # e.g. mystore
    site_url = Column(String(500), nullable=True)                   # e.g. https://mystore.myshopline.com

    _access_token = Column("access_token", Text, nullable=True)     # stored encrypted
    # ⚠️ SHOPLINE-specific: tokens expire, so we persist a refresh token + expiry.
    _refresh_token = Column("refresh_token", Text, nullable=True)   # stored encrypted
    token_expires_at = Column(DateTime(timezone=True), nullable=True)

    scopes = Column(String(500), nullable=True)
    is_active = Column(Integer, default=1)  # 1=active, 0=disconnected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @hybrid_property
    def access_token(self):
        return _decrypt(self._access_token)

    @access_token.setter
    def access_token(self, value):
        self._access_token = _encrypt(value)

    @hybrid_property
    def refresh_token(self):
        return _decrypt(self._refresh_token)

    @refresh_token.setter
    def refresh_token(self, value):
        self._refresh_token = _encrypt(value)

    def __repr__(self):
        return f"<ShoplineStore(merchant_id={self.merchant_id}, shop_handle={self.shop_handle})>"


class ShoplineProduct(Base):
    __tablename__ = "shopline_products"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "shopline_product_id",
            name="ix_shopline_products_merchant_product_id",
        ),
        {"schema": "shopline_sync"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ⚠️ SHOPLINE product id is a STRING (Shopify uses a numeric BigInteger).
    shopline_product_id = Column(String(255), index=True, nullable=False)

    store_id = Column(Integer, ForeignKey("shopline_sync.shopline_stores.id"), nullable=False)
    merchant_id = Column(String(255), nullable=False, index=True)  # denormalised for fast tenant queries

    # Searchable fields
    title = Column(String(500))
    vendor = Column(String(255))
    product_type = Column(String(255))   # ⚠️ enum (NORMAL/POD_TEMPORARY/...) — source, NOT category
    handle = Column(String(255), index=True)
    status = Column(String(50))          # active / draft / archived

    raw_data = Column(JSONB)             # complete SHOPLINE product JSON
    embedding = Column(Vector(768), nullable=True)  # text-embedding-004, 768 dims

    # Soft delete
    is_deleted = Column(Integer, default=0)  # 0=active, 1=soft-deleted
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    store = relationship("ShoplineStore", backref="products", foreign_keys=[store_id])

    def __repr__(self):
        return f"<ShoplineProduct(id={self.shopline_product_id}, merchant_id={self.merchant_id}, title={self.title})>"


class ShoplineOrder(Base):
    __tablename__ = "shopline_orders"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "order_number",
            name="ix_shopline_orders_merchant_order_number",
        ),
        {"schema": "shopline_sync"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("shopline_sync.shopline_stores.id"), nullable=False)
    merchant_id = Column(String(255), nullable=False, index=True)

    order_number = Column(String(255), nullable=False)
    total_price = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(10), nullable=True)
    financial_status = Column(String(50), nullable=True)
    raw_data = Column(JSONB)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    store = relationship("ShoplineStore", backref="orders", foreign_keys=[store_id])

    def __repr__(self):
        return f"<ShoplineOrder(order_number={self.order_number}, merchant_id={self.merchant_id})>"


class ShoplineDocument(Base):
    """Knowledge documents (policies, pages, blog articles) for chatbot RAG.

    shopline-sync owns these (vs writing to public.document_chunks). The chatbot
    read path (Section 4) is extended to search this table alongside document_chunks.
    """
    __tablename__ = "shopline_documents"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "doc_type", "source_id",
            name="ix_shopline_documents_merchant_type_source",
        ),
        {"schema": "shopline_sync"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("shopline_sync.shopline_stores.id"), nullable=False)
    merchant_id = Column(String(255), nullable=False, index=True)

    doc_type = Column(String(50), nullable=False, index=True)  # policy / page / blog_article
    source_id = Column(String(255), nullable=False)            # SHOPLINE id (or policy key)
    title = Column(String(500))
    content = Column(Text)                                     # plain-text body (HTML stripped)
    url = Column(String(1000))
    raw_data = Column(JSONB)
    embedding = Column(Vector(768), nullable=True)

    is_deleted = Column(Integer, default=0)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    store = relationship("ShoplineStore", backref="documents", foreign_keys=[store_id])

    def __repr__(self):
        return f"<ShoplineDocument(type={self.doc_type}, source_id={self.source_id}, merchant_id={self.merchant_id})>"


class ShoplineWebhook(Base):
    """Tracks webhook subscriptions registered with SHOPLINE."""
    __tablename__ = "shopline_webhooks"
    __table_args__ = {"schema": "shopline_sync"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("shopline_sync.shopline_stores.id"), nullable=False)
    merchant_id = Column(String(255), nullable=False, index=True)

    topic = Column(String(100), nullable=False, index=True)  # e.g. "product/update"
    subscription_id = Column(String(255), nullable=True, index=True)  # SHOPLINE webhook id
    status = Column(String(50), default="active")  # active / inactive
    last_event_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    store = relationship("ShoplineStore", backref="webhooks", foreign_keys=[store_id])

    def __repr__(self):
        return f"<ShoplineWebhook(topic={self.topic}, merchant_id={self.merchant_id})>"
