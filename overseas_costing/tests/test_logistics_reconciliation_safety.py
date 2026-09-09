"""Purchase totals and manual corrections survive later shipment row changes."""
from copy import deepcopy
from decimal import Decimal
import json

from overseas_costing.services.logistics_autofill_service import (
    autofill_preview,
    build_logistics_reconciliation,
    selected_carrier,
)


def _source(quantities):
    return {"source_id": "approval:logistics:1", "approval_role": "international_logistics",
            "source_kind": "approval_form", "form_fields": {"货物信息Bienes": [
                {"物料编码": "SKU-A", "物料名称": "A", "数量": quantity, "单位": "个"}
                for quantity in quantities]}}


def _first_saved_rows():
    # This generic flag also appears on ordinary AI confirmations in the real batch.
    items = [{"name": "PURCHASE-1", "stable_line_key": "purchase-line-1", "material_code": "SKU-A",
              "quantity": "100", "goods_value": "1000", "actual_shipped_qty": "100",
              "actual_shipped_qty_mode": "DEFAULT_PURCHASE", "manual_override_flag": 1,
              "manual_override_reason": "AI 资料草稿人工确认", "extra_json": "{}"}]
    rows = build_logistics_reconciliation(items, _source([60, 40]))["payload"]["rows"]
    for index, row in enumerate(rows):
        if row["name"].startswith("draft-"):
            row["name"] = f"SAVED-{index}"
    return rows


def _total(rows, field):
    return sum(Decimal(str(row.get(field) or 0)) for row in rows)


def _metadata(row):
    return json.loads(row["extra_json"])["logistics_row"]


def test_new_shipment_row_conserves_purchase_totals_despite_generic_manual_flag():
    saved = _first_saved_rows()
    before = deepcopy(saved)
    rows = build_logistics_reconciliation(saved, _source([50, 30, 20]))["payload"]["rows"]
    assert _total(rows, "quantity") == 100
    assert _total(rows, "goods_value") == 1000
    assert [Decimal(str(row["goods_value"])) for row in rows] == [500, 300, 200]
    assert [Decimal(str(row["quantity"])) for row in rows] == [50, 30, 20]
    assert saved == before


def test_manual_goods_correction_is_protected_independently_from_quantity():
    saved = _first_saved_rows()
    saved[0].update(goods_value="700", manual_override_flag=0)
    rows = build_logistics_reconciliation(saved, _source([50, 30, 20]))["payload"]["rows"]
    assert _total(rows, "quantity") == 100
    assert _total(rows, "goods_value") == 1100
    assert [Decimal(str(row["quantity"])) for row in rows] == [50, 30, 20]
    assert [Decimal(str(row["goods_value"])) for row in rows] == [700, 240, 160]
    assert _metadata(rows[0])["manual_purchase_fields"] == ["goods_value"]
    assert _metadata(rows[0])["purchase_fact"]["goods_value"] == "1000"
    assert _metadata(rows[0])["allocated_purchase"] == {"quantity": "50.000000", "goods_value": "700"}


def test_manual_quantity_and_goods_corrections_leave_only_remaining_totals_to_allocate():
    saved = _first_saved_rows()
    saved[0].update(quantity="65", goods_value="700", manual_override_flag=0)
    rows = build_logistics_reconciliation(saved, _source([50, 30, 20]))["payload"]["rows"]
    assert [Decimal(str(row["quantity"])) for row in rows] == [65, 24, 16]
    assert [Decimal(str(row["goods_value"])) for row in rows] == [700, 240, 160]
    assert _total(rows, "quantity") == 105
    assert _total(rows, "goods_value") == 1100


def test_same_row_structure_preserves_current_manual_field_and_tracks_it_on_rerun():
    saved = _first_saved_rows()
    saved[0].update(goods_value="700", manual_override_flag=0)
    first = build_logistics_reconciliation(saved, _source([60, 40]))["payload"]["rows"]
    second = build_logistics_reconciliation(first, _source([60, 40]))["payload"]["rows"]
    for rows in (first, second):
        assert [Decimal(str(row["goods_value"])) for row in rows] == [700, 400]
        assert _metadata(rows[0])["manual_purchase_fields"] == ["goods_value"]


def test_legacy_allocations_without_snapshots_preserve_detectable_manual_corrections():
    saved = _first_saved_rows()
    for row in saved:
        metadata = json.loads(row["extra_json"])
        metadata["logistics_row"].pop("allocated_purchase", None)
        metadata["logistics_row"].pop("manual_purchase_fields", None)
        row["extra_json"] = json.dumps(metadata)
    saved[0].update(goods_value="700", manual_override_flag=0)
    rows = build_logistics_reconciliation(saved, _source([50, 30, 20]))["payload"]["rows"]
    assert [Decimal(str(row["goods_value"])) for row in rows] == [700, 240, 160]
    assert _total(rows, "quantity") == 100


def test_second_row_expansion_keeps_corrected_total_and_does_not_copy_manual_protection():
    saved = _first_saved_rows()
    saved[0]["goods_value"] = "700"
    first = build_logistics_reconciliation(saved, _source([50, 30, 20]))["payload"]["rows"]
    for index, row in enumerate(first):
        if row["name"].startswith("draft-"):
            row["name"] = f"ROUND-2-{index}"
    second = build_logistics_reconciliation(first, _source([40, 30, 20, 10]))["payload"]["rows"]
    assert _total(second, "goods_value") == 1100
    assert _total(second, "quantity") == 100
    assert second[0]["goods_value"] == "700"
    assert all(_metadata(row)["manual_purchase_fields"] == [] for row in second[1:])


def test_all_existing_goods_values_corrected_leave_zero_without_duplication_for_new_row():
    saved = _first_saved_rows()
    saved[0]["goods_value"] = "800"
    saved[1]["goods_value"] = "500"
    rows = build_logistics_reconciliation(saved, _source([50, 30, 20]))["payload"]["rows"]
    assert [Decimal(str(row["goods_value"])) for row in rows] == [800, 500, 0]
    assert _total(rows, "goods_value") == 1300
    assert _total(rows, "quantity") == 100


def test_preserved_unmatched_old_row_is_not_counted_twice_in_purchase_allocation():
    saved = _first_saved_rows()
    rows = build_logistics_reconciliation(saved, _source([100]))["payload"]["rows"]
    assert {row["name"] for row in rows} == {row["name"] for row in saved}
    assert _total(rows, "quantity") == 100
    assert _total(rows, "goods_value") == 1000
    assert next(row for row in rows if row["name"] == "SAVED-1")["goods_value"] == saved[1]["goods_value"]


def test_blocked_reconciliation_is_not_used_as_a_modified_preview_base():
    original = [{"name": "I1", "net_weight_kg": "10"}]
    blocked = {"proposal_id": "blocked", "proposal_type": "logistics_reconcile", "blocked": True,
               "default_selected": False, "payload": {"rows": [{"name": "I1", "net_weight_kg": "999"}],
                                                       "unresolved": [{"message": "待核对"}]}}
    preview = autofill_preview(original, [blocked], [])
    assert preview["items"] == original
    assert preview["unresolved"] == [{"message": "待核对"}]


def test_latest_logistics_cancellation_without_carrier_invalidates_old_choice():
    quotes = [{"carrier": "大墨仓"}, {"carrier": "SISA"}]
    old = {"result": "AGREE", "remark": "走大墨仓", "operation_time": "2026-09-04 09:00"}
    for remark in ("取消前面的物流选择，重新询价", "重新询价", "前面的承运人方案作废", "物流报价作废，请重报"):
        current = {"result": "AGREE", "remark": remark, "operation_time": "2026-09-04 10:00"}
        assert selected_carrier(quotes, [old, current]) == "", remark
    unrelated = {"result": "AGREE", "remark": "取消周会", "operation_time": "2026-09-04 10:00"}
    assert selected_carrier(quotes, [old, unrelated]) == "大墨仓"


def test_added_row_never_inherits_manual_shipment_quantity_or_uom_from_retained_row():
    saved = _first_saved_rows()
    saved[0].update(actual_shipped_qty="55", actual_shipped_qty_mode="MANUAL_CONFIRMED", shipped_uom="箱")
    rows = build_logistics_reconciliation(saved, _source([50, 30, 20]))["payload"]["rows"]
    retained = next(row for row in rows if row["name"] == saved[0]["name"])
    added = next(row for row in rows if not row["_existing_name"])
    assert (retained["actual_shipped_qty"], retained["actual_shipped_qty_mode"], retained["shipped_uom"]) == ("55", "MANUAL_CONFIRMED", "箱")
    assert (added["actual_shipped_qty"], added["actual_shipped_qty_mode"], added["shipped_uom"]) == ("20", "EXPLICIT_SOURCE", "个")
    assert _total(rows, "quantity") == 100
    assert _total(rows, "goods_value") == 1000
