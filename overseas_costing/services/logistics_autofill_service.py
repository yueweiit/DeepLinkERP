"""Server-owned shipment rows and compact, read-only autofill previews."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
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
AUTO_SCOPE_EXCLUSION_REASON = "系统按国际物流物料范围自动排除"


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


def _manual_scope_protected(item: dict) -> bool:
    """A human-confirmed row survives automatic logistics scope contraction."""

    if str(item.get("manual_override_flag") or "0").strip().casefold() not in {
        "", "0", "false", "no", "none",
    }:
        return True
    metadata = extra(item)
    return bool(
        metadata.get("manual_scope_include")
        or metadata.get("manual_scope_restored")
        or (metadata.get("shipment_material_scope") or {}).get("manual_include")
    )


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
    """Build an authoritative logistics-scope draft without mutating inputs."""
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
                    "row_no": index, "material_code": code, "_review_origin": "source",
                    "product_name": goods_row.get("product_name") or old.get("product_name") or code,
                    "spec_model": goods_row.get("spec_model") or old.get("spec_model"),
                    "actual_shipped_qty": str(goods_row["quantity"]),
                    "actual_shipped_qty_mode": "EXPLICIT_SOURCE",
                    "shipped_uom": goods_row.get("unit") or "",
                    "source_doc_no": old.get("source_doc_no") or source.get("approval_no"),
                    "source_type": "OA_LOGISTICS_ROW",
                    "_existing_name": retained_name,
                    "_existing_stable_line_key": (
                        old.get("_existing_stable_line_key")
                        if "_existing_stable_line_key" in old
                        else old.get("stable_line_key")
                    )})
        if retained_name and str(old.get("actual_shipped_qty_mode") or "") == "MANUAL_CONFIRMED":
            row["actual_shipped_qty"] = old.get("actual_shipped_qty")
            row["actual_shipped_qty_mode"] = "MANUAL_CONFIRMED"
            row["shipped_uom"] = old.get("shipped_uom")
        metadata["logistics_row"] = {**prior, "identity": key, "source_id": source["source_id"], "approval_no": source.get("approval_no"),
                                      "row_no": index, "purchase_key": purchase_key, "purchase_fact": fact}
        row["extra_json"] = json.dumps(metadata, ensure_ascii=False, default=str)
        if old.get("_purchase_fact_enriched"):
            row["_review_purchase_values"] = {
                field: fact.get(field)
                for field in ("unit_price", "purchase_currency", "purchase_uom", "unit_price_uom")
            }
            row["_review_price_metadata"] = deepcopy(metadata)
        row['_review_source_values'] = {key: row.get(key) for key in ('material_code','product_name','spec_model','actual_shipped_qty','shipped_uom','unit','stable_line_key')}
        # Physical fields copied/apportioned above are historical context, not evidence from this approval.
        rows.append(row)
    # International logistics defines this shipment.  Preserve only explicit
    # human inclusions; unrelated purchase rows remain recoverable by soft
    # exclusion when the reviewed projection is confirmed.
    unmatched = [row for row in items if str(row.get("name")) not in used]
    excluded_item_names = []
    for original in unmatched:
        if not _manual_scope_protected(original):
            excluded_item_names.append(str(original.get("name") or ""))
            continue
        row = deepcopy(original)
        row["_existing_name"] = row["name"]
        row["_existing_stable_line_key"] = (
            row.get("_existing_stable_line_key")
            if "_existing_stable_line_key" in row
            else row.get("stable_line_key")
        )
        row["_review_origin"] = "current"
        row["stable_line_key"] = row.get("stable_line_key") or "retained:" + hashlib.sha256(row["name"].encode()).hexdigest()[:32]
        row["row_no"] = len(rows) + 1
        rows.append(row)
        unresolved.append({"message": f"保留人工确认纳入的物料 {row.get('material_code') or row['name']}。"})
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
            "payload": {"rows": rows, "unresolved": unresolved,
                        "original_item_names": [row["name"] for row in items],
                        "excluded_item_names": sorted(name for name in excluded_item_names if name),
                        "scope_status": "AUTHORITATIVE"}}


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
    excluded = [str(name or "") for name in payload.get("excluded_item_names") or []]
    if (set(retained).intersection(excluded) or set(retained).union(excluded) != existing
            or len(retained) != len(set(retained)) or len(excluded) != len(set(excluded))):
        raise ValueError("物流物料范围已变化，请重新分析。")
    keys = [row.get("stable_line_key") for row in rows]
    if not all(keys) or len(set(keys)) != len(keys):
        raise ValueError("物流行身份重复或缺失。")
    settled = {row['name']:row for row in current if extra(row).get('settlement_cargo')}
    if settled:
        if len(rows) != len(current) or any(not row.get('_existing_name') for row in rows):
            raise ValueError('已采用物流结算货物清单，不能从装箱来源拆分或新增结算物料行；请核对采购支出关联。')
        for row in rows:
            previous = settled.get(row.get('_existing_name'))
            if previous and (extra(previous).get('settlement_cargo') != extra(row).get('settlement_cargo')
                             or any(str(previous.get(key) or '') != str(row.get(key) or '') for key in ('material_code','spec_model'))):
                raise ValueError('结算货物身份由采购支出确定，装箱资料只能补充物理信息。')
    allowed = (set(GRID_FIELDS) | {"extra_json", "manual_override_flag", "manual_override_reason"}) - {"name", "modified"}
    created = []
    excluded_at = datetime.now().isoformat(timespec="seconds")
    for item_name in excluded:
        frappe.db.set_value(
            "Overseas Cost Item",
            item_name,
            {
                "is_excluded": 1,
                "excluded_at": excluded_at,
                "excluded_by": "system",
                "exclusion_reason": AUTO_SCOPE_EXCLUSION_REASON,
            },
            update_modified=True,
        )
    for row in rows:
        values = {key: value for key, value in row.items() if key in allowed}
        values.update(batch=batch, version=version, actual_shipped_qty_source_revision=run_id,
                      is_excluded=0, excluded_at=None, excluded_by="", exclusion_reason="",
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


def plan_authoritative_scope_membership(items: list[dict], proposal: dict) -> dict:
    """Return idempotent soft-exclusion changes for an existing current version."""

    payload = proposal.get('payload') or {}
    eligible = {
        str(item.get('name') or ''): item
        for item in items or []
        if str(item.get('name') or '')
        and (
            not int(item.get('is_excluded') or 0)
            or str(item.get('exclusion_reason') or '') == AUTO_SCOPE_EXCLUSION_REASON
        )
    }
    expected = {str(name or '') for name in payload.get('original_item_names') or []}
    if expected != set(eligible):
        raise ValueError('历史版本物料范围已变化，请重新生成修复计划。')
    retained = {
        str(row.get('_existing_name') or '')
        for row in payload.get('rows') or []
        if str(row.get('_existing_name') or '')
    }
    excluded = {str(name or '') for name in payload.get('excluded_item_names') or []}
    if retained & excluded or retained | excluded != set(eligible):
        raise ValueError('国际物流物料范围不完整，不执行历史修复。')
    exclude = sorted(
        name for name in excluded if not int(eligible[name].get('is_excluded') or 0)
    )
    restore = sorted(
        name for name in retained
        if int(eligible[name].get('is_excluded') or 0)
        and str(eligible[name].get('exclusion_reason') or '') == AUTO_SCOPE_EXCLUSION_REASON
    )
    active = sorted(
        name for name in retained
        if name not in excluded
    )
    return {'exclude':exclude,'restore':restore,'active_item_names':active}


def backfill_current_material_scopes(batch_names=None, *, dry_run=True, limit=500):
    """Repair current-version material scopes from locally archived logistics forms.

    The default is deliberately a dry run.  This command never creates rows;
    payment-only additions remain an explicit AI-preview decision.
    """

    import frappe
    from .material_input_service import GRID_FIELDS
    from .packing_snapshot_service import list_material_ai_sources

    if batch_names is None:
        filters={'current_version':['!=','']}
        batches=frappe.get_all(
            'Overseas Cost Batch',filters=filters,
            fields=['name','current_version'],order_by='name asc',
            limit_page_length=max(1,int(limit or 100000)),
        )
    else:
        if isinstance(batch_names,str):
            batch_names=[batch_names]
        requested=[str(value or '').strip() for value in batch_names if str(value or '').strip()]
        batches=frappe.get_all(
            'Overseas Cost Batch',filters={'name':['in',requested]},
            fields=['name','current_version'],order_by='name asc',
            limit_page_length=max(1,len(requested)),
        )
    summary={'dry_run':bool(dry_run),'checked':0,'changed':0,'excluded':0,'restored':0,
             'batches':[],'skipped':[]}
    for batch in batches:
        batch_name=str(batch.get('name') or '')
        version=str(batch.get('current_version') or '')
        summary['checked']+=1
        try:
            sources=list_material_ai_sources(batch_name,version_name=version,original_scope=True)
            logistics=next((source for source in sources
                if source.get('approval_role')=='international_logistics'
                and source.get('source_kind')=='approval_form'
                and source.get('available',True) and not source.get('excluded')),None)
            if not logistics:
                summary['skipped'].append({'batch':batch_name,'reason':'未找到可用的国际物流正文。'})
                continue
            all_items=frappe.get_all(
                'Overseas Cost Item',filters={'batch':batch_name,'version':version},
                fields=list(dict.fromkeys([*GRID_FIELDS,'extra_json','manual_override_flag',
                    'manual_override_reason','is_excluded','exclusion_reason'])),
                order_by='row_no asc,name asc',limit_page_length=10000,
            )
            eligible=[item for item in all_items if
                not int(item.get('is_excluded') or 0)
                or str(item.get('exclusion_reason') or '')==AUTO_SCOPE_EXCLUSION_REASON]
            proposal=build_logistics_reconciliation(eligible,logistics)
            if not proposal or proposal.get('blocked') or not (proposal.get('payload') or {}).get('rows'):
                summary['skipped'].append({'batch':batch_name,'reason':'国际物流物料表无法唯一确定。'})
                continue
            plan=plan_authoritative_scope_membership(all_items,proposal)
            if not plan['exclude'] and not plan['restore']:
                continue
            summary['changed']+=1
            summary['excluded']+=len(plan['exclude'])
            summary['restored']+=len(plan['restore'])
            summary['batches'].append({'batch':batch_name,'version':version,**plan})
            if dry_run:
                continue
            timestamp=datetime.now().isoformat(timespec='seconds')
            for name in plan['exclude']:
                frappe.db.set_value('Overseas Cost Item',name,{
                    'is_excluded':1,'excluded_at':timestamp,'excluded_by':'system',
                    'exclusion_reason':AUTO_SCOPE_EXCLUSION_REASON,
                },update_modified=True)
            for name in plan['restore']:
                frappe.db.set_value('Overseas Cost Item',name,{
                    'is_excluded':0,'excluded_at':None,'excluded_by':'','exclusion_reason':'',
                },update_modified=True)
            frappe.db.set_value('Overseas Cost Batch',batch_name,{
                'item_count':len(plan['active_item_names']),
                'status':'Dirty','confirm_status':'Pending','writeback_status':'Not Started',
            },update_modified=True)
        except Exception as error:
            summary['skipped'].append({'batch':batch_name,'reason':str(error)[:500]})
    return summary


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
    originals = {row['name']:row for row in items}
    notes = []
    fees, changes, unresolved = [], [], list((reconciliation or {}).get("payload", {}).get("unresolved", []))
    for proposal in proposals:
        payload = proposal.get("payload") or {}
        if not proposal.get("default_selected"):
            if proposal.get("conflict"):
                original = originals.get(payload.get('item_name'), {})
                retained = by_name.get(payload.get('item_name'), {})
                fields = payload.get('fields') or {}
                if (proposal.get('proposal_type') == 'item_update' and proposal.get('result_origin') == 'SYSTEM'
                    and str(original.get('manual_override_flag') or '0').lower() not in {'0','false','no'}
                    and fields and set(fields).issubset(PHYSICAL_FIELDS)
                    and all(_purchase_decimal(original.get(field)) is not None and _purchase_decimal(original.get(field)) >= 0 for field in fields)
                    and all(retained.get(field) == original.get(field) for field in fields)):
                    notes.append({'proposal_id':proposal['proposal_id'],
                        'message':f'{original.get("material_code")} 已保留人工填写的重量/体积，装箱单差异留在高级来源中供追溯。'})
                    continue
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
    presented = {row['name']:row for row in rows}
    remaining = []
    for issue in unresolved:
        row = presented.get(issue.get('item_name'), {})
        valuation = row.get('shipment_valuation') or {}
        if ('未匹配到采购明细' in str(issue.get('message') or '') and not valuation.get('error')
            and valuation.get('method') not in (None, 'LEGACY_PURCHASE')
            and _purchase_decimal(row.get('shipment_value_rmb')) is not None and _purchase_decimal(row.get('shipment_value_rmb')) > 0):
            notes.append({**issue,'message':f'{row.get("material_code")} 采购审批仍待关联；本次发货货值 {row["shipment_value_rmb"]} RMB 已取得，不影响本次试算。'})
        else:
            remaining.append(issue)
    unresolved = remaining
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
    return {"items": rows, "fees": fees, "changes": changes, "unresolved": unresolved, "notes": notes,
            "project_summary": cost['project_summary'], "cost_summary": cost['summary']}
