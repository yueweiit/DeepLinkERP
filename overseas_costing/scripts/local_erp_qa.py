"""Create and verify one isolated local ERP writeback QA fixture.

This script is intentionally limited to the fixed LOCAL-ERP-QA batch. It does
not call the real ERP HTTP writeback endpoint and it never touches production
or non-test records.

Run inside the Frappe bench:

    bench --site development.localhost execute \
      overseas_costing.scripts.local_erp_qa.build

The normal sequence is:

    build -> recalculate_batch.recalculate -> check_writeback_ready
    -> confirm_calculation_result -> preview_erp_payload -> write_local_draft
    -> cleanup
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

try:
    import frappe
except ModuleNotFoundError:  # pragma: no cover - bench execute provides Frappe
    frappe = None


__test__ = False

BATCH_NO = "LOCAL-ERP-QA-20260918"
APPROVAL_NO = "ERPTEST-HPCU5155607-LOCAL-20260918"
INSTANCE_ID = "ERPTEST-INSTANCE-20260918"
CORP_ID = "ERPTEST-CORP-20260918"
SUPPLIER_NAME = "ERPTEST Supplier LOCAL-ERP-QA-20260918"
ITEM_PREFIX = "ERPTEST-LOCAL-ERP-QA-20260918-"
SOURCE_BINDING_ID = "ERPTEST-SOURCE-LOCAL-ERP-QA-20260918"
SOURCE_SNAPSHOT = "ERPTEST-SNAPSHOT-LOCAL-ERP-QA-20260918"
VERSION_CODE = "LOCAL-ERP-QA-20260918-V1"

FX_USD_TO_RMB = 7.01
FX_RMB_TO_MXN = 2.60


def build() -> dict[str, Any]:
    """Recreate the fixed local QA fixture and return its database summary."""

    _require_frappe()
    cleanup()
    from overseas_costing.install import ensure_erpnext_standard_fields

    ensure_result = ensure_erpnext_standard_fields()
    if not ensure_result.get("ok"):
        return {"ok": False, "stage": "ensure_standard_fields", **ensure_result}

    batch = frappe.get_doc(
        {
            "doctype": "Overseas Cost Batch",
            "batch_no": BATCH_NO,
            "transport_mode": "SEA",
            "business_type": "SEA_STANDARD",
            "project_collection": "ERP local QA",
            "subsidiary_code": "YW MOLDES/UV",
            "source_type": "manual",
            "source_approval_no": APPROVAL_NO,
            "source_instance_id": INSTANCE_ID,
            "source_approval_status": "COMPLETED",
            "source_title": "ERP local writeback QA fixture",
            "source_creator_name": "Codex local QA",
            "source_creator_dept": "Engineering",
            "source_attachment_count": 0,
            "status": "Imported",
            "confirm_status": "Pending",
            "writeback_status": "Not Started",
            "item_count": 4,
            "import_remark": "LOCAL-ERP-QA only; no production source.",
            "source_remark": "Synthetic fixture for local ERP writeback verification.",
            "source_corp_id": CORP_ID,
            "extra_json": json.dumps(
                {
                    "local_erp_qa": True,
                    "qa_batch_no": BATCH_NO,
                    "oa_logistics_trace": {
                        "source_instance_id": INSTANCE_ID,
                        "approval_status": "COMPLETED",
                        "linked_purchase_approvals": [],
                    },
                },
                ensure_ascii=False,
            ),
        }
    ).insert(ignore_permissions=True)

    version = frappe.get_doc(
        {
            "doctype": "Overseas Cost Version",
            "batch": batch.name,
            "version_code": VERSION_CODE,
            "version_type": "Actual",
            "status": "Active",
            "is_current": 1,
            "source_type": "Manual",
            "fx_usd_to_rmb": FX_USD_TO_RMB,
            "fx_rmb_to_mxn": FX_RMB_TO_MXN,
            "remark": "LOCAL-ERP-QA synthetic cost version.",
            "created_by_name": "Codex local QA",
            "extra_json": json.dumps(
                {"local_erp_qa": True, "qa_batch_no": BATCH_NO},
                ensure_ascii=False,
            ),
        }
    ).insert(ignore_permissions=True)

    frappe.db.set_value(
        "Overseas Cost Batch",
        batch.name,
        {
            "current_version": version.name,
            "version_count": 1,
        },
        update_modified=False,
    )

    for row_no, values in enumerate(_item_values(), start=1):
        frappe.get_doc(
            {
                "doctype": "Overseas Cost Item",
                "batch": batch.name,
                "version": version.name,
                "row_no": row_no,
                "excel_row_no": row_no + 1,
                "stable_line_key": f"LOCAL-QA-LINE-{row_no}",
                "source_type": "LOCAL_ERP_QA",
                "source_doc_no": APPROVAL_NO,
                "parse_status": "MANUAL",
                "material_code": values["material_code"],
                "product_name": values["product_name"],
                "spec_model": values["spec_model"],
                "unit": "个",
                "purchase_uom": "个",
                "shipped_uom": "个",
                "supplier": SUPPLIER_NAME,
                "unit_price": values["unit_price"],
                "purchase_currency": "CNY",
                "quantity": values["quantity"],
                "actual_shipped_qty": values["quantity"],
                "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
                "cost_output_uom": "个",
                "goods_value": values["goods_value"],
                "gross_weight_kg": values["gross_weight_kg"],
                "net_weight_kg": values["net_weight_kg"],
                "volume_m3": values["volume_m3"],
                "chargeable_weight_kg": values["gross_weight_kg"],
                "project_collection": "ERP local QA",
                "subsidiary_code": "YW MOLDES/UV",
                "transport_mode": "SEA",
                "is_excluded": 0,
                "extra_json": json.dumps(
                    {"local_erp_qa": True, "qa_batch_no": BATCH_NO},
                    ensure_ascii=False,
                ),
            }
        ).insert(ignore_permissions=True)

    for rule in _rule_values(version.name, batch.name):
        frappe.get_doc(
            {"doctype": "Overseas Cost Allocation Rule", **rule}
        ).insert(ignore_permissions=True)

    frappe.db.commit()
    return _summary("build", batch.name, version.name)


def cleanup() -> dict[str, Any]:
    """Delete only the fixed QA fixture and its local draft ERP records."""

    _require_frappe()
    deleted: dict[str, list[str]] = {}

    po_names = frappe.get_all(
        "Purchase Order",
        filters={"custom_overseas_batch_no": BATCH_NO},
        pluck="name",
        limit_page_length=100,
    )
    for name in po_names:
        frappe.delete_doc("Purchase Order", name, ignore_permissions=True, force=True)
    if po_names:
        deleted["Purchase Order"] = po_names

    item_names = frappe.get_all(
        "Item",
        filters={"item_code": ["like", f"{ITEM_PREFIX}%"]},
        pluck="name",
        limit_page_length=100,
    )
    for name in item_names:
        if not str(name).startswith(ITEM_PREFIX):
            raise ValueError("Refusing to delete an item outside the QA prefix.")
        if not frappe.db.exists("Item", name):
            continue
        frappe.delete_doc("Item", name, ignore_permissions=True, force=True)
    if item_names:
        deleted["Item"] = item_names

    for doctype in (
        "Overseas Cost Audit Log",
        "Overseas Cost Allocation Rule",
        "Overseas Cost Item",
        "Overseas Cost Version",
    ):
        names = frappe.get_all(
            doctype,
            filters={"batch": ["in", _batch_doc_names()]},
            pluck="name",
            limit_page_length=1000,
        ) if doctype != "Overseas Cost Audit Log" else frappe.get_all(
            doctype,
            filters={"batch": ["in", _batch_doc_names()]},
            pluck="name",
            limit_page_length=1000,
        )
        for name in names:
            frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
        if names:
            deleted[doctype] = names

    batch_names = _batch_doc_names()
    for name in batch_names:
        if not str(name):
            continue
        frappe.delete_doc(
            "Overseas Cost Batch", name, ignore_permissions=True, force=True
        )
    if batch_names:
        deleted["Overseas Cost Batch"] = batch_names

    if frappe.db.exists("Supplier", SUPPLIER_NAME):
        linked = frappe.get_all(
            "Purchase Order",
            filters={"supplier": SUPPLIER_NAME},
            pluck="name",
            limit_page_length=1,
        )
        if linked:
            raise ValueError("Refusing to delete QA supplier while a purchase order remains.")
        frappe.delete_doc(
            "Supplier", SUPPLIER_NAME, ignore_permissions=True, force=True
        )
        deleted["Supplier"] = [SUPPLIER_NAME]

    frappe.db.commit()
    return {"ok": True, "deleted": deleted}


def write_local_draft() -> dict[str, Any]:
    """Write a Draft Purchase Order locally after the public ERP gate passes."""

    _require_frappe()
    batch_name = _resolve_batch_name()
    if not batch_name:
        return {"ok": False, "stage": "write_local_draft", "message": "QA batch is missing."}

    from overseas_costing.services import batch_service, erp_client

    readiness = batch_service.check_writeback_ready(BATCH_NO)
    if not readiness.get("ready"):
        return {
            "ok": False,
            "stage": "write_local_draft",
            "message": "Writeback gate is not ready.",
            "readiness": readiness,
        }

    preview = batch_service.preview_erp_payload(BATCH_NO)
    payload = preview.get("payload") or {}
    if not payload:
        return {
            "ok": False,
            "stage": "preview",
            "message": "No ERP payload was produced.",
            "preview": preview,
        }

    config = _local_erp_config()
    _ensure_supplier(config["supplier"])
    created_items = _ensure_local_items(payload, config)
    po_body = erp_client._build_purchase_order_body(payload, config)
    purchase_order = frappe.get_doc(
        {"doctype": "Purchase Order", **po_body}
    ).insert(ignore_permissions=True)
    frappe.db.commit()

    actual = frappe.get_all(
        "Purchase Order Item",
        filters={"parent": purchase_order.name},
        fields=[
            "item_code",
            "qty",
            "rate",
            "custom_overseas_original_unit_price",
            "custom_overseas_comprehensive_unit_price",
            "custom_overseas_original_amount",
            "custom_overseas_comprehensive_amount",
            "custom_overseas_freight_alloc_amount",
            "custom_overseas_clearance_alloc_amount",
            "custom_overseas_tax_alloc_amount",
            "custom_overseas_batch_no",
            "custom_overseas_cost_version",
            "custom_overseas_business_entity",
            "custom_overseas_stable_line_key",
        ],
        order_by="idx asc",
        limit_page_length=100,
    )
    checks = _compare_purchase_order_rows(payload, actual, config)
    return {
        "ok": all(row["ok"] for row in checks),
        "stage": "write_local_draft",
        "local_only": True,
        "http_writeback_called": False,
        "purchase_order": purchase_order.name,
        "purchase_order_status": purchase_order.docstatus,
        "created_items": created_items,
        "preview_ok": bool(preview.get("ok")),
        "preview_config_ready": bool(preview.get("config_ready")),
        "preview_blocking_reasons": preview.get("blocking_reasons") or [],
        "checks": checks,
    }


def run_full() -> dict[str, Any]:
    """Run the whole local flow without calling the real ERP endpoint."""

    result: dict[str, Any] = {"ok": False, "batch_no": BATCH_NO, "steps": []}
    result["steps"].append(build())
    if not result["steps"][-1].get("ok"):
        return result

    from overseas_costing.scripts.recalculate_batch import recalculate
    from overseas_costing.services import batch_service

    recalculated = recalculate(BATCH_NO)
    result["steps"].append({"stage": "recalculate", **recalculated})
    if not recalculated.get("ok"):
        return result

    confirmed = batch_service.confirm_calculation_result(
        BATCH_NO,
        remark="Local ERP writeback QA synthetic fixture.",
    )
    result["steps"].append({"stage": "confirm", **confirmed})
    if not confirmed.get("confirmed"):
        return result

    readiness = batch_service.check_writeback_ready(BATCH_NO)
    result["steps"].append({"stage": "writeback_gate", **readiness})
    if not readiness.get("ready"):
        return result

    preview = batch_service.preview_erp_payload(BATCH_NO)
    result["steps"].append(
        {
            "stage": "preview",
            "ok": bool(preview.get("ok")),
            "ready": bool(preview.get("ready")),
            "config_ready": bool(preview.get("config_ready")),
            "payload_item_count": len((preview.get("payload") or {}).get("items") or []),
            "blocking_reasons": preview.get("blocking_reasons") or [],
        }
    )
    local_draft = write_local_draft()
    result["steps"].append(local_draft)
    result["ok"] = bool(local_draft.get("ok"))
    return result


def _item_values() -> list[dict[str, Any]]:
    rows = [
        ("MOLD-001", "Mold ring", "MR-100", 120, 680.00, 420.0, 390.0, 0.62),
        ("MOLD-002", "Mold insert", "MI-220", 80, 950.00, 360.0, 330.0, 0.41),
        ("PACK-001", "Packing tray", "PT-010", 300, 48.00, 510.0, 470.0, 0.88),
        ("AUX-001", "Accessory kit", "AK-050", 160, 125.00, 275.0, 250.0, 0.36),
    ]
    return [
        {
            "material_code": f"{ITEM_PREFIX}{code}",
            "product_name": name,
            "spec_model": spec,
            "quantity": quantity,
            "unit_price": unit_price,
            "goods_value": round(quantity * unit_price, 2),
            "gross_weight_kg": gross,
            "net_weight_kg": net,
            "volume_m3": volume,
        }
        for code, name, spec, quantity, unit_price, gross, net, volume in rows
    ]


def _rule_values(version_name: str, batch_name: str) -> list[dict[str, Any]]:
    common = {
        "batch": batch_name,
        "version": version_name,
        "scope_type": "ALL_ITEMS",
        "scope_value_json": "{}",
        "scope_revision": "LOCAL-1",
        "required_evidence_role": "LOCAL_QA",
        "priority_no": 10,
        "is_enabled": 1,
        "is_active": 1,
        "is_final": 1,
        "amount_status": "ACTUAL",
        "source_binding_id": SOURCE_BINDING_ID,
        "source_snapshot": SOURCE_SNAPSHOT,
        "remark": "LOCAL-ERP-QA synthetic final fee.",
    }
    return [
        {
            **common,
            "rule_code": "LOCAL_QA_SEA_FREIGHT",
            "logical_fee_key": "international_sea_freight",
            "expense_category": "International sea freight",
            "allocation_basis": "gross_weight",
            "basis_field": "gross_weight_kg",
            "currency": "CNY",
            "amount": 42000,
            "covered_scopes": "freight",
        },
        {
            **common,
            "rule_code": "LOCAL_QA_CUSTOMS_CLEARANCE",
            "logical_fee_key": "customs_clearance_fee",
            "expense_category": "Customs clearance fee",
            "allocation_basis": "goods_value",
            "basis_field": "goods_value",
            "currency": "MXN",
            "amount": 16000,
            "covered_scopes": "customs",
            "priority_no": 20,
        },
        {
            **common,
            "rule_code": "LOCAL_QA_IMPORT_TAX",
            "logical_fee_key": "import_tax",
            "expense_category": "Import tax",
            "allocation_basis": "goods_value",
            "basis_field": "goods_value",
            "currency": "MXN",
            "amount": 24000,
            "covered_scopes": "tax",
            "priority_no": 30,
        },
        {
            **common,
            "rule_code": "LOCAL_QA_DESTINATION_DELIVERY",
            "logical_fee_key": "destination_delivery",
            "expense_category": "Destination delivery",
            "allocation_basis": "gross_weight",
            "basis_field": "gross_weight_kg",
            "currency": "MXN",
            "amount": 8500,
            "covered_scopes": "mexico_inland",
            "priority_no": 40,
        },
    ]


def _local_erp_config() -> dict[str, str]:
    companies = frappe.get_all(
        "Company", fields=["name"], order_by="creation asc", limit_page_length=1
    )
    company = companies[0]["name"] if companies else ""
    if not company:
        raise ValueError("No local ERPNext Company is available.")
    return {
        "company": company,
        "supplier": SUPPLIER_NAME,
        "cost_center": frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name"
        )
        or "",
        "item_group": frappe.db.get_value(
            "Item Group", {"name": "All Item Groups"}, "name"
        )
        or frappe.db.get_value("Item Group", {}, "name"),
        "stock_uom": frappe.db.get_value("UOM", {"name": "Nos"}, "name")
        or frappe.db.get_value("UOM", {}, "name"),
        "default_currency": frappe.db.get_value(
            "Company", company, "default_currency"
        )
        or "CNY",
        "schedule_date": date.today().isoformat(),
    }


def _ensure_supplier(supplier_name: str) -> None:
    if frappe.db.exists("Supplier", supplier_name):
        return
    supplier_group = frappe.db.get_value(
        "Supplier Group", {"name": "All Supplier Groups"}, "name"
    ) or frappe.db.get_value("Supplier Group", {}, "name")
    frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": supplier_name,
            "supplier_group": supplier_group,
        }
    ).insert(ignore_permissions=True)


def _ensure_local_items(payload: dict, config: dict) -> list[str]:
    from overseas_costing.services import erp_client

    names = []
    for item in payload.get("items") or []:
        code = str(item.get("material_code") or "").strip()
        if not code.startswith(ITEM_PREFIX):
            raise ValueError("Refusing to create an Item outside the QA prefix.")
        if frappe.db.exists("Item", code):
            names.append(code)
            continue
        body = erp_client._build_item_body(item, payload, config)
        names.append(
            frappe.get_doc({"doctype": "Item", **body})
            .insert(ignore_permissions=True)
            .name
        )
    return names


def _compare_purchase_order_rows(
    payload: dict, actual_rows: list[dict], config: dict
) -> list[dict]:
    expected_rows = payload.get("items") or []
    if len(expected_rows) != len(actual_rows):
        return [
            {
                "ok": False,
                "field": "item_count",
                "expected": len(expected_rows),
                "actual": len(actual_rows),
            }
        ]

    from overseas_costing.services import erp_client

    checks = []
    for expected, actual in zip(expected_rows, actual_rows, strict=True):
        expected_row = erp_client._build_purchase_order_item(
            expected,
            payload,
            config,
            config["schedule_date"],
        )
        fields = (
            "item_code",
            "qty",
            "rate",
            "custom_overseas_original_unit_price",
            "custom_overseas_comprehensive_unit_price",
            "custom_overseas_original_amount",
            "custom_overseas_comprehensive_amount",
            "custom_overseas_freight_alloc_amount",
            "custom_overseas_clearance_alloc_amount",
            "custom_overseas_tax_alloc_amount",
            "custom_overseas_batch_no",
            "custom_overseas_cost_version",
            "custom_overseas_business_entity",
            "custom_overseas_stable_line_key",
        )
        differences = {}
        for field in fields:
            left = expected_row.get(field)
            right = actual.get(field)
            if not _same_value(left, right):
                differences[field] = {"expected": left, "actual": right}
        checks.append(
            {
                "item_code": actual.get("item_code"),
                "ok": not differences,
                "differences": differences,
            }
        )
    return checks


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        try:
            return round(float(left or 0), 2) == round(float(right or 0), 2)
        except (TypeError, ValueError):
            return False
    return str(left or "") == str(right or "")


def _batch_doc_names() -> list[str]:
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"batch_no": BATCH_NO},
        pluck="name",
        limit_page_length=20,
    )
    return [str(name) for name in rows if str(name)]


def _resolve_batch_name() -> str:
    return str(
        frappe.db.get_value(
            "Overseas Cost Batch", {"batch_no": BATCH_NO}, "name"
        )
        or ""
    )


def _summary(stage: str, batch_name: str, version_name: str) -> dict[str, Any]:
    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_name,
        [
            "name",
            "batch_no",
            "status",
            "confirm_status",
            "current_version",
            "item_count",
            "estimated_total_cost_rmb",
            "actual_total_cost_rmb",
        ],
        as_dict=True,
    )
    return {
        "ok": True,
        "stage": stage,
        "batch": batch,
        "version_name": version_name,
        "item_count": frappe.db.count(
            "Overseas Cost Item",
            {"batch": batch_name, "version": version_name, "is_excluded": 0},
        ),
        "rule_count": frappe.db.count(
            "Overseas Cost Allocation Rule",
            {"batch": batch_name, "version": version_name},
        ),
    }


def _require_frappe() -> None:
    if frappe is None:
        raise RuntimeError("This script must run inside a Frappe bench.")
