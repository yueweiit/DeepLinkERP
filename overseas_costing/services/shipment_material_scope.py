"""Conservative shipment identity rules shared by logistics and payment evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
import unicodedata


IDENTIFIER_LABELS = (
    "运单号",
    "快递单号",
    "物流单号",
    "提单号",
    "装箱单号",
    "装箱号",
    "waybill",
    "trackingnumber",
    "trackingno",
    "awb",
    "packinglistnumber",
    "packinglistno",
    "物流审批号",
    "审批编号",
    "approvalno",
)


def normalize_shipment_identifier(value: object) -> str:
    """Normalize presentation only; matching remains complete-value equality."""

    text = unicodedata.normalize("NFKC", str(value or "")).upper().strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return "".join(character for character in text if character.isalnum())


def _normalized_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def _label_is_identifier(label: object) -> bool:
    normalized = _normalized_label(label)
    return any(alias in normalized for alias in IDENTIFIER_LABELS)


def _values(value: object) -> Iterable[object]:
    if isinstance(value, Mapping):
        for label, child in value.items():
            if _label_is_identifier(label):
                if isinstance(child, (list, tuple, set)):
                    yield from child
                else:
                    yield child
            if isinstance(child, (Mapping, list, tuple, set)):
                yield from _values(child)
        return
    if isinstance(value, (list, tuple, set)):
        for child in value:
            if isinstance(child, tuple) and len(child) == 2 and str(child[0]).casefold() in {
                "waybill", "tracking", "awb", "packing_list", "packinglist", "approval",
            }:
                yield child[1]
            elif isinstance(child, (Mapping, list, tuple, set)):
                yield from _values(child)


def shipment_identifiers(value: object) -> set[str]:
    """Extract explicit shipment references without fuzzy/substring matching."""

    result = {normalize_shipment_identifier(raw) for raw in _values(value)}
    if isinstance(value, Mapping):
        text = "\n".join(
            str(value.get(key) or "")
            for key in ("scoped_text", "text", "comment_text", "remark")
        )
        aliases = (
            r"运单号", r"快递单号", r"物流单号", r"提单号",
            r"装箱单号", r"AWB", r"Waybill", r"Tracking\s*(?:Number|No)",
            r"Packing\s*List\s*(?:Number|No)",
        )
        pattern = rf"(?:{'|'.join(aliases)})\s*[:：#]?\s*([A-Z0-9][A-Z0-9\-]{{3,}})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            result.add(normalize_shipment_identifier(match.group(1)))
    return {identifier for identifier in result if len(identifier) >= 4}


def same_shipment(evidence: object, allowed_identifiers: Iterable[object]) -> bool:
    allowed = {
        normalize_shipment_identifier(value)
        for value in allowed_identifiers or []
        if normalize_shipment_identifier(value)
    }
    return bool(allowed.intersection(shipment_identifiers(evidence)))
