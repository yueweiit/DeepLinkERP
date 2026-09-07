"""费用待办状态、完成条件与结果哈希测试。"""

from overseas_costing.services.fee_status_service import (
    build_cost_result_hash,
    build_fee_input_hash,
    build_fee_status,
    build_erp_work_state,
    build_erp_work_summary,
    summarize_fee_statuses,
)


def test_current_result_closes_only_successful_site_todo() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[
            {"site_code": "PROD", "last_cost_result_hash": "H2", "status": "SUCCESS"},
            {"site_code": "ECOM", "last_cost_result_hash": "H1", "status": "SUCCESS"},
        ],
    )

    assert work["PROD"]["todo"] is None
    assert work["ECOM"]["todo"]["code"] == "ERP_UPDATE_REQUIRED"
    summary = build_erp_work_summary(current_hash="H2", sites=list(work.values()))
    assert summary["overall"] == "PARTIAL"


def test_old_receipt_and_business_change_do_not_close_current_erp_todo() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[
            {
                "site_code": "PROD",
                "last_cost_result_hash": "H1",
                "request_cost_result_hash": "H1",
                "status": "SUCCESS",
            },
            {
                "site_code": "ECOM",
                "last_cost_result_hash": "H1",
                "status": "SUCCESS",
                "business_change_required": True,
            },
        ],
    )

    assert work["PROD"]["state"] == "UPDATE_REQUIRED"
    assert work["ECOM"]["state"] == "BUSINESS_CHANGE_REQUIRED"
    assert work["ECOM"]["todo"]["code"] == "ERP_BUSINESS_CHANGE_REQUIRED"


def test_erp_receipt_fields_do_not_change_fee_todos() -> None:
    fee = {
        "logical_fee_key": "FREIGHT",
        "amount": "100",
        "currency": "CNY",
        "amount_status": "ESTIMATED",
        "required_evidence_role": "invoice",
        "erp_status": "SUCCESS",
        "last_cost_result_hash": "H2",
    }

    result = build_fee_status(
        fee=fee,
        allocation={"status": "ALLOCATED"},
        evidence=[],
        calculation={"input_hash": "F1", "fee_input_hash": "F1"},
    )

    assert {todo["code"] for todo in result["todos"]} == {
        "ACTUAL_AMOUNT_REQUIRED",
        "EVIDENCE_REQUIRED",
    }


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
    assert result["affected_fee_count"] == 2


def test_invalidated_final_evidence_reopens_completion_without_forcing_recalc() -> None:
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

    codes = {todo["code"] for todo in result["todos"]}
    assert codes == {"EVIDENCE_REQUIRED", "ACTUAL_CONFIRMATION_INVALID"}
    assert "RECALCULATE_REQUIRED" not in codes


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


def test_cost_result_hash_changes_when_a_material_cost_changes() -> None:
    statuses = [{"fee_key": "FREIGHT", "amount_state": "ACTUAL", "input_hash": "FH1"}]
    first = build_cost_result_hash(
        [{"stable_line_key": "A", "total_cost_rmb": "150", "total_unit_rmb": "15"}],
        statuses,
        {"fx_rmb_to_mxn": "2.6"},
    )
    same = build_cost_result_hash(
        [{"total_unit_rmb": 15, "stable_line_key": "A", "total_cost_rmb": 150}],
        statuses,
        {"fx_rmb_to_mxn": 2.6},
    )
    changed = build_cost_result_hash(
        [{"stable_line_key": "A", "total_cost_rmb": "151", "total_unit_rmb": "15.1"}],
        statuses,
        {"fx_rmb_to_mxn": "2.6"},
    )

    assert first == same
    assert changed != first
