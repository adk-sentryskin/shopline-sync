from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings for the SHOPLINE sync service.

    Values can be sourced from plain environment variables (development) or
    Google Cloud Secret Manager (production). Whichever is present is used.
    Mirrors the app-webhook (Shopify) service so the two stay consistent.
    """

    # Database — shared chekoutai PostgreSQL, search_path pinned to shopline_sync
    DB_DSN: str

    # API key for service-to-service authentication.
    # Generate using: python -c "import secrets; print(secrets.token_urlsafe(32))"
    API_KEY: str

    # SHOPLINE Open Platform API
    SHOPLINE_API_KEY: str            # client id
    SHOPLINE_API_SECRET: str         # client secret
    SHOPLINE_WEBHOOK_SECRET: str     # HMAC signing secret (often == app secret; confirm)
    # Admin API version (path segment). v20260601 confirmed current (2026-06-11).
    SHOPLINE_API_VERSION: str = "v20260601"
    SHOPLINE_SCOPES: str = "read_products,read_orders,read_content,read_page,read_shop_policy"

    # Application
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"

    # OAuth — ⚠️ SHOPLINE forbids query params in the redirect URI.
    SHOPLINE_OAUTH_REDIRECT_URL: str

    # Public base URL of this service (for webhook subscription registration).
    # If not provided, derived from SHOPLINE_OAUTH_REDIRECT_URL.
    APP_URL: Optional[str] = None

    # Where /api/oauth/callback redirects the browser after a successful connect.
    # If unset, the callback returns JSON instead of redirecting. The frontend
    # engineer provides this (e.g. https://app.chekout.ai/integrations/shopline).
    SHOPLINE_FRONTEND_RETURN_URL: Optional[str] = None

    # Token encryption (access_token + refresh_token at rest).
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str

    # Scheduler (Section 3 — token refresh before expiry + daily reconciliation)
    ENABLE_SCHEDULER: bool = True
    RECONCILIATION_HOUR: int = 2
    RECONCILIATION_MINUTE: int = 0

    # Google Cloud Platform (Vertex AI embeddings)
    GCP_PROJECT_ID: Optional[str] = None
    GCP_REGION: str = "us-central1"
    ENABLE_EMBEDDINGS: bool = True
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def app_url(self) -> str:
        """Public base URL, derived from the redirect URL when not set explicitly."""
        if self.APP_URL:
            return self.APP_URL.rstrip("/")
        # Strip the OAuth callback path to get the service root
        return self.SHOPLINE_OAUTH_REDIRECT_URL.split("/api/oauth/callback")[0].rstrip("/")


settings = Settings()
