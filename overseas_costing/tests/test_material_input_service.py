"""物料数量、单位和稳定行标识的契约测试。"""

import json
from pathlib import Path

from overseas_costing.services.material_input_service import (
    GRID_FIELDS,
    analyze_material_requirements,
    build_shipping_quantity_updates,
    ensure_stable_line_key,
    normalize_grid_page,
    present_material_row,
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
    } <= fields.keys()
    assert fields["stable_line_key"]["read_only"] == 1
    assert fields["cost_output_uom"]["read_only"] == 1
    assert fields["net_weight_kg"]["fieldtype"] == "Float"
    assert "net_weight_kg" in GRID_FIELDS


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

    assert result["missing_cell_count"] == 0
    assert result["rows"]["A"]["missing_fields"] == []
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
