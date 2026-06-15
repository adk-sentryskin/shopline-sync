-- Migration: Create shopline_sync schema and tables
-- Date: 2026-06-11
-- Service: shopline-sync
--
-- STRICTLY ADDITIVE: only CREATE ... IF NOT EXISTS and GRANT statements.
-- No DROP, no ALTER of pre-existing objects. Safe to run against the shared
-- chekoutai database without touching shopify_sync / public / any other schema.
-- Idempotent: safe to run after SQLAlchemy create_all (uses IF NOT EXISTS).

-- ============================================================================
-- STEP 0: Extensions + schema
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;  -- already present (Shopify uses it); no-op if so

CREATE SCHEMA IF NOT EXISTS shopline_sync;

-- ============================================================================
-- STEP 1: shopline_stores  (one row per connected merchant)
-- ============================================================================
CREATE TABLE IF NOT EXISTS shopline_sync.shopline_stores (
    id               SERIAL PRIMARY KEY,
    merchant_id      VARCHAR(255) NOT NULL UNIQUE,
    shop_handle      VARCHAR(255) NOT NULL UNIQUE,
    site_url         VARCHAR(500),
    access_token     TEXT,                 -- Fernet-encrypted
    refresh_token    TEXT,                 -- Fernet-encrypted (⚠️ SHOPLINE-specific)
    token_expires_at TIMESTAMPTZ,          -- ⚠️ drives the refresh scheduler
    scopes           VARCHAR(500),
    is_active        INTEGER DEFAULT 1,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_shopline_stores_merchant_id
    ON shopline_sync.shopline_stores (merchant_id);

-- ============================================================================
-- STEP 2: shopline_products
-- ============================================================================
CREATE TABLE IF NOT EXISTS shopline_sync.shopline_products (
    id                  SERIAL PRIMARY KEY,
    shopline_product_id VARCHAR(255) NOT NULL,   -- ⚠️ string id (Shopify is numeric)
    store_id            INTEGER NOT NULL REFERENCES shopline_sync.shopline_stores(id),
    merchant_id         VARCHAR(255) NOT NULL,    -- denormalised for fast tenant queries
    title               VARCHAR(500),
    vendor              VARCHAR(255),
    product_type        VARCHAR(255),             -- ⚠️ enum (source), NOT category
    handle              VARCHAR(255),
    status              VARCHAR(50),              -- active / draft / archived
    raw_data            JSONB,
    embedding           vector(768),              -- text-embedding-004
    is_deleted          INTEGER DEFAULT 0,
    deleted_at          TIMESTAMPTZ,
    synced_at           TIMESTAMPTZ DEFAULT now(),
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ,
    CONSTRAINT ix_shopline_products_merchant_product_id
        UNIQUE (merchant_id, shopline_product_id)  -- idempotent upserts
);
CREATE INDEX IF NOT EXISTS ix_shopline_products_merchant_id
    ON shopline_sync.shopline_products (merchant_id);
CREATE INDEX IF NOT EXISTS ix_shopline_products_shopline_product_id
    ON shopline_sync.shopline_products (shopline_product_id);
CREATE INDEX IF NOT EXISTS ix_shopline_products_handle
    ON shopline_sync.shopline_products (handle);
-- Partial index for the common active-product vector query path
CREATE INDEX IF NOT EXISTS ix_shopline_products_merchant_status
    ON shopline_sync.shopline_products (merchant_id, status)
    WHERE is_deleted = 0 AND embedding IS NOT NULL;

-- Vector similarity index.
-- NOTE: This uses HNSW (vector_cosine_ops), matching the live Shopify service
-- (app-webhook/migrations/004) rather than the IVFFlat note in the TODO. HNSW
-- builds fine on an empty table and needs no "build after load" step, whereas
-- IVFFlat requires data to train its lists. IVFFlat alternative kept below.
CREATE INDEX IF NOT EXISTS ix_shopline_products_embedding_hnsw
    ON shopline_sync.shopline_products
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- Alternative (run AFTER initial load if you prefer IVFFlat):
-- CREATE INDEX ix_shopline_products_embedding_ivfflat
--     ON shopline_sync.shopline_products
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================================
-- STEP 3: shopline_orders
-- ============================================================================
CREATE TABLE IF NOT EXISTS shopline_sync.shopline_orders (
    id               SERIAL PRIMARY KEY,
    store_id         INTEGER NOT NULL REFERENCES shopline_sync.shopline_stores(id),
    merchant_id      VARCHAR(255) NOT NULL,
    order_number     VARCHAR(255) NOT NULL,
    total_price      NUMERIC(12, 2),
    currency         VARCHAR(10),
    financial_status VARCHAR(50),
    raw_data         JSONB,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ,
    CONSTRAINT ix_shopline_orders_merchant_order_number
        UNIQUE (merchant_id, order_number)
);
CREATE INDEX IF NOT EXISTS ix_shopline_orders_merchant_id
    ON shopline_sync.shopline_orders (merchant_id);

-- ============================================================================
-- STEP 4: shopline_webhooks  (registered subscriptions)
-- ============================================================================
CREATE TABLE IF NOT EXISTS shopline_sync.shopline_webhooks (
    id              SERIAL PRIMARY KEY,
    store_id        INTEGER NOT NULL REFERENCES shopline_sync.shopline_stores(id),
    merchant_id     VARCHAR(255) NOT NULL,
    topic           VARCHAR(100) NOT NULL,   -- e.g. "product/update"
    subscription_id VARCHAR(255),            -- SHOPLINE webhook id
    status          VARCHAR(50) DEFAULT 'active',
    last_event_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_shopline_webhooks_merchant_id
    ON shopline_sync.shopline_webhooks (merchant_id);
CREATE INDEX IF NOT EXISTS ix_shopline_webhooks_topic
    ON shopline_sync.shopline_webhooks (topic);

-- ============================================================================
-- STEP 4b: shopline_documents  (policies / pages / blog articles for RAG)
-- ============================================================================
CREATE TABLE IF NOT EXISTS shopline_sync.shopline_documents (
    id          SERIAL PRIMARY KEY,
    store_id    INTEGER NOT NULL REFERENCES shopline_sync.shopline_stores(id),
    merchant_id VARCHAR(255) NOT NULL,
    doc_type    VARCHAR(50) NOT NULL,    -- policy / page / blog_article
    source_id   VARCHAR(255) NOT NULL,   -- SHOPLINE id or policy key
    title       VARCHAR(500),
    content     TEXT,                    -- plain-text body (HTML stripped)
    url         VARCHAR(1000),
    raw_data    JSONB,
    embedding   vector(768),
    is_deleted  INTEGER DEFAULT 0,
    deleted_at  TIMESTAMPTZ,
    synced_at   TIMESTAMPTZ DEFAULT now(),
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ,
    CONSTRAINT ix_shopline_documents_merchant_type_source
        UNIQUE (merchant_id, doc_type, source_id)
);
CREATE INDEX IF NOT EXISTS ix_shopline_documents_merchant_id
    ON shopline_sync.shopline_documents (merchant_id);
CREATE INDEX IF NOT EXISTS ix_shopline_documents_doc_type
    ON shopline_sync.shopline_documents (doc_type);
CREATE INDEX IF NOT EXISTS ix_shopline_documents_embedding_hnsw
    ON shopline_sync.shopline_documents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- STEP 5: Read-only grants for the chatbot (read path)
-- ============================================================================
-- chekout_chatbot already exists (SELECT-only user used by langflow).
GRANT USAGE ON SCHEMA shopline_sync TO chekout_chatbot;
GRANT SELECT ON ALL TABLES IN SCHEMA shopline_sync TO chekout_chatbot;
-- Ensure future tables in this schema are also readable by the chatbot.
ALTER DEFAULT PRIVILEGES IN SCHEMA shopline_sync
    GRANT SELECT ON TABLES TO chekout_chatbot;

-- ============================================================================
-- VERIFICATION (run manually after migration)
-- ============================================================================
-- \dt shopline_sync.*
-- SELECT grantee, privilege_type FROM information_schema.role_table_grants
--   WHERE table_schema = 'shopline_sync';
