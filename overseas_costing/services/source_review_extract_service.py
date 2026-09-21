"""Deterministic extraction rules used by unified source review runs."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Optional

from overseas_costing.services.material_value_semantics import is_effectively_missing


SIX_PLACES = Decimal("0.000001")


def _proposal_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        "|".join(str(part or "") for part in parts).encode("utf-8")
    ).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).replace(",", "").strip()
    try:
        number = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        matches = re.findall(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", text)
        if len(matches) != 1:
            return None
        try:
            number = Decimal(matches[0])
        except (InvalidOperation, TypeError, ValueError):
            return None
    return number if number.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def normalize_weight_uom(value: Any) -> str:
    text = str(value or "").strip().casefold().replace(" ", "")
    if text in {"kg", "kgs", "kilogram", "kilograms", "千克", "公斤"}:
        return "kg"
    return str(value or "").strip()


def allocate_gross_weight(total_gross: Decimal, net_weights: Iterable[Decimal]) -> list[Decimal]:
    """Allocate a shipment gross total by net weight with exact conservation."""

    gross = _decimal(total_gross)
    nets = [_decimal(value) for value in net_weights]
    if gross is None or gross <= 0 or not nets or any(value is None or value <= 0 for value in nets):
        return []
    typed_nets = [value for value in nets if value is not None]
    total_net = sum(typed_nets, Decimal("0"))
    if total_net <= 0:
        return []
    allocated: list[Decimal] = []
    for net in typed_nets[:-1]:
        allocated.append((gross * net / total_net).quantize(SIX_PLACES, rounding=ROUND_HALF_UP))
    allocated.append(gross.quantize(SIX_PLACES) - sum(allocated, Decimal("0")))
    return allocated


def _source_ref(source: dict, *, row: int = 0, field: str = "") -> dict:
    return {
        "source": "approval_form",
        "file": str(source.get("source_label") or "钉钉审批正文"),
        "sheet": "",
        "page": None,
        "row": row or None,
        "cell": "",
        "field": field,
        "source_id": str(source.get("source_id") or ""),
        "approval_no": str(source.get("approval_no") or ""),
        "actor_name": str(source.get("actor_name") or ""),
        "occurred_at": str(source.get("occurred_at") or ""),
    }


def _approval_goods_rows(source: dict) -> list[dict]:
    from overseas_costing.scripts.import_oa_logistics import extract_oa_goods_rows

    fields = source.get("form_fields") if isinstance(source.get("form_fields"), dict) else {}
    from overseas_costing.services.logistics_purchase_facts_service import parse_labelled_approval_rows
    for label, value in fields.items():
        if any(key in str(label) for key in ("货物信息", "采购明细", "需求明细")):
            labelled = parse_labelled_approval_rows(value)
            if labelled:
                return labelled
    payload = {
        "form_fields": fields,
        "transport_mode_raw": source.get("transport_mode_raw") or "",
        "logistics_no": source.get("approval_no") or "",
    }
    rows = extract_oa_goods_rows(payload)
    if rows:
        return rows
    for value in fields.values():
        if isinstance(value, list) and any(isinstance(row, dict) for row in value):
            return [dict(row) for row in value if isinstance(row, dict)]
    return []


def _match_item(items: list[dict], material_code: Any, source_doc_no: Any = "", *, mapped=None) -> Optional[dict]:
    code = str(material_code or "").strip().casefold()
    if not code:
        return None
    candidates = [
        item for item in items if str(item.get("material_code") or "").strip().casefold() == code
    ]
    source_no = str(source_doc_no or "").strip().casefold()
    if source_no:
        scoped = [
            item
            for item in candidates
            if str(item.get("source_doc_no") or "").strip().casefold() == source_no
        ]
        if scoped:
            candidates = scoped
    if len(candidates) > 1 and mapped:
        from .purchase_value_evidence import uom
        if uom(mapped.get('unit')):
            candidates = [item for item in candidates if uom(item.get('shipped_uom') or item.get('unit')) == uom(mapped['unit'])]
        if mapped.get('spec_model'):
            candidates = [item for item in candidates if str(item.get('spec_model') or '').strip().casefold()
                          == str(mapped['spec_model']).strip().casefold()]
        if len(candidates) > 1:
            candidates = [item for item in candidates if _decimal(item.get('actual_shipped_qty') or item.get('quantity'))
                          == _decimal(mapped.get('quantity'))]
    return candidates[0] if len(candidates) == 1 else None


def build_system_approval_proposals(
    items: list[dict],
    source: dict,
    *,
    transport_mode: str = "",
    fx_rates: dict | None = None,
) -> list[dict]:
    """Read same-row logistics quantities and purchase totals without an AI call.

    Source priority chooses defaults; it never forbids valid lower-priority
    purchase evidence. Identity and original purchase quantities stay read-only.
    """

    role = str(source.get('approval_role') or '')
    if role not in {'international_logistics', 'payment', 'purchase', 'logistics_expense'}:
        return []
    from overseas_costing.scripts.import_oa_logistics import (
        LOGISTICS_WEIGHT_FIELD_ALIASES,
        _find_field_value,
    )
    from .purchase_value_evidence import mapped_row, row_context

    goods_rows = [row_context(row, source) for row in _approval_goods_rows(source)]
    mapped_rows = []
    allocation_targets: set[str] = set()
    complete_net_set = bool(goods_rows)
    for source_row, raw in enumerate(goods_rows, start=1):
        mapped = mapped_row(raw)
        item = _match_item(items, mapped.get("material_code"), raw.get("source_doc_no"), mapped=mapped)
        quantity = _decimal(mapped.get("quantity"))
        if not item or quantity is None or quantity <= 0:
            complete_net_set = False
            continue
        uom = normalize_weight_uom(mapped.get("unit"))
        item_name = str(item.get("name") or "")
        if uom != "kg" or not item_name or item_name in allocation_targets:
            complete_net_set = False
        allocation_targets.add(item_name)
        fields = {
            "actual_shipped_qty": _decimal_text(quantity),
            "shipped_uom": uom,
        } if role == 'international_logistics' else {}
        if role == 'international_logistics' and uom == "kg":
            fields["net_weight_kg"] = _decimal_text(quantity)
        row_gross = _decimal(mapped.get("gross_weight_kg"))
        if role == 'international_logistics' and row_gross is not None and row_gross > 0:
            fields["gross_weight_kg"] = _decimal_text(row_gross)
        from .purchase_value_evidence import extract_row_fact
        fact = extract_row_fact(raw, role=str(source.get('approval_role') or ''), fx_rates=fx_rates)
        if fact:
            fields['goods_value'] = fact['amount_rmb']
        if fields:
            mapped_rows.append((source_row, item, fields))

    form_fields = source.get("form_fields") if isinstance(source.get("form_fields"), dict) else {}
    total_gross = _decimal(_find_field_value(form_fields, LOGISTICS_WEIGHT_FIELD_ALIASES))
    if (
        role == 'international_logistics' and total_gross
        and complete_net_set
        and len(mapped_rows) == len(goods_rows)
        and not any("gross_weight_kg" in fields for _, _, fields in mapped_rows)
    ):
        nets = [_decimal(fields.get("net_weight_kg")) for _, _, fields in mapped_rows]
        if all(value is not None and value > 0 for value in nets):
            allocation = allocate_gross_weight(total_gross, [value for value in nets if value is not None])
            for (_source_row, _item, fields), gross in zip(mapped_rows, allocation):
                fields["gross_weight_kg"] = _decimal_text(gross)

    proposals = []
    for source_row, item, fields in mapped_rows:
        conflict = any(
            not is_effectively_missing(fieldname, item.get(fieldname), item)
            and str(item.get(fieldname) or "").strip().casefold()
            != str(value or "").strip().casefold()
            for fieldname, value in fields.items()
        )
        proposals.append(
            {
                "proposal_id": _proposal_id(
                    "system-approval", source.get("source_id"), item.get("name")
                ),
                "proposal_type": "item_update",
                "target_item_name": str(item.get("name") or ""),
                "confidence": 1.0,
                "conflict": conflict,
                "default_selected": not conflict,
                "result_origin": "SYSTEM",
                "reason": "钉钉审批结构化明细由系统直接读取；同一行货值与数量配对。",
                "source_refs": [_source_ref(source, row=source_row, field=next(
                    (str(label) for label in form_fields if any(word in str(label) for word in ('货物信息', '采购明细', '需求明细'))),
                    '货物信息'))],
                "payload": {"item_name": str(item.get("name") or ""), "fields": fields},
            }
        )
    return proposals


def projection_candidates_to_review_proposals(candidates: list[dict], source: dict) -> list[dict]:
    """Convert deterministic packing projections to unified review proposals."""

    result = []
    for index, candidate in enumerate(candidates or [], start=1):
        item_name = str(candidate.get("item_name") or "")
        fieldname = str(candidate.get("fieldname") or "")
        if not item_name or not fieldname:
            continue
        result.append(
            {
                "proposal_id": _proposal_id(
                    "system-excel", source.get("source_id"), item_name, fieldname, index
                ),
                "proposal_type": "item_update",
                "target_item_name": item_name,
                "confidence": float(candidate.get("confidence") or 0.99),
                "conflict": float(candidate.get("confidence") or 0) < 0.9,
                "default_selected": float(candidate.get("confidence") or 0) >= 0.9,
                "result_origin": "SYSTEM",
                "reason": str(candidate.get("reason") or "Excel 确定性解析。"),
                "source_refs": list(candidate.get("source_refs") or []),
                **({"fact_ids": list(candidate.get("fact_ids") or [])} if candidate.get("fact_ids") else {}),
                "payload": {"item_name": item_name, "fields": {fieldname: candidate.get("suggested_value")}},
            }
        )
    return result
