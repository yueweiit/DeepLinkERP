"""只读综合成本试算测试。"""

from copy import deepcopy

import pytest

from overseas_costing.services import cost_preview_service
from overseas_costing.services.cost_preview_service import preview_comprehensive_cost_data


def _items():
    return [
        {
            "name": "ITEM-A",
            "stable_line_key": "A",
            "material_code": "SKU-1",
            "product_name": "A",
            "purchase_uom": "件",
            "unit_price_uom": "件",
            "quantity": "10",
            "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
            "shipped_uom": "件",
            "goods_value": "100",
            "gross_weight_kg": "20",
            "volume_m3": "1",
        },
        {
            "name": "ITEM-B",
            "stable_line_key": "B",
            "material_code": "SKU-1",
            "product_name": "B",
            "purchase_uom": "桶",
            "unit_price_uom": "kg",
            "quantity": "10",
            "actual_shipped_qty": "5",
            "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
            "shipped_uom": "桶",
            "goods_value": "100",
            "gross_weight_kg": "30",
            "volume_m3": "1",
        },
    ]


def test_preview_conserves_direct_and_allocated_fees_with_dual_unit_output() -> None:
    result = preview_comprehensive_cost_data(
        _items(),
        [
            {
                "logical_fee_key": "freight",
                "expense_category": "国际海运费",
                "amount_status": "ACTUAL",
                "amount": "100",
                "currency": "RMB",
                "allocation_basis": "goods_value",
                "scope_type": "ALL_ITEMS",
            },
            {
                "logical_fee_key": "inspection",
                "expense_category": "检查费",
                "amount_status": "ACTUAL",
                "amount": "20",
                "currency": "RMB",
                "allocation_basis": "gross_weight",
                "scope_type": "DIRECT_ITEM",
                "scope_item_keys": ["A"],
            },
        ],
        {"fx_usd_to_rmb": "7", "fx_rmb_to_mxn": "2.5"},
    )

    assert result["summary"] == {
        "purchase_goods_value_rmb": "200.00",
        "direct_fees_rmb": "20.00",
        "allocated_fees_rmb": "100.00",
        "total_cost_rmb": "320.00",
        "included_fee_count": 2,
        "excluded_fee_count": 0,
        "is_complete": True,
    }
    assert result["items"][0]["total_cost_rmb"] == "170.00"
    assert result["items"][0]["shipping_unit_cost"] == {"amount_rmb": "17.000000", "uom": "件"}
    assert result["items"][0]["purchase_pricing_unit_cost"] == {
        "amount_rmb": "17.000000",
        "uom": "件",
    }
    assert result["items"][1]["total_cost_rmb"] == "150.00"
    assert result["items"][1]["shipping_unit_cost"] == {"amount_rmb": "30.000000", "uom": "桶"}
    assert result["items"][1]["purchase_pricing_unit_cost"] is None


def test_preview_lists_missing_fx_unknown_amount_and_unallocatable_fees_without_zeroing() -> None:
    result = preview_comprehensive_cost_data(
        _items(),
        [
            {
                "logical_fee_key": "missing",
                "amount_status": "MISSING",
                "currency": "RMB",
                "allocation_basis": "goods_value",
            },
            {
                "logical_fee_key": "usd",
                "amount_status": "ACTUAL",
                "amount": "10",
                "currency": "USD",
                "allocation_basis": "goods_value",
            },
            {
                "logical_fee_key": "volume",
                "amount_status": "ESTIMATED",
                "amount": "50",
                "currency": "RMB",
                "allocation_basis": "chargeable_weight",
            },
        ],
        {"fx_usd_to_rmb": "", "fx_rmb_to_mxn": "2.5"},
    )

    assert result["summary"]["total_cost_rmb"] == "200.00"
    assert result["summary"]["excluded_fee_count"] == 3
    assert result["summary"]["is_complete"] is False
    assert {row["reason_code"] for row in result["excluded_fees"]} == {
        "AMOUNT_MISSING",
        "FX_RATE_MISSING",
        "ALLOCATION_BASIS_INCOMPLETE",
    }


def test_preview_does_not_mutate_input_or_block_on_missing_project() -> None:
    items = _items()
    for row in items:
        row["project_collection"] = ""
    fees = [
        {
            "logical_fee_key": "delivery",
            "amount_status": "ACTUAL",
            "amount": "10",
            "currency": "RMB",
            "allocation_basis": "gross_weight",
        }
    ]
    before = (deepcopy(items), deepcopy(fees))

    result = preview_comprehensive_cost_data(items, fees, {})

    assert result["summary"]["is_complete"] is True
    assert (items, fees) == before
    assert all("project_collection" not in reason.get("field", "") for reason in result["incomplete_reasons"])


def test_preview_rejects_a_version_from_another_batch(monkeypatch) -> None:
    class FakeDb:
        @staticmethod
        def get_value(doctype, name, fieldname, **_kwargs):
            if doctype == "Overseas Cost Version" and fieldname == "batch":
                return "OTHER-BATCH"
            return None

    class FakeFrappe:
        db = FakeDb()

    monkeypatch.setattr(cost_preview_service, "frappe", FakeFrappe())

    with pytest.raises(ValueError, match="不属于当前批次"):
        cost_preview_service.preview_comprehensive_cost("BATCH-1", "VERSION-OTHER")
