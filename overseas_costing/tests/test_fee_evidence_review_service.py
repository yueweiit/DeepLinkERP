"""费用凭证审核、结算净额与 SKU 税种分项测试。"""

from decimal import Decimal

import pytest

from overseas_costing.services import fee_evidence_review_service as service
from overseas_costing.services import fee_service


def _items():
    return [
        {
            "name": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "material_code": "GL-01",
            "product_name": "眼镜",
            "import_name": "GAFAS",
            "hs_code": "90041000",
            "customs_declared_value_mxn": "200",
            "goods_value": "400",
        },
        {
            "name": "ITEM-SUNGLASSES",
            "stable_line_key": "LINE-SUNGLASSES",
            "material_code": "SUN-01",
            "product_name": "太阳眼镜",
            "import_name": "GAFAS DE SOL",
            "hs_code": "90041000",
            "customs_declared_value_mxn": "100",
            "goods_value": "200",
        },
    ]


def test_fee_status_transition_requires_reason_for_unproved_actual_and_actual_rollback() -> None:
    with pytest.raises(ValueError, match="最终凭证|原因"):
        fee_service.validate_fee_status_transition(
            "ESTIMATED", "ACTUAL", reason="", has_valid_final_evidence=False
        )
    with pytest.raises(ValueError, match="原因"):
        fee_service.validate_fee_status_transition(
            "ACTUAL", "ESTIMATED", reason="", has_valid_final_evidence=True
        )

    assert fee_service.validate_fee_status_transition(
        "ESTIMATED", "ACTUAL", reason="完税凭证已核对", has_valid_final_evidence=False
    )["reason"] == "完税凭证已核对"
    assert fee_service.validate_fee_status_transition(
        "ESTIMATED", "ACTUAL", reason="", has_valid_final_evidence=True
    )["requires_reason"] is False


@pytest.mark.parametrize(
    ("previous_status", "next_status"),
    [
        ("MISSING", "NOT_INCURRED"),
        ("MISSING", "INCLUDED"),
        ("ESTIMATED", "ACTUAL"),
        ("ACTUAL", "ESTIMATED"),
    ],
)
def test_reason_gated_status_transitions_reject_blank_reason(
    previous_status: str, next_status: str
) -> None:
    with pytest.raises(ValueError, match="原因"):
        fee_service.validate_fee_status_transition(
            previous_status,
            next_status,
            reason="",
            has_valid_final_evidence=False,
        )


def test_first_inline_amount_defaults_to_estimated_instead_of_actual() -> None:
    assert fee_service.default_status_for_amount_entry("MISSING", "251") == "ESTIMATED"
    assert fee_service.default_status_for_amount_entry("ACTUAL", "251") == "ACTUAL"
    assert fee_service.default_status_for_amount_entry("MISSING", "") == "MISSING"


def test_tax_components_split_same_hs_by_declared_value_and_conserve_each_tax() -> None:
    lines = [
        {
            "row_no": 8,
            "hs_code": "90041000",
            "import_name": "GAFAS",
            "taxes": {"igi_amount_mxn": "10.01", "iva_amount_mxn": "20.00"},
        }
    ]

    result = service.allocate_tax_certificate_components(
        lines,
        _items(),
        fx_context={"fx_rmb_to_mxn": "2"},
        source_ref={"attachment": "ATT-TAX", "page": 3},
    )

    assert result["needs_review"] is False
    assert result["allocation_basis"] == "customs_declared_value"
    assert {row["item"] for row in result["components"]} == {
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    }
    for tax_code, expected in (("IGI", Decimal("10.01")), ("IVA", Decimal("20.00"))):
        rows = [row for row in result["components"] if row["tax_code"] == tax_code]
        assert sum(Decimal(row["original_amount"]) for row in rows) == expected
        assert sum(Decimal(row["amount_rmb"]) for row in rows) == expected / 2
        assert all(row["source_evidence"]["attachment"] == "ATT-TAX" for row in rows)
        assert all(row["accounting_role"] == "FINAL_BILL" for row in rows)
        assert all(row["cost_effect"] == "COST" for row in rows)


def test_tax_components_fall_back_to_purchase_value_and_block_without_any_basis() -> None:
    items = _items()
    for row in items:
        row["customs_declared_value_mxn"] = ""
    allocated = service.allocate_tax_certificate_components(
        [{"row_no": 1, "hs_code": "90041000", "taxes": {"igi_amount_mxn": "9"}}],
        items,
        fx_context={"fx_rmb_to_mxn": "3"},
    )
    assert allocated["allocation_basis"] == "purchase_goods_value"
    assert allocated["needs_review"] is False

    for row in items:
        row["goods_value"] = ""
    blocked = service.allocate_tax_certificate_components(
        [{"row_no": 1, "hs_code": "90041000", "taxes": {"igi_amount_mxn": "9"}}],
        items,
        fx_context={"fx_rmb_to_mxn": "3"},
    )
    assert blocked["needs_review"] is True
    assert blocked["unmatched_lines"][0]["reason_code"] == "SKU_ALLOCATION_BASIS_MISSING"


def test_evidence_ledger_keeps_estimate_separate_from_payments_and_refunds() -> None:
    evidence = [
        {"evidence_type": "QUOTE", "accounting_role": "ESTIMATE", "original_amount": "1000", "direction": "DEBIT"},
        {"evidence_type": "PAYMENT", "accounting_role": "SETTLEMENT", "original_amount": "300", "direction": "DEBIT"},
        {"evidence_type": "REFUND", "accounting_role": "SETTLEMENT", "original_amount": "50", "direction": "CREDIT"},
    ]
    provisional = service.summarize_evidence_ledger(
        evidence, current_amount="1000", current_status="ESTIMATED"
    )
    assert provisional["effective_amount"] == "1000.00"
    assert provisional["settlement_net"] == "250.00"
    assert provisional["effective_status"] == "ESTIMATED"

    evidence.append(
        {"evidence_type": "FINAL_INVOICE", "accounting_role": "FINAL_BILL", "original_amount": "900", "direction": "DEBIT", "is_final": 1}
    )
    final = service.summarize_evidence_ledger(
        evidence, current_amount="1000", current_status="ESTIMATED"
    )
    assert final["effective_amount"] == "900.00"
    assert final["settlement_net"] == "250.00"
    assert final["effective_status"] == "ACTUAL"


def test_evidence_ledger_ignores_pending_and_invalid_evidence() -> None:
    summary = service.summarize_evidence_ledger(
        [
            {"validation_status": "VALID", "accounting_role": "SETTLEMENT", "original_amount": "100", "direction": "DEBIT", "currency": "MXN"},
            {"validation_status": "PENDING", "accounting_role": "SETTLEMENT", "original_amount": "80", "direction": "DEBIT", "currency": "MXN"},
            {"validation_status": "INVALID", "accounting_role": "FINAL_BILL", "original_amount": "999", "direction": "DEBIT", "currency": "MXN", "is_final": 1},
        ],
        current_amount="120",
        current_status="ESTIMATED",
    )

    assert summary["settlement_net_by_currency"] == {"MXN": "100.00"}
    assert summary["final_bill_by_currency"] == {}
    assert summary["effective_amount"] == "120.00"
    assert summary["effective_status"] == "ESTIMATED"


def test_mixed_customs_document_separates_tax_clearance_and_unclassified_difference() -> None:
    parsed = {
        "parser": "mexico_tax_certificate_pedimento",
        "header": {"paid_total_mxn": 130},
        "tax_totals": {"igi_mxn": 50, "iva_mxn": 50, "dta_mxn": 0},
        "service_fees": [{"code": "broker_service", "label": "报关行服务费", "amount_mxn": 20}],
        "line_items": [],
        "validation": {"status": "passed"},
    }

    split = service.split_customs_evidence(parsed)

    assert split["import_tax_amount"] == "100.00"
    assert split["customs_clearance_amount"] == "20.00"
    assert split["unclassified_difference"] == "10.00"
    assert split["currency"] == "MXN"


def test_review_draft_uses_only_evidenced_numbers_and_defaults_final_tax_certificate() -> None:
    parsed = {
        "parser": "mexico_tax_certificate_pedimento",
        "header": {"paid_total_mxn": 30.01},
        "tax_totals": {"igi_mxn": 10.01, "iva_mxn": 20},
        "line_items": [
            {
                "row_no": 8,
                "hs_code": "90041000",
                "import_name": "GAFAS",
                "taxes": {"igi_amount_mxn": 10.01, "iva_amount_mxn": 20},
                "source_evidence": {
                    "hs_code": {"page": 3, "text_line": 18},
                    "igi_amount_mxn": {"page": 3, "text_line": 20},
                    "iva_amount_mxn": {"page": 3, "text_line": 21},
                },
            }
        ],
        "source_evidence": {
            "header.paid_total_mxn": {"page": 4, "text_line": 2},
            "tax_totals.igi_mxn": {"page": 4, "text_line": 4},
            "tax_totals.iva_mxn": {"page": 4, "text_line": 5},
        },
        "validation": {"status": "passed"},
    }
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment={"name": "ATT-TAX", "file_name": "完税凭证.pdf", "parse_result_json": parsed},
        items=_items(),
        fx_context={"fx_rmb_to_mxn": 2},
    )

    assert draft["evidence"]["evidence_type"] == "TAX_CERTIFICATE"
    assert draft["evidence"]["accounting_role"] == "FINAL_BILL"
    assert draft["evidence"]["suggested_amount_status"] == "ACTUAL"
    assert draft["evidence"]["default_selected"] is True
    assert draft["fee_splits"][0]["logical_fee_key"] == "import_tax"
    assert draft["fee_splits"][0]["amount"] == "30.01"
    assert draft["components"]
    assert {row["item"] for row in draft["item_options"]} == {
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    }
    assert all(row["source_evidence"] for row in draft["components"])


def test_amount_without_precise_locator_is_not_default_selected() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="customs_clearance_fee",
        attachment={
            "name": "ATT-NO-LOCATOR",
            "file_name": "quotation.pdf",
            "parse_result_json": {"total_amount": 100, "currency": "MXN"},
        },
        items=[],
        ai_review={
            "evidence_type": "QUOTE",
            "accounting_role": "ESTIMATE",
            "direction": "DEBIT",
            "confidence": "0.99",
        },
    )

    assert draft["evidence"]["default_selected"] is False
    assert draft["evidence"]["needs_review"] is True


def test_ai_rule_conflict_is_marked_and_not_default_selected() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment={
            "name": "ATT-CONFLICT",
            "file_name": "完税凭证.pdf",
            "parse_result_json": {
                "parser": "mexico_tax_certificate_pedimento",
                "header": {"paid_total_mxn": "30"},
                "tax_totals": {"igi_mxn": "30"},
                "line_items": [],
                "validation": {"status": "passed"},
                "source_evidence": {
                    "header.paid_total_mxn": {"page": 1, "text_line": 4},
                    "tax_totals.igi_mxn": {"page": 1, "text_line": 3},
                },
            },
        },
        items=_items(),
        ai_review={
            "evidence_type": "QUOTE",
            "accounting_role": "ESTIMATE",
            "confidence": "0.99",
        },
    )

    assert draft["evidence"]["has_conflict"] is True
    assert draft["evidence"]["default_selected"] is False
    assert "AI" in draft["evidence"]["warning"]


def test_human_amount_edits_are_recorded_as_manual_review_evidence() -> None:
    evidence, fee_rows, _components = service._selected_proposals(
        {
            "evidence": {
                "proposal_id": "evidence:classification",
                "original_amount": "10",
                "source_refs": [{"page": 1, "text_line": 2}],
            },
            "fee_splits": [
                {
                    "proposal_id": "fee:import_tax",
                    "logical_fee_key": "import_tax",
                    "amount": "10",
                    "source_refs": [{"page": 1, "text_line": 2}],
                }
            ],
            "components": [],
        },
        ["evidence:classification", "fee:import_tax"],
        {
            "evidence:classification": {"original_amount": "11"},
            "fee:import_tax": {"amount": "11"},
        },
    )

    assert evidence["human_edits"] == ["original_amount"]
    assert fee_rows[0]["human_edits"] == ["amount"]
    assert evidence["source_refs"][-1]["type"] == "MANUAL_REVIEW"
    assert fee_rows[0]["source_refs"][-1]["field"] == "amount"


def test_refund_parent_is_an_allowed_evidence_edit() -> None:
    evidence, _fee_rows, _components = service._selected_proposals(
        {
            "evidence": {
                "proposal_id": "evidence:classification",
                "evidence_type": "REFUND",
                "related_evidence": "",
            },
            "fee_splits": [],
            "components": [],
        },
        ["evidence:classification"],
        {"evidence:classification": {"related_evidence": "PAYMENT-1"}},
    )

    assert evidence["related_evidence"] == "PAYMENT-1"


def test_payment_and_refund_evidence_never_replace_the_fee_total() -> None:
    for evidence_type, direction in (("PAYMENT", "DEBIT"), ("REFUND", "CREDIT")):
        draft = service.build_fee_evidence_review_draft(
            logical_fee_key="customs_clearance_fee",
            attachment={
                "name": f"ATT-{evidence_type}",
                "file_name": f"{evidence_type}.pdf",
                "parse_result_json": {"currency": "MXN", "total_amount": 251},
            },
            items=_items(),
            ai_review={
                "evidence_type": evidence_type,
                "accounting_role": "SETTLEMENT",
                "direction": direction,
                "is_final": 0,
                "confidence": "0.99",
                "reason": "付款或退款流水",
            },
        )

        assert draft["evidence"]["original_amount"] == "251"
        assert draft["fee_splits"] == []


def test_attachment_review_ignores_archive_metadata_and_routes_pdf_by_content(monkeypatch) -> None:
    calls = []

    def preview_source_document(**_kwargs):
        calls.append("classify")
        return {
            "ok": True,
            "classification": {"code": "tax_certificate", "label": "完税凭证"},
            "field_candidates": {},
        }

    def preview_tax_certificate_pdf(**_kwargs):
        calls.append("tax")
        return {"ok": True, "parser": "mexico_tax_certificate_pedimento", "tax_totals": {"igi_mxn": 10}}

    from overseas_costing.services import attachment_parse_service

    monkeypatch.setattr(attachment_parse_service, "preview_source_document", preview_source_document)
    monkeypatch.setattr(attachment_parse_service, "preview_tax_certificate_pdf", preview_tax_certificate_pdf)

    parsed, warning = service._parse_attachment_for_review(
        {
            "file_name": "pedimento.pdf",
            "file_url": "/private/files/pedimento.pdf",
            "parse_result_json": {"source": "dingtalk_archive", "raw_attachment": {"fileId": "F1"}},
        },
        "B1",
    )

    assert warning == ""
    assert calls == ["classify", "tax"]
    assert parsed["parser"] == "mexico_tax_certificate_pedimento"


def test_non_tax_pdf_is_not_forced_through_tax_certificate_parser(monkeypatch) -> None:
    calls = []

    def preview_source_document(**_kwargs):
        calls.append("classify")
        return {
            "ok": True,
            "classification": {"code": "logistics_quote", "label": "物流报价"},
            "field_candidates": {"fee_amount": 251, "currencies": ["RMB"]},
        }

    from overseas_costing.services import attachment_parse_service

    monkeypatch.setattr(attachment_parse_service, "preview_source_document", preview_source_document)
    monkeypatch.setattr(
        attachment_parse_service,
        "preview_tax_certificate_pdf",
        lambda **_kwargs: calls.append("tax") or {},
    )

    parsed, warning = service._parse_attachment_for_review(
        {"file_name": "DHL报价.pdf", "file_url": "/private/files/quote.pdf"},
        "B1",
    )

    assert warning == ""
    assert calls == ["classify"]
    assert parsed["classification"]["code"] == "logistics_quote"


def test_component_amounts_are_authoritative_and_only_residual_uses_fee_rule() -> None:
    from overseas_costing.services.cost_preview_service import preview_comprehensive_cost_data

    items = [
        {"name": "I1", "stable_line_key": "L1", "goods_value": 100, "quantity": 1, "purchase_uom": "个", "unit_price_uom": "个"},
        {"name": "I2", "stable_line_key": "L2", "goods_value": 100, "quantity": 1, "purchase_uom": "个", "unit_price_uom": "个"},
    ]
    fees = [
        {
            "name": "F-TAX",
            "logical_fee_key": "import_tax",
            "expense_category": "进口税费",
            "amount_status": "ESTIMATED",
            "amount": "100",
            "currency": "RMB",
            "allocation_basis": "goods_value",
            "scope_type": "ALL_ITEMS",
            "is_enabled": 1,
        }
    ]
    components = [
        {"fee_rule": "F-TAX", "item": "I1", "stable_line_key": "L1", "tax_code": "IGI", "amount_rmb": "30", "status": "CONFIRMED", "is_active": 1},
    ]

    result = preview_comprehensive_cost_data(items, fees, {}, fee_components=components)

    tax = result["included_fees"][0]
    assert tax["amount_rmb"] == "100.00"
    assert tax["allocations"] == {"L1": "65.00", "L2": "35.00"}
    assert tax["component_allocations"] == {"L1": "30.00"}
    assert tax["residual_amount_rmb"] == "70.00"
    assert result["summary"]["total_cost_rmb"] == "300.00"


def test_component_conservation_allows_original_currency_without_fx() -> None:
    fee = {"amount": "100", "currency": "MXN"}
    valid = [
        {"currency": "MXN", "original_amount": "40", "amount_rmb": "20"},
        {"currency": "MXN", "original_amount": "60", "amount_rmb": "30"},
    ]

    assert service.validate_component_amount_conservation(
        fee, valid, {"fx_rmb_to_mxn": "2"}
    )["component_total_rmb"] == "50.00"

    missing_fx = service.validate_component_amount_conservation(
        fee,
        [
            {"currency": "MXN", "original_amount": "40", "amount_rmb": None},
            {"currency": "MXN", "original_amount": "60", "amount_rmb": None},
        ],
        {},
    )
    assert missing_fx == {
        "original_currency": "MXN",
        "original_total": "100.00",
        "missing_fx": True,
    }
    with pytest.raises(ValueError, match="汇率快照"):
        service.validate_component_amount_conservation(fee, valid, {})


def test_component_conservation_rejects_invalid_conversion_and_amounts_above_fee_total() -> None:
    fee = {"amount": "100", "currency": "MXN"}
    with pytest.raises(ValueError, match="换算金额"):
        service.validate_component_amount_conservation(
            fee,
            [{"currency": "MXN", "original_amount": "100", "amount_rmb": "60"}],
            {"fx_rmb_to_mxn": "2"},
        )
    with pytest.raises(ValueError, match="超过费用总额"):
        service.validate_component_amount_conservation(
            fee,
            [{"currency": "RMB", "original_amount": "51", "amount_rmb": "51"}],
            {"fx_rmb_to_mxn": "2"},
        )


def test_clearance_service_without_line_scope_uses_purchase_value() -> None:
    result = service.allocate_service_fee_components(
        [
            {
                "amount_mxn": "30",
                "source_evidence": {"page": 2, "text_line": 8},
            }
        ],
        _items(),
        fx_context={"fx_rmb_to_mxn": "2"},
    )

    assert [row["original_amount"] for row in result["components"]] == [
        "20.00",
        "10.00",
    ]
    assert [row["amount_rmb"] for row in result["components"]] == ["10", "5"]
    assert all(
        row["allocation_basis"] == "purchase_goods_value"
        for row in result["components"]
    )


def test_clearance_service_requires_complete_purchase_values() -> None:
    items = _items()
    items[1]["goods_value"] = ""

    result = service.allocate_service_fee_components(
        [{"amount_mxn": "30", "source_evidence": {"page": 2, "text_line": 8}}],
        items,
        fx_context={"fx_rmb_to_mxn": "2"},
    )

    assert result["components"] == []
    assert result["needs_review"] is True
    assert result["reason_code"] == "SKU_ALLOCATION_BASIS_MISSING"


def test_mixed_customs_draft_includes_clearance_service_components() -> None:
    parsed = {
        "parser": "mexico_tax_certificate_pedimento",
        "header": {"paid_total_mxn": "50"},
        "tax_totals": {"igi_mxn": "20"},
        "service_fees": [
            {
                "code": "broker_service",
                "amount_mxn": "30",
                "source_evidence": {"page": 2, "text_line": 8},
            }
        ],
        "line_items": [],
        "source_evidence": {
            "header.paid_total_mxn": {"page": 2, "text_line": 10},
            "tax_totals.igi_mxn": {"page": 2, "text_line": 6},
        },
        "validation": {"status": "passed"},
    }

    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment={"name": "ATT-MIXED", "parse_result_json": parsed},
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
    )

    clearance = [
        row
        for row in draft["components"]
        if row["fee_logical_key"] == "customs_clearance_fee"
    ]
    assert sum(Decimal(row["original_amount"]) for row in clearance) == Decimal("30")
    assert all(row["component_type"] == "CUSTOMS_SERVICE" for row in clearance)


def test_linked_refund_reverses_original_sku_tax_proportions_as_ledger_only() -> None:
    reversed_rows = service.build_refund_reversal_components(
        "15",
        [
            {
                "name": "COMP-1",
                "item": "ITEM-GLASSES",
                "stable_line_key": "LINE-GLASSES",
                "tax_code": "IVA",
                "currency": "MXN",
                "original_amount": "20",
                "amount_rmb": "10",
            },
            {
                "name": "COMP-2",
                "item": "ITEM-SUNGLASSES",
                "stable_line_key": "LINE-SUNGLASSES",
                "tax_code": "IVA",
                "currency": "MXN",
                "original_amount": "10",
                "amount_rmb": "5",
            },
        ],
    )

    assert [row["original_amount"] for row in reversed_rows] == ["-10.00", "-5.00"]
    assert [row["amount_rmb"] for row in reversed_rows] == ["-5", "-2.5"]
    assert [row["reverses_component"] for row in reversed_rows] == [
        "COMP-1",
        "COMP-2",
    ]
    assert all(row["accounting_role"] == "SETTLEMENT" for row in reversed_rows)
    assert all(row["cost_effect"] == "LEDGER_ONLY" for row in reversed_rows)


def test_components_are_grouped_by_their_own_logical_fee_key() -> None:
    grouped = service.group_components_by_fee_key(
        [
            {"fee_logical_key": "import_tax", "original_amount": "20"},
            {"fee_logical_key": "customs_clearance_fee", "original_amount": "30"},
            {"fee_logical_key": "import_tax", "original_amount": "10"},
        ]
    )

    assert list(grouped) == ["customs_clearance_fee", "import_tax"]
    assert [row["original_amount"] for row in grouped["import_tax"]] == ["20", "10"]


def test_refund_parent_must_be_a_valid_payment_for_the_same_fee_and_currency() -> None:
    refund = {
        "batch": "B1",
        "version": "V1",
        "fee_rule": "F1",
        "evidence_type": "REFUND",
        "accounting_role": "SETTLEMENT",
        "currency": "MXN",
    }
    payment = {
        "name": "PAYMENT-1",
        "batch": "B1",
        "version": "V1",
        "fee_rule": "F1",
        "evidence_type": "PAYMENT",
        "accounting_role": "SETTLEMENT",
        "currency": "MXN",
        "validation_status": "VALID",
    }

    assert service.validate_refund_parent(refund, payment)["name"] == "PAYMENT-1"
    with pytest.raises(ValueError, match="币种"):
        service.validate_refund_parent(refund, {**payment, "currency": "USD"})
    with pytest.raises(ValueError, match="原付款"):
        service.validate_refund_parent(refund, {**payment, "evidence_type": "QUOTE"})


def test_review_children_require_selected_evidence_and_final_role_is_consistent() -> None:
    with pytest.raises(ValueError, match="先确认凭证"):
        service.validate_review_selections(
            {"selected": False, "accounting_role": "REFERENCE", "is_final": 0},
            [{"logical_fee_key": "import_tax", "amount": "20", "currency": "MXN"}],
            [],
        )
    with pytest.raises(ValueError, match="最终账单"):
        service.validate_review_selections(
            {"selected": True, "accounting_role": "SETTLEMENT", "is_final": 1},
            [],
            [],
        )
    with pytest.raises(ValueError, match="实际费用"):
        service.validate_review_selections(
            {"selected": True, "accounting_role": "ESTIMATE", "is_final": 0},
            [{"logical_fee_key": "import_tax", "amount": "20", "currency": "MXN", "amount_status": "ACTUAL"}],
            [],
        )
    with pytest.raises(ValueError, match="实际费用"):
        service.validate_review_selections(
            {"selected": True, "accounting_role": "FINAL_BILL", "is_final": "0"},
            [{"logical_fee_key": "import_tax", "amount": "20", "currency": "MXN", "amount_status": "ACTUAL"}],
            [],
        )

    service.validate_review_selections(
        {"selected": True, "accounting_role": "FINAL_BILL", "is_final": 1},
        [{"logical_fee_key": "import_tax", "amount": "20", "currency": "MXN"}],
        [{"item": "ITEM-GLASSES", "original_amount": "10", "currency": "MXN"}],
    )


def test_review_edits_cannot_change_proposal_identity_or_source_evidence() -> None:
    draft = {
        "evidence": {
            "proposal_id": "evidence:classification",
            "attachment": "ATT-1",
            "evidence_type": "QUOTE",
            "accounting_role": "ESTIMATE",
        },
        "fee_splits": [
            {
                "proposal_id": "fee:import_tax",
                "logical_fee_key": "import_tax",
                "amount": "20",
                "currency": "MXN",
                "source_refs": [{"attachment": "ATT-1", "page": 2}],
            }
        ],
        "components": [
            {
                "proposal_id": "component:1",
                "fee_logical_key": "import_tax",
                "item": "ITEM-GLASSES",
                "original_amount": "10",
                "amount_rmb": "5",
                "source_evidence": {"attachment": "ATT-1", "row": 8},
            }
        ],
    }
    selections = ["evidence:classification", "fee:import_tax", "component:1"]
    edits = {
        "evidence:classification": {"currency": "USD", "attachment": "ATT-EVIL"},
        "fee:import_tax": {
            "amount": "21",
            "logical_fee_key": "customs_clearance_fee",
            "source_refs": [{"attachment": "ATT-EVIL"}],
        },
        "component:1": {
            "item": "ITEM-SUNGLASSES",
            "original_amount": "999",
            "amount_rmb": "999",
            "source_evidence": {"attachment": "ATT-EVIL"},
        },
    }

    evidence, fees, components = service._selected_proposals(draft, selections, edits)

    assert evidence["attachment"] == "ATT-1"
    assert evidence["currency"] == "USD"
    assert fees[0]["logical_fee_key"] == "import_tax"
    assert fees[0]["amount"] == "21"
    assert fees[0]["source_refs"][0]["attachment"] == "ATT-1"
    assert components[0]["item"] == "ITEM-SUNGLASSES"
    assert components[0]["original_amount"] == "10"
    assert components[0]["amount_rmb"] == "5"
    assert components[0]["source_evidence"]["attachment"] == "ATT-1"


class _StartRepository:
    def __init__(self, *, running=None, reusable=None):
        self.running = running
        self.reusable = reusable
        self.created = []
        self.commits = 0

    def get_context(self, batch_name, version_name):
        return {"batch": batch_name, "version": version_name, "transport_mode": "AIR", "fx_context": {}}

    def lock_batch(self, _batch_name):
        return None

    def get_attachment(self, batch_name, attachment_name):
        return {"name": attachment_name, "batch": batch_name, "file_name": "关税.pdf", "modified": "m1", "file_url": "/files/tax.pdf", "parse_status": "Parsed", "parse_result_json": "{}", "mapped_result_json": "{}"}

    def find_running(self, *_args):
        return self.running

    def find_reusable(self, *_args):
        return self.reusable

    def create_run(self, values):
        self.created.append(values)
        return {"name": "RUN-NEW", **values}

    def commit(self):
        self.commits += 1


def test_start_review_reuses_running_task_even_when_force_is_requested() -> None:
    repository = _StartRepository(running={"name": "RUN-1", "status": "RUNNING", "progress_revision": 4})
    enqueued = []

    result = service.start_fee_evidence_review(
        "B1", "V1", "import_tax", "ATT-1", "tax_certificate",
        force=True, repository=repository, enqueue=enqueued.append,
    )

    assert result == {"ok": True, "run_id": "RUN-1", "status": "RUNNING", "reused": True, "reuse_reason": "RUNNING", "progress_revision": 4}
    assert repository.created == []
    assert enqueued == []


def test_incremental_status_omits_large_draft_while_running_and_unchanged() -> None:
    class Repository:
        def get_run(self, _run_id):
            return {"name": "RUN-1", "batch": "B1", "version": "V1", "status": "RUNNING", "progress_revision": 7, "draft_json": {"large": "draft"}}

    result = service.get_fee_evidence_review_status("B1", "RUN-1", after_revision=7, repository=Repository())

    assert result["unchanged"] is True
    assert "draft" not in result
