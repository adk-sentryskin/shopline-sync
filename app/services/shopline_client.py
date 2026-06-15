"""SHOPLINE Admin OpenAPI client.

Confirmed against developer.shopline.com (2026-06-11):
  Base:   https://{handle}.myshopline.com/admin/openapi/{version}
  Auth:   Authorization: Bearer {access_token}   (NO appkey/timestamp/sign —
          request signing is only for the OAuth token create/refresh calls)
  Products: GET /products/products.json   (requires read_products scope)
  Rate limit: 20 req/s (HTTP 429 when exceeded).
"""
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ShoplineClient:
    def __init__(
        self,
        handle: str,
        access_token: str,
        version: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.handle = handle
        self.access_token = access_token
        self.version = version or settings.SHOPLINE_API_VERSION
        self.base_url = f"https://{handle}.myshopline.com/admin/openapi/{self.version}"
        self._client = client or httpx.Client(timeout=30.0)
        self._owns_client = client is None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=utf-8",
            "accept": "application/json",
        }

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        resp = self._client.get(f"{self.base_url}{path}", headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, json_body: Optional[dict] = None) -> dict:
        resp = self._client.post(f"{self.base_url}{path}", headers=self._headers(), json=json_body)
        resp.raise_for_status()
        return resp.json()

    def list_products(self, **params) -> dict:
        """GET the product list. params may include limit / page / since_id etc."""
        return self.get("/products/products.json", params=params or None)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
