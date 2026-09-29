# Navigation Chevron Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every sidebar chevron an independent, easy-to-click branch toggle while preserving module navigation on the icon-and-label link.

**Architecture:** Reuse the existing navigation tree, branch state, route close behavior, and DOM-only collapsed markers. Split each rendered row into a semantic main navigation control plus an optional 36×36px chevron button, then bind branch toggling only to the chevron and route behavior only to the main link.

**Tech Stack:** Frappe v16 Desk, vanilla JavaScript, scoped CSS, Node.js `node:test`, Docker Compose local preview.

---

## File Map

- Modify `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`: route event binding and reusable branch-toggle behavior.
- Modify `deeplinkerp_branding/public/js/deeplinkerp_branding.js`: semantic row/link/chevron DOM construction and lifecycle wiring.
- Modify `deeplinkerp_branding/public/css/deeplinkerp_navigation.css`: split-control layout, 36×36px hit target, 18px icon, hover/focus/active states.
- Modify `deeplinkerp_branding/hooks.py`: cache-busting versions for the changed Desk assets.
- Modify `tests/navigation-model.test.js`: interaction, semantic structure, sizing, and regression scenarios.

No new production file, navigation data source, router, persisted state, or compatibility layer is required.

### Task 1: Separate Route And Branch Event Targets

**Files:**
- Modify: `tests/navigation-model.test.js:443-582`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_navigation.js:104-133,175-190`

- [ ] **Step 1: Replace the row-wide branch tests with failing split-control tests**

Add tests that use separate `navigationLink` and `toggleButton` elements. The inactive parent case must prove the chevron can expand without route navigation, while the main link retains mobile close behavior:

```javascript
test("parent chevron toggles its branch without invoking route behavior", () => {
	const bindNavigationRowInteractions = productionFunction("bindNavigationRowInteractions");
	const navigationLink = new FakeElement();
	const toggleButton = new FakeElement();
	const group = new FakeElement(["dlp-mes-navigation__group"]);
	const branch = new FakeElement();
	toggleButton.setAttribute("aria-expanded", "false");
	branch.hidden = true;
	let closeCalls = 0;
	const chevronStates = [];

	bindNavigationRowInteractions(navigationLink, {
		toggleButton,
		group,
		branch,
		route: "/desk/buying",
		updateChevron: (open) => chevronStates.push(open),
		isNarrowViewport: () => true,
		closeSidebar: () => {
			closeCalls += 1;
		},
	});

	const toggleEvent = toggleButton.dispatch("click");
	assert.equal(toggleEvent.defaultPrevented, true);
	assert.equal(toggleButton.getAttribute("aria-expanded"), "true");
	assert.equal(branch.hidden, false);
	assert.equal(closeCalls, 0);
	assert.deepEqual(chevronStates, [true]);

	const linkEvent = navigationLink.dispatch("click");
	assert.equal(linkEvent.defaultPrevented, false);
	assert.equal(closeCalls, 1);
	assert.equal(toggleButton.getAttribute("aria-expanded"), "true");
});
```

Add a second test that dispatches the chevron twice and verifies `aria-expanded`, `branch.hidden`, `dlp-mes-navigation__group--open`, and `data-user-collapsed` switch in both directions. Add a third test for a route-less parent: its main button and chevron both use the same existing branch-toggle helper because there is no destination.

- [ ] **Step 2: Run the focused Node suite and verify RED**

Run:

```bash
node --test tests/navigation-model.test.js
```

Expected: the new split-control tests fail because `bindNavigationRowInteractions` does not accept `toggleButton`, and inactive routed parents currently do not bind a branch toggle.

- [ ] **Step 3: Bind the existing behaviors to separate controls**

Change the interaction helpers to use the toggle control as the sole owner of `aria-expanded` and branch state:

```javascript
function bindNavigationRowInteractions(
	navigationLink,
	{
		toggleButton,
		group,
		branch,
		route = "",
		updateChevron,
		isNarrowViewport,
		closeSidebar,
		preserveDesktopExpansion,
	}
) {
	const toggleOptions = { group, branch, updateChevron };
	if (toggleButton && branch) {
		bindNavigationBranchToggle(toggleButton, toggleOptions);
	}
	if (!route && branch) {
		bindNavigationBranchToggle(navigationLink, toggleOptions);
	}
	if (route) {
		bindNativeSidebarClose(navigationLink, {
			isNarrowViewport,
			closeSidebar,
			preserveDesktopExpansion,
		});
	}
}

function bindNavigationBranchToggle(
	toggleControl,
	{ group, branch, updateChevron }
) {
	toggleControl.addEventListener("click", (event) => {
		event.preventDefault();
		const open = toggleControl.getAttribute("aria-expanded") !== "true";
		toggleControl.setAttribute("aria-expanded", String(open));
		branch.hidden = !open;
		group.classList.toggle("dlp-mes-navigation__group--open", open);
		if (open) delete group.dataset.userCollapsed;
		else group.dataset.userCollapsed = "true";
		updateChevron(open);
	});
}
```

Remove the obsolete `route` and `itemIsOpen` conditions from `bindNavigationBranchToggle`. They encoded the old whole-row interaction and would prevent expanding an inactive module before navigation.

- [ ] **Step 4: Run the focused suite and verify GREEN**

Run:

```bash
node --test tests/navigation-model.test.js
```

Expected: all interaction tests pass; the suite count increases only for the new independent behavior scenarios.

- [ ] **Step 5: Commit the event-boundary change**

```bash
git add tests/navigation-model.test.js deeplinkerp_branding/public/js/deeplinkerp_navigation.js
git commit -m "拆分导航跳转与子菜单切换事件"
```

### Task 2: Render Semantic Split Controls And Larger Chevron

**Files:**
- Modify: `tests/navigation-model.test.js:620-705`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_branding.js:302-395`
- Modify: `deeplinkerp_branding/public/css/deeplinkerp_navigation.css:24-31,102-185,303-308`
- Modify: `deeplinkerp_branding/hooks.py:27-30`

- [ ] **Step 1: Add failing DOM-contract and CSS-contract tests**

Extend the lifecycle source test so it requires a separate row container, main link, and button chevron, and rejects the former span chevron:

```javascript
assert.match(lifecycle, /navigationLink\.className\s*=\s*"dlp-mes-navigation__link"/);
assert.match(lifecycle, /toggleButton\.type\s*=\s*"button"/);
assert.match(lifecycle, /toggleButton\.className\s*=\s*"dlp-mes-navigation__chevron"/);
assert.match(lifecycle, /toggleButton\.setAttribute\("aria-expanded"/);
assert.doesNotMatch(lifecycle, /chevron\.className\s*=\s*"dlp-mes-navigation__chevron"/);
```

Extend the CSS test to require a 36×36px button hit target and an 18×18px icon:

```javascript
assert.match(chevron || "", /width:\s*36px/);
assert.match(chevron || "", /height:\s*36px/);
assert.match(chevron || "", /flex:\s*0\s+0\s+36px/);
assert.match(chevronSvg || "", /width:\s*18px/);
assert.match(chevronSvg || "", /height:\s*18px/);
assert.match(stylesheet, /\.dlp-mes-navigation__chevron:focus-visible/);
```

Update the hook-version test to expect navigation model `0.0.7`, lifecycle `0.0.13`, and navigation CSS `0.0.6`.

- [ ] **Step 2: Run the focused Node suite and verify RED**

Run:

```bash
node --test tests/navigation-model.test.js
```

Expected: DOM structure, sizing, focus, and asset-version assertions fail against the current span-inside-link implementation.

- [ ] **Step 3: Split the rendered row into valid sibling controls**

Replace `makeNavigationRow` so it returns the three elements needed by the renderer:

```javascript
function makeNavigationRow(item, isOpen = item.isOpen) {
	const hasChildren = item.children.length > 0 || item.hasNativeChildren;
	const route = item.navigation_route || item.route || item.link || item.url;
	const row = document.createElement("div");
	row.className = "dlp-mes-navigation__row";

	const navigationLink = document.createElement(route ? "a" : "button");
	navigationLink.className = "dlp-mes-navigation__link";
	if (route) navigationLink.href = route;
	else navigationLink.type = "button";
	if (item.isSelfActive) navigationLink.setAttribute("aria-current", "page");

	const icon = document.createElement("span");
	icon.className = "dlp-mes-navigation__icon";
	icon.innerHTML = makeLineIcon(DeepLinkERPNavigation.getNavigationIcon(item.label));
	navigationLink.appendChild(icon);

	const label = document.createElement("span");
	label.className = "dlp-mes-navigation__label";
	label.textContent = translate(item.label);
	navigationLink.appendChild(label);
	row.appendChild(navigationLink);

	let toggleButton = null;
	if (hasChildren) {
		toggleButton = document.createElement("button");
		toggleButton.type = "button";
		toggleButton.className = "dlp-mes-navigation__chevron";
		toggleButton.setAttribute("aria-expanded", String(isOpen));
		toggleButton.setAttribute(
			"aria-label",
			`${translate(isOpen ? "Collapse" : "Expand")} ${translate(item.label)}`
		);
		toggleButton.innerHTML = makeLineIcon(isOpen ? "chevron-down" : "chevron-right");
		row.appendChild(toggleButton);
	}

	return { row, navigationLink, toggleButton };
}
```

In `renderNavigationItem`, destructure the returned controls, append `row`, pass `navigationLink` as the first argument to `bindNavigationRowInteractions`, and pass `toggleButton` in the options. Update the chevron callback to modify `toggleButton.innerHTML`, its `aria-label`, and no other route element.

- [ ] **Step 4: Update the scoped styles without changing the 40px row height**

Keep hover and active backgrounds on `.dlp-mes-navigation__row`. Move link-specific padding, font, cursor, and text-decoration rules to `.dlp-mes-navigation__link`:

```css
.dlp-mes-navigation__row {
	display: flex;
	align-items: center;
	width: 100%;
	height: 40px;
	margin: 1px 0;
	border-radius: 8px;
	background: transparent;
	color: #91a3b7;
}

.dlp-mes-navigation__link {
	display: flex;
	align-items: center;
	min-width: 0;
	height: 100%;
	padding-left: calc(8px + var(--dlp-navigation-depth, 0) * 12px);
	flex: 1 1 auto;
	border: 0;
	background: transparent;
	color: inherit;
	font: inherit;
	text-align: left;
	text-decoration: none;
	cursor: pointer;
}

.dlp-mes-navigation__chevron {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 36px;
	height: 36px;
	margin: 0 2px 0 0;
	padding: 0;
	flex: 0 0 36px;
	border: 0;
	border-radius: 7px;
	background: transparent;
	color: #c7d4e3;
	cursor: pointer;
}

.dlp-mes-navigation__chevron:hover {
	background: rgba(255, 255, 255, 0.1);
	color: #fff;
}

.dlp-mes-navigation__chevron svg {
	width: 18px;
	height: 18px;
}
```

Include both `.dlp-mes-navigation__link:focus-visible` and `.dlp-mes-navigation__chevron:focus-visible` in the existing focus ring. Keep collapsed-side hiding for the chevron and children.

- [ ] **Step 5: Bump asset query versions**

Set:

```python
app_include_css = "/assets/deeplinkerp_branding/css/deeplinkerp_navigation.css?v=0.0.6"
app_include_js = [
    "/assets/deeplinkerp_branding/js/deeplinkerp_navigation.js?v=0.0.7",
    "/assets/deeplinkerp_branding/js/deeplinkerp_branding.js?v=0.0.13",
]
```

- [ ] **Step 6: Run automated verification and verify GREEN**

Run:

```bash
node --test tests/navigation-model.test.js
python3 -m unittest -v tests.test_boot_branding
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
python3 -m compileall -q deeplinkerp_branding tests
git diff --check
```

Expected: every command exits 0; existing 20 Node and 4 Python scenarios remain green, with only the deliberately added independent interaction scenarios increasing the Node count.

- [ ] **Step 7: Commit the semantic DOM and visual change**

```bash
git add tests/navigation-model.test.js deeplinkerp_branding/hooks.py \
  deeplinkerp_branding/public/js/deeplinkerp_branding.js \
  deeplinkerp_branding/public/css/deeplinkerp_navigation.css
git commit -m "分离导航箭头与模块跳转"
```

### Task 3: Build And Verify The Local Preview

**Files:**
- Verify only; no source file changes expected.

- [ ] **Step 1: Build the preview image from the isolated worktree**

Run from `/Users/smk/.codex/worktrees/mes-navigation/DeepLinkERP`:

```bash
docker build --platform linux/amd64 \
  -f /tmp/Dockerfile.deeplinkerp-mes-nav \
  -t overseas-cost-local:mes-nav-preview .
```

Expected: image build exits 0. Redis asset-manifest warnings during the isolated image build are acceptable because Redis is not attached at build time.

- [ ] **Step 2: Recreate only the preview application services and clear cache**

Run from `/Users/smk/Documents/ChatGPT/综合成本计算系统-local-env/frappe_docker`:

```bash
docker compose -p overseas-cost-local \
  -f pwd.yml -f compose.local.yaml -f /tmp/compose.deeplinkerp-mes-nav.yaml \
  up -d --no-deps --force-recreate \
  backend frontend websocket queue-short queue-long scheduler
docker exec overseas-cost-local-backend-1 bench --site frontend clear-cache
```

Expected: all six services report `Up`; no database or Redis volume is recreated.

- [ ] **Step 3: Verify desktop behavior at 1280×800**

Open `http://localhost:64115/desk/buying` and verify:

1. Clicking the Buying chevron changes only its branch visibility; URL remains `/desk/buying` and the 220px sidebar remains expanded.
2. From another module, clicking the Buying chevron expands Buying without navigating away.
3. Clicking the Buying icon or label navigates to `/desk/buying`.
4. Repeat the same checks for Manufacturing and Projects to prove the rule is generic.
5. The chevron hit target measures 36×36px, the icon is 18×18px, focus is visible, one navigation root exists, and horizontal overflow is 0.

- [ ] **Step 4: Verify mobile behavior at 375px**

Verify:

1. With the sidebar open, clicking any chevron keeps the whole sidebar open and leaves the URL unchanged.
2. Clicking that module's icon or label navigates and closes the mobile sidebar.
3. Reopening the sidebar shows the correct current module, branch, active leaf, and chevron direction.
4. Horizontal overflow remains 0.

- [ ] **Step 5: Record final repository and change statistics**

Run:

```bash
git status --short --branch
git diff --numstat ab4d38d..HEAD
git log --oneline ab4d38d..HEAD
```

Expected: the worktree is clean. Report added, modified, and deleted files; new business scenarios versus adjusted existing tests; no duplicate router/menu state; retained compatibility; and any remaining Frappe DOM dependency as technical debt.
