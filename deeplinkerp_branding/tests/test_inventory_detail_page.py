"""Unified inventory detail client rendering and safety tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHARED_JS = ROOT / "deeplinkerp_branding/public/js/inventory_detail.bundle.js"
SHARED_CSS = ROOT / "deeplinkerp_branding/public/css/inventory_detail.bundle.css"
MODULE_ROOT = ROOT / "deeplinkerp_branding/deeplinkerp_branding"


def run_js(body: str) -> dict:
	source = f"const inventory=require({json.dumps(str(SHARED_JS))});\n{body}"
	result = subprocess.run(["node", "-e", source], text=True, capture_output=True)
	assert result.returncode == 0, result.stderr
	return json.loads(result.stdout)


def test_material_rows_use_one_selectable_checkbox_per_item_warehouse_group() -> None:
	result = run_js(
		"""
const html=inventory.renderMaterialRows([{
 item_code:'A',item_name:'物料A',warehouse:'W1',total_qty:5,stock_uom:'个：pieza',
 item_group:'物料',locations:[{original_location:'L1',location_qty:2},{original_location:'L2',location_qty:3}]
}]);
console.log(JSON.stringify({html}));
"""
	)
	html = result["html"]
	assert html.count('type="checkbox"') == 1
	assert html.count('rowspan="2"') == 10
	assert "data-selection-key" in html


def test_placeholder_without_a_warehouse_cannot_be_selected() -> None:
	result = run_js(
		"""
const html=inventory.renderCategorizedRows([{
 item_code:'A',item_name:'半成品A',warehouse:'',actual_qty:0,stock_uom:'个：pieza',item_group:'半成品',
 inventory_status:'库位待维护',locations:[{reference_location:'库位待维护',snapshot_location_qty:null,snapshot_date:''}]
}]);
console.log(JSON.stringify({html}));
"""
	)
	assert 'type="checkbox"' in result["html"]
	assert "disabled" in result["html"]


def test_current_page_select_all_ignores_placeholder_rows_and_can_clear_again() -> None:
	result = run_js(
		"""
const groups=[
 {item_code:'A',warehouse:'W1'},
 {item_code:'B',warehouse:'W2'},
 {item_code:'C',warehouse:''}
];
const selected=inventory.updateCurrentPageSelection(groups,new Map(),true);
const cleared=inventory.updateCurrentPageSelection(groups,selected,false);
console.log(JSON.stringify({
 selected:[...selected.values()],
 cleared:cleared.size
}));
"""
	)
	assert result == {
		"selected": [
			{"item_code": "A", "source_warehouse": "W1"},
			{"item_code": "B", "source_warehouse": "W2"},
		],
		"cleared": 0,
	}


def test_shared_page_uses_integer_page_size_and_only_opens_an_unsaved_stock_entry() -> None:
	source = SHARED_JS.read_text(encoding="utf-8")
	assert 'fieldname: "page_length"' in source
	assert 'fieldtype: "Int"' in source
	assert "DEFAULT_PAGE_LENGTH = 200" in source
	assert "MIN_PAGE_LENGTH = 1" in source
	assert "MAX_PAGE_LENGTH = 2500" in source
	assert "get_inventory_movement_context" in source
	assert "prepare_inventory_stock_entry" in source
	assert 'frappe.set_route("Form", "Stock Entry"' in source
	assert "overseas_costing.services.inventory_location_service" not in source
	assert "this.resetSelection();" in source
	assert "物料移动 (${this.selected.size})" in source
	assert "this.movementActionDataLabel" not in source
	assert ".menu-item-label" not in source
	assert 'aria-disabled' in source
	for forbidden in (".insert(", ".save(", ".submit(", "frappe.client.insert"):
		assert forbidden not in source


def test_reset_selection_clears_visible_row_and_header_checkboxes() -> None:
	source = SHARED_JS.read_text(encoding="utf-8")
	reset_selection = source.split("resetSelection() {", 1)[1].split(
		"updateSelectionUi() {", 1
	)[0]

	assert '"[data-selection-key], [data-select-current-page]"' in reset_selection
	assert '$selectionInputs.prop("checked", false);' in reset_selection
	assert '$selectionInputs.prop("indeterminate", false);' in reset_selection


def test_all_four_routes_are_thin_wrappers_over_the_shared_component() -> None:
	pages = {
		"inventory_location_detail": "material",
		"semi_finished_inventory_detail": "semi_finished",
		"finished_goods_inventory_detail": "finished_goods",
		"mold_inventory_detail": "mold",
	}
	for folder, category in pages.items():
		page = MODULE_ROOT / "page" / folder
		script = (page / f"{folder}.js").read_text(encoding="utf-8")
		definition = json.loads((page / f"{folder}.json").read_text(encoding="utf-8"))
		assert "InventoryDetail.bootstrap" in script
		assert f'category: "{category}"' in script
		assert "renderMaterialRows" not in script
		assert definition["module"] == "Deeplinkerp Branding"


def test_shared_assets_are_registered_once_in_branding_hooks() -> None:
	hooks = (ROOT / "deeplinkerp_branding/hooks.py").read_text(encoding="utf-8")
	assert "inventory_detail.bundle.js" in hooks
	assert "inventory_detail.bundle.css" in hooks
	assert SHARED_CSS.is_file()


@pytest.mark.parametrize("category", ["material", "semi_finished", "finished_goods", "mold"])
def test_movement_action_is_in_page_content_not_responsive_toolbar(category: str) -> None:
	result = run_js(
		f"""
let html='';
const button={{length:1,text(){{return this}},prop(){{return this}},attr(){{return this}}}};
const root={{find(){{return button}}}};
global.$=(value)=>typeof value==='string' ? (html=value,root) :
 {{children:()=>({{remove(){{}}}}),append(){{}}}};
const page=Object.assign(Object.create(inventory.InventoryDetailPage.prototype),{{
 config:{{title:'库存明细'}},isMaterial:{json.dumps(category == 'material')},
 page:{{body:{{}}}},selected:new Map(),canCreateStockEntry:false
}});
page.renderShell();
console.log(JSON.stringify({{html}}));
"""
	)
	assert 'data-inventory-action="movement"' in result["html"]
	assert 'class="id-actions"' in result["html"]
	source = SHARED_JS.read_text(encoding="utf-8")
	assert 'add_inner_button("物料移动' not in source
	assert "'[data-inventory-action=\"movement\"]'" in source


@pytest.mark.parametrize("count,can_create", [(0, True), (1, True), (200, True), (2, False)])
def test_content_movement_action_preserves_count_and_creation_permission(count: int, can_create: bool) -> None:
	result = run_js(
		f"""
const state={{}};
const button={{length:1,text(v){{state.label=v;return this}},
 prop(k,v){{state[k]=v;return this}},attr(k,v){{state[k]=v;return this}}}};
inventory.InventoryDetailPage.prototype.updateMovementButton.call({{
 $movementButton:button,selected:new Map(Array.from({{length:{count}}},(_,i)=>[i,{{}}])),
 canCreateStockEntry:{json.dumps(can_create)},movementDisabledReason:'权限说明'
}});
console.log(JSON.stringify(state));
"""
	)
	assert result == {
		"label": f"物料移动 ({count})",
		"disabled": not can_create or count == 0,
		"aria-disabled": "true" if not can_create or count == 0 else "false",
		"title": "权限说明",
	}
