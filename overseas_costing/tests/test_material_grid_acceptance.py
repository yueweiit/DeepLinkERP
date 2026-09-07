"""物料补充流程的本地验收样本：不连接真实 OA、钉钉或 ERP。"""

from overseas_costing.scripts.seed_workbench_sample import build_material_grid_acceptance_sample
from overseas_costing.services.calculate_service import calculate_item_rows
from overseas_costing.services.material_import_service import build_material_import_preview
from overseas_costing.services.material_input_service import (
    build_material_requirements,
    resolve_effective_quantity,
)


def _sample() -> dict:
    return build_material_grid_acceptance_sample()


def _row(tag: str) -> dict:
    return next(row for row in _sample()["items"] if row["acceptance_tag"] == tag)


def test_sample_is_oa_only_and_has_no_live_integration_locator() -> None:
    sample = _sample()

    assert sample["batch"]["source_type"] == "oa_logistics"
    assert sample["packing_source"] is None
    assert "file_url" not in str(sample)
    assert "http://" not in str(sample)
    assert "https://" not in str(sample)


def test_sample_covers_default_and_explicit_shipping_quantities() -> None:
    default = resolve_effective_quantity(_row("default_purchase_qty"))
    explicit = resolve_effective_quantity(_row("explicit_lower_qty"))

    assert default == {
        "quantity": "34",
        "uom": "桶",
        "mode": "DEFAULT_PURCHASE",
        "is_default": True,
        "blocking": [],
    }
    assert explicit["quantity"] == "30"
    assert explicit["mode"] == "MANUAL_CONFIRMED"


def test_sample_calculates_kg_purchase_as_cost_per_barrel() -> None:
    row = _row("kg_price_barrel_shipping")
    calculated, summary = calculate_item_rows([row], [])

    assert calculated[0]["goods_value"] == 15300
    assert calculated[0]["total_unit_rmb"] == 450
    assert calculated[0]["cost_output_uom"] == "桶"
    assert summary["blocking"] == []


def test_sample_duplicate_sku_requires_stable_line_choice() -> None:
    duplicates = [row for row in _sample()["items"] if row["material_code"] == "FL000103"]
    preview = build_material_import_preview(
        duplicates,
        [{"source_row": 9, "material_code": "FL000103", "actual_shipped_qty": 15}],
        {"kind": "manual_xlsx", "revision": "LOCAL-ONLY"},
    )

    assert len({row["stable_line_key"] for row in duplicates}) == 2
    assert preview["rows"][0]["match_status"] == "choice_required"
    assert len(preview["rows"][0]["candidates"]) == 2


def test_goods_value_allocation_does_not_require_weight_but_project_blocks_erp() -> None:
    row = _row("missing_weight_and_project")
    state = build_material_requirements([row], _sample()["rules"])
    requirements = state["by_item"][row["stable_line_key"]]

    assert requirements["gross_weight_kg"]["severity"] == "optional"
    assert requirements["project_collection"]["gate"] == "erp_push"
    assert state["summary"]["blocking_for_calculation"] == 0
    assert state["summary"]["blocking_for_erp"] == 1


def test_shared_box_sample_counts_one_package_for_two_material_rows() -> None:
    group = _sample()["packing_preview"]["groups"][0]

    assert group["row_numbers"] == [5, 6]
    assert group["gross_weight_kg"] == {"value": "612", "count_once": True}
    assert _sample()["packing_preview"]["totals"]["gross_weight_kg"] == "612"
