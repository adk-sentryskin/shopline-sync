# shopline-sync

OAuth + webhook sync microservice for **SHOPLINE** merchants. Parallel to
`app-webhook` (the Shopify sync service); owns the `shopline_sync` PostgreSQL
schema in the shared `chekoutai` database.

> Status: **Section 1–2 scaffold** (service boots, data model + migration in
> place, OAuth/webhook/sync handlers are stubs). See `SHOPLINE_SYNC_TODO.md`.

## Layout

```
app/
  main.py                  FastAPI app, API-key middleware, /health
  config.py                pydantic-settings (env or Secret Manager)
  database.py              SQLAlchemy engine + init_db()
  models.py                shopline_stores / _products / _orders / _webhooks
  schemas.py               Pydantic request/response models
  middleware/auth.py       X-API-Key + X-Merchant-Id
  utils/encryption.py      Fernet token encryption (access + refresh)
  utils/webhook_verification.py   ⚠️ base16-hex HMAC (X-Shopline-Hmac-Sha256)
  routers/                 oauth / webhooks / sync  (STUBS — Section 3)
migrations/001_create_shopline_sync.sql   authoritative DDL (+ index, grants)
tests/                     pytest: health, config, HMAC, encryption
```

## Local run

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in values
python run.py                 # http://localhost:8000/docs
```

## Tests

```bash
pytest -v
```

## Key SHOPLINE divergences from Shopify

- Webhook HMAC is **base16 hex** in `X-Shopline-Hmac-Sha256` (Shopify: base64).
- Product `id` is a **string** (Shopify: numeric).
- Tokens **expire** → `refresh_token` + `token_expires_at` columns + refresh scheduler.
- OAuth redirect URI allows **no query params** → `state` carried via signed cookie.
- Webhook ack window is **5s** → ack fast, process async.

## Deploy

```bash
./deploy.sh development     # service: shopline-sync (shopify-473015 / us-central1)
```

Secrets come from Secret Manager: `SHOPLINE_API_KEY`, `SHOPLINE_API_SECRET`,
`SHOPLINE_WEBHOOK_SECRET`, `SHOPLINE_OAUTH_REDIRECT_URL`, `DB_DSN`, `API_KEY`,
`ENCRYPTION_KEY`.
