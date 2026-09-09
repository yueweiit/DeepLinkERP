"""Shared material-field placeholder and correction semantics."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


PLACEHOLDER_TOKENS = frozenset(
    {"", "-", "--", "/", "\\", "n/a", "na", "null", "none", "无", "暂无"}
)
ZERO_IS_MISSING_FIELDS = frozenset(
    {
        "goods_value",
        "unit_price",
        "net_weight_kg",
        "gross_weight_kg",
        "volume_m3",
        "chargeable_weight_kg",
    }
)
PROTECTED_ZERO_SHIPPING_MODES = frozenset({"MANUAL_CONFIRMED", "EXPLICIT_SOURCE"})


def is_placeholder_token(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return " ".join(value.strip().split()).casefold() in PLACEHOLDER_TOKENS


def _is_zero(value: Any) -> bool:
    try:
        return Decimal(str(value).strip()) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def is_effectively_missing(fieldname: str, value: Any, item: dict | None = None) -> bool:
    """Treat UI placeholders and field-specific default zeroes as missing evidence."""

    if is_placeholder_token(value):
        return True
    field = str(fieldname or "")
    if field in ZERO_IS_MISSING_FIELDS and _is_zero(value):
        return True
    if field == "actual_shipped_qty" and _is_zero(value):
        mode = str((item or {}).get("actual_shipped_qty_mode") or "").strip().upper()
        return mode not in PROTECTED_ZERO_SHIPPING_MODES
    return False
