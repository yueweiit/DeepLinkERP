# Navigation Ownership and MES Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correctly attach Frappe's live child menu after cross-workspace navigation, keep the DL brand header stable, and visually distinguish level-one modules from level-two menu regions.

**Architecture:** Extend the existing pure navigation model with an authorized active-leaf ownership resolver. Pass a small descriptor from the live Frappe sidebar into that model, keep reusing the existing native sidebar node, and scope all visual changes to the current DL navigation CSS. Do not add menu data, route tables, storage, APIs, or lifecycle listeners.

**Tech Stack:** Frappe / ERPNext v16, vanilla JavaScript, CSS, Node.js `node:test`, Docker Compose browser preview.

---

## File map

- Modify `tests/navigation-model.test.js`: regression coverage for stale parent titles, ambiguous leaf names, stable brand header, and level colors.
- Modify `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`: normalize active leaf identity and resolve its authorized workspace owner before stale title fallback.
- Modify `deeplinkerp_branding/public/js/deeplinkerp_branding.js`: collect the live active leaf descriptor and keep a dedicated DL brand header.
- Modify `deeplinkerp_branding/public/css/deeplinkerp_navigation.css`: separate level-one and level-two background colors and hide the mutable native header only in DL mode.
- Modify `deeplinkerp_branding/hooks.py`: increment asset query versions so the local preview loads the fix.

### Task 1: Lock the cross-workspace ownership regression with tests

**Files:**

- Modify: `tests/navigation-model.test.js`

- [ ] **Step 1: Write a failing model test**

Add a case with `currentSidebar: "Buying"`, `route: "/desk/bom"`, and `nativeActiveItem: { label: "物料清单", href: "/desk/bom" }`. Provide authorized Buying and Manufacturing sidebars and assert:

```javascript
assert.equal(model.activeItem.label, "Manufacturing");
assert.equal(model.nativeHostKey, model.activeItem.key);
assert.equal(model.activeItem.isOpen, true);
```

- [ ] **Step 2: Add ambiguity and lifecycle contract tests**

Create two workspace sidebars containing the same translated label and different `link_to` values. Assert that the current href selects the matching owner. Assert `deeplinkerp_branding.js` passes both active label and href to `buildNavigationModel`, always creates the dedicated brand entry, and hides no header outside DL scope.

- [ ] **Step 3: Add CSS contract tests**

Read `deeplinkerp_navigation.css` and assert the top-level row uses `#001b33`, the child branch uses `#000f1c`, and `.active-sidebar` remains `#1677ff`.

- [ ] **Step 4: Run the focused suite and confirm RED**

```bash
node --test tests/navigation-model.test.js
```

Expected: the stale Buying title still owns the native node, the dedicated brand contract is absent, and hierarchy color assertions fail.

### Task 2: Resolve the live active leaf to its authorized module

**Files:**

- Modify: `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`
- Modify: `deeplinkerp_branding/public/js/deeplinkerp_branding.js`

- [ ] **Step 1: Add pure active-leaf helpers**

Add normalization for sidebar leaf labels and hrefs, recursively inspect each authorized sidebar's `items` / `nested_items`, and score matches in this order: exact normalized href/link target plus label, exact href/link target, then unique label. Return an empty path when no authorized owner is unambiguous.

- [ ] **Step 2: Change model authority order**

In `buildNavigationModel`, resolve in this exact order:

```javascript
query sidebar -> exact top-level route -> authorized native leaf owner -> currentSidebar fallback
```

Use the resolved path for `activeItem`, `nativeHostKey`, automatic open state, and parent active styling.

- [ ] **Step 3: Pass the live active leaf descriptor**

In `renderPersistentNavigation`, read the active `.standard-sidebar-item` label and its `.item-anchor[href]`. Pass `{ label, href }` as `nativeActiveItem`; keep `nativeLeafSelected` for existing self-active behavior.

- [ ] **Step 4: Run the focused suite and confirm GREEN**

```bash
node --test tests/navigation-model.test.js
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
```

Expected: all navigation model tests pass and both JavaScript files parse.

- [ ] **Step 5: Commit the ownership fix**

```bash
git add tests/navigation-model.test.js \
  deeplinkerp_branding/public/js/deeplinkerp_navigation.js \
  deeplinkerp_branding/public/js/deeplinkerp_branding.js
git commit -m "修复跨模块导航归属"
```

### Task 3: Stabilize the brand header and apply MES hierarchy colors

**Files:**

- Modify: `deeplinkerp_branding/public/js/deeplinkerp_branding.js`
- Modify: `deeplinkerp_branding/public/css/deeplinkerp_navigation.css`
- Modify: `deeplinkerp_branding/hooks.py`
- Test: `tests/navigation-model.test.js`

- [ ] **Step 1: Render one dedicated DL brand header**

Make `ensureBrandHeader` idempotently create/update `.dlp-mes-navigation__brand-fallback` even when Frappe's native header exists. Keep its href `/desk`, logo and `DeepLinkERP` label. In `disableDLEnhancements`, remove the dedicated entry so classic mode reveals the untouched native header.

- [ ] **Step 2: Scope header and hierarchy styles to DL mode**

Hide `.sidebar-header` only below `body.dlp-mes-navigation-enabled`. Apply:

```css
.dlp-mes-navigation > .dlp-mes-navigation__group > .dlp-mes-navigation__row {
  background: #001b33;
}

.dlp-mes-navigation > .dlp-mes-navigation__group > .dlp-mes-navigation__children {
  background: #000f1c;
}

.sidebar-items .active-sidebar {
  background: #1677ff;
}
```

Keep hover, focus, collapsed rail, mobile overlay, nested indentation, and active selectors at equal or higher specificity.

- [ ] **Step 3: Increment asset versions**

Increment the navigation CSS, navigation model JS, and branding lifecycle JS query versions in `hooks.py`. Do not change the interface-mode helper when its content is unchanged.

- [ ] **Step 4: Run all local automated checks**

```bash
node --test tests/*.test.js
python3 -m unittest discover -s tests -v
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
python3 -m compileall -q deeplinkerp_branding tests
git diff --check
```

Expected: all tests and syntax checks pass with no whitespace errors.

- [ ] **Step 5: Commit the visual hierarchy**

```bash
git add tests/navigation-model.test.js \
  deeplinkerp_branding/public/js/deeplinkerp_branding.js \
  deeplinkerp_branding/public/css/deeplinkerp_navigation.css \
  deeplinkerp_branding/hooks.py
git commit -m "区分导航层级并固定品牌入口"
```

### Task 4: Rebuild and verify the real browser flow

**Files:**

- No source changes expected.

- [ ] **Step 1: Build and recreate the local preview**

From the established local Docker context, build `overseas-cost-local:mes-nav-preview`, recreate backend/frontend/websocket/worker/scheduler containers, and clear the site and website caches.

- [ ] **Step 2: Verify the exact reported route race**

At `http://localhost:64115/desk/buying`:

1. Expand Buying.
2. Expand Manufacturing.
3. Click the Manufacturing child “物料清单”.
4. Assert the URL is `/desk/bom`.
5. Assert the tagged live native node is a descendant of Manufacturing, contains the active BOM row, and is not below Buying.
6. Refresh and assert Manufacturing alone auto-opens with BOM still active.

- [ ] **Step 3: Verify computed colors and brand**

Assert the computed backgrounds are `rgb(0, 27, 51)`, `rgb(0, 15, 28)`, and `rgb(22, 119, 255)` for a level-one row, its level-two branch, and the selected child. Assert exactly one visible DeepLinkERP brand entry and no visible route-mutated native header.

- [ ] **Step 4: Verify retained behavior**

Check a 375px viewport for no horizontal overflow and child-navigation close behavior. Switch once to classic mode and back to DL to confirm the native header is restored in classic and the dedicated brand returns only in DL.

- [ ] **Step 5: Record delivery evidence**

Capture final test counts, browser checks, `git diff --stat`, commit list, compatibility retained, and any remaining Frappe DOM dependency in the completion report. Do not merge, push, or deploy.
