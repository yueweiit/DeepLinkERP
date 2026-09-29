"""独立库存库位页面的真实合并和物料跳转测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "overseas_costing/page/inventory_location_detail"
JS = PAGE / "inventory_location_detail.js"


def run_js(body: str) -> dict:
    source = f"""
const page = require({json.dumps(str(JS))});
{body}
"""
    result = subprocess.run(["node", "-e", source], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_true_rowspan_renders_code_only_and_location_rows() -> None:
    result = run_js(
        """
const html = page.renderTableRows([{
  item_code:'FL002917', item_name:'PET片材 / PET SHEET', warehouse:'IML 仓库 - YWFM',
  total_qty:2560, stock_uom:'张：hoja', item_group:'FL 辅料', dpci:'',
  external_code:'EXT-2917', original_identifier_alias:'PET 2917',
  locations:[
    {original_location:'AI-11-A02', location_qty:1865},
    {original_location:'AI-12-T02', location_qty:695}
  ]
}]);
console.log(JSON.stringify({html}));
"""
    )

    html = result["html"]
    assert html.count('rowspan="2"') == 9
    assert 'data-item-code="FL002917"' in html
    assert ">FL002917</a>" in html
    assert "FL002917: PET" not in html
    assert "AI-11-A02" in html and "AI-12-T02" in html
    assert "2,560" in html


def test_single_location_omits_rowspan_and_escapes_untrusted_values() -> None:
    result = run_js(
        """
const html = page.renderTableRows([{
  item_code:'FL007979', item_name:'<script>alert(1)</script>', warehouse:'综合仓库 - YWFM',
  total_qty:19.6, stock_uom:'kg', item_group:'FL 辅料', dpci:'',
  external_code:'', original_identifier_alias:'FL000164',
  locations:[{original_location:'AI-4-C01', location_qty:19.6}]
}]);
console.log(JSON.stringify({html}));
"""
    )

    html = result["html"]
    assert "rowspan=" not in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert html.count("19.60") == 2


def test_page_assets_are_scoped_mirrored_and_link_to_standard_item_form() -> None:
    assert JS.exists(), "库存库位明细页面尚未实现"
    source = JS.read_text(encoding="utf-8")
    assert "make_app_page" in source
    assert 'frappe.set_route("Form", "Item"' in source
    assert 'fieldname: "snapshot_key"' in source
    assert 'fieldtype: "Select"' in source
    assert "snapshot_options" in source
    assert "renderTableRows" in source
    assert "rowspan" in source
    assert 'default: DEFAULT_COMPANY' in source
    assert 'children(":not(.page-form)")' in source
    assert "$(this.page.body).empty()" not in source

    css = (PAGE / "inventory_location_detail.css").read_text(encoding="utf-8")
    assert ".inventory-location-detail" in css
    assert "position: sticky" in css

    mirror = ROOT / "overseas_costing/overseas_costing/page/inventory_location_detail"
    for extension in ("js", "css", "json", "py"):
        assert (PAGE / f"inventory_location_detail.{extension}").read_bytes() == (
            mirror / f"inventory_location_detail.{extension}"
        ).read_bytes()

    definition = json.loads((PAGE / "inventory_location_detail.json").read_text())
    assert definition["title"] == "库存库位明细"
    assert {row["role"] for row in definition["roles"]} >= {
        "System Manager",
        "Stock Manager",
        "Stock User",
    }
