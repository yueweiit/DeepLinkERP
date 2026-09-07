"""物料录入的纯规则：稳定行、有效发货数量和单位来源。"""

import json
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, Optional
from uuid import uuid4

try:
    import frappe
except Exception:  # pragma: no cover - pure tests do not require Frappe
    frappe = None


VALID_QTY_MODES = frozenset(
    {
        "DEFAULT_PURCHASE",
        "EXPLICIT_SOURCE",
        "MANUAL_CONFIRMED",
        "LEGACY_UNVERIFIED",
    }
)

MATERIAL_FIELDS = {
    "actual_shipped_qty": "发货数量",
    "shipped_uom": "发货单位",
    "goods_value": "采购货值",
    "gross_weight_kg": "毛重",
    "volume_m3": "体积",
    "chargeable_weight_kg": "计费重",
    "project_collection": "项目归属",
}

BASIS_FIELDS = {
    "goods_value": "goods_value",
    "gross_weight": "gross_weight_kg",
    "gross_weight_kg": "gross_weight_kg",
    "volume": "volume_m3",
    "volume_m3": "volume_m3",
    "chargeable_weight": "chargeable_weight_kg",
    "chargeable_weight_kg": "chargeable_weight_kg",
}


def _positive_decimal(value: object) -> Optional[Decimal]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def ensure_stable_line_key(
    item: dict,
    *,
    key_factory: Optional[Callable[[], str]] = None,
) -> str:
    """Return the existing business-row key, or create one for a new row."""

    existing = str(item.get("stable_line_key") or "").strip()
    if existing:
        return existing
    generated = str((key_factory or (lambda: uuid4().hex))() or "").strip()
    if not generated:
        raise ValueError("stable_line_key generator returned an empty value")
    return generated


def resolve_effective_quantity(item: dict) -> Dict[str, object]:
    """Resolve the quantity used by costing without inferring legacy provenance."""

    mode = str(item.get("actual_shipped_qty_mode") or "LEGACY_UNVERIFIED").strip()
    if mode not in VALID_QTY_MODES:
        mode = "LEGACY_UNVERIFIED"

    raw_quantity = item.get("quantity") if mode == "DEFAULT_PURCHASE" else item.get("actual_shipped_qty")
    quantity = _positive_decimal(raw_quantity)
    uom = str(item.get("shipped_uom") or item.get("purchase_uom") or item.get("unit") or "").strip()
    blocking = []
    if quantity is None:
        blocking.append({"code": "SHIPPED_QTY_REQUIRED", "field": "actual_shipped_qty"})
    if not uom:
        blocking.append({"code": "SHIPPED_UOM_REQUIRED", "field": "shipped_uom"})

    return {
        "quantity": format(quantity, "f") if quantity is not None else "",
        "uom": uom,
        "mode": mode,
        "is_default": mode == "DEFAULT_PURCHASE",
        "blocking": blocking,
    }


def resolve_goods_value(item: dict) -> Dict[str, object]:
    """Resolve purchase value without multiplying quantities in incompatible units."""

    explicit = _positive_decimal(item.get("goods_value"))
    if explicit is not None:
        return {"amount": explicit, "source": "EXPLICIT_AMOUNT", "blocking": []}

    price = _positive_decimal(item.get("unit_price"))
    purchase_quantity = _positive_decimal(item.get("quantity"))
    price_uom = str(item.get("unit_price_uom") or "").strip()
    purchase_uom = str(item.get("purchase_uom") or item.get("unit") or "").strip()
    if (
        price is not None
        and purchase_quantity is not None
        and price_uom
        and price_uom == purchase_uom
    ):
        return {
            "amount": price * purchase_quantity,
            "source": "PRICE_X_PURCHASE_QTY",
            "blocking": [],
        }

    return {
        "amount": Decimal("0"),
        "source": "UNRESOLVED",
        "blocking": [
            {
                "code": "GOODS_VALUE_OR_UOM_CONVERSION_REQUIRED",
                "field": "goods_value",
            }
        ],
    }


def _optional_requirement(fieldname: str) -> dict:
    return {
        "severity": "optional",
        "gate": "none",
        "code": "OPTIONAL",
        "message": f"{MATERIAL_FIELDS[fieldname]}当前不是必填项",
    }


def _blocking_requirement(fieldname: str, gate: str, code: str, message: str) -> dict:
    return {
        "severity": "blocking",
        "gate": gate,
        "code": code,
        "message": message,
    }


def _scope_item_names(rule: dict) -> set:
    value = rule.get("scope_item_names")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = []
    return {str(name).strip() for name in (value or []) if str(name).strip()}


def _rule_applies(rule: dict, item: dict, item_key: str) -> bool:
    names = _scope_item_names(rule)
    if not names:
        return True
    identities = {
        item_key,
        str(item.get("name") or "").strip(),
        str(item.get("stable_line_key") or "").strip(),
    }
    return bool(names.intersection(identities))


def _has_basis_value(item: dict, fieldname: str) -> bool:
    if fieldname == "goods_value":
        return not resolve_goods_value(item)["blocking"]
    if fieldname == "chargeable_weight_kg":
        return any(
            _positive_decimal(item.get(candidate)) is not None
            for candidate in ("chargeable_weight_kg", "gross_weight_kg", "volume_weight_kg")
        )
    return _positive_decimal(item.get(fieldname)) is not None


def build_material_requirements(items: list, rules: list) -> dict:
    """Build per-cell requirements for the current costing and ERP gates."""

    by_item = {}
    calculation_count = 0
    erp_count = 0
    warning_count = 0

    for index, item in enumerate(items or [], start=1):
        item_key = str(item.get("stable_line_key") or item.get("name") or index)
        requirements = {
            fieldname: _optional_requirement(fieldname)
            for fieldname in MATERIAL_FIELDS
        }

        quantity_state = resolve_effective_quantity(item)
        for issue in quantity_state["blocking"]:
            fieldname = issue["field"]
            requirements[fieldname] = _blocking_requirement(
                fieldname,
                "calculation",
                issue["code"],
                f"请补充{MATERIAL_FIELDS[fieldname]}",
            )

        goods_state = resolve_goods_value(item)
        for issue in goods_state["blocking"]:
            requirements["goods_value"] = _blocking_requirement(
                "goods_value",
                "calculation",
                issue["code"],
                "请补总货值，或补齐采购数量、单价及一致的计价单位",
            )

        if not str(item.get("project_collection") or "").strip():
            requirements["project_collection"] = _blocking_requirement(
                "project_collection",
                "erp_push",
                "PROJECT_ROUTE_REQUIRED",
                "成本可先预览，推送 ERP 前请补项目归属",
            )

        for rule in rules or []:
            if not bool(rule.get("is_enabled", rule.get("is_active", 1))):
                continue
            if not _rule_applies(rule, item, item_key):
                continue
            basis = str(rule.get("allocation_basis") or rule.get("basis_field") or "goods_value")
            fieldname = BASIS_FIELDS.get(basis)
            if not fieldname or _has_basis_value(item, fieldname):
                continue
            rule_name = str(rule.get("name") or rule.get("rule_code") or "当前费用")
            requirements[fieldname] = _blocking_requirement(
                fieldname,
                "calculation",
                f"{basis.upper()}_REQUIRED_BY_{rule_name}",
                f"费用 {rule_name} 按{MATERIAL_FIELDS[fieldname]}分摊，请补{MATERIAL_FIELDS[fieldname]}",
            )

        for requirement in requirements.values():
            if requirement["severity"] == "warning":
                warning_count += 1
            elif requirement["severity"] == "blocking":
                if requirement["gate"] == "erp_push":
                    erp_count += 1
                else:
                    calculation_count += 1
        by_item[item_key] = requirements

    return {
        "summary": {
            "blocking_for_calculation": calculation_count,
            "blocking_for_erp": erp_count,
            "warnings": warning_count,
        },
        "by_item": by_item,
    }


def build_shipping_quantity_updates(
    item: dict,
    *,
    mode: str,
    value: object,
    uom: str,
    source_revision: str = "",
) -> dict:
    normalized_mode = str(mode or "").strip()
    if normalized_mode not in {"DEFAULT_PURCHASE", "MANUAL_CONFIRMED"}:
        raise ValueError("发货数量来源状态不合法。")
    resolved_uom = str(uom or item.get("shipped_uom") or item.get("purchase_uom") or item.get("unit") or "").strip()
    if not resolved_uom:
        raise ValueError("请填写发货单位。")

    if normalized_mode == "DEFAULT_PURCHASE":
        if _positive_decimal(item.get("quantity")) is None:
            raise ValueError("采购数量缺失，不能设为采购数量默认。")
        quantity = None
        revision = ""
    else:
        quantity_value = _positive_decimal(value)
        if quantity_value is None:
            raise ValueError("手工确认的发货数量必须大于 0。")
        quantity = format(quantity_value, "f")
        revision = str(source_revision or "")

    return {
        "actual_shipped_qty": quantity,
        "actual_shipped_qty_mode": normalized_mode,
        "actual_shipped_qty_source_revision": revision,
        "shipped_uom": resolved_uom,
        "cost_output_uom": resolved_uom,
    }


def set_shipping_quantity(
    batch_name: str,
    item_name: str,
    mode: str,
    value: object,
    uom: str,
    edit_token: str,
    expected_modified: str,
) -> dict:
    """Atomically update quantity, provenance and output unit for one item."""

    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "item_name": item_name,
            "updates": build_shipping_quantity_updates(
                {"quantity": value, "purchase_uom": uom},
                mode=mode,
                value=value,
                uom=uom,
            ),
        }

    from overseas_costing.services import batch_service, edit_session_service, import_service

    resolved_batch = batch_service._resolve_batch_name(str(batch_name or ""))
    if not resolved_batch:
        raise ValueError(f"未找到批次：{batch_name}")
    edit_session_service.assert_batch_write(
        resolved_batch,
        edit_token=edit_token,
        expected_modified=expected_modified,
    )
    item = frappe.db.get_value(
        "Overseas Cost Item",
        str(item_name or ""),
        [
            "name",
            "batch",
            "version",
            "row_no",
            "quantity",
            "unit",
            "purchase_uom",
            "shipped_uom",
            "actual_shipped_qty",
        ],
        as_dict=True,
    ) or {}
    if str(item.get("batch") or "") != resolved_batch:
        raise ValueError("物料行不属于当前批次。")
    current_version = str(frappe.db.get_value("Overseas Cost Batch", resolved_batch, "current_version") or "")
    if str(item.get("version") or "") != current_version:
        raise RuntimeError("物料行不属于当前版本，请刷新后重试。")

    updates = build_shipping_quantity_updates(item, mode=mode, value=value, uom=uom)
    changed = import_service._update_item_fields(
        item_name=str(item["name"]),
        batch_doc_name=resolved_batch,
        version_name=current_version,
        row_no=item.get("row_no"),
        field_updates=updates,
        action_remark="设置采购数量默认发货" if mode == "DEFAULT_PURCHASE" else "人工确认发货数量",
    )
    if changed:
        import_service._mark_batch_dirty(resolved_batch)
        frappe.db.commit()
    return {
        "ok": True,
        "batch_name": resolved_batch,
        "version_name": current_version,
        "item_name": str(item["name"]),
        "changed_field_count": len(changed),
        "updates": updates,
        "batch_modified": frappe.db.get_value("Overseas Cost Batch", resolved_batch, "modified"),
    }
