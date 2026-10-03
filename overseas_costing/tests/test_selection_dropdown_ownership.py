"""Keep shared selector assets and behavior tests out of Overseas ownership."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_overseas_does_not_register_selection_dropdown_asset():
    tree = ast.parse((ROOT / "overseas_costing/hooks.py").read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "app_include_js"
            for target in node.targets
        ):
            continue
        assets = ast.literal_eval(node.value)
        if isinstance(assets, str):
            assets = [assets]
        assert all(
            asset.split("?", 1)[0].rsplit("/", 1)[-1] != "selection_dropdown.bundle.js"
            for asset in assets
        )


@pytest.mark.parametrize("relative_path", [
    "overseas_costing/public/js/selection_dropdown.bundle.js",
    "overseas_costing/tests/frontend/selection_dropdown_harness.js",
    "overseas_costing/tests/test_selection_dropdown_frontend.py",
])
def test_overseas_legacy_selection_dropdown_files_are_absent(relative_path):
    assert not (ROOT / relative_path).exists()
