"""物料数量、单位和稳定行标识的契约测试。"""

import json
from pathlib import Path

from overseas_costing.services.material_input_service import (
    build_shipping_quantity_updates,
    build_material_requirements,
    ensure_stable_line_key,
    resolve_effective_quantity,
    resolve_goods_value,
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


def test_goods_value_requires_matching_purchase_and_price_units() -> None:
    unresolved = resolve_goods_value(
        {"quantity": 34, "purchase_uom": "桶", "unit_price": 25, "unit_price_uom": "kg"}
    )
    resolved = resolve_goods_value(
        {"quantity": 612, "purchase_uom": "kg", "unit_price": 25, "unit_price_uom": "kg"}
    )

    assert unresolved["amount"] == 0
    assert unresolved["blocking"][0]["code"] == "GOODS_VALUE_OR_UOM_CONVERSION_REQUIRED"
    assert resolved["amount"] == 15300
    assert resolved["source"] == "PRICE_X_PURCHASE_QTY"


def test_required_cells_follow_active_fee_basis() -> None:
    result = build_material_requirements(
        [
            {
                "name": "I1",
                "quantity": 10,
                "purchase_uom": "件",
                "shipped_uom": "件",
                "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
                "goods_value": 100,
                "gross_weight_kg": "",
                "volume_m3": "",
                "project_collection": "生产项目",
            }
        ],
        [
            {
                "name": "F1",
                "is_enabled": 1,
                "allocation_basis": "gross_weight",
                "scope_item_names": ["I1"],
            }
        ],
    )

    assert result["by_item"]["I1"]["gross_weight_kg"]["severity"] == "blocking"
    assert result["by_item"]["I1"]["gross_weight_kg"]["gate"] == "calculation"
    assert result["by_item"]["I1"]["volume_m3"]["severity"] == "optional"


def test_missing_project_warns_for_push_but_not_cost_preview() -> None:
    result = build_material_requirements(
        [
            {
                "name": "I1",
                "quantity": 2,
                "purchase_uom": "件",
                "shipped_uom": "件",
                "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
                "goods_value": 16,
                "project_collection": "",
            }
        ],
        [],
    )

    project = result["by_item"]["I1"]["project_collection"]
    assert project["severity"] == "blocking"
    assert project["gate"] == "erp_push"
    assert result["summary"]["blocking_for_calculation"] == 0
    assert result["summary"]["blocking_for_erp"] == 1


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
        "erp_stock_uom",
        "shipped_to_erp_factor",
    } <= fields.keys()
    assert fields["stable_line_key"]["read_only"] == 1
    assert fields["cost_output_uom"]["read_only"] == 1
