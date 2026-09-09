"""Server-owned shipment rows and compact, read-only autofill previews."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import signal
import threading
import time


class SupplementBudgetExceeded(BaseException):
    """Escape model clients' broad Exception fallbacks without leaving a worker."""


def run_supplement(callback, *, seconds: float = 60) -> dict:
    failure = {"ok": False, "proposals": [], "warning": "补充识别超时，已保留系统直读结果。"}
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        return {**failure, "warning": "当前执行环境无法限制补充识别时间，已保留系统直读结果。"}
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    # Never replace an enclosing worker timeout with a later timeout.
    if old_timer[0] and old_timer[0] <= seconds:
        return {**failure, "warning": "任务剩余时间不足，已保留系统直读结果。"}
    started = time.monotonic()
    def deadline(signum, frame):
        raise SupplementBudgetExceeded()
    try:
        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        return callback()
    except SupplementBudgetExceeded:
        return failure
    except Exception as exc:
        return {**failure, "warning": f"补充识别未完成，已保留系统直读结果：{exc}"}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, old_timer[0] - (time.monotonic() - started)), old_timer[1])

from overseas_costing.services.source_review_extract_service import _approval_goods_rows
from overseas_costing.utils.field_mapper import map_oa_row_to_item

PURCHASE_FIELDS = ("quantity", "goods_value", "unit_price", "purchase_currency", "purchase_uom",
                   "unit_price_uom", "source_doc_no", "source_type")
PHYSICAL_FIELDS = ("net_weight_kg", "gross_weight_kg", "volume_m3", "chargeable_weight_kg")


def extra(item: dict) -> dict:
    try:
        result = json.loads(item.get("extra_json") or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def apportioned(total, quantities: list[Decimal]) -> list[str | None]:
    if total is None:
        return [None] * len(quantities)
    total = Decimal(str(total))
    denominator = sum(quantities)
    result = [(total * qty / denominator).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
              for qty in quantities[:-1]]
    result.append(total - sum(result))
    return [format(value, "f") for value in result]


def _purchase_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _reconcile_purchase_allocations(rows: list[dict], items: list[dict], facts: dict, used: set) -> None:
    """Keep current group totals and protect independently corrected row fields."""
    fields = ("quantity", "goods_value")
    current = {row["name"]: row for row in items}
    metadata = {row["name"]: extra(row).get("logistics_row", {}) for row in items}
    for purchase_key, fact in facts.items():
        group = [row for row in rows if extra(row).get("logistics_row", {}).get("purchase_key") == purchase_key]
        previous = [row for row in items if (metadata[row["name"]].get("purchase_key") or row["name"]) == purchase_key]
        previously_allocated = any(metadata[row["name"]].get("identity") for row in previous)
        manual_fields = {}
        legacy_expected = {}
        if previously_allocated:
            quantities = [(_purchase_decimal(row.get("actual_shipped_qty")) or Decimal("0")) for row in previous]
            for field in fields:
                if _purchase_decimal(fact.get(field)) is not None and sum(quantities) > 0:
                    legacy_expected[field] = dict(zip(
                        [row["name"] for row in previous], apportioned(fact[field], quantities)))
            for old in previous:
                prior = metadata[old["name"]]
                protected = set(prior.get("manual_purchase_fields") or []) & set(fields)
                snapshot = prior.get("allocated_purchase") or {}
                for field in fields:
                    # Older runs have no allocation snapshot. Compare them with
                    # their previous shipment shares, never with the new shares.
                    expected = snapshot.get(field) if field in snapshot else legacy_expected.get(field, {}).get(old["name"])
                    if (field in snapshot or old["name"] in legacy_expected.get(field, {})) and _purchase_decimal(old.get(field)) != _purchase_decimal(expected):
                        protected.add(field)
                manual_fields[old["name"]] = protected
        for field in fields:
            if previously_allocated:
                stored = [_purchase_decimal(row.get(field)) for row in previous]
                known = [value for value in stored if value is not None]
                total = sum(known) if known else None
            else:
                total = _purchase_decimal(fact.get(field))
            protected_rows = [row for row in group if row.get("_existing_name") in current and (
                field in manual_fields.get(row["_existing_name"], set()) or row["_existing_name"] not in used)]
            protected_names = {row["name"] for row in protected_rows}
            for row in protected_rows:
                row[field] = current[row["_existing_name"]].get(field)
            distributable = [row for row in group if row["name"] not in protected_names]
            quantities = [(_purchase_decimal(row.get("actual_shipped_qty")) or Decimal("0")) for row in distributable]
            if not distributable or sum(quantities) <= 0:
                continue
            remaining = None if total is None else total - sum(
                (_purchase_decimal(row.get(field)) or Decimal("0")) for row in protected_rows)
            for row, value in zip(distributable, apportioned(remaining, quantities)):
                row[field] = value
        for row in group:
            row_metadata = extra(row)
            prior = row_metadata["logistics_row"]
            prior["allocated_purchase"] = {field: row.get(field) for field in fields}
            prior["manual_purchase_fields"] = sorted(manual_fields.get(row.get("_existing_name"), set()))
            row["extra_json"] = json.dumps(row_metadata, ensure_ascii=False, default=str)


def build_logistics_reconciliation(items: list[dict], source: dict) -> dict | None:
    """Build a row-preserving draft; never mutate inputs, DB or purchase facts."""
    if source.get("approval_role") != "international_logistics":
        return None
    goods = [map_oa_row_to_item(row) for row in _approval_goods_rows(source)]
    if not goods or any(not row.get("material_code") or Decimal(str(row.get("quantity") or 0)) <= 0 for row in goods):
        return None
    for item in items:
        if not extra(item).get("logistics_row", {}).get("identity") and item.get("actual_shipped_qty_mode") == "MANUAL_CONFIRMED" and sum(str(g.get("material_code") or "").casefold() == str(item.get("material_code") or "").casefold() for g in goods) > 1:
            message = f"{item.get('material_code')} 的现有人工实发数量属于聚合行，无法直接拆分；已保留现有物料，请先核对这项人工差异。"
            return {"proposal_id": "logistics-manual-conflict", "proposal_type": "logistics_reconcile", "result_origin": "SYSTEM", "default_selected": False,
                    "conflict": True, "blocked": True, "reason": message, "source_refs": [],
                    "payload": {"rows": deepcopy(items), "unresolved": [{"message": message}], "original_item_names": [row["name"] for row in items]}}
    by_code: dict[str, list[dict]] = {}
    for item in items:
        by_code.setdefault(str(item.get("material_code") or "").casefold(), []).append(item)
    rows, used, unresolved = [], set(), []
    facts: dict[str, dict] = {}
    for index, goods_row in enumerate(goods, 1):
        code = str(goods_row["material_code"])
        identity = f"{source['source_id']}:{index}:{code}"
        key = "logistics:" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        matches = by_code.get(code.casefold(), [])
        old = next((row for row in matches if row.get("stable_line_key") == key or extra(row).get("logistics_row", {}).get("identity") == key), None)
        if old is None:
            # Distinct purchases must not be silently resolved by SKU alone.
            purchase_keys = {extra(row).get("logistics_row", {}).get("purchase_key") or row.get("name") for row in matches}
            if len(purchase_keys) > 1:
                unresolved.append({"message": f"{code} 对应多个采购明细，保留物流行，采购关联待补。"})
                matches = []
            remaining = [row for row in matches if row.get("name") not in used]
            exact = [row for row in remaining if Decimal(str(row.get("actual_shipped_qty") or row.get("quantity") or 0)) == Decimal(str(goods_row["quantity"]))]
            old = (exact or remaining or matches or [{}])[0]
        metadata = extra(old)
        prior = metadata.get("logistics_row") or {}
        fact = prior.get("purchase_fact") or {field: old.get(field) for field in PURCHASE_FIELDS}
        purchase_key = prior.get("purchase_key") or old.get("name") or ""
        if purchase_key:
            facts[purchase_key] = fact
        existing_name = str(old.get("name") or "")
        retained_name = existing_name if existing_name and existing_name not in used else ""
        if retained_name:
            used.add(retained_name)
        row = {field: old.get(field) for field in (*PURCHASE_FIELDS, *PHYSICAL_FIELDS,
                "project_collection", "manual_override_flag", "manual_override_reason", "spec_model")}
        row.update({"name": retained_name or f"draft-{key[10:]}", "stable_line_key": (old.get("stable_line_key") if retained_name else None) or key,
                    "unit": old.get('unit') or goods_row.get('unit') or '',
                    "row_no": index, "material_code": code,
                    "product_name": goods_row.get("product_name") or old.get("product_name") or code,
                    "spec_model": goods_row.get("spec_model") or old.get("spec_model"),
                    "actual_shipped_qty": str(goods_row["quantity"]),
                    "actual_shipped_qty_mode": "EXPLICIT_SOURCE",
                    "shipped_uom": goods_row.get("unit") or "",
                    "source_doc_no": old.get("source_doc_no") or source.get("approval_no"),
                    "source_type": "OA_LOGISTICS_ROW",
                    "_existing_name": retained_name})
        if retained_name and str(old.get("actual_shipped_qty_mode") or "") == "MANUAL_CONFIRMED":
            row["actual_shipped_qty"] = old.get("actual_shipped_qty")
            row["actual_shipped_qty_mode"] = "MANUAL_CONFIRMED"
            row["shipped_uom"] = old.get("shipped_uom")
        metadata["logistics_row"] = {**prior, "identity": key, "source_id": source["source_id"], "approval_no": source.get("approval_no"),
                                      "row_no": index, "purchase_key": purchase_key, "purchase_fact": fact}
        row["extra_json"] = json.dumps(metadata, ensure_ascii=False, default=str)
        rows.append(row)
    # Never silently remove unrelated or manually added rows.
    unmatched = [row for row in items if str(row.get("name")) not in used]
    for original in unmatched:
        row = deepcopy(original)
        row["_existing_name"] = row["name"]
        row["stable_line_key"] = row.get("stable_line_key") or "retained:" + hashlib.sha256(row["name"].encode()).hexdigest()[:32]
        row["row_no"] = len(rows) + 1
        rows.append(row)
        unresolved.append({"message": f"保留审批之外的现有物料 {row.get('material_code') or row['name']}。"})
    _reconcile_purchase_allocations(rows, items, facts, used)
    for purchase_key in facts:
        group = [row for row in rows if extra(row).get("logistics_row", {}).get("purchase_key") == purchase_key]
        quantities = [Decimal(str(row.get("actual_shipped_qty") or 0)) for row in group]
        # Historical aggregate physical values belong to the group, not every split.
        original = next((row for row in items if row.get("name") == purchase_key), {})
        if len(group) > 1 and sum(quantities) > 0 and not extra(original).get("logistics_row"):
            for field in PHYSICAL_FIELDS:
                for row, value in zip(group, apportioned(original.get(field), quantities)):
                    row[field] = value
    return {"proposal_id": "logistics-reconcile:" + hashlib.sha256(source["source_id"].encode()).hexdigest()[:24],
            "proposal_type": "logistics_reconcile", "result_origin": "SYSTEM", "confidence": 1.0,
            "default_selected": True, "conflict": False, "reason": "按物流审批逐行填充，保留采购事实。",
            "source_refs": [{"source": "approval_form", "source_id": source["source_id"],
                             "file": source.get("source_label"), "approval_no": source.get("approval_no"), "field": "货物信息"}],
            "payload": {"rows": rows, "unresolved": unresolved, "original_item_names": [row["name"] for row in items]}}


def apply_reconciliation(frappe, proposal: dict, *, batch: str, version: str, current: list[dict], run_id: str) -> list[str]:
    """Called only inside the review transaction with locked, fingerprinted rows."""
    from overseas_costing.services.material_input_service import GRID_FIELDS
    payload = proposal["payload"]
    if proposal.get("blocked"):
        raise ValueError(proposal.get("reason") or "存在待核对的人工物流差异。")
    existing = {row["name"] for row in current}
    if set(payload.get("original_item_names") or []) != existing:
        raise ValueError("物流行已变化，请重新分析。")
    rows = payload.get("rows") or []
    retained = [row["_existing_name"] for row in rows if row.get("_existing_name")]
    if set(retained) != existing or len(retained) != len(existing):
        raise ValueError("物流行重整必须保留每条原记录，不能删除或重复采购事实。")
    keys = [row.get("stable_line_key") for row in rows]
    if not all(keys) or len(set(keys)) != len(keys):
        raise ValueError("物流行身份重复或缺失。")
    allowed = (set(GRID_FIELDS) | {"extra_json", "manual_override_flag", "manual_override_reason"}) - {"name", "modified"}
    created = []
    for row in rows:
        values = {key: value for key, value in row.items() if key in allowed}
        values.update(batch=batch, version=version, actual_shipped_qty_source_revision=run_id,
                      cost_output_uom=row.get("shipped_uom") or "")
        metadata = extra(row)
        metadata["autofill_review"] = {"run_id": run_id, "proposal_id": proposal["proposal_id"], "source_refs": proposal.get("source_refs") or []}
        values["extra_json"] = json.dumps(metadata, ensure_ascii=False, default=str)
        if row.get("_existing_name"):
            frappe.db.set_value("Overseas Cost Item", row["_existing_name"], values, update_modified=True)
        else:
            created.append(frappe.get_doc({"doctype": "Overseas Cost Item", **values}).insert(ignore_permissions=True).name)
    frappe.db.set_value("Overseas Cost Batch", batch, "item_count", len(rows), update_modified=False)
    return created


def selected_carrier(candidates: list[dict], decisions: list[dict]) -> str:
    """Use the latest affirmative approval decision, never a price heuristic."""
    for decision in sorted(decisions, key=lambda row: str(row.get("operation_time") or row.get("create_time") or ""), reverse=True):
        result = str(decision.get("operation_result") or decision.get("result") or "").upper()
        if result not in {"AGREE", "APPROVED", "同意"}:
            continue
        remark = str(decision.get("remark") or "")
        # A later cancellation/negative decision invalidates any older choice.
        cancelled_choice = re.search(r"取消|撤销|作废|废止", remark) and re.search(r"物流|承运|运输|报价|询价|选择|方案", remark)
        renewed_quotes = re.search(r"(?:重新|再次)(?:询价|报价|比价)", remark)
        if cancelled_choice or renewed_quotes:
            return ""
        if any(str(row.get("carrier") or "") in remark for row in candidates) and re.search(r"不|取消|撤销|待定|暂缓|再议|[?？]", remark):
            return ""
        matches = {str(row.get("carrier") or "") for row in candidates
                   if row.get("carrier") and re.search(r"(?:走|选择|选用|采用|确定|同意使用)\s*" + re.escape(str(row["carrier"])), remark, re.I)}
        if len(matches) == 1:
            return next(iter(matches))
    return ""


def autofill_preview(items: list[dict], proposals: list[dict], existing_fees: list[dict], *, fx_rates=None) -> dict:
    reconciliation = next((p for p in proposals if p["proposal_type"] == "logistics_reconcile"), None)
    rows = deepcopy(reconciliation["payload"]["rows"] if reconciliation and not reconciliation.get("blocked") else items)
    by_name = {row["name"]: row for row in rows}
    fees, changes, unresolved = [], [], list((reconciliation or {}).get("payload", {}).get("unresolved", []))
    for proposal in proposals:
        payload = proposal.get("payload") or {}
        if not proposal.get("default_selected"):
            if proposal.get("conflict"):
                unresolved.append({"proposal_id": proposal["proposal_id"], "message": proposal.get("reason") or "存在待核对差异"})
            continue
        if proposal["proposal_type"] == "item_update" and payload.get("item_name") in by_name:
            row = by_name[payload["item_name"]]
            for field, value in payload["fields"].items():
                changes.append({"item_name": row["name"], "fieldname": field, "previous_value": row.get(field), "value": value})
                row[field] = value
        elif proposal["proposal_type"] == "fee_update":
            old = next((fee for fee in existing_fees if fee.get("logical_fee_key") == payload.get("logical_fee_key")), {})
            fees.append({**payload, "proposal_id": proposal["proposal_id"], "fee_type": payload.get("expense_category"),
                         "previous_amount": old.get("amount"), "carrier": proposal.get("carrier", "")})
    from overseas_costing.services.material_input_service import present_material_row
    from overseas_costing.services.cost_preview_service import preview_comprehensive_cost_data
    if not reconciliation or not reconciliation.get('blocked'):
        rows = [present_material_row(row) for row in rows]
    from overseas_costing.services.fee_service import merge_logical_fee
    effective_fees = deepcopy(existing_fees)
    for fee in fees:
        try:
            effective_fees = merge_logical_fee(effective_fees, fee)['fees']
        except ValueError as exc:
            unresolved.append({'message':str(exc)})
    rates = fx_rates or {}
    mxn_to_rmb = _purchase_decimal(rates.get('MXN'))
    cost = preview_comprehensive_cost_data(rows, effective_fees, {
        'fx_usd_to_rmb':rates.get('USD'),
        'fx_rmb_to_mxn':str(Decimal('1') / mxn_to_rmb) if mxn_to_rmb and mxn_to_rmb > 0 else None})
    unresolved.extend(reason for reason in cost['incomplete_reasons']
        if str(reason.get('reason_code') or '').startswith(('PROJECT_', 'SHIPMENT_VALUATION_', 'FX_', 'DUPLICATE_LOGICAL_FEE')))
    return {"items": rows, "fees": fees, "changes": changes, "unresolved": unresolved,
            "project_summary": cost['project_summary'], "cost_summary": cost['summary']}
