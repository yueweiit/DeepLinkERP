"""费用持续待办状态和成本结果哈希。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from overseas_costing.services import fee_allocation_service


TODO_DEFINITIONS = {
    "AMOUNT_REQUIRED": ("error", "enter_amount", "补充费用金额"),
    "ACTUAL_AMOUNT_REQUIRED": ("warning", "enter_actual", "补充实际费用"),
    "ALLOCATION_REQUIRED": ("error", "fix_allocation", "完成费用分摊"),
    "EVIDENCE_REQUIRED": ("warning", "link_evidence", "关联最终凭证"),
    "EVIDENCE_VALIDATION_REQUIRED": ("warning", "validate_evidence", "校验最终凭证"),
    "ACTUAL_CONFIRMATION_INVALID": ("warning", "review_completion", "重新确认费用已齐"),
    "RECALCULATE_REQUIRED": ("error", "recalculate", "重新计算费用"),
}


def _decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_text(value) -> str:
    number = _decimal(value)
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
    calculation: dict | None,
    completion: dict | None = None,
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
    if not required_role:
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
        todos.append(_todo("ALLOCATION_REQUIRED"))
    if evidence_state in {"MISSING", "INVALID"}:
        todos.append(_todo("EVIDENCE_REQUIRED"))
    elif evidence_state == "PENDING":
        todos.append(_todo("EVIDENCE_VALIDATION_REQUIRED"))
    if evidence_state == "INVALID" or str((completion or {}).get("status") or "").upper() == "INVALIDATED":
        todos.append(_todo("ACTUAL_CONFIRMATION_INVALID"))

    current_input_hash = str((calculation or {}).get("input_hash") or "")
    calculated_input_hash = str((calculation or {}).get("fee_input_hash") or "")
    if current_input_hash and calculated_input_hash and current_input_hash != calculated_input_hash:
        todos.append(_todo("RECALCULATE_REQUIRED"))

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
        if "ALLOCATION_REQUIRED" in codes and status.get("amount_state") in {"ESTIMATED", "ACTUAL"}:
            unallocated[currency] = unallocated.get(currency, Decimal("0")) + amount
        if status.get("amount_state") == "ESTIMATED":
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
        "unallocated_by_currency": {
            currency: _decimal_text(amount) for currency, amount in sorted(unallocated.items())
        },
        "estimated_by_currency": {
            currency: _decimal_text(amount) for currency, amount in sorted(estimated.items())
        },
        "is_complete": not any(status.get("todos") for status in statuses or []),
    }


def build_erp_work_state(*, current_hash: str, sites: list[dict]) -> dict[str, dict]:
    """Build independent ERP work items without reading or changing fee completion."""

    work = {}
    for source in sites or []:
        site = dict(source)
        site_code = str(site.get("site_code") or "")
        status = str(site.get("status") or "").upper()
        last_hash = str(site.get("last_cost_result_hash") or site.get("last_hash") or "")
        request_hash = str(site.get("request_cost_result_hash") or "")
        if site.get("business_change_required") or status == "BUSINESS_CHANGE_REQUIRED":
            state = "BUSINESS_CHANGE_REQUIRED"
            todo = {
                "code": "ERP_BUSINESS_CHANGE_REQUIRED",
                "action": "resolve_business_change",
                "label": "物料、数量或站点已变更，需按业务变更处理",
            }
        elif status == "MANUAL_REQUIRED":
            state = "MANUAL_REQUIRED"
            todo = {"code": "ERP_MANUAL_REQUIRED", "action": "view_manual_steps", "label": "需人工完成 ERP 成本更新"}
        elif status == "UNCERTAIN" and request_hash == str(current_hash or ""):
            state = "UNCERTAIN"
            todo = {"code": "ERP_VERIFY_REQUIRED", "action": "verify_remote", "label": "ERP 结果不确定，需先回读核对"}
        elif status == "FAILED" and (not request_hash or request_hash == str(current_hash or "")):
            state = "FAILED"
            todo = {"code": "ERP_RETRY_REQUIRED", "action": "retry", "label": "ERP 同步失败，可安全重试"}
        elif last_hash and last_hash == str(current_hash or "") and status == "SUCCESS":
            state = "SYNCED"
            todo = None
        elif last_hash:
            state = "UPDATE_REQUIRED"
            todo = {"code": "ERP_UPDATE_REQUIRED", "action": "preview_update", "label": "ERP 成本落后于当前结果"}
        else:
            state = "CREATE_REQUIRED"
            todo = {"code": "ERP_CREATE_REQUIRED", "action": "preview_create", "label": "尚未推送到该 ERP 站点"}
        work[site_code] = {
            **site,
            "site_code": site_code,
            "state": state,
            "cost_result_hash": str(current_hash or "") if state == "SYNCED" else "",
            "last_hash": last_hash,
            "todo": todo,
        }
    return work


def build_erp_work_summary(*, current_hash: str, sites: list[dict]) -> dict:
    rows = list(build_erp_work_state(current_hash=current_hash, sites=sites).values())
    synced = sum(row.get("state") == "SYNCED" for row in rows)
    if rows and synced == len(rows):
        overall = "SYNCED"
    elif synced:
        overall = "PARTIAL"
    elif any(row.get("state") == "BUSINESS_CHANGE_REQUIRED" for row in rows):
        overall = "BLOCKED"
    elif any(row.get("state") in {"FAILED", "UNCERTAIN", "MANUAL_REQUIRED"} for row in rows):
        overall = "FAILED"
    else:
        overall = "PENDING"
    return {
        "overall": overall,
        "current_hash": str(current_hash or ""),
        "sites": rows,
        "todo_count": sum(bool(row.get("todo")) for row in rows),
    }


def build_cost_result_hash(
    items: list[dict],
    fee_statuses: list[dict],
    fx_context: dict | None = None,
) -> str:
    material_rows = [
        {
            "stable_line_key": row.get("stable_line_key") or row.get("name") or row.get("row_no"),
            "goods_value": row.get("goods_value") or "",
            "total_cost_rmb": row.get("total_cost_rmb") or "",
            "total_unit_rmb": row.get("total_unit_rmb") or "",
            "cost_output_uom": row.get("cost_output_uom") or "",
            "quantity_revision": row.get("actual_shipped_qty_source_revision") or "",
        }
        for row in items or []
    ]
    adopted_fees = [
        {
            "fee_key": status.get("fee_key") or "",
            "amount_state": status.get("amount_state") or "",
            "allocation_state": status.get("allocation_state") or "",
            "input_hash": status.get("input_hash") or "",
        }
        for status in fee_statuses or []
        if status.get("amount_state") in {"ESTIMATED", "ACTUAL"}
    ]
    return _hash({"items": material_rows, "fees": adopted_fees, "fx": fx_context or {}})
