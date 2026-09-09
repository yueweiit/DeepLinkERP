# Remove Workbench Summary Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the redundant summary-card row from all three workbench tasks without changing filtering, classification, or business data.

**Architecture:** Remove the summary section from the workbench shell and remove its dedicated renderer and click bindings. Keep URL parsing, select-based review filtering, summary API loading, and server-side classification unchanged for compatibility.

**Tech Stack:** Frappe Desk page, JavaScript, CSS, pytest, Node.js syntax checks, generated workbench assets.

---

### Task 1: Lock the absence of summary cards with a frontend regression test

**Files:**
- Modify: `overseas_costing/tests/test_review_workbench_ui.py`

- [x] **Step 1: Replace the obsolete card-rendering test with an absence test**

```python
def test_workbench_shell_has_no_summary_card_row_for_any_task():
    source = (PARTS / '35-workbench-view.js').read_text(encoding='utf-8')
    assert 'data-area="exception-summary"' not in source
    assert 'ocw-summary-card' not in source
    assert 'renderExceptionSummary' not in source
    assert "data-action='set-review-filter'" not in source
    assert "data-action='set-issue'" not in source
```

- [x] **Step 2: Run the regression test and confirm it fails against the existing row**

Run: `python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py::test_workbench_shell_has_no_summary_card_row_for_any_task`

Expected: FAIL because the current shell and renderer still contain the summary row.

### Task 2: Remove the row, renderer, bindings, and dedicated styles

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/35-workbench-view.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/25-workbench-redesign.css`
- Test: `overseas_costing/tests/test_review_workbench_ui.py`

- [x] **Step 1: Remove the summary section and card-only JavaScript**

Delete this shell element:

```html
<section class="ocw-exception-summary" data-area="exception-summary" aria-label="异常摘要"></section>
```

Delete the two click bindings whose selectors are `data-action='set-review-filter'` and `data-action='set-issue'`. Keep `setReviewFilter()` because the “核对状态” select still uses it. Remove the `this.renderExceptionSummary();` call from `renderWorkbench()` and delete the complete `renderExceptionSummary()` method.

- [x] **Step 2: Remove card-only CSS**

Delete the `.ocw-exception-summary`, `.ocw-summary-card`, `.ocw-summary-card strong`, `.ocw-summary-card small`, `.ocw-summary-card.is-active`, and four tone rules from `25-workbench-redesign.css`. Delete its responsive `.ocw-exception-summary` grid override. Do not change `.ocw-profit-summary-card`, which belongs to a different detail view.

- [x] **Step 3: Run focused frontend tests**

Run: `python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_workbench_frontend_state.py`

Expected: all tests PASS; task switching, URL state, filters, and request-race coverage remain green.

- [x] **Step 4: Commit source and test changes**

```bash
git add overseas_costing/tests/test_review_workbench_ui.py \
  overseas_costing/page/overseas_cost_workbench/parts/35-workbench-view.js \
  overseas_costing/page/overseas_cost_workbench/parts/25-workbench-redesign.css
git commit -m "ui: remove redundant workbench summary cards"
```

### Task 3: Regenerate and verify deployable assets

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`

- [x] **Step 1: Generate both asset copies from source parts**

Run: `python3 overseas_costing/scripts/build_workbench_assets.py`

Expected: the build reports matching JavaScript and CSS digests for both output locations.

- [x] **Step 2: Run complete verification**

Run: `python3 -m pytest -q`

Run: `python3 -m compileall -q overseas_costing`

Run: `node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`

Run: `node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`

Run: `git diff --check`

Expected: all tests and syntax checks PASS with no whitespace errors.

- [x] **Step 3: Commit generated assets**

```bash
git add overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js \
  overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css \
  overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js \
  overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
git commit -m "build: regenerate workbench assets without summary cards"
```

### Task 4: Deploy and perform read-only production acceptance

**Files:**
- No application source changes.

- [x] **Step 1: Push the verified branch through existing GitHub Actions**

Run: `git push production HEAD:overseas_costing`

Run: `git push origin HEAD:overseas_costing`

Expected: DeepLinkERP workflow tests and deployment succeed; mirror workflow tests succeed without a second production deployment.

- [x] **Step 2: Check all three production task tabs in an authenticated browser**

Open “待处理”, “成本核对”, and “ERP 队列”. Confirm each task tab is followed directly by the search panel, no summary cards or empty summary space remain, and switching tasks changes only the list/filter context.

- [x] **Step 3: Confirm no business-data mutation**

Use read-only API/browser checks only. Do not click recalculate, confirm, or ERP push actions. Confirm this release changed only frontend files and documentation; no batch amount, item, fee, or allocation record is written.
