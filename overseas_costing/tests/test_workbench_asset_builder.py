"""中文用途：工作台 parts 可重复构建并同步源码/部署副本测试。"""

from pathlib import Path

from overseas_costing.scripts.build_workbench_assets import build_workbench_assets


def test_builder_uses_numeric_part_order_and_writes_identical_copies(tmp_path) -> None:
    package_root = tmp_path / "overseas_costing"
    parts = package_root / "page" / "overseas_cost_workbench" / "parts"
    parts.mkdir(parents=True)
    (parts / "10-last.js").write_text("window.order.push('ten');\n", encoding="utf-8")
    (parts / "02-first.js").write_text("window.order = ['two'];\n", encoding="utf-8")
    (parts / "10-layout.css").write_text(".ten { color: blue; }\n", encoding="utf-8")
    (parts / "02-base.css").write_text(".two { color: red; }\n", encoding="utf-8")
    (parts / "99-ignore.js.tmp").write_text("SECRET", encoding="utf-8")
    (package_root / ".superpowers").mkdir()
    (package_root / ".superpowers" / "ignore.js").write_text("SECRET", encoding="utf-8")

    first = build_workbench_assets(package_root)
    source_js = package_root / "page" / "overseas_cost_workbench" / "overseas_cost_workbench.js"
    deployed_js = package_root / "overseas_costing" / "page" / "overseas_cost_workbench" / "overseas_cost_workbench.js"
    source_css = source_js.with_suffix(".css")
    deployed_css = deployed_js.with_suffix(".css")

    assert source_js.read_text(encoding="utf-8") == "window.order = ['two'];\n\nwindow.order.push('ten');\n"
    assert source_css.read_text(encoding="utf-8") == ".two { color: red; }\n\n.ten { color: blue; }\n"
    assert deployed_js.read_bytes() == source_js.read_bytes()
    assert deployed_css.read_bytes() == source_css.read_bytes()
    assert "SECRET" not in source_js.read_text(encoding="utf-8")

    second = build_workbench_assets(package_root)
    assert second["digests"] == first["digests"]
    assert second["changed"] == []
