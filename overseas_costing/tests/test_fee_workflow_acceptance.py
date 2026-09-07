"""费用分摊、暂估实际化与持续待办的本地验收测试。"""

from decimal import Decimal

from overseas_costing.scripts.seed_workbench_sample import build_fee_workflow_acceptance_sample
from overseas_costing.services import fee_allocation_service, fee_service, fee_status_service


def _sample() -> dict:
    return build_fee_workflow_acceptance_sample()


def _fee(key: str) -> dict:
    return next(row for row in _sample()["fees"] if row["logical_fee_key"] == key)


def test_fee_sample_is_local_only_and_covers_required_scenarios() -> None:
    sample = _sample()

    assert sample["batch"]["writeback_status"] == "Success"
    assert sample["batch"]["extra_json"]["live_integrations"] is False
    assert "http://" not in str(sample)
    assert "https://" not in str(sample)
    assert {row["scope_type"] for row in sample["fees"]} >= {"ALL_ITEMS", "ITEMS", "DIRECT_ITEM"}
    assert {row["amount_status"] for row in sample["fees"]} >= {"MISSING", "ESTIMATED", "ACTUAL", "NOT_INCURRED"}
    assert {row["lifecycle_case"] for row in sample["lifecycle"]} == {
        "estimate_to_actual_same_amount",
        "amount_change",
        "scope_change",
        "evidence_invalidated",
    }


def test_every_counted_fee_conserves_amount_and_excludes_out_of_scope_items() -> None:
    sample = _sample()
    items = sample["items"]

    for fee in sample["fees"]:
        result = fee_allocation_service.allocate_fee(fee, items)
        if fee["amount_status"] not in fee_allocation_service.COUNTED_AMOUNT_STATUSES:
            assert result["status"] == "NOT_COUNTED"
            continue
        assert result["status"] == "ALLOCATED"
        assert sum(Decimal(value) for value in result["allocations"].values()) == Decimal(result["allocated_total"])
        assert Decimal(result["allocated_total"]) == Decimal(str(fee["amount"])).quantize(Decimal("0.01"))

    production = fee_allocation_service.allocate_fee(_fee("PRODUCTION-EXTRA"), items)
    direct = fee_allocation_service.allocate_fee(_fee("ECOMMERCE-DIRECT"), items)
    assert production["allocations"]["E-1"] == "0.00"
    assert direct["allocations"]["P-1"] == "0.00"
    assert direct["allocations"]["P-2"] == "0.00"


def test_estimate_to_actual_same_amount_replaces_logical_fee_instead_of_adding() -> None:
    estimated = _fee("FREIGHT")
    actual = {**estimated, "amount_status": "ACTUAL"}

    result = fee_service.merge_logical_fee([estimated], actual, revision="REV-ACTUAL")

    assert len(result["fees"]) == 1
    assert result["action"] == "updated"
    assert result["cost_inputs_changed"] is True
    assert result["fee"]["amount"] == estimated["amount"]
    assert result["fee"]["amount_status"] == "ACTUAL"
    assert result["fee"]["amount_revision"] == "REV-ACTUAL"


def test_amount_and_scope_changes_each_advance_the_correct_revision() -> None:
    original = _fee("PRODUCTION-EXTRA")
    amount_changed = fee_service.merge_logical_fee(
        [original], {**original, "amount": "120"}, revision="REV-AMOUNT"
    )["fee"]
    scope_changed = fee_service.merge_logical_fee(
        [amount_changed],
        {**amount_changed, "scope_item_keys": ["P-2"], "scope_value_json": '["P-2"]'},
        revision="REV-SCOPE",
    )["fee"]

    assert amount_changed["amount_revision"] == "REV-AMOUNT"
    assert scope_changed["scope_revision"] == "REV-SCOPE"


def test_same_amount_nature_change_invalidates_completion_hash() -> None:
    sample = _sample()
    estimated = _fee("FREIGHT")
    actual = {**estimated, "amount_status": "ACTUAL"}
    estimated_hash = fee_status_service.build_fee_input_hash(estimated, items=sample["items"], fx_context=sample["fx"])
    actual_hash = fee_status_service.build_fee_input_hash(actual, items=sample["items"], fx_context=sample["fx"])
    estimated_status = fee_status_service.build_fee_status(
        fee=estimated,
        allocation={"status": "ALLOCATED"},
        evidence=[],
        calculation={"input_hash": estimated_hash, "fee_input_hash": estimated_hash},
    )
    actual_status = fee_status_service.build_fee_status(
        fee=actual,
        allocation={"status": "ALLOCATED"},
        evidence=[],
        calculation={"input_hash": actual_hash, "fee_input_hash": actual_hash},
    )

    assert estimated_hash != actual_hash
    assert fee_service.build_completion_input_hash([estimated_status]) != fee_service.build_completion_input_hash([actual_status])


def test_invalid_final_evidence_reopens_fee_after_confirmation() -> None:
    fee = _fee("IMPORT-TAX")
    current_hash = "CURRENT-HASH"
    complete = fee_status_service.build_fee_status(
        fee=fee,
        allocation={"status": "ALLOCATED"},
        evidence=[{"evidence_role": "tax_certificate", "validation_status": "VALID"}],
        calculation={"input_hash": current_hash, "fee_input_hash": current_hash},
        completion={"status": "CONFIRMED"},
    )
    reopened = fee_status_service.build_fee_status(
        fee=fee,
        allocation={"status": "ALLOCATED"},
        evidence=[{"evidence_role": "tax_certificate", "validation_status": "INVALID"}],
        calculation={"input_hash": current_hash, "fee_input_hash": current_hash},
        completion={"status": "INVALIDATED"},
    )

    assert complete["todos"] == []
    assert {todo["code"] for todo in reopened["todos"]} >= {"EVIDENCE_REQUIRED", "ACTUAL_CONFIRMATION_INVALID"}


def test_erp_success_never_closes_fee_todos() -> None:
    fee = _fee("FREIGHT")
    base = fee_status_service.build_fee_status(
        fee=fee,
        allocation={"status": "ALLOCATED"},
        evidence=[],
        calculation={"input_hash": "A", "fee_input_hash": "A"},
    )
    after_erp = fee_status_service.build_fee_status(
        fee={**fee, "erp_status": "Success", "erp_sync_revision": "SYNC-1"},
        allocation={"status": "ALLOCATED"},
        evidence=[],
        calculation={"input_hash": "A", "fee_input_hash": "A"},
    )

    assert base["todos"] == after_erp["todos"]
    assert {todo["code"] for todo in after_erp["todos"]} == {"ACTUAL_AMOUNT_REQUIRED", "EVIDENCE_REQUIRED"}
