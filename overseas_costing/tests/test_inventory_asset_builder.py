"""库存页面源码与 Frappe 部署副本同步测试。"""

from pathlib import Path

from overseas_costing.scripts.build_inventory_assets import build_inventory_assets


def test_inventory_asset_builder_copies_pages_and_shared_assets_repeatably(tmp_path: Path) -> None:
    package_root = tmp_path / "overseas_costing"
    material = package_root / "page/inventory_location_detail"
    category = package_root / "page/semi_finished_inventory_detail"
    public_js = package_root / "public/js"
    public_css = package_root / "public/css"
    for directory in (material, category, public_js, public_css):
        directory.mkdir(parents=True)

    (material / "inventory_location_detail.js").write_text("material", encoding="utf-8")
    (category / "semi_finished_inventory_detail.js").write_text("category", encoding="utf-8")
    (public_js / "categorized_inventory_detail.js").write_text("shared", encoding="utf-8")
    (public_css / "categorized_inventory_detail.css").write_text("style", encoding="utf-8")

    first = build_inventory_assets(package_root)
    deployed = package_root / "overseas_costing"
    assert (deployed / "page/inventory_location_detail/inventory_location_detail.js").read_text() == "material"
    assert (deployed / "page/semi_finished_inventory_detail/semi_finished_inventory_detail.js").read_text() == "category"
    assert (deployed / "public/js/categorized_inventory_detail.js").read_text() == "shared"
    assert (deployed / "public/css/categorized_inventory_detail.css").read_text() == "style"
    assert first["changed"]

    assert build_inventory_assets(package_root)["changed"] == []
