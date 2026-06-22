"""Read-time attribution extraction for SHOPLINE orders.

shopify-sync extracts attribution markers into dedicated indexed columns at
ingest. The SHOPLINE order model only stores the full order JSON in
``shopline_orders.raw_data``, so we extract attribution at READ time here.

Field names follow the confirmed SHOPLINE Admin REST order schema
(GET /admin/openapi/<version>/orders.json):
  - order: id, name, created_at, currency, current_total_price, financial_status,
           note, note_attributes[{name, value}]
  - line item: product_id, variant_id, sku, title, quantity, price,
               properties[{name, value, type, show}], customized_attributes[{key, value}]

The chat widget stamps ``_chekout_ai_session/agent/source`` as line-item
properties at POST /cart/add, so they surface under line_items[].properties on
the resulting order (the Admin API lowercases the name/value keys the Ajax cart
API capitalized — handled below). Order-level note_attributes and line-item
customized_attributes are also scanned defensively.

Once order volume grows, move this to ingest-time extraction with indexed
columns (mirror shopify-sync) for faster querying.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

ATTRIBUTION_PREFIX = "chekout_ai"
_SESSION = f"{ATTRIBUTION_PREFIX}_session"
_AGENT = f"{ATTRIBUTION_PREFIX}_agent"
_SOURCE = f"{ATTRIBUTION_PREFIX}_source"


def _unwrap(raw: Any) -> dict:
    """Some SHOPLINE payloads wrap the body in a top-level ``data`` object."""
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        return raw["data"]
    return raw if isinstance(raw, dict) else {}


def _norm_key(name: Optional[str]) -> str:
    return (name or "").lstrip("_").strip().lower()


def _kv_pairs(obj: Any) -> Iterator[Tuple[Optional[str], Any]]:
    """Yield (name, value) from a map {k: v} or a list of attribute objects.

    Handles SHOPLINE's varied shapes: {name, value} (note_attributes / order
    line-item properties), {Name, Value} (Ajax cart properties), and
    {key, value} (customized_attributes).
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
    elif isinstance(obj, list):
        for item in obj:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name") or item.get("key")
            if "value" in item:
                value = item.get("value")
            elif "Value" in item:
                value = item.get("Value")
            else:
                value = None
            yield name, value


def _collect(obj: Any, found: dict) -> None:
    for name, value in _kv_pairs(obj):
        key = _norm_key(name)
        if not key.startswith(ATTRIBUTION_PREFIX):
            continue
        if key == _SESSION:
            found.setdefault("chekout_ai_session", value)
        elif key == _AGENT:
            found.setdefault("chekout_ai_agent", value)
        elif key == _SOURCE:
            found.setdefault("chekout_ai_source", value)
        else:
            # Some chekout_ai_* key we don't have a slot for — presence alone
            # still flags the order as attributed.
            found.setdefault("_attributed", True)


def line_items(raw: Any) -> list:
    src = _unwrap(raw)
    val = src.get("line_items")
    if isinstance(val, list):
        return val
    for key in ("lineItems", "items"):  # defensive fallbacks for shape drift
        v = src.get(key)
        if isinstance(v, list):
            return v
    return []


def extract_attribution(raw: Any) -> dict:
    """Return {chekout_ai_session, chekout_ai_agent, chekout_ai_source, attributed}.

    ``attributed`` is True if any chekout_ai_* marker is present anywhere we look.
    """
    src = _unwrap(raw)
    found: dict = {}
    # Order-level attribute containers.
    for key in ("note_attributes", "noteAttributes", "attributes", "customized_attributes"):
        if key in src:
            _collect(src.get(key), found)
    # Line-item properties — where the widget stamps via /cart/add.
    for li in line_items(src):
        if isinstance(li, dict):
            _collect(li.get("properties"), found)
            _collect(li.get("customized_attributes"), found)
    attributed = any(
        found.get(k) for k in ("chekout_ai_session", "chekout_ai_agent", "chekout_ai_source")
    ) or bool(found.get("_attributed"))
    return {
        "chekout_ai_session": found.get("chekout_ai_session"),
        "chekout_ai_agent": found.get("chekout_ai_agent"),
        "chekout_ai_source": found.get("chekout_ai_source"),
        "attributed": attributed,
    }


def normalized_line_items(raw: Any) -> list:
    """PII-free line items in the dashboard shape: product_id/title/quantity/price."""
    out = []
    for li in line_items(raw):
        if not isinstance(li, dict):
            continue
        out.append({
            "product_id": li.get("product_id") or li.get("variant_id") or li.get("sku") or li.get("id"),
            "title": li.get("title") or li.get("name"),
            "quantity": li.get("quantity") or 0,
            "price": li.get("price"),
        })
    return out


def order_created_at(raw: Any) -> Optional[datetime]:
    """Parse the order's placed timestamp (ISO 8601) to a tz-aware datetime."""
    src = _unwrap(raw)
    value = src.get("created_at") or src.get("createdAt")
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def order_total_price(raw: Any) -> Optional[str]:
    """Order total. SHOPLINE's field is ``current_total_price`` (string)."""
    src = _unwrap(raw)
    value = src.get("current_total_price") or src.get("total_price") or src.get("totalPrice")
    return str(value) if value is not None else None


def order_currency(raw: Any) -> Optional[str]:
    src = _unwrap(raw)
    return src.get("currency") or src.get("currency_code")


def order_financial_status(raw: Any) -> Optional[str]:
    src = _unwrap(raw)
    return src.get("financial_status") or src.get("financialStatus")


def order_external_id(raw: Any) -> Optional[str]:
    src = _unwrap(raw)
    oid = src.get("id") or src.get("order_id")
    return str(oid) if oid is not None else None


def order_name(raw: Any) -> Optional[str]:
    src = _unwrap(raw)
    return src.get("name") or src.get("order_number")
