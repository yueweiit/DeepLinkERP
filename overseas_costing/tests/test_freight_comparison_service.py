"""中文用途：整票按重量/体积报价的精确计算、保存与正式成本隔离测试。"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from overseas_costing.services.freight_comparison_service import (
    ceil_to_increment,
    compare_freight,
    save_freight_comparison,
)


def _quote(scope_confirmed=True):
    return {
        "currency": "USD",
        "scope_confirmed": scope_confirmed,
        "weight": {
            "unit_price": "1.2",
            "min_quantity": "4200",
            "rounding_increment": "10",
            "min_base_freight": "5000",
            "surcharge": "100",
        },
        "volume": {
            "unit_price": "560",
            "min_quantity": "0",
            "rounding_increment": "0.1",
            "min_base_freight": "0",
            "surcharge": "80",
        },
        "quote_remark": "同一承运范围的两套报价",
    }


def test_compare_freight_uses_ceiling_minimums_and_exact_decimal_trace() -> None:
    result = compare_freight(
        gross_weight_kg="4197.4",
        volume_m3="8.7403305",
        currency="USD",
        scope_confirmed=True,
        weight=_quote()["weight"],
        volume=_quote()["volume"],
    )

    assert ceil_to_increment(Decimal("8.7403305"), Decimal("0.1")) == Decimal("8.8")
    assert result["weight"]["chargeable_quantity"] == "4200"
    assert result["weight"]["calculated_base_freight"] == "5040.0"
    assert result["weight"]["base_freight"] == "5040.0"
    assert result["weight"]["total"] == "5140.0"
    assert result["volume"]["chargeable_quantity"] == "8.8"
    assert result["volume"]["total"] == "5008.0"
    assert result["recommended_basis"] == "volume"
    assert result["difference_amount"] == "132.0"
    assert result["savings_percent"].startswith("2.568093385")
    assert result["display"] == {
        "weight_total": "5,140.00",
        "volume_total": "5,008.00",
        "difference_amount": "132.00",
        "savings_percent": "2.57%",
        "currency": "USD",
    }


def test_scope_must_be_confirmed_before_recommending_cheaper_basis() -> None:
    result = compare_freight(
        gross_weight_kg="100",
        volume_m3="1",
        currency="CNY",
        scope_confirmed=False,
        weight={"unit_price": "1", "surcharge": "0"},
        volume={"unit_price": "200", "surcharge": "0"},
    )

    assert result["weight"]["total"] == "100"
    assert result["volume"]["total"] == "200"
    assert result["recommended_basis"] is None
    assert result["scope_status"] == "unconfirmed"


def test_equal_quotes_and_explicit_zero_are_distinct_from_absent_values() -> None:
    equal = compare_freight(
        gross_weight_kg="10",
        volume_m3="2",
        currency="USD",
        scope_confirmed=True,
        weight={"unit_price": "0", "surcharge": "10"},
        volume={"unit_price": "5", "surcharge": "0"},
    )
    assert equal["recommended_basis"] == "equal"
    assert equal["difference_amount"] == "0"

    with pytest.raises(ValueError, match="unit_price 不能为空"):
        compare_freight(
            gross_weight_kg="10",
            volume_m3="2",
            currency="USD",
            scope_confirmed=True,
            weight={"surcharge": "0"},
            volume={"unit_price": "5", "surcharge": "0"},
        )


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "-Infinity"])
def test_invalid_numeric_inputs_are_rejected(value) -> None:
    with pytest.raises(ValueError):
        compare_freight(
            gross_weight_kg=value,
            volume_m3="1",
            currency="USD",
            scope_confirmed=True,
            weight={"unit_price": "1"},
            volume={"unit_price": "1"},
        )


def test_both_quotes_must_use_common_currency() -> None:
    with pytest.raises(ValueError, match="同一币种"):
        compare_freight(
            gross_weight_kg="10",
            volume_m3="1",
            currency="USD",
            scope_confirmed=True,
            weight={"unit_price": "1", "currency": "USD"},
            volume={"unit_price": "1", "currency": "CNY"},
        )


class FakeRepository:
    def __init__(self):
        self.snapshot = {
            "name": "SNAP-1",
            "batch": "BATCH-1",
            "idempotency_key": "snapshot-revision-1",
            "status": "Confirmed",
            "is_current": 1,
            "total_gross_weight_kg": "4197.4",
            "total_volume_m3": "8.7403305",
        }
        self.current_name = "SNAP-1"
        self.saved = []
        self.audits = []
        self.domain_state = {
            "items": [{"name": "ITEM-1", "freight": "100"}],
            "expense_pool": [{"name": "EXP-1", "amount": "100"}],
            "version": {"status": "Active"},
            "batch": {"status": "Calculated", "writeback_status": "Not Started"},
        }
        self.commits = 0

    def lock_batch(self, batch_name):
        assert batch_name == "BATCH-1"

    def get_by_request_id(self, request_id):
        return next((row for row in self.saved if row["request_id"] == request_id), None)

    def get_snapshot(self, batch_name, revision):
        if batch_name == "BATCH-1" and revision == self.snapshot["idempotency_key"]:
            return self.snapshot
        return None

    def get_current_snapshot_name(self, _batch_name):
        return self.current_name

    def insert_comparison(self, values):
        row = {"name": f"COMPARE-{len(self.saved) + 1}", **values}
        self.saved.append(row)
        return row

    def write_audit(self, values):
        self.audits.append(values)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_save_is_idempotent_and_does_not_modify_formal_cost_state() -> None:
    repository = FakeRepository()
    before = copy.deepcopy(repository.domain_state)
    request_id = "f" * 64

    first = save_freight_comparison(
        "BATCH-1", "snapshot-revision-1", request_id, _quote(), repository=repository
    )
    second = save_freight_comparison(
        "BATCH-1", "snapshot-revision-1", request_id, _quote(), repository=repository
    )

    assert first["ok"] is True
    assert first["comparison"]["name"] == "COMPARE-1"
    assert second["idempotent"] is True
    assert len(repository.saved) == 1
    assert repository.audits[0]["action_type"] == "FREIGHT_COMPARE"
    assert repository.domain_state == before
    assert repository.commits == 1


def test_old_comparison_is_marked_when_newer_snapshot_is_current() -> None:
    repository = FakeRepository()
    result = save_freight_comparison(
        "BATCH-1", "snapshot-revision-1", "e" * 64, _quote(), repository=repository
    )
    repository.current_name = "SNAP-2"

    from overseas_costing.services.freight_comparison_service import public_comparison

    public = public_comparison(result["comparison"], current_snapshot_name=repository.current_name)
    assert public["based_on_superseded_snapshot"] is True
