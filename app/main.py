from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import init_db
from app.routers import oauth, webhooks, sync, diagnostics
import logging
import secrets

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown. DB init is best-effort so the service can still serve
    /health if the DB is briefly unreachable (the authoritative DDL is the SQL
    migration, not this fallback)."""
    try:
        init_db()
    except Exception as e:  # pragma: no cover - exercised only when DB is down
        logger.warning("init_db skipped (DB unreachable at startup): %s", e)
    yield
    # Scheduler shutdown will be wired here in Section 3.


app = FastAPI(
    title="SHOPLINE Sync Service",
    description="OAuth-based microservice for syncing SHOPLINE products/orders per merchant",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — mirror app-webhook; allow the SHOPLINE webhook/topic headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-API-Key",
        "X-Merchant-Id",
        "Authorization",
        "Accept",
        "X-Shopline-Hmac-Sha256",  # webhook signature
        "X-Shopline-Topic",        # webhook routing
    ],
    expose_headers=["Content-Type"],
    max_age=600,
)

# Paths that bypass the global API-key check.
PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/oauth/callback",  # SHOPLINE redirects the browser here (state-signed, no API key)
}
# Webhook paths authenticate via HMAC, not the API key.
WEBHOOK_PATHS = {
    "/api/webhooks/shopline",
    "/api/webhooks/customers/redact",  # GDPR mandatory
    "/api/webhooks/shop/redact",       # GDPR mandatory
}


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Require X-API-Key on all endpoints except public + webhook paths."""
    path = request.url.path

    if request.method == "OPTIONS":
        return await call_next(request)

    if path in PUBLIC_PATHS or path in WEBHOOK_PATHS:
        return await call_next(request)

    api_key = request.headers.get("x-api-key")
    if not api_key:
        return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key header"})
    if not secrets.compare_digest(api_key, settings.API_KEY):
        return JSONResponse(status_code=403, content={"detail": "Invalid API Key"})

    return await call_next(request)


app.include_router(oauth.router)
app.include_router(webhooks.router)
app.include_router(sync.router)
app.include_router(diagnostics.router)


@app.get("/")
async def root():
    return {"service": "shopline-sync", "status": "ok", "version": app.version}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "shopline-sync"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=True)
