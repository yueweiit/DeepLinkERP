# Single Trial Error Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show only the workbench business error dialog when a trial calculation request fails.

**Architecture:** Reuse the workbench's existing opt-in direct-AJAX transport for endpoints whose errors are rendered locally. Add only the trial calculation endpoint to the allowlist and opt that call into the transport; all other requests keep the default Frappe behavior.

**Tech Stack:** ERPNext/Frappe client JavaScript, jQuery AJAX, pytest-driven Node harness, generated workbench assets.

---

### Task 1: Reproduce the duplicate-dialog transport path

**Files:**
- Modify: `overseas_costing/tests/test_material_ai_error_ui.py`
- Modify: `overseas_costing/tests/test_review_workbench_ui.py`

- [ ] **Step 1: Add a failing transport test**

Extend the direct-AJAX transport parameterization to include `overseas_costing.api.calculate.recalculate_batch`. Assert `frappe.call` is not used, `$.ajax` receives the method URL and request data, and the exact failure object is rethrown.

- [ ] **Step 2: Add a failing trial-flow test**

Capture the four arguments passed to `view.call()` from `recalculate()`. Assert the trial request uses `freeze === true`, `options.inlineErrors === true`, and a rejected request produces exactly one `showError()` call.

- [ ] **Step 3: Run the two focused tests and verify RED**

Run:

```bash
python3 -m pytest \
  overseas_costing/tests/test_material_ai_error_ui.py::test_inline_error_transport_uses_local_ajax_and_preserves_failure_response \
  overseas_costing/tests/test_review_workbench_ui.py::test_failed_recalculation_uses_single_locally_handled_error -q
```

Expected: both tests fail because trial calculation is not yet opted into the locally handled transport.

### Task 2: Opt trial calculation into local error handling

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/20-data-filters.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/30-calculation-erp.js`
- Regenerate: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Regenerate: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`

- [ ] **Step 1: Extend the explicit direct-AJAX allowlist**

Rename the local boolean to describe locally handled errors and include:

```javascript
"overseas_costing.api.calculate.recalculate_batch"
```

Continue using direct AJAX only when `options.inlineErrors === true`.

- [ ] **Step 2: Opt the trial request into that transport**

Pass the existing fourth options argument from `recalculate()`:

```javascript
true,
{ inlineErrors: true }
```

- [ ] **Step 3: Run the focused tests and verify GREEN**

Run the command from Task 1. Expected: both tests pass and the failure count is zero.

- [ ] **Step 4: Rebuild generated assets twice**

Run:

```bash
python3 overseas_costing/scripts/build_workbench_assets.py
python3 overseas_costing/scripts/build_workbench_assets.py
```

Expected: the first build updates both JavaScript mirrors; the second reports `"changed": []`.

### Task 3: Verify and release

**Files:**
- Verify all files changed since production commit `3bc2d4d9688fe2324597dc05368274a7dd65e910`.

- [ ] **Step 1: Run syntax and focused frontend tests**

```bash
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
python3 -m pytest overseas_costing/tests/test_material_ai_error_ui.py overseas_costing/tests/test_review_workbench_ui.py -q
```

- [ ] **Step 2: Run affected and full suites**

```bash
python3 overseas_costing/scripts/run_affected_tests.py 3bc2d4d9688fe2324597dc05368274a7dd65e910
python3 -m pytest
git diff --check
```

Expected: zero failures; only the 13 explicitly skipped PostgreSQL integration tests may remain skipped.

- [ ] **Step 3: Commit and push both release branches**

Commit the design, plan, tests, source parts, and generated mirrors, then push the exact HEAD to `origin/overseas_costing` and `production/overseas_costing` after confirming both remotes still point to `3bc2d4d9688fe2324597dc05368274a7dd65e910`.

- [ ] **Step 4: Monitor and accept production**

Wait for the real `yueweiit/DeepLinkERP` deployment workflow to complete successfully. On a batch with missing shipment values, trigger trial once and verify only the business `操作失败` dialog is visible, with no simultaneous or subsequent `服务器错误` dialog and no saved trial result.

