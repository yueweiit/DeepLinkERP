"""Regression: observed archived approval 202609032107000062462 (2026-09-09)."""
from copy import deepcopy
from decimal import Decimal
import json

from overseas_costing.scripts.import_oa_logistics import extract_logistics_quote_candidates_from_approval

QUOTES = """计费重量预估875.7kg/350=2.502立方
大墨仓报价：3100元/立方（1:350），2.502立方费用：7756.2元
SISA报价：3420元/立方（1:300），2.919立方费用：9982.98元
重量 重量占比 ¥7,756.20
超队1.0项目 668.7kg 76.36% ¥5,922.77
亮甲2.0项目 77kg 8.79% ¥520.79
TK宠物用品项目130kg 14.85% ¥77.31
875.7 100%"""
GOODS = [("FL000429", 96000), ("FL000429", 4000), ("FL000427", 4000),
         ("FL000427", 96000), ("FL000428", 100000), ("FL000430", 100000),
         ("FL003377", 22000), ("CW000191", 2400)]

def approval():
    return {"source_kind": "approval_form", "source_id": "approval:LOG-6262:form",
            "process_instance_id": "LOG-6262", "approval_no": "202609032107000062462",
            "approval_role": "international_logistics", "source_label": "国际物流正文",
            "form_fields": {"货物信息Bienes": [
                {"物料编码": code, "物料名称": code, "数量": qty, "单位": "个"}
                for code, qty in GOODS], "重量Peso（KG）": 875.7, "物流报价": QUOTES},
            "approval_decisions": [{"remark": "走大墨仓", "operation_result": "AGREE",
                                    "operation_time": "2026-09-04 09:45", "user_name": "审批人"}]}

def existing_items():
    return [{"name": f"ITEM-{code}", "material_code": code, "quantity": qty,
             "actual_shipped_qty": qty, "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
             "goods_value": value, "source_doc_no": "PURCHASE-1", "purchase_uom": "个",
             "source_type": "PURCHASE_EXPENSE_OA", "extra_json": "{}"}
            for code, qty, value in [("FL000427", 100000, 15100), ("FL000428", 100000, 15100),
                                     ("FL000429", 100000, 15100), ("FL000430", 100000, 15100),
                                     ("FL003377", 200000, 26000)]]

def test_quote_rate_and_total_on_same_line():
    rows = extract_logistics_quote_candidates_from_approval(approval())
    assert [(r["carrier"], r["amount"]) for r in rows] == [("大墨仓", 7756.2), ("SISA", 9982.98)]
    assert [r["unit_rate"] for r in rows] == [3100, 3420]

def test_logistics_rows_keep_duplicates_missing_purchase_and_purchase_totals():
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    original = existing_items()
    before = deepcopy(original)
    proposal = build_logistics_reconciliation(original, approval())
    rows = proposal["payload"]["rows"]
    assert [(r["material_code"], int(Decimal(str(r["actual_shipped_qty"])))) for r in rows] == GOODS
    assert len({r["stable_line_key"] for r in rows}) == 8
    assert sum(Decimal(str(r.get("goods_value") or 0)) for r in rows) == Decimal("86400")
    assert sum(Decimal(str(r.get("quantity") or 0)) for r in rows) == Decimal("600000")
    assert rows[-1].get("quantity") is None and rows[-1].get("goods_value") is None
    assert original == before
    assert proposal["default_selected"] is True
    assert json.loads(rows[0]["extra_json"])["logistics_row"]["purchase_fact"]["quantity"] == 100000

def test_reconcile_again_does_not_split_or_multiply_purchase_facts():
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    first = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    second = build_logistics_reconciliation(first, approval())["payload"]["rows"]
    assert [(r["stable_line_key"], r["quantity"], r["goods_value"]) for r in second] == [
        (r["stable_line_key"], r["quantity"], r["goods_value"]) for r in first]

def test_carrier_decision_selects_final_freight_without_choosing_cheapest():
    from overseas_costing.services.material_ai_fill_service import build_approval_fee_proposals
    rows = build_approval_fee_proposals(approval(), transport_mode="SEA", existing_fees=[
        {"logical_fee_key": "international_sea_freight", "amount_status": "ACTUAL", "amount": 2004}])
    assert len(rows) == 1
    assert Decimal(rows[0]["payload"]["amount"]) == Decimal("7756.20")
    assert rows[0]["default_selected"] is True
    source = approval()
    source["approval_decisions"][0]["remark"] = "走SISA"
    rows = build_approval_fee_proposals(source, transport_mode="SEA")
    assert len(rows) == 1 and Decimal(rows[0]["payload"]["amount"]) == Decimal("9982.98")

def test_browser_cannot_edit_logistics_reconciliation_payload():
    from overseas_costing.services.material_ai_fill_service import validate_source_review_application
    import pytest
    with pytest.raises(ValueError, match="物流行"):
        validate_source_review_application([
            {"proposal_id": "R", "proposal_type": "logistics_reconcile", "payload": {"rows": []}}],
            ["R"], {"R": {"rows": [{"material_code": "FORGED"}]}}, [])

def test_supplement_budget_interrupts_even_when_inner_code_catches_exception():
    import time
    from overseas_costing.services.logistics_autofill_service import run_supplement
    def slow():
        try:
            time.sleep(0.2)
        except Exception:
            return {"ok": True}
    start = time.monotonic()
    result = run_supplement(slow, seconds=0.01)
    assert result["ok"] is False and "超时" in result["warning"]
    assert time.monotonic() - start < 0.15

def test_comment_reads_server_manifest_without_reloading_approval(monkeypatch):
    from overseas_costing.services import material_ai_fill_service as service, packing_source_service
    def unexpected(*args, **kwargs):
        raise AssertionError("must not reload complete approval")
    monkeypatch.setattr(packing_source_service, "_find_comment_source", unexpected)
    _, document = service._read_source([], {"source_kind": "approval_comment", "comment_text": "走大墨仓"})
    assert document["text"] == "走大墨仓"

def test_worker_previews_eight_rows_and_final_freight_without_business_write(monkeypatch):
    from overseas_costing.services import material_ai_fill_service as service
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    repo = _LifecycleRepository(status="QUEUED")
    repo.sources = [approval()]
    repo.get_items = lambda *args: existing_items()
    repo.get_context = lambda *args: {"batch": "B1", "version": "V1", "transport_mode": "SEA"}
    manifest = prepare_source_manifest(repo.sources)
    repo.run.update(proposal_version=1, source_manifest_json=manifest,
                    input_fingerprint=service._source_review_fingerprint(
                        "B1", "V1", existing_items(), manifest, "", context=repo.get_context("B1", "V1")))
    monkeypatch.setattr(service, "_call_source_review_ai", lambda *args, **kwargs: {"ok": False, "proposals": [], "warning": "AI 不可用"})
    result = service.execute_material_ai_fill("RUN-1", repository=repo)
    assert result["status"] == "READY", repo.run.get("error_message")
    preview = repo.run["draft_json"]["autofill_preview"]
    assert len(preview["items"]) == 8
    assert Decimal(preview["fees"][0]["amount"]) == Decimal("7756.20")
    assert repo.applied == []

def test_packing_matches_duplicate_sku_by_shipping_quantity():
    from overseas_costing.services.material_ai_fill_service import _projection_candidates
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    items = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    preview = {"material_rows": [{"source_row": 3, "material_code": "FL000429", "quantity": 96000, "gross_weight_kg": 96},
                                  {"source_row": 4, "material_code": "FL000429", "quantity": 4000, "gross_weight_kg": 4}], "groups": []}
    result = _projection_candidates(items, {"source_id": "X", "source_kind": "approval_attachment"}, preview)
    gross = [r for r in result if r["fieldname"] == "gross_weight_kg"]
    assert [(r["item_name"], Decimal(str(r["suggested_value"]))) for r in gross] == [(items[0]["name"], Decimal(96)), (items[1]["name"], Decimal(4))]


def test_manual_aggregate_shipping_is_not_copied_to_two_split_rows():
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    items = existing_items()
    items[2].update(actual_shipped_qty_mode="MANUAL_CONFIRMED", actual_shipped_qty=100000)
    proposal = build_logistics_reconciliation(items, approval())
    assert proposal["default_selected"] is False
    assert proposal["payload"]["unresolved"]
    assert proposal["payload"]["rows"] == items


def test_reanalysis_preserves_manual_purchase_correction_after_split():
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    rows = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    rows[0].update(goods_value=20000, manual_override_flag=1)
    again = build_logistics_reconciliation(rows, approval())["payload"]["rows"]
    assert again[0]["goods_value"] == 20000


def test_negated_or_cancelled_carrier_decisions_are_not_adopted():
    from overseas_costing.services.logistics_autofill_service import selected_carrier
    quotes = [{"carrier": "大墨仓"}, {"carrier": "SISA"}]
    for remark in ["不走大墨仓", "不采用大墨仓", "暂不选择SISA", "走大墨仓的方案取消"]:
        assert selected_carrier(quotes, [{"result": "AGREE", "remark": remark}]) == ""


def test_apply_reconciliation_preserves_names_and_stable_ids_without_committing():
    from types import SimpleNamespace
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation, apply_reconciliation
    items = existing_items()
    for row in items:
        row["stable_line_key"] = "stable-" + row["name"]
    proposal = build_logistics_reconciliation(items, approval())
    writes, inserts = [], []
    class Doc:
        def __init__(self, payload):
            self.payload = payload
            self.name = "NEW-" + str(len(inserts))
        def insert(self, **kwargs):
            inserts.append(self.payload)
            return self
    fake = SimpleNamespace(db=SimpleNamespace(set_value=lambda *args, **kwargs: writes.append(args)), get_doc=Doc)
    created = apply_reconciliation(fake, proposal, batch="B1", version="V1", current=items, run_id="R1")
    assert len(created) == 3
    updates = [args for args in writes if args[0] == "Overseas Cost Item"]
    assert {args[1] for args in updates} == {row["name"] for row in items}
    assert all(args[2]["stable_line_key"] == "stable-" + args[1] for args in updates)
    assert all(row["actual_shipped_qty_mode"] == "EXPLICIT_SOURCE" for row in inserts)


def test_real_archived_excel_rows_and_one_shared_carton_are_read_independently():
    """Minimal exact cell fixture from archived 9.4日指环扣双清 (2026-09-09)."""
    from overseas_costing.services.packing_parse_service import parse_packing_grid
    from overseas_costing.services.material_ai_fill_service import _projection_candidates
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    headers = ["品目编码Item code", "中文品名 Chinese Name", "申报单位", "总个数 The total number of", "总净重", "总毛重Gross weight", "总体积total capacity", "件数Number of pieces"]
    physical = [(380,388,.4002,20),(9,9.7,.00864,1),(0,0,0,None),(31.2,32,.032016,4),
                (145,150,.0828,10),(85,89,.04071,5),(76,77,.16687,2),(125,130,.507375,5)]
    raw = [headers] + [[code, code, "个", qty, *values] for (code, qty), values in zip(GOODS, physical)]
    grid = {"cells": [[{"raw_value": value, "display_value": str(value) if value is not None else ""} for value in row] for row in raw],
            "merge_ranges_available": True, "merge_ranges": [{"start_row":3,"end_row":4,"start_column":8,"end_column":8}]}
    preview = parse_packing_grid(grid)
    items = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    candidates = _projection_candidates(items, {"source_id":"real-xlsx","source_kind":"approval_attachment"}, preview)
    gross = [Decimal(str(row["suggested_value"])) for row in candidates if row["fieldname"] == "gross_weight_kg"]
    assert gross == [Decimal(str(row[1])) for row in physical]
    assert sum(gross) == Decimal("875.7")
    boxes = [Decimal(str(row["suggested_value"])) for row in candidates if row["fieldname"] == "package_count"]
    assert sum(boxes) == 47  # T3:T4 is one carton, not two.


def test_transaction_rolls_back_row_reconciliation_when_fee_write_fails(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from overseas_costing.services import material_ai_fill_service as service, fee_service
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    original = existing_items()
    state = {"items": deepcopy(original), "rollbacks": 0, "commits": 0, "writes": 0}
    class DB:
        def sql(self, query, *args, **kwargs):
            return [{"name": "B1", "current_version": "V1"}] if "current_version" in query else []
        def set_value(self, doctype, name, *args, **kwargs):
            state["writes"] += 1
            if doctype == "Overseas Cost Item":
                next(row for row in state["items"] if row["name"] == name).update(args[0])
        def rollback(self):
            state["items"] = deepcopy(original)
            state["rollbacks"] += 1
        def commit(self):
            state["commits"] += 1
    class Doc:
        def __init__(self, values):
            self.values = values
            self.name = "NEW-" + str(len(state["items"]))
        def insert(self, **kwargs):
            state["items"].append({**self.values, "name": self.name})
            return self
    monkeypatch.setattr(service, "frappe", SimpleNamespace(db=DB(), get_all=lambda *a, **kw: deepcopy(state["items"]), get_doc=Doc))
    monkeypatch.setattr(fee_service, "_query_rules", lambda *args: [])
    monkeypatch.setattr(fee_service, "normalize_fee_payload", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("fee failed")))
    proposals = [build_logistics_reconciliation(original, approval()), {"proposal_type": "fee_update", "payload": {"amount": "7756.20"}}]
    with pytest.raises(ValueError, match="fee failed"):
        service.FrappeMaterialAIFillRepository().apply_source_review(SimpleNamespace(name="R1"), proposals, [], {"batch": "B1", "version": "V1"})
    assert state["items"] == original
    assert state["writes"] > 0 and state["rollbacks"] == 1 and state["commits"] == 0


def test_main_approval_archived_labelled_text_preserves_all_eight_rows():
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    source = approval()
    source["form_fields"]["货物信息Bienes"] = "\n".join(
        f"物料编码 Código de material：{code}；物料名称（中文）Nombre del material (chino)：指环扣；规格型号Especificación / Modelo：超队；数量Cantidad：{qty}；单位Unidad：个"
        for code, qty in GOODS)
    rows = build_logistics_reconciliation(existing_items(), source)["payload"]["rows"]
    assert [(row["material_code"], int(row["actual_shipped_qty"])) for row in rows] == GOODS


def test_duplicate_sku_quantity_mismatch_is_not_forced_by_position():
    from overseas_costing.services.material_ai_fill_service import _projection_candidates
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    items = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    preview = {"material_rows": [{"source_row":2,"material_code":"FL000429","quantity":60000,"gross_weight_kg":60},
                                 {"source_row":3,"material_code":"FL000429","quantity":40000,"gross_weight_kg":40}]}
    assert _projection_candidates(items, {"source_id":"X"}, preview) == []
    assert len(preview["autofill_warnings"]) == 2


def test_stalled_status_exposes_retry_even_when_revision_is_unchanged(monkeypatch):
    from overseas_costing.services import material_ai_fill_service as service
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    repo = _LifecycleRepository(status="RUNNING")
    repo.run["modified"] = "2026-09-09 12:00:00"
    monkeypatch.setattr(service, "_now", lambda: "2026-09-09 12:04:00")
    result = service.get_material_ai_fill_status("B1", "RUN-1", after_revision=3, repository=repo)
    assert result["stalled"] is True
    assert result["unchanged"] is False
    assert result["status"] == "RUNNING"  # Status reads don't mutate runs.
