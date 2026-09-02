from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PAGE_DIRS = (
    ROOT / "overseas_costing/page/overseas_cost_workbench",
    ROOT / "overseas_costing/overseas_costing/page/overseas_cost_workbench",
)


def method_source(js: str, start: str, end: str) -> str:
    return js.split(start, 1)[1].split(end, 1)[0]


@pytest.fixture(params=PAGE_DIRS, ids=("compat", "module"))
def workbench_source(request):
    page_dir = request.param
    return {
        "js": (page_dir / "overseas_cost_workbench.js").read_text(encoding="utf-8"),
        "css": (page_dir / "overseas_cost_workbench.css").read_text(encoding="utf-8"),
    }


def test_detail_and_expand_have_explicit_single_click_contracts(workbench_source):
    js = workbench_source["js"]
    assert 'data-action="open-batch-drawer"' in js
    assert 'data-action="toggle-batch"' in js
    assert '.on("dblclick", ".ocw-parent-row"' not in js
    assert "双击批次查看详情" not in js
    assert "双击查看批次详情" not in js


def test_compact_filters_transport_tabs_and_role_views_exist(workbench_source):
    js = workbench_source["js"]
    assert 'data-area="transport-workbench"' in js
    assert 'data-action="toggle-advanced-filters"' in js
    assert 'data-action="set-role-view"' in js
    assert "采购视图" in js
    assert "财务视图" in js


def test_sku_mouse_navigation_and_frozen_columns_exist(workbench_source):
    js = workbench_source["js"]
    css = workbench_source["css"]
    assert 'data-role="child-table-range"' in js
    assert 'data-action="scroll-child-table"' in js
    assert 'data-action="jump-child-columns"' in js
    assert ".ocw-child-table-navigator" in css
    assert ".ocw-col-code { width: 160px; }" in css
    assert ".ocw-col-product { width: 260px; }" in css
    assert ".ocw-sticky-1" in css and "left: 160px" in css
    assert "-webkit-line-clamp: 2" in css


def test_sku_group_jumps_use_excel_codes_not_guessed_indexes(workbench_source):
    js = workbench_source["js"]
    for column_code in ("A", "I", "Q", "AA", "AK"):
        assert f'data-column-code="{column_code}"' in js
    assert "jumpChildColumns(batchName, columnCode)" in js


def test_list_load_and_normal_filters_do_not_prefetch_or_expand_skus(workbench_source):
    js = workbench_source["js"]
    load_batches = method_source(js, "  async loadBatches() {", "  async prefetchBatchItems(")
    apply_filters = method_source(js, "  async applyFilters() {", "  clearFilters() {")
    transport_filter = method_source(js, "  async setTransportFilter(", "  syncActiveSelectionWithVisible() {")
    restore_focus = method_source(js, "  restoreBatchFocusStateFromUrl() {", "  async applyBatchFocusFromUrl() {")
    assert "prefetchBatchItems" not in load_batches
    assert "expandedBatchNames" not in apply_filters
    assert "prefetchBatchItems" not in transport_filter
    assert "expandedBatchNames" not in restore_focus


def test_role_views_are_capability_gated_and_user_scoped(workbench_source):
    js = workbench_source["js"]
    assert "availableRoleViews()" in js
    assert 'const user = (frappe.session && frappe.session.user) || "guest"' in js
    assert "`ocw-role-view:${user}`" in js
    assert "renderParentActions(batch)" in js


def test_drawer_error_has_local_retry(workbench_source):
    js = workbench_source["js"]
    assert 'data-action="retry-batch-drawer"' in js
    assert "this.openBatchDrawer(this.drawerBatchName, { updateUrl: false })" in js
