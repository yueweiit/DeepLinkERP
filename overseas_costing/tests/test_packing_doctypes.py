"""中文用途：装箱确认快照与独立运费试算 DocType 契约测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _doctype(name: str) -> dict:
    path = ROOT / "doctype" / name / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _fields(meta: dict) -> dict[str, dict]:
    return {field["fieldname"]: field for field in meta["fields"]}


def test_packing_doctypes_are_present_in_frappe_module_tree() -> None:
    """生产 bench migrate 只扫描模块目录，不能只保留顶层兼容副本。"""

    for name in ("overseas_packing_snapshot", "overseas_freight_comparison"):
        source_directory = ROOT / "doctype" / name
        module_directory = ROOT / "overseas_costing" / "doctype" / name
        for filename in ("__init__.py", f"{name}.json", f"{name}.py"):
            assert (module_directory / filename).read_bytes() == (
                source_directory / filename
            ).read_bytes()


def test_packing_snapshot_metadata_is_traceable_and_immutable() -> None:
    meta = _doctype("overseas_packing_snapshot")
    fields = _fields(meta)
    expected = {
        "batch",
        "version",
        "idempotency_key",
        "source_kind",
        "source_id",
        "source_revision",
        "source_label",
        "source_locator_json",
        "source_read_at",
        "source_updated_at",
        "source_hash",
        "status",
        "is_current",
        "material_row_count",
        "package_count",
        "total_net_weight_kg",
        "net_total_kind",
        "total_gross_weight_kg",
        "total_volume_m3",
        "material_rows_json",
        "package_groups_json",
        "totals_json",
        "validation_json",
        "resolutions_json",
        "confirmed_by",
        "confirmed_at",
    }

    assert meta["autoname"] == "hash"
    assert meta["track_changes"] == 1
    assert expected <= fields.keys()
    assert fields["idempotency_key"]["unique"] == 1
    for fieldname in (
        "source_locator_json",
        "material_rows_json",
        "package_groups_json",
        "totals_json",
        "validation_json",
        "resolutions_json",
    ):
        assert fields[fieldname]["permlevel"] == 1
        assert fields[fieldname]["read_only"] == 1
    cost_permission = next(row for row in meta["permissions"] if row["role"] == "海外成本核算用户")
    assert cost_permission["read"] == 1
    assert cost_permission["create"] == 1
    assert not cost_permission.get("delete")


def test_freight_comparison_metadata_keeps_exact_inputs_and_results() -> None:
    meta = _doctype("overseas_freight_comparison")
    fields = _fields(meta)
    expected = {
        "batch",
        "packing_snapshot",
        "request_id",
        "snapshot_revision",
        "currency",
        "scope_confirmed",
        "gross_weight_kg",
        "volume_m3",
        "weight_unit_price",
        "weight_min_quantity",
        "weight_rounding_increment",
        "weight_min_base_freight",
        "weight_surcharge",
        "weight_total",
        "volume_unit_price",
        "volume_min_quantity",
        "volume_rounding_increment",
        "volume_min_base_freight",
        "volume_surcharge",
        "volume_total",
        "recommended_basis",
        "difference_amount",
        "savings_percent",
        "input_json",
        "calculation_json",
        "quote_remark",
    }

    assert meta["autoname"] == "hash"
    assert meta["track_changes"] == 1
    assert expected <= fields.keys()
    assert fields["request_id"]["unique"] == 1
    assert fields["input_json"]["permlevel"] == 1
    assert fields["calculation_json"]["permlevel"] == 1
    cost_permission = next(row for row in meta["permissions"] if row["role"] == "海外成本核算用户")
    assert cost_permission["read"] == 1
    assert cost_permission["create"] == 1
    assert not cost_permission.get("delete")


def test_controllers_reject_mutation_and_audit_actions_are_registered() -> None:
    snapshot_controller = (
        ROOT
        / "doctype"
        / "overseas_packing_snapshot"
        / "overseas_packing_snapshot.py"
    ).read_text(encoding="utf-8")
    comparison_controller = (
        ROOT
        / "doctype"
        / "overseas_freight_comparison"
        / "overseas_freight_comparison.py"
    ).read_text(encoding="utf-8")
    audit = _doctype("overseas_cost_audit_log")
    audit_options = _fields(audit)["action_type"]["options"].splitlines()

    assert "allow_packing_supersede" in snapshot_controller
    assert "不能修改已确认的装箱快照" in snapshot_controller
    assert "不能修改已保存的运费试算" in comparison_controller
    assert "PACKING_CONFIRM" in audit_options
    assert "FREIGHT_COMPARE" in audit_options
