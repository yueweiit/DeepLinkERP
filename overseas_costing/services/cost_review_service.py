"""Pure review readiness for trusted current inputs and saved cost snapshots.

Review permits estimates and missing evidence. Final confirmation and ERP keep
their existing, stricter guards. This module never reads or writes a database.
"""

from __future__ import annotations

import json
from decimal import Decimal

from overseas_costing.services import cost_preview_service, fee_service, fee_status_service
from overseas_costing.services.material_input_service import present_material_row
from overseas_costing.services.transport_fee_service import fee_is_active


ISSUE_ORDER = ("purchase", "logistics", "calculation", "erp_failed")
PURCHASE_CODES = {"MATERIAL_ITEMS_REQUIRED", "GOODS_VALUE_MISSING", "PURCHASE_SOURCE_INVALID",
                  "SUBSIDIARY_REQUIRED", "MATERIAL_CODE_REQUIRED", "PURCHASE_QUANTITY_REQUIRED"}
ALLOCATION_CODES = {"SHIPPING_UNIT_REQUIRED", "ALLOCATION_BASIS_INCOMPLETE", "ALLOCATION_DENOMINATOR_ZERO",
                    "FEE_SCOPE_EMPTY", "FEE_SCOPE_INVALID", "DIRECT_ITEM_SCOPE_INVALID",
                    "STABLE_ITEM_KEY_REQUIRED", "STABLE_ITEM_KEY_DUPLICATED"}
FEE_CODES = {"AMOUNT_MISSING", "AMOUNT_STATUS_INVALID", "FEE_AMOUNT_INVALID", "DUPLICATE_LOGICAL_FEE",
             "FX_RATE_MISSING", "CURRENCY_UNSUPPORTED"}
MESSAGES = {
    "PURCHASE_SOURCE_INVALID": "采购来源已失效或无法读取，请先核对采购资料。",
    "SUBSIDIARY_REQUIRED": "请补充所属子公司。",
    "MATERIAL_CODE_REQUIRED": "物料编码缺失，请补充采购资料。",
    "PURCHASE_QUANTITY_REQUIRED": "采购数量缺失，请补充采购资料。",
    "TRANSPORT_MODE_REQUIRED": "请先确认批次运输方式。",
    "RESULT_NOT_SAVED": "尚未保存综合成本试算，请先重新计算。",
    "RESULT_LEGACY": "历史结果缺少可验证的计算快照，请重新计算。",
    "RESULT_STALE": "计算输入或版本已变化，请重新计算。",
    "SAVED_RESULT_INVALID": "保存结果的物料、费用分摊或汇总不一致，请重新计算。",
    "AMOUNT_MISSING": "存在未填金额的费用，请补充费用。",
    "AMOUNT_STATUS_INVALID": "费用金额状态无效，请核对费用。",
    "FEE_AMOUNT_INVALID": "费用金额无效，请核对费用。",
    "DUPLICATE_LOGICAL_FEE": "存在重复费用，请核对并处理重复记录。",
    "FX_RATE_MISSING": "费用换算所需汇率缺失，请补充汇率。",
    "CURRENCY_UNSUPPORTED": "费用币种暂不支持，请核对费用。",
    "ESTIMATED_AMOUNT": "含暂估费用，可先审核，最终确认前仍需补充实际金额。",
    "EVIDENCE_MISSING": "费用凭证缺失或尚未通过校验，可先审核。",
}


def _dict(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _same_amount(left, right) -> bool:
    left_value = cost_preview_service._decimal(left)
    right_value = cost_preview_service._decimal(right)
    return left_value is not None and right_value is not None and left_value == right_value


def _source_invalid(source: dict, items: list[dict]) -> bool:
    from overseas_costing.services.batch_service import is_invalid_approval_status

    if source.get("invalid_business") or str(source.get("purchase_approval_sync_state") or "").lower() in {"invalid", "excluded", "unreadable", "error"}:
        return True
    approvals = [row for row in source.get("linked_purchase_approvals") or [] if isinstance(row, dict)]
    invalid_ids = {str(row.get("source_instance_id") or "") for row in approvals
                   if is_invalid_approval_status(row.get("approval_status"))
                   or is_invalid_approval_status(row.get("message"))}
    invalid_ids.discard("")
    valid_ids = {str(row.get("source_instance_id") or "") for row in approvals
                 if row.get("approval_status") and not is_invalid_approval_status(row.get("approval_status"))
                 and not is_invalid_approval_status(row.get("message"))}
    valid_ids.discard("")
    for row in items:
        instance_id = str(row.get("dingtalk_instance_id") or "")
        if instance_id in invalid_ids:
            return True
        if (source.get("purchase_approval_sync_state") == "partial"
                and str(row.get("source_type") or "").upper() == "PURCHASE_EXPENSE_OA"
                and instance_id not in valid_ids):
            return True
    return False


def _saved_result_matches(snapshot: dict, expected: dict, items: list[dict]) -> bool:
    """Recompute only in memory to verify saved coverage, allocations and totals."""
    saved = _dict(snapshot.get("comprehensive_cost"))
    for field in ("items", "included_fees", "excluded_fees", "ignored_fees", "incomplete_reasons"):
        # These are the canonical structures emitted by the same pure calculator.
        # Comparing every allocation also rejects duplicate and omitted item rows.
        if saved.get(field) != expected.get(field):
            return False
    if saved.get("summary") != expected.get("summary"):
        return False
    for field in ("purchase_goods_value_rmb", "direct_fees_rmb", "allocated_fees_rmb", "total_cost_rmb"):
        if not _same_amount(snapshot.get(field), expected["summary"].get(field)):
            return False
    if snapshot.get("item_count") != len(items):
        return False
    expected_by_name = {row["name"]: row for row in expected["items"]}
    if len(expected_by_name) != len(items):
        return False
    for item in items:
        output = expected_by_name.get(item.get("name")) or {}
        if not _same_amount(item.get("total_cost_rmb"), output.get("total_cost_rmb")):
            return False
        if _dict(item.get("derived_json")).get("calculation_schema") != 2:
            return False
    return True


def evaluate_review_readiness(*, batch: dict, version: dict, items: list[dict], fees: list[dict],
                              evidence: list[dict] | None = None) -> dict:
    """Evaluate one authorized batch; fee rows must use the saved query's order.

    Project exactly the fields used by FrappeCostRepository, including nulls.
    Output-only item fields and bulk-query grouping fields must not enter the hash.
    Fee composition and the second historical decoration match build_saved_cost_data.
    """
    blockers: dict[str, dict] = {}
    warnings: dict[str, dict] = {}

    def block(code, message=""):
        issue = "purchase" if code in PURCHASE_CODES else "logistics" if code in ALLOCATION_CODES | FEE_CODES else "calculation"
        blockers.setdefault(code, {"code": code, "message": MESSAGES.get(code) or message or "费用分摊资料不完整，请核对适用物料和分摊依据。", "issue": issue})

    def warn(code):
        warnings.setdefault(code, {"code": code, "message": MESSAGES[code]})

    mode = fee_service.resolve_transport_mode(batch.get("transport_mode"))
    inputs = [{field: row.get(field) for field in cost_preview_service.COST_INPUT_FIELDS} for row in items]
    inputs.sort(key=lambda row: (cost_preview_service._decimal(row.get("row_no")) or Decimal(0), str(row.get("name") or "")))
    raw_fees = [{field: row.get(field) for field in fee_service._rule_fields()} for row in fees]
    composed = fee_service.compose_fee_worklist_rows(raw_fees, mode)
    canonical_fees = fee_service._decorate_historical_rules(composed, mode)
    fx = {key: version.get(key) for key in ("fx_usd_to_rmb", "fx_rmb_to_mxn")}
    current_hash = cost_preview_service.cost_input_hash(inputs, canonical_fees, fx, mode)
    expected = cost_preview_service.preview_comprehensive_cost_data(inputs, canonical_fees, fx)

    if not batch.get("subsidiary_code"):
        block("SUBSIDIARY_REQUIRED")
    if not mode:
        block("TRANSPORT_MODE_REQUIRED")
    if _source_invalid(_dict(batch.get("source_status")), inputs):
        block("PURCHASE_SOURCE_INVALID")
    for row in inputs:
        if not str(row.get("material_code") or "").strip():
            block("MATERIAL_CODE_REQUIRED")
        quantity = cost_preview_service._decimal(row.get("quantity"))
        if quantity is None or quantity <= 0:
            block("PURCHASE_QUANTITY_REQUIRED")
    keys = [present_material_row(row)["stable_line_key"] for row in inputs]
    if len(set(keys)) != len(keys):
        block("STABLE_ITEM_KEY_DUPLICATED")
    for reason in expected["incomplete_reasons"]:
        code = reason["reason_code"]
        if code == "ESTIMATED_AMOUNT":
            warn(code)
        else:
            block(code, reason.get("message"))

    evidence_by_rule: dict[str, list[dict]] = {}
    for row in evidence or []:
        evidence_by_rule.setdefault(str(row.get("fee_rule") or ""), []).append(row)
    for fee in canonical_fees:
        if not fee_is_active(fee):
            continue
        status = fee_status_service.build_fee_status(fee=fee, allocation=None,
            evidence=evidence_by_rule.get(str(fee.get("name") or ""), []))
        if status["amount_state"] == "ESTIMATED":
            warn("ESTIMATED_AMOUNT")
        if status["evidence_state"] in {"MISSING", "INVALID", "PENDING"}:
            warn("EVIDENCE_MISSING")

    snapshot = _dict(version.get("summary_snapshot_json"))
    result_current = True
    if not snapshot:
        block("RESULT_NOT_SAVED")
        result_current = False
    elif snapshot.get("calculation_schema") != 2 or not snapshot.get("input_hash") or not isinstance(snapshot.get("comprehensive_cost"), dict):
        block("RESULT_LEGACY")
        result_current = False
    elif snapshot.get("input_hash") == current_hash and not _saved_result_matches(snapshot, expected, items):
        block("SAVED_RESULT_INVALID")
        result_current = False
    if (not version.get("name") or version.get("name") != batch.get("current_version")
            or version.get("batch") != batch.get("name")
            or not version.get("calculated_at")
            or str(snapshot.get("calculated_at") or "") != str(version.get("calculated_at") or "")
            or snapshot.get("input_hash") != current_hash
            or str(batch.get("status") or "").lower() in {"draft", "dirty"}):
        block("RESULT_STALE")
        result_current = False

    confirmed = str(batch.get("confirm_status") or "").lower() == "confirmed"
    state = "confirmed" if confirmed else "processing" if blockers else "ready"
    issues = {row["issue"] for row in blockers.values()}
    if "fail" in str(batch.get("writeback_status") or "").lower():
        issues.add("erp_failed")
    primary = next((code for code in ISSUE_ORDER if code in issues), "ready")
    if state == "confirmed":
        action = "view"
    elif state == "ready":
        action = "review"
    elif primary == "purchase":
        action = "supplement"
    elif any(code in FEE_CODES for code in blockers):
        action = "supplement_fees"
    elif any(code in ALLOCATION_CODES for code in blockers):
        action = "supplement_allocation"
    else:
        action = "recalculate"
    return {"review_state": state, "review_blockers": list(blockers.values()),
            "review_warnings": list(warnings.values()), "result_is_current": result_current,
            "issue_codes": [code for code in ISSUE_ORDER if code in issues], "primary_issue": primary,
            "primary_action": action, "reviewed_at": version.get("reviewed_at") or version.get("confirmed_at") if confirmed else None,
            "reviewed_version": version.get("name") if confirmed else None,
            "reviewed_version_code": version.get("version_code") if confirmed else None}
