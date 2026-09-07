"""物料录入的纯规则：稳定行、有效发货数量和单位来源。"""

from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, Optional
from uuid import uuid4


VALID_QTY_MODES = frozenset(
    {
        "DEFAULT_PURCHASE",
        "EXPLICIT_SOURCE",
        "MANUAL_CONFIRMED",
        "LEGACY_UNVERIFIED",
    }
)


def _positive_decimal(value: object) -> Optional[Decimal]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def ensure_stable_line_key(
    item: dict,
    *,
    key_factory: Optional[Callable[[], str]] = None,
) -> str:
    """Return the existing business-row key, or create one for a new row."""

    existing = str(item.get("stable_line_key") or "").strip()
    if existing:
        return existing
    generated = str((key_factory or (lambda: uuid4().hex))() or "").strip()
    if not generated:
        raise ValueError("stable_line_key generator returned an empty value")
    return generated


def resolve_effective_quantity(item: dict) -> Dict[str, object]:
    """Resolve the quantity used by costing without inferring legacy provenance."""

    mode = str(item.get("actual_shipped_qty_mode") or "LEGACY_UNVERIFIED").strip()
    if mode not in VALID_QTY_MODES:
        mode = "LEGACY_UNVERIFIED"

    raw_quantity = item.get("quantity") if mode == "DEFAULT_PURCHASE" else item.get("actual_shipped_qty")
    quantity = _positive_decimal(raw_quantity)
    uom = str(item.get("shipped_uom") or item.get("purchase_uom") or item.get("unit") or "").strip()
    blocking = []
    if quantity is None:
        blocking.append({"code": "SHIPPED_QTY_REQUIRED", "field": "actual_shipped_qty"})
    if not uom:
        blocking.append({"code": "SHIPPED_UOM_REQUIRED", "field": "shipped_uom"})

    return {
        "quantity": format(quantity, "f") if quantity is not None else "",
        "uom": uom,
        "mode": mode,
        "is_default": mode == "DEFAULT_PURCHASE",
        "blocking": blocking,
    }


def resolve_goods_value(item: dict) -> Dict[str, object]:
    """Resolve purchase value without multiplying quantities in incompatible units."""

    explicit = _positive_decimal(item.get("goods_value"))
    if explicit is not None:
        return {"amount": explicit, "source": "EXPLICIT_AMOUNT", "blocking": []}

    price = _positive_decimal(item.get("unit_price"))
    purchase_quantity = _positive_decimal(item.get("quantity"))
    price_uom = str(item.get("unit_price_uom") or "").strip()
    purchase_uom = str(item.get("purchase_uom") or item.get("unit") or "").strip()
    if (
        price is not None
        and purchase_quantity is not None
        and price_uom
        and price_uom == purchase_uom
    ):
        return {
            "amount": price * purchase_quantity,
            "source": "PRICE_X_PURCHASE_QTY",
            "blocking": [],
        }

    return {
        "amount": Decimal("0"),
        "source": "UNRESOLVED",
        "blocking": [
            {
                "code": "GOODS_VALUE_OR_UOM_CONVERSION_REQUIRED",
                "field": "goods_value",
            }
        ],
    }
