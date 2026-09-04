# Workspace Sidebar Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the “海外成本核算” workspace header reuse the exact authorized blue SVG shown in the ERP module rail.

**Architecture:** Add one page-scoped synchronization helper in the workbench bootstrap. It reads the matching entry from `frappe.boot.desktop_icons`, swaps only the current workspace header icon, snapshots the original markup, and restores it when the page is hidden.

**Tech Stack:** Frappe Desk JavaScript, jQuery, pytest static asset regression tests.

---

### Task 1: Synchronize and restore the workspace header icon

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/00-bootstrap.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/10-shell.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/20-desk-layout.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Test: `overseas_costing/tests/test_workbench_frontend_state.py`

- [ ] **Step 1: Write the failing regression test**

Add:

```python
def test_workspace_header_reuses_authorized_desktop_icon_and_restores_original() -> None:
    bootstrap = (PARTS / "00-bootstrap.js").read_text(encoding="utf-8")
    shell = (PARTS / "10-shell.js").read_text(encoding="utf-8")

    assert "function syncWorkspaceSidebarHeaderIcon" in bootstrap
    assert "frappe.boot.desktop_icons" in bootstrap
    assert ".body-sidebar-container .sidebar-header > .sidebar-item-icon" in bootstrap
    assert "desktopIcon.logo_url || desktopIcon.icon_image" in bootstrap
    assert "ocw-workspace-sidebar-icon" in bootstrap
    assert "_workspaceSidebarIconSnapshot" in shell
    assert ".ocw-workspace-sidebar-icon" in (PARTS / "20-desk-layout.css").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py
```

Expected: the new test fails because the synchronization helper is absent.

- [ ] **Step 3: Implement the minimal page-scoped helper**

Implement:

```javascript
function syncWorkspaceSidebarHeaderIcon(workbench) {
  const desktopIcon = (frappe.boot.desktop_icons || []).find(
    (icon) => icon && icon.hidden != 1 && icon.label === "海外成本核算"
  );
  const iconSource = desktopIcon && (desktopIcon.logo_url || desktopIcon.icon_image);
  const $target = $(".body-sidebar-container .sidebar-header > .sidebar-item-icon").first();
  if (!iconSource || !$target.length) return;
  if (!workbench._workspaceSidebarIconSnapshot) {
    workbench._workspaceSidebarIconSnapshot = { element: $target.get(0), html: $target.html() };
  }
  $target.html($("<img>", {
    class: "ocw-workspace-sidebar-icon",
    src: iconSource,
    alt: "",
  }));
}
```

Call it during initial load, delayed shell readiness, and subsequent page shows.

Add the scoped image sizing rule:

```css
.body-sidebar-container .sidebar-header > .sidebar-item-icon > .ocw-workspace-sidebar-icon {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
```

Extend `restoreDeskChrome` with:

```javascript
if (this._workspaceSidebarIconSnapshot) {
  const snapshot = this._workspaceSidebarIconSnapshot;
  if (snapshot.element && snapshot.element.isConnected) {
    $(snapshot.element).html(snapshot.html);
  }
  this._workspaceSidebarIconSnapshot = null;
}
```

- [ ] **Step 4: Synchronize generated assets and verify GREEN**

Apply the same generated JavaScript change to both shipped workbench files, then run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q overseas_costing
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
git diff --check
```

Expected: all tests pass, both JavaScript files parse, and the diff is clean.

- [ ] **Step 5: Deploy and verify production DOM**

Commit and push the release branches. After CI/CD succeeds, open the production workbench and verify that the workspace header image `src` equals the active “海外成本核算” module-rail image `src`, while both sidebars and the workspace collapse button remain visible.
