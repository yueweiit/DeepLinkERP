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
)


def _item(row_no: int, scenario: str) -> dict:
    row = {fieldname: "" for fieldname in EXCEL_FIELDNAMES}
    quantity = 10 + (row_no % 7)
    unit_price = round(18.5 + (row_no % 11) * 1.75, 2)
    goods_value = round(quantity * unit_price, 2)
    total_cost = round(goods_value * 1.31, 2)
    row.update(
        {
            "material_code": f"LOCAL-SKU-{row_no:04d}-LONG-CODE",
            "product_name": f"本地验收用工业零件第 {row_no} 行（用于验证固定列自动换行）",
            "unit_price": unit_price,
            "quantity": quantity,
            "actual_shipped_qty": quantity,
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
        row.update({"actual_shipped_qty": 0, "gross_weight_kg": 0})
    return row


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
            frappe.get_doc(
                {
                    "doctype": "Overseas Cost Item",
                    "batch": batch_doc.name,
                    "version": version_doc.name,
                    "row_no": index,
                    "excel_row_no": index + 1,
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
