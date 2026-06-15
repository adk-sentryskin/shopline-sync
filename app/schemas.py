from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ShoplineStoreBase(BaseModel):
    merchant_id: str
    shop_handle: str


class ShoplineStoreResponse(ShoplineStoreBase):
    id: int
    site_url: Optional[str] = None
    scopes: Optional[str] = None
    is_active: int
    token_expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OAuthStart(BaseModel):
    """Begin the OAuth install flow for a merchant."""
    shop_handle: str = Field(..., description="SHOPLINE store handle (e.g. mystore)")
    merchant_id: str = Field(..., description="Chekout merchant identifier")


class OAuthCallback(BaseModel):
    """
    OAuth callback payload.

    ⚠️ SHOPLINE forbids query params in the whitelisted redirect URI, so `state`
    is carried via a signed cookie/session rather than the URL. These fields are
    parsed from the callback request the platform makes to /api/oauth/callback.
    """
    code: str = Field(..., description="Authorization code from SHOPLINE")
    handle: Optional[str] = Field(None, description="Store handle returned by SHOPLINE")
    state: Optional[str] = Field(None, description="State value (from signed cookie)")
    merchant_id: Optional[str] = Field(None, description="Merchant id when state not used")


class ProductResponse(BaseModel):
    id: int
    shopline_product_id: str
    merchant_id: str
    title: Optional[str] = None
    vendor: Optional[str] = None
    product_type: Optional[str] = None
    handle: Optional[str] = None
    status: Optional[str] = None
    is_deleted: int = 0
    synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductSyncStatus(BaseModel):
    synced_count: int
    created_count: int
    updated_count: int
    failed_count: int = 0
