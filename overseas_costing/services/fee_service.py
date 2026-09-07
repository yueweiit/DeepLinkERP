"""费用修改、凭证关联和最终确认事务。"""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation

try:
    import frappe
except Exception:  # pragma: no cover - 纯函数测试时保持可导入
    frappe = None

from overseas_costing.services import (
    edit_session_service,
    fee_allocation_service,
    fee_status_service,
)


AMOUNT_STATUSES = frozenset({"MISSING", "ESTIMATED", "ACTUAL", "NOT_INCURRED", "INCLUDED"})
SCOPE_TYPES = frozenset({"ALL_ITEMS", "ITEMS", "DIRECT_ITEM"})
ALLOCATION_BASES = frozenset({"goods_value", "gross_weight", "volume", "chargeable_weight"})
EVIDENCE_STATUSES = frozenset({"PENDING", "VALID", "INVALID", "UNLINKED"})
FEE_FIELDS = (
    "logical_fee_key",
    "rule_code",
    "expense_category",
    "amount_status",
    "amount",
    "currency",
    "allocation_basis",
    "basis_field",
    "scope_type",
    "scope_value_json",
    "required_evidence_role",
    "included_in_fee_key",
    "priority_no",
    "remark",
    "is_active",
    "is_enabled",
)
COST_INPUT_FIELDS = (
    "amount_status",
    "amount",
    "currency",
    "allocation_basis",
    "scope_type",
    "scope_value_json",
    "included_in_fee_key",
    "is_enabled",
)


def _load_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    loaded = json.loads(value or "{}")
    if not isinstance(loaded, dict):
        raise ValueError("费用参数必须是 JSON 对象。")
    return loaded


def _decimal_text(value) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("费用金额格式不正确。") from exc
    if number < 0:
        raise ValueError("费用金额不能小于 0。")
    return format(number.normalize(), "f")


def _scope_keys(payload: dict) -> list[str]:
    return sorted(set(fee_allocation_service._scope_keys(payload)))


def normalize_fee_payload(payload) -> dict:
    raw = _load_dict(payload)
    fee_key = str(raw.get("logical_fee_key") or "").strip()
    if not fee_key:
        raise ValueError("逻辑费用标识不能为空。")

    status = str(raw.get("amount_status") or "MISSING").strip().upper()
    if status not in AMOUNT_STATUSES:
        raise ValueError("金额状态不合法。")
    scope_type = str(raw.get("scope_type") or "ALL_ITEMS").strip().upper()
    if scope_type not in SCOPE_TYPES:
        raise ValueError("费用适用范围不合法。")
    basis = str(raw.get("allocation_basis") or raw.get("basis_field") or "goods_value").strip()
    if basis not in ALLOCATION_BASES:
        raise ValueError("费用分摊依据不合法。")

    remark = str(raw.get("remark") or "").strip()
    included_in = str(raw.get("included_in_fee_key") or "").strip()
    if status in {"NOT_INCURRED", "INCLUDED"} and not remark:
        raise ValueError("标记未发生或已包含时必须填写原因。")
    if status == "INCLUDED" and not included_in:
        raise ValueError("标记已包含时必须选择“已包含于费用”或本批采购金额。")

    keys = _scope_keys(raw)
    if scope_type in {"ITEMS", "DIRECT_ITEM"} and not keys:
        raise ValueError("请选择费用适用的物料。")
    if scope_type == "DIRECT_ITEM" and len(keys) != 1:
        raise ValueError("直接费用必须且只能选择一条物料。")

    amount = ""
    if status in fee_allocation_service.COUNTED_AMOUNT_STATUSES:
        if raw.get("amount") in (None, ""):
            raise ValueError("暂估或实际费用必须填写金额。")
        amount = _decimal_text(raw.get("amount"))
    elif raw.get("amount") not in (None, ""):
        amount = _decimal_text(raw.get("amount"))

    normalized = {key: raw[key] for key in FEE_FIELDS if key in raw}
    normalized.update(
        {
            "logical_fee_key": fee_key,
            "rule_code": str(raw.get("rule_code") or fee_key).strip(),
            "amount_status": status,
            "amount": amount,
            "currency": str(raw.get("currency") or "RMB").strip().upper(),
            "allocation_basis": basis,
            "basis_field": basis,
            "scope_type": scope_type,
            "scope_value_json": json.dumps(keys, ensure_ascii=False, separators=(",", ":")) if scope_type != "ALL_ITEMS" else "[]",
            "included_in_fee_key": included_in,
            "remark": remark,
            "is_active": 1 if raw.get("is_active", 1) else 0,
            "is_enabled": 1 if raw.get("is_enabled", 1) else 0,
        }
    )
    return normalized


def _cost_value(record: dict, fieldname: str):
    value = record.get(fieldname)
    if fieldname == "amount" and value not in (None, ""):
        return _decimal_text(value)
    if fieldname == "scope_value_json":
        return tuple(_scope_keys(record))
    return value


def merge_logical_fee(existing_fees: list[dict], payload: dict, *, revision: str | None = None) -> dict:
    fees = deepcopy(existing_fees or [])
    fee_key = payload["logical_fee_key"]
    existing_index = next(
        (index for index, row in enumerate(fees) if str(row.get("logical_fee_key") or "") == fee_key),
        None,
    )
    previous = fees[existing_index] if existing_index is not None else {}
    merged = {**previous, **payload}
    cost_inputs_changed = existing_index is None or any(
        _cost_value(previous, fieldname) != _cost_value(merged, fieldname)
        for fieldname in COST_INPUT_FIELDS
    )
    revision_value = revision or uuid.uuid4().hex
    if existing_index is None or any(
        _cost_value(previous, fieldname) != _cost_value(merged, fieldname)
        for fieldname in ("amount", "amount_status", "currency")
    ):
        merged["amount_revision"] = revision_value
    if existing_index is None or any(
        _cost_value(previous, fieldname) != _cost_value(merged, fieldname)
        for fieldname in ("scope_type", "scope_value_json", "allocation_basis")
    ):
        merged["scope_revision"] = revision_value

    if existing_index is None:
        fees.append(merged)
        action = "created"
    else:
        fees[existing_index] = merged
        action = "updated"
    return {
        "fees": fees,
        "fee": merged,
        "action": action,
        "cost_inputs_changed": cost_inputs_changed,
    }


def deduplicate_evidence_candidates(candidates: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for row in candidates or []:
        normalized = {
            "attachment": str(row.get("attachment") or "").strip(),
            "evidence_role": str(row.get("evidence_role") or "").strip(),
            "source_revision": str(row.get("source_revision") or "").strip(),
        }
        key = tuple(normalized.values())
        if not normalized["attachment"] or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def validate_fee_completion(statuses: list[dict]) -> dict:
    blocking = []
    if not statuses:
        blocking.append({"code": "NO_FEES_DEFINED", "fee_key": "", "label": "尚未建立费用清单"})
    for status in statuses or []:
        for todo in status.get("todos") or []:
            blocking.append({"fee_key": status.get("fee_key") or "", **todo})
    return {"ok": not blocking, "blocking": blocking}


def build_completion_input_hash(statuses: list[dict]) -> str:
    payload = [
        {
            "fee_key": row.get("fee_key") or "",
            "input_hash": row.get("input_hash") or "",
            "amount_state": row.get("amount_state") or "",
            "allocation_state": row.get("allocation_state") or "",
            "evidence_state": row.get("evidence_state") or "",
        }
        for row in sorted(statuses or [], key=lambda value: str(value.get("fee_key") or ""))
    ]
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now():
    if frappe is not None:
        try:
            return frappe.utils.now()
        except Exception:
            pass
    return datetime.now().isoformat(timespec="seconds")


def _session_user() -> str:
    return str(getattr(getattr(frappe, "session", None), "user", "") or "")


def _revision() -> str:
    if frappe is not None and hasattr(frappe, "generate_hash"):
        return str(frappe.generate_hash(length=20))
    return uuid.uuid4().hex[:20]


def _assert_write_context(batch_name: str, version_name: str | None, edit_token, expected_modified) -> None:
    edit_session_service.assert_batch_write(
        batch_name,
        edit_token=edit_token,
        expected_modified=expected_modified,
    )
    if version_name:
        version_batch = frappe.db.get_value("Overseas Cost Version", version_name, "batch")
        if version_batch != batch_name:
            raise ValueError("成本版本不属于当前批次。")
    from overseas_costing.services.batch_service import _build_invalid_business_state

    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_name,
        ["name", "source_approval_status", "extra_json"],
        as_dict=True,
    ) or {}
    invalid = _build_invalid_business_state(batch)
    if invalid.get("invalid"):
        raise ValueError(invalid.get("message") or "当前审批已失效，不能修改费用。")


def _rule_fields() -> list[str]:
    return [
        "name",
        "batch",
        "version",
        *FEE_FIELDS,
        "amount_revision",
        "scope_revision",
    ]


def _query_rules(batch_name: str, version_name: str) -> list[dict]:
    return frappe.get_all(
        "Overseas Cost Allocation Rule",
        filters={"batch": batch_name, "version": version_name},
        fields=_rule_fields(),
        order_by="priority_no asc, modified asc",
        limit_page_length=1000,
    )


def save_fee(
    batch_name: str,
    version_name: str,
    fee_payload,
    edit_token: str | None = None,
    expected_modified: str | None = None,
) -> dict:
    payload = normalize_fee_payload(fee_payload)
    if frappe is None:
        merged = merge_logical_fee([], payload, revision="DRY-RUN")
        return {"ok": True, "dry_run": True, **merged}

    _assert_write_context(batch_name, version_name, edit_token, expected_modified)
    existing = _query_rules(batch_name, version_name)
    merged = merge_logical_fee(existing, payload, revision=_revision())
    fee = merged["fee"]
    values = {key: fee.get(key) for key in (*FEE_FIELDS, "amount_revision", "scope_revision")}
    values.update({"batch": batch_name, "version": version_name})
    if merged["action"] == "updated":
        rule_name = fee["name"]
        frappe.db.set_value("Overseas Cost Allocation Rule", rule_name, values, update_modified=True)
    else:
        rule_name = frappe.get_doc({"doctype": "Overseas Cost Allocation Rule", **values}).insert(
            ignore_permissions=True
        ).name
    if merged["cost_inputs_changed"]:
        invalidate_fee_completion(
            batch_name,
            version_name,
            reason=f"费用 {payload['logical_fee_key']} 的金额、性质、范围或分摊依据已变化。",
        )
        frappe.db.set_value("Overseas Cost Batch", batch_name, "status", "Dirty", update_modified=True)
    frappe.db.commit()
    return {
        "ok": True,
        "action": merged["action"],
        "rule_name": rule_name,
        "fee": fee,
        "cost_inputs_changed": merged["cost_inputs_changed"],
        "message": "费用已保存，原逻辑费用记录已替换更新。",
    }


def link_fee_evidence(
    batch_name: str,
    fee_rule: str,
    attachment: str,
    evidence_role: str,
    edit_token: str | None = None,
    expected_modified: str | None = None,
) -> dict:
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "evidence": {
                "batch": batch_name,
                "fee_rule": fee_rule,
                "attachment": attachment,
                "evidence_role": evidence_role,
                "validation_status": "PENDING",
            },
        }
    rule = frappe.db.get_value(
        "Overseas Cost Allocation Rule",
        fee_rule,
        ["name", "batch", "version"],
        as_dict=True,
    ) or {}
    if rule.get("batch") != batch_name:
        raise ValueError("费用规则不属于当前批次。")
    _assert_write_context(batch_name, rule.get("version"), edit_token, expected_modified)
    attachment_row = frappe.db.get_value(
        "Overseas Cost Attachment",
        attachment,
        ["name", "batch", "version", "modified"],
        as_dict=True,
    ) or {}
    if attachment_row.get("batch") != batch_name:
        raise ValueError("凭证附件不属于当前批次。")
    role = str(evidence_role or "").strip()
    if not role:
        raise ValueError("凭证角色不能为空。")
    existing = frappe.db.get_value(
        "Overseas Cost Fee Evidence",
        {"fee_rule": fee_rule, "attachment": attachment, "evidence_role": role},
        "name",
    )
    if existing:
        return {"ok": True, "action": "existing", "evidence_name": existing, "message": "该凭证已关联，未重复新增。"}
    doc = frappe.get_doc(
        {
            "doctype": "Overseas Cost Fee Evidence",
            "batch": batch_name,
            "version": rule.get("version"),
            "fee_rule": fee_rule,
            "attachment": attachment,
            "evidence_role": role,
            "validation_status": "PENDING",
            "source_revision": str(attachment_row.get("modified") or ""),
        }
    ).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "action": "created", "evidence_name": doc.name, "message": "凭证已关联，等待校验。"}


def set_fee_evidence_status(
    batch_name: str,
    evidence_name: str,
    status: str,
    remark: str | None = None,
    edit_token: str | None = None,
    expected_modified: str | None = None,
) -> dict:
    normalized = str(status or "").strip().upper()
    if normalized not in EVIDENCE_STATUSES:
        raise ValueError("费用凭证校验状态不合法。")
    if frappe is None:
        return {"ok": True, "dry_run": True, "evidence_name": evidence_name, "status": normalized}
    row = frappe.db.get_value(
        "Overseas Cost Fee Evidence",
        evidence_name,
        ["name", "batch", "version", "attachment"],
        as_dict=True,
    ) or {}
    if row.get("batch") != batch_name:
        raise ValueError("费用凭证不属于当前批次。")
    _assert_write_context(batch_name, row.get("version"), edit_token, expected_modified)
    values = {
        "validation_status": normalized,
        "remark": str(remark or "").strip(),
        "validated_by": _session_user(),
        "validated_at": _now(),
    }
    frappe.db.set_value("Overseas Cost Fee Evidence", evidence_name, values, update_modified=True)
    if normalized in {"INVALID", "UNLINKED"}:
        invalidate_fee_completion(
            batch_name,
            row.get("version"),
            reason=f"最终凭证 {evidence_name} 已标记为 {normalized}。",
        )
    frappe.db.commit()
    return {"ok": True, "evidence_name": evidence_name, "status": normalized, "message": "凭证状态已更新。"}


def invalidate_fee_completion(batch_name: str, version_name: str, *, reason: str) -> dict:
    if frappe is None:
        return {"ok": True, "dry_run": True, "invalidated_count": 0}
    confirmations = frappe.get_all(
        "Overseas Cost Fee Completion",
        filters={"batch": batch_name, "version": version_name, "status": "CONFIRMED"},
        fields=["name", "input_hash", "creation"],
        order_by="creation desc",
        limit_page_length=1,
    )
    if not confirmations:
        return {"ok": True, "invalidated_count": 0}
    confirmation = confirmations[0]
    existing = frappe.db.get_value(
        "Overseas Cost Fee Completion",
        {
            "batch": batch_name,
            "version": version_name,
            "input_hash": confirmation.get("input_hash"),
            "status": "INVALIDATED",
        },
        "name",
    )
    if existing:
        return {"ok": True, "invalidated_count": 0, "invalidation_name": existing}
    doc = frappe.get_doc(
        {
            "doctype": "Overseas Cost Fee Completion",
            "batch": batch_name,
            "version": version_name,
            "input_hash": confirmation.get("input_hash"),
            "status": "INVALIDATED",
            "invalidated_by": _session_user(),
            "invalidated_at": _now(),
            "invalidation_reason": str(reason or "").strip(),
        }
    ).insert(ignore_permissions=True)
    return {"ok": True, "invalidated_count": 1, "invalidation_name": doc.name}


def invalidate_fee_completion_for_evidence(
    attachment: str,
    *,
    reason: str = "最终凭证已删除或撤销。",
    unlink: bool = True,
) -> dict:
    if frappe is None or not hasattr(frappe, "get_all"):
        return {"ok": True, "dry_run": frappe is None, "affected_evidence_count": 0, "invalidated_count": 0}
    rows = frappe.get_all(
        "Overseas Cost Fee Evidence",
        filters={"attachment": attachment},
        fields=["name", "batch", "version", "validation_status"],
        limit_page_length=1000,
    )
    invalidated_count = 0
    for row in rows:
        if unlink:
            frappe.db.set_value(
                "Overseas Cost Fee Evidence",
                row["name"],
                {
                    "attachment": "",
                    "validation_status": "UNLINKED",
                    "source_revision": str(attachment),
                    "validated_by": _session_user(),
                    "validated_at": _now(),
                    "remark": str(reason or "").strip(),
                },
                update_modified=True,
            )
        invalidated_count += invalidate_fee_completion(
            row.get("batch"),
            row.get("version"),
            reason=reason,
        ).get("invalidated_count", 0)
    return {
        "ok": True,
        "affected_evidence_count": len(rows),
        "invalidated_count": invalidated_count,
    }


def get_fee_worklist(batch_name: str, version_name: str | None = None) -> dict:
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "items": [],
            "summary": fee_status_service.summarize_fee_statuses([]),
            "input_hash": build_completion_input_hash([]),
            "completion_status": "INCOMPLETE",
        }
    version = version_name or frappe.db.get_value("Overseas Cost Batch", batch_name, "current_version")
    rules = _query_rules(batch_name, version)
    items = frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_name, "version": version},
        fields=[
            "name",
            "stable_line_key",
            "quantity",
            "actual_shipped_qty",
            "actual_shipped_qty_source_revision",
            "goods_value",
            "gross_weight_kg",
            "volume_m3",
            "volume_weight_kg",
            "chargeable_weight_kg",
        ],
        limit_page_length=10000,
    )
    version_row = frappe.db.get_value(
        "Overseas Cost Version",
        version,
        ["fx_usd_to_rmb", "fx_rmb_to_mxn", "summary_snapshot_json"],
        as_dict=True,
    ) or {}
    try:
        snapshot = json.loads(version_row.get("summary_snapshot_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        snapshot = {}
    saved_statuses = {
        str(row.get("fee_key") or ""): row for row in snapshot.get("fee_statuses") or []
    }
    evidence_rows = frappe.get_all(
        "Overseas Cost Fee Evidence",
        filters={"batch": batch_name, "version": version},
        fields=[
            "name",
            "fee_rule",
            "attachment",
            "evidence_role",
            "validation_status",
            "source_revision",
            "remark",
        ],
        limit_page_length=5000,
    )
    evidence_by_rule: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_rule.setdefault(str(row.get("fee_rule") or ""), []).append(row)

    fx_context = {
        "fx_usd_to_rmb": version_row.get("fx_usd_to_rmb"),
        "fx_rmb_to_mxn": version_row.get("fx_rmb_to_mxn"),
    }
    statuses = []
    for rule in rules:
        key = str(rule.get("logical_fee_key") or rule.get("rule_code") or "")
        current_hash = fee_status_service.build_fee_input_hash(rule, items=items, fx_context=fx_context)
        saved = saved_statuses.get(key) or {}
        statuses.append(
            fee_status_service.build_fee_status(
                fee=rule,
                allocation={"status": saved.get("allocation_state") or "NOT_ALLOCATED"},
                evidence=evidence_by_rule.get(str(rule.get("name") or ""), []),
                calculation={"input_hash": current_hash, "fee_input_hash": saved.get("input_hash") or ""},
            )
        )
    completion_hash = build_completion_input_hash(statuses)
    events = frappe.get_all(
        "Overseas Cost Fee Completion",
        filters={"batch": batch_name, "version": version, "input_hash": completion_hash},
        fields=["name", "status", "creation", "confirmed_by", "confirmed_at", "invalidation_reason"],
        order_by="creation asc",
        limit_page_length=1000,
    )
    completion_status = "INCOMPLETE"
    if events:
        completion_status = "COMPLETE" if events[-1].get("status") == "CONFIRMED" else "INVALIDATED"
    summary = fee_status_service.summarize_fee_statuses(statuses)
    summary["completion_status"] = completion_status
    return {
        "ok": True,
        "batch_name": batch_name,
        "version_name": version,
        "items": statuses,
        "summary": summary,
        "input_hash": completion_hash,
        "completion_status": completion_status,
        "completion_events": events,
    }


def confirm_all_fees_complete(
    batch_name: str,
    version_name: str,
    expected_input_hash: str,
    edit_token: str | None = None,
    expected_modified: str | None = None,
) -> dict:
    if frappe is None:
        return {"ok": False, "dry_run": True, "message": "当前未连接 Frappe，不会伪造费用完成确认。"}
    _assert_write_context(batch_name, version_name, edit_token, expected_modified)
    work = get_fee_worklist(batch_name, version_name)
    validation = validate_fee_completion(work["items"])
    if not validation["ok"]:
        return {"ok": False, **validation, "message": "费用仍有未完成项，不能确认已齐。"}
    if str(expected_input_hash or "") != work["input_hash"]:
        return {"ok": False, "stale": True, "message": "费用输入已变化，请刷新后重新确认。"}
    doc = frappe.get_doc(
        {
            "doctype": "Overseas Cost Fee Completion",
            "batch": batch_name,
            "version": version_name,
            "input_hash": work["input_hash"],
            "status": "CONFIRMED",
            "confirmed_by": _session_user(),
            "confirmed_at": _now(),
        }
    ).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "completion_name": doc.name, "input_hash": work["input_hash"], "message": "已确认本批费用完整。"}
