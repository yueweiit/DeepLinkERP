"""费用修改、凭证关联和最终确认事务。"""

from __future__ import annotations

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

TRANSPORT_FEE_PAIRS = {
    "SEA": (
        ("international_sea_freight", "国际海运费", "volume", "freight_invoice"),
        ("sea_port_forwarder_surcharge", "港杂/货代附加费", "volume", "expense_invoice"),
    ),
    "AIR": (
        ("international_air_freight", "国际空运费", "chargeable_weight", "freight_invoice"),
        ("air_forwarder_surcharge", "空运附加费", "chargeable_weight", "expense_invoice"),
    ),
    "EXPRESS": (
        ("international_express_fee", "国际快递费", "chargeable_weight", "freight_invoice"),
        ("express_surcharge", "快递附加费", "chargeable_weight", "expense_invoice"),
    ),
}
COMMON_FEE_TEMPLATES = (
    ("customs_clearance_fee", "清关费", "goods_value", "customs_declaration"),
    ("import_tax", "进口税费", "goods_value", "tax_certificate"),
    ("destination_delivery", "目的地配送费", "gross_weight", "expense_invoice"),
)


def _normalized_fee_name(value: object) -> str:
    return "".join(str(value or "").strip().casefold().replace("／", "/").split())


def build_default_fee_templates(transport_mode: str) -> list[dict]:
    mode = str(transport_mode or "SEA").strip().upper()
    if mode not in TRANSPORT_FEE_PAIRS:
        mode = "SEA"
    rows = [*TRANSPORT_FEE_PAIRS[mode], *COMMON_FEE_TEMPLATES]
    templates = [
        {
            "name": "",
            "logical_fee_key": key,
            "rule_code": key,
            "expense_category": label,
            "amount_status": "MISSING",
            "amount": "",
            "currency": "RMB",
            "allocation_basis": basis,
            "basis_field": basis,
            "scope_type": "ALL_ITEMS",
            "scope_value_json": "[]",
            "required_evidence_role": evidence_role,
            "included_in_fee_key": "",
            "priority_no": index,
            "remark": "",
            "is_active": 1,
            "is_enabled": 1,
            "virtual": True,
        }
        for index, (key, label, basis, evidence_role) in enumerate(rows, start=1)
    ]
    if mode == "EXPRESS":
        for row in templates:
            key = row["logical_fee_key"]
            if key == "international_express_fee":
                continue
            row["entry_responsibility"] = "MEXICO"
            if key in {"customs_clearance_fee", "import_tax", "destination_delivery"}:
                row["currency"] = "MXN"
            if key in {"express_surcharge", "destination_delivery"}:
                # A display/preview default, not a persisted actual or no-charge declaration.
                row.update(amount="0", amount_status="ESTIMATED", is_default_zero=True)
            if key == "destination_delivery":
                row["expense_category"] = "当地快递费"
    return templates


def map_historical_fee_key(fee: dict, transport_mode: str) -> str:
    explicit = str(fee.get("logical_fee_key") or "").strip()
    if explicit:
        return explicit
    aliases = {}
    for row in build_default_fee_templates(transport_mode):
        key = row["logical_fee_key"]
        aliases[_normalized_fee_name(row["expense_category"])] = key
        aliases[_normalized_fee_name(key)] = key
    aliases.update(
        {
            "oceanfreight": "international_sea_freight",
            "seafreight": "international_sea_freight",
            "airfreight": "international_air_freight",
            "expressfreight": "international_express_fee",
            "customsclearance": "customs_clearance_fee",
            "importduty": "import_tax",
            "delivery": "destination_delivery",
            "目的地配送费": "destination_delivery",
        }
    )
    if str(transport_mode or "").strip().upper() == "EXPRESS":
        aliases["当地快递费"] = "destination_delivery"
    for candidate in (fee.get("expense_category"), fee.get("rule_code")):
        matched = aliases.get(_normalized_fee_name(candidate))
        if matched:
            return matched
    return ""


def _decorate_historical_rules(rules: list[dict], transport_mode: str) -> list[dict]:
    """Add read-time logical identities without rewriting historical rows."""

    decorated = []
    for raw in rules or []:
        row = dict(raw or {})
        original_key = str(row.get("logical_fee_key") or "").strip()
        mapped_key = map_historical_fee_key(row, transport_mode)
        if mapped_key:
            row["logical_fee_key"] = mapped_key
            row["historical_name_mapped"] = not bool(original_key)
            row["legacy_unmapped"] = False
        else:
            identity = str(row.get("name") or row.get("rule_code") or "unidentified").strip()
            row["logical_fee_key"] = original_key or f"legacy:{identity}"
            row["historical_name_mapped"] = False
            row["legacy_unmapped"] = True
        row["virtual"] = False
        decorated.append(row)
    return decorated


def compose_fee_worklist_rows(existing_fees: list[dict], transport_mode: str) -> list[dict]:
    """Overlay persisted fees on the five read-only defaults for this transport."""

    templates = build_default_fee_templates(transport_mode)
    template_by_key = {row["logical_fee_key"]: dict(row) for row in templates}
    extras = []
    duplicate_names: dict[str, list[str]] = {}
    for row in _decorate_historical_rules(existing_fees, transport_mode):
        if row.get("is_enabled") in (0, False, "0"):
            continue
        key = str(row.get("logical_fee_key") or "")
        if key in template_by_key:
            if not template_by_key[key].get("virtual"):
                duplicate_names.setdefault(key, []).append(str(row.get("name") or ""))
                continue
            template = template_by_key[key]
            merged = {**template, **row, "virtual": False, "is_default_zero": False}
            if key == "destination_delivery" and template.get("entry_responsibility") == "MEXICO":
                merged["expense_category"] = template["expense_category"]
            for fieldname in (
                "rule_code",
                "currency",
                "allocation_basis",
                "basis_field",
                "scope_type",
                "scope_value_json",
                "required_evidence_role",
            ):
                if row.get(fieldname) in (None, ""):
                    # Preserve the historical RMB interpretation of saved blank currency.
                    # MXN defaults apply only to new, virtual fee rows.
                    merged[fieldname] = "RMB" if fieldname == "currency" else template.get(fieldname)
            if row.get("amount_status") in (None, ""):
                merged["amount_status"] = fee_allocation_service.amount_status(row)
            template_by_key[key] = merged
        else:
            extras.append(row)
    rows = [template_by_key[row["logical_fee_key"]] for row in templates]
    for row in rows:
        names = duplicate_names.get(str(row.get("logical_fee_key") or ""), [])
        if names:
            row["duplicate_rule_names"] = names
            row["requires_review"] = True
    rows.extend(extras)
    return rows


def _safe_json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _candidate_currency(payload: dict) -> str:
    for key, value in payload.items():
        if str(key).strip().casefold() in {"currency", "currency_code", "币种"}:
            currency = str(value or "").strip().upper()
            if currency:
                return "RMB" if currency == "CNY" else currency
    for value in payload.values():
        if isinstance(value, dict):
            nested = _candidate_currency(value)
            if nested:
                return nested
    return ""


def _extract_amount_candidates(payload: dict) -> list[dict]:
    currency = _candidate_currency(payload)
    result = []
    seen = set()

    def walk(value, path: str = "", depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                normalized_key = str(key).strip().casefold()
                is_amount_key = any(
                    marker in normalized_key
                    for marker in ("amount", "total", "fee", "tax", "金额", "费用", "税费")
                )
                if is_amount_key and not isinstance(child, (dict, list, tuple, bool)):
                    try:
                        amount = Decimal(str(child))
                    except (InvalidOperation, TypeError, ValueError):
                        amount = None
                    if amount is not None and amount.is_finite() and amount >= 0:
                        candidate = (
                            format(amount.normalize(), "f"),
                            currency,
                            child_path,
                        )
                        if candidate not in seen:
                            seen.add(candidate)
                            result.append(
                                {"amount": candidate[0], "currency": currency, "path": child_path}
                            )
                walk(child, child_path, depth + 1)
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", depth + 1)

    walk(payload)
    return result[:30]


def build_evidence_candidates(attachments: list[dict]) -> list[dict]:
    """Expose parser values as candidates only; never synthesize fee records."""

    result = []
    for attachment in attachments or []:
        parsed = _safe_json_dict(attachment.get("parse_result_json"))
        mapped = _safe_json_dict(attachment.get("mapped_result_json"))
        classification = parsed.get("classification") if isinstance(parsed.get("classification"), dict) else {}
        result.append(
            {
                "attachment": str(attachment.get("name") or ""),
                "file_name": str(attachment.get("file_name") or ""),
                "file_url": str(attachment.get("file_url") or ""),
                "source_type": str(attachment.get("source_type") or ""),
                "attachment_type": str(attachment.get("attachment_type") or ""),
                "parse_status": str(attachment.get("parse_status") or "Draft"),
                "classification": classification,
                "amount_candidates": _extract_amount_candidates({**parsed, **mapped}),
            }
        )
    return result


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
    if not number.is_finite():
        raise ValueError("费用金额必须是有限数值。")
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

    currency = (
        "RMB"
        if "currency" not in raw
        else str(raw.get("currency") if raw.get("currency") is not None else "").strip().upper()
    )
    if currency == "CNY":
        currency = "RMB"
    if currency not in {"RMB", "MXN", "USD"}:
        raise ValueError("费用币种只能选择人民币（RMB）、墨西哥比索（MXN）或美金（USD）。")

    normalized = {key: raw[key] for key in FEE_FIELDS if key in raw}
    normalized.update(
        {
            "logical_fee_key": fee_key,
            "rule_code": str(raw.get("rule_code") or fee_key).strip(),
            "amount_status": status,
            "amount": amount,
            "currency": currency,
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
    transport_mode = frappe.db.get_value("Overseas Cost Batch", batch_name, "transport_mode") or "SEA"
    existing = _decorate_historical_rules(_query_rules(batch_name, version_name), transport_mode)
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
        frappe.db.set_value("Overseas Cost Batch", batch_name, "status", "Dirty", update_modified=True)
    frappe.db.commit()
    batch_modified = frappe.db.get_value("Overseas Cost Batch", batch_name, "modified")
    return {
        "ok": True,
        "action": merged["action"],
        "rule_name": rule_name,
        "fee": fee,
        "cost_inputs_changed": merged["cost_inputs_changed"],
        "batch_modified": batch_modified,
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
        return {
            "ok": True,
            "action": "existing",
            "evidence_name": existing,
            "batch_modified": frappe.db.get_value("Overseas Cost Batch", batch_name, "modified"),
            "message": "该凭证已关联，未重复新增。",
        }
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
    return {
        "ok": True,
        "action": "created",
        "evidence_name": doc.name,
        "batch_modified": frappe.db.get_value("Overseas Cost Batch", batch_name, "modified"),
        "message": "凭证已关联，等待校验。",
    }


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
    frappe.db.commit()
    return {
        "ok": True,
        "evidence_name": evidence_name,
        "status": normalized,
        "batch_modified": frappe.db.get_value("Overseas Cost Batch", batch_name, "modified"),
        "message": "凭证状态已更新。",
    }


def unlink_fee_evidence_for_attachment(attachment: str, *, reason: str = "附件已删除。") -> dict:
    """Keep evidence history after its file record is removed."""

    if frappe is None:
        return {"ok": True, "dry_run": True, "affected_count": 0}
    rows = frappe.get_all(
        "Overseas Cost Fee Evidence",
        filters={"attachment": str(attachment or "")},
        fields=["name"],
        limit_page_length=5000,
    )
    for row in rows:
        frappe.db.set_value(
            "Overseas Cost Fee Evidence",
            row["name"],
            {
                "attachment": "",
                "validation_status": "UNLINKED",
                "source_revision": str(attachment or ""),
                "validated_by": _session_user(),
                "validated_at": _now(),
                "remark": str(reason or "").strip(),
            },
            update_modified=True,
        )
    return {"ok": True, "affected_count": len(rows)}


def get_fee_worklist(batch_name: str, version_name: str | None = None) -> dict:
    if frappe is None:
        rows = compose_fee_worklist_rows([], "SEA")
        statuses = []
        for row in rows:
            allocation = fee_allocation_service.allocate_fee(row, [])
            statuses.append(
                {
                    **row,
                    **fee_status_service.build_fee_status(
                        fee=row,
                        allocation=allocation,
                        evidence=[],
                    ),
                    "allocation": allocation,
                    "evidence": [],
                }
            )
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "transport_mode": "SEA",
            "fees": statuses,
            "items": statuses,
            "summary": fee_status_service.summarize_fee_statuses(statuses),
            "evidence_candidates": [],
        }
    version = version_name or frappe.db.get_value("Overseas Cost Batch", batch_name, "current_version")
    if not version:
        raise ValueError("当前批次没有可用成本版本。")
    if frappe.db.get_value("Overseas Cost Version", version, "batch") != batch_name:
        raise ValueError("成本版本不属于当前批次。")
    transport_mode = frappe.db.get_value("Overseas Cost Batch", batch_name, "transport_mode") or "SEA"
    rules = compose_fee_worklist_rows(_query_rules(batch_name, version), transport_mode)
    raw_items = frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_name, "version": version},
        fields=[
            "name",
            "stable_line_key",
            "row_no",
            "material_code",
            "product_name",
            "unit",
            "purchase_uom",
            "unit_price_uom",
            "quantity",
            "actual_shipped_qty",
            "actual_shipped_qty_mode",
            "actual_shipped_qty_source_revision",
            "shipped_uom",
            "goods_value",
            "gross_weight_kg",
            "volume_m3",
            "volume_weight_kg",
            "chargeable_weight_kg",
            "project_collection",
        ],
        order_by="row_no asc, name asc",
        limit_page_length=10000,
    )
    from overseas_costing.services.material_input_service import present_material_row

    items = [present_material_row(row) for row in raw_items]
    version_row = frappe.db.get_value(
        "Overseas Cost Version",
        version,
        ["fx_usd_to_rmb", "fx_rmb_to_mxn"],
        as_dict=True,
    ) or {}
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
    from overseas_costing.services.cost_preview_service import allocate_fee_in_rmb

    for rule in rules:
        allocation = allocate_fee_in_rmb(rule, items, fx_context)
        current_hash = fee_status_service.build_fee_input_hash(rule, items=items, fx_context=fx_context)
        evidence = evidence_by_rule.get(str(rule.get("name") or ""), [])
        status = fee_status_service.build_fee_status(
                fee=rule,
                allocation=allocation,
                evidence=evidence,
                calculation={"input_hash": current_hash},
        )
        statuses.append({**rule, **status, "allocation": allocation, "evidence": evidence})

    attachments = frappe.get_all(
        "Overseas Cost Attachment",
        filters={"batch": batch_name},
        fields=[
            "name",
            "version",
            "source_type",
            "attachment_type",
            "file_name",
            "file_url",
            "parse_status",
            "parse_result_json",
            "mapped_result_json",
        ],
        order_by="modified desc",
        limit_page_length=1000,
    )
    summary = fee_status_service.summarize_fee_statuses(statuses)
    return {
        "ok": True,
        "batch_name": batch_name,
        "version_name": version,
        "transport_mode": transport_mode,
        "fees": statuses,
        "items": statuses,
        "summary": summary,
        "evidence_candidates": build_evidence_candidates(attachments),
    }
