"""物料录入的纯规则：稳定行、有效发货数量和单位来源。"""

from __future__ import annotations

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

GRID_FIELDS = (
    "name",
    "modified",
    "row_no",
    "excel_row_no",
    "stable_line_key",
    "material_code",
    "product_name",
    "product_name_es",
    "spec_model",
    "unit",
    "purchase_uom",
    "unit_price",
    "unit_price_uom",
    "purchase_currency",
    "quantity",
    "actual_shipped_qty",
    "actual_shipped_qty_mode",
    "actual_shipped_qty_source_revision",
    "shipped_uom",
    "cost_output_uom",
    "goods_value",
    "gross_weight_kg",
    "volume_m3",
    "volume_weight_kg",
    "chargeable_weight_kg",
    "project_collection",
    "supplier",
    "source_type",
    "source_doc_no",
    "source_file_name",
    "source_attachment_id",
    "parse_status",
)


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

    stored_mode = str(item.get("actual_shipped_qty_mode") or "").strip()
    if not stored_mode:
        stored_mode = (
            "LEGACY_UNVERIFIED"
            if _positive_decimal(item.get("actual_shipped_qty")) is not None
            else "DEFAULT_PURCHASE"
        )
    mode = stored_mode
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


def normalize_grid_page(page: object, page_length: object) -> tuple[int, int]:
    try:
        normalized_page = max(1, int(page or 1))
    except (TypeError, ValueError):
        normalized_page = 1
    try:
        normalized_length = min(200, max(1, int(page_length or 100)))
    except (TypeError, ValueError):
        normalized_length = 100
    return normalized_page, normalized_length


def present_material_row(item: dict) -> dict:
    """Expose a stable row identity and lazy quantity provenance without backfilling."""

    row = dict(item or {})
    stored_key = str(row.get("stable_line_key") or "").strip()
    item_name = str(row.get("name") or "").strip()
    row["stable_line_key"] = stored_key or (f"legacy:{item_name}" if item_name else "")
    quantity_state = resolve_effective_quantity(row)
    row["effective_shipping"] = quantity_state
    row["effective_shipping_quantity"] = quantity_state["quantity"]
    row["effective_shipping_uom"] = quantity_state["uom"]
    row["quantity_source_badge"] = {
        "DEFAULT_PURCHASE": "默认采购数量",
        "EXPLICIT_SOURCE": "资料来源",
        "MANUAL_CONFIRMED": "已人工确认",
        "LEGACY_UNVERIFIED": "历史值待核对",
    }.get(str(quantity_state["mode"]), "待核对")
    row["field_sources"] = {
        "purchase": {
            "source_type": row.get("source_type") or "",
            "source_doc_no": row.get("source_doc_no") or "",
        },
        "shipping_quantity": {
            "mode": quantity_state["mode"],
            "revision": row.get("actual_shipped_qty_source_revision") or "",
        },
    }
    return row


def analyze_material_requirements(items: list[dict], fees: list[dict]) -> dict:
    """Derive red cells from current fee bases; project ownership is informational."""

    from overseas_costing.services import fee_allocation_service

    presented = [present_material_row(dict(row or {})) for row in (items or [])]
    row_states = {}
    for row in presented:
        key = str(row.get("stable_line_key") or row.get("name") or "")
        reasons: dict[str, list[dict]] = {}
        for blocking in (row.get("effective_shipping") or {}).get("blocking") or []:
            reasons.setdefault(str(blocking.get("field") or "actual_shipped_qty"), []).append(blocking)
        if _positive_decimal(row.get("goods_value")) is None:
            reasons.setdefault("goods_value", []).append(
                {"code": "GOODS_VALUE_REQUIRED", "message": "缺少采购货值。"}
            )
        row_states[key] = {"missing_fields": [], "field_reasons": reasons}

    basis_fields = {
        "goods_value": "goods_value",
        "gross_weight": "gross_weight_kg",
        "volume": "volume_m3",
        "chargeable_weight": "chargeable_weight_kg",
    }
    for fee in fees or []:
        if not fee_allocation_service.is_counted_fee(fee):
            continue
        if str(fee.get("scope_type") or "ALL_ITEMS").upper() == "DIRECT_ITEM":
            continue
        basis = str(fee.get("allocation_basis") or fee.get("basis_field") or "goods_value")
        fieldname = basis_fields.get(basis)
        if not fieldname:
            continue
        fee_key = str(fee.get("logical_fee_key") or fee.get("rule_code") or "")
        for row in fee_allocation_service.resolve_eligible_items(fee, presented):
            if _positive_decimal(row.get(fieldname)) is not None:
                continue
            key = str(row.get("stable_line_key") or row.get("name") or "")
            state = row_states.get(key)
            if state is None:
                continue
            state["field_reasons"].setdefault(fieldname, []).append(
                {
                    "code": "ALLOCATION_BASIS_REQUIRED",
                    "fee_key": fee_key,
                    "message": f"费用 {fee_key or '--'} 需要该分摊依据。",
                }
            )

    missing_cell_count = 0
    for state in row_states.values():
        state["missing_fields"] = sorted(state["field_reasons"])
        missing_cell_count += len(state["missing_fields"])
    return {
        "rows": row_states,
        "missing_cell_count": missing_cell_count,
        "affected_row_count": sum(1 for state in row_states.values() if state["missing_fields"]),
    }


def get_material_grid(
    batch_name: str,
    version_name: str | None = None,
    page: object = 1,
    page_length: object = 100,
) -> dict:
    """Return only the material-input grid data for the current batch version."""

    normalized_page, normalized_length = normalize_grid_page(page, page_length)
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "items": [],
            "total": 0,
            "page": normalized_page,
            "page_length": normalized_length,
            "page_count": 0,
        }

    from overseas_costing.services import batch_service

    resolved_batch = batch_service._resolve_batch_name(str(batch_name or ""))
    if not resolved_batch:
        raise ValueError(f"未找到批次：{batch_name}")
    resolved_version = batch_service._resolve_version_name(resolved_batch, version_name)
    if not resolved_version:
        raise ValueError("当前批次没有可用成本版本。")

    filters = {"batch": resolved_batch, "version": resolved_version}
    total = int(frappe.db.count("Overseas Cost Item", filters=filters) or 0)
    raw_items = frappe.get_all(
        "Overseas Cost Item",
        filters=filters,
        fields=list(GRID_FIELDS),
        order_by="row_no asc, name asc",
        limit_start=(normalized_page - 1) * normalized_length,
        limit_page_length=normalized_length,
    )
    items = [present_material_row(item) for item in raw_items]
    all_items = items
    if total > len(items):
        all_items = [
            present_material_row(item)
            for item in frappe.get_all(
                "Overseas Cost Item",
                filters=filters,
                fields=list(GRID_FIELDS),
                order_by="row_no asc, name asc",
                limit_page_length=10000,
            )
        ]
    from overseas_costing.services import fee_service

    transport_mode = frappe.db.get_value("Overseas Cost Batch", resolved_batch, "transport_mode") or "SEA"
    fees = fee_service.compose_fee_worklist_rows(
        fee_service._query_rules(resolved_batch, resolved_version),
        transport_mode,
    )
    requirements = analyze_material_requirements(all_items, fees)
    for item in items:
        item["requirements"] = requirements["rows"].get(item["stable_line_key"], {})
    return {
        "ok": True,
        "batch_name": resolved_batch,
        "version_name": resolved_version,
        "items": items,
        "total": total,
        "page": normalized_page,
        "page_length": normalized_length,
        "page_count": (total + normalized_length - 1) // normalized_length,
        "missing_cell_count": requirements["missing_cell_count"],
        "affected_row_count": requirements["affected_row_count"],
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
