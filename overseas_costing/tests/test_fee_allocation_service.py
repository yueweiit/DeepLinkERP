"""逐费用范围和 Decimal 金额守恒分摊测试。"""

from overseas_costing.services.fee_allocation_service import allocate_fee


def test_item_scoped_fee_excludes_unrelated_items() -> None:
    result = allocate_fee(
        fee={
            "logical_fee_key": "PRODUCTION-EXTRA",
            "amount": "90",
            "currency": "CNY",
            "amount_status": "ACTUAL",
            "scope_type": "ITEMS",
            "scope_item_keys": ["P1", "P2"],
            "allocation_basis": "goods_value",
        },
        items=[
            {"stable_line_key": "P1", "goods_value": "100"},
            {"stable_line_key": "P2", "goods_value": "200"},
            {"stable_line_key": "E1", "goods_value": "300"},
        ],
    )

    assert result["allocations"] == {"P1": "30.00", "P2": "60.00", "E1": "0.00"}
    assert result["allocated_total"] == "90.00"


def test_missing_basis_on_one_eligible_item_blocks_entire_fee() -> None:
    result = allocate_fee(
        fee={
            "amount": "100",
            "amount_status": "ACTUAL",
            "scope_type": "ITEMS",
            "scope_item_keys": ["P1", "P2"],
            "allocation_basis": "gross_weight",
        },
        items=[
            {"stable_line_key": "P1", "gross_weight_kg": 10},
            {"stable_line_key": "P2", "gross_weight_kg": ""},
        ],
    )

    assert result["status"] == "BLOCKED"
    assert result["allocations"] == {}


def test_chargeable_weight_does_not_silently_fall_back_to_gross_weight() -> None:
    result = allocate_fee(
        fee={
            "amount": "100",
            "amount_status": "ACTUAL",
            "scope_type": "ALL_ITEMS",
            "allocation_basis": "chargeable_weight",
        },
        items=[{"stable_line_key": "P1", "gross_weight_kg": 10, "chargeable_weight_kg": ""}],
    )

    assert result["status"] == "BLOCKED"
    assert result["code"] == "ALLOCATION_BASIS_INCOMPLETE"


def test_direct_item_fee_does_not_require_an_unrelated_allocation_basis() -> None:
    result = allocate_fee(
        fee={
            "amount": "100",
            "amount_status": "ACTUAL",
            "scope_type": "DIRECT_ITEM",
            "scope_item_keys": ["P1"],
            "allocation_basis": "volume",
        },
        items=[{"stable_line_key": "P1", "volume_m3": ""}],
    )

    assert result["status"] == "ALLOCATED"
    assert result["allocations"] == {"P1": "100.00"}


def test_stable_remainder_preserves_the_fee_amount() -> None:
    result = allocate_fee(
        fee={
            "amount": "1.00",
            "amount_status": "ACTUAL",
            "scope_type": "ALL_ITEMS",
            "allocation_basis": "goods_value",
        },
        items=[
            {"stable_line_key": "C", "goods_value": "1"},
            {"stable_line_key": "A", "goods_value": "1"},
            {"stable_line_key": "B", "goods_value": "1"},
        ],
    )

    assert result["allocations"] == {"A": "0.34", "B": "0.33", "C": "0.33"}
    assert result["allocated_total"] == "1.00"


def test_non_counted_amount_states_do_not_enter_fee_pool() -> None:
    for status in ("MISSING", "NOT_INCURRED", "INCLUDED"):
        result = allocate_fee(
            fee={
                "amount": "100",
                "amount_status": status,
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "goods_value",
            },
            items=[{"stable_line_key": "P1", "goods_value": "100"}],
        )
        assert result["status"] == "NOT_COUNTED"
        assert result["allocated_total"] == "0.00"


def test_direct_item_scope_requires_exactly_one_item() -> None:
    result = allocate_fee(
        fee={
            "amount": "100",
            "amount_status": "ACTUAL",
            "scope_type": "DIRECT_ITEM",
            "scope_item_keys": ["P1", "P2"],
            "allocation_basis": "goods_value",
        },
        items=[
            {"stable_line_key": "P1", "goods_value": "100"},
            {"stable_line_key": "P2", "goods_value": "100"},
        ],
    )

    assert result["status"] == "BLOCKED"
    assert result["code"] == "DIRECT_ITEM_SCOPE_INVALID"
