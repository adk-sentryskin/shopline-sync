"""Read endpoints for SHOPLINE sales attribution.

Mirrors the shopify-sync contract so the dashboard consumes SHOPLINE attribution
through identical shapes:

    GET /api/orders/scope-status
    GET /api/orders/attribution-summary
    GET /api/orders/attributed

Unlike Shopify (where read_orders is an optional scope behind an upgrade flow),
SHOPLINE grants read_orders at install — so scope-status reports granted=true for
any connected store carrying the scope, and there is deliberately no
upgrade-scopes endpoint here.

Attribution is extracted from raw_data at read time (see order_attribution). The
chat widget stamps _chekout_ai_* as line-item properties at /cart/add; those
surface under line_items[].properties on the order.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_merchant_from_header
from app.models import ShoplineOrder, ShoplineStore
from app.services import order_attribution as attribution

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orders", tags=["orders"])

REQUIRED_SCOPE = "read_orders"
WINDOW_DAYS = 60
PAID_STATUS = "paid"


def _scopes(store: ShoplineStore) -> set:
    raw = (store.scopes or "").replace(" ", ",")
    return {s.strip() for s in raw.split(",") if s.strip()}


def _has_orders_scope(store: ShoplineStore) -> bool:
    return REQUIRED_SCOPE in _scopes(store)


def _ensure_scope(store: ShoplineStore) -> None:
    if not _has_orders_scope(store):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Merchant has not granted the '{REQUIRED_SCOPE}' scope. "
                "Sales attribution is unavailable until order access is authorized."
            ),
        )


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def _attributed_orders(db: Session, store: ShoplineStore, window_days: int = WINDOW_DAYS):
    """Agent-attributed orders for this merchant within the window, newest first.

    Reads the local ``shopline_orders`` table and extracts attribution from
    raw_data — no SHOPLINE call in the request path. Returns dicts shaped
    ``{row, attr, raw, created_at(datetime|None)}``. Volume is low, so the
    per-row extraction is cheap; revisit with indexed columns if that changes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        db.query(ShoplineOrder)
        .filter(ShoplineOrder.merchant_id == store.merchant_id)
        .all()
    )
    out = []
    for r in rows:
        raw = r.raw_data or {}
        attr = attribution.extract_attribution(raw)
        if not attr["attributed"]:
            continue
        created = attribution.order_created_at(raw) or r.created_at
        if created and created < cutoff:
            continue
        out.append({"row": r, "attr": attr, "raw": raw, "created_at": created})
    out.sort(
        key=lambda o: o["created_at"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return out


@router.get("/scope-status")
async def order_scope_status(
    store: ShoplineStore = Depends(get_merchant_from_header),
):
    """Whether this merchant can use sales attribution.

    SHOPLINE grants read_orders at install, so this is true for any connected
    store carrying the scope — there's no separate 'enable' grant like Shopify.
    """
    granted = _has_orders_scope(store)
    return {
        "merchant_id": store.merchant_id,
        "required_scope": REQUIRED_SCOPE,
        "granted": granted,
        "sales_attribution_available": granted,
    }


@router.get("/attributed")
async def get_attributed_orders(
    limit: int = Query(100, ge=1, le=500, description="Max orders to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """Agent-attributed orders, newest first. Backed by the local table."""
    _ensure_scope(store)
    items = _attributed_orders(db, store)
    page = items[offset:offset + limit]
    orders = []
    for it in page:
        r, raw = it["row"], it["raw"]
        orders.append({
            "order_id": attribution.order_external_id(raw),
            "order_name": attribution.order_name(raw) or r.order_number,
            "created_at": it["created_at"].isoformat() if it["created_at"] else None,
            "financial_status": attribution.order_financial_status(raw) or r.financial_status,
            "total_price": attribution.order_total_price(raw)
            or (str(r.total_price) if r.total_price is not None else None),
            "currency": attribution.order_currency(raw) or r.currency,
            "chekout_ai_session": it["attr"]["chekout_ai_session"],
            "line_items": attribution.normalized_line_items(raw),
        })
    return {
        "merchant_id": store.merchant_id,
        "site_url": store.site_url,
        "window_days": WINDOW_DAYS,
        "count": len(orders),
        "orders": orders,
    }


@router.get("/attribution-summary")
async def attribution_summary(
    store: ShoplineStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """Aggregate KPIs for the dashboard widgets: orders, revenue, units, products.

    Revenue + units are summed over PAID orders only (mirrors shopify-sync);
    by_financial_status counts every attributed order regardless of status.
    """
    _ensure_scope(store)
    items = _attributed_orders(db, store)

    orders_attributed = len(items)
    total_revenue = Decimal(0)
    units_sold = 0
    unique_products = set()
    by_status: dict = {}
    currency_counts: dict = {}

    for it in items:
        raw, row = it["raw"], it["row"]
        status = attribution.order_financial_status(raw) or row.financial_status or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        if status.lower() != PAID_STATUS:
            continue
        total_revenue += _to_decimal(
            attribution.order_total_price(raw)
            or (row.total_price if row.total_price is not None else None)
        )
        currency = attribution.order_currency(raw) or row.currency
        if currency:
            currency_counts[currency] = currency_counts.get(currency, 0) + 1
        for li in attribution.normalized_line_items(raw):
            try:
                units_sold += int(li.get("quantity") or 0)
            except (TypeError, ValueError):
                pass
            pid = li.get("product_id")
            if pid is not None:
                unique_products.add(pid)

    currency = max(currency_counts, key=currency_counts.get) if currency_counts else None

    return {
        "merchant_id": store.merchant_id,
        "site_url": store.site_url,
        "window_days": WINDOW_DAYS,
        "summary": {
            "orders_attributed": orders_attributed,
            "total_revenue": str(total_revenue),
            "currency": currency,
            "units_sold": units_sold,
            "unique_products": len(unique_products),
            "by_financial_status": by_status,
        },
    }
