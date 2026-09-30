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
    assert 'default: defaultCompany' in source
    assert "resolveDefaultCompany(frappe)" in source
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
    assert definition["title"] == "物料库存明细"
    assert {row["role"] for row in definition["roles"]} >= {
        "System Manager",
        "Stock Manager",
        "Stock User",
    }


def test_material_page_is_renamed_without_changing_its_route_or_snapshot_contract() -> None:
    source = JS.read_text(encoding="utf-8")

    assert 'const PAGE_NAME = "inventory-location-detail"' in source
    assert 'title: "物料库存明细"' in source
    assert "库存库位明细" not in source
    assert "get_inventory_location_detail" in source
    assert "export_inventory_location_detail" in source


def test_inventory_pages_use_the_erp_default_company_without_a_hard_coded_fallback() -> None:
    material = run_js(
        """
const found = page.resolveDefaultCompany({defaults:{get_default:(key)=>key === 'company' ? 'Yuewei' : ''}});
const missing = page.resolveDefaultCompany({defaults:{get_default:()=>''}});
console.log(JSON.stringify({found, missing}));
"""
    )
    assert material == {"found": "Yuewei", "missing": ""}

    shared = ROOT / "overseas_costing/public/js/categorized_inventory_detail.js"
    script = (
        f"const page=require({json.dumps(str(shared))});"
        "const found=page.resolveDefaultCompany({defaults:{get_default:(key)=>key==='company'?'Yuewei':''}});"
        "const missing=page.resolveDefaultCompany({defaults:{get_default:()=>''}});"
        "console.log(JSON.stringify({found,missing}));"
    )
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"found": "Yuewei", "missing": ""}

    for source in (JS.read_text(encoding="utf-8"), shared.read_text(encoding="utf-8")):
        assert '"YW Fabricación MX 核心制造"' not in source


def test_three_category_pages_are_thin_wrappers_over_one_shared_component() -> None:
    definitions = {
        "semi_finished": ("semi_finished_inventory_detail", "半成品库存明细"),
        "finished_goods": ("finished_goods_inventory_detail", "成品库存明细"),
        "mold": ("mold_inventory_detail", "模具库存明细"),
    }
    for category, (folder, title) in definitions.items():
        page = ROOT / "overseas_costing/page" / folder
        script = (page / f"{folder}.js").read_text(encoding="utf-8")
        definition = json.loads((page / f"{folder}.json").read_text(encoding="utf-8"))
        assert title == definition["title"]
        assert f'category: "{category}"' in script
        assert "CategorizedInventoryDetail.bootstrap" in script
        assert "renderTableRows" not in script

        mirror = ROOT / "overseas_costing/overseas_costing/page" / folder
        for extension in ("js", "json", "py"):
            assert (page / f"{folder}.{extension}").read_bytes() == (
                mirror / f"{folder}.{extension}"
            ).read_bytes()


def test_shared_category_asset_renders_status_location_and_pagination_controls() -> None:
    shared = ROOT / "overseas_costing/public/js/categorized_inventory_detail.js"
    mirror = ROOT / "overseas_costing/overseas_costing/public/js/categorized_inventory_detail.js"
    assert shared.read_bytes() == mirror.read_bytes()
    source = shared.read_text(encoding="utf-8")
    assert "get_categorized_inventory_detail" in source
    assert "export_categorized_inventory_detail" in source
    assert 'fieldname: "only_with_stock"' in source
    assert "100, 500, 2500" in source
    assert "库位待维护" in source
    assert "库存差异" in source
    assert 'frappe.set_route("Form", "Item"' in source
    assert "set_value(current)" not in source

    result = subprocess.run(
        [
            "node",
            "-e",
            f"const page=require({json.dumps(str(shared))});"
            "const html=page.renderTableRows([{item_code:'N1',item_name:'<b>x</b>',warehouse:'',actual_qty:0,"
            "stock_uom:'个：pieza',item_group:'半成品',dpci:'',external_code:'',original_identifier_alias:'',"
            "snapshot_qty:null,difference_qty:null,inventory_status:'库位待维护',"
            "locations:[{reference_location:'库位待维护',snapshot_location_qty:null,snapshot_date:''}]}]);"
            "console.log(JSON.stringify({html}));",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    html = json.loads(result.stdout)["html"]
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "库位待维护" in html
    assert ">—<" in html


def test_shared_category_rows_match_header_column_order() -> None:
    shared = ROOT / "overseas_costing/public/js/categorized_inventory_detail.js"
    script = (
        f"const page=require({json.dumps(str(shared))});"
        "const html=page.renderTableRows([{item_code:'N1',item_name:'半成品',warehouse:'W1',actual_qty:12,"
        "stock_uom:'个：pieza',item_group:'半成品',dpci:'DPCI-MARK',external_code:'EXT-MARK',"
        "original_identifier_alias:'ALIAS-MARK',snapshot_qty:10,difference_qty:2,inventory_status:'库存差异',"
        "locations:[{reference_location:'LOC-MARK',snapshot_location_qty:10,snapshot_date:'DATE-MARK'}]}]);"
        "console.log(JSON.stringify({html}));"
    )
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    html = json.loads(result.stdout)["html"]

    assert html.index("LOC-MARK") < html.index("库存差异")
    assert html.index("库存差异") < html.index("DATE-MARK")
    assert html.index("DATE-MARK") < html.index("个：pieza")
    assert html.index("个：pieza") < html.index("DPCI-MARK") < html.index("EXT-MARK")
