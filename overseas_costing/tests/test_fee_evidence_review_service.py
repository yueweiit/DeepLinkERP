"""费用凭证审核、结算净额与 SKU 税种分项测试。"""

import json

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
            "quantity": "20",
            "unit": "PCS",
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
            "quantity": "10",
            "unit": "PCS",
        },
    ]


def _tax_attachment(*line_items: dict, total: str = "15") -> dict:
    return {
        "name": "ATT-MATRIX",
        "file_name": "完税凭证.pdf",
        "parse_result_json": {
            "parser": "mexico_tax_certificate_pedimento",
            "header": {"paid_total_mxn": total},
            "tax_totals": {"igi_mxn": total},
            "line_items": list(line_items),
            "source_evidence": {
                "header.paid_total_mxn": {"page": 1, "text_line": 2},
                "tax_totals.igi_mxn": {"page": 1, "text_line": 3},
            },
            "validation": {"status": "passed"},
        },
    }


def _resolved_cell(draft: dict, row_index: int, column_key: str) -> dict:
    return service.resolve_material_matrix_cell(
        draft["material_matrix"],
        draft["components"],
        component_store=draft.get("component_store"),
        row_index=row_index,
        column_key=column_key,
    )


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


def test_fee_split_evidence_prevents_document_total_from_double_counting() -> None:
    summary = service.summarize_evidence_ledger(
        [
            {
                "name": "E-SPLIT",
                "evidence_role": "fee_split",
                "validation_status": "VALID",
                "accounting_role": "FINAL_BILL",
                "original_amount": "30",
                "currency": "MXN",
                "direction": "DEBIT",
                "is_final": 1,
                "review_run": "RUN-1",
            },
            {
                "name": "E-TOTAL",
                "evidence_role": "tax_certificate",
                "validation_status": "VALID",
                "accounting_role": "FINAL_BILL",
                "original_amount": "70",
                "currency": "MXN",
                "direction": "DEBIT",
                "is_final": 1,
                "review_run": "RUN-1",
            },
        ],
        current_amount="30",
        current_status="ACTUAL",
    )

    assert summary["final_bill_by_currency"] == {"MXN": "30.00"}
    assert summary["effective_amount"] == "30.00"


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
    assert "component_store" not in draft
    assert "component_contract" not in draft
    assert {row["item"] for row in draft["item_options"]} == {
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    }
    assert all(row["source_evidence"] for row in draft["components"])


def test_material_matrix_has_fixed_columns_and_every_item_in_repository_order() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "10"},
                "source_evidence": {
                    "igi_amount_mxn": {"page": 3, "text_line": 20}
                },
            },
            total="10",
        ),
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
        ai_review={"line_item_matches": {"8": ["ITEM-GLASSES"]}},
    )

    matrix = draft["material_matrix"]
    assert [column["key"] for column in matrix["columns"]] == [
        "IGI",
        "IVA",
        "DTA",
        "PRV",
        "PRV_IVA",
        "CUSTOMS_SERVICE",
    ]
    assert [column["fee_logical_key"] for column in matrix["columns"]] == [
        "import_tax",
        "import_tax",
        "import_tax",
        "import_tax",
        "import_tax",
        "customs_clearance_fee",
    ]
    assert [row["item"] for row in matrix["rows"]] == [
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    ]
    assert {
        key: matrix["rows"][0][key]
        for key in (
            "item",
            "stable_line_key",
            "material_code",
            "product_name",
            "quantity",
            "unit",
            "hs_code",
        )
    } == {
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "material_code": "GL-01",
        "product_name": "眼镜",
        "quantity": "20",
        "unit": "PCS",
        "hs_code": "90041000",
    }
    assert list(matrix["rows"][0]["cells"]) == ["IGI"]
    assert matrix["rows"][1]["cells"] == {}
    assert matrix["empty_cell"] == {"proposals": [], "saved": []}


def test_material_matrix_empty_rows_use_sparse_cells_and_compact_shared_default() -> None:
    items = [
        {
            "name": f"ITEM-{index:05d}",
            "stable_line_key": f"LINE-{index:05d}",
            "material_code": f"M-{index:05d}",
            "product_name": "测试物料",
            "quantity": "1",
            "unit": "PCS",
            "hs_code": "90041000",
        }
        for index in range(10000)
    ]

    matrix = service.build_material_matrix(items=items, components=[])
    serialized = json.dumps(
        matrix, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")

    assert len(matrix["rows"]) == 10000
    assert all(row["cells"] == {} for row in matrix["rows"])
    assert matrix["empty_cell"] == {"proposals": [], "saved": []}
    assert len(serialized) < 5 * 1024 * 1024


def test_material_matrix_high_proposal_dedup_avoids_pairwise_ref_comparisons(
    monkeypatch,
) -> None:
    class CountingRef(dict):
        comparisons = 0

        def __eq__(self, other):
            type(self).comparisons += 1
            return super().__eq__(other)

    components = [
        {
            "proposal_id": f"component:{index}",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "component_type": "IMPORT_TAX",
            "fee_logical_key": "import_tax",
            "tax_code": "IGI",
            "currency": "MXN",
            "original_amount": "1",
            "amount_rmb": "0.5",
            "source_evidence": {"row": index},
            "needs_review": True,
        }
        for index in range(300)
    ]
    monkeypatch.setattr(
        service,
        "_component_source_refs",
        lambda component: [CountingRef({"row": component["source_evidence"]["row"]})],
    )

    matrix = service.build_material_matrix(items=_items(), components=components)

    assert matrix["rows"][0]["cells"]["IGI"] == {
        "proposals": list(range(300)),
        "saved": [],
    }
    resolved = service.resolve_material_matrix_cell(
        matrix,
        components,
        row_index=0,
        column_key="IGI",
    )
    assert resolved["original_amount"] == "300.00"
    assert resolved["suggested_amount_rmb"] == "150"
    assert len(resolved["source_proposal_ids"]) == 300
    assert len(resolved["source_refs"]) == 300
    assert CountingRef.comparisons < 2000


def test_material_matrix_cells_store_only_compact_component_references() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "10"},
            },
            {
                "row_no": 9,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "5"},
            },
            total="15",
        ),
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
        ai_review={
            "line_item_matches": {
                "8": ["ITEM-GLASSES"],
                "9": ["ITEM-GLASSES"],
            }
        },
    )

    matrix = draft["material_matrix"]
    assert matrix["rows"][0]["cells"]["IGI"] == {
        "proposals": [0, 1],
        "saved": [],
    }
    assert matrix["empty_cell"] == {"proposals": [], "saved": []}
    assert matrix["saved_components"] == []
    resolved = service.resolve_material_matrix_cell(
        matrix,
        draft["components"],
        row_index=0,
        column_key="IGI",
    )
    assert resolved["original_amount"] == "15.00"
    assert resolved["suggested_amount_rmb"] == "7.5"
    assert resolved["source_proposal_ids"] == ["component:1", "component:2"]
    assert len(resolved["source_refs"]) == 2
    assert resolved["has_warning"] is True


@pytest.fixture(scope="module")
def large_six_column_draft() -> dict:
    items = [
        {
            "name": f"ITEM-{index:05d}",
            "stable_line_key": f"LINE-{index:05d}",
            "material_code": f"M-{index:05d}",
            "product_name": "测试物料",
            "quantity": "1",
            "unit": "PCS",
            "hs_code": "90041000",
            "customs_declared_value_mxn": "1",
            "goods_value": "1",
        }
        for index in range(10000)
    ]
    tax_amounts = {
        "igi_amount_mxn": "10000",
        "iva_amount_mxn": "10000",
        "dta_amount_mxn": "10000",
        "prv_amount_mxn": "10000",
        "prv_iva_amount_mxn": "10000",
    }
    attachment = {
        "name": "ATT-LARGE-MATRIX",
        "file_name": "large-tax.pdf",
        "parse_result_json": {
            "parser": "mexico_tax_certificate_pedimento",
            "header": {"paid_total_mxn": "60000"},
            "tax_totals": {
                "igi_mxn": "10000",
                "iva_mxn": "10000",
                "dta_mxn": "10000",
                "prv_mxn": "10000",
                "prv_iva_mxn": "10000",
            },
            "line_items": [
                {
                    "row_no": 1,
                    "hs_code": "90041000",
                    "taxes": tax_amounts,
                }
            ],
            "service_fees": [
                {
                    "code": "broker_service",
                    "amount_mxn": "10000",
                }
            ],
            "validation": {"status": "passed"},
        },
    }
    return service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=attachment,
        items=items,
        fx_context={"fx_rmb_to_mxn": "2"},
    )


def test_large_draft_uses_auditable_bounded_component_storage(
    large_six_column_draft: dict,
) -> None:
    draft = large_six_column_draft
    serialized = json.dumps(
        draft, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")

    assert draft["components"] == []
    assert draft["component_contract"] == {
        "mode": "INDEXED_COLUMNS_V1",
        "component_count": 60000,
        "legacy_components_included": False,
        "legacy_component_limit": service.LEGACY_COMPONENT_LIMIT,
        "max_draft_bytes": service.FEE_EVIDENCE_DRAFT_MAX_BYTES,
    }
    assert draft["component_store"]["format"] == "INDEXED_COLUMNS_V1"
    assert draft["component_store"]["count"] == 60000
    assert draft["summary"]["component_proposal_count"] == 60000
    assert all(len(row["cells"]) == 6 for row in draft["material_matrix"]["rows"])
    assert len(serialized) < 8 * 1024 * 1024


def test_large_draft_matrix_resolves_and_confirms_compact_components(
    large_six_column_draft: dict,
) -> None:
    draft = large_six_column_draft
    first = service.resolve_material_matrix_cell(
        draft["material_matrix"],
        draft["components"],
        component_store=draft["component_store"],
        row_index=0,
        column_key="IGI",
    )
    last = service.resolve_material_matrix_cell(
        draft["material_matrix"],
        draft["components"],
        component_store=draft["component_store"],
        row_index=9999,
        column_key="CUSTOMS_SERVICE",
    )

    assert first["original_amount"] == "1.00"
    assert first["amount_rmb"] == "0.5"
    assert first["source_proposal_ids"] == ["component:1"]
    assert first["source_refs"][0]["tax_code"] == "IGI"
    assert first["has_warning"] is True
    assert last["original_amount"] == "1.00"
    assert last["source_proposal_ids"] == ["component:60000"]
    assert last["source_refs"][0]["service_code"] == "broker_service"

    _, _, selected_components = service._selected_proposals(
        draft,
        ["component:1", "component:60000"],
        {},
    )
    assert [row["proposal_id"] for row in selected_components] == [
        "component:1",
        "component:60000",
    ]
    assert selected_components[0]["original_amount"] == "1.00"
    assert selected_components[0]["source_evidence"]["tax_code"] == "IGI"
    assert selected_components[1]["source_evidence"]["service_code"] == (
        "broker_service"
    )


def test_large_ready_status_returns_compact_draft_without_expansion(
    large_six_column_draft: dict,
) -> None:
    class Repository:
        @staticmethod
        def get_run(_run_id):
            return {
                "name": "RUN-LARGE",
                "batch": "BATCH-LARGE",
                "version": "VERSION-LARGE",
                "logical_fee_key": "import_tax",
                "status": "READY",
                "progress_revision": 1,
                "draft_json": json.dumps(
                    large_six_column_draft,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
            }

    status = service.get_fee_evidence_review_status(
        "BATCH-LARGE",
        "RUN-LARGE",
        repository=Repository(),
    )
    returned = status["draft"]
    serialized = json.dumps(
        returned, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")

    assert returned["components"] == []
    assert returned["component_store"]["count"] == 60000
    assert len(serialized) <= service.FEE_EVIDENCE_DRAFT_MAX_BYTES


def test_component_contract_rejects_unpersistable_oversized_draft_explicitly() -> None:
    draft = {
        "components": [
            {
                "proposal_id": "component:1",
                "source_evidence": {
                    "text": "x" * service.FEE_EVIDENCE_DRAFT_MAX_BYTES
                },
            }
        ]
    }

    with pytest.raises(ValueError, match="安全上限"):
        service._finalize_component_contract(draft)


def test_component_expansion_count_budget_rejects_before_allocators(
    monkeypatch,
) -> None:
    items = [
        {
            "name": f"ITEM-{index}",
            "stable_line_key": f"LINE-{index}",
            "hs_code": "90041000",
            "customs_declared_value_mxn": "1",
            "goods_value": "1",
        }
        for index in range(10001)
    ]
    attachment = {
        "name": "ATT-OVER-BUDGET",
        "parse_result_json": {
            "parser": "mexico_tax_certificate_pedimento",
            "header": {"paid_total_mxn": "6"},
            "tax_totals": {"igi_mxn": "1"},
            "line_items": [
                {
                    "row_no": 1,
                    "hs_code": "90041000",
                    "taxes": {
                        "igi_amount_mxn": "1",
                        "iva_amount_mxn": "1",
                        "dta_amount_mxn": "1",
                        "prv_amount_mxn": "1",
                        "prv_iva_amount_mxn": "1",
                    },
                }
            ],
            "service_fees": [{"code": "broker", "amount_mxn": "1"}],
            "validation": {"status": "passed"},
        },
    }
    allocator_called = False

    def unexpected_allocator(*_args, **_kwargs):
        nonlocal allocator_called
        allocator_called = True
        raise AssertionError("allocator must not run after expansion budget failure")

    monkeypatch.setattr(
        service,
        "allocate_tax_certificate_components",
        unexpected_allocator,
    )
    monkeypatch.setattr(
        service,
        "allocate_service_fee_components",
        unexpected_allocator,
    )

    with pytest.raises(ValueError, match="分项展开数量.*60000"):
        service.build_fee_evidence_review_draft(
            logical_fee_key="import_tax",
            attachment=attachment,
            items=items,
        )

    assert allocator_called is False


def test_component_expansion_byte_budget_rejects_large_source_before_allocation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service,
        "FEE_EVIDENCE_COMPONENT_EXPANSION_MAX_BYTES",
        512,
        raising=False,
    )
    attachment = _tax_attachment(
        {
            "row_no": 1,
            "hs_code": "90041000",
            "taxes": {"igi_amount_mxn": "1"},
            "source_evidence": {
                "igi_amount_mxn": {"region": "x" * 1024}
            },
        },
        total="1",
    )
    allocator_called = False

    def unexpected_allocator(*_args, **_kwargs):
        nonlocal allocator_called
        allocator_called = True
        raise AssertionError("allocator must not run after expansion budget failure")

    monkeypatch.setattr(
        service,
        "allocate_tax_certificate_components",
        unexpected_allocator,
    )
    monkeypatch.setattr(
        service,
        "allocate_service_fee_components",
        unexpected_allocator,
    )

    with pytest.raises(ValueError, match="分项展开预算"):
        service.build_fee_evidence_review_draft(
            logical_fee_key="import_tax",
            attachment=attachment,
            items=[_items()[0]],
        )

    assert allocator_called is False


def test_match_plan_indexes_10000_one_to_one_lines_once_and_is_reused(
    monkeypatch,
) -> None:
    item_count = 10000
    items = [
        {
            "name": f"ITEM-{index:05d}",
            "stable_line_key": f"LINE-{index:05d}",
            "hs_code": str(10000000 + index),
            "customs_declared_value_mxn": "1",
            "goods_value": "1",
        }
        for index in range(item_count)
    ]
    lines = [
        {
            "row_no": index + 1,
            "hs_code": str(10000000 + index),
            "taxes": {"igi_amount_mxn": "1"},
        }
        for index in range(item_count)
    ]
    service_fees = [
        {
            "code": "broker_service",
            "amount_mxn": "1",
            "item_names": ["ITEM-00000"],
        }
    ]
    normalize_calls = 0
    original_normalize = service._normalize_hs

    def counted_normalize(value):
        nonlocal normalize_calls
        normalize_calls += 1
        if normalize_calls > item_count * 2 + 10:
            raise AssertionError("HS matching rescanned the item collection")
        return original_normalize(value)

    monkeypatch.setattr(service, "_normalize_hs", counted_normalize)

    match_plan = service._validate_component_expansion_budget(
        line_items=lines,
        service_fees=service_fees,
        items=items,
        source_ref={"attachment": "ATT-10K"},
        explicit_matches={},
    )
    tax_result = service.allocate_tax_certificate_components(
        lines,
        items,
        source_ref={"attachment": "ATT-10K"},
        match_plan=match_plan,
    )
    service_result = service.allocate_service_fee_components(
        service_fees,
        items,
        source_ref={"attachment": "ATT-10K"},
        match_plan=match_plan,
    )

    assert match_plan["proposal_count"] == item_count + 1
    assert len(tax_result["components"]) == item_count
    assert len(service_result["components"]) == 1
    assert normalize_calls == item_count * 2


def test_draft_builder_passes_one_preflight_match_plan_to_both_allocators(
    monkeypatch,
) -> None:
    match_plan = {
        "proposal_count": 0,
        "estimated_bytes": 0,
        "tax_matches": [],
        "service_matches": [],
        "items_by_name": {},
    }
    received = []

    monkeypatch.setattr(
        service,
        "_validate_component_expansion_budget",
        lambda **_kwargs: match_plan,
    )

    def tax_allocator(*_args, **kwargs):
        received.append(kwargs.get("match_plan"))
        return {
            "components": [],
            "unmatched_lines": [],
            "needs_review": False,
            "allocation_basis": "",
            "missing_fx": False,
        }

    def service_allocator(*_args, **kwargs):
        received.append(kwargs.get("match_plan"))
        return {
            "components": [],
            "unmatched_lines": [],
            "needs_review": False,
            "reason_code": "",
            "missing_fx": False,
        }

    monkeypatch.setattr(service, "allocate_tax_certificate_components", tax_allocator)
    monkeypatch.setattr(service, "allocate_service_fee_components", service_allocator)

    service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "1"},
            },
            total="1",
        ),
        items=[_items()[0]],
    )

    assert received == [match_plan, match_plan]


def _valid_component_store() -> dict:
    return service._build_component_store(
        [
            {"proposal_id": "component:1", "item": "ITEM-1"},
            {"proposal_id": "component:2", "item": "ITEM-2"},
        ]
    )


def test_indexed_store_rejects_abnormal_count() -> None:
    store = {
        "format": "INDEXED_COLUMNS_V1",
        "count": 10**9,
        "columns": {},
    }

    with pytest.raises(ValueError, match="count|数量"):
        service._validate_component_store(store)


def test_abnormal_store_count_is_rejected_by_finalize_resolve_and_apply() -> None:
    store = {
        "format": "INDEXED_COLUMNS_V1",
        "count": 10**9,
        "columns": {},
    }
    draft = {
        "evidence": {},
        "fee_splits": [],
        "components": [],
        "component_store": store,
        "component_contract": {
            "mode": "INDEXED_COLUMNS_V1",
            "component_count": 10**9,
        },
    }
    matrix = {
        "rows": [
            {
                "hs_code": "",
                "hs_suggestion_details": [],
                "cells": {"IGI": {"proposals": [0], "saved": []}},
            }
        ],
        "saved_components": [],
    }

    with pytest.raises(ValueError, match="count|数量"):
        service._finalize_component_contract(draft)
    with pytest.raises(ValueError, match="count|数量"):
        service.resolve_material_matrix_cell(
            matrix,
            [],
            component_store=store,
            row_index=0,
            column_key="IGI",
        )
    with pytest.raises(ValueError, match="count|数量"):
        service._selected_proposals(draft, ["component:1"], {})


def test_indexed_store_rejects_dense_column_length_mismatch() -> None:
    store = _valid_component_store()
    store["columns"]["proposal_id"] = {"values": ["component:1"]}

    with pytest.raises(ValueError, match="长度"):
        service._validate_component_store(store)


@pytest.mark.parametrize("rows", ([1, 0], [0, 0], [2]))
def test_indexed_store_rejects_invalid_sparse_rows(rows: list[int]) -> None:
    store = _valid_component_store()
    store["columns"]["optional"] = {"constant": "x", "rows": rows}

    with pytest.raises(ValueError, match="rows|行索引"):
        service._validate_component_store(store)


def test_indexed_store_rejects_invalid_dictionary_index() -> None:
    store = _valid_component_store()
    store["columns"]["item"] = {
        "dictionary": ["ITEM-1"],
        "indices": [0, 1],
    }

    with pytest.raises(ValueError, match="dictionary|字典"):
        service._validate_component_store(store)


@pytest.mark.parametrize(
    "proposal_column",
    [
        None,
        {"values": ["component:1", "component:1"]},
        {"values": ["component:1", ""]},
    ],
)
def test_indexed_store_requires_dense_unique_nonempty_proposal_ids(
    proposal_column,
) -> None:
    store = _valid_component_store()
    if proposal_column is None:
        del store["columns"]["proposal_id"]
    else:
        store["columns"]["proposal_id"] = proposal_column

    with pytest.raises(ValueError, match="proposal_id"):
        service._validate_component_store(store)


def test_indexed_apply_uses_validated_proposal_lookup_without_blind_scan(
    monkeypatch,
) -> None:
    store = _valid_component_store()
    draft = {
        "evidence": {},
        "fee_splits": [],
        "components": [],
        "component_store": store,
        "component_contract": {
            "mode": "INDEXED_COLUMNS_V1",
            "component_count": 2,
        },
    }
    decoded = []
    proposal_reads = []
    original_row = service._component_store_row
    original_value = service._component_store_value
    monkeypatch.setattr(
        service,
        "_validate_component_store",
        lambda _store: {"component:1": 0, "component:2": 1},
    )

    def tracked_row(component_store, row_index):
        decoded.append(row_index)
        return original_row(component_store, row_index)

    def tracked_value(component_store, fieldname, row_index):
        if fieldname == "proposal_id":
            proposal_reads.append(row_index)
        return original_value(component_store, fieldname, row_index)

    monkeypatch.setattr(service, "_component_store_row", tracked_row)
    monkeypatch.setattr(
        service,
        "_component_store_value",
        tracked_value,
    )

    _, _, selected = service._selected_proposals(
        draft,
        ["component:2"],
        {},
    )

    assert [row["proposal_id"] for row in selected] == ["component:2"]
    assert decoded == [1]
    assert proposal_reads == [1]


def test_material_matrix_computes_component_routing_once_per_collected_row(
    monkeypatch,
) -> None:
    component = {
        "proposal_id": "component:1",
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "component_type": "IMPORT_TAX",
        "fee_logical_key": "import_tax",
        "tax_code": "IGI",
        "currency": "MXN",
        "original_amount": "10",
        "amount_rmb": "5",
    }
    calls = 0
    original = service._matrix_component_route

    def counted_route(row):
        nonlocal calls
        calls += 1
        return original(row)

    monkeypatch.setattr(service, "_matrix_component_route", counted_route)

    service.build_material_matrix(items=_items(), components=[component])

    assert calls == 1


def test_populated_ten_thousand_row_matrix_stays_under_eight_mib() -> None:
    items = [
        {
            "name": f"ITEM-{index:05d}",
            "stable_line_key": f"LINE-{index:05d}",
            "material_code": f"M-{index:05d}",
            "product_name": "测试物料",
            "quantity": "1",
            "unit": "PCS",
            "hs_code": "90041000",
        }
        for index in range(10000)
    ]
    components = []
    for item in items:
        for column in ("IGI", "IVA", "DTA", "PRV", "PRV_IVA"):
            components.append(
                {
                    "item": item["name"],
                    "stable_line_key": item["stable_line_key"],
                    "component_type": "IMPORT_TAX",
                    "fee_logical_key": "import_tax",
                    "tax_code": column,
                    "currency": "MXN",
                    "original_amount": "1",
                    "amount_rmb": "0.5",
                }
            )
        components.append(
            {
                "item": item["name"],
                "stable_line_key": item["stable_line_key"],
                "component_type": "CUSTOMS_SERVICE",
                "fee_logical_key": "customs_clearance_fee",
                "tax_code": "",
                "currency": "MXN",
                "original_amount": "1",
                "amount_rmb": "0.5",
            }
        )

    matrix = service.build_material_matrix(items=items, components=components)
    serialized = json.dumps(
        matrix, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")

    assert all(len(row["cells"]) == 6 for row in matrix["rows"])
    assert len(serialized) < 8 * 1024 * 1024


def test_material_matrix_uses_complete_raw_items_without_expanding_ai_scope() -> None:
    raw_items = _items()
    projected_items = [
        {
            "name": "ITEM-GLASSES",
            "material_code": "GL-01",
            "product_name": "投影后眼镜",
            "goods_value": "400",
            "customs_declared_value_mxn": "200",
        }
    ]

    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "10"},
                "source_evidence": {
                    "igi_amount_mxn": {"page": 3, "text_line": 20}
                },
            },
            total="10",
        ),
        items=projected_items,
        matrix_items=raw_items,
        fx_context={"fx_rmb_to_mxn": "2"},
        ai_review={"line_item_matches": {"8": ["ITEM-GLASSES"]}},
    )

    assert [component["item"] for component in draft["components"]] == [
        "ITEM-GLASSES"
    ]
    assert [row["item"] for row in draft["material_matrix"]["rows"]] == [
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    ]
    second_row = draft["material_matrix"]["rows"][1]
    assert {
        key: second_row[key] for key in ("stable_line_key", "hs_code", "unit")
    } == {
        "stable_line_key": "LINE-SUNGLASSES",
        "hs_code": "90041000",
        "unit": "PCS",
    }


def test_material_matrix_aggregates_soft_anomaly_component_suggestions() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "10"},
            },
            {
                "row_no": 9,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "5"},
            },
            total="15",
        ),
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
        ai_review={
            "line_item_matches": {
                "8": ["ITEM-GLASSES"],
                "9": ["ITEM-GLASSES"],
            }
        },
    )

    proposals = [
        component
        for component in draft["components"]
        if component["item"] == "ITEM-GLASSES" and component["tax_code"] == "IGI"
    ]
    assert proposals and all(component["default_selected"] is False for component in proposals)
    assert all(component["needs_review"] is True for component in proposals)
    cell = _resolved_cell(draft, 0, "IGI")
    assert cell["original_amount"] == "15.00"
    assert cell["amount_rmb"] == "7.5"
    assert cell["suggested_amount_rmb"] == "7.5"
    assert cell["origin"] == "AI"
    assert cell["source_proposal_ids"] == ["component:1", "component:2"]
    assert len(cell["source_refs"]) == 2
    assert cell["has_warning"] is True


def test_material_matrix_saved_value_precedes_new_suggestion() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "10"},
                "source_evidence": {
                    "igi_amount_mxn": {"page": 3, "text_line": 20}
                },
            },
            total="10",
        ),
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
        ai_review={"line_item_matches": {"8": ["ITEM-GLASSES"]}},
        existing_components=[
            {
                "name": "COMP-SAVED",
                "item": "ITEM-GLASSES",
                "stable_line_key": "LINE-GLASSES",
                "logical_fee_key": "import_tax",
                "component_type": "IMPORT_TAX",
                "tax_code": "IGI",
                "hs_code": "90041000",
                "currency": "MXN",
                "original_amount": "198",
                "amount_rmb": "99",
                "status": "CONFIRMED",
                "source_evidence": {"attachment": "ATT-OLD", "row": 2},
                "confidence": "1",
            }
        ],
    )

    matrix = draft["material_matrix"]
    assert matrix["rows"][0]["cells"]["IGI"] == {
        "proposals": [0],
        "saved": [0],
    }
    assert matrix["saved_components"][0]["id"] == "COMP-SAVED"
    assert matrix["saved_components"][0]["source_refs"] == [
        {"attachment": "ATT-OLD", "row": 2}
    ]
    cell = _resolved_cell(draft, 0, "IGI")
    assert cell["origin"] == "SAVED"
    assert cell["status"] == "CONFIRMED"
    assert cell["original_amount"] == "198.00"
    assert cell["amount_rmb"] == "99"
    assert cell["suggested_original_amount"] == "10.00"
    assert cell["suggested_amount_rmb"] == "5"
    assert cell["source_proposal_ids"] == ["component:1"]
    assert cell["saved_component_ids"] == ["COMP-SAVED"]
    assert cell["saved_source_refs"] == [{"attachment": "ATT-OLD", "row": 2}]


def test_material_matrix_keeps_current_hs_and_exposes_voucher_hs_difference() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "99999999",
                "taxes": {"igi_amount_mxn": "10"},
                "source_evidence": {
                    "igi_amount_mxn": {"page": 3, "text_line": 20}
                },
            },
            total="10",
        ),
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
        ai_review={"line_item_matches": {"8": ["ITEM-GLASSES"]}},
    )

    row = draft["material_matrix"]["rows"][0]
    assert row["hs_code"] == "90041000"
    assert row["hs_suggestions"] == ["99999999"]
    assert row["hs_suggestion_details"] == [
        {"hs_code": "99999999", "proposals": [0], "saved": []}
    ]
    cell = _resolved_cell(draft, 0, "IGI")
    assert cell["has_warning"] is True
    assert "99999999" in cell["warning"]


def test_material_matrix_keeps_unmatched_lines_outside_material_rows() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 77,
                "hs_code": "12345678",
                "taxes": {"igi_amount_mxn": "10"},
            },
            total="10",
        ),
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
    )

    matrix = draft["material_matrix"]
    assert [row["item"] for row in matrix["rows"]] == [
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    ]
    assert all(row["cells"] == {} for row in matrix["rows"])
    assert matrix["unmatched_lines"] == draft["unmatched_lines"]
    assert matrix["unmatched_lines"][0]["row_no"] == 77
    assert matrix["unmatched_lines"][0]["reason_code"] == "SKU_MATCH_REQUIRED"


def test_material_matrix_missing_fx_keeps_rmb_blank() -> None:
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment=_tax_attachment(
            {
                "row_no": 8,
                "hs_code": "90041000",
                "taxes": {"igi_amount_mxn": "10"},
                "source_evidence": {
                    "igi_amount_mxn": {"page": 3, "text_line": 20}
                },
            },
            total="10",
        ),
        items=_items(),
        fx_context={},
        ai_review={"line_item_matches": {"8": ["ITEM-GLASSES"]}},
    )

    cell = _resolved_cell(draft, 0, "IGI")
    assert cell["original_amount"] == "10.00"
    assert cell["amount_rmb"] is None
    assert cell["suggested_amount_rmb"] is None
    assert cell["missing_fx"] is True
    assert draft["material_matrix"]["missing_fx"] is True


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"original_amount": ""}, "MATERIAL_MATRIX_ORIGINAL_AMOUNT_INVALID"),
        ({"original_amount": "NaN"}, "MATERIAL_MATRIX_ORIGINAL_AMOUNT_INVALID"),
        ({"original_amount": "-1"}, "MATERIAL_MATRIX_ORIGINAL_AMOUNT_INVALID"),
        ({"currency": "EUR"}, "MATERIAL_MATRIX_CURRENCY_UNSUPPORTED"),
        ({"currency": ""}, "MATERIAL_MATRIX_CURRENCY_UNSUPPORTED"),
        ({"amount_rmb": "-1"}, "MATERIAL_MATRIX_RMB_AMOUNT_INVALID"),
        ({"amount_rmb": "NaN"}, "MATERIAL_MATRIX_RMB_AMOUNT_INVALID"),
        ({"currency": "RMB", "amount_rmb": None}, "MATERIAL_MATRIX_RMB_AMOUNT_REQUIRED"),
    ],
)
def test_material_matrix_rejects_structurally_invalid_components(
    overrides: dict, reason_code: str
) -> None:
    component = {
        "proposal_id": "component:invalid",
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "component_type": "IMPORT_TAX",
        "tax_code": "IGI",
        "currency": "MXN",
        "original_amount": "10",
        "amount_rmb": "5",
        "source_evidence": {"attachment": "ATT-1", "row": 8},
        **overrides,
    }

    matrix = service.build_material_matrix(items=_items(), components=[component])

    assert matrix["rows"][0]["cells"] == {}
    assert matrix["unmatched_lines"][0]["reason_code"] == reason_code
    assert matrix["unmatched_lines"][0]["proposal_id"] == "component:invalid"
    assert matrix["unmatched_lines"][0]["source_refs"] == [
        {"attachment": "ATT-1", "row": 8}
    ]


@pytest.mark.parametrize(
    "routing",
    [
        {
            "component_type": "IMPORT_TAX",
            "logical_fee_key": "import_tax",
            "tax_code": "CUSTOMS_SERVICE",
        },
        {
            "component_type": "IMPORT_TAX",
            "logical_fee_key": "customs_clearance_fee",
            "tax_code": "IGI",
        },
        {
            "component_type": "CUSTOMS_SERVICE",
            "logical_fee_key": "customs_clearance_fee",
            "tax_code": "IGI",
        },
        {
            "component_type": "CUSTOMS_SERVICE",
            "logical_fee_key": "import_tax",
            "tax_code": "",
        },
    ],
)
def test_material_matrix_isolates_conflicting_component_routing(routing: dict) -> None:
    component = {
        "proposal_id": "component:conflict",
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "currency": "MXN",
        "original_amount": "10",
        "amount_rmb": "5",
        "source_evidence": {"attachment": "ATT-1", "row": 8},
        **routing,
    }

    matrix = service.build_material_matrix(items=_items(), components=[component])

    assert matrix["rows"][0]["cells"] == {}
    assert matrix["unmatched_lines"][0]["reason_code"] == (
        "MATERIAL_MATRIX_COMPONENT_CONFLICT"
    )
    assert matrix["unmatched_lines"][0]["proposal_id"] == "component:conflict"


def test_material_matrix_intentionally_excludes_refund_reversals_as_ledger_only() -> None:
    matrix = service.build_material_matrix(
        items=_items(),
        components=[
            {
                "proposal_id": "component:refund",
                "item": "ITEM-GLASSES",
                "stable_line_key": "LINE-GLASSES",
                "component_type": "REFUND_REVERSAL",
                "accounting_role": "SETTLEMENT",
                "cost_effect": "LEDGER_ONLY",
                "tax_code": "IGI",
                "currency": "MXN",
                "original_amount": "-10",
                "amount_rmb": "-5",
                "source_evidence": {"reverses_component": "COMP-1"},
            }
        ],
    )

    assert matrix["rows"][0]["cells"] == {}
    assert matrix["unmatched_lines"][0]["reason_code"] == "MATERIAL_MATRIX_LEDGER_ONLY"
    assert matrix["component_policy"]["ledger_only"] == "UNMATCHED"
    assert matrix["component_policy"]["negative_amounts"] == "UNMATCHED"


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


def test_legacy_component_item_edit_records_manual_review_provenance(
    monkeypatch,
) -> None:
    monkeypatch.setattr(service, "_session_user", lambda: "reviewer@example.com")

    _evidence, _fee_rows, components = service._selected_proposals(
        {
            "evidence": {
                "proposal_id": "evidence:classification",
                "evidence_type": "FINAL_INVOICE",
                "accounting_role": "FINAL_BILL",
            },
            "fee_splits": [],
            "components": [
                {
                    "proposal_id": "component:1",
                    "item": "ITEM-GLASSES",
                    "source_refs": [{"attachment": "ATT-1", "row": 2}],
                }
            ],
        },
        ["evidence:classification", "component:1"],
        {"component:1": {"item": "ITEM-SUNGLASSES"}},
    )

    assert components[0]["item"] == "ITEM-SUNGLASSES"
    assert components[0]["human_edits"] == ["item"]
    assert components[0]["source_refs"][-1] == {
        "type": "MANUAL_REVIEW",
        "field": "item",
        "operator": "reviewer@example.com",
        "from": "ITEM-GLASSES",
        "to": "ITEM-SUNGLASSES",
    }


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


def test_invalid_service_row_does_not_discard_valid_sibling_from_matrix() -> None:
    parsed = {
        "parser": "mexico_tax_certificate_pedimento",
        "header": {"paid_total_mxn": "30"},
        "tax_totals": {},
        "service_fees": [
            {
                "code": "invalid_negative",
                "amount_mxn": "-5",
                "source_evidence": {"page": 2, "text_line": 7},
            },
            {
                "code": "broker_service",
                "amount_mxn": "30",
                "item_names": ["ITEM-GLASSES"],
                "source_evidence": {"page": 2, "text_line": 8},
            },
        ],
        "source_evidence": {
            "header.paid_total_mxn": {"page": 2, "text_line": 10},
        },
        "validation": {"status": "passed"},
    }

    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="customs_clearance_fee",
        attachment={"name": "ATT-MIXED-SERVICE", "parse_result_json": parsed},
        items=_items(),
        fx_context={"fx_rmb_to_mxn": "2"},
    )

    clearance = [
        row
        for row in draft["components"]
        if row["fee_logical_key"] == "customs_clearance_fee"
    ]
    assert [row["item"] for row in clearance] == ["ITEM-GLASSES"]
    cell = _resolved_cell(draft, 0, "CUSTOMS_SERVICE")
    assert cell["original_amount"] == "30.00"
    assert cell["amount_rmb"] == "15"
    assert draft["unmatched_lines"] == [
        {
            "service_row": 1,
            "service_code": "invalid_negative",
            "reason_code": "SERVICE_AMOUNT_INVALID",
            "message": "清关服务费金额无效。",
            "source_evidence": {"page": 2, "text_line": 7},
        }
    ]


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


def test_unique_refund_parent_adds_reviewable_sku_reversal_proposals() -> None:
    draft = {
        "evidence": {
            "proposal_id": "evidence:classification",
            "evidence_type": "REFUND",
            "accounting_role": "SETTLEMENT",
            "direction": "CREDIT",
            "currency": "MXN",
            "original_amount": "15",
            "default_selected": True,
            "source_refs": [{"attachment": "ATT-R", "page": 1, "text_line": 8}],
        },
        "components": [],
        "summary": {"component_proposal_count": 0},
    }
    payment = {
        "name": "PAYMENT-1",
        "batch": "B1",
        "version": "V1",
        "fee_rule": "F1",
        "attachment": "ATT-P",
        "evidence_type": "PAYMENT",
        "accounting_role": "SETTLEMENT",
        "currency": "MXN",
        "original_amount": "30",
        "validation_status": "VALID",
    }
    original_components = [
        {
            "name": "C1",
            "logical_fee_key": "import_tax",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "currency": "MXN",
            "original_amount": "20",
            "amount_rmb": "10",
        },
        {
            "name": "C2",
            "logical_fee_key": "import_tax",
            "item": "ITEM-SUNGLASSES",
            "stable_line_key": "LINE-SUNGLASSES",
            "currency": "MXN",
            "original_amount": "10",
            "amount_rmb": "5",
        },
    ]

    result = service.add_refund_review_proposals(
        draft,
        batch_name="B1",
        version_name="V1",
        fee_rule="F1",
        candidates=[payment],
        components_by_evidence={"PAYMENT-1": original_components},
    )

    assert result["evidence"]["related_evidence"] == "PAYMENT-1"
    assert result["refund_parent_options"] == [payment]
    assert [row["original_amount"] for row in result["components"]] == [
        "-10.00",
        "-5.00",
    ]
    assert all(row["fee_logical_key"] == "import_tax" for row in result["components"])
    assert all(row["default_selected"] for row in result["components"])


def test_large_indexed_draft_keeps_original_and_refund_components_in_one_contract() -> None:
    draft = service._finalize_component_contract(
        {
            "evidence": {
                "proposal_id": "evidence:classification",
                "evidence_type": "REFUND",
                "accounting_role": "SETTLEMENT",
                "direction": "CREDIT",
                "currency": "MXN",
                "original_amount": "5",
                "default_selected": True,
                "source_refs": [
                    {"attachment": "ATT-R", "page": 1, "text_line": 8}
                ],
            },
            "components": [
                {
                    "proposal_id": f"component:{index + 1}",
                    "fee_logical_key": "import_tax",
                    "item": "ITEM-GLASSES",
                    "stable_line_key": "LINE-GLASSES",
                    "component_type": "IMPORT_TAX",
                    "accounting_role": "FINAL_BILL",
                    "cost_effect": "COST",
                    "tax_code": "IGI",
                    "currency": "MXN",
                    "original_amount": "1",
                    "amount_rmb": "0.5",
                }
                for index in range(service.LEGACY_COMPONENT_LIMIT + 1)
            ],
            "summary": {
                "component_proposal_count": service.LEGACY_COMPONENT_LIMIT + 1
            },
        }
    )
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

    result = service.add_refund_review_proposals(
        draft,
        batch_name="B1",
        version_name="V1",
        fee_rule="F1",
        candidates=[payment],
        components_by_evidence={
            "PAYMENT-1": [
                {
                    "name": "PARENT-COMPONENT",
                    "logical_fee_key": "import_tax",
                    "item": "ITEM-GLASSES",
                    "stable_line_key": "LINE-GLASSES",
                    "currency": "MXN",
                    "original_amount": "10",
                    "amount_rmb": "5",
                }
            ]
        },
    )

    assert result["components"] == []
    assert result["component_store"]["count"] == service.LEGACY_COMPONENT_LIMIT + 2
    assert result["component_contract"]["component_count"] == (
        service.LEGACY_COMPONENT_LIMIT + 2
    )
    assert result["summary"]["component_proposal_count"] == (
        service.LEGACY_COMPONENT_LIMIT + 2
    )
    _, _, selected = service._selected_proposals(
        result,
        ["component:1", "refund-component:1"],
        {},
    )
    assert [row["proposal_id"] for row in selected] == [
        "component:1",
        "refund-component:1",
    ]
    assert selected[0]["original_amount"] == "1"
    assert selected[1]["original_amount"] == "-5.00"


def test_ambiguous_refund_parent_stays_unlinked_and_requires_review() -> None:
    draft = {
        "evidence": {
            "evidence_type": "REFUND",
            "accounting_role": "SETTLEMENT",
            "currency": "MXN",
            "original_amount": "15",
        },
        "components": [],
        "summary": {},
    }
    candidates = [
        {
            "name": name,
            "batch": "B1",
            "version": "V1",
            "fee_rule": "F1",
            "evidence_type": "PAYMENT",
            "accounting_role": "SETTLEMENT",
            "currency": "MXN",
            "validation_status": "VALID",
        }
        for name in ("P1", "P2")
    ]

    result = service.add_refund_review_proposals(
        draft,
        batch_name="B1",
        version_name="V1",
        fee_rule="F1",
        candidates=candidates,
        components_by_evidence={},
    )

    assert not result["evidence"].get("related_evidence")
    assert result["evidence"]["needs_review"] is True
    assert result["components"] == []


def test_ambiguous_refund_parents_expose_unselected_reversal_choices() -> None:
    draft = {
        "evidence": {
            "evidence_type": "REFUND",
            "accounting_role": "SETTLEMENT",
            "direction": "CREDIT",
            "currency": "MXN",
            "original_amount": "5",
            "source_refs": [{"attachment": "R1", "page": 1, "text_line": 2}],
        },
        "components": [],
        "summary": {},
    }
    candidates = [
        {
            "name": name,
            "batch": "B1",
            "version": "V1",
            "fee_rule": "F1",
            "evidence_type": "PAYMENT",
            "accounting_role": "SETTLEMENT",
            "direction": "DEBIT",
            "currency": "MXN",
            "validation_status": "VALID",
        }
        for name in ("P1", "P2")
    ]
    components = {
        name: [
            {
                "name": f"C-{name}",
                "logical_fee_key": "import_tax",
                "item": "ITEM-GLASSES",
                "currency": "MXN",
                "original_amount": "10",
                "amount_rmb": "5",
            }
        ]
        for name in ("P1", "P2")
    }

    result = service.add_refund_review_proposals(
        draft,
        batch_name="B1",
        version_name="V1",
        fee_rule="F1",
        candidates=candidates,
        components_by_evidence=components,
    )

    assert {row["refund_parent"] for row in result["components"]} == {"P1", "P2"}
    assert all(row["default_selected"] is False for row in result["components"])


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

    def materialize_fee_rule(self, _batch_name, _version_name, logical_fee_key):
        return {"name": "FEE-1", "logical_fee_key": logical_fee_key}

    def find_or_create_pending_evidence(self, **_kwargs):
        return "EVIDENCE-1"

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


def test_start_review_force_bypasses_only_same_input_ready_reuse() -> None:
    repository = _StartRepository(
        reusable={"name": "RUN-OLD", "status": "READY", "progress_revision": 8}
    )

    result = service.start_fee_evidence_review(
        "B1",
        "V1",
        "import_tax",
        "ATT-1",
        "tax_certificate",
        force=True,
        repository=repository,
        enqueue=lambda _run_id: None,
    )

    assert result["run_id"] == "RUN-NEW"
    assert result["reused"] is False


def test_execute_passes_persisted_evidence_role_to_draft(monkeypatch) -> None:
    class Repository:
        def __init__(self):
            self.run = {
                "name": "RUN-1",
                "batch": "B1",
                "version": "V1",
                "logical_fee_key": "import_tax",
                "evidence_role": "refund",
                "attachment": "ATT-1",
                "evidence": "E-LEGACY",
                "status": "QUEUED",
                "source_progress_json": [{}],
            }

        def get_run(self, _run_id):
            return self.run

        def claim_run(self, _run_id, token):
            self.run = {**self.run, "status": "RUNNING", "execution_token": token}
            return self.run

        def get_context(self, _batch, _version):
            return {"batch": "B1", "version": "V1", "fx_context": {}}

        def get_attachment(self, _batch, _attachment):
            return {
                "name": "ATT-1",
                "file_name": "退款.pdf",
                "modified": "m1",
                "file_url": "/files/refund.pdf",
                "parse_status": "Parsed",
                "parse_result_json": {"classification": {"code": "refund"}},
                "mapped_result_json": {},
            }

        def get_items(self, _batch, _version):
            return []

        def save_claimed(self, _run_id, token, **updates):
            assert token == self.run["execution_token"]
            self.run = {**self.run, **updates}
            return self.run

        def rollback(self):
            return None

    captured = {}
    monkeypatch.setattr(
        service,
        "_parse_attachment_for_review",
        lambda _attachment, _batch: ({"classification": {"code": "refund"}}, ""),
    )
    monkeypatch.setattr(
        service,
        "_semantic_ai_review",
        lambda *_args: {"ok": False, "warning": "", "model": ""},
    )
    monkeypatch.setattr(
        service,
        "build_fee_evidence_review_draft",
        lambda **kwargs: captured.update(kwargs)
        or {
            "summary": {},
            "evidence": {},
            "fee_splits": [],
            "components": [],
        },
    )

    result = service.execute_fee_evidence_review("RUN-1", repository=Repository())

    assert result["status"] == "READY"
    assert captured["evidence_role"] == "refund"
    assert captured["existing_components"] == []


def test_execute_rechecks_final_draft_size_after_adding_source_context(
    monkeypatch,
) -> None:
    class Repository:
        def __init__(self):
            self.run = {
                "name": "RUN-LIMIT",
                "batch": "B1",
                "version": "V1",
                "logical_fee_key": "import_tax",
                "evidence_role": "tax_certificate",
                "attachment": "ATT-1",
                "status": "QUEUED",
                "source_progress_json": [{}],
            }

        def get_run(self, _run_id):
            return self.run

        def claim_run(self, _run_id, token):
            self.run = {**self.run, "status": "RUNNING", "execution_token": token}
            return self.run

        def get_context(self, _batch, _version):
            return {
                "batch": "B1",
                "version": "V1",
                "fx_context": {},
                "effective_source": {},
            }

        def get_attachment(self, _batch, _attachment):
            return {
                "name": "ATT-1",
                "file_name": "tax.pdf",
                "modified": "m1",
                "parse_status": "Parsed",
                "parse_result_json": {"parser": "test"},
                "mapped_result_json": {},
            }

        def get_items(self, _batch, _version):
            return []

        def save_claimed(self, _run_id, token, **updates):
            assert token == self.run["execution_token"]
            self.run = {**self.run, **updates}
            return self.run

        def rollback(self):
            return None

    draft = {
        "summary": {},
        "evidence": {},
        "fee_splits": [],
        "components": [],
        "padding": "",
    }
    draft["padding"] = "x" * (
        service.FEE_EVIDENCE_DRAFT_MAX_BYTES
        - service._serialized_payload_size(draft)
        - 128
    )
    assert service._serialized_payload_size(draft) < (
        service.FEE_EVIDENCE_DRAFT_MAX_BYTES
    )
    repository = Repository()
    monkeypatch.setattr(
        service,
        "_parse_attachment_for_review",
        lambda _attachment, _batch: ({"parser": "test"}, ""),
    )
    monkeypatch.setattr(
        service,
        "_semantic_ai_review",
        lambda *_args: {"ok": False, "warning": "", "model": ""},
    )
    monkeypatch.setattr(
        service,
        "build_fee_evidence_review_draft",
        lambda **_kwargs: dict(draft),
    )
    monkeypatch.setattr(
        service.effective_source,
        "public_context",
        lambda _context: {"detail": "y" * 512},
    )

    result = service.execute_fee_evidence_review(
        "RUN-LIMIT",
        repository=repository,
    )

    assert result["status"] == "FAILED"
    assert repository.run["status"] == "FAILED"
    assert "安全上限" in repository.run["error_message"]
    assert "draft_json" not in repository.run


def test_execute_loads_current_evidence_components_for_material_matrix(monkeypatch) -> None:
    saved_components = [
        {
            "name": "COMP-SAVED",
            "item": "ITEM-GLASSES",
            "tax_code": "IGI",
            "amount_rmb": "99",
        }
    ]

    class Repository:
        def __init__(self):
            self.run = {
                "name": "RUN-1",
                "batch": "B1",
                "version": "V1",
                "logical_fee_key": "import_tax",
                "evidence_role": "tax_certificate",
                "attachment": "ATT-1",
                "evidence": "EVIDENCE-1",
                "status": "QUEUED",
                "source_progress_json": [{}],
            }

        def get_run(self, _run_id):
            return self.run

        def claim_run(self, _run_id, token):
            self.run = {**self.run, "status": "RUNNING", "execution_token": token}
            return self.run

        def get_context(self, _batch, _version):
            return {"batch": "B1", "version": "V1", "fx_context": {}}

        def get_attachment(self, _batch, _attachment):
            return {
                "name": "ATT-1",
                "file_name": "完税凭证.pdf",
                "modified": "m1",
                "parse_status": "Parsed",
                "parse_result_json": {"parser": "mexico_tax_certificate_pedimento"},
                "mapped_result_json": {},
            }

        def get_items(self, _batch, _version):
            return [
                {
                    "name": "ITEM-GLASSES",
                    "material_code": "GL-01",
                    "goods_value": "400",
                }
            ]

        def get_matrix_items(self, _batch, _version):
            return _items()

        def get_evidence_components(self, evidence_name):
            assert evidence_name == "EVIDENCE-1"
            return saved_components

        def save_claimed(self, _run_id, token, **updates):
            assert token == self.run["execution_token"]
            self.run = {**self.run, **updates}
            return self.run

        def rollback(self):
            return None

    captured = {}
    monkeypatch.setattr(
        service,
        "_parse_attachment_for_review",
        lambda _attachment, _batch: ({"parser": "mexico_tax_certificate_pedimento"}, ""),
    )
    monkeypatch.setattr(
        service,
        "_semantic_ai_review",
        lambda *_args: {"ok": False, "warning": "", "model": ""},
    )
    monkeypatch.setattr(
        service,
        "build_fee_evidence_review_draft",
        lambda **kwargs: captured.update(kwargs)
        or {
            "summary": {},
            "evidence": {},
            "fee_splits": [],
            "components": [],
            "material_matrix": {},
        },
    )

    result = service.execute_fee_evidence_review("RUN-1", repository=Repository())

    assert result["status"] == "READY"
    assert captured["existing_components"] is saved_components
    assert [row["name"] for row in captured["items"]] == ["ITEM-GLASSES"]
    assert [row["name"] for row in captured["matrix_items"]] == [
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    ]
    assert captured["matrix_items"][1]["stable_line_key"] == "LINE-SUNGLASSES"


def test_repository_parses_saved_component_evidence_and_confidence(monkeypatch) -> None:
    captured = {}

    class FakeFrappe:
        @staticmethod
        def get_all(_doctype, **kwargs):
            captured.update(kwargs)
            return [
                {
                    "name": "COMP-SAVED",
                    "confidence": "0.98",
                    "reverses_component": "COMP-PARENT",
                    "source_evidence_json": '{"attachment":"ATT-OLD","row":2}',
                }
            ]

    monkeypatch.setattr(service, "frappe", FakeFrappe())

    rows = service.FrappeFeeEvidenceReviewRepository().get_evidence_components(
        "EVIDENCE-1"
    )

    assert "source_evidence_json" in captured["fields"]
    assert "confidence" in captured["fields"]
    assert "reverses_component" in captured["fields"]
    assert rows[0]["source_evidence"] == {"attachment": "ATT-OLD", "row": 2}
    assert rows[0]["confidence"] == "0.98"
    assert rows[0]["reverses_component"] == "COMP-PARENT"


def test_repository_pages_exact_component_limit_and_keeps_tail_parent(
    monkeypatch,
) -> None:
    total = service.EVIDENCE_COMPONENT_READ_LIMIT
    calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(_doctype, **kwargs):
            calls.append(dict(kwargs))
            start = int(kwargs.get("limit_start") or 0)
            page_length = int(kwargs["limit_page_length"])
            stop = min(start + page_length, total)
            rows = []
            for index in range(start, stop):
                is_tail = index == total - 1
                rows.append(
                    {
                        "name": "PARENT-TAIL" if is_tail else f"COMP-{index:05d}",
                        "item": "ITEM-GLASSES",
                        "stable_line_key": "LINE-GLASSES",
                        "source_evidence_json": (
                            '{"kind":"tail-parent"}' if is_tail else "{}"
                        ),
                    }
                )
            return rows

    monkeypatch.setattr(service, "frappe", FakeFrappe())

    rows = service.FrappeFeeEvidenceReviewRepository().get_evidence_components(
        "EVIDENCE-1"
    )

    assert len(rows) == total
    assert rows[-1]["name"] == "PARENT-TAIL"
    assert rows[-1]["source_evidence"] == {"kind": "tail-parent"}
    assert calls[-1]["limit_start"] == total
    assert calls[-1]["limit_page_length"] == 1
    assert all(
        call["limit_page_length"] <= service.EVIDENCE_COMPONENT_READ_PAGE_SIZE
        for call in calls[:-1]
    )
    parent_by_name = {str(row.get("name") or ""): row for row in rows}
    normalized = service.normalize_component_for_apply(
        {
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "component_type": "REFUND_REVERSAL",
            "accounting_role": "SETTLEMENT",
            "cost_effect": "LEDGER_ONLY",
            "currency": "MXN",
            "original_amount": "-1",
            "amount_rmb": "-0.5",
            "reverses_component": "PARENT-TAIL",
        },
        item={"name": "ITEM-GLASSES", "stable_line_key": "LINE-GLASSES"},
        parent_components_by_name=parent_by_name,
    )
    assert normalized["reverses_component"] == "PARENT-TAIL"


def test_repository_rejects_component_count_above_explicit_limit(monkeypatch) -> None:
    total = service.EVIDENCE_COMPONENT_READ_LIMIT + 1

    class FakeFrappe:
        @staticmethod
        def get_all(_doctype, **kwargs):
            start = int(kwargs.get("limit_start") or 0)
            stop = min(start + int(kwargs["limit_page_length"]), total)
            return [
                {"name": f"COMP-{index}", "source_evidence_json": "{}"}
                for index in range(start, stop)
            ]

    monkeypatch.setattr(service, "frappe", FakeFrappe())

    with pytest.raises(ValueError, match="60,000"):
        service.FrappeFeeEvidenceReviewRepository().get_evidence_components(
            "EVIDENCE-1"
        )


def test_repository_bulk_inserts_sixty_thousand_components_in_bounded_chunks(
    monkeypatch,
) -> None:
    class FakeDB:
        def __init__(self):
            self.sql_calls = []
            self.bulk_calls = []

        def sql(self, query, values):
            self.sql_calls.append((query, values))

        def bulk_insert(
            self,
            doctype,
            fields,
            values,
            ignore_duplicates=False,
            *,
            chunk_size,
        ):
            rows = list(values)
            self.bulk_calls.append(
                {
                    "doctype": doctype,
                    "fields": list(fields),
                    "rows": rows,
                    "ignore_duplicates": ignore_duplicates,
                    "chunk_size": chunk_size,
                    "chunks": [
                        len(rows[index : index + chunk_size])
                        for index in range(0, len(rows), chunk_size)
                    ],
                }
            )

    fake_db = FakeDB()
    hashes = iter(f"HASH-{index:06d}" for index in range(60000))

    class FakeFrappe:
        db = fake_db
        session = type("Session", (), {"user": "reviewer@example.com"})()
        utils = type("Utils", (), {"now": staticmethod(lambda: "2026-09-18 12:00:00")})()

        @staticmethod
        def generate_hash(*, length):
            assert length == 10
            return next(hashes)

        @staticmethod
        def get_doc(_values):
            raise AssertionError("large component replacement must not use ORM inserts")

    monkeypatch.setattr(service, "frappe", FakeFrappe())
    component = {
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "component_type": "IMPORT_TAX",
        "accounting_role": "FINAL_BILL",
        "cost_effect": "COST",
        "tax_code": "IGI",
        "hs_code": "90041000",
        "currency": "MXN",
        "original_amount": Decimal("1.00"),
        "amount_rmb": Decimal("0.50"),
        "exchange_rate": Decimal("0.50"),
        "allocation_basis": "matrix_review",
        "source_evidence": {"type": "MANUAL_REVIEW", "operator": "reviewer@example.com"},
        "confidence": Decimal("1.00"),
        "reverses_component": None,
    }

    service.FrappeFeeEvidenceReviewRepository().replace_components(
        context={"batch": "B1", "version": "V1"},
        fee_rule={"name": "F-import_tax"},
        evidence_name="EVIDENCE-1",
        attachment_name="ATT-1",
        logical_fee_key="import_tax",
        components=[component] * 60000,
    )

    assert len(fake_db.sql_calls) == 1
    assert len(fake_db.bulk_calls) == 1
    bulk = fake_db.bulk_calls[0]
    assert bulk["doctype"] == "Overseas Cost Fee SKU Component"
    assert bulk["ignore_duplicates"] is False
    assert bulk["chunk_size"] == service.COMPONENT_BULK_INSERT_CHUNK_SIZE
    assert len(bulk["rows"]) == 60000
    assert max(bulk["chunks"]) <= service.COMPONENT_BULK_INSERT_CHUNK_SIZE
    assert len(bulk["chunks"]) < 60000
    field_index = {fieldname: index for index, fieldname in enumerate(bulk["fields"])}
    first = bulk["rows"][0]
    assert first[field_index["name"]] == "HASH-000000"
    assert first[field_index["owner"]] == "reviewer@example.com"
    assert first[field_index["status"]] == "CONFIRMED"
    assert first[field_index["is_active"]] == 1
    assert first[field_index["source_evidence_json"]] == (
        '{"operator":"reviewer@example.com","type":"MANUAL_REVIEW"}'
    )


def test_repository_small_component_replace_falls_back_without_bulk_insert(
    monkeypatch,
) -> None:
    inserted = []

    class FakeDocument:
        def __init__(self, values):
            self.values = values

        def insert(self, **_kwargs):
            inserted.append(self.values)
            return self

    class FakeDB:
        @staticmethod
        def sql(_query, _values):
            return None

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_doc(values):
            return FakeDocument(values)

    monkeypatch.setattr(service, "frappe", FakeFrappe())

    service.FrappeFeeEvidenceReviewRepository().replace_components(
        context={"batch": "B1", "version": "V1"},
        fee_rule={"name": "F-import_tax"},
        evidence_name="EVIDENCE-1",
        attachment_name="ATT-1",
        logical_fee_key="import_tax",
        components=[
            {
                "item": "ITEM-GLASSES",
                "stable_line_key": "LINE-GLASSES",
                "component_type": "IMPORT_TAX",
                "accounting_role": "FINAL_BILL",
                "cost_effect": "COST",
                "tax_code": "IGI",
                "currency": "MXN",
                "original_amount": Decimal("1.00"),
                "source_evidence": {},
            }
        ],
    )

    assert len(inserted) == 1
    assert inserted[0]["doctype"] == "Overseas Cost Fee SKU Component"


def test_repository_large_component_replace_fails_without_bulk_insert(
    monkeypatch,
) -> None:
    class FakeDB:
        @staticmethod
        def sql(_query, _values):
            raise AssertionError("capability must be checked before voiding current rows")

    class FakeFrappe:
        db = FakeDB()

    monkeypatch.setattr(service, "frappe", FakeFrappe())

    with pytest.raises(RuntimeError, match="不支持批量写入"):
        service.FrappeFeeEvidenceReviewRepository().replace_components(
            context={"batch": "B1", "version": "V1"},
            fee_rule={"name": "F-import_tax"},
            evidence_name="EVIDENCE-1",
            attachment_name="ATT-1",
            logical_fee_key="import_tax",
            components=[{}] * (service.COMPONENT_ORM_FALLBACK_LIMIT + 1),
        )


def test_repository_builds_raw_and_projected_item_views_from_one_snapshot(
    monkeypatch,
) -> None:
    raw_items = _items()
    calls = {"get_all": 0, "project": 0}

    class FakeFrappe:
        @staticmethod
        def get_all(_doctype, **_kwargs):
            calls["get_all"] += 1
            return raw_items

    bundle = {"context": {"root_kind": "expense"}, "source": {}}

    def project_ai_items(items, received_bundle):
        calls["project"] += 1
        assert items is raw_items
        assert received_bundle is bundle
        return [items[0]]

    monkeypatch.setattr(service, "frappe", FakeFrappe())
    monkeypatch.setattr(
        service.effective_source,
        "current_source_bundle",
        lambda _batch, _version: bundle,
    )
    monkeypatch.setattr(service.effective_source, "project_ai_items", project_ai_items)

    views = service.FrappeFeeEvidenceReviewRepository().get_review_items("B1", "V1")

    assert calls == {"get_all": 1, "project": 1}
    assert views["matrix_items"] is raw_items
    assert views["items"] == [raw_items[0]]


def test_execute_uses_repository_item_views_once(monkeypatch) -> None:
    class Repository:
        def __init__(self):
            self.item_view_calls = 0
            self.run = {
                "name": "RUN-1",
                "batch": "B1",
                "version": "V1",
                "logical_fee_key": "import_tax",
                "evidence_role": "tax_certificate",
                "attachment": "ATT-1",
                "status": "QUEUED",
                "source_progress_json": [{}],
            }

        def get_run(self, _run_id):
            return self.run

        def claim_run(self, _run_id, token):
            self.run = {**self.run, "status": "RUNNING", "execution_token": token}
            return self.run

        def get_context(self, _batch, _version):
            return {"batch": "B1", "version": "V1", "fx_context": {}}

        def get_attachment(self, _batch, _attachment):
            return {
                "name": "ATT-1",
                "file_name": "完税凭证.pdf",
                "modified": "m1",
                "parse_status": "Parsed",
                "parse_result_json": {"parser": "mexico_tax_certificate_pedimento"},
                "mapped_result_json": {},
            }

        def get_review_items(self, _batch, _version):
            self.item_view_calls += 1
            return {"items": [_items()[0]], "matrix_items": _items()}

        def get_items(self, *_args):
            raise AssertionError("execution must use the combined item snapshot")

        def get_matrix_items(self, *_args):
            raise AssertionError("execution must use the combined item snapshot")

        def save_claimed(self, _run_id, token, **updates):
            assert token == self.run["execution_token"]
            self.run = {**self.run, **updates}
            return self.run

        def rollback(self):
            return None

    repository = Repository()
    captured = {}
    monkeypatch.setattr(
        service,
        "_parse_attachment_for_review",
        lambda _attachment, _batch: ({"parser": "mexico_tax_certificate_pedimento"}, ""),
    )
    monkeypatch.setattr(
        service,
        "_semantic_ai_review",
        lambda *_args: {"ok": False, "warning": "", "model": ""},
    )
    monkeypatch.setattr(
        service,
        "build_fee_evidence_review_draft",
        lambda **kwargs: captured.update(kwargs)
        or {"summary": {}, "evidence": {}, "fee_splits": [], "components": []},
    )

    result = service.execute_fee_evidence_review("RUN-1", repository=repository)

    assert result["status"] == "READY"
    assert repository.item_view_calls == 1
    assert [row["name"] for row in captured["items"]] == ["ITEM-GLASSES"]
    assert [row["name"] for row in captured["matrix_items"]] == [
        "ITEM-GLASSES",
        "ITEM-SUNGLASSES",
    ]


def test_execute_claim_loss_never_writes_with_a_new_owners_token() -> None:
    class Repository:
        def __init__(self):
            self.run = {"name": "RUN-1", "status": "QUEUED"}

        def get_run(self, _run_id):
            return self.run

        def claim_run(self, _run_id, _token):
            self.run = {"name": "RUN-1", "status": "RUNNING", "execution_token": "other"}
            return None

    result = service.execute_fee_evidence_review("RUN-1", repository=Repository())

    assert result == {
        "ok": True,
        "run_id": "RUN-1",
        "status": "RUNNING",
        "claimed": False,
    }


def test_malformed_deepseek_match_shape_falls_back_without_losing_rule_result(
    monkeypatch,
) -> None:
    from overseas_costing.services import allocation_service

    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {"api_key": "test", "model": "deepseek-test"},
    )
    monkeypatch.setattr(
        allocation_service,
        "_call_chat_completions",
        lambda *_args: '{"evidence_type":"REFUND","line_item_matches":[{"bad":true}]}',
    )
    monkeypatch.setattr(
        allocation_service,
        "_extract_json_object",
        lambda _content: {
            "evidence_type": "REFUND",
            "line_item_matches": [{"bad": True}],
        },
    )

    result = service._semantic_ai_review({}, {"file_name": "refund.pdf"}, _items())

    assert result["ok"] is True
    assert result["review"]["evidence_type"] == "REFUND"
    assert result["review"]["line_item_matches"] == {}


def test_incremental_status_omits_large_draft_while_running_and_unchanged() -> None:
    class Repository:
        def get_run(self, _run_id):
            return {"name": "RUN-1", "batch": "B1", "version": "V1", "status": "RUNNING", "progress_revision": 7, "draft_json": {"large": "draft"}}

    result = service.get_fee_evidence_review_status("B1", "RUN-1", after_revision=7, repository=Repository())

    assert result["unchanged"] is True
    assert "draft" not in result


def test_apply_lock_order_contains_every_mutated_target() -> None:
    assert service.review_lock_targets(
        {"batch": "B1", "version": "V1"},
        {"name": "RUN1", "attachment": "A1", "evidence": "E1"},
    ) == [
        ("batch", "B1"),
        ("run", "RUN1"),
        ("version", "V1"),
        ("attachment", "A1"),
        ("fee_rules", "B1", "V1"),
        ("evidence", "E1"),
        ("items", "B1", "V1"),
        ("components", "B1", "V1"),
    ]


def test_duplicate_attachment_fingerprint_is_rejected() -> None:
    candidate = {
        "attachment": "A-NEW",
        "attachment_fingerprint": "sha256:x",
        "accounting_role": "FINAL_BILL",
        "direction": "DEBIT",
        "original_amount": "30",
        "validation_status": "VALID",
    }
    existing = [
        {
            "name": "E-OLD",
            "attachment": "A-OLD",
            "attachment_fingerprint": "sha256:x",
            "accounting_role": "FINAL_BILL",
            "direction": "DEBIT",
            "original_amount": "30.00",
            "validation_status": "VALID",
        }
    ]

    with pytest.raises(ValueError, match="重复凭证"):
        service.assert_no_duplicate_evidence(candidate, existing)

    service.assert_no_duplicate_evidence(
        candidate,
        [{**existing[0], "attachment": "A-NEW"}],
    )


def test_attachment_fingerprint_uses_file_content_not_attachment_identity() -> None:
    first = {
        "name": "A1",
        "file_name": "first.pdf",
        "file_url": "/files/first.pdf",
        "modified": "m1",
        "content_sha256": "same-content",
        "parse_result_json": {"total": "30"},
        "mapped_result_json": {},
    }
    duplicate_upload = {
        **first,
        "name": "A2",
        "file_name": "renamed.pdf",
        "file_url": "/files/renamed.pdf",
        "modified": "m2",
        "parse_result_json": {"total": "30", "parser_version": "new"},
    }

    assert service._attachment_fingerprint(first) == service._attachment_fingerprint(
        duplicate_upload
    )
    assert service._attachment_fingerprint(first) != service._attachment_fingerprint(
        {**duplicate_upload, "content_sha256": "different-content"}
    )


def test_review_fingerprint_includes_evidence_role() -> None:
    attachment = {"name": "A1", "modified": "m1", "file_url": "/files/a.pdf"}

    assert service.build_input_fingerprint(
        batch_name="B1",
        version_name="V1",
        logical_fee_key="import_tax",
        attachment=attachment,
        evidence_role="tax_certificate",
    ) != service.build_input_fingerprint(
        batch_name="B1",
        version_name="V1",
        logical_fee_key="import_tax",
        attachment=attachment,
        evidence_role="expense_invoice",
    )


def test_start_review_persists_requested_evidence_role() -> None:
    repository = _StartRepository()

    service.start_fee_evidence_review(
        "B1",
        "V1",
        "import_tax",
        "ATT-1",
        "tax_certificate",
        repository=repository,
        enqueue=lambda _run_id: None,
    )

    assert repository.created[0]["evidence_role"] == "tax_certificate"


def test_frappe_run_creation_serializes_long_text_json_fields(monkeypatch) -> None:
    captured = {}

    class RunDocument:
        def insert(self, **_kwargs):
            return self

    class FakeFrappe:
        @staticmethod
        def get_doc(values):
            captured.update(values)
            return RunDocument()

    monkeypatch.setattr(service, "frappe", FakeFrappe())

    service.FrappeFeeEvidenceReviewRepository().create_run(
        {
            "status": "QUEUED",
            "source_progress_json": [{"status": "WAITING"}],
            "draft_json": {"summary": {}},
        }
    )

    assert captured["source_progress_json"] == '[{"status":"WAITING"}]'
    assert captured["draft_json"] == '{"summary":{}}'


class _ApplyRepository:
    def __init__(self, *, fail_audit=False):
        self.fail_audit = fail_audit
        self.attachment = {
            "name": "ATT-1",
            "batch": "B1",
            "file_name": "账单.pdf",
            "modified": "m1",
            "file_url": "/files/bill.pdf",
            "parse_status": "Parsed",
            "parse_result_json": "{}",
            "mapped_result_json": "{}",
        }
        self.draft = {
            "evidence": {
                "proposal_id": "evidence:classification",
                "evidence_type": "FINAL_INVOICE",
                "accounting_role": "FINAL_BILL",
                "direction": "DEBIT",
                "currency": "MXN",
                "original_amount": "30",
                "is_final": 1,
            },
            "fee_splits": [
                {
                    "proposal_id": "fee:import_tax",
                    "logical_fee_key": "import_tax",
                    "amount": "30",
                    "currency": "MXN",
                    "amount_status": "ACTUAL",
                }
            ],
            "components": [],
        }
        self.run = {
            "name": "RUN-1",
            "batch": "B1",
            "version": "V1",
            "fee_rule": "F1",
            "attachment": "ATT-1",
            "evidence": "E1",
            "status": "READY",
            "attachment_fingerprint": service._attachment_fingerprint(self.attachment),
            "draft_json": self.draft,
        }
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.saved_evidence = None

    def get_run(self, _run_id):
        return self.run

    def get_context(self, batch_name, version_name):
        self.calls.append(("context", batch_name, version_name))
        return {
            "batch": batch_name,
            "version": version_name,
            "transport_mode": "AIR",
            "fx_context": {"fx_rmb_to_mxn": "2"},
        }

    def lock_apply_context(self, _context, _run):
        self.calls.append(("lock",))
        return self.run

    def assert_batch_write(self, _batch_name, _version_name, **_kwargs):
        self.calls.append(("permission",))

    def get_attachment(self, _batch_name, _attachment_name):
        return self.attachment

    def list_duplicate_evidence_candidates(self, *_args):
        return []

    def update_evidence(self, _evidence_name, values):
        self.saved_evidence = values
        self.calls.append(("evidence",))

    def save_fee_split(self, **kwargs):
        self.calls.append(("fee", kwargs["fee_row"]["logical_fee_key"]))
        return {
            "name": "F1",
            "logical_fee_key": "import_tax",
            "amount": "30",
            "currency": "MXN",
        }

    def mark_batch_dirty(self, _batch_name):
        self.calls.append(("dirty",))

    def insert_review_audit(self, **_kwargs):
        self.calls.append(("audit",))
        if self.fail_audit:
            raise RuntimeError("audit failed")

    def finish_run(self, _run_id, values):
        self.calls.append(("finish", values["status"]))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def get_batch_modified(self, _batch_name):
        return "m2"


def test_apply_review_commits_once_and_preserves_evidence_gross_total() -> None:
    repository = _ApplyRepository()

    result = service.apply_fee_evidence_review(
        "B1",
        "RUN-1",
        ["evidence:classification", "fee:import_tax"],
        {},
        "EDIT",
        "m1",
        repository=repository,
    )

    assert result["status"] == "APPLIED"
    assert repository.saved_evidence["original_amount"] == Decimal("30")
    assert repository.commits == 1
    assert repository.rollbacks == 0
    assert repository.calls.index(("lock",)) < repository.calls.index(("permission",))
    assert repository.calls[-1] == ("finish", "APPLIED")


def test_apply_review_rolls_back_all_writes_and_leaves_run_unfinished_on_error() -> None:
    repository = _ApplyRepository(fail_audit=True)

    with pytest.raises(RuntimeError, match="audit failed"):
        service.apply_fee_evidence_review(
            "B1",
            "RUN-1",
            ["evidence:classification", "fee:import_tax"],
            {},
            "EDIT",
            "m1",
            repository=repository,
        )

    assert repository.commits == 0
    assert repository.rollbacks == 1
    assert not any(call[0] == "finish" for call in repository.calls)


class _MatrixApplyRepository(_ApplyRepository):
    def __init__(self, *, fx_context=None, fail_replace=False):
        super().__init__()
        self.context = {
            "batch": "B1",
            "version": "V1",
            "transport_mode": "AIR",
            "fx_context": {"fx_rmb_to_mxn": "2"} if fx_context is None else fx_context,
        }
        self.items = _items()
        self.replaced = []
        self.get_items_calls = 0
        self.fail_replace = fail_replace
        self.fees = {
            "import_tax": {
                "name": "F-import_tax",
                "logical_fee_key": "import_tax",
                "amount": "50",
                "currency": "MXN",
            },
            "customs_clearance_fee": {
                "name": "F-customs_clearance_fee",
                "logical_fee_key": "customs_clearance_fee",
                "amount": "20",
                "currency": "MXN",
            },
        }
        self.draft["evidence"]["original_amount"] = "70"
        self.draft["fee_splits"] = [
            {
                "proposal_id": "fee:import_tax",
                "logical_fee_key": "import_tax",
                "amount": "50",
                "currency": "MXN",
                "amount_status": "ACTUAL",
            },
            {
                "proposal_id": "fee:customs_clearance_fee",
                "logical_fee_key": "customs_clearance_fee",
                "amount": "20",
                "currency": "MXN",
                "amount_status": "ACTUAL",
            },
        ]
        self.draft["components"] = [
            {
                "proposal_id": f"component:{column_key.lower()}",
                "item": "ITEM-GLASSES",
                "stable_line_key": "LINE-GLASSES",
                "component_type": (
                    "CUSTOMS_SERVICE" if column_key == "CUSTOMS_SERVICE" else "IMPORT_TAX"
                ),
                "tax_code": "" if column_key == "CUSTOMS_SERVICE" else column_key,
                "fee_logical_key": (
                    "customs_clearance_fee"
                    if column_key == "CUSTOMS_SERVICE"
                    else "import_tax"
                ),
                "currency": "MXN",
                "original_amount": "5.00",
                "amount_rmb": "999999",
                "exchange_rate": "999999",
                "source_evidence": {"page": 1, "text_line": index},
                "source_refs": [{"page": 1, "text_line": index, "field": column_key}],
                "confidence": "0.80",
            }
            for index, column_key in enumerate(
                ("IGI", "IVA", "DTA", "PRV", "PRV_IVA", "CUSTOMS_SERVICE"),
                start=1,
            )
        ]
        self.draft["material_matrix"] = service.build_material_matrix(
            items=self.items,
            components=self.draft["components"],
        )
        self.run["draft_json"] = self.draft
        self.current_components = []

    def get_context(self, batch_name, version_name):
        self.calls.append(("context", batch_name, version_name))
        return {**self.context, "batch": batch_name, "version": version_name}

    def get_review_items(self, _batch_name, _version_name):
        return {"items": [{"name": "AI-SCOPE-SHOULD-NOT-BE-USED"}], "matrix_items": self.items}

    def get_items(self, _batch_name, _version_name):
        self.get_items_calls += 1
        return self.items

    def get_evidence_components(self, _evidence_name):
        return [dict(row) for row in self.current_components]

    def save_fee_split(self, **kwargs):
        fee_key = kwargs["fee_row"]["logical_fee_key"]
        self.calls.append(("fee", fee_key))
        return dict(self.fees[fee_key])

    def materialize_fee_rule(self, _batch, _version, logical_fee_key):
        return dict(self.fees[logical_fee_key])

    def replace_components(self, **kwargs):
        self.replaced.append(kwargs)
        if self.fail_replace:
            raise RuntimeError("replace failed")


def _matrix_apply_payload(*cells: dict) -> dict:
    return {"cells": list(cells)}


def _matrix_cell(column_key, amount="5.00", *, item="ITEM-GLASSES", sources=None, **extra):
    return {
        "item": item,
        "column_key": column_key,
        "original_amount": amount,
        "source_proposal_ids": (
            [f"component:{column_key.lower()}"] if sources is None else sources
        ),
        **extra,
    }


def _apply_matrix(repository, matrix, *, selections=None):
    return service.apply_fee_evidence_review(
        "B1",
        "RUN-1",
        selections
        or ["evidence:classification", "fee:import_tax", "fee:customs_clearance_fee"],
        {},
        "EDIT",
        "m1",
        component_matrix=matrix,
        repository=repository,
    )


def test_apply_material_matrix_maps_all_six_columns_and_recomputes_server_values() -> None:
    repository = _MatrixApplyRepository()
    columns = ("IGI", "IVA", "DTA", "PRV", "PRV_IVA", "CUSTOMS_SERVICE")

    result = _apply_matrix(
        repository,
        _matrix_apply_payload(*[_matrix_cell(column) for column in columns]),
    )

    assert result["component_count"] == 6
    assert {row["logical_fee_key"] for row in repository.replaced} == {
        "import_tax",
        "customs_clearance_fee",
    }
    saved = [component for row in repository.replaced for component in row["components"]]
    assert {row["tax_code"] for row in saved} == {
        "IGI",
        "IVA",
        "DTA",
        "PRV",
        "PRV_IVA",
        "",
    }
    assert all(row["component_type"] == ("CUSTOMS_SERVICE" if not row["tax_code"] else "IMPORT_TAX") for row in saved)
    assert all(row["currency"] == "MXN" for row in saved)
    assert all(row["amount_rmb"] == Decimal("2.5") for row in saved)
    assert all(row["exchange_rate"] == Decimal("0.5") for row in saved)
    assert all(row["stable_line_key"] == "LINE-GLASSES" for row in saved)
    assert all(row["hs_code"] == "90041000" for row in saved)
    assert all(row["source_evidence"]["type"] == "MANUAL_REVIEW" for row in saved)
    assert all(row["source_evidence"]["attachment"] == "ATT-1" for row in saved)
    assert all(row["source_evidence"]["review_run"] == "RUN-1" for row in saved)
    assert all(row["source_evidence"]["operator"] for row in saved)
    assert all(row["source_evidence"]["source_proposals"] for row in saved)
    assert repository.get_items_calls == 0


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"cells": [], "rmb_total": "1"}, "顶层|unknown|未知"),
        (_matrix_apply_payload(_matrix_cell("IGI", amount="1", amount_rmb="99")), "字段"),
        (_matrix_apply_payload(_matrix_cell("IGI", item="ITEM-UNKNOWN")), "物料|SKU"),
        (_matrix_apply_payload(_matrix_cell("UNKNOWN", sources=[])), "列"),
        (_matrix_apply_payload(_matrix_cell("IGI"), _matrix_cell("IGI", amount="1")), "重复"),
        (_matrix_apply_payload(_matrix_cell("IGI", amount="-1")), "非负|金额"),
        (_matrix_apply_payload(_matrix_cell("IGI", amount="NaN")), "有限|金额"),
        (_matrix_apply_payload(_matrix_cell("IGI", amount="Infinity")), "有限|金额"),
        (_matrix_apply_payload(_matrix_cell("IGI", amount="1e1000000")), "金额|精度"),
        (_matrix_apply_payload(_matrix_cell("IGI", amount="1.001")), "精度|小数"),
        (_matrix_apply_payload(_matrix_cell("IGI", sources=["missing"])), "不存在"),
        (_matrix_apply_payload(_matrix_cell("IGI", sources=["component:iva"])), "单元格|不匹配"),
        (_matrix_apply_payload(_matrix_cell("IGI", sources=["component:igi", "component:igi"])), "重复"),
    ],
)
def test_apply_material_matrix_rejects_untrusted_or_invalid_cells(payload, message) -> None:
    repository = _MatrixApplyRepository()

    with pytest.raises(ValueError, match=message):
        _apply_matrix(repository, payload)

    assert repository.commits == 0
    assert repository.rollbacks == 1
    assert repository.replaced == []


@pytest.mark.parametrize(
    "amount",
    [
        "9" * 65,
        10**28,
    ],
)
def test_material_matrix_rejects_oversized_amount_before_decimal_conversion(
    amount,
) -> None:
    repository = _MatrixApplyRepository()

    with pytest.raises(ValueError, match="金额.*(过长|位数)"):
        service.validate_material_matrix_submission(
            _matrix_apply_payload(
                _matrix_cell("IGI", amount=amount, sources=[]),
            ),
            draft=repository.draft,
            items=repository.items,
        )


def test_material_matrix_rejects_combined_cells_and_external_components_above_limit(
    monkeypatch,
) -> None:
    repository = _MatrixApplyRepository()
    repository.current_components = [
        {
            "name": "CURRENT-LEDGER",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "logical_fee_key": "import_tax",
            "component_type": "IMPORT_TAX",
            "accounting_role": "SETTLEMENT",
            "cost_effect": "LEDGER_ONLY",
            "tax_code": "IGI",
            "currency": "MXN",
            "original_amount": "1.00",
            "amount_rmb": "0.50",
            "exchange_rate": "0.5",
            "source_evidence": {"attachment": "ATT-1", "kind": "ledger"},
        }
    ]
    monkeypatch.setattr(service, "EVIDENCE_COMPONENT_READ_LIMIT", 1)

    with pytest.raises(ValueError, match="SKU 分项.*1"):
        _apply_matrix(
            repository,
            _matrix_apply_payload(_matrix_cell("IGI", amount="1.00")),
        )

    assert repository.replaced == []
    assert repository.rollbacks == 1


def test_apply_material_matrix_rejects_component_total_above_fee() -> None:
    repository = _MatrixApplyRepository()

    with pytest.raises(ValueError, match="超过费用总额"):
        _apply_matrix(repository, _matrix_apply_payload(_matrix_cell("IGI", amount="50.01")))

    assert repository.rollbacks == 1


def test_apply_material_matrix_missing_fx_keeps_original_and_blank_rmb() -> None:
    repository = _MatrixApplyRepository(fx_context={})

    _apply_matrix(repository, _matrix_apply_payload(_matrix_cell("IGI", amount="12.34", sources=[])))

    component = next(row for saved in repository.replaced for row in saved["components"])
    assert component["currency"] == "MXN"
    assert component["original_amount"] == Decimal("12.34")
    assert component["amount_rmb"] is None
    assert component["exchange_rate"] is None
    assert component["source_evidence"]["source_proposal_ids"] == []
    assert component["source_evidence"]["manual_change"] is True


def test_apply_material_matrix_empty_cells_replace_selected_fee_components_with_empty_lists() -> None:
    repository = _MatrixApplyRepository()

    result = _apply_matrix(repository, {"cells": []})

    assert result["component_count"] == 0
    assert {row["logical_fee_key"] for row in repository.replaced} == {
        "import_tax",
        "customs_clearance_fee",
    }
    assert all(row["components"] == [] for row in repository.replaced)


def test_apply_material_matrix_clear_replaces_fee_keys_from_saved_preview_values() -> None:
    repository = _MatrixApplyRepository()
    repository.draft["material_matrix"] = {
        "saved_components": [
            {
                "id": "SAVED-CUSTOMS",
                "item": "ITEM-GLASSES",
                "stable_line_key": "LINE-GLASSES",
                "logical_fee_key": "customs_clearance_fee",
                "component_type": "CUSTOMS_SERVICE",
                "tax_code": "",
                "currency": "MXN",
                "original_amount": "7.00",
            }
        ]
    }
    repository.run["draft_json"] = repository.draft

    _apply_matrix(
        repository,
        {"cells": []},
        selections=["evidence:classification", "fee:import_tax"],
    )

    assert {row["logical_fee_key"] for row in repository.replaced} == {
        "import_tax",
        "customs_clearance_fee",
    }
    assert all(row["components"] == [] for row in repository.replaced)


def test_apply_material_matrix_reads_source_proposals_from_indexed_draft() -> None:
    repository = _MatrixApplyRepository()
    components = repository.draft.pop("components")
    repository.draft["component_store"] = service._build_component_store(components)
    repository.draft["component_contract"] = {
        "mode": "INDEXED_COLUMNS_V1",
        "component_count": len(components),
    }
    repository.run["draft_json"] = repository.draft

    _apply_matrix(
        repository,
        _matrix_apply_payload(_matrix_cell("PRV_IVA", amount="4.00")),
    )

    component = next(row for saved in repository.replaced for row in saved["components"])
    source = component["source_evidence"]["source_proposals"][0]
    assert source["proposal_id"] == "component:prv_iva"
    assert source["source_refs"][0]["field"] == "PRV_IVA"
    assert source["original_amount"] == "5.00"
    assert component["source_evidence"]["manual_change"] is True
    assert component["source_evidence"]["suggested_original_amounts_by_currency"] == {"MXN": "5.00"}


def test_apply_material_matrix_indexed_draft_materializes_only_referenced_proposals(
    monkeypatch,
) -> None:
    repository = _MatrixApplyRepository()
    template = repository.draft["components"][0]
    components = [
        {
            **template,
            "proposal_id": f"component:igi:{index}",
            "original_amount": "0.01",
        }
        for index in range(1000)
    ]
    repository.draft["material_matrix"] = service.build_material_matrix(
        items=repository.items,
        components=components,
    )
    repository.draft["components"] = []
    repository.draft["component_store"] = service._build_component_store(components)
    repository.draft["component_contract"] = {
        "mode": "INDEXED_COLUMNS_V1",
        "component_count": len(components),
    }
    repository.run["draft_json"] = repository.draft
    original = service._component_store_row
    calls = []

    def counted(store, row_index):
        calls.append(row_index)
        return original(store, row_index)

    monkeypatch.setattr(service, "_component_store_row", counted)
    _apply_matrix(
        repository,
        _matrix_apply_payload(
            _matrix_cell("IGI", amount="0.01", sources=["component:igi:999"])
        ),
    )

    assert calls == [999]


def test_apply_material_matrix_preserves_selected_ledger_component_like_legacy_apply() -> None:
    ledger = {
        "proposal_id": "ledger:settlement:1",
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "component_type": "IMPORT_TAX",
        "accounting_role": "SETTLEMENT",
        "cost_effect": "LEDGER_ONLY",
        "tax_code": "IGI",
        "hs_code": "90041000",
        "currency": "MXN",
        "original_amount": "4.00",
        "amount_rmb": "2.00",
        "exchange_rate": "0.5",
        "allocation_basis": "settlement_ledger",
        "source_evidence": {"attachment": "ATT-1", "ledger": "payment"},
        "confidence": "1.00",
        "fee_logical_key": "import_tax",
    }
    old_repository = _MatrixApplyRepository()
    old_repository.draft["components"].append(ledger)
    old_repository.run["draft_json"] = old_repository.draft
    matrix_repository = _MatrixApplyRepository()
    matrix_repository.draft["components"].append(ledger)
    matrix_repository.current_components = [
        {
            **ledger,
            "name": "CURRENT-LEDGER-SAME",
            "logical_fee_key": "import_tax",
            "fee_logical_key": "",
            "original_amount": Decimal("4"),
            "amount_rmb": Decimal("2"),
            "exchange_rate": Decimal("0.500000"),
        }
    ]
    matrix_repository.run["draft_json"] = matrix_repository.draft
    selections = [
        "evidence:classification",
        "fee:import_tax",
        "ledger:settlement:1",
    ]

    service.apply_fee_evidence_review(
        "B1",
        "RUN-1",
        selections,
        {},
        "EDIT",
        "m1",
        repository=old_repository,
    )
    _apply_matrix(matrix_repository, {"cells": []}, selections=selections)

    old_components = [
        component
        for saved in old_repository.replaced
        for component in saved["components"]
    ]
    matrix_components = [
        component
        for saved in matrix_repository.replaced
        for component in saved["components"]
    ]
    assert len(old_components) == 1
    assert matrix_components == old_components
    assert matrix_components[0]["cost_effect"] == "LEDGER_ONLY"
    assert matrix_components[0]["source_evidence"] == {
        "attachment": "ATT-1",
        "ledger": "payment",
    }


def test_apply_material_matrix_clear_voids_matrix_cost_but_reinserts_existing_ledger() -> None:
    repository = _MatrixApplyRepository()
    repository.current_components = [
        {
            "name": "CURRENT-COST",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "logical_fee_key": "import_tax",
            "component_type": "IMPORT_TAX",
            "accounting_role": "FINAL_BILL",
            "cost_effect": "COST",
            "tax_code": "IGI",
            "hs_code": "90041000",
            "currency": "MXN",
            "original_amount": "10.00",
            "amount_rmb": "5.00",
            "exchange_rate": "0.5",
            "allocation_basis": "voucher",
            "source_evidence": {"attachment": "ATT-1", "kind": "cost"},
            "confidence": "1.00",
        },
        {
            "name": "CURRENT-LEDGER",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "logical_fee_key": "import_tax",
            "component_type": "IMPORT_TAX",
            "accounting_role": "SETTLEMENT",
            "cost_effect": "LEDGER_ONLY",
            "tax_code": "IGI",
            "hs_code": "90041000",
            "currency": "MXN",
            "original_amount": "4.00",
            "amount_rmb": "2.00",
            "exchange_rate": "0.5",
            "allocation_basis": "settlement_ledger",
            "source_evidence": {"attachment": "ATT-1", "kind": "ledger"},
            "confidence": "1.00",
        },
    ]

    _apply_matrix(repository, {"cells": []})

    import_tax = next(
        row for row in repository.replaced if row["logical_fee_key"] == "import_tax"
    )
    assert len(import_tax["components"]) == 1
    saved = import_tax["components"][0]
    assert saved["cost_effect"] == "LEDGER_ONLY"
    assert saved["source_evidence"] == {
        "attachment": "ATT-1",
        "kind": "ledger",
    }
    assert all(
        component["allocation_basis"] != "voucher"
        for row in repository.replaced
        for component in row["components"]
    )


def test_legacy_component_item_edit_persists_manual_review_audit(monkeypatch) -> None:
    repository = _MatrixApplyRepository()
    monkeypatch.setattr(service, "_session_user", lambda: "reviewer@example.com")
    igi = next(
        row
        for row in repository.draft["components"]
        if row["proposal_id"] == "component:igi"
    )
    igi["amount_rmb"] = "2.50"
    igi["exchange_rate"] = "0.50"

    result = service.apply_fee_evidence_review(
        "B1",
        "RUN-1",
        ["evidence:classification", "fee:import_tax", "component:igi"],
        {"component:igi": {"item": "ITEM-SUNGLASSES"}},
        "EDIT",
        "m1",
        repository=repository,
    )

    assert result["component_count"] == 1
    saved = repository.replaced[0]["components"][0]
    assert saved["item"] == "ITEM-SUNGLASSES"
    assert saved["source_evidence"]["human_edits"] == ["item"]
    assert saved["source_evidence"]["source_refs"][-1] == {
        "type": "MANUAL_REVIEW",
        "field": "item",
        "operator": "reviewer@example.com",
        "from": "ITEM-GLASSES",
        "to": "ITEM-SUNGLASSES",
    }


@pytest.mark.parametrize("component_matrix", [None, {"cells": []}])
def test_refund_reversal_rejects_item_edit_that_disagrees_with_parent(
    component_matrix,
) -> None:
    repository = _MatrixApplyRepository()
    repository.draft["evidence"].update(
        evidence_type="REFUND",
        accounting_role="SETTLEMENT",
        direction="CREDIT",
        original_amount="4.00",
        related_evidence="E-PARENT",
        is_final=0,
    )
    repository.draft["fee_splits"] = []
    repository.draft["components"].append(
        {
            "proposal_id": "refund-component:forged-item",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "component_type": "REFUND_REVERSAL",
            "accounting_role": "SETTLEMENT",
            "cost_effect": "LEDGER_ONLY",
            "tax_code": "IGI",
            "currency": "MXN",
            "original_amount": "-4.00",
            "amount_rmb": "-2.00",
            "exchange_rate": "0.5",
            "allocation_basis": "original_component_proportion",
            "reverses_component": "PARENT-COMP",
            "source_evidence": {"reverses_component": "PARENT-COMP"},
            "fee_logical_key": "import_tax",
        }
    )
    repository.run["draft_json"] = repository.draft
    repository.get_evidence = lambda _name: {
        "name": "E-PARENT",
        "batch": "B1",
        "version": "V1",
        "fee_rule": "F1",
        "evidence_type": "PAYMENT",
        "accounting_role": "SETTLEMENT",
        "validation_status": "VALID",
        "currency": "MXN",
    }

    def evidence_components(name):
        if name == "E-PARENT":
            return [
                {
                    "name": "PARENT-COMP",
                    "item": "ITEM-GLASSES",
                    "stable_line_key": "LINE-GLASSES",
                }
            ]
        return []

    repository.get_evidence_components = evidence_components

    with pytest.raises(ValueError, match="原付款.*SKU"):
        service.apply_fee_evidence_review(
            "B1",
            "RUN-1",
            ["evidence:classification", "refund-component:forged-item"],
            {"refund-component:forged-item": {"item": "ITEM-SUNGLASSES"}},
            "EDIT",
            "m1",
            component_matrix=component_matrix,
            repository=repository,
        )

    assert repository.replaced == []
    assert repository.commits == 0
    assert repository.rollbacks == 1


def test_apply_material_matrix_preserves_selected_refund_reversal_and_parent_link() -> None:
    repository = _MatrixApplyRepository()
    repository.draft["evidence"].update(
        evidence_type="REFUND",
        accounting_role="SETTLEMENT",
        direction="CREDIT",
        original_amount="4.00",
        related_evidence="E-PARENT",
        is_final=0,
    )
    repository.draft["fee_splits"] = []
    repository.draft["components"].append(
        {
            "proposal_id": "refund-component:1",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "component_type": "REFUND_REVERSAL",
            "accounting_role": "SETTLEMENT",
            "cost_effect": "LEDGER_ONLY",
            "tax_code": "IGI",
            "hs_code": "90041000",
            "currency": "MXN",
            "original_amount": "-4.00",
            "amount_rmb": "-2.00",
            "exchange_rate": "0.5",
            "allocation_basis": "original_component_proportion",
            "reverses_component": "PARENT-COMP",
            "source_evidence": {"reverses_component": "PARENT-COMP"},
            "confidence": "1.00",
            "fee_logical_key": "import_tax",
        }
    )
    repository.run["draft_json"] = repository.draft
    repository.get_evidence = lambda _name: {
        "name": "E-PARENT",
        "batch": "B1",
        "version": "V1",
        "fee_rule": "F1",
        "evidence_type": "PAYMENT",
        "accounting_role": "SETTLEMENT",
        "validation_status": "VALID",
        "currency": "MXN",
    }

    def evidence_components(name):
        if name == "E-PARENT":
            return [
                {
                    "name": "PARENT-COMP",
                    "item": "ITEM-GLASSES",
                    "stable_line_key": "LINE-GLASSES",
                }
            ]
        return []

    repository.get_evidence_components = evidence_components

    result = _apply_matrix(
        repository,
        {"cells": []},
        selections=["evidence:classification", "refund-component:1"],
    )

    assert result["component_count"] == 1
    saved = next(
        component
        for row in repository.replaced
        for component in row["components"]
    )
    assert saved["component_type"] == "REFUND_REVERSAL"
    assert saved["cost_effect"] == "LEDGER_ONLY"
    assert saved["original_amount"] == Decimal("-4.00")
    assert saved["reverses_component"] == "PARENT-COMP"
    assert saved["source_evidence"] == {"reverses_component": "PARENT-COMP"}


def test_apply_material_matrix_preserves_distinct_existing_ledger_rows_with_same_values() -> None:
    repository = _MatrixApplyRepository()
    shared = {
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "logical_fee_key": "import_tax",
        "component_type": "IMPORT_TAX",
        "accounting_role": "SETTLEMENT",
        "cost_effect": "LEDGER_ONLY",
        "tax_code": "IGI",
        "hs_code": "90041000",
        "currency": "MXN",
        "original_amount": "4.00",
        "amount_rmb": "2.00",
        "exchange_rate": "0.5",
        "allocation_basis": "settlement_ledger",
        "source_evidence": {"attachment": "ATT-1", "ledger": "payment"},
        "confidence": "1.00",
    }
    repository.current_components = [
        {**shared, "name": "CURRENT-LEDGER-1"},
        {**shared, "name": "CURRENT-LEDGER-2"},
    ]

    _apply_matrix(repository, {"cells": []})

    saved = [
        component
        for row in repository.replaced
        for component in row["components"]
        if component["cost_effect"] == "LEDGER_ONLY"
    ]
    assert len(saved) == 2


def test_apply_material_matrix_reinserts_all_external_components_for_other_fee() -> None:
    repository = _MatrixApplyRepository()
    repository.fees["other_fee"] = {
        "name": "F-other_fee",
        "logical_fee_key": "other_fee",
        "amount": "20",
        "currency": "MXN",
    }
    shared = {
        "item": "ITEM-GLASSES",
        "stable_line_key": "LINE-GLASSES",
        "logical_fee_key": "other_fee",
        "component_type": "OTHER",
        "tax_code": "",
        "hs_code": "90041000",
        "currency": "MXN",
        "original_amount": "5.00",
        "amount_rmb": "2.50",
        "exchange_rate": "0.5",
        "allocation_basis": "legacy_external",
        "confidence": "1.00",
    }
    repository.current_components = [
        {
            **shared,
            "name": "OTHER-COST",
            "accounting_role": "FINAL_BILL",
            "cost_effect": "COST",
            "source_evidence": {"attachment": "ATT-1", "kind": "other-cost"},
        },
        {
            **shared,
            "name": "OTHER-LEDGER",
            "accounting_role": "SETTLEMENT",
            "cost_effect": "LEDGER_ONLY",
            "source_evidence": {"attachment": "ATT-1", "kind": "other-ledger"},
        },
    ]

    _apply_matrix(repository, {"cells": []})

    other_fee = next(
        row for row in repository.replaced if row["logical_fee_key"] == "other_fee"
    )
    assert len(other_fee["components"]) == 2
    assert {row["cost_effect"] for row in other_fee["components"]} == {
        "COST",
        "LEDGER_ONLY",
    }
    assert {
        row["source_evidence"]["kind"] for row in other_fee["components"]
    } == {"other-cost", "other-ledger"}


def test_apply_material_matrix_clear_preserves_unroutable_cost_with_same_import_tax_key() -> None:
    repository = _MatrixApplyRepository()
    repository.current_components = [
        {
            "name": "MATRIX-MANAGED-COST",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "logical_fee_key": "import_tax",
            "component_type": "IMPORT_TAX",
            "accounting_role": "FINAL_BILL",
            "cost_effect": "COST",
            "tax_code": "IGI",
            "hs_code": "90041000",
            "currency": "MXN",
            "original_amount": "8.00",
            "amount_rmb": "4.00",
            "exchange_rate": "0.5",
            "allocation_basis": "matrix_managed",
            "source_evidence": {"attachment": "ATT-1", "kind": "managed"},
        },
        {
            "name": "UNROUTABLE-COST",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "logical_fee_key": "import_tax",
            "component_type": "OTHER",
            "accounting_role": "FINAL_BILL",
            "cost_effect": "COST",
            "tax_code": "",
            "hs_code": "90041000",
            "currency": "MXN",
            "original_amount": "6.00",
            "amount_rmb": "3.00",
            "exchange_rate": "0.5",
            "allocation_basis": "legacy_external",
            "source_evidence": {"attachment": "ATT-1", "kind": "unroutable"},
        },
    ]

    _apply_matrix(repository, {"cells": []})

    import_tax = next(
        row for row in repository.replaced if row["logical_fee_key"] == "import_tax"
    )
    assert len(import_tax["components"]) == 1
    saved = import_tax["components"][0]
    assert saved["component_type"] == "OTHER"
    assert saved["cost_effect"] == "COST"
    assert saved["source_evidence"]["kind"] == "unroutable"


def test_apply_material_matrix_preserves_selected_external_cost_proposal() -> None:
    repository = _MatrixApplyRepository()
    repository.fees["other_fee"] = {
        "name": "F-other_fee",
        "logical_fee_key": "other_fee",
        "amount": "20",
        "currency": "MXN",
    }
    repository.draft["components"].append(
        {
            "proposal_id": "component:external-other",
            "item": "ITEM-GLASSES",
            "stable_line_key": "LINE-GLASSES",
            "component_type": "OTHER",
            "accounting_role": "FINAL_BILL",
            "cost_effect": "COST",
            "tax_code": "",
            "hs_code": "90041000",
            "currency": "MXN",
            "original_amount": "5.00",
            "amount_rmb": "2.50",
            "exchange_rate": "0.5",
            "allocation_basis": "selected_external",
            "source_evidence": {"attachment": "ATT-1", "kind": "selected"},
            "confidence": "1.00",
            "fee_logical_key": "other_fee",
        }
    )
    repository.run["draft_json"] = repository.draft

    _apply_matrix(
        repository,
        {"cells": []},
        selections=[
            "evidence:classification",
            "fee:import_tax",
            "component:external-other",
        ],
    )

    other_fee = next(
        row for row in repository.replaced if row["logical_fee_key"] == "other_fee"
    )
    assert len(other_fee["components"]) == 1
    saved = other_fee["components"][0]
    assert saved["component_type"] == "OTHER"
    assert saved["source_evidence"]["kind"] == "selected"


@pytest.mark.parametrize("hard_problem", ["ledger", "currency", "not_in_cell"])
def test_apply_material_matrix_source_must_be_valid_member_of_draft_cell(
    hard_problem,
) -> None:
    repository = _MatrixApplyRepository()
    proposal = {
        **repository.draft["components"][0],
        "proposal_id": f"component:forged:{hard_problem}",
    }
    if hard_problem == "ledger":
        proposal.update(accounting_role="SETTLEMENT", cost_effect="LEDGER_ONLY")
    elif hard_problem == "currency":
        proposal["currency"] = "EUR"
    repository.draft["components"].append(proposal)
    if hard_problem != "not_in_cell":
        first_row = repository.draft["material_matrix"]["rows"][0]
        first_row["cells"]["IGI"]["proposals"].append(
            len(repository.draft["components"]) - 1
        )
    repository.run["draft_json"] = repository.draft

    with pytest.raises(ValueError, match="单元格|不匹配|分项|来源"):
        _apply_matrix(
            repository,
            _matrix_apply_payload(
                _matrix_cell(
                    "IGI",
                    sources=[f"component:forged:{hard_problem}"],
                )
            ),
        )

    assert repository.replaced == []
    assert repository.rollbacks == 1


def test_apply_material_matrix_accepts_more_than_256_valid_sources_in_one_cell() -> None:
    repository = _MatrixApplyRepository()
    template = repository.draft["components"][0]
    proposals = [
        {
            **template,
            "proposal_id": f"component:igi:aggregate:{index}",
            "original_amount": "0.01",
            "amount_rmb": "0.005",
        }
        for index in range(300)
    ]
    repository.draft["components"] = proposals
    repository.draft["material_matrix"] = service.build_material_matrix(
        items=repository.items,
        components=proposals,
    )
    repository.run["draft_json"] = repository.draft

    result = _apply_matrix(
        repository,
        _matrix_apply_payload(
            _matrix_cell(
                "IGI",
                amount="3.00",
                sources=[row["proposal_id"] for row in proposals],
            )
        ),
    )

    assert result["component_count"] == 1
    saved = next(
        component
        for row in repository.replaced
        for component in row["components"]
    )
    assert len(saved["source_evidence"]["source_proposal_ids"]) == 300
    assert len(saved["source_evidence"]["source_proposals"]) == 300


def test_apply_material_matrix_rolls_back_when_replace_fails() -> None:
    repository = _MatrixApplyRepository(fail_replace=True)

    with pytest.raises(RuntimeError, match="replace failed"):
        _apply_matrix(repository, _matrix_apply_payload(_matrix_cell("IGI")))

    assert repository.commits == 0
    assert repository.rollbacks == 1
    assert not any(call[0] == "finish" for call in repository.calls)


def test_apply_material_matrix_attachment_change_returns_stale_without_writes() -> None:
    repository = _MatrixApplyRepository()
    repository.run["attachment_fingerprint"] = "old"
    repository.mark_stale = lambda run_id: repository.calls.append(("stale", run_id))

    result = _apply_matrix(repository, _matrix_apply_payload(_matrix_cell("IGI")))

    assert result["stale"] is True
    assert repository.replaced == []
    assert repository.commits == 0


def test_apply_material_matrix_concurrent_batch_change_rolls_back() -> None:
    repository = _MatrixApplyRepository()

    def reject_concurrent(*_args, **_kwargs):
        raise ValueError("批次已被修改")

    repository.assert_batch_write = reject_concurrent
    with pytest.raises(ValueError, match="批次已被修改"):
        _apply_matrix(repository, _matrix_apply_payload(_matrix_cell("IGI")))

    assert repository.rollbacks == 1
    assert repository.replaced == []


def test_settlement_evidence_cannot_be_selected_as_a_fee_total() -> None:
    with pytest.raises(ValueError, match="结算流水"):
        service.validate_fee_split_conservation(
            {
                "accounting_role": "SETTLEMENT",
                "currency": "MXN",
                "original_amount": "30",
            },
            [
                {
                    "logical_fee_key": "import_tax",
                    "currency": "MXN",
                    "amount": "30",
                    "amount_status": "ESTIMATED",
                }
            ],
        )


def test_end_to_end_mixed_customs_review_applies_only_confirmed_draft(monkeypatch) -> None:
    class Repository:
        def __init__(self):
            self.attachment = {
                "name": "ATT-MIXED",
                "batch": "B1",
                "version": "V1",
                "file_name": "完税与清关结算.pdf",
                "modified": "m1",
                "file_url": "/files/mixed.pdf",
                "parse_status": "Parsed",
                "parse_result_json": {
                    "parser": "mexico_tax_certificate_pedimento",
                    "header": {"paid_total_mxn": "70"},
                    "tax_totals": {"igi_mxn": "10", "iva_mxn": "20"},
                    "service_fees": [
                        {
                            "code": "broker_service",
                            "amount_mxn": "30",
                            "source_evidence": {"page": 2, "text_line": 8},
                        }
                    ],
                    "line_items": [
                        {
                            "row_no": 1,
                            "hs_code": "90041000",
                            "taxes": {
                                "igi_amount_mxn": "10",
                                "iva_amount_mxn": "20",
                            },
                            "source_evidence": {
                                "igi_amount_mxn": {"page": 1, "text_line": 10},
                                "iva_amount_mxn": {"page": 1, "text_line": 11},
                            },
                        }
                    ],
                    "source_evidence": {
                        "header.paid_total_mxn": {"page": 2, "text_line": 12},
                        "tax_totals.igi_mxn": {"page": 2, "text_line": 13},
                        "tax_totals.iva_mxn": {"page": 2, "text_line": 14},
                    },
                    "validation": {"status": "passed"},
                },
                "mapped_result_json": {},
            }
            self.items = _items()
            self.fees = {}
            self.evidence = {"E1": {"name": "E1", "validation_status": "PENDING"}}
            self.components = []
            self.run = None
            self.run_status = ""
            self.batch_status = "Draft"
            self.unclassified_difference_writes = 0
            self.external_calls = []
            self.commits = 0

        def get_context(self, batch_name, version_name):
            return {
                "batch": batch_name,
                "version": version_name,
                "transport_mode": "AIR",
                "fx_context": {"fx_rmb_to_mxn": "2"},
            }

        def lock_batch(self, _batch_name):
            return None

        def get_attachment(self, _batch_name, _attachment_name):
            return self.attachment

        def get_items(self, _batch_name, _version_name):
            return self.items

        def materialize_fee_rule(self, _batch, _version, logical_fee_key):
            return self.fees.setdefault(
                logical_fee_key,
                {
                    "name": f"F-{logical_fee_key}",
                    "logical_fee_key": logical_fee_key,
                    "amount_status": "MISSING",
                    "amount": None,
                    "currency": "RMB",
                },
            )

        def find_running(self, *_args):
            return None

        def find_reusable(self, *_args):
            return None

        def find_or_create_pending_evidence(self, **_kwargs):
            return "E1"

        def create_run(self, values):
            self.run = {"name": "RUN-E2E", **values}
            self.run_status = values["status"]
            return self.run

        def get_run(self, _run_id):
            return self.run

        def claim_run(self, _run_id, token):
            self.run.update(status="RUNNING", execution_token=token)
            self.run_status = "RUNNING"
            return self.run

        def save_claimed(self, _run_id, token, **updates):
            assert token == self.run["execution_token"]
            self.run.update(updates)
            self.run_status = self.run["status"]
            return self.run

        def save_attachment_parse(self, *_args):
            raise AssertionError("existing deterministic parse should be reused")

        def get_refund_candidates(self, *_args):
            return []

        def get_evidence_components(self, *_args):
            return []

        def lock_apply_context(self, _context, _run):
            return self.run

        def assert_batch_write(self, *_args, **_kwargs):
            return None

        def list_duplicate_evidence_candidates(self, *_args):
            return []

        def update_evidence(self, evidence_name, values):
            self.evidence[evidence_name].update(values)

        def save_fee_split(self, *, fee_row, **_kwargs):
            fee = self.materialize_fee_rule("B1", "V1", fee_row["logical_fee_key"])
            fee.update(
                amount=fee_row["amount"],
                currency=fee_row["currency"],
                amount_status=fee_row.get("amount_status") or "ACTUAL",
            )
            return fee

        def replace_components(self, *, components, **_kwargs):
            self.components.extend(components)

        def mark_batch_dirty(self, _batch_name):
            self.batch_status = "Dirty"

        def insert_review_audit(self, **_kwargs):
            return None

        def finish_run(self, _run_id, values):
            self.run.update(values)
            self.run_status = values["status"]

        def get_batch_modified(self, _batch_name):
            return "m2"

        def commit(self):
            self.commits += 1

        def rollback(self):
            return None

    repository = Repository()
    monkeypatch.setattr(
        service,
        "_semantic_ai_review",
        lambda *_args: {"ok": False, "warning": "DeepSeek unavailable", "model": ""},
    )
    queued = []

    started = service.start_fee_evidence_review(
        "B1",
        "V1",
        "import_tax",
        "ATT-MIXED",
        "tax_certificate",
        repository=repository,
        enqueue=queued.append,
    )
    assert queued == [started["run_id"]]
    assert service.execute_fee_evidence_review(
        started["run_id"], repository=repository
    )["status"] == "READY"
    draft = repository.run["draft_json"]
    selections = [
        row["proposal_id"]
        for row in [
            draft["evidence"],
            *draft["fee_splits"],
            *draft["components"],
        ]
        if row.get("default_selected")
    ]
    applied = service.apply_fee_evidence_review(
        "B1",
        started["run_id"],
        selections,
        {},
        "EDIT",
        "m1",
        repository=repository,
    )

    assert applied["fee_count"] == 2
    assert applied["component_count"] > 0
    assert draft["unclassified_difference"] == "10.00"
    assert repository.run_status == "APPLIED"
    assert repository.batch_status == "Dirty"
    assert repository.unclassified_difference_writes == 0
    assert repository.external_calls == []
