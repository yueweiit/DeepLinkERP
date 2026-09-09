"""Packing price evidence and per-shipment valuation, independent of purchase totals."""

from copy import deepcopy
from decimal import Decimal
import importlib
import json

import pytest

from overseas_costing.services.packing_grid import build_grid_from_dingtalk_snapshot
from overseas_costing.services.packing_parse_service import parse_packing_grid


def _preview(rows, headers=None, **snapshot):
    headers = headers or ["物料编码", "数量", "申报单位", "单价 unit price", "总价（RMB)", "项目归属"]
    return parse_packing_grid(build_grid_from_dingtalk_snapshot({
        "schemaVersion": 1, "sheetName": "装箱", "values": [headers, *rows],
        "mergeRangesAvailable": True, **snapshot,
    }))


def _item(index=1, *, qty=10, price=None, uom="个", currency="RMB", **extra):
    metadata = {"logistics_row": {"purchase_key": "PUR-1:row-1", "purchase_fact": {
        "unit_price": price, "purchase_currency": currency, "purchase_uom": None,
        "source_doc_no": "PUR-1", "quantity": 100000, "goods_value": 15100,
    }}} if price is not None else {}
    return {"name": f"ITEM-{index}", "stable_line_key": f"stable-{index}",
            "material_code": "REPEATED-SKU", "actual_shipped_qty": qty, "unit": uom,
            "unit_price": price, "purchase_currency": currency,
            "extra_json": json.dumps(metadata, ensure_ascii=False), **extra}


def _build(items, preview):
    assert importlib.util.find_spec("overseas_costing.services.shipment_valuation_service"), "valuation service is required"
    module = importlib.import_module("overseas_costing.services.shipment_valuation_service")
    return module.build_shipment_valuations(items, preview, {
        "source_id": "attachment:packing", "source_hash": "sha256-fixture", "sheet_name": "装箱",
    })


def _match(preview, items):
    for row, item in zip(preview["material_rows"], items):
        row["_target_stable_line_key"] = item["stable_line_key"]
    return preview


def test_parser_keeps_price_currency_and_resolved_cell_evidence():
    preview = _preview([["FL001", 2400, "个", 4.4, 10560, "TK宠物用品项目"]],
                       formulas=[[], [None, None, None, None, "=B2*D2"]])
    row = preview["material_rows"][0]
    assert row.get("unit_price") == "4.4"
    assert row.get("total_amount") == "10560"
    assert row.get("currency") == "RMB"
    assert row["unit"] == "个" and row["quantity"] == "2400"
    assert row["project_collection"] == "TK宠物用品项目"
    evidence = row["field_evidence"]["total_amount"]
    assert evidence["raw_value"] == evidence["cached_value"] == 10560
    assert evidence["formula"] == "=B2*D2"
    assert evidence["cache_status"] == "available"
    assert evidence["range"] == row["field_ranges"]["total_amount"]
    assert row["currency_evidence"]["kind"] == "header"
    assert row["currency_evidence"]["label"] == "总价（RMB)"


def test_parser_never_uses_price_as_unit_or_total_price_as_quantity():
    preview = _preview([["FL001", "Item", 3, 30]],
                       ["item code", "product name", "unit price", "total price"])
    row = preview["material_rows"][0]
    assert row.get("unit_price") == "3"
    assert row.get("total_amount") == "30"
    assert row["unit"] is None
    assert row["quantity"] is None
    assert row.get("currency") is None


def test_parser_currency_column_is_explicit_and_formula_cache_is_not_zero():
    preview = _preview([["FL001", 10, "个", 2, None, "USD"]],
                       ["物料编码", "数量", "单位", "单价", "总价", "币种"],
                       formulas=[[], [None, None, None, None, "=B2*D2"]])
    row = preview["material_rows"][0]
    assert row.get("currency") == "USD"
    assert row.get("total_amount") is None
    assert row["field_evidence"]["total_amount"]["cache_status"] == "missing"
    assert row["field_evidence"]["total_amount"]["cached_value"] is None
    assert any(w["code"] == "unresolved_valuation_formula" for w in preview["validation"]["warnings"])


def test_parser_preserves_real_amount_merge_origin_without_inventing_blank_fill():
    preview = _preview([["FL001", 10, "个", 2, 40, "项目"],
                        ["FL002", 10, "个", None, None, "项目"],
                        ["FL003", 10, "个", None, None, "项目"]],
                       mergeRanges=[{"startRow": 2, "endRow": 3, "startColumn": 5, "endColumn": 5}])
    first, second, third = preview["material_rows"]
    assert second.get("total_amount") == "40"
    assert second["field_evidence"]["total_amount"]["row"] == 2
    assert second["field_ranges"]["total_amount"]["end_row"] == 3
    assert third.get("total_amount") is None
    assert second.get("unit_price") is None


def test_packing_total_uses_shipped_quantity_preserves_purchase_fields_and_projects():
    items = [_item(qty=22000, price="0.13"), _item(2, qty=2400)]
    preview = _match(_preview([["FL003377", 22000, "个", .13, 2860, "亮甲2.0项目"],
                               ["CW000191", 2400, "个", 4.4, 10560, "TK宠物用品项目"]]), items)
    before = deepcopy((items, preview))
    result = _build(items, preview)
    assert {name: value["amount_rmb"] for name, value in result["valuations"].items()} == {
        "ITEM-1": "2860", "ITEM-2": "10560"}
    value = result["valuations"]["ITEM-1"]
    assert value["method"] == "packing_row_total"
    assert value["quantity"] == "22000" and value["unit_price"] == "0.13"
    assert value["currency"] == "RMB" and value["uom"] == "个"
    assert value["source_hash"] == "sha256-fixture"
    assert value["source_refs"][0]["source_id"] == "attachment:packing"
    assert value["input_evidence"]["actual_shipped_qty"] == "22000"
    assert value["input_evidence"]["stable_line_key"] == "stable-1"
    assert result["projects"] == {"ITEM-1": "亮甲2.0项目", "ITEM-2": "TK宠物用品项目"}
    assert (items, preview) == before


def test_packing_price_can_calculate_only_with_explicit_currency_and_units():
    items = [_item(qty=10)]
    preview = _match(_preview([["FL001", 10, "pcs", 2, None, "项目"]]), items)
    result = _build(items, preview)
    assert result["valuations"]["ITEM-1"]["amount_rmb"] == "20"
    assert result["valuations"]["ITEM-1"]["method"] == "packing_unit_price"


def test_purchase_price_fallback_splits_repeated_codes_by_stable_key():
    items = [_item(qty=96000, price="0.151"), _item(2, qty=4000, price="0.151")]
    preview = _match(_preview([["FL000429", 96000, "个", None, None, "项目"],
                               ["FL000429", 4000, "个", None, None, "项目"]]), items)
    preview["material_rows"].reverse()
    result = _build(items, preview)
    assert {key: value["amount_rmb"] for key, value in result["valuations"].items()} == {
        "ITEM-1": "14496", "ITEM-2": "604"}
    assert all(value["method"] == "purchase_unit_price" for value in result["valuations"].values())
    assert result["valuations"]["ITEM-1"]["input_evidence"]["purchase_fact"]["unit_price"] == "0.151"


@pytest.mark.parametrize("case,warning", [
    ("wrong_currency", "USD"), ("unknown_currency", "币种"),
    ("missing_unit", "单位"), ("unit_mismatch", "单位"),
    ("quantity_mismatch", "数量"), ("missing_formula_cache", "缓存"),
    ("invalid_total", "不一致"), ("not_matched", "匹配"),
])
def test_unproven_values_remain_unavailable_with_specific_warning(case, warning):
    items = [_item()]
    preview = _match(_preview([["FL001", 10, "个", 2, 20, "项目"]]), items)
    row = preview["material_rows"][0]
    if case == "wrong_currency":
        row["currency"] = "USD"
    elif case == "unknown_currency":
        row["currency"] = None
        row["currency_evidence"] = None
    elif case == "missing_unit":
        row["unit"] = None
    elif case == "unit_mismatch":
        row["unit"] = "箱"
    elif case == "quantity_mismatch":
        items[0]["actual_shipped_qty"] = 11
    elif case == "missing_formula_cache":
        row["total_amount"] = None
        row["field_evidence"]["total_amount"].update(
            formula="=B2*D2", raw_value=None, cached_value=None, cache_status="missing")
    elif case == "invalid_total":
        row["total_amount"] = "30"
    elif case == "not_matched":
        row.pop("_target_stable_line_key")
    result = _build(items, preview)
    assert result["valuations"] == {}
    assert any(warning in message for message in result["warnings"])


@pytest.mark.parametrize("change,warning", [
    ({"purchase_currency": "USD"}, "USD"),
    ({"purchase_currency": None}, "币种"),
    ({"unit_price_uom": "箱"}, "单位"),
    ({"unit_price": None}, "单价"),
])
def test_purchase_fallback_requires_linked_price_currency_and_compatible_unit(change, warning):
    items = [_item(price=2)]
    metadata = json.loads(items[0]["extra_json"])
    metadata["logistics_row"]["purchase_fact"].update(change)
    items[0]["extra_json"] = json.dumps(metadata)
    preview = _match(_preview([["FL001", 10, "个", None, None, "项目"]]), items)
    result = _build(items, preview)
    assert result["valuations"] == {}
    assert any(warning in message for message in result["warnings"])


def test_existing_confirmed_manual_valuation_survives_reparse_unchanged():
    manual = {"amount_rmb": "99", "quantity": "10", "uom": "个", "currency": "RMB",
              "method": "manual", "manual_override_flag": 1, "confirmed": True, "note": "已核对"}
    items = [_item(extra_json=json.dumps({"shipment_valuation": manual}))]
    preview = _match(_preview([["FL001", 10, "个", 2, 20, "项目"]]), items)
    result = _build(items, preview)
    assert result["valuations"]["ITEM-1"] == manual
    assert json.loads(items[0]["extra_json"])["shipment_valuation"] == manual


def _grouped_case():
    quantities = [96000, 4000, 4000, 96000, 100000, 100000, 22000, 2400]
    codes = ["FL000429", "FL000429", "FL000427", "FL000427", "FL000428", "FL000430", "FL003377", "CW000191"]
    items = [_item(index, qty=qty, price="0.151" if index <= 6 else "0.13" if index == 7 else None,
                   material_code=code) for index, (code, qty) in enumerate(zip(codes, quantities), 1)]
    rows = [[code, qty, "个", ".604" if index == 1 else ".13" if index == 7 else "4.4" if index == 8 else None,
             60400 if index == 1 else 2860 if index == 7 else 10560 if index == 8 else None,
             "超队1.0项目" if index <= 6 else "亮甲2.0项目" if index == 7 else "TK宠物用品项目"]
            for index, (code, qty) in enumerate(zip(codes, quantities), 1)]
    return items, _match(_preview(rows), items)


def test_set_price_only_controls_independently_valued_six_row_project_and_total_73820():
    items, preview = _grouped_case()
    result = _build(items, preview)
    values = result["valuations"]
    assert [values[item["name"]]["amount_rmb"] for item in items] == [
        "14496", "604", "604", "14496", "15100", "15100", "2860", "10560"]
    assert sum(Decimal(value["amount_rmb"]) for value in values.values()) == Decimal("73820")
    for item in items[:6]:
        valuation = values[item["name"]]
        assert valuation["unit_price"] == "0.151"
        control = valuation["input_evidence"].get("group_control")
        assert control is not None
        assert control["amount_rmb"] == "60400" and control["role"] == "control_only"
        assert control["verified_row_numbers"] == [2, 3, 4, 5, 6, 7]
        assert control["source_range"]["start_row"] == control["source_range"]["end_row"] == 2
    assert result["projects"]["ITEM-8"] == "TK宠物用品项目"
    assert result["warnings"] == []


@pytest.mark.parametrize("change", ["different_project", "missing_purchase_fact", "wrong_purchase_price"])
def test_set_total_never_infers_a_group_without_independent_purchase_evidence(change):
    items, preview = _grouped_case()
    if change == "different_project":
        preview["material_rows"][3]["project_collection"] = "另一项目"
    elif change == "missing_purchase_fact":
        items[2]["extra_json"] = "{}"
    else:
        metadata = json.loads(items[2]["extra_json"])
        metadata["logistics_row"]["purchase_fact"]["unit_price"] = ".2"
        items[2]["extra_json"] = json.dumps(metadata)
    result = _build(items, preview)
    assert all(not value["input_evidence"].get("group_control") for value in result["valuations"].values())
    assert all(value["amount_rmb"] != "60400" for value in result["valuations"].values())
    assert any("控制" in message for message in result["warnings"])


def test_real_merged_total_cannot_be_reused_as_each_rows_total():
    items = [_item(), _item(2)]
    preview = _match(_preview([["FL001", 10, "个", 2, 20, "项目"],
                               ["FL002", 10, "个", 2, None, "项目"]],
                              mergeRanges=[{"startRow": 2, "endRow": 3, "startColumn": 5, "endColumn": 5}]), items)
    result = _build(items, preview)
    assert result["valuations"] == {}
    assert any("合并" in message for message in result["warnings"])


def test_real_merged_price_is_not_replicated_onto_each_component():
    items = [_item(), _item(2)]
    preview = _match(_preview([["FL001", 10, "个", 2, None, "项目"],
                               ["FL002", 10, "个", None, None, "项目"]],
                              mergeRanges=[{"startRow": 2, "endRow": 3, "startColumn": 4, "endColumn": 4}]), items)
    result = _build(items, preview)
    assert result["valuations"] == {}
    assert any("合并" in message for message in result["warnings"])


def test_duplicate_stable_target_is_unavailable_instead_of_last_row_wins():
    items = [_item()]
    preview = _preview([["FL001", 10, "个", 2, 20, "项目"], ["FL001", 10, "个", 3, 30, "项目"]])
    for row in preview["material_rows"]:
        row["_target_stable_line_key"] = items[0]["stable_line_key"]
    result = _build(items, preview)
    assert result["valuations"] == {}
    assert any("唯一" in message for message in result["warnings"])


def test_inconsistent_price_and_amount_currencies_cannot_be_silently_combined():
    items = [_item(price=2)]
    preview = _match(_preview([["FL001", 10, "个", 2, 20]],
                              ["物料编码", "数量", "单位", "单价（USD)", "总价（RMB)"]), items)
    result = _build(items, preview)
    assert preview["material_rows"][0]["currency_evidence"]["kind"] == "conflict"
    assert result["valuations"] == {}
    assert any("币种" in message and "冲突" in message for message in result["warnings"])


@pytest.mark.parametrize("confirmed", [False, 0, "false", "0"])
def test_unconfirmed_manual_proposal_does_not_override_verified_source(confirmed):
    items = [_item(extra_json=json.dumps({"shipment_valuation": {
        "manual_override_flag": 1, "confirmed": confirmed, "amount_rmb": "99"}}))]
    preview = _match(_preview([["FL001", 10, "个", 2, 20, "项目"]]), items)
    assert _build(items, preview)["valuations"]["ITEM-1"]["amount_rmb"] == "20"
