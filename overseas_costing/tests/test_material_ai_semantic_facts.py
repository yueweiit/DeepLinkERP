from __future__ import annotations

import json

import pytest

from overseas_costing.services import material_ai_fill_service as fill


def _items():
    return [
        {
            "name": "ITEM-144",
            "stable_line_key": "LINE-144",
            "material_code": "MWV101144",
            "product_name": "薇武士 IP17 PRO",
        },
        {
            "name": "ITEM-145",
            "stable_line_key": "LINE-145",
            "material_code": "MWV101145",
            "product_name": "薇武士 IP17 PRO MAX",
        },
    ]


def _line(row: int, waybill: str, code: str, *, approval_no: str = "OTHER") -> dict:
    return {
        "id": f"LINE-{row}",
        "line_key": f"BUSINESS-{waybill}",
        "waybill": waybill,
        "approval_no": approval_no,
        "scope": "freight",
        "amount": "3414.19",
        "currency": "RMB",
        "cargo_text": f"{code} 薇武士手机壳",
        "packing": {
            "material_code_hints": [code],
            "package_count": "1",
            "gross_weight_kg": "42.0500",
            "chargeable_weight_kg": "46",
            "dimensions_cm": ["33", "20", "23"],
            "volume_m3": ".015180",
        },
        "evidence": {
            "document_id": "DHL-MONTHLY",
            "file_name": "DHL(6.29-7.24)快递明细.xlsx",
            "sheet": "DHL快递",
            "row": row,
        },
    }


def test_selected_monthly_rows_become_independent_physical_facts_and_one_freight_total():
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    source = {
        "id": "PAYMENT",
        "instance": "202608260009000284583",
        "approval_no": "202608260009000284583",
        "title": "月结付款",
    }
    facts = build_payment_facts(
        _items(),
        source,
        [
            _line(14, "1841361513", "MWV101144", approval_no="202607211417000078258"),
            _line(13, "1841364722", "MWV101145", approval_no="202607211416000291269"),
        ],
    )

    physical = [fact for fact in facts if fact["fact_kind"] == "payment_physical"]
    assert [(fact["waybill"], fact["material_targets"][0]["item_name"]) for fact in physical] == [
        ("1841364722", "ITEM-145"),
        ("1841361513", "ITEM-144"),
    ]
    assert len({fact["fact_id"] for fact in physical}) == 2
    assert len({fact["package_identity"] for fact in physical}) == 2
    assert all(fact["scope_status"] == "in_scope" for fact in physical)
    assert all(
        fact["physical"]
        == {
            "package_count": "1",
            "gross_weight_kg": "42.05",
            "chargeable_weight_kg": "46",
            "volume_m3": "0.01518",
            "dimensions_cm": ["33", "20", "23"],
        }
        for fact in physical
    )

    components = [fact for fact in facts if fact["fact_kind"] == "payment_freight_component"]
    total = next(fact for fact in facts if fact["fact_kind"] == "payment_freight_total")
    assert len(components) == 2
    assert all(fact["read_only"] is True for fact in components)
    assert {fact["selection_role"] for fact in components} == {"component"}
    assert total["monetary"] == {"amount": "6828.38", "currency": "RMB"}
    assert total["selection_role"] == "primary_total"
    assert total["allowed_actions"] == []
    assert total["component_fact_ids"] == [fact["fact_id"] for fact in components]


def test_code_precedes_unique_name_and_unknown_or_ambiguous_rows_are_not_eligible():
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    items = [
        *_items(),
        {"name": "DUP-1", "stable_line_key": "DUP-1", "material_code": "DUP1", "product_name": "同名产品"},
        {"name": "DUP-2", "stable_line_key": "DUP-2", "material_code": "DUP2", "product_name": " 同 名 产 品 "},
    ]
    source = {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}
    exact_code = _line(2, "WB-CODE", "MWV101144")
    exact_code["goods"] = [{"material_code": "MWV101144", "product_name": "薇武士 IP17 PRO MAX"}]
    unique_name = _line(3, "WB-NAME", "")
    unique_name["packing"]["material_code_hints"] = []
    unique_name["goods"] = [{"material_code": "", "product_name": "薇 武士 ip17 pro max"}]
    ambiguous_name = _line(4, "WB-DUP", "")
    ambiguous_name["packing"]["material_code_hints"] = []
    ambiguous_name["goods"] = [{"material_code": "", "product_name": "同名产品"}]
    unknown = _line(5, "WB-FOREIGN", "FOREIGN999")
    unknown["goods"] = [{"material_code": "FOREIGN999", "product_name": "薇武士 IP17 PRO"}]

    facts = build_payment_facts(items, source, [exact_code, unique_name, ambiguous_name, unknown])
    by_waybill = {
        fact["waybill"]: fact
        for fact in facts
        if fact["fact_kind"] == "payment_physical"
    }

    assert by_waybill["WB-CODE"]["material_targets"][0]["item_name"] == "ITEM-144"
    assert by_waybill["WB-CODE"]["match_method"] == "exact_code"
    assert by_waybill["WB-NAME"]["material_targets"][0]["item_name"] == "ITEM-145"
    assert by_waybill["WB-NAME"]["match_method"] == "unique_name"
    assert by_waybill["WB-DUP"]["scope_status"] == "ambiguous"
    assert by_waybill["WB-DUP"]["default_eligible"] is False
    assert by_waybill["WB-FOREIGN"]["scope_status"] == "out_of_scope"
    assert by_waybill["WB-FOREIGN"]["default_eligible"] is False


def test_duplicate_row_identity_is_coalesced_but_distinct_rows_for_one_sku_stay_manual():
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    source = {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}
    first = _line(7, "WB-ONE", "MWV101144")
    duplicate = {**first, "id": "ARCHIVE-COPY"}
    other_shipment = _line(8, "WB-TWO", "MWV101144")

    duplicate_facts = build_payment_facts(_items(), source, [first, duplicate])
    reversed_duplicate_facts = build_payment_facts(_items(), source, [duplicate, first])
    duplicate_physical = [fact for fact in duplicate_facts if fact["fact_kind"] == "payment_physical"]
    reversed_physical = [fact for fact in reversed_duplicate_facts if fact["fact_kind"] == "payment_physical"]
    assert len(duplicate_physical) == 1
    assert duplicate_physical[0]["fact_id"] == reversed_physical[0]["fact_id"]
    assert duplicate_physical[0]["scope_status"] == "in_scope"

    ambiguous_facts = build_payment_facts(_items(), source, [first, other_shipment])
    ambiguous_physical = [fact for fact in ambiguous_facts if fact["fact_kind"] == "payment_physical"]
    assert len(ambiguous_physical) == 2
    assert {fact["scope_status"] for fact in ambiguous_physical} == {"ambiguous"}
    assert all(fact["default_eligible"] is False for fact in ambiguous_physical)


def test_same_sku_genuine_rows_with_same_waybill_are_ambiguous_and_not_totalled_twice():
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    source = {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}
    first = _line(7, "WB-SHARED", "MWV101144")
    second = _line(8, "WB-SHARED", "MWV101144")

    facts = build_payment_facts(_items(), source, [first, second])
    physical = [fact for fact in facts if fact["fact_kind"] == "payment_physical"]

    assert len(physical) == 2
    assert {fact["scope_status"] for fact in physical} == {"ambiguous"}
    assert all(fact["allowed_actions"] == [] for fact in physical)
    assert not any(fact["fact_kind"] == "payment_freight_total" for fact in facts)


@pytest.mark.parametrize(
    "item_updates",
    [
        {"tracking_no": "WB-ONE"},
        {"extra_json": json.dumps({"tracking_number": "WB-ONE"})},
    ],
)
def test_item_tracking_identifier_resolves_one_same_sku_shipment(item_updates):
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    items = _items()
    items[0].update(item_updates)
    source = {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}
    facts = build_payment_facts(
        items,
        source,
        [_line(7, "WB-ONE", "MWV101144"), _line(8, "WB-TWO", "MWV101144")],
    )
    physical = {
        fact["waybill"]: fact
        for fact in facts
        if fact["fact_kind"] == "payment_physical"
    }

    assert physical["WB-ONE"]["scope_status"] == "in_scope"
    assert physical["WB-ONE"]["default_eligible"] is True
    assert physical["WB-TWO"]["scope_status"] == "out_of_scope"
    assert physical["WB-TWO"]["default_eligible"] is False
    total = next(fact for fact in facts if fact["fact_kind"] == "payment_freight_total")
    assert total["monetary"] == {"amount": "3414.19", "currency": "RMB"}


def test_matched_freight_without_physical_values_still_yields_component_and_total():
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    line = _line(9, "WB-NO-PHYSICAL", "MWV101144")
    line["packing"] = {"material_code_hints": ["MWV101144"]}
    line["cargo_text"] = "MWV101144"

    facts = build_payment_facts(
        _items(), {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}, [line]
    )

    component = next(fact for fact in facts if fact["fact_kind"] == "payment_freight_component")
    total = next(fact for fact in facts if fact["fact_kind"] == "payment_freight_total")
    assert component["monetary"] == {"amount": "3414.19", "currency": "RMB"}
    assert component["scope_status"] == "in_scope"
    assert total["monetary"] == {"amount": "3414.19", "currency": "RMB"}
    assert total["allowed_actions"] == []


def test_explicit_goods_value_is_distinct_from_freight_amount_and_allowlisted():
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    line = _line(10, "WB-GOODS", "MWV101144")
    line.update(amount="88.50", currency="RMB", goods_value="1200", goods_currency="USD")

    facts = build_payment_facts(
        _items(), {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}, [line]
    )

    goods = next(fact for fact in facts if fact["fact_kind"] == "payment_goods_value")
    freight = next(fact for fact in facts if fact["fact_kind"] == "payment_freight_component")
    assert goods["monetary"] == {"amount": "1200", "currency": "USD"}
    assert freight["monetary"] == {"amount": "88.5", "currency": "RMB"}
    assert goods["allowed_actions"] == [
        {
            "action": "item_update",
            "target_item_name": "ITEM-144",
            "material_key": "LINE-144",
            "fieldname": "goods_value",
            "value": "1200",
        },
        {
            "action": "item_update",
            "target_item_name": "ITEM-144",
            "material_key": "LINE-144",
            "fieldname": "purchase_currency",
            "value": "USD",
        },
    ]


def test_ambiguous_scope_keeps_goods_value_read_only_and_excludes_freight_total():
    from overseas_costing.services.material_ai_semantic_facts import build_payment_facts

    first = _line(11, "WB-A", "MWV101144")
    second = _line(12, "WB-B", "MWV101144")
    for line in (first, second):
        line.update(goods_value="600", goods_currency="USD")
        line["packing"] = {"material_code_hints": ["MWV101144"]}
        line["cargo_text"] = "MWV101144"

    facts = build_payment_facts(
        _items(), {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}, [first, second]
    )
    goods = [fact for fact in facts if fact["fact_kind"] == "payment_goods_value"]

    assert len(goods) == 2
    assert {fact["scope_status"] for fact in goods} == {"ambiguous"}
    assert all(fact["default_eligible"] is False and fact["allowed_actions"] == [] for fact in goods)
    assert not any(fact["fact_kind"] == "payment_freight_total" for fact in facts)


def test_monetary_only_row_is_an_eligible_preview_evidence_anchor():
    from overseas_costing.services.material_ai_semantic_facts import (
        build_payment_facts,
        eligible_evidence_facts,
    )

    line = _line(15, "WB-MONEY-ONLY", "MWV101144")
    line["packing"] = {"material_code_hints": ["MWV101144"]}
    facts = build_payment_facts(
        _items(), {"id": "PAYMENT", "instance": "PROCESS", "approval_no": "PAY"}, [line]
    )

    anchors = eligible_evidence_facts(facts)
    assert [fact["fact_kind"] for fact in anchors] == ["payment_freight_component"]
    assert anchors[0]["waybill"] == "WB-MONEY-ONLY"


def test_scoped_goods_fact_actions_become_deterministic_candidates():
    fact = {
        "fact_id": "GOODS-FACT",
        "fact_kind": "payment_goods_value",
        "scope_status": "in_scope",
        "default_eligible": True,
        "material_targets": [{"item_name": "ITEM-144", "material_key": "LINE-144"}],
        "allowed_actions": [
            {
                "action": "item_update",
                "target_item_name": "ITEM-144",
                "material_key": "LINE-144",
                "fieldname": "goods_value",
                "value": "1200",
            },
            {
                "action": "item_update",
                "target_item_name": "ITEM-144",
                "material_key": "LINE-144",
                "fieldname": "purchase_currency",
                "value": "USD",
            },
        ],
    }
    source = {
        "source_id": "PAYMENT-FACT",
        "source_kind": "approval_attachment",
        "scoped_packing": True,
        "scoped_goods": [{"material_code": "MWV101144", "_material_key": "LINE-144"}],
        "semantic_facts": [fact],
    }

    candidates, document = fill._read_source(_items(), source)

    assert {
        (row["item_name"], row["fieldname"], row["suggested_value"], tuple(row["fact_ids"]))
        for row in candidates
    } == {
        ("ITEM-144", "goods_value", "1200", ("GOODS-FACT",)),
        ("ITEM-144", "purchase_currency", "USD", ("GOODS-FACT",)),
    }
    assert document["semantic_facts"] == [fact]


def test_model_fact_reference_must_be_known_in_scope_and_use_allowlisted_value():
    fact = {
        "fact_id": "FACT-1",
        "fact_kind": "payment_physical",
        "scope_status": "in_scope",
        "default_eligible": True,
        "material_targets": [{"item_name": "ITEM-144", "material_key": "LINE-144"}],
        "allowed_actions": [
            {
                "action": "item_update",
                "target_item_name": "ITEM-144",
                "fieldname": "gross_weight_kg",
                "value": "42.05",
            }
        ],
    }
    document = {
        "document_id": "DOC-1",
        "source_ref": {"source": "approval_attachment", "file": "DHL.xlsx"},
        "structured_rows": [{"source_row": 14}],
        "semantic_facts": [fact],
    }
    base = {
        "proposal_id": "MODEL-1",
        "proposal_type": "item_update",
        "target_item_name": "ITEM-144",
        "confidence": 1,
        "reason": "structured fact",
        "source_refs": [{"document_id": "DOC-1", "row": 14}],
        "payload": {"item_name": "ITEM-144", "fields": {"gross_weight_kg": "42.05"}},
    }
    items = [{"name": "ITEM-144", "stable_line_key": "LINE-144", "gross_weight_kg": "0"}]

    valid = fill.normalize_source_review_proposals(
        [{**base, "fact_ids": ["FACT-1"]}], items, [document]
    )
    unknown = fill.normalize_source_review_proposals(
        [{**base, "fact_ids": ["FACT-UNKNOWN"]}], items, [document]
    )
    invented = fill.normalize_source_review_proposals(
        [{**base, "fact_ids": ["FACT-1"], "payload": {"item_name": "ITEM-144", "fields": {"gross_weight_kg": "99"}}}],
        items,
        [document],
    )
    out_of_scope = fill.normalize_source_review_proposals(
        [{**base, "fact_ids": ["FACT-1"]}],
        items,
        [{**document, "semantic_facts": [{**fact, "scope_status": "out_of_scope", "default_eligible": False}]}],
    )

    assert len(valid) == 1
    assert valid[0]["fact_ids"] == ["FACT-1"]
    assert unknown == []
    assert invented == []
    assert out_of_scope == []
