"""费用页的派生待办状态；不落库生成费用完结状态。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from overseas_costing.services import fee_allocation_service


TODO_DEFINITIONS = {
    "AMOUNT_REQUIRED": ("error", "enter_amount", "补充费用金额"),
    "ACTUAL_AMOUNT_REQUIRED": ("warning", "enter_actual", "补充实际费用"),
    "ALLOCATION_REQUIRED": ("error", "fix_allocation", "完成费用分摊"),
    "FX_RATE_MISSING": ("error", "enter_fx_rate", "补充批次汇率后试算"),
    "CURRENCY_UNSUPPORTED": ("error", "enter_currency", "请选择人民币、比索或美金"),
    "FEE_AMOUNT_INVALID": ("error", "enter_amount", "请修正费用金额"),
    "EVIDENCE_REQUIRED": ("warning", "link_evidence", "关联最终凭证"),
    "EVIDENCE_VALIDATION_REQUIRED": ("warning", "validate_evidence", "校验最终凭证"),
}


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value) -> str:
    number = _decimal(value)
    if number is None:
        return ""
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _normalize(value):
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple, set)):
        normalized = [_normalize(row) for row in value]
        return sorted(normalized, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return _decimal_text(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return format(Decimal(stripped).normalize(), "f") if stripped else ""
        except (InvalidOperation, ValueError):
            return stripped
    return str(value)


def _hash(payload: dict) -> str:
    canonical = json.dumps(
        _normalize(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_fee_input_hash(
    fee: dict,
    *,
    items: list[dict] | None = None,
    fx_context: dict | None = None,
) -> str:
    scope_keys = fee_allocation_service._scope_keys(fee)
    item_revisions = [
        {
            "stable_line_key": row.get("stable_line_key") or row.get("name") or row.get("row_no"),
            "quantity_revision": row.get("actual_shipped_qty_source_revision") or "",
            "effective_quantity": row.get("actual_shipped_qty") or row.get("quantity") or "",
            "goods_value": row.get("goods_value") or "",
            "gross_weight_kg": row.get("gross_weight_kg") or "",
            "volume_m3": row.get("volume_m3") or "",
            "chargeable_weight_kg": row.get("chargeable_weight_kg") or "",
        }
        for row in (items or [])
    ]
    return _hash(
        {
            "fee_key": fee.get("logical_fee_key") or fee.get("rule_code") or fee.get("fee_key") or "",
            "amount": fee.get("amount") or "",
            "currency": str(fee.get("currency") or "").upper(),
            "amount_status": fee_allocation_service.amount_status(fee),
            "amount_revision": fee.get("amount_revision") or "",
            "allocation_basis": fee.get("allocation_basis") or fee.get("basis_field") or "goods_value",
            "scope_type": fee.get("scope_type") or "ALL_ITEMS",
            "scope_item_keys": scope_keys,
            "scope_revision": fee.get("scope_revision") or "",
            "included_in_fee_key": fee.get("included_in_fee_key") or "",
            "fx": fx_context or {},
            "items": item_revisions,
        }
    )


def _todo(code: str) -> dict:
    severity, action, label = TODO_DEFINITIONS[code]
    return {"code": code, "severity": severity, "action": action, "label": label}


def build_fee_status(
    *,
    fee: dict,
    allocation: dict | None,
    evidence: list[dict] | None,
    calculation: dict | None = None,
) -> dict:
    amount_state = fee_allocation_service.amount_status(fee)
    allocation_state = str((allocation or {}).get("status") or "NOT_ALLOCATED")
    required_role = str(fee.get("required_evidence_role") or "").strip()
    matching_evidence = [
        row
        for row in (evidence or [])
        if not required_role or str(row.get("evidence_role") or "") == required_role
    ]
    validation_states = {str(row.get("validation_status") or "PENDING").upper() for row in matching_evidence}
    if amount_state in {"NOT_INCURRED", "INCLUDED"}:
        evidence_state = "NOT_REQUIRED"
    elif not required_role:
        evidence_state = "NOT_REQUIRED"
    elif "VALID" in validation_states:
        evidence_state = "VALID"
    elif "INVALID" in validation_states:
        evidence_state = "INVALID"
    elif validation_states.intersection({"PENDING"}):
        evidence_state = "PENDING"
    else:
        evidence_state = "MISSING"

    todos = []
    if amount_state == "MISSING":
        todos.append(_todo("AMOUNT_REQUIRED"))
    elif amount_state == "ESTIMATED":
        todos.append(_todo("ACTUAL_AMOUNT_REQUIRED"))
    if amount_state in fee_allocation_service.COUNTED_AMOUNT_STATUSES and allocation_state != "ALLOCATED":
        code = (allocation or {}).get("code")
        todos.append(_todo(code if code in {"FX_RATE_MISSING", "CURRENCY_UNSUPPORTED", "FEE_AMOUNT_INVALID"} else "ALLOCATION_REQUIRED"))
    if evidence_state in {"MISSING", "INVALID"}:
        todos.append(_todo("EVIDENCE_REQUIRED"))
    elif evidence_state == "PENDING":
        todos.append(_todo("EVIDENCE_VALIDATION_REQUIRED"))
    current_input_hash = str((calculation or {}).get("input_hash") or "")

    return {
        "fee_key": fee.get("logical_fee_key") or fee.get("rule_code") or fee.get("fee_key") or "",
        "expense_category": fee.get("expense_category") or "",
        "amount_state": amount_state,
        "allocation_state": allocation_state,
        "evidence_state": evidence_state,
        "currency": str(fee.get("currency") or "").upper(),
        "amount": "" if fee.get("amount") in (None, "") else _decimal_text(fee.get("amount")),
        "required_evidence_role": required_role,
        "input_hash": current_input_hash,
        "todos": todos,
    }


def summarize_fee_statuses(statuses: list[dict]) -> dict:
    unallocated: dict[str, Decimal] = {}
    estimated: dict[str, Decimal] = {}
    todo_count = 0
    for status in statuses or []:
        codes = {str(todo.get("code") or "") for todo in status.get("todos") or []}
        currency = str(status.get("currency") or "").upper() or "UNKNOWN"
        amount = _decimal(status.get("amount"))
        if amount is not None and codes.intersection({"ALLOCATION_REQUIRED", "FX_RATE_MISSING", "CURRENCY_UNSUPPORTED"}) and status.get("amount_state") in {"ESTIMATED", "ACTUAL"}:
            unallocated[currency] = unallocated.get(currency, Decimal("0")) + amount
        if amount is not None and status.get("amount_state") == "ESTIMATED":
            estimated[currency] = estimated.get(currency, Decimal("0")) + amount
        todo_count += len(status.get("todos") or [])

    return {
        "fee_count": len(statuses or []),
        "affected_fee_count": sum(1 for status in statuses or [] if status.get("todos")),
        "todo_count": todo_count,
        "missing_amount_fee_count": sum(
            1 for status in statuses or [] if status.get("amount_state") == "MISSING"
        ),
        "estimated_fee_count": sum(
            1 for status in statuses or [] if status.get("amount_state") == "ESTIMATED"
        ),
        "unallocated_fee_count": sum(
            1
            for status in statuses or []
            if any(
                str(todo.get("code") or "") in {"ALLOCATION_REQUIRED", "FX_RATE_MISSING", "CURRENCY_UNSUPPORTED", "FEE_AMOUNT_INVALID"}
                for todo in status.get("todos") or []
            )
        ),
        "missing_evidence_fee_count": sum(
            1 for status in statuses or [] if status.get("evidence_state") in {"MISSING", "INVALID"}
        ),
        "pending_evidence_fee_count": sum(
            1 for status in statuses or [] if status.get("evidence_state") == "PENDING"
        ),
        "unallocated_by_currency": {
            currency: _decimal_text(amount) for currency, amount in sorted(unallocated.items())
        },
        "estimated_by_currency": {
            currency: _decimal_text(amount) for currency, amount in sorted(estimated.items())
        },
        "all_requirements_satisfied": not any(status.get("todos") for status in statuses or []),
    }
