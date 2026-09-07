"""Generate opt-in, local-only workbench acceptance samples."""

from __future__ import annotations

import json
import os

try:
    import frappe
except Exception:  # pragma: no cover - pure builder tests run without Frappe
    frappe = None

from overseas_costing.services.batch_service import EXCEL_FIELDNAMES


SAMPLE_BATCH_NOS = (
    "LOCAL-SAMPLE-PURCHASE-MISSING-1",
    "LOCAL-SAMPLE-LOGISTICS-MISSING-2",
    "LOCAL-SAMPLE-SEA-184-3",
    "LOCAL-SAMPLE-CALCULATED-4",
    "LOCAL-SAMPLE-MATERIAL-GRID-5",
)


def _item(row_no: int, scenario: str) -> dict:
    row = {fieldname: "" for fieldname in EXCEL_FIELDNAMES}
    quantity = 10 + (row_no % 7)
    unit_price = round(18.5 + (row_no % 11) * 1.75, 2)
    goods_value = round(quantity * unit_price, 2)
    total_cost = round(goods_value * 1.31, 2)
    row.update(
        {
            "stable_line_key": f"LOCAL-LINE-{scenario}-{row_no:04d}",
            "material_code": f"LOCAL-SKU-{row_no:04d}-LONG-CODE",
            "product_name": f"本地验收用工业零件第 {row_no} 行（用于验证固定列自动换行）",
            "unit": "件",
            "purchase_uom": "件",
            "unit_price_uom": "件",
            "shipped_uom": "件",
            "cost_output_uom": "件",
            "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
            "unit_price": unit_price,
            "quantity": quantity,
            "actual_shipped_qty": "",
            "goods_value": goods_value,
            "purchase_currency": "RMB",
            "gross_weight_kg": round(8.5 + (row_no % 13) * 0.7, 3),
            "volume_m3": round(0.08 + (row_no % 5) * 0.015, 3),
            "import_name": "工业零部件",
            "hs_code": "8413910000",
            "category": "机械配件",
            "customs_no": f"LOCAL-CUSTOMS-{row_no:04d}",
            "waybill_no": "LOCAL-WAYBILL-SEA-20260902",
            "container_no": "LOCAL-CONT-001",
            "china_misc_rmb": 8.5,
            "china_ocean_usd": 12.0,
            "cc_rate": 7.1,
            "igi_rate": 0.15,
            "igi_amount": round(goods_value * 0.15, 2),
            "iva_rate": 0.16,
            "iva_amount": round(goods_value * 0.16, 2),
            "china_to_mexico_freight_rmb": 85.0,
            "freight_alloc_rmb": 85.0,
            "total_cost_rmb": total_cost if scenario == "calculated" else 0,
            "total_unit_rmb": round(total_cost / quantity, 4) if scenario == "calculated" else 0,
            "project_collection": "LOCAL-QA",
            "transport_mode": "SEA",
        }
    )
    if scenario == "purchase_missing":
        row.update({"unit_price": 0, "purchase_currency": "", "goods_value": 0})
    if scenario == "logistics_missing":
        row.update({"actual_shipped_qty": "", "actual_shipped_qty_mode": "LEGACY_UNVERIFIED", "gross_weight_kg": 0})
    return row


def _acceptance_item(row_no: int, tag: str, **values) -> dict:
    row = {fieldname: "" for fieldname in EXCEL_FIELDNAMES}
    row.update(
        {
            "acceptance_tag": tag,
            "row_no": row_no,
            "stable_line_key": f"LOCAL-MATERIAL-LINE-{row_no}",
            "material_code": f"LOCAL-MATERIAL-{row_no}",
            "product_name": f"本地物料验收 {row_no}",
            "unit": "桶",
            "purchase_uom": "桶",
            "unit_price": 25,
            "unit_price_uom": "桶",
            "purchase_currency": "RMB",
            "quantity": 34,
            "actual_shipped_qty": "",
            "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
            "actual_shipped_qty_source_revision": "",
            "shipped_uom": "桶",
            "cost_output_uom": "桶",
            "goods_value": 850,
            "gross_weight_kg": "",
            "volume_m3": "",
            "project_collection": "LOCAL-生产项目",
            "transport_mode": "SEA",
            "source_doc_no": "LOCAL-OA-MATERIAL-05",
        }
    )
    row.update(values)
    return row


def build_material_grid_acceptance_sample() -> dict:
    """构建只含虚构数据的物料网格验收批次。"""

    items = [
        _acceptance_item(1, "default_purchase_qty"),
        _acceptance_item(
            2,
            "explicit_lower_qty",
            actual_shipped_qty=30,
            actual_shipped_qty_mode="MANUAL_CONFIRMED",
        ),
        _acceptance_item(
            3,
            "kg_price_barrel_shipping",
            material_code="LOCAL-RUBBER-OIL",
            product_name="本地验收橡胶油",
            unit="kg",
            purchase_uom="kg",
            unit_price_uom="kg",
            quantity=612,
            actual_shipped_qty=34,
            actual_shipped_qty_mode="EXPLICIT_SOURCE",
            actual_shipped_qty_source_revision="LOCAL-XLSX-SHA256",
            shipped_uom="桶",
            cost_output_uom="桶",
            goods_value=15300,
        ),
        _acceptance_item(
            5,
            "duplicate_sku_first",
            stable_line_key="LOCAL-DUPLICATE-LINE-A",
            material_code="FL000103",
            source_doc_no="LOCAL-PO-A",
            gross_weight_kg=612,
            volume_m3=1.5337,
        ),
        _acceptance_item(
            6,
            "duplicate_sku_second",
            stable_line_key="LOCAL-DUPLICATE-LINE-B",
            material_code="FL000103",
            source_doc_no="LOCAL-PO-B",
        ),
        _acceptance_item(
            7,
            "missing_weight_and_project",
            material_code="LOCAL-NO-WEIGHT",
            project_collection="",
            gross_weight_kg="",
            volume_m3="",
        ),
    ]
    goods_value = sum(float(row.get("goods_value") or 0) for row in items)
    return {
        "scenario": "material_grid_acceptance",
        "batch": {
            "batch_no": SAMPLE_BATCH_NOS[4],
            "waybill_no": "LOCAL-WAYBILL-MATERIAL-05",
            "transport_mode": "SEA",
            "business_type": "SEA_STANDARD",
            "subsidiary_code": "YUEWEI-MX",
            "source_type": "oa_logistics",
            "source_approval_no": "LOCAL-OA-MATERIAL-05",
            "source_approval_status": "COMPLETED",
            "source_title": "本地验收 OA-only 物料补充批次",
            "source_created_at": "2026-09-05 09:00:00",
            "status": "Dirty",
            "confirm_status": "Pending",
            "writeback_status": "Not Started",
            "item_count": len(items),
            "total_goods_value": round(goods_value, 2),
            "actual_total_cost_rmb": 0,
            "estimated_total_cost_rmb": 0,
            "source_remark": "只有 OA 基础资料，无装箱计划；仅供本地验收",
            "extra_json": json.dumps({"local_acceptance": True, "live_integrations": False}, ensure_ascii=False),
        },
        "items": items,
        "rules": [
            {
                "rule_code": "LOCAL-FREIGHT-BY-GOODS",
                "expense_category": "本地验收国际运费",
                "allocation_basis": "goods_value",
                "basis_field": "goods_value",
                "currency": "RMB",
                "amount": 600,
                "priority_no": 10,
                "remark": "本地虚构费用；按货值分摊时不要求毛重",
                "is_enabled": 1,
                "is_active": 1,
            }
        ],
        "packing_source": None,
        "packing_preview": {
            "groups": [
                {
                    "group_id": "LOCAL-SHARED-BOX-1",
                    "row_numbers": [5, 6],
                    "gross_weight_kg": {"value": "612", "count_once": True},
                    "volume_m3": {"value": "1.5337", "count_once": True},
                    "needs_confirmation": True,
                }
            ],
            "totals": {"gross_weight_kg": "612", "volume_m3": "1.5337"},
        },
    }


def _sample(batch_no: str, scenario: str, item_count: int, day: int) -> dict:
    items = [_item(index, scenario) for index in range(1, item_count + 1)]
    goods_value = sum(float(row.get("goods_value") or 0) for row in items)
    total_cost = sum(float(row.get("total_cost_rmb") or 0) for row in items)
    has_purchase_link = scenario != "purchase_missing"
    trace = {
        "oa_logistics_trace": {
            "linked_purchase_approvals": ([{
                "approval_no": f"LOCAL-PO-{day:02d}",
                "approval_status": "COMPLETED",
                "approval_title": "本地验收采购审批",
            }] if has_purchase_link else [])
        }
    }
    return {
        "scenario": scenario,
        "batch": {
            "batch_no": batch_no,
            "waybill_no": f"LOCAL-WAYBILL-{day:02d}",
            "transport_mode": "SEA",
            "business_type": "SEA_STANDARD",
            "subsidiary_code": "" if scenario == "purchase_missing" else "YUEWEI-MX",
            "source_type": "manual",
            "source_approval_no": f"LOCAL-OA-{day:02d}",
            "source_approval_status": "COMPLETED",
            "source_title": f"本地工作台验收样本 · {scenario}",
            "source_created_at": f"2026-09-{day:02d} 09:00:00",
            "status": "Calculated" if scenario == "calculated" else "Dirty",
            "confirm_status": "Pending",
            "writeback_status": "Not Started",
            "item_count": item_count,
            "total_goods_value": round(goods_value, 2),
            "actual_total_cost_rmb": round(total_cost, 2),
            "estimated_total_cost_rmb": round(total_cost, 2),
            "source_remark": "仅供本地 UI 验收，可重复生成",
            "extra_json": json.dumps(trace, ensure_ascii=False),
        },
        "items": items,
    }


def build_sample_payloads() -> list[dict]:
    """Return deterministic payloads without reading production data."""
    return [
        _sample(SAMPLE_BATCH_NOS[0], "purchase_missing", 6, 2),
        _sample(SAMPLE_BATCH_NOS[1], "logistics_missing", 12, 1),
        _sample(SAMPLE_BATCH_NOS[2], "pending_calculation", 184, 29),
        _sample(SAMPLE_BATCH_NOS[3], "calculated", 8, 30),
        build_material_grid_acceptance_sample(),
    ]


def _delete_existing_sample(batch_no: str) -> None:
    batch_name = frappe.db.get_value("Overseas Cost Batch", {"batch_no": batch_no}, "name")
    if not batch_name:
        return
    for doctype in (
        "Overseas Cost Usage Log",
        "Overseas Cost Audit Log",
        "Overseas Cost Attachment",
        "Overseas Cost Allocation Rule",
        "Overseas Cost Item",
        "Overseas Cost Version",
    ):
        for row in frappe.get_all(doctype, filters={"batch": batch_name}, fields=["name"], limit_page_length=1000):
            frappe.delete_doc(doctype, row["name"], ignore_permissions=True, force=True)
    frappe.delete_doc("Overseas Cost Batch", batch_name, ignore_permissions=True, force=True)


def seed() -> dict:
    if os.environ.get("OVERSEAS_COST_ALLOW_SAMPLE") != "1":
        raise RuntimeError("只允许在显式设置 OVERSEAS_COST_ALLOW_SAMPLE=1 的本地环境生成样本")
    if frappe is None:
        raise RuntimeError("当前未连接 Frappe")

    samples = build_sample_payloads()
    for sample in samples:
        batch_values = sample["batch"]
        batch_no = batch_values["batch_no"]
        if batch_no not in SAMPLE_BATCH_NOS:
            raise RuntimeError(f"拒绝生成未登记的样本批次：{batch_no}")
        _delete_existing_sample(batch_no)
        batch_doc = frappe.get_doc({"doctype": "Overseas Cost Batch", **batch_values}).insert(ignore_permissions=True)
        version_doc = frappe.get_doc(
            {
                "doctype": "Overseas Cost Version",
                "batch": batch_doc.name,
                "version_code": f"LOCAL-QA-{batch_no}",
                "version_type": "Actual" if sample["scenario"] == "calculated" else "Estimated",
                "status": "Active",
                "is_current": 1,
                "source_type": "Manual",
                "remark": "本地工作台验收样本",
            }
        ).insert(ignore_permissions=True)
        for index, values in enumerate(sample["items"], start=1):
            item_values = {key: value for key, value in values.items() if key != "acceptance_tag"}
            frappe.get_doc(
                {
                    "doctype": "Overseas Cost Item",
                    "batch": batch_doc.name,
                    "version": version_doc.name,
                    "row_no": index,
                    "excel_row_no": index + 1,
                    **item_values,
                }
            ).insert(ignore_permissions=True)
        for values in sample.get("rules") or []:
            frappe.get_doc(
                {
                    "doctype": "Overseas Cost Allocation Rule",
                    "batch": batch_doc.name,
                    "version": version_doc.name,
                    **values,
                }
            ).insert(ignore_permissions=True)
        frappe.db.set_value(
            "Overseas Cost Batch",
            batch_doc.name,
            {"current_version": version_doc.name, "version_count": 1, "item_count": len(sample["items"])},
            update_modified=False,
        )
    frappe.db.commit()
    return summary()


def summary() -> dict:
    if frappe is None:
        return {sample["batch"]["batch_no"]: len(sample["items"]) for sample in build_sample_payloads()}
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"batch_no": ["in", SAMPLE_BATCH_NOS]},
        fields=["batch_no", "item_count"],
        order_by="batch_no asc",
        limit_page_length=len(SAMPLE_BATCH_NOS),
    )
    return {row["batch_no"]: int(row.get("item_count") or 0) for row in rows}
