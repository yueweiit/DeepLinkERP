"""物料数量、单位和稳定行标识的契约测试。"""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from overseas_costing.services.material_input_service import (
    GRID_FIELDS,
    analyze_material_requirements,
    assert_complete_purchase_values,
    build_shipping_quantity_updates,
    ensure_stable_line_key,
    normalize_grid_page,
    present_material_row,
    purchase_value_coverage,
    resolve_effective_quantity,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_quantity_follows_purchase_source() -> None:
    result = resolve_effective_quantity(
        {
            "quantity": "34",
            "actual_shipped_qty": "",
            "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
            "purchase_uom": "桶",
            "shipped_uom": "桶",
        }
    )

    assert result == {
        "quantity": "34",
        "uom": "桶",
        "mode": "DEFAULT_PURCHASE",
        "is_default": True,
        "blocking": [],
    }


def test_explicit_quantity_does_not_follow_purchase_update() -> None:
    result = resolve_effective_quantity(
        {
            "quantity": "34",
            "actual_shipped_qty": "32",
            "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
            "purchase_uom": "桶",
            "shipped_uom": "桶",
        }
    )

    assert result["quantity"] == "32"
    assert result["is_default"] is False


def test_missing_explicit_shipping_quantity_defaults_to_purchase_quantity() -> None:
    result = resolve_effective_quantity(
        {
            "quantity": "34",
            "actual_shipped_qty": "",
            "actual_shipped_qty_mode": "",
            "unit": "桶",
        }
    )

    assert result["quantity"] == "34"
    assert result["mode"] == "DEFAULT_PURCHASE"
    assert result["is_default"] is True


def test_legacy_equal_values_are_not_reclassified_as_default() -> None:
    result = resolve_effective_quantity(
        {
            "quantity": "34",
            "actual_shipped_qty": "34",
            "actual_shipped_qty_mode": "LEGACY_UNVERIFIED",
            "unit": "桶",
        }
    )

    assert result["mode"] == "LEGACY_UNVERIFIED"
    assert result["is_default"] is False


def test_invalid_quantity_and_missing_unit_are_both_reported() -> None:
    result = resolve_effective_quantity(
        {
            "quantity": "0",
            "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
        }
    )

    assert result["quantity"] == ""
    assert {row["code"] for row in result["blocking"]} == {
        "SHIPPED_QTY_REQUIRED",
        "SHIPPED_UOM_REQUIRED",
    }


def test_stable_line_key_is_preserved_or_created_once() -> None:
    assert ensure_stable_line_key({"stable_line_key": "  LINE-1  "}) == "LINE-1"
    assert ensure_stable_line_key({}, key_factory=lambda: "LINE-2") == "LINE-2"


def test_legacy_rows_with_duplicate_sku_keep_distinct_row_identity() -> None:
    first = present_material_row({"name": "ITEM-1", "material_code": "SKU-1", "quantity": 2})
    second = present_material_row({"name": "ITEM-2", "material_code": "SKU-1", "quantity": 3})

    assert first["stable_line_key"] == "legacy:ITEM-1"
    assert second["stable_line_key"] == "legacy:ITEM-2"
    assert first["stable_line_key"] != second["stable_line_key"]


def test_missing_purchase_price_uses_purchase_total_and_partial_shipment_is_prorated_without_mutation() -> None:
    source = {
        "name": "ITEM-1",
        "quantity": 1700,
        "actual_shipped_qty": 1500,
        "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
        "shipped_uom": "个",
        "purchase_uom": "pieza",
        "unit": "pieza",
        "unit_price": 0,
        "purchase_currency": "",
        "unit_price_uom": "",
        "goods_value": 2067,
    }
    original = deepcopy(source)

    presented = present_material_row(source)

    assert presented["adopted_price"] == {
        "value": "1.22",
        "calculation_value": "1.215882352941176470588235294",
        "currency": "RMB",
        "unit": "pieza",
        "error": "",
        "source_type": "purchase_total_derived",
        "source": "LEGACY_PURCHASE",
        "evidence": {
            "total_goods_value_rmb": "2067",
            "purchase_quantity": "1700",
            "purchase_uom": "pieza",
        },
    }
    assert Decimal(presented["shipment_value_rmb"]) == Decimal("2067") * Decimal("1500") / Decimal("1700")
    assert presented["shipment_valuation"]["method"] == "purchase_total_proration"
    assert presented["shipment_valuation"]["input_evidence"] == {
        "total_goods_value_rmb": "2067",
        "purchase_quantity": "1700",
        "purchase_uom": "个",
        "actual_shipped_qty": "1500",
        "shipped_uom": "个",
    }
    assert source == original


def test_purchase_total_proration_refuses_incompatible_purchase_and_shipping_units() -> None:
    source = {
        "name": "ITEM-1",
        "quantity": 10,
        "actual_shipped_qty": 5,
        "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
        "shipped_uom": "kg",
        "purchase_uom": "箱",
        "unit": "箱",
        "unit_price": 0,
        "goods_value": 100,
    }

    presented = present_material_row(source)

    assert presented["adopted_price"]["value"] == "10.00"
    assert presented["shipment_value_rmb"] is None
    assert presented["shipment_valuation"]["error"] == "PURCHASE_TOTAL_PRORATION_UOM_MISMATCH"


def test_existing_purchase_price_wins_over_shipment_value_derived_price() -> None:
    source = {
        "name": "ITEM-1",
        "quantity": 2,
        "purchase_uom": "件",
        "unit_price": "3.50",
        "purchase_currency": "USD",
        "unit_price_uom": "件",
        "goods_value": 50,
    }

    presented = present_material_row(source)

    assert presented["adopted_price"]["value"] == "3.50"
    assert presented["adopted_price"]["calculation_value"] == "3.50"
    assert presented["adopted_price"]["source_type"] == "explicit_purchase_price"
    assert presented["unit_price"] == "3.50"


@pytest.mark.parametrize(
    ("price_fields", "expected_value", "expected_source"),
    [
        (
            {"unit_price": "3.50", "purchase_currency": "USD", "unit_price_uom": "kg"},
            "3.50",
            "explicit_purchase_price",
        ),
        (
            {"unit_price": 0, "purchase_currency": "", "unit_price_uom": ""},
            "200.00",
            "purchase_total_derived",
        ),
    ],
)
def test_payment_bound_local_packing_value_uses_canonical_price_projection(
    price_fields, expected_value, expected_source
) -> None:
    source = {
        "name": "ITEM-1",
        "quantity": 4,
        "purchase_uom": "kg",
        "unit": "kg",
        "goods_value": 800,
        **price_fields,
        "extra_json": json.dumps({
            "effective_logistics_source": {
                "root_kind": "expense",
                "separate_adoption": True,
            },
            "shipment_valuation": {
                "amount_rmb": "800",
                "quantity": "4",
                "uom": "kg",
                "currency": "RMB",
                "method": "packing_row_total",
                "source_refs": [{"source_id": "LOCAL-PACK", "row": 2}],
            },
        }),
    }

    presented = present_material_row(source)

    assert presented["adopted_price"]["value"] == expected_value
    assert presented["adopted_price"]["source_type"] == expected_source


def test_errored_settlement_price_is_not_adopted_or_reused_from_raw_fields() -> None:
    source = {
        "name": "ITEM-1",
        "quantity": 4,
        "actual_shipped_qty": 4,
        "shipped_uom": "kg",
        "purchase_uom": "kg",
        "unit": "kg",
        "unit_price": 300,
        "purchase_currency": "RMB",
        "unit_price_uom": "kg",
        "goods_value": 1200,
        "extra_json": json.dumps({
            "settlement_cargo": {"quantity": "4", "unit": "kg"},
            "settlement_valuation": {
                "amount_rmb": None,
                "quantity": "4",
                "uom": "kg",
                "currency": "RMB",
                "method": "settlement_expense_unit_price",
                "status": "conflict",
                "error": "SETTLEMENT_EXPENSE_PRICE_AMBIGUOUS",
                "trusted_shipment_source": True,
                "input_evidence": {
                    "price": "300",
                    "original_currency": "RMB",
                    "price_uom": "kg",
                    "purchase_source": "PAYMENT-1",
                },
            },
        }),
    }

    presented = present_material_row(source)

    assert presented.get("adopted_price") in (None, {})


def test_grid_pagination_is_bounded_without_silently_skipping_page() -> None:
    assert normalize_grid_page("2", "999") == (2, 200)
    assert normalize_grid_page("bad", "bad") == (1, 100)


def test_shipping_quantity_updates_keep_default_and_manual_modes_distinct() -> None:
    default_updates = build_shipping_quantity_updates(
        {"quantity": 34, "purchase_uom": "桶", "actual_shipped_qty": 32},
        mode="DEFAULT_PURCHASE",
        value="",
        uom="",
    )
    manual_updates = build_shipping_quantity_updates(
        {"quantity": 34, "purchase_uom": "桶"},
        mode="MANUAL_CONFIRMED",
        value="32",
        uom="桶",
    )

    assert default_updates == {
        "actual_shipped_qty": None,
        "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
        "actual_shipped_qty_source_revision": "",
        "shipped_uom": "桶",
        "cost_output_uom": "桶",
    }
    assert manual_updates["actual_shipped_qty"] == "32"
    assert manual_updates["actual_shipped_qty_mode"] == "MANUAL_CONFIRMED"


def test_item_doctype_mirrors_include_quantity_provenance_fields() -> None:
    source_path = ROOT / "doctype/overseas_cost_item/overseas_cost_item.json"
    mirror_path = ROOT / "overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
    fields = {row["fieldname"]: row for row in source["fields"]}

    assert source == mirror
    assert {
        "stable_line_key",
        "purchase_uom",
        "unit_price_uom",
        "shipped_uom",
        "cost_output_uom",
        "actual_shipped_qty_mode",
        "actual_shipped_qty_source_revision",
        "net_weight_kg",
        "is_excluded",
        "excluded_at",
        "excluded_by",
        "exclusion_reason",
    } <= fields.keys()
    assert fields["stable_line_key"]["read_only"] == 1
    assert fields["cost_output_uom"]["read_only"] == 1
    assert fields["net_weight_kg"]["fieldtype"] == "Float"
    assert "net_weight_kg" in GRID_FIELDS


def test_grid_query_only_requests_physical_item_columns() -> None:
    source_path = ROOT / "doctype/overseas_cost_item/overseas_cost_item.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    physical_fields = {row["fieldname"] for row in source["fields"]}

    assert set(GRID_FIELDS) <= physical_fields | {"name", "modified"}
    assert "package_count" not in GRID_FIELDS
    assert "packaging_type" not in GRID_FIELDS


def test_material_requirements_mark_only_active_contextual_missing_cells() -> None:
    result = analyze_material_requirements(
        [
            {
                "name": "ITEM-1",
                "stable_line_key": "A",
                "quantity": "10",
                "purchase_uom": "件",
                "goods_value": "100",
                "volume_m3": "",
                "gross_weight_kg": "",
                "project_collection": "",
            },
            {
                "name": "ITEM-2",
                "stable_line_key": "B",
                "quantity": "5",
                "purchase_uom": "件",
                "goods_value": "50",
                "volume_m3": "2",
                "gross_weight_kg": "",
                "project_collection": "",
            },
        ],
        [
            {
                "logical_fee_key": "freight",
                "amount_status": "ACTUAL",
                "amount": "20",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "volume",
            },
            {
                "logical_fee_key": "delivery",
                "amount_status": "MISSING",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "gross_weight",
            },
        ],
    )

    assert result["missing_cell_count"] == 1
    assert result["rows"]["A"]["missing_fields"] == ["volume_m3"]
    assert result["rows"]["B"]["missing_fields"] == []
    assert all("project_collection" not in row["missing_fields"] for row in result["rows"].values())


def test_material_requirements_respect_fee_item_scope() -> None:
    result = analyze_material_requirements(
        [
            {"name": "ITEM-1", "stable_line_key": "A", "quantity": 1, "purchase_uom": "件", "goods_value": 10},
            {"name": "ITEM-2", "stable_line_key": "B", "quantity": 1, "purchase_uom": "件", "goods_value": ""},
        ],
        [
            {
                "logical_fee_key": "delivery",
                "amount_status": "ACTUAL",
                "amount": 20,
                "scope_type": "ITEMS",
                "scope_item_keys": ["B"],
                "allocation_basis": "gross_weight",
            }
        ],
    )

    assert result["rows"]["A"]["missing_fields"] == []
    assert result["rows"]["B"]["missing_fields"] == ["goods_value", "gross_weight_kg"]


def test_manual_zero_is_explicit_but_not_a_positive_goods_allocation_basis() -> None:
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    item = {"name": "ITEM-1", "stable_line_key": "A", "actual_shipped_qty": 1,
            "shipped_uom": "件", "unit": "件", "goods_value": 0}
    item["extra_json"] = json.dumps({"manual_shipment_valuation": build_manual_shipment_valuation(
        item, 0, actor="finance", reason="confirmed", confirmed_at="now")})

    without_fee = analyze_material_requirements([item], [])
    with_fee = analyze_material_requirements([item], [{
        "logical_fee_key": "freight", "amount_status": "ACTUAL", "amount": 20,
        "scope_type": "ALL_ITEMS", "allocation_basis": "goods_value",
    }])

    assert "shipment_value_rmb" not in without_fee["rows"]["A"]["missing_fields"]
    assert with_fee["rows"]["A"]["missing_fields"] == ["shipment_value_rmb"]
    assert with_fee["rows"]["A"]["field_reasons"]["shipment_value_rmb"][0]["code"] == "ALLOCATION_BASIS_REQUIRED"


def test_bare_legacy_zero_is_missing_but_structured_automatic_zero_is_explicit() -> None:
    base = {"quantity": 1, "purchase_uom": "件", "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
            "shipped_uom": "件", "goods_value": 0}
    bare = {**base, "name": "ITEM-BARE", "stable_line_key": "BARE", "extra_json": "{}"}
    automatic = {**base, "name": "ITEM-AUTO", "stable_line_key": "AUTO", "extra_json": json.dumps({
        "shipment_valuation": {"amount_rmb": "0", "currency": "RMB", "quantity": "1",
                               "uom": "件", "method": "SYSTEM_EXCEL", "status": "automatic", "error": ""},
    })}

    result = analyze_material_requirements([bare, automatic], [])

    assert result["rows"]["BARE"]["missing_fields"] == ["goods_value"]
    assert result["rows"]["BARE"]["field_reasons"]["goods_value"][0]["code"] == "GOODS_VALUE_MISSING"
    assert result["rows"]["AUTO"]["missing_fields"] == []


def _purchase_value_row(name: str, value: object = "100") -> dict:
    return {
        "name": name,
        "stable_line_key": name,
        "quantity": 1,
        "purchase_uom": "件",
        "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
        "shipped_uom": "件",
        "goods_value": value,
        "extra_json": "{}",
    }


def test_purchase_value_coverage_requires_every_active_row() -> None:
    result = purchase_value_coverage([
        _purchase_value_row("VALID", "100"),
        _purchase_value_row("MISSING", ""),
        {**_purchase_value_row("EXCLUDED", ""), "is_excluded": 1},
    ])

    assert result["complete"] is False
    assert result["item_count"] == 2
    assert result["missing_count"] == 1
    assert [row["stable_line_key"] for row in result["missing_items"]] == ["MISSING"]


@pytest.mark.parametrize("value", [None, "", "0", 0, "-1"])
def test_purchase_value_coverage_rejects_blank_plain_zero_and_negative(value) -> None:
    result = purchase_value_coverage([_purchase_value_row("INVALID", value)])

    assert result["complete"] is False
    assert result["missing_count"] == 1


def test_purchase_value_coverage_accepts_structured_confirmed_zero() -> None:
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    row = _purchase_value_row("FREE-SAMPLE", 0)
    row["extra_json"] = json.dumps({
        "manual_shipment_valuation": build_manual_shipment_valuation(
            row, 0, actor="buyer@example.com", reason="免费样品", confirmed_at="2026-09-21 09:00:00"
        )
    })

    assert purchase_value_coverage([row]) == {
        "complete": True,
        "item_count": 1,
        "missing_count": 0,
        "missing_items": [],
    }


def test_purchase_value_coverage_rejects_stale_source_and_expired_manual_confirmation() -> None:
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    stale_source = _purchase_value_row("STALE-SOURCE", 0)
    stale_source["extra_json"] = json.dumps({
        "shipment_valuation": {
            "amount_rmb": "10",
            "currency": "RMB",
            "quantity": "1",
            "uom": "件",
            "method": "SYSTEM_EXCEL",
            "status": "stale",
            "error": "SHIPMENT_VALUATION_STALE",
        }
    })
    expired_confirmation = _purchase_value_row("EXPIRED-MANUAL", 0)
    confirmed = build_manual_shipment_valuation(
        expired_confirmation, 0, actor="buyer@example.com", confirmed_at="2026-09-21 09:00:00"
    )
    expired_confirmation["quantity"] = 2
    expired_confirmation["extra_json"] = json.dumps({"manual_shipment_valuation": confirmed})

    result = purchase_value_coverage([stale_source, expired_confirmation])

    assert result["complete"] is False
    assert result["missing_count"] == 2


def test_purchase_value_coverage_rejects_an_empty_active_batch() -> None:
    result = purchase_value_coverage([])

    assert result == {
        "complete": False,
        "item_count": 0,
        "missing_count": 0,
        "missing_items": [],
    }
    with pytest.raises(ValueError, match="当前批次没有物料"):
        assert_complete_purchase_values([])


def test_purchase_value_assertion_reports_missing_row_count() -> None:
    with pytest.raises(
        ValueError,
        match="还有 2 行本次发货货值缺失或失效，请先补齐后再试算",
    ):
        assert_complete_purchase_values([
            _purchase_value_row("MISSING-1", ""),
            _purchase_value_row("MISSING-2", "-1"),
            _purchase_value_row("VALID", "100"),
        ])
