from __future__ import annotations

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
