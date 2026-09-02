# Overseas Cost Workbench Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce workbench density, replace the hidden double-click detail gesture with an explicit single-click link, and make the A–BE SKU table reliably navigable with a mouse.

**Architecture:** Keep the existing Frappe Page and API contracts. Refactor only the page shell, parent-table rendering, delegated UI events, and synchronized SKU scrolling inside the two existing workbench source copies; add source-contract tests so both copies retain the same interaction behavior while preserving their deliberate Frappe chrome difference.

**Tech Stack:** Frappe Page, jQuery delegated events, ES6 JavaScript, CSS sticky positioning, pytest source-contract tests, Node syntax validation.

---

## File map

- Create `overseas_costing/tests/test_workbench_ui_source.py`: fast source-contract tests for both workbench copies.
- Modify `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`: deployed module page structure, state, events, role views, row rendering, and SKU navigation.
- Modify `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`: deployed module page density, horizontal transport tabs, two-line frozen columns, and visible mouse navigation.
- Modify `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`: keep the compatibility copy behaviorally synchronized while preserving its Desk chrome handling.
- Modify `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`: keep the compatibility copy visually synchronized.

### Task 1: Add workbench UI source contracts

**Files:**
- Create: `overseas_costing/tests/test_workbench_ui_source.py`

- [ ] **Step 1: Write the failing source-contract tests**

```python
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PAGE_DIRS = (
    ROOT / "overseas_costing/page/overseas_cost_workbench",
    ROOT / "overseas_costing/overseas_costing/page/overseas_cost_workbench",
)


@pytest.fixture(params=PAGE_DIRS, ids=("compat", "module"))
def workbench_source(request):
    page_dir = request.param
    return {
        "js": (page_dir / "overseas_cost_workbench.js").read_text(encoding="utf-8"),
        "css": (page_dir / "overseas_cost_workbench.css").read_text(encoding="utf-8"),
    }


def test_detail_and_expand_have_explicit_single_click_contracts(workbench_source):
    js = workbench_source["js"]
    assert "data-action=\"open-batch-drawer\"" in js
    assert "data-action=\"toggle-batch\"" in js
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
```

- [ ] **Step 2: Run the tests and verify the old UI fails the contracts**

Run: `pytest -q overseas_costing/tests/test_workbench_ui_source.py`

Expected: failures for the missing explicit drawer link, remaining double-click binding, missing role/filter controls, old `148px/300px` widths, and missing custom navigator.

- [ ] **Step 3: Commit the failing contracts**

```bash
git add overseas_costing/tests/test_workbench_ui_source.py
git commit -m "test: define workbench interaction contracts"
```

### Task 2: Replace the dense shell with compact filters and horizontal transport tabs

**Files:**
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js:165-290`
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js:163-291`
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`

- [ ] **Step 1: Add the compact shell state and markup**

In each constructor, initialize the view state before rendering:

```javascript
this.advancedFiltersOpen = false;
this.roleView = this.loadRoleViewPreference();
```

Replace the sidebar shell with one full-width main area. Render the transport controls above the query toolbar:

```html
<div class="ocw-transport-tabs" data-area="transport-workbench" aria-label="按运输方式筛选"></div>
```

Keep `customs_no`, `waybill_no`, and `material_code` in `.ocw-filter-grid.ocw-filter-grid-primary`. Move `product_name`, `import_name`, `hs_code`, and `category` into:

```html
<div class="ocw-filter-grid ocw-filter-grid-advanced" data-area="advanced-filters" hidden>...</div>
```

Add the explicit toggle beside Query/Reset:

```html
<button class="ocw-text-btn" type="button" data-action="toggle-advanced-filters" aria-expanded="false">高级筛选</button>
```

Keep “添加报关运单” visible and place the remaining header actions inside a `<details class="ocw-head-more">` block headed “更多操作”.

- [ ] **Step 2: Render transport modes as horizontal tabs**

Change `renderTransportWorkbench()` so it owns the “全部” item and renders one compact button per mode:

```javascript
const options = [
  { value: "", label: "全部", count: totalCount },
  ...modes.map((mode) => ({
    ...mode,
    count: (stats[mode.value] || {}).batchCount || 0,
  })),
];
const html = options.map((mode) => `
  <button class="ocw-transport-tab ${activeMode === mode.value ? "active" : ""}"
    type="button" data-action="set-transport-filter" data-transport-mode="${this.escape(mode.value)}">
    <span>${this.escape(mode.label)}</span><b>${this.escape(String(mode.count))}</b>
  </button>
`).join("");
this.$root.find("[data-area='transport-workbench']").html(html);
```

- [ ] **Step 3: Bind and render advanced-filter state**

Add the delegated event:

```javascript
this.$root.on("click", "[data-action='toggle-advanced-filters']", () => this.toggleAdvancedFilters());
```

Add the method:

```javascript
toggleAdvancedFilters() {
  this.advancedFiltersOpen = !this.advancedFiltersOpen;
  const $panel = this.$root.find("[data-area='advanced-filters']");
  const $button = this.$root.find("[data-action='toggle-advanced-filters']");
  $panel.prop("hidden", !this.advancedFiltersOpen);
  $button.attr("aria-expanded", String(this.advancedFiltersOpen));
  $button.text(this.advancedFiltersOpen ? "收起筛选" : "高级筛选");
}
```

- [ ] **Step 4: Add compact shell and transport CSS**

Use a single-column shell and horizontally scrollable tabs:

```css
.ocw-shell { display: block; }
.ocw-main { min-width: 0; width: 100%; }
.ocw-transport-tabs { display: flex; gap: 8px; overflow-x: auto; padding: 8px 0; }
.ocw-transport-tab { min-height: 34px; padding: 6px 12px; border: 1px solid #b8cecc; border-radius: 999px; background: #fff; color: #47605f; }
.ocw-transport-tab.active { border-color: #0d777a; background: #e2f3f1; color: #075f62; }
.ocw-filter-grid-primary { grid-template-columns: repeat(3, minmax(180px, 1fr)) auto; }
.ocw-filter-grid-advanced { margin-top: 10px; grid-template-columns: repeat(4, minmax(180px, 1fr)); }
.ocw-head-more { position: relative; }
.ocw-head-more-menu { position: absolute; right: 0; z-index: 20; display: grid; gap: 6px; min-width: 180px; padding: 8px; background: #fff; border: 1px solid #c8d8d6; border-radius: 8px; box-shadow: 0 10px 24px rgba(22, 57, 58, .16); }
```

- [ ] **Step 5: Run syntax and source tests**

Run:

```bash
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
pytest -q overseas_costing/tests/test_workbench_ui_source.py -k compact
```

Expected: both Node commands exit 0; compact-shell contract passes while the other contract groups may still fail.

- [ ] **Step 6: Commit the compact shell**

```bash
git add overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css} overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css}
git commit -m "feat: simplify workbench filters and transport navigation"
```

### Task 3: Make detail and SKU expansion explicit and add role views

**Files:**
- Modify: both `overseas_cost_workbench.js` copies in `bindEvents()`, `renderTable()`, `renderParentRow()`, and the constructor.
- Modify: both `overseas_cost_workbench.css` copies for link, selected-row, and role-view styling.

- [ ] **Step 1: Replace the row timer and double-click handlers**

Remove `batchClickTimer`, the delayed `focusBatch()` row handler, and the delegated `dblclick` handler. Add:

```javascript
this.$root.on("click", "[data-action='open-batch-drawer']", (event) => {
  event.preventDefault();
  this.openBatchDrawer($(event.currentTarget).attr("data-batch-name"));
});
this.$root.on("click", ".ocw-parent-row", (event) => {
  if ($(event.target).closest("button, input, select, textarea, a").length) return;
  this.selectBatch($(event.currentTarget).attr("data-batch-name")).catch((error) => this.showError(error));
});
```

Render the source number as an obvious link and leave the toggle as the only SKU expansion control:

```html
<button class="ocw-source-link" type="button" data-action="open-batch-drawer" data-batch-name="..." aria-label="查看批次详情：...">...</button>
```

Set the tree toggle `title` and `aria-label` to “展开 SKU 明细” or “收起 SKU 明细”. Remove “全部展开/全部收起” from the toolbar and change the drawer placeholder title to “选择单号查看批次详情”.

- [ ] **Step 2: Add role preference helpers and event**

```javascript
loadRoleViewPreference() {
  const saved = window.localStorage.getItem("ocw-role-view");
  if (saved === "purchase" || saved === "finance") return saved;
  const roles = (frappe.user_roles || []).join(" ");
  return roles.includes("财务") ? "finance" : "purchase";
}

setRoleView(view = "purchase") {
  this.roleView = view === "finance" ? "finance" : "purchase";
  window.localStorage.setItem("ocw-role-view", this.roleView);
  this.renderTable();
}
```

Bind `[data-action='set-role-view']` and render “采购视图 / 财务视图” beside the existing “成本列表 / ERP 队列” control.

- [ ] **Step 3: Drive the parent table from role column descriptors**

Add `parentColumns()` returning common columns plus view-specific columns:

```javascript
parentColumns() {
  const common = [
    { key: "toggle", label: "", className: "ocw-col-toggle" },
    { key: "source", label: this.parentTableLabels().sourceNo, className: "ocw-col-customs" },
    { key: "logistics", label: this.parentTableLabels().logisticsNo, className: "ocw-col-waybill" },
    { key: "count", label: "SKU数", className: "ocw-col-count" },
  ];
  const purchase = [
    { key: "documents", label: "资料状态", className: "ocw-col-state" },
    { key: "goods", label: "采购货值", className: "ocw-col-value" },
    { key: "fees", label: "已识别费用", className: "ocw-col-money" },
    { key: "total", label: "综合成本", className: "ocw-col-value" },
  ];
  const finance = [
    { key: "goods", label: "采购货值", className: "ocw-col-value" },
    { key: "fees", label: "已识别费用", className: "ocw-col-money" },
    { key: "total", label: "综合成本", className: "ocw-col-value" },
    { key: "voucher", label: "凭证差异", className: "ocw-col-voucher" },
    { key: "erp", label: "ERP 状态", className: "ocw-col-state" },
  ];
  return [...common, ...(this.roleView === "finance" ? finance : purchase), { key: "actions", label: "操作", className: "ocw-col-action" }];
}
```

Render `<colgroup>`, `<th>`, parent cells, and child `colspan` from the descriptor count. Use the existing metric builders and map `erp` through `erpWritebackStatusInfo()` without changing backend state.

- [ ] **Step 4: Add interaction styling**

```css
.ocw-source-link { border: 0; padding: 0; background: transparent; color: #075f62; font: inherit; font-weight: 750; text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
.ocw-parent-row.is-selected > td { background: #edf8f7; }
.ocw-role-switch { display: inline-flex; padding: 3px; border: 1px solid #c4d6d4; border-radius: 8px; background: #f6f9f9; }
.ocw-tree-toggle { min-width: 30px; min-height: 30px; }
```

- [ ] **Step 5: Run interaction contracts and syntax checks**

Run:

```bash
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
pytest -q overseas_costing/tests/test_workbench_ui_source.py -k "detail or role"
```

Expected: all selected tests pass and both Node commands exit 0.

- [ ] **Step 6: Commit explicit row interactions and role views**

```bash
git add overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css} overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css}
git commit -m "feat: clarify batch detail and role views"
```

### Task 4: Add a persistent mouse-first SKU horizontal navigator

**Files:**
- Modify: both `overseas_cost_workbench.js` copies in `bindEvents()`, `renderChildRow()`, `renderChildTable()`, and `bindHierarchyScrollbars()`.
- Modify: both `overseas_cost_workbench.css` copies around `.ocw-child-table-*`, `.ocw-col-code`, `.ocw-col-product`, and sticky cells.

- [ ] **Step 1: Render group jump controls and the persistent navigator**

Add column indices to SKU headers and replace the old bare x-scroll element with:

```html
<div class="ocw-sku-column-groups" aria-label="SKU 字段分组">
  <button data-action="jump-child-columns" data-column-start="0" data-batch-name="...">基础信息 A–H</button>
  <button data-action="jump-child-columns" data-column-start="8" data-batch-name="...">采购数据 I–P</button>
  <button data-action="jump-child-columns" data-column-start="16" data-batch-name="...">物流费用 Q–Z</button>
  <button data-action="jump-child-columns" data-column-start="26" data-batch-name="...">税费 AA–AJ</button>
  <button data-action="jump-child-columns" data-column-start="36" data-batch-name="...">综合成本 AK–BE</button>
</div>
<div class="ocw-child-table-navigator" data-role="child-table-navigator" data-batch-name="...">
  <button type="button" data-action="scroll-child-table" data-direction="-1" data-batch-name="..." aria-label="SKU 字段向左移动一屏">◀</button>
  <input type="range" min="0" max="1000" value="0" data-role="child-table-range" data-batch-name="..." aria-label="拖动浏览 SKU 字段" />
  <button type="button" data-action="scroll-child-table" data-direction="1" data-batch-name="..." aria-label="SKU 字段向右移动一屏">▶</button>
  <span data-role="child-table-range-label">当前 A–H / 全部 A–BE</span>
</div>
```

- [ ] **Step 2: Add navigator lookup, scroll, jump, and synchronization methods**

Implement small methods with one responsibility:

```javascript
childScrollElements(batchName) {
  const selector = `[data-batch-name='${CSS.escape(String(batchName || ""))}']`;
  return {
    $source: this.$root.find(`[data-role='child-table-scroll']${selector}`),
    $header: this.$root.find(`[data-role='child-table-head-scroll']${selector}`),
    $navigator: this.$root.find(`[data-role='child-table-navigator']${selector}`),
  };
}

scrollChildTable(batchName, direction) {
  const { $source } = this.childScrollElements(batchName);
  const source = $source.get(0);
  if (!source) return;
  source.scrollBy({ left: Number(direction) * Math.max(240, source.clientWidth * .8), behavior: "smooth" });
}

setChildScrollRatio(batchName, value) {
  const { $source } = this.childScrollElements(batchName);
  const source = $source.get(0);
  if (!source) return;
  const max = Math.max(0, source.scrollWidth - source.clientWidth);
  source.scrollLeft = max * Math.max(0, Math.min(1000, Number(value))) / 1000;
}

jumpChildColumns(batchName, columnIndex) {
  const { $source, $header } = this.childScrollElements(batchName);
  const source = $source.get(0);
  const header = $header.get(0);
  const cell = $header.find(`[data-column-index='${Number(columnIndex)}']`).get(0);
  if (!source || !header || !cell) return;
  const frozenWidth = 420;
  source.scrollLeft = Math.max(0, cell.offsetLeft - frozenWidth);
}

visibleChildColumnRange($header) {
  const header = $header.get(0);
  if (!header) return [];
  const viewport = header.getBoundingClientRect();
  return $header
    .find("th[data-excel-col]")
    .toArray()
    .filter((cell) => {
      const rect = cell.getBoundingClientRect();
      return rect.right > viewport.left + 420 && rect.left < viewport.right;
    })
    .map((cell) => String(cell.dataset.excelCol || ""))
    .filter(Boolean);
}

updateChildNavigator(batchName) {
  const { $source, $header, $navigator } = this.childScrollElements(batchName);
  const source = $source.get(0);
  if (!source || !$navigator.length) return;
  const max = Math.max(0, source.scrollWidth - source.clientWidth);
  const ratio = max ? Math.round(source.scrollLeft / max * 1000) : 0;
  const visibleColumns = this.visibleChildColumnRange($header);
  const allColumns = this.batchColumns || [];
  const first = visibleColumns[0] || (allColumns[0] || {}).excel_col || "A";
  const last = visibleColumns[visibleColumns.length - 1] || first;
  const allFirst = (allColumns[0] || {}).excel_col || "A";
  const allLast = (allColumns[allColumns.length - 1] || {}).excel_col || allFirst;
  $navigator.toggleClass("is-hidden", max <= 1);
  $navigator.find("[data-role='child-table-range']").val(ratio).prop("disabled", max <= 1);
  $navigator.find("[data-direction='-1']").prop("disabled", source.scrollLeft <= 1);
  $navigator.find("[data-direction='1']").prop("disabled", source.scrollLeft >= max - 1);
  $navigator.find("[data-role='child-table-range-label']").text(`当前 ${first}–${last} / 全部 ${allFirst}–${allLast}`);
  $navigator.prevAll(".ocw-sku-column-groups").first().toggleClass("is-hidden", max <= 1);
}
```

- [ ] **Step 3: Bind mouse, range, group, and Shift+wheel actions**

```javascript
this.$root.on("click", "[data-action='scroll-child-table']", (event) => {
  const $button = $(event.currentTarget);
  this.scrollChildTable($button.attr("data-batch-name"), Number($button.attr("data-direction")));
});
this.$root.on("input", "[data-role='child-table-range']", (event) => {
  const $range = $(event.currentTarget);
  this.setChildScrollRatio($range.attr("data-batch-name"), $range.val());
});
this.$root.on("click", "[data-action='jump-child-columns']", (event) => {
  const $button = $(event.currentTarget);
  this.jumpChildColumns($button.attr("data-batch-name"), Number($button.attr("data-column-start")));
});
this.$root.on("wheel", "[data-role='child-table-scroll']", (event) => {
  if (!event.originalEvent.shiftKey) return;
  event.preventDefault();
  event.currentTarget.scrollLeft += event.originalEvent.deltaY || event.originalEvent.deltaX;
});
```

- [ ] **Step 4: Replace old scrollbar pairing with navigator synchronization**

Keep header/body scroll synchronization in `bindHierarchyScrollbars()`. On each child source scroll, set the header `scrollLeft` and call `updateChildNavigator(batchName)`. Hide `.ocw-child-table-navigator` and `.ocw-sku-column-groups` only when `scrollWidth <= clientWidth + 1`; do not depend on visible vertical height.

- [ ] **Step 5: Implement the approved frozen-column dimensions and two-line clamp**

```css
.ocw-col-code { width: 160px; }
.ocw-col-product { width: 260px; }
.ocw-sticky-1 { left: 160px; }
.ocw-child-sku-table tbody tr { height: 56px; }
.ocw-sticky-cell { background: #fff; }
.ocw-sticky-cell .ocw-table-display,
.ocw-sticky-head .ocw-sku-header-primary,
.ocw-sticky-head .ocw-sku-header-secondary {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.ocw-child-table-navigator { position: sticky; bottom: 0; z-index: 18; display: grid; grid-template-columns: 34px minmax(180px, 1fr) 34px auto; gap: 8px; align-items: center; padding: 8px 10px; border-top: 2px solid #0d777a; background: #fff; }
.ocw-child-table-range { width: 100%; accent-color: #0d777a; cursor: ew-resize; }
```

- [ ] **Step 6: Run SKU navigation contracts and syntax checks**

Run:

```bash
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
pytest -q overseas_costing/tests/test_workbench_ui_source.py -k sku
```

Expected: selected pytest cases pass; both JavaScript files parse.

- [ ] **Step 7: Commit the SKU navigator**

```bash
git add overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css} overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css}
git commit -m "feat: add mouse-first SKU field navigation"
```

### Task 5: Regression, visual verification, and cleanup

**Files:**
- Modify if needed: the four workbench JS/CSS files and `overseas_costing/tests/test_workbench_ui_source.py`.

- [ ] **Step 1: Run all source contracts**

Run: `pytest -q overseas_costing/tests/test_workbench_ui_source.py`

Expected: all tests pass for both `compat` and `module` source copies.

- [ ] **Step 2: Run JavaScript and whitespace validation**

Run:

```bash
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 3: Run the existing focused backend regression suite**

Run:

```bash
pytest -q overseas_costing/tests/test_batch_service.py overseas_costing/tests/test_calculate_service.py overseas_costing/tests/test_erp_client.py
```

Expected: pass with no changes to API, calculation, or ERP behavior.

- [ ] **Step 4: Verify the local page at desktop width**

Open the local workbench and verify:

1. Transport modes are horizontal and the advanced fields are initially collapsed.
2. Clicking a source number opens the drawer once; clicking the row background only selects; the left button alone expands SKU.
3. Switching purchase/finance view changes parent columns without changing batch data.
4. Long material codes and product names occupy at most two lines in 160px/260px frozen columns.
5. Left/right buttons, range drag, group jumps, direct table scrolling, and Shift+wheel stay synchronized.
6. The navigator hides when the columns fit and disables buttons at the ends.

- [ ] **Step 5: Commit any verification fixes**

```bash
git add overseas_costing/tests/test_workbench_ui_source.py overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css} overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css}
git commit -m "fix: polish overseas cost workbench interactions"
```

- [ ] **Step 6: Report final status without pushing**

Report the commits, tests run, remaining untracked visual-companion files, and the exact local URL used for review. Do not push or deploy without an explicit user request.
