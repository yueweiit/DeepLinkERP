"""Review readiness checks real saved comprehensive-cost results without database writes."""

from copy import deepcopy
import importlib
import json

import pytest

from overseas_costing.services import cost_preview_service, fee_service


def saved_context():
    batch = {"name": "B-1", "current_version": "V-1", "status": "Calculated",
             "confirm_status": "Pending", "subsidiary_code": "MX", "transport_mode": "SEA",
             "estimated_total_cost_rmb": "130.00", "source_status": {"purchase_approval_sync_state": "missing"}}
    values = {"name": "I-1", "row_no": 1, "stable_line_key": "line-1", "material_code": "SKU-1",
              "product_name": "Product", "unit": "件", "purchase_uom": "件", "unit_price_uom": "件",
              "quantity": 10.0, "actual_shipped_qty_mode": "DEFAULT_PURCHASE", "goods_value": 100.0,
              "gross_weight_kg": 0.0, "volume_m3": 0.0}
    items = [{field: values.get(field) for field in cost_preview_service.COST_INPUT_FIELDS}]
    rules = []
    for index, template in enumerate(fee_service.build_default_fee_templates("SEA")):
        values = {**template, "name": f"F-{index}", "batch": "B-1", "version": "V-1",
                  "amount_status": "ACTUAL" if index == 0 else "NOT_INCURRED", "amount": 30.0 if index == 0 else 0.0,
                  "currency": "RMB", "amount_revision": "manual:1", "scope_revision": ""}
        rules.append({field: values.get(field) for field in fee_service._rule_fields()})
    version = {"name": "V-1", "batch": "B-1", "version_code": "EST-001", "status": "Active",
               "fx_usd_to_rmb": 7.0, "fx_rmb_to_mxn": 2.5}
    evidence = []
    context = {"batch": batch, "version": version, "items": items, "fees": rules, "evidence": evidence}
    save_result(context)
    return context


def save_result(context):
    version = context["version"]
    inputs = [{field: row.get(field) for field in cost_preview_service.COST_INPUT_FIELDS} for row in context["items"]]
    fx = {key: version.get(key) for key in ("fx_usd_to_rmb", "fx_rmb_to_mxn")}
    fees = fee_service.compose_fee_worklist_rows(context["fees"], context["batch"]["transport_mode"])
    saved = cost_preview_service.build_saved_cost_data(inputs, fees, fx, context["batch"]["transport_mode"])
    version["calculated_at"] = "2026-09-08 10:00:00"
    saved["summary_snapshot"]["calculated_at"] = version["calculated_at"]
    version["summary_snapshot_json"] = json.dumps(saved["summary_snapshot"])
    for item, update in zip(context["items"], saved["item_updates"]):
        item.update(update)
    context["batch"]["estimated_total_cost_rmb"] = saved["summary"]["total_cost_rmb"]


def evaluate(context):
    return importlib.import_module("overseas_costing.services.cost_review_service").evaluate_review_readiness(**context)


def codes(result):
    return {row["code"] for row in result["review_blockers"]}


def test_current_saved_result_is_ready_with_goods_value_fallback_and_missing_sync_marker():
    context = saved_context()
    before = deepcopy(context)
    result = evaluate(context)
    assert result["review_state"] == "ready"
    assert result["result_is_current"] is True
    assert result["review_blockers"] == []
    assert result["primary_action"] == "review"
    assert {row["code"] for row in result["review_warnings"]} == {"EVIDENCE_MISSING"}
    assert context == before


@pytest.mark.parametrize("confirm_status", ["Pending", "Partially Confirmed"])
def test_latest_estimates_and_missing_evidence_are_review_warnings(confirm_status):
    context = saved_context()
    context["batch"]["confirm_status"] = confirm_status
    context["fees"][0]["amount_status"] = "ESTIMATED"
    save_result(context)
    result = evaluate(context)
    assert result["review_state"] == "ready"
    assert result["result_is_current"] is True
    assert {row["code"] for row in result["review_warnings"]} == {"ESTIMATED_AMOUNT", "EVIDENCE_MISSING"}


@pytest.mark.parametrize("change", ["dirty", "no_snapshot", "legacy", "no_time", "wrong_version", "input_changed", "fx_changed"])
def test_positive_saved_amount_does_not_make_stale_or_unverifiable_results_ready(change):
    context = saved_context()
    if change == "dirty":
        context["batch"]["status"] = "Dirty"
    elif change == "no_snapshot":
        context["version"]["summary_snapshot_json"] = "{}"
    elif change == "legacy":
        context["version"]["summary_snapshot_json"] = '{"total_cost_rmb": "130.00"}'
    elif change == "no_time":
        context["version"]["calculated_at"] = None
    elif change == "wrong_version":
        context["version"]["name"] = "V-2"
    elif change == "input_changed":
        context["items"][0]["goods_value"] = 110.0
    else:
        context["version"]["fx_usd_to_rmb"] = 7.1
    result = evaluate(context)
    assert result["review_state"] == "processing"
    assert result["result_is_current"] is False
    assert result["primary_action"] == "recalculate"


@pytest.mark.parametrize("change, code", [("missing_fee", "AMOUNT_MISSING"), ("fx", "FX_RATE_MISSING"),
    ("currency", "CURRENCY_UNSUPPORTED"), ("scope", "FEE_SCOPE_EMPTY"),
    ("missing_goods", "GOODS_VALUE_MISSING"), ("missing_shipping", "SHIPPING_UNIT_REQUIRED")])
def test_saved_partial_result_with_missing_required_inputs_remains_processing(change, code):
    context = saved_context()
    if change == "missing_fee":
        context["fees"][0]["amount_status"] = "MISSING"
    elif change == "fx":
        context["fees"][0]["currency"] = "USD"
        context["version"]["fx_usd_to_rmb"] = 0
    elif change == "currency":
        context["fees"][0]["currency"] = "EUR"
    elif change == "scope":
        context["fees"][0].update(scope_type="ITEMS", scope_value_json='["other"]')
    elif change == "missing_goods":
        context["items"][0]["goods_value"] = None
    else:
        context["items"][0]["quantity"] = None
    save_result(context)
    result = evaluate(context)
    assert result["review_state"] == "processing"
    assert code in codes(result)


def test_new_duplicate_fee_blocks_review_of_previously_saved_result():
    context = saved_context()
    context["fees"].append({**context["fees"][0], "name": "DUPLICATE"})
    result = evaluate(context)
    assert "DUPLICATE_LOGICAL_FEE" in codes(result)
    assert result["review_state"] == "processing"
    assert result["primary_action"] == "supplement_fees"


@pytest.mark.parametrize("change", ["item_missing", "item_duplicate", "item_total", "fee_missing", "allocation_missing", "allocation_wrong", "summary_total", "stored_item_total"])
def test_saved_allocations_must_cover_items_and_reconcile_with_current_inputs(change):
    context = saved_context()
    snapshot = json.loads(context["version"]["summary_snapshot_json"])
    saved = snapshot["comprehensive_cost"]
    if change == "item_missing":
        saved["items"] = []
    elif change == "item_duplicate":
        saved["items"].append(deepcopy(saved["items"][0]))
    elif change == "item_total":
        saved["items"][0]["total_cost_rmb"] = "129.00"
    elif change == "fee_missing":
        saved["included_fees"] = []
    elif change == "allocation_missing":
        saved["included_fees"][0]["allocations"] = {}
    elif change == "allocation_wrong":
        saved["included_fees"][0]["allocations"]["line-1"] = "29.00"
    elif change == "summary_total":
        snapshot["total_cost_rmb"] = "999.00"
    else:
        context["items"][0]["total_cost_rmb"] = "999.00"
    context["version"]["summary_snapshot_json"] = json.dumps(snapshot)
    result = evaluate(context)
    assert "SAVED_RESULT_INVALID" in codes(result)
    assert result["result_is_current"] is False
    assert result["review_state"] == "processing"


def test_confirmed_history_is_separate_even_when_legacy_snapshot_is_not_current():
    context = saved_context()
    context["batch"].update(confirm_status="Confirmed", status="Confirmed")
    context["version"].update(summary_snapshot_json="{}", confirmed_at="2026-09-08 11:00:00")
    result = evaluate(context)
    assert result["review_state"] == "confirmed"
    assert result["result_is_current"] is False
    assert result["primary_action"] == "view"
    assert result["reviewed_at"] == "2026-09-08 11:00:00"
    assert result["reviewed_version"] == "V-1"


@pytest.mark.parametrize("source_status", [
    {"purchase_approval_sync_state": "unreadable"},
    {"invalid_business": True, "invalid_business_scope": "linked_purchase_approval"},
    {"purchase_approval_sync_state": "partial", "linked_purchase_approvals": [
        {"source_instance_id": "bad", "approval_status": "拒绝"}]}])
def test_invalid_purchase_source_is_a_purchase_blocker(source_status):
    context = saved_context()
    context["batch"]["source_status"] = source_status
    context["items"][0]["dingtalk_instance_id"] = "bad"
    save_result(context)
    result = evaluate(context)
    assert "PURCHASE_SOURCE_INVALID" in codes(result)
    assert result["primary_issue"] == "purchase"


def test_valid_evidence_removes_only_evidence_warning():
    context = saved_context()
    context["fees"][0]["amount_status"] = "ESTIMATED"
    context["evidence"] = [{"fee_rule": "F-0", "evidence_role": "freight_invoice", "validation_status": "VALID"}]
    save_result(context)
    assert {row["code"] for row in evaluate(context)["review_warnings"]} == {"ESTIMATED_AMOUNT"}


def test_partially_invalid_approval_requires_purchase_oa_items_to_reference_a_valid_source():
    context = saved_context()
    context["batch"]["source_status"] = {"purchase_approval_sync_state": "partial", "linked_purchase_approvals": [
        {"source_instance_id": "bad", "approval_status": "拒绝"},
        {"source_instance_id": "good", "approval_status": "已完成"}]}
    context["items"][0].update(source_type="PURCHASE_EXPENSE_OA", dingtalk_instance_id="unverified")
    save_result(context)
    assert "PURCHASE_SOURCE_INVALID" in codes(evaluate(context))
    context["items"][0]["dingtalk_instance_id"] = "good"
    save_result(context)
    assert evaluate(context)["review_state"] == "ready"


def test_changed_inputs_report_staleness_without_claiming_saved_result_is_corrupt():
    context = saved_context()
    context["items"][0]["goods_value"] = 110.0
    assert codes(evaluate(context)) == {"RESULT_STALE"}
