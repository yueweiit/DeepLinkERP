# Workbench UI Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the remediation form use its available width, pin the detail header flush to the scroll viewport, and remove the unused current-source dialog end to end.

**Architecture:** Keep the existing drawer and sticky header, changing only the CSS declarations that cause the two visual defects. Remove the current-source feature vertically across its UI, event handler, dialog methods, dedicated API, CSS, and obsolete tests while preserving shared source services.

**Tech Stack:** Frappe page JavaScript, CSS, Python whitelisted APIs, pytest, Node-based frontend harness, generated workbench assets.

---

### Task 1: Add failing UI and deletion contracts

**Files:**
- Modify: `overseas_costing/tests/test_review_workbench_ui.py`
- Modify: `overseas_costing/tests/test_detail_erp_header_ui.py`
- Modify: `overseas_costing/tests/test_settlement_frontend.py`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`

- [ ] Add assertions that the remediation card label is block-level/full-width and the textarea uses `box-sizing: border-box`.
- [ ] Change the sticky-header assertion to require `top: 0` and reject `top: 12px`.
- [ ] Add a vertical deletion contract asserting that `mf-show-sources`, `openMaterialFeeSourcesDialog`, `renderMaterialFeeSourcesContent`, `list_current_source_documents`, and the dedicated source-list CSS are absent.
- [ ] Remove obsolete test expectations and test stubs that require the deleted source dialog.
- [ ] Run the three targeted tests and confirm they fail only because the requested behavior is not implemented.

### Task 2: Apply the minimal production changes

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/52-review-communication.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/45-detail-page.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/48-material-fee-workspace.css`
- Modify: `overseas_costing/api/packing_api.py`

- [ ] Add `display: block; width: 100%` to the direct draft-card label and `display: block; box-sizing: border-box` to its textarea.
- [ ] Set `.ocw-detail-header` to `top: 0`.
- [ ] Delete the source button, delegated click binding, dialog content renderer, dialog opener, dedicated source-list CSS, and `list_current_source_documents` API.
- [ ] Run the targeted tests and confirm they pass.

### Task 3: Rebuild and verify generated assets

**Files:**
- Modify (generated): `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Modify (generated): `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`

- [ ] Run `python3 overseas_costing/scripts/build_workbench_assets.py`.
- [ ] Run it again and require `changed: []`.
- [ ] Run focused and affected tests, JavaScript syntax checks, Python compile checks, and `git diff --check`.
- [ ] Inspect the final diff and report additions, modifications, deletions, test-count changes, parameterization changes, duplicate logic, and remaining debt.
