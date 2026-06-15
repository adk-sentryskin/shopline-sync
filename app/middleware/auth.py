from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models import ShoplineStore
from app.config import settings
import secrets


async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """Verify the API key for service-to-service authentication."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    if not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API Key")

    return True


async def get_merchant_from_header(
    x_merchant_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> ShoplineStore:
    """Resolve an active, authenticated SHOPLINE store from the X-Merchant-Id header."""
    if not x_merchant_id:
        raise HTTPException(
            status_code=400,
            detail="Missing X-Merchant-Id header. Required for merchant-specific operations.",
        )

    store = (
        db.query(ShoplineStore)
        .filter(ShoplineStore.merchant_id == x_merchant_id, ShoplineStore.is_active == 1)
        .first()
    )

    if not store:
        raise HTTPException(status_code=404, detail="SHOPLINE store not found or inactive")

    if not store.access_token:
        raise HTTPException(
            status_code=403,
            detail="SHOPLINE store has not completed OAuth. Please authenticate first.",
        )

    return store


async def get_optional_merchant(
    x_merchant_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[ShoplineStore]:
    """Optional store lookup (used during OAuth initiation, before a token exists)."""
    if not x_merchant_id:
        return None
    return (
        db.query(ShoplineStore)
        .filter(ShoplineStore.merchant_id == x_merchant_id)
        .first()
    )
