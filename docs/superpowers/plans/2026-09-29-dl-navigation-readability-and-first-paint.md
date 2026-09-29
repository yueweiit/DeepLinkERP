# DL Navigation Readability and First Paint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the approved DL sidebar readable, replace the native white scrollbar with a thin MES-style scrollbar, and prevent the classic large-icon desktop from flashing before DL navigation appears on hard refresh.

**Architecture:** Extend the existing `DeepLinkERPInterfaceMode` module with one document-scoped preparation controller that reads the already-resolved boot mode synchronously, owns a single two-second watchdog, and exposes one completion method to the existing branding lifecycle. Keep the current Frappe-authorized navigation renderer unchanged; add only narrowly scoped pending-state and sidebar visual rules to the existing Desk stylesheet.

**Tech Stack:** Frappe v16 Desk JavaScript, CSS, Node.js built-in test runner, Python unittest, Docker Compose local preview, Chromium visual acceptance.

---

## File map

- `tests/interface-mode.test.js`: executable preparation-state, idempotency, classic-mode, completion, and timeout tests.
- `tests/navigation-model.test.js`: lifecycle wiring, CSS contract, and asset-version regression tests.
- `deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js`: the only owner of effective-mode parsing and first-paint preparation state.
- `deeplinkerp_branding/public/js/deeplinkerp_branding.js`: completes preparation only after the existing real navigation has been rendered and synchronized.
- `deeplinkerp_branding/public/css/deeplinkerp_navigation.css`: pending brand shell, approved A-palette overrides, and 6px scrollbar.
- `deeplinkerp_branding/hooks.py`: cache-busting versions for the three changed Desk assets.

No new production file, menu model, API, database field, or persistent client state is introduced.

### Task 1: Add a document-scoped DL preparation controller

**Files:**
- Modify: `tests/interface-mode.test.js:8-305`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js:1-216`

- [ ] **Step 1: Extend the test fake with the DOM operations used by preparation state**

Add `documentElement` to `FakeDocument`, and add this getter to `FakeElement` so the tests exercise the same class API as the browser:

```js
get classList() {
	const element = this;
	return {
		add(...names) {
			const classes = new Set(element.className.split(/\s+/).filter(Boolean));
			names.forEach((name) => classes.add(name));
			element.className = Array.from(classes).join(" ");
		},
		remove(...names) {
			const removed = new Set(names);
			element.className = element.className
				.split(/\s+/)
				.filter((name) => name && !removed.has(name))
				.join(" ");
		},
		contains(name) {
			return element.className.split(/\s+/).includes(name);
		},
	};
}
```

In `FakeDocument.constructor`, add:

```js
this.documentElement = root;
```

- [ ] **Step 2: Write failing tests for DL, classic, completion, idempotency, and timeout**

Add these focused tests to `tests/interface-mode.test.js`:

```js
test("starts one synchronous preparation only for an explicit DL boot mode", () => {
	const startDLPreparation = productionFunction("startDLPreparation");
	const root = new FakeElement("html");
	const document = new FakeDocument(root);
	let scheduled;
	const schedule = (callback, delay) => {
		scheduled = { callback, delay };
		return 42;
	};

	const first = startDLPreparation({
		document,
		boot: { deeplinkerp_interface_mode: { effective_mode: "dl" } },
		schedule,
		cancel() {},
		warn() {},
	});
	const second = startDLPreparation({
		document,
		boot: { deeplinkerp_interface_mode: { effective_mode: "dl" } },
		schedule,
		cancel() {},
		warn() {},
	});

	assert.equal(first, second);
	assert.equal(root.classList.contains("dlp-interface-mode-dl-pending"), true);
	assert.equal(root.getAttribute("aria-busy"), "true");
	assert.equal(scheduled.delay, 2000);
});

test("does not prepare classic or missing boot state", () => {
	const startDLPreparation = productionFunction("startDLPreparation");
	for (const boot of [
		{},
		{ deeplinkerp_interface_mode: { effective_mode: "classic" } },
	]) {
		const root = new FakeElement("html");
		const document = new FakeDocument(root);
		assert.equal(startDLPreparation({ document, boot }), null);
		assert.equal(root.classList.contains("dlp-interface-mode-dl-pending"), false);
	}
});

test("finishes preparation once and cancels its watchdog", () => {
	const startDLPreparation = productionFunction("startDLPreparation");
	const finishDLPreparation = productionFunction("finishDLPreparation");
	const root = new FakeElement("html");
	const document = new FakeDocument(root);
	const cancelled = [];
	startDLPreparation({
		document,
		boot: { deeplinkerp_interface_mode: { effective_mode: "dl" } },
		schedule: () => 42,
		cancel: (timer) => cancelled.push(timer),
		warn() {},
	});

	assert.equal(finishDLPreparation(document), true);
	assert.equal(finishDLPreparation(document), false);
	assert.deepEqual(cancelled, [42]);
	assert.equal(root.classList.contains("dlp-interface-mode-dl-pending"), false);
	assert.equal(root.getAttribute("aria-busy"), null);
});

test("times out to the native UI with one warning", () => {
	const startDLPreparation = productionFunction("startDLPreparation");
	const root = new FakeElement("html");
	const document = new FakeDocument(root);
	let timeoutCallback;
	const warnings = [];
	startDLPreparation({
		document,
		boot: { deeplinkerp_interface_mode: { effective_mode: "dl" } },
		schedule: (callback) => {
			timeoutCallback = callback;
			return 7;
		},
		cancel() {},
		warn: (message) => warnings.push(message),
	});

	timeoutCallback();
	timeoutCallback();
	assert.equal(root.classList.contains("dlp-interface-mode-dl-pending"), false);
	assert.equal(root.getAttribute("aria-busy"), null);
	assert.equal(warnings.length, 1);
});

test("boots preparation before the branding lifecycle waits for DOMContentLoaded", () => {
	const source = fs.readFileSync(modulePath, "utf8");
	assert.match(source, /root\.DeepLinkERPInterfaceMode\s*=\s*interfaceMode/);
	assert.match(source, /interfaceMode\.startDLPreparation\(/);
	assert.ok(
		source.indexOf("root.DeepLinkERPInterfaceMode = interfaceMode") <
			source.indexOf("interfaceMode.startDLPreparation(")
	);
});
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
node --test --test-name-pattern="preparation|prepare classic|times out" tests/interface-mode.test.js
```

Expected: FAIL because `startDLPreparation` and `finishDLPreparation` are not exported.

- [ ] **Step 4: Implement the minimal preparation controller and synchronous bootstrap**

Add these constants and helpers beside the existing module-level WeakMaps:

```js
const DL_PREPARING_CLASS = "dlp-interface-mode-dl-pending";
const DL_PREPARATION_TIMEOUT_MS = 2000;
const activePreparations = new WeakMap();

function explicitEffectiveMode(boot = {}) {
	return normalizeMode(boot?.deeplinkerp_interface_mode?.effective_mode);
}

function startDLPreparation({
	document,
	boot,
	schedule = globalThis.setTimeout?.bind(globalThis),
	cancel = globalThis.clearTimeout?.bind(globalThis),
	warn = globalThis.console?.warn?.bind(globalThis.console),
	timeoutMs = DL_PREPARATION_TIMEOUT_MS,
} = {}) {
	const rootElement = document?.documentElement;
	if (!rootElement || explicitEffectiveMode(boot) !== "dl") return null;
	const existing = activePreparations.get(document);
	if (existing) return existing;

	rootElement.classList.add(DL_PREPARING_CLASS);
	rootElement.setAttribute("aria-busy", "true");
	let finished = false;
	let timerId;
	const controller = {
		finish({ timedOut = false } = {}) {
			if (finished) return false;
			finished = true;
			if (!timedOut && timerId !== undefined && cancel) cancel(timerId);
			rootElement.classList.remove(DL_PREPARING_CLASS);
			rootElement.removeAttribute("aria-busy");
			activePreparations.delete(document);
			if (timedOut && warn) warn("DL navigation preparation timed out; showing the native Desk UI.");
			return true;
		},
	};
	activePreparations.set(document, controller);
	if (schedule) timerId = schedule(() => controller.finish({ timedOut: true }), timeoutMs);
	return controller;
}

function finishDLPreparation(document) {
	const controller = document ? activePreparations.get(document) : null;
	if (controller) return controller.finish();
	document?.documentElement?.classList.remove(DL_PREPARING_CLASS);
	document?.documentElement?.removeAttribute("aria-busy");
	return false;
}
```

Export both functions. Immediately after assigning `root.DeepLinkERPInterfaceMode`, call:

```js
interfaceMode.startDLPreparation({
	document: root.document,
	boot: root.frappe?.boot,
	schedule: root.setTimeout?.bind(root),
	cancel: root.clearTimeout?.bind(root),
	warn: root.console?.warn?.bind(root.console),
});
```

The explicit boot check is intentional: do not reuse `getModeState({})` for the early path because its normal fallback is DL, while first-paint preparation must not guess when boot data is absent.

- [ ] **Step 5: Run the focused and full interface-mode tests**

Run:

```bash
node --test --test-name-pattern="preparation|prepare classic|times out" tests/interface-mode.test.js
node --test tests/interface-mode.test.js
```

Expected: all focused tests and the full interface-mode suite PASS.

- [ ] **Step 6: Commit the preparation controller**

```bash
git add tests/interface-mode.test.js deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js
git commit -m "增加 DL 导航首屏准备态"
```

### Task 2: Complete preparation only after the real navigation is ready

**Files:**
- Modify: `tests/interface-mode.test.js:260-305`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_branding.js:528-646`

- [ ] **Step 1: Write the failing lifecycle-order test**

Add a source integration test that isolates `renderPersistentNavigation` and requires completion after native active-state accessibility is synchronized:

```js
test("finishes first-paint preparation only after the real navigation is synchronized", () => {
	const lifecycle = fs.readFileSync(
		path.join(__dirname, "..", "deeplinkerp_branding", "public", "js", "deeplinkerp_branding.js"),
		"utf8"
	);
	const start = lifecycle.indexOf("function renderPersistentNavigation()");
	const end = lifecycle.indexOf("function enhanceDesktopIcons()", start);
	const source = lifecycle.slice(start, end);

	assert.ok(start >= 0 && end > start);
	assert.match(source, /updateNativeLeafAccessibility\(nativeItems\)/);
	assert.match(source, /DeepLinkERPInterfaceMode\?\.finishDLPreparation\(document\)/);
	assert.ok(
		source.indexOf("updateNativeLeafAccessibility(nativeItems)") <
			source.indexOf("finishDLPreparation(document)")
	);
});
```

Extend the existing DL/classic lifecycle test with:

```js
assert.match(lifecycle, /function disableDLEnhancements\([\s\S]*finishDLPreparation\(document\)/);
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
node --test --test-name-pattern="first-paint preparation" tests/interface-mode.test.js
```

Expected: FAIL because the branding lifecycle does not yet finish preparation.

- [ ] **Step 3: Wire completion into existing success and classic paths**

At the end of `renderPersistentNavigation`, after `updateNativeLeafAccessibility(nativeItems)`, add:

```js
window.DeepLinkERPInterfaceMode?.finishDLPreparation(document);
return true;
```

At the end of `disableDLEnhancements`, add:

```js
window.DeepLinkERPInterfaceMode?.finishDLPreparation(document);
```

Do not finish on any early return from `renderPersistentNavigation`; the watchdog owns that failure path. Do not add a new render loop or another timer.

- [ ] **Step 4: Run lifecycle and full JavaScript tests**

Run:

```bash
node --test --test-name-pattern="first-paint preparation|gates DL navigation" tests/interface-mode.test.js
node --test tests/*.test.js
```

Expected: all tests PASS.

- [ ] **Step 5: Commit lifecycle wiring**

```bash
git add tests/interface-mode.test.js deeplinkerp_branding/public/js/deeplinkerp_branding.js
git commit -m "在 DL 导航就绪后结束首屏准备态"
```

### Task 3: Apply the approved A-palette and thin scrollbar

**Files:**
- Modify: `tests/navigation-model.test.js:1160-1240`
- Modify: `deeplinkerp_branding/public/css/deeplinkerp_navigation.css:1-426`

- [ ] **Step 1: Write failing CSS contract assertions**

Update the existing chevron assertion from `#c7d4e3` to `#d0dbe6`, then add one focused test:

```js
test("uses the approved readable palette, pending shell, and thin transparent scrollbar", () => {
	const stylesheet = fs.readFileSync(
		path.join(__dirname, "..", "deeplinkerp_branding", "public", "css", "deeplinkerp_navigation.css"),
		"utf8"
	);

	assert.match(stylesheet, /html\.dlp-interface-mode-dl-pending\s+body::before/);
	assert.match(stylesheet, /html\.dlp-interface-mode-dl-pending\s+body::after/);
	assert.match(stylesheet, /html\.dlp-interface-mode-dl-pending[\s\S]*\.desktop-container[\s\S]*visibility:\s*hidden\s*!important/);
	assert.match(stylesheet, /\.dlp-mes-navigation__row[^{]*\{[^}]*color:\s*#c1d0df/i);
	assert.match(stylesheet, /\.sidebar-items\s+\.item-anchor[^{]*\{[^}]*color:\s*#afbfce/i);
	assert.match(stylesheet, /\.standard-items-sections[\s\S]*#9fb4c8/i);
	assert.match(stylesheet, /\.avatar-name-email[\s\S]*#d8e3ed/i);
	assert.match(stylesheet, /scrollbar-width:\s*thin/);
	assert.match(stylesheet, /scrollbar-color:[^;]*transparent/);
	assert.match(stylesheet, /\.body-sidebar-top::?-webkit-scrollbar\s*\{[^}]*width:\s*6px/i);
	assert.match(stylesheet, /\.body-sidebar-top::?-webkit-scrollbar-track\s*\{[^}]*background:\s*transparent/i);
});
```

- [ ] **Step 2: Run the focused CSS tests and verify RED**

Run:

```bash
node --test --test-name-pattern="readable palette|dark shell" tests/navigation-model.test.js
```

Expected: FAIL on pending shell, palette, and scrollbar assertions.

- [ ] **Step 3: Add the non-interactive DL first-paint shell**

Add the pending styles before the existing `body.dlp-mes-navigation-enabled` block:

```css
html.dlp-interface-mode-dl-pending body {
	--sidebar-width: 220px;
	overflow-x: hidden;
}

html.dlp-interface-mode-dl-pending body::before {
	position: fixed;
	inset: 0 auto 0 0;
	z-index: 1100;
	width: var(--sidebar-width);
	background: #001529;
	content: "";
	pointer-events: none;
}

html.dlp-interface-mode-dl-pending body::after {
	position: fixed;
	top: 14px;
	left: 12px;
	z-index: 1101;
	display: flex;
	align-items: center;
	height: 28px;
	padding-left: 38px;
	background: url("/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6") left center / 28px 28px no-repeat;
	color: #fff;
	content: "DeepLinkERP";
	font-size: 15px;
	font-weight: 600;
	line-height: 28px;
	pointer-events: none;
}

html.dlp-interface-mode-dl-pending body .desktop-container {
	visibility: hidden !important;
}
```

In the existing mobile media query, size the pseudo-shell with the same existing mobile limit:

```css
html.dlp-interface-mode-dl-pending body::before {
	width: min(var(--sidebar-width), 84vw);
}
```

- [ ] **Step 4: Apply the approved scoped color rules**

Change the base DL sidebar and rows to the approved palette:

```css
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar {
	color: #c1d0df;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .dlp-mes-navigation__row {
	color: #c1d0df;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .dlp-mes-navigation__chevron {
	color: #d0dbe6;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .sidebar-items .item-anchor {
	color: #afbfce;
}
```

Add precise Frappe utility and footer overrides without affecting page content:

```css
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .standard-items-sections .item-anchor,
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .standard-items-sections .sidebar-item-label,
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .standard-items-sections .sidebar-item-icon,
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .standard-items-sections .sidebar-item-suffix {
	color: #9fb4c8 !important;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-bottom,
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-bottom .onboarding-sidebar,
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-bottom .onboarding-sidebar span,
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-bottom .onboarding-sidebar svg,
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .sidebar-user-button .text-secondary {
	color: #9fb4c8 !important;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .sidebar-user-button .avatar-name-email > :first-child {
	color: #d8e3ed !important;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .collapse-sidebar-link {
	color: #d0dbe6;
}
```

Keep open and active rules white, keep active background `#1677ff`, and keep nested background `#000f1c`.

- [ ] **Step 5: Style the actual scrolling element for Firefox and Chromium/WebKit**

Extend the existing `.body-sidebar-top` rule:

```css
scrollbar-width: thin;
scrollbar-color: rgba(132, 157, 181, 0.68) transparent;
```

Add:

```css
body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-top::-webkit-scrollbar {
	width: 6px;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-top::-webkit-scrollbar-track {
	background: transparent;
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-top::-webkit-scrollbar-thumb {
	border-radius: 999px;
	background: rgba(132, 157, 181, 0.68);
}

body.dlp-mes-navigation-enabled .body-sidebar.dlp-mes-navigation-sidebar .body-sidebar-top::-webkit-scrollbar-thumb:hover {
	background: rgba(178, 199, 219, 0.82);
}
```

- [ ] **Step 6: Run focused and full navigation tests**

Run:

```bash
node --test --test-name-pattern="readable palette|dark shell" tests/navigation-model.test.js
node --test tests/navigation-model.test.js
```

Expected: all tests PASS.

- [ ] **Step 7: Commit visual changes**

```bash
git add tests/navigation-model.test.js deeplinkerp_branding/public/css/deeplinkerp_navigation.css
git commit -m "提亮 DL 侧栏并优化滚动条"
```

### Task 4: Bust changed assets and run the complete automated verification

**Files:**
- Modify: `tests/navigation-model.test.js:780-805`
- Modify: `deeplinkerp_branding/hooks.py:27-31`

- [ ] **Step 1: Write the failing asset-version expectations**

Change the existing hook assertions to require:

```js
assert.match(hooks, /deeplinkerp_navigation\.css\?v=0\.0\.9/);
assert.match(hooks, /deeplinkerp_interface_mode\.js\?v=0\.0\.3/);
assert.match(hooks, /deeplinkerp_branding\.js\?v=0\.0\.26/);
```

- [ ] **Step 2: Run the asset-order test and verify RED**

Run:

```bash
node --test --test-name-pattern="keeps the Desk assets separate" tests/navigation-model.test.js
```

Expected: FAIL because hooks still reference the previous versions.

- [ ] **Step 3: Bump only the changed Desk assets**

Set `hooks.py` to:

```python
app_include_css = "/assets/deeplinkerp_branding/css/deeplinkerp_navigation.css?v=0.0.9"
app_include_js = [
	"/assets/deeplinkerp_branding/js/deeplinkerp_navigation.js?v=0.0.18",
	"/assets/deeplinkerp_branding/js/deeplinkerp_interface_mode.js?v=0.0.3",
	"/assets/deeplinkerp_branding/js/deeplinkerp_branding.js?v=0.0.26",
]
```

Do not bump `deeplinkerp_navigation.js`; its model is unchanged.

- [ ] **Step 4: Run all static and automated tests**

Run:

```bash
node --check deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
node --test tests/*.test.js
python3 -m unittest -v tests.test_interface_mode tests.test_boot_branding tests.test_interface_mode_metadata
python3 -m compileall -q deeplinkerp_branding
git diff --check
```

Expected: both JavaScript syntax checks succeed, all JavaScript tests pass, 18 Python tests pass, compilation succeeds, and `git diff --check` prints nothing.

- [ ] **Step 5: Commit the cache-busting versions**

```bash
git add tests/navigation-model.test.js deeplinkerp_branding/hooks.py
git commit -m "更新 DL 导航首屏资源版本"
```

### Task 5: Rebuild and accept the local preview

**Files:**
- No production file changes expected.

- [ ] **Step 1: Build the existing preview image from the worktree**

Run:

```bash
docker build \
	-f /tmp/Dockerfile.deeplinkerp-mes-nav \
	-t overseas-cost-local:mes-nav-preview \
	/Users/smk/.codex/worktrees/mes-navigation/DeepLinkERP
```

Expected: the image builds successfully and `bench build --app deeplinkerp_branding` completes.

- [ ] **Step 2: Recreate the six application services and clear the local site cache**

Run:

```bash
docker compose -p overseas-cost-local \
	-f /Users/smk/Documents/ChatGPT/综合成本计算系统-local-env/frappe_docker/pwd.yml \
	-f /Users/smk/Documents/ChatGPT/综合成本计算系统-local-env/frappe_docker/compose.local.yaml \
	-f /tmp/compose.deeplinkerp-mes-nav.yaml \
	up -d --force-recreate backend frontend websocket queue-short queue-long scheduler

docker compose -p overseas-cost-local \
	-f /Users/smk/Documents/ChatGPT/综合成本计算系统-local-env/frappe_docker/pwd.yml \
	-f /Users/smk/Documents/ChatGPT/综合成本计算系统-local-env/frappe_docker/compose.local.yaml \
	-f /tmp/compose.deeplinkerp-mes-nav.yaml \
	exec -T backend bench --site frontend clear-cache
```

Expected: all six services are running on `overseas-cost-local:mes-nav-preview`, cache clearing succeeds, and `curl -I http://localhost:64115/login` returns an HTTP response.

- [ ] **Step 3: Verify DL first paint and final computed styles in Chromium**

Hard-refresh `http://localhost:64115/desk/purchase-order` with DL mode active and verify:

- the first visible navigation surface is the dark DL brand shell;
- no classic large colored icon or centered DLP desktop logo is visible;
- one `.dlp-mes-navigation` exists after readiness;
- `html` no longer contains `dlp-interface-mode-dl-pending` and has no `aria-busy`;
- Purchase is expanded and Purchase Order has `active-sidebar` plus `aria-current="page"`;
- `.body-sidebar-top` computes to a transparent scrollbar track and the Chromium scrollbar width rule is 6px;
- root label, utility label, nested link, Getting Started, username, email, chevron, and collapse button compute to the approved readable palette.

- [ ] **Step 4: Verify compatibility paths**

In the same local browser:

- refresh `/desk/manufacturing`, `/desk/china-finance`, and `/desk/ai-chat` and confirm the classic grid never flashes;
- switch to Classic Mode, refresh `/desk/purchase-order`, and confirm no pending DL shell appears;
- switch back to DL Mode and confirm the shell-to-navigation handoff returns;
- check desktop, tablet, and phone widths for no horizontal overflow and correct mobile overlay/collapse behavior;
- exercise route clicks, refresh, back, and forward to confirm active highlights and expanded roots still synchronize.

- [ ] **Step 5: Run final evidence checks and prepare the completion report**

Run:

```bash
node --test tests/*.test.js
python3 -m unittest -v tests.test_interface_mode tests.test_boot_branding tests.test_interface_mode_metadata
git diff --check
git status --short
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | rg '^overseas-cost-local-(backend|frontend|websocket|queue-short|queue-long|scheduler)-1'
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:64115/login
```

Expected: all tests pass, the worktree is clean after implementation commits, all six containers use `overseas-cost-local:mes-nav-preview`, and the HTTP check succeeds.

Report separately:

- 新增: preparation controller and its tests;
- 修改: lifecycle completion, scoped colors, scrollbar, and asset versions;
- 删除: none;
- 测试变化: new test count, total JavaScript/Python pass counts, and browser paths checked;
- 兼容保留: classic mode, permissions, menu data, routing, mobile collapse, user ordering, and active state;
- 未处理技术债: only issues actually observed outside this approved scope.
