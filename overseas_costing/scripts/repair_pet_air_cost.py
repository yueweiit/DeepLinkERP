"""Approved, repeatable repair for one unconfirmed pet-products air shipment.

Run only after downloading attachment sjgvbaphea through the archive service.
The default is a transaction rolled back after all acceptance checks. Pass
apply=True for the authorized production repair. No confirmation or ERP calls.
"""
from __future__ import annotations

import json
from decimal import Decimal

BATCH = "sjgde0rgc3"
VERSION = "sjg4j03827"
ATTACHMENT = "sjgvbaphea"
SHEET = "6月份宠物用品"
REPAIR_KEY = "pet_air_cost_consistency_20260908"
SOURCE_HASH = "e3f37420fe5dc5e2e7d8242dde0eb4547732d9e275facbfbfd7cad2a17f723c6"
OLD_RULE = "ervq0bcq3t"
REPLACEMENTS = ["kncvrfasoh", "kr2rgs4kp1", "ksnvgtu6jt", "kkkqtdhsi6", "ku6kfcagd1"]
# Purchase quantity/value and approved shipping quantity/gross weight/volume.
EXPECTED = {
    "CW000004": (2000, 13900, 2000, "432", "2.1"),
    "CW000014": (2000, 6800, 2000, "130", "1.794375"),
    "CW000012": (2000, 4400, 2000, "60", ".6"),
    "CW000023": (1000, 12300, 990, "242.88", "2.268"),
    "CW000092": (1000, 3400, 1000, "69", ".75"),
}


def number(value):
    return Decimal(str(value or 0))


def equal(value, expected):
    return abs(number(value) - number(expected)) < Decimal("0.00000001")


def validate_items(items, *, physical=False):
    assert len(items) == 5 and {row["material_code"] for row in items} == set(EXPECTED), "本批物料已变化，停止修复。"
    for row in items:
        qty, goods, shipped, gross, volume = EXPECTED[row["material_code"]]
        assert equal(row["quantity"], qty) and equal(row["goods_value"], goods), "采购事实已变化，停止修复。"
        if physical:
            assert equal(row["actual_shipped_qty"], shipped), "发货数量与已确认装箱数据不符。"
            assert equal(row["gross_weight_kg"], gross) and equal(row["volume_m3"], volume), "重量或体积与已确认装箱数据不符。"


def validate_preview(preview):
    assert preview.get("ok") and len(preview["rows"]) == 5, "装箱预览未汇总为 5 条物料。"
    assert not preview.get("out_of_batch"), "存在批次外物料，停止修复。"
    source_rows = set()
    for row in preview["rows"]:
        incoming = row["incoming"]
        code = row.get("material_code") or incoming.get("material_code")
        assert code in EXPECTED and row["match_status"] not in {"unmatched", "choice_required"}, "装箱物料匹配不唯一。"
        _, _, shipped, gross, volume = EXPECTED[code]
        assert equal(incoming.get("actual_shipped_qty"), shipped), "附件数量与已确认口径不符。"
        assert equal(incoming.get("gross_weight_kg"), gross) and equal(incoming.get("volume_m3"), volume), "附件重量或体积与已确认口径不符。"
        source_rows.update(int(v) for v in row.get("source_rows", []))
        assert not row.get("source_conflicts"), "附件来源字段存在冲突，停止修复。"
    assert source_rows == set(range(2, 14)), "附件原始行号已变化，停止修复。"
    assert not (preview.get("source_validation") or {}).get("blocking"), "附件仍有待确认的装箱校验项。"


def run(*, apply=False):
    import frappe
    from overseas_costing.services import cost_preview_service as cost, material_import_service as material
    from overseas_costing.services import edit_session_service, calculate_service

    class TransactionalImport(material.FrappeMaterialImportRepository):
        def assert_write(self, batch_name, edit_token, expected_modified):
            edit_session_service._lock_row(batch_name)
            assert str(frappe.db.get_value("Overseas Cost Batch", batch_name, "modified")) == expected_modified

        def commit(self):
            pass  # One outer transaction owns import + retirement + calculation.

        def rollback(self):
            pass  # Validation returns are handled by the outer transaction.

    repo = TransactionalImport()
    try:
        edit_session_service._lock_row(BATCH)
        batch = frappe.get_doc("Overseas Cost Batch", BATCH)
        assert batch.current_version == VERSION and batch.transport_mode == "AIR", "当前版本或运输方式已变化。"
        assert batch.confirm_status != "Confirmed" and not batch.is_locked, "已确认批次不能修复。"
        repo.lock(BATCH, VERSION)
        version = frappe.get_doc("Overseas Cost Version", VERSION)
        assert version.status not in {"Confirmed", "Archived"}, "历史确认版本不能修复。"
        items = frappe.get_all("Overseas Cost Item", filters={"batch": BATCH, "version": VERSION}, fields=["*"], limit_page_length=100)
        validate_items(items)
        old = frappe.get_doc("Overseas Cost Allocation Rule", OLD_RULE)
        assert old.batch == BATCH and old.version == VERSION and old.rule_code == "oa_logistics_freight" and equal(old.amount, 20360), "被替代费用已变化。"
        for name, amount in zip(REPLACEMENTS, [7000, 5000, 12000, 0, 0]):
            rule = frappe.get_doc("Overseas Cost Allocation Rule", name)
            assert rule.batch == BATCH and rule.version == VERSION and rule.is_enabled and rule.amount_status == "ACTUAL" and equal(rule.amount, amount), "已确认费用已变化。"
        extra = json.loads(batch.extra_json or "{}")
        prior = extra.get(REPAIR_KEY)
        if prior:
            validate_items(items, physical=True)
            assert not old.is_enabled and all(row["transport_mode"] == "AIR" for row in items)
            snapshot = json.loads(version.summary_snapshot_json or "{}")
            assert equal(snapshot.get("total_cost_rmb"), 64800) and batch.status == "Calculated", "修复后的输入或结果已变化，请人工核查。"
            assert equal(sum(number(row["total_cost_rmb"]) for row in items), 64800)
            frappe.db.rollback()
            return {"ok": True, "already_applied": True, "total_cost_rmb": "64800.00", "repair": prior}

        preview = material.preview_material_import(BATCH, "approval_attachment", ATTACHMENT, SHEET, repository=repo)
        assert material.decode_material_preview_revision(preview["preview_revision"])["source_hash"] == SOURCE_HASH, "附件文件已变化，停止修复。"
        validate_preview(preview)
        choices = {"fields": {str(row["source_row"]): {change["field"]: "use_source" for change in row.get("changes", [])} for row in preview["rows"]}}
        expected_modified = repo.get_context(BATCH)["batch_modified"]
        imported = material.apply_material_import(BATCH, preview["preview_revision"], choices, "approved-repair", expected_modified, repository=repo)
        if imported.get("code") == "MERGED_PREVIEW_CONFIRMATION_REQUIRED":
            validate_preview(imported["merged_preview"])
            choices["merged_preview_hash"] = imported["merged_preview_hash"]
            imported = material.apply_material_import(BATCH, preview["preview_revision"], choices, "approved-repair", expected_modified, repository=repo)
        assert imported.get("ok"), f"装箱导入失败：{imported}"
        frappe.db.set_value("Overseas Cost Allocation Rule", OLD_RULE, {"is_enabled": 0,
            "remark": (old.remark or "") + f"\n[{REPAIR_KEY}] 已由当前录入费用替代，保留来源，不再计费。"})
        for row in items:
            assert row.get("source_type") == "PURCHASE_EXPENSE_OA" and row.get("transport_mode") in {"SEA", "AIR"}, "运输来源与已核实记录不符。"
            raw = json.loads(row.get("raw_excel_json") or "{}")
            assert not any(raw.get(key) for key in ("transport_mode", "transportMode", "运输方式")), "存在明确运输来源冲突。"
            if row["transport_mode"] != "AIR":
                frappe.db.set_value("Overseas Cost Item", row["name"], "transport_mode", "AIR")
        now = frappe.utils.now()
        repair = {"at": now, "version": VERSION, "attachment": ATTACHMENT,
                  "sheet": SHEET, "source_hash": material.decode_material_preview_revision(preview["preview_revision"])["source_hash"],
                  "retired_rule": OLD_RULE, "replaced_by": REPLACEMENTS,
                  "transport_repaired": [row["name"] for row in items if row["transport_mode"] != "AIR"]}
        extra[REPAIR_KEY] = repair
        frappe.db.set_value("Overseas Cost Batch", BATCH, "extra_json", json.dumps(extra, ensure_ascii=False))
        calculated = cost.calculate_comprehensive_cost(BATCH, VERSION, trusted=True, commit_after_calculate=False)
        assert calculated["summary"]["is_complete"] and equal(calculated["summary"]["total_cost_rmb"], 64800), "总成本验收失败。"
        assert equal(calculated["summary_snapshot"]["fee_pool_rmb"], 24000), "有效费用合计验收失败。"
        after = frappe.get_all("Overseas Cost Item", filters={"batch": BATCH, "version": VERSION}, fields=["*"], limit_page_length=100)
        validate_items(after, physical=True)
        assert equal(sum(number(row["total_cost_rmb"]) for row in after), 64800)
        assert all(row["transport_mode"] == "AIR" for row in after)
        current = frappe.get_doc("Overseas Cost Batch", BATCH)
        assert current.confirm_status == batch.confirm_status and current.writeback_status == batch.writeback_status
        calculate_service._insert_audit_log(batch_doc_name=BATCH, version_name=VERSION, action_type="BATCH_EDIT",
            action_remark=json.dumps({"repair": REPAIR_KEY, **repair}, ensure_ascii=False))
        result = {"ok": True, "applied": bool(apply), "batch": BATCH, "version": VERSION,
                  "total_cost_rmb": "64800.00", "goods_value_rmb": "40800.00", "fee_total_rmb": "24000.00",
                  "gross_weight_kg": "933.88", "volume_m3": "7.512375", "backpack_shipped_qty": 990,
                  "confirm_status": current.confirm_status, "writeback_status": current.writeback_status, "repair": repair}
        frappe.db.commit() if apply else frappe.db.rollback()
        return result
    except Exception:
        frappe.db.rollback()
        raise
