"""Pure, traceable shipment valuation; purchase totals are never apportioned or changed."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from typing import Any

from overseas_costing.utils.field_mapper import normalize_unit


MONEY_TOLERANCE = Decimal("0.01")


def build_shipment_valuations(items: list[dict], preview: dict, source: dict) -> dict:
    """Return valuation/project proposals keyed by item name, without mutating inputs.

    Rows must already carry a uniquely matched ``_target_stable_line_key``.
    ``quantity`` and ``uom`` are the actual shipment inputs at valuation time,
    allowing consumers to invalidate the result when those inputs change.
    All automatically valued currencies are explicitly evidenced RMB/CNY.
    """
    rows = preview.get("material_rows") or []
    valuations, projects, warnings = {}, {}, []
    packing_warnings = {}
    row_keys = Counter(_text(row.get("_target_stable_line_key")) for row in rows)
    item_keys = Counter(_text(item.get("stable_line_key")) for item in items)
    item_names = Counter(_text(item.get("name")) for item in items)
    by_key = {_text(row.get("_target_stable_line_key")): row for row in rows}
    for item in items:
        name, key = _text(item.get("name")), _text(item.get("stable_line_key"))
        label = f"{name or '未命名物料'}（{item.get('material_code') or key}）"
        metadata = _metadata(item.get("extra_json"))
        saved = metadata.get("shipment_valuation")
        manual = _confirmed_manual(saved)
        if name and item_names[name] == 1 and manual:
            valuations[name] = deepcopy(saved)
        if not name or item_names[name] != 1 or not key or item_keys[key] != 1 or row_keys[key] != 1:
            warnings.append(f"{label} 装箱行缺少唯一稳定行匹配，自动发货估值不可用。")
            continue
        row = by_key[key]
        project = _text(row.get("project_collection"))
        if project:
            projects[name] = project
        if manual:
            continue
        qty, uom, reason = _shipment_inputs(item, row)
        if reason:
            warnings.append(f"{label} {reason}")
            continue
        if (row.get("currency_evidence") or {}).get("kind") == "conflict":
            warnings.append(f"{label} 装箱单价、总价或币种列的币种证据冲突，发货估值不可用。")
            continue
        currency = _currency(row.get("currency"))
        if currency and currency != "RMB":
            warnings.append(f"{label} 装箱币种 {currency} 不是 RMB/CNY，当前无法生成人民币发货估值。")
            continue
        value, reason = _packing_value(item, row, source, qty, uom)
        if value is None:
            if reason:
                message = f"{label} {reason}"
                warnings.append(message)
                packing_warnings[row.get("source_row")] = message
            value, purchase_reason = _purchase_value(item, row, source, qty, uom, metadata)
            if value is None and purchase_reason:
                warnings.append(f"{label} {purchase_reason}")
        if value is not None:
            valuations[name] = value
    verified_rows = _verify_group_controls(items, rows, valuations, warnings)
    resolved_warnings = {packing_warnings.get(number) for number in verified_rows}
    warnings = [message for message in warnings if message not in resolved_warnings]
    return {"valuations": valuations, "projects": projects, "warnings": list(dict.fromkeys(warnings))}


def _shipment_inputs(item, row):
    qty = _number(item.get("actual_shipped_qty"))
    row_qty = _number(row.get("quantity"))
    uom = normalize_unit(item.get("shipped_uom") or item.get("unit"))
    row_uom = normalize_unit(row.get("unit"))
    if _missing_cache(row, ("quantity", "unit")):
        return None, None, "装箱数量或单位公式缺少缓存结果，发货估值不可用。"
    if qty is None or qty < 0 or row_qty is None or row_qty != qty:
        return None, None, "装箱数量与实际发货数量不一致或缺失，发货估值不可用。"
    if not uom or not row_uom or uom != row_uom:
        return None, None, f"装箱单位 {row_uom or '缺失'} 与发货单位 {uom or '缺失'} 不一致，发货估值不可用。"
    return qty, uom, None


def _packing_value(item, row, source, qty, uom):
    if _missing_cache(row, ("unit_price", "total_amount", "currency")):
        return None, "装箱金额、单价或币种公式缺少缓存结果，未将其按空白或零计价。"
    price, amount = _number(row.get("unit_price")), _number(row.get("total_amount"))
    if price is None and amount is None:
        return None, None
    if _shared_field(row, "unit_price") or _shared_field(row, "total_amount"):
        return None, "装箱价格或金额来自跨行合并单元格，仅可核对组控制总额，不能重复用于各行。"
    if _currency(row.get("currency")) != "RMB" or not row.get("currency_evidence"):
        return None, "装箱价格缺少明确人民币币种证据，不能生成发货估值。"
    if price is None or price < 0:
        return None, "装箱单价缺失或无效，无法核对该行金额。"
    calculated = qty * price
    if amount is not None and (amount < 0 or abs(amount - calculated) > MONEY_TOLERANCE):
        return None, f"装箱总价 {_text(row.get('total_amount'))} 与单价×发货数量 {_decimal(calculated)} 不一致，未作为该行货值。"
    if amount is None and row.get("total_amount") not in (None, ""):
        return None, "装箱总价不是有效数字，无法生成该行发货估值。"
    return _valuation(item, row, source, qty, uom, price,
                      amount if amount is not None else calculated,
                      "packing_row_total" if amount is not None else "packing_unit_price"), None


def _purchase_value(item, row, source, qty, uom, metadata):
    association = metadata.get("logistics_row") or {}
    if not isinstance(association, dict):
        association = {}
    fact = association.get("purchase_fact")
    linked = association.get("purchase_key") or association.get("purchase_source_id")
    if not isinstance(fact, dict) or not (linked or fact.get("source_doc_no")):
        return None, "没有已关联的采购事实，发货估值待核对。"
    price = _number(fact.get("unit_price"))
    if price is None or price < 0:
        return None, "关联采购事实缺少有效单价，发货估值待核对。"
    currency = _currency(fact.get("purchase_currency"))
    if currency != "RMB":
        return None, f"关联采购币种 {currency or '缺失'} 缺少可用人民币证据，发货估值待核对。"
    purchase_uom = normalize_unit(fact.get("unit_price_uom") or fact.get("purchase_uom")
                                  or item.get("unit_price_uom") or item.get("purchase_uom") or item.get("unit"))
    if not purchase_uom or purchase_uom != uom:
        return None, f"采购单价单位 {purchase_uom or '缺失'} 与发货单位 {uom} 不一致，未做单位换算。"
    value = _valuation(item, row, source, qty, uom, price, qty * price, "purchase_unit_price")
    value["input_evidence"]["purchase_fact"] = deepcopy(fact)
    value["input_evidence"]["purchase_unit_price_uom"] = purchase_uom
    value["source_refs"].append({"source_kind": "purchase_fact", "source_id": association.get("purchase_source_id"),
                                 "source_doc_no": fact.get("source_doc_no"), "purchase_key": association.get("purchase_key"),
                                 "purchase_row_id": association.get("purchase_row_id")})
    return value, None


def _verify_group_controls(items, rows, valuations, warnings):
    """Recognize controls only after every member was independently purchase-valued.

    A real amount merge supplies its exact range. An unmerged leading amount can
    only be checked against the complete following blank-price block, which must
    be contiguous and share an explicit project. This records a check, never an
    allocation or an inferred merge.
    """
    ordered = sorted(rows, key=lambda row: row.get("source_row") or 0)
    names = {_text(item.get("stable_line_key")): _text(item.get("name")) for item in items}
    verified_rows = set()
    for index, row in enumerate(ordered):
        amount = _number(row.get("total_amount"))
        if amount is None or amount < 0 or _currency(row.get("currency")) != "RMB":
            continue
        if _missing_cache(row, ("unit_price", "total_amount", "currency")):
            continue
        region = (row.get("field_ranges") or {}).get("total_amount") or {}
        number = row.get("source_row") or 0
        if region.get("start_row", number) != number:
            continue
        if _shared_field(row, "total_amount"):
            members = [candidate for candidate in ordered
                       if region["start_row"] <= (candidate.get("source_row") or 0) <= region["end_row"]]
            expected_count = region["end_row"] - region["start_row"] + 1
        else:
            price, qty = _number(row.get("unit_price")), _number(row.get("quantity"))
            if price is not None and qty is not None and abs(amount - price * qty) <= MONEY_TOLERANCE:
                continue
            members = [row]
            for candidate in ordered[index + 1:]:
                if (candidate.get("unit_price") not in (None, "") or candidate.get("total_amount") not in (None, "")
                        or _missing_cache(candidate, ("unit_price", "total_amount"))):
                    break
                members.append(candidate)
            expected_count = len(members)
        project = _text(row.get("project_collection"))
        row_numbers = [member.get("source_row") for member in members]
        values = [valuations.get(names.get(_text(member.get("_target_stable_line_key")), "")) for member in members]
        verified = (len(members) > 1 and len(members) == expected_count and project
                    and row_numbers == list(range(number, number + expected_count))
                    and all(_text(member.get("project_collection")) == project for member in members)
                    and all(value and value.get("method") == "purchase_unit_price" for value in values))
        if verified:
            total = sum((_number(value["amount_rmb"]) for value in values), Decimal("0"))
            verified = abs(total - amount) <= MONEY_TOLERANCE
        if not verified:
            warnings.append(f"第 {number} 行金额 {_decimal(amount)} 未通过同项目完整采购估值加总，不能确认组控制范围或分摊。")
            continue
        control = {"role": "control_only", "amount_rmb": _decimal(amount), "project_collection": project,
                   "source_row": number, "source_range": deepcopy(region), "verified_row_numbers": row_numbers,
                   "method": "independent_purchase_sum", "field_evidence": deepcopy((row.get("field_evidence") or {}).get("total_amount"))}
        for value in values:
            value["input_evidence"]["group_control"] = deepcopy(control)
        verified_rows.update(row_numbers)
    return verified_rows


def _shared_field(row, field):
    region = (row.get("field_ranges") or {}).get(field) or {}
    return bool(region and region.get("end_row", 0) > region.get("start_row", 0))


def _valuation(item, row, source, qty, uom, price, amount, method):
    return {"amount_rmb": _decimal(amount.quantize(MONEY_TOLERANCE, rounding=ROUND_HALF_UP)),
            "unit_price": _decimal(price), "currency": "RMB", "quantity": _decimal(qty),
            "uom": uom, "method": method, "source_hash": source.get("source_hash"),
            "source_refs": [{"source_id": source.get("source_id"), "source_kind": source.get("source_kind"),
                             "source_hash": source.get("source_hash"), "sheet_name": source.get("sheet_name"),
                             "source_row": row.get("source_row"), "field_ranges": deepcopy(row.get("field_ranges") or {})}],
            "input_evidence": {"stable_line_key": item.get("stable_line_key"),
                               "actual_shipped_qty": _decimal(qty), "shipped_uom": uom,
                               "item_unit": item.get("unit"), "packing_quantity": row.get("quantity"),
                               "packing_uom": row.get("unit"), "packing_unit_price": row.get("unit_price"),
                               "packing_total_amount": row.get("total_amount"),
                               "currency_evidence": deepcopy(row.get("currency_evidence")),
                               "field_evidence": deepcopy(row.get("field_evidence") or {}),
                               "raw_fields": deepcopy(row.get("raw_fields") or {})}}


def _confirmed_manual(value):
    if not isinstance(value, dict) or ("confirmed" in value and not _truthy(value.get("confirmed"))):
        return False
    return any(_truthy(value.get(field)) for field in ("manual", "manual_override", "manual_override_flag"))


def _truthy(value):
    return _text(value).lower() not in {"", "0", "false", "no", "none"}


def _missing_cache(row, fields):
    for field in fields:
        cell = (row.get("field_evidence") or {}).get(field) or {}
        if cell.get("formula") and (cell.get("cache_status") == "missing" or cell.get("raw_value") in (None, "")):
            return True
    return False


def _currency(value):
    text = _text(value).upper()
    return "RMB" if text in {"RMB", "CNY", "人民币", "人民币RMB"} else text


def _metadata(value):
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def _number(value: Any):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).replace(",", "").strip())
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _decimal(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _text(value):
    return str(value if value is not None else "").strip()
