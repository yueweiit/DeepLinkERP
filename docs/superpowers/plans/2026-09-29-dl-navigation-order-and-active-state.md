# DL Navigation Order and Active State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix visible native submenu highlighting and make the DL-mode root navigation follow the approved fixed order with “China Finance” displayed as “Finance/财务”.

**Architecture:** Extend the existing `DeepLinkERPNavigation` model instead of introducing another menu source. Root ordering is a pure stable transform over the already-authorized navigation-tree copy; display naming is a pure helper consumed by the existing renderer. The existing route-based active-state synchronizer is reused for the live native sidebar before ownership resolution.

**Tech Stack:** Frappe v16 Desk JavaScript, Node.js built-in test runner, Python unittest, Docker Compose local preview.

---

### Task 1: Synchronize the visible live submenu before navigation ownership resolution

**Files:**
- Modify: `tests/navigation-model.test.js`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_branding.js`

- [ ] **Step 1: Write the failing lifecycle regression test**

Add a focused test that extracts the `renderPersistentNavigation` source and requires `updateRenderedSidebarActive(nativeItems)` to run before `buildNavigationModel`:

```js
test("synchronizes the live native sidebar before resolving navigation ownership", () => {
	const lifecycle = fs.readFileSync(
		path.join(__dirname, "..", "deeplinkerp_branding", "public", "js", "deeplinkerp_branding.js"),
		"utf8"
	);
	const start = lifecycle.indexOf("function renderPersistentNavigation()");
	const end = lifecycle.indexOf("function enhanceDesktopIcons()", start);
	const renderSource = lifecycle.slice(start, end);

	assert.ok(start >= 0 && end > start);
	assert.match(renderSource, /updateRenderedSidebarActive\(nativeItems\)/);
	assert.ok(
		renderSource.indexOf("updateRenderedSidebarActive(nativeItems)") <
			renderSource.indexOf("DeepLinkERPNavigation.buildNavigationModel")
	);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test --test-name-pattern="synchronizes the live native sidebar" tests/navigation-model.test.js`

Expected: FAIL because `renderPersistentNavigation` does not yet synchronize `nativeItems`.

- [ ] **Step 3: Reuse the existing active-state synchronizer on the live node**

In `renderPersistentNavigation`, after the native node is claimed and before the model reads `getNativeActiveItem(nativeItems)`, add:

```js
updateRenderedSidebarActive(nativeItems);
```

Keep `updateRenderedSidebarActive` as the single URL-to-`active-sidebar` implementation for both live and rendered sidebar containers.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `node --test --test-name-pattern="synchronizes the live native sidebar" tests/navigation-model.test.js`

Expected: PASS.

### Task 2: Apply the fixed DL root navigation order

**Files:**
- Modify: `tests/navigation-model.test.js`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`

- [ ] **Step 1: Write failing model tests for known and unknown roots**

Add one test with all approved modules in scrambled source order and assert this result:

```js
[
	"Organization",
	"Buying",
	"Selling",
	"Stock",
	"Manufacturing",
	"Assets",
	"China Finance",
	"Overseas Costing",
	"Projects",
	"Quality",
	"Subcontracting",
	"Accounting",
	"AI Assistant",
	"DLP Framework",
	"Deeplinkerp Settings",
]
```

Add a second test with `Custom B`, `Quality`, `Buying`, and `Custom A`; assert `Buying`, `Quality`, `Custom B`, `Custom A`. Also assert the input array is unchanged and a child of `Buying` remains a child rather than becoming a root.

- [ ] **Step 2: Run the two ordering tests and verify RED**

Run: `node --test --test-name-pattern="fixed DL root order|unknown DL roots" tests/navigation-model.test.js`

Expected: both tests FAIL because roots currently preserve source order.

- [ ] **Step 3: Implement one stable root-order transform**

Add a single alias-to-priority table covering English and Chinese identities for the approved modules:

```js
const ROOT_NAVIGATION_ORDER = Object.freeze([
	["organization", "组织"],
	["buying", "采购"],
	["selling", "销售"],
	["stock", "库存"],
	["manufacturing", "生产"],
	["assets", "资产"],
	["china finance", "中国财务", "财务"],
	["overseas costing", "overseas cost", "overseas cost workbench", "海外成本核算"],
	["projects", "项目"],
	["quality", "质量"],
	["subcontracting", "委外"],
	["accounting", "会计"],
	["ai assistant", "ai 助手"],
	["dlp framework"],
	["deeplinkerp settings", "deeplinkerp setting", "erpnext settings"],
]);
```

Create `arrangeNavigationRoots(roots)` using `nodeAliases(node)`, the configured priority, and the original source index as the stable fallback. Return `arrangeNavigationRoots(roots)` from `buildNavigationTree`; do not sort child arrays or mutate `desktopIcons`.

- [ ] **Step 4: Run the ordering tests and full model tests**

Run: `node --test --test-name-pattern="fixed DL root order|unknown DL roots" tests/navigation-model.test.js`

Expected: PASS.

Run: `node --test tests/navigation-model.test.js`

Expected: all navigation tests PASS; update the existing source-order test only where its root expectation is intentionally changed by the approved DL order.

### Task 3: Render China Finance as Finance without changing its identity

**Files:**
- Modify: `tests/navigation-model.test.js`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_branding.js`
- Modify: `deeplinkerp_branding/translations/zh.csv`
- Modify: `deeplinkerp_branding/translations/es.csv`
- Modify: `deeplinkerp_branding/hooks.py`

- [ ] **Step 1: Write the failing display-label tests**

Add a model test that requires:

```js
assert.equal(getNavigationDisplayLabel({ name: "China Finance", label: "China Finance" }), "Finance");
assert.equal(getNavigationDisplayLabel({ name: "Buying", label: "Buying", translated_label: "采购" }), "采购");
```

Extend the existing lifecycle integration test to require:

```js
assert.match(lifecycle, /translate\(DeepLinkERPNavigation\.getNavigationDisplayLabel\(item\)\)/);
```

- [ ] **Step 2: Run the focused display test and verify RED**

Run: `node --test --test-name-pattern="navigation display label" tests/navigation-model.test.js`

Expected: FAIL because `getNavigationDisplayLabel` is not exported.

- [ ] **Step 3: Implement the display-only label helper**

Add and export:

```js
function getNavigationDisplayLabel(node) {
	const aliases = nodeAliases(node);
	if (aliases.includes("china finance") || aliases.includes("中国财务")) return "Finance";
	return node?.translated_label || node?.label || node?.name || "";
}
```

Change only the row renderer:

```js
label.textContent = translate(DeepLinkERPNavigation.getNavigationDisplayLabel(item));
```

Add `"Finance","财务"` to `translations/zh.csv` and `"Finance","Finanzas"` to `translations/es.csv`. Do not change the source workspace label or route aliases.

- [ ] **Step 4: Bump Desk asset versions and update the existing assertion**

Change:

```python
"/assets/deeplinkerp_branding/js/deeplinkerp_navigation.js?v=0.0.18",
"/assets/deeplinkerp_branding/js/deeplinkerp_branding.js?v=0.0.25",
```

Update the matching version assertions in `tests/navigation-model.test.js`.

- [ ] **Step 5: Run the focused and full JavaScript suites**

Run: `node --test tests/*.test.js`

Expected: all tests PASS with no failures.

### Task 4: Build and verify the local preview

**Files:**
- No production file changes expected.

- [ ] **Step 1: Run static and Python verification**

Run:

```bash
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
python3 -m unittest -v tests.test_interface_mode tests.test_boot_branding tests.test_interface_mode_metadata
python3 -m compileall -q deeplinkerp_branding
git diff --check
```

Expected: JavaScript syntax checks succeed, 18 Python tests pass, compilation and diff checks succeed.

- [ ] **Step 2: Commit the implementation**

```bash
git add deeplinkerp_branding tests/navigation-model.test.js
git commit -m "固定 DL 导航顺序并恢复子菜单高亮"
```

- [ ] **Step 3: Rebuild the existing local preview image**

Build `overseas-cost-local:mes-nav-preview` with `/tmp/Dockerfile.deeplinkerp-mes-nav`, recreate the services from `pwd.yml`, `compose.local.yaml`, and `/tmp/compose.deeplinkerp-mes-nav.yaml`, then clear Frappe cache and website cache.

Expected: image build and service recreation exit successfully; `http://localhost:64115/login` responds.

- [ ] **Step 4: Verify live behavior in the browser**

On `http://localhost:64115/desk/purchase-order`, verify:

- visible root order matches the approved order, omitting only unauthorized modules;
- “中国财务” is rendered as “财务”;
- the visible “采购订单” row has `active-sidebar` and `aria-current="page"`;
- clicking a root still toggles without navigating;
- clicking a leaf still routes in the same tab;
- refresh and browser back/forward retain the correct visible highlighter;
- one `.dlp-mes-navigation` root exists and the page has no horizontal overflow.

- [ ] **Step 5: Run final verification and report reuse-first statistics**

Re-run all JavaScript and Python tests, syntax checks, `git diff --check`, clean worktree check, local HTTP check, and running-container check. Report additions, modifications, deletions, duplicate logic, line/test changes, compatibility, and technical debt separately.
