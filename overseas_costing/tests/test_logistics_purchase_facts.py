"""Deterministic purchase facts for the observed 8 shipment / 5 purchase row case."""

from copy import deepcopy
import json

import pytest


GOODS = [("FL000429", 96000), ("FL000429", 4000), ("FL000427", 4000),
         ("FL000427", 96000), ("FL000428", 100000), ("FL000430", 100000),
         ("FL003377", 22000), ("CW000191", 2400)]
PURCHASE = [("FL000427", 100000, 15100), ("FL000428", 100000, 15100),
            ("FL000429", 100000, 15100), ("FL000430", 100000, 15100),
            ("FL003377", 200000, 26000)]


def _items():
    return [{"name": f"ITEM-{index}", "row_no": index, "material_code": code,
             "quantity": qty, "actual_shipped_qty": qty, "shipped_uom": "个",
             "actual_shipped_qty_mode": "EXPLICIT_SOURCE", "source_type": "OA_LOGISTICS_ROW",
             "source_doc_no": "LOG-6262", "extra_json": json.dumps({"source": "dingtalk_oa_logistics_form"})}
            for index, (code, qty) in enumerate(GOODS, 1)]


def _source(rows=None, source_id="approval:PUR-1:form", approval_no="PUR-1"):
    if rows is None:
        rows = [{"rowNumber": f"purchase-row-{index}", "rowValue": [
            {"label": "物品编码Código", "value": code},
            {"label": "数量Cantidad", "value": qty},
            {"label": "总金额Monto Total", "value": value},
            {"label": "单价Precio", "value": value / qty},
            {"label": "单位Unidad", "value": "pcs"}]} for index, (code, qty, value) in enumerate(PURCHASE, 1)]
    return {"source_kind": "approval_form", "source_id": source_id, "approval_no": approval_no,
            "approval_role": "purchase", "selected": True,
            "form_fields": {"币种Moneda": "人民币RMB", "采购明细": rows}}


def _enrich(items, sources, **kwargs):
    from overseas_costing.services.logistics_purchase_facts_service import enrich_logistics_purchase_facts
    return enrich_logistics_purchase_facts(items, sources, **kwargs)


def _association(item):
    return json.loads(item["extra_json"])["logistics_row"]


def test_new_logistics_rows_share_full_purchase_fact_without_multiplying_totals():
    original_items, sources = _items(), [_source()]
    before_items, before_sources = deepcopy(original_items), deepcopy(sources)
    result = _enrich(original_items, sources)
    rows = result["items"]
    assert [(row["material_code"], row["actual_shipped_qty"]) for row in rows] == GOODS
    assert all(row["quantity"] is None for row in rows)
    assert _association(rows[0])["purchase_key"] == _association(rows[1])["purchase_key"]
    assert _association(rows[2])["purchase_key"] == _association(rows[3])["purchase_key"]
    facts = {_association(row)["purchase_key"]: _association(row)["purchase_fact"]
             for row in rows if _association(row).get("purchase_key")}
    assert len(facts) == 5
    assert sum(float(fact["quantity"]) for fact in facts.values()) == 600000
    assert sum(float(fact["goods_value"]) for fact in facts.values()) == 86400
    assert _association(rows[0])["purchase_fact"]["purchase_uom"] == "个"
    assert _association(rows[0])["purchase_fact"]["unit_price_uom"] == "个"
    assert _association(rows[0])["purchase_fact"]["purchase_currency"] == "RMB"
    assert _association(rows[0])["purchase_fact"]["source_doc_no"] == "PUR-1"
    assert rows[-1]["quantity"] is None and rows[-1]["goods_value"] is None
    assert not _association(rows[-1]).get("purchase_key")
    assert any("CW000191" in row["message"] for row in result["unresolved"])
    assert original_items == before_items and sources == before_sources


def test_existing_purchase_rows_are_preserved_even_when_source_fact_changed():
    item = {"name": "OLD-1", "material_code": "FL000429", "source_type": "PURCHASE_EXPENSE_OA",
            "quantity": 123, "goods_value": 456, "unit_price": 3, "purchase_currency": "RMB",
            "source_doc_no": "PUR-OLD", "manual_override_flag": 1, "extra_json": "{}"}
    result = _enrich([item], [_source()])
    assert result["items"] == [item]
    assert result["unresolved"] == []


def test_saved_purchase_fact_and_existing_manual_fields_win_over_new_source():
    item = _items()[0]
    item.update(quantity=42, goods_value=84, unit_price=2, manual_override_flag=1,
                extra_json=json.dumps({"keep": "metadata", "logistics_row": {
                    "purchase_key": "saved-purchase-detail", "identity": "logistics:old",
                    "purchase_fact": {"quantity": 400, "goods_value": 800, "unit_price": 2,
                                      "source_doc_no": "PUR-1", "purchase_currency": "RMB"}}}))
    result = _enrich([item], [_source()])
    row = result["items"][0]
    assert row["quantity"] == 42 and row["goods_value"] == 84 and row["unit_price"] == 2
    association = _association(row)
    assert association["purchase_key"] == "saved-purchase-detail"
    assert association["identity"] == "logistics:old"
    assert association["purchase_fact"]["quantity"] == 400
    assert association["purchase_fact"]["goods_value"] == 800
    assert association["purchase_fact"]["unit_price"] == 2
    assert association["purchase_fact"]["purchase_uom"] == "个"
    assert json.loads(row["extra_json"])["keep"] == "metadata"


def test_new_row_manual_purchase_correction_is_not_erased_as_shipping_quantity():
    item = _items()[0]
    item.update(quantity=777, goods_value=888, unit_price=9, manual_override_flag=1)
    row = _enrich([item], [_source()])["items"][0]
    assert (row["quantity"], row["goods_value"], row["unit_price"]) == (777, 888, 9)
    assert (_association(row)["purchase_fact"]["quantity"],
            _association(row)["purchase_fact"]["goods_value"]) == (777, 888)


def test_ambiguous_purchase_rows_remain_unknown_with_source_context():
    source2 = _source([{"物料编码": "FL000429", "数量": 50000, "总货值": 9000}],
                      source_id="approval:PUR-2:form", approval_no="PUR-2")
    result = _enrich(_items()[:2], [_source(), source2])
    assert all(row["quantity"] is None and row["goods_value"] is None for row in result["items"])
    assert all(not _association(row).get("purchase_key") for row in result["items"])
    assert any("FL000429" in row["message"] and "PUR-1" in row["message"] and "PUR-2" in row["message"]
               for row in result["unresolved"])


@pytest.mark.parametrize("matching_field, value", [("spec_model", "A"), ("source_doc_no", "PUR-2")])
def test_purchase_match_can_be_disambiguated_by_saved_spec_or_purchase_document(matching_field, value):
    source1 = _source([{"物料编码": "FL000429", "规格型号": "B", "数量": 100000, "总货值": 15100}])
    source2 = _source([{"物料编码": "FL000429", "规格型号": "A", "数量": 50000, "总货值": 9000}],
                      source_id="approval:PUR-2:form", approval_no="PUR-2")
    item = _items()[0]
    item[matching_field] = value
    row = _enrich([item], [source1, source2])["items"][0]
    assert float(_association(row)["purchase_fact"]["quantity"]) == 50000


def test_unique_purchase_sku_matches_when_logistics_uses_a_different_spec_description():
    item = _items()[0]
    item["spec_model"] = "物流填写的包装规格"
    source = _source([{"物料编码": "FL000429", "规格型号": "采购填写的原始规格", "数量": 100000, "总货值": 15100}])
    row = _enrich([item], [source])["items"][0]
    assert _association(row)["purchase_fact"]["quantity"] == 100000
    assert row["spec_model"] == "物流填写的包装规格"


@pytest.mark.parametrize("override", [{"approval_role": "international_logistics"}, {"excluded": True},
                                      {"selected": False}, {"available": False}, {"source_kind": "approval_comment"}])
def test_only_selected_available_purchase_approval_bodies_supply_facts(override):
    source = {**_source(), **override}
    result = _enrich(_items()[:1], [source])
    assert result["items"][0]["quantity"] is None
    assert result["items"][0]["goods_value"] is None
    assert not _association(result["items"][0]).get("purchase_key")


def test_stable_purchase_row_identity_survives_structured_table_reordering():
    source = _source()
    first = _enrich(_items(), [source])
    source["form_fields"]["采购明细"].reverse()
    source["form_fields"]["采购明细"] = json.dumps(source["form_fields"]["采购明细"])
    second = _enrich(_items(), [source])
    assert [_association(row).get("purchase_key") for row in first["items"]] == [
        _association(row).get("purchase_key") for row in second["items"]]
    assert _enrich(first["items"], [_source()])["items"] == first["items"]


def test_missing_stored_fact_can_be_completed_without_using_apportioned_row_quantity():
    item = _items()[0]
    item.update(quantity=96000, goods_value=14496, extra_json=json.dumps({"logistics_row": {
        "purchase_key": "existing-group", "purchase_fact": {"quantity": None, "goods_value": 15100}}}))
    row = _enrich([item], [_source()])["items"][0]
    assert row["quantity"] == 96000 and row["goods_value"] == 14496
    assert _association(row)["purchase_fact"]["quantity"] == 100000
    assert _association(row)["purchase_fact"]["goods_value"] == 15100


def test_missing_saved_fact_fields_are_not_borrowed_from_another_purchase_document():
    item = _items()[0]
    item["extra_json"] = json.dumps({"logistics_row": {"purchase_key": "saved-old-purchase",
        "purchase_fact": {"source_doc_no": "PUR-OLD", "quantity": 50000, "goods_value": 1234}}})
    row = _enrich([item], [_source()])["items"][0]
    fact = _association(row)["purchase_fact"]
    assert fact["source_doc_no"] == "PUR-OLD"
    assert fact.get("unit_price") is None and fact.get("purchase_uom") is None


def test_purchase_row_key_without_row_number_is_scoped_to_its_table():
    source = _source([{"物料编码": "FL000429", "数量": 100000, "总货值": 15100}])
    first = _enrich(_items()[:1], [source])["items"][0]
    source["form_fields"] = {"审批人": [{"姓名": "审批人"}], **source["form_fields"]}
    second = _enrich(_items()[:1], [source])["items"][0]
    assert _association(first)["purchase_key"] == _association(second)["purchase_key"]


def test_helper_has_no_database_or_network_dependency(monkeypatch):
    from overseas_costing.scripts import import_oa_logistics
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError(f"must not access database: {name}")
    monkeypatch.setattr(import_oa_logistics, "frappe", Forbidden())
    monkeypatch.setattr(import_oa_logistics, "_request_json", lambda *args, **kwargs: pytest.fail("must not use network"))
    assert len(_enrich(_items(), [_source()])["items"]) == 8


def test_archived_labelled_purchase_rows_use_the_structured_mapper():
    source = _source()
    source["form_fields"]["需求明细Desglose de los gastos"] = "\n".join(
        f"物品名称Nombre del artículo：包装材料；图片Imagen：https://example.invalid/picture.jpg；"
        f"物品编码Código：{code}；物品规格Especificacion：规格；数量Cantidad：{qty}；"
        f"库存Inventario：100；单位Unidad：PZA；单价Precio：{value / qty}；总金额Monto Total：{value}"
        for code, qty, value in PURCHASE)
    del source["form_fields"]["采购明细"]
    rows = _enrich(_items(), [source])["items"]
    facts = {_association(row)["purchase_key"]: _association(row)["purchase_fact"]
             for row in rows if _association(row).get("purchase_key")}
    assert len(facts) == 5
    assert sum(float(fact["goods_value"]) for fact in facts.values()) == 86400
    assert all(fact["purchase_uom"] == "个" for fact in facts.values())


def test_new_purchase_total_converts_to_rmb_but_preserves_source_unit_price_and_amount():
    source = _source([{"物料编码": "FL000429", "数量": 10, "单价Precio": "10.035", "总货值": "100.35"}])
    source["form_fields"]["币种Moneda"] = "USD"
    row = _enrich(_items()[:1], [source], fx_rates={"USD": "7.1"})["items"][0]
    fact = _association(row)["purchase_fact"]
    assert float(fact["goods_value"]) == 712.485
    assert float(fact["unit_price"]) == float(row["unit_price"]) == 10.035
    assert fact["purchase_currency"] == "USD"
    assert float(fact["original_goods_value"]) == 100.35
    assert fact["original_currency"] == "USD"
    assert float(fact["goods_value_fx_rate"]) == 7.1


@pytest.mark.parametrize("rates", [{}, {"USD": "0"}, {"USD": "NaN"}])
def test_missing_or_invalid_fx_leaves_new_rmb_value_unknown(rates):
    source = _source([{"物料编码": "FL000429", "数量": 10, "单价Precio": 10, "总货值": 100}])
    source["form_fields"]["币种Moneda"] = "USD"
    result = _enrich(_items()[:1], [source], fx_rates=rates)
    fact = _association(result["items"][0])["purchase_fact"]
    assert fact["goods_value"] is None and fact["original_goods_value"] == 100
    assert fact["unit_price"] == 10
    assert any("USD" in row["message"] and "汇率" in row["message"] for row in result["unresolved"])


def test_existing_rmb_purchase_fact_is_not_converted_again():
    source = _source([{"物料编码": "FL000429", "数量": 10, "总货值": 100}])
    source["form_fields"]["币种Moneda"] = "USD"
    item = _items()[0]
    item["extra_json"] = json.dumps({"logistics_row": {"purchase_key": "saved-group",
        "purchase_fact": {"quantity": 10, "goods_value": 699, "purchase_currency": "USD", "source_doc_no": "PUR-1"}}})
    row = _enrich([item], [source], fx_rates={"USD": "7.1"})["items"][0]
    assert _association(row)["purchase_fact"]["goods_value"] == 699


def test_new_database_zero_defaults_are_missing_purchase_facts():
    item = {**_items()[0], "goods_value": 0, "unit_price": 0}
    row = _enrich([item], [_source()])["items"][0]
    fact = _association(row)["purchase_fact"]
    assert fact["goods_value"] == 15100 and float(fact["unit_price"]) == 0.151
    assert float(row["unit_price"]) == 0.151
    assert row["quantity"] is None and row["goods_value"] is None


def test_manual_zero_purchase_values_are_real_corrections():
    item = {**_items()[0], "quantity": 0, "goods_value": 0, "unit_price": 0, "manual_override_flag": 1}
    row = _enrich([item], [_source()])["items"][0]
    fact = _association(row)["purchase_fact"]
    assert (row["quantity"], row["goods_value"], row["unit_price"]) == (0, 0, 0)
    assert (fact["quantity"], fact["goods_value"], fact["unit_price"]) == (0, 0, 0)


def test_labelled_rows_parser_accepts_logistics_and_purchase_labels():
    from overseas_costing.services.logistics_purchase_facts_service import parse_labelled_approval_rows
    value = "物料编码 Código de material：FL000429；物料名称：包装；数量Cantidad：96000；单位Unidad：PZA\n物品编码Código:FL000429;数量Cantidad:4000;单位Unidad:PZA"
    rows = parse_labelled_approval_rows(value)
    assert len(rows) == 2
    assert rows[0]["数量Cantidad"] == "96000" and rows[1]["数量Cantidad"] == "4000"


@pytest.mark.parametrize("value", ["本次发送FL000429共96000件", "物料编码:FL000429", "数量:20;说明:FL000429",
                                   "物料编码:FL000429;数量:不详", "物料编码:FL000429;数量:0"])
def test_labelled_rows_parser_rejects_unstructured_or_invalid_rows(value):
    from overseas_costing.services.logistics_purchase_facts_service import parse_labelled_approval_rows
    assert parse_labelled_approval_rows(value) == []
