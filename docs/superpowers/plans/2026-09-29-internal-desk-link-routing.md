# Internal Desk Link Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every same-origin `/desk` child-menu link use Frappe's existing SPA router instead of being forced into a new full-page tab by `target="_blank"`.

**Architecture:** Extend the existing pure navigation model with one URL-classification helper, then call it from the existing `bindRenderedSidebarLinks()` entry point. Internal Desk links only lose their `_blank` target; Frappe's global body click handler remains the sole router, while external URLs keep their original behavior.

**Tech Stack:** Frappe v16 Desk router, vanilla JavaScript, Node.js built-in test runner, Docker Compose local preview, Chrome browser acceptance.

---

## File map and reuse decision

- Modify `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`: add and export one pure internal-Desk URL predicate next to the existing route normalization helpers.
- Modify `deeplinkerp_branding/public/js/deeplinkerp_branding.js`: reuse `bindRenderedSidebarLinks()` for both live and snapshot sidebar nodes; normalize internal targets before the existing mobile-close/desktop-state binding.
- Modify `deeplinkerp_branding/hooks.py`: bump only the two changed Desk asset cache versions.
- Modify `tests/navigation-model.test.js`: add one independent URL-classification scenario and extend the existing lifecycle contract test; do not create a parallel test file.

No existing implementation is replaced or deleted. Frappe's body-level router is still called by the browser click event, so no compatibility layer or future removal milestone is needed.

### Task 1: Classify internal Desk URLs

**Files:**
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`
- Test: `tests/navigation-model.test.js`

- [ ] **Step 1: Write the failing pure-function test**

Add a test beside the existing route normalization test:

```javascript
test("classifies only same-origin Desk links as internal navigation", () => {
	const isInternalDeskLink = productionFunction("isInternalDeskLink");
	const origin = "https://erp.test";

	assert.equal(isInternalDeskLink("/desk/china-finance", origin), true);
	assert.equal(isInternalDeskLink("https://erp.test/desk/buying?view=1", origin), true);
	assert.equal(isInternalDeskLink("/desk", origin), true);
	assert.equal(isInternalDeskLink("https://external.test/desk/buying", origin), false);
	assert.equal(isInternalDeskLink("/files/report.pdf", origin), false);
	assert.equal(isInternalDeskLink("mailto:help@example.com", origin), false);
	assert.equal(isInternalDeskLink("not a valid url", "not an origin"), false);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
node --test --test-name-pattern="classifies only same-origin Desk links" tests/navigation-model.test.js
```

Expected: FAIL because `isInternalDeskLink` is not exported.

- [ ] **Step 3: Implement the minimal predicate**

Add next to `normalizeRoute()`:

```javascript
function isInternalDeskLink(href, origin) {
	if (!href || !origin) return false;
	try {
		const base = new URL(origin);
		const target = new URL(href, base);
		const path = normalizePath(target.pathname);
		return target.origin === base.origin && (path === "/desk" || path.startsWith("/desk/"));
	} catch (error) {
		return false;
	}
}
```

Export `isInternalDeskLink` from the existing frozen navigation API.

- [ ] **Step 4: Run the focused and full model tests**

Run:

```bash
node --test --test-name-pattern="classifies only same-origin Desk links" tests/navigation-model.test.js
node --test tests/*.test.js
```

Expected: focused test PASS; full suite PASS with one additional business scenario.

### Task 2: Normalize every rendered internal child link

**Files:**
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_branding.js`
- Modify: `deeplinkerp_branding/hooks.py`
- Test: `tests/navigation-model.test.js`

- [ ] **Step 1: Extend the lifecycle contract test and verify RED**

Add assertions to `integrates the executable lifecycle helpers through the existing single router binding`:

```javascript
assert.match(lifecycle, /function normalizeRenderedSidebarTarget\(link\)/);
assert.match(lifecycle, /DeepLinkERPNavigation\.isInternalDeskLink\(/);
assert.match(lifecycle, /link\.removeAttribute\("target"\)/);
assert.match(
	lifecycle,
	/function bindRenderedSidebarLinks\(container\)[\s\S]*normalizeRenderedSidebarTarget\(link\)/
);
```

Run:

```bash
node --test --test-name-pattern="integrates the executable lifecycle helpers" tests/navigation-model.test.js
```

Expected: FAIL because the target-normalization helper does not exist.

- [ ] **Step 2: Reuse the existing link-binding entry point**

Add immediately before `bindRenderedSidebarLinks()`:

```javascript
function normalizeRenderedSidebarTarget(link) {
	const href = link.getAttribute("href") || "";
	if (!DeepLinkERPNavigation.isInternalDeskLink(href, window.location.origin)) return false;
	link.removeAttribute("target");
	return true;
}
```

Call it once for every unbound `.item-anchor` before assigning `data-dlp-navigation-bound`:

```javascript
container.querySelectorAll(".item-anchor").forEach((link) => {
	if (link.dataset.dlpNavigationBound === "true") return;
	normalizeRenderedSidebarTarget(link);
	link.dataset.dlpNavigationBound = "true";
	// keep the existing bindNativeSidebarClose call unchanged
});
```

This applies automatically to both existing callers: the live native sidebar and every authorized snapshot branch.

- [ ] **Step 3: Bump changed asset versions**

In `deeplinkerp_branding/hooks.py`, increment the navigation model and branding lifecycle query versions once. Update the existing hook assertions to those exact versions.

- [ ] **Step 4: Run all automated checks**

Run:

```bash
node --test tests/*.test.js
python3 -m unittest -v \
  tests.test_interface_mode \
  tests.test_boot_branding \
  tests.test_interface_mode_metadata
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
python3 -m compileall -q deeplinkerp_branding tests
git diff --check
```

Expected: all JavaScript and Python tests pass; syntax, compile and diff checks exit 0.

- [ ] **Step 5: Commit the code change**

```bash
git add \
  deeplinkerp_branding/hooks.py \
  deeplinkerp_branding/public/js/deeplinkerp_navigation.js \
  deeplinkerp_branding/public/js/deeplinkerp_branding.js \
  tests/navigation-model.test.js
git commit -m "统一内部 Desk 菜单的单页路由"
```

### Task 3: Rebuild and verify the local preview

**Files:**
- No source changes expected.

- [ ] **Step 1: Build the preview image**

Run from the worktree:

```bash
docker build --platform linux/amd64 \
  -f /tmp/Dockerfile.deeplinkerp-mes-nav \
  -t overseas-cost-local:mes-nav-preview .
```

Expected: image build exits 0. The existing constant-platform and build-time Redis warnings may remain; no asset compilation failure is allowed.

- [ ] **Step 2: Recreate local services and clear caches**

Run from `/Users/smk/Documents/ChatGPT/综合成本计算系统-local-env/frappe_docker`:

```bash
docker compose -p overseas-cost-local \
  -f pwd.yml \
  -f compose.local.yaml \
  -f /tmp/compose.deeplinkerp-mes-nav.yaml \
  up -d --force-recreate backend frontend websocket queue-short queue-long scheduler

docker compose -p overseas-cost-local \
  -f pwd.yml \
  -f compose.local.yaml \
  -f /tmp/compose.deeplinkerp-mes-nav.yaml \
  exec -T backend bench --site frontend clear-cache
```

Expected: all recreated services report `Up`; `http://localhost:64115/login` returns HTTP 200.

- [ ] **Step 3: Verify the original China Finance scenario**

In Chrome at `http://localhost:64115/desk/buying`:

1. Expand 中国财务.
2. Inspect 中国财务工作台 and confirm `href=/desk/china-finance` with no `target`.
3. Click it and confirm the same tab enters `/desk/china-finance` without opening a new tab or showing the classic Desktop screen.
4. Confirm 中国财务 is expanded and 中国财务工作台 is the active blue leaf.

- [ ] **Step 4: Verify global coverage and retained behavior**

Repeat with two other internal URL-type children from different modules. Confirm external URL items retain `_blank`. Verify browser back/forward, page refresh, one navigation root, and no horizontal overflow.

- [ ] **Step 5: Record final reuse-first report**

Run:

```bash
git diff HEAD~1 --numstat
git status --short
git log -3 --oneline
```

Report:

- Added: one pure route classifier and its independent business test.
- Modified: the existing single link-binding entry point and asset versions.
- Deleted: none.
- Duplicate logic: none; Frappe remains the only router.
- Compatibility retention: external URL behavior and Frappe modifier-key handling remain because their existing callers are still active; no temporary compatibility layer was introduced.
- Technical debt: the underlying workspace records may still classify internal routes as `URL`, but navigation no longer depends on correcting each record individually.
