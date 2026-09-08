"""费用待办状态、完成条件与结果哈希测试。"""

from overseas_costing.services.fee_status_service import (
    build_fee_input_hash,
    build_fee_status,
    summarize_fee_statuses,
)


def test_estimated_allocated_fee_keeps_actual_and_evidence_todos() -> None:
    result = build_fee_status(
        fee={
            "logical_fee_key": "TAX",
            "amount": "1000",
            "currency": "MXN",
            "amount_status": "ESTIMATED",
            "required_evidence_role": "tax_certificate",
        },
        allocation={"status": "ALLOCATED", "amount": "1000", "allocated_total": "1000"},
        evidence=[],
        calculation={"input_hash": "H1", "fee_input_hash": "H1"},
    )

    assert {row["code"] for row in result["todos"]} == {
        "ACTUAL_AMOUNT_REQUIRED",
        "EVIDENCE_REQUIRED",
    }


def test_missing_amount_is_not_counted_as_zero_unallocated_money() -> None:
    result = summarize_fee_statuses(
        [
            {
                "fee_key": "F1",
                "amount_state": "MISSING",
                "currency": "CNY",
                "amount": "",
                "todos": [{"code": "AMOUNT_REQUIRED"}],
            },
            {
                "fee_key": "F2",
                "amount_state": "ACTUAL",
                "currency": "CNY",
                "amount": "80",
                "todos": [{"code": "ALLOCATION_REQUIRED"}],
            },
        ]
    )

    assert result["missing_amount_fee_count"] == 1
    assert result["unallocated_by_currency"] == {"CNY": "80"}
    assert result["unallocated_fee_count"] == 1
    assert result["affected_fee_count"] == 2


def test_summary_exposes_evidence_and_estimate_counts_for_page_header() -> None:
    result = summarize_fee_statuses(
        [
            {
                "fee_key": "F1",
                "amount_state": "ESTIMATED",
                "evidence_state": "MISSING",
                "currency": "USD",
                "amount": "20",
                "todos": [
                    {"code": "ACTUAL_AMOUNT_REQUIRED"},
                    {"code": "EVIDENCE_REQUIRED"},
                ],
            },
            {
                "fee_key": "F2",
                "amount_state": "ACTUAL",
                "evidence_state": "PENDING",
                "currency": "RMB",
                "amount": "10",
                "todos": [{"code": "EVIDENCE_VALIDATION_REQUIRED"}],
            },
        ]
    )

    assert result["estimated_fee_count"] == 1
    assert result["missing_evidence_fee_count"] == 1
    assert result["pending_evidence_fee_count"] == 1


def test_invalid_final_evidence_keeps_the_evidence_todo_open() -> None:
    result = build_fee_status(
        fee={
            "logical_fee_key": "TAX",
            "amount": "1000",
            "currency": "MXN",
            "amount_status": "ACTUAL",
            "required_evidence_role": "tax_certificate",
        },
        allocation={"status": "ALLOCATED", "amount": "1000", "allocated_total": "1000"},
        evidence=[{"evidence_role": "tax_certificate", "validation_status": "INVALID"}],
        calculation={"input_hash": "H1", "fee_input_hash": "H1"},
    )

    assert {todo["code"] for todo in result["todos"]} == {"EVIDENCE_REQUIRED"}


def test_not_incurred_or_included_fee_does_not_require_evidence() -> None:
    for amount_status in ("NOT_INCURRED", "INCLUDED"):
        result = build_fee_status(
            fee={
                "logical_fee_key": "FEE",
                "amount_status": amount_status,
                "required_evidence_role": "expense_invoice",
            },
            allocation={"status": "NOT_COUNTED"},
            evidence=[],
        )

        assert result["evidence_state"] == "NOT_REQUIRED"
        assert result["todos"] == []


def test_fee_input_hash_is_stable_and_changes_with_cost_inputs() -> None:
    fee = {
        "logical_fee_key": "FREIGHT",
        "amount": "100",
        "amount_status": "ACTUAL",
        "allocation_basis": "gross_weight",
        "scope_type": "ITEMS",
        "scope_item_keys": ["B", "A"],
        "amount_revision": "A1",
        "scope_revision": "S1",
    }
    items = [
        {"stable_line_key": "A", "actual_shipped_qty_source_revision": "Q1"},
        {"stable_line_key": "B", "actual_shipped_qty_source_revision": "Q2"},
    ]

    first = build_fee_input_hash(fee, items=items, fx_context={"fx_rmb_to_mxn": "2.6"})
    same = build_fee_input_hash(
        {**fee, "scope_item_keys": ["A", "B"]},
        items=list(reversed(items)),
        fx_context={"fx_rmb_to_mxn": "2.6"},
    )
    changed = build_fee_input_hash(
        {**fee, "amount": "101"},
        items=items,
        fx_context={"fx_rmb_to_mxn": "2.6"},
    )

    assert first == same
    assert changed != first


def test_invalid_historical_amounts_do_not_crash_or_pollute_summary():
    from overseas_costing.services.fee_allocation_service import allocate_fee
    for amount in ["NaN", "Infinity", "sNaN"]:
        fee = {"logical_fee_key": "bad", "amount_status": "ACTUAL", "currency": "RMB", "amount": amount}
        status = build_fee_status(fee=fee, allocation=allocate_fee(fee, []), evidence=[])
        assert any(todo["code"] == "FEE_AMOUNT_INVALID" for todo in status["todos"])
        assert summarize_fee_statuses([status])["unallocated_by_currency"] == {}
