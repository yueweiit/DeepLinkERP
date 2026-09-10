import json
from pathlib import Path
from overseas_costing import install

ROOT = Path(__file__).resolve().parents[1]


def test_team_roles_have_equal_record_crud_and_schema_is_mirrored():
    relative = Path("doctype/overseas_air_sea_comparison/overseas_air_sea_comparison.json")
    doc = json.loads((ROOT / relative).read_text())
    assert (ROOT / relative).read_bytes() == (ROOT / "overseas_costing" / relative).read_bytes()
    assert doc["track_changes"] == 1
    for role in ("System Manager", "海外成本核算用户"):
        permission = next(row for row in doc["permissions"] if row["role"] == role)
        assert all(permission[key] == 1 for key in ("read", "create", "write", "delete"))


def test_sidebar_entries_have_comparison_immediately_after_workbench():
    items = install.cost_sidebar_items()
    assert [row["link_to"] for row in items[:2]] == ["overseas-cost-workbench", "air-sea-cost-comparison"]
    assert [row["idx"] for row in items] == list(range(1, len(items) + 1))
    assert install.cost_sidebar_items() == items


def test_workspace_shortcuts_include_comparison(monkeypatch):
    values = {}
    monkeypatch.setattr(install, "_set_if_field", lambda _doc, key, value: values.update({key: value}))
    monkeypatch.setattr(install, "_set_child_table", lambda _doc, key, value: values.update({key: value}))
    install._set_workspace_content(object())
    assert values["shortcuts"][1]["link_to"] == "air-sea-cost-comparison"
