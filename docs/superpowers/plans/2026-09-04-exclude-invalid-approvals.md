# Exclude Invalid DingTalk Approvals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude revoked, terminated, cancelled, rejected, denied, or refused DingTalk approvals from imports and costing while retaining read-only audit history.

**Architecture:** Introduce one backward-compatible approval-decision helper that combines DingTalk process `status` and decision `result`. Feed its effective state through logistics summaries, purchase summaries, workbench filtering, approval-detail responses, and the existing PostgreSQL-only refresh path; keep invalid records for traceability instead of deleting them.

**Tech Stack:** Python 3.12, Frappe/ERPNext, PostgreSQL approval views, MariaDB Frappe documents, JavaScript/jQuery, pytest.

---

### Task 1: Resolve status and result through one decision helper

**Files:**
- Modify: `overseas_costing/scripts/import_oa_logistics.py:80-105,2976-3010,3030-3060,3590-3625`
- Test: `overseas_costing/tests/test_dingtalk.py`

- [ ] **Step 1: Write failing decision tests**

Add tests proving that `COMPLETED + refuse` and `TERMINATED + agree` are excluded, `COMPLETED + agree` is completed, and `RUNNING + agree` stays running:

```python
def test_approval_decision_combines_process_status_and_result() -> None:
    assert resolve_approval_decision("COMPLETED", "refuse") == {
        "process_status": "COMPLETED",
        "approval_result": "refuse",
        "effective_status": "REJECTED",
        "excluded": True,
    }
    assert resolve_approval_decision("TERMINATED", "agree")["excluded"] is True
    assert resolve_approval_decision("COMPLETED", "agree")["effective_status"] == "COMPLETED"
    assert resolve_approval_decision("RUNNING", "agree")["effective_status"] == "RUNNING"
    assert is_completed_approval_status("COMPLETED", result="refuse") is False
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_dingtalk.py -k approval_decision
```

Expected: FAIL because `resolve_approval_decision` and the `result` argument do not exist.

- [ ] **Step 3: Implement the minimal decision helper**

Add `INVALID_APPROVAL_RESULTS` and this public helper:

```python
def resolve_approval_decision(status: str | None, result: str | None = None) -> dict:
    process_status = _clean(status)
    approval_result = _clean(result)
    normalized_result = approval_result.upper()
    rejected = any(token in normalized_result for token in INVALID_APPROVAL_RESULTS)
    status_excluded = is_hidden_approval_status(process_status)
    return {
        "process_status": process_status,
        "approval_result": approval_result,
        "effective_status": "REJECTED" if rejected else process_status or approval_result,
        "excluded": bool(rejected or status_excluded),
    }
```

Extend `is_hidden_approval_status` and `is_completed_approval_status` with an optional `result` argument without breaking existing callers. Update both logistics and purchase summaries to return `process_status`, `approval_result`, `effective_status`, `excluded`, and use `effective_status` as `approval_status`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_dingtalk.py -k 'approval_decision or completed_approval_status or revoked_approval'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add overseas_costing/scripts/import_oa_logistics.py overseas_costing/tests/test_dingtalk.py
git commit -m "fix: combine DingTalk status and result"
```

### Task 2: Exclude invalid purchase approvals from every write path

**Files:**
- Modify: `overseas_costing/services/import_service.py:4920-5000`
- Modify: `overseas_costing/scripts/import_oa_logistics.py:4043-4070,4380-4475`
- Test: `overseas_costing/tests/test_import_service.py`
- Test: `overseas_costing/tests/test_dingtalk.py`

- [ ] **Step 1: Write failing purchase-filter tests**

Add one preview test with a valid `COMPLETED + agree` summary and an invalid `COMPLETED + refuse` summary. Assert that `purchase_summaries` retains both for audit, while `mapped_preview_items` and `mapped_purchase_row_count` contain only the valid approval. Add a sync test asserting the fallback apply function is not called when every summary is excluded.

```python
assert result["purchase_summary_count"] == 2
assert result["excluded_purchase_summary_count"] == 1
assert [row["source_instance_id"] for row in result["mapped_preview_items"]] == ["PROC-VALID"]
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_import_service.py overseas_costing/tests/test_dingtalk.py -k 'excluded_purchase or refuses_purchase'
```

Expected: FAIL because refused summaries still contribute mapped rows or reach the fallback write path.

- [ ] **Step 3: Filter before mapping and writing**

In `preview_linked_purchase_expense_oa`, split normalized summaries into active and excluded collections using their `excluded` flag or the unified decision helper. Build `mapped_rows` only from active summaries, return `excluded_purchase_summaries` and `excluded_purchase_summary_count`, and keep the full summary list for audit.

In `_sync_linked_purchase_fields`, when all summaries are excluded, persist their latest states and return a successful skipped result without calling `apply_linked_purchase_expense_fillable_fields`.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_import_service.py overseas_costing/tests/test_dingtalk.py -k 'purchase or rejected'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add overseas_costing/services/import_service.py overseas_costing/scripts/import_oa_logistics.py overseas_costing/tests/test_import_service.py overseas_costing/tests/test_dingtalk.py
git commit -m "fix: exclude rejected purchase approvals"
```

### Task 3: Repair only rows proven to come from excluded purchases

**Files:**
- Modify: `overseas_costing/scripts/import_oa_logistics.py:4117-4235,4380-4475`
- Test: `overseas_costing/tests/test_dingtalk.py`

- [ ] **Step 1: Write failing provenance-safety tests**

Cover these two cases:

1. Every current item has `source_type=PURCHASE_EXPENSE_OA`, its `dingtalk_instance_id` belongs to an excluded purchase approval, and the main logistics form still has item rows. Assert the helper replaces those rows with the main logistics rows and records an audit entry.
2. At least one item is manually overridden, has another source type, or lacks a matching invalid purchase instance ID. Assert no row is deleted and the result requires manual review.

```python
assert repaired["action"] == "restored_main_logistics_items"
assert protected["action"] == "manual_required"
assert protected["deleted_count"] == 0
```

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_dingtalk.py -k invalid_purchase_item_repair
```

Expected: FAIL because the provenance-safe repair helper is absent.

- [ ] **Step 3: Implement guarded historical repair**

Add `_restore_main_logistics_items_after_excluded_purchases`. It may replace existing items only when every current item is non-manual `PURCHASE_EXPENSE_OA` and its `dingtalk_instance_id` belongs to the excluded instance set. Build replacements with the existing `build_oa_item_values_from_approval`, insert them as `oa_logistics` rows, update the batch item count/status, and write an audit log containing invalid instance IDs and row counts.

If provenance is mixed, manual, missing, or the main logistics form contains no recoverable rows, return `manual_required` without deleting or changing anything. Call this helper from `_sync_linked_purchase_fields` only when all linked purchase summaries are excluded and no valid purchase rows remain.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_dingtalk.py -k 'invalid_purchase_item_repair or rejected_purchase'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add overseas_costing/scripts/import_oa_logistics.py overseas_costing/tests/test_dingtalk.py
git commit -m "fix: repair rejected purchase-derived rows safely"
```

### Task 4: Hide invalid main approvals from active workbench views

**Files:**
- Modify: `overseas_costing/services/workbench_service.py:518-565`
- Test: `overseas_costing/tests/test_workbench_service.py`
- Test: `overseas_costing/tests/test_batch_service.py`

- [ ] **Step 1: Write a failing workbench-scope test**

Create classified rows for one invalid main logistics approval, one valid main approval with an invalid linked purchase approval, and one fully valid approval. Assert only the invalid main row is removed from active workbench lists and summaries.

```python
assert [row["name"] for row in visible] == ["VALID-WITH-INVALID-PURCHASE", "VALID"]
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_workbench_service.py -k invalid_main
```

Expected: FAIL because `_classified_batches` currently retains every batch.

- [ ] **Step 3: Add the active-workbench filter**

After source status is attached, filter only rows where both conditions hold:

```python
not (
    (row.get("source_status") or {}).get("invalid_business")
    and (row.get("source_status") or {}).get("invalid_business_scope") == "source_approval"
)
```

Do not change `batch_service.get_batch_list`; direct historical lookup must remain available for traceability.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py -k 'invalid or workbench'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add overseas_costing/services/workbench_service.py overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py
git commit -m "fix: hide invalid main approvals from workbench"
```

### Task 5: Expose active and excluded approvals safely in the detail API

**Files:**
- Modify: `overseas_costing/services/dingtalk_approval_service.py:230-335`
- Test: `overseas_costing/tests/test_dingtalk_approval_service.py`

- [ ] **Step 1: Write failing API normalization tests**

Extend the batch-detail fixture with one `COMPLETED + agree` and one `COMPLETED + refuse` linked approval. Assert normalized decision fields and list separation:

```python
assert result["linked_purchase_approvals"][0]["effective_status"] == "COMPLETED"
assert result["excluded_linked_purchase_approvals"][0]["effective_status"] == "REJECTED"
assert result["excluded_linked_purchase_approvals"][0]["excluded"] is True
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_dingtalk_approval_service.py -k excluded
```

Expected: FAIL because decision fields and the excluded list are absent.

- [ ] **Step 3: Normalize and split linked approvals**

Have `_approval` call `resolve_approval_decision`. Preserve `status` and `result`, add `process_status`, `approval_result`, `effective_status`, and `excluded`. In `get_batch_dingtalk_approval_detail`, build all trusted linked approvals once, then return active entries in `linked_purchase_approvals` and excluded entries in `excluded_linked_purchase_approvals`.

Update attachment materialization to search both lists so audit-only attachments remain downloadable, while cost-source selection is controlled in the frontend.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_dingtalk_approval_service.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add overseas_costing/services/dingtalk_approval_service.py overseas_costing/tests/test_dingtalk_approval_service.py
git commit -m "feat: expose excluded approval audit details"
```

### Task 6: Render excluded approvals without cost-source actions

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/84-dingtalk-approval.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/46-dingtalk-approval.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Modify: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Test: `overseas_costing/tests/test_workbench_frontend_state.py`

- [ ] **Step 1: Write a failing frontend asset test**

Assert the source part contains `excluded_linked_purchase_approvals`, the heading `已排除审批`, and that packing candidates skip `approval.excluded`. Keep the generated-asset equality test intact.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py -k excluded
```

Expected: FAIL because the excluded section is absent.

- [ ] **Step 3: Implement the excluded section**

Render valid linked approvals under `采购审批` and excluded approvals in a separate warning-toned `已排除审批` section. Show original status/result and exclusion text. Ensure `dingtalkPackingCandidates` ignores excluded approvals and `syncPurchaseApprovalStatusFromDingtalk` never marks an all-excluded set as valid.

- [ ] **Step 4: Synchronize generated assets and verify GREEN**

Apply identical JavaScript and CSS changes to both shipped asset copies, then run:

```bash
.venv/bin/python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
```

Expected: PASS with both generated copies byte-identical.

- [ ] **Step 5: Commit Task 6**

```bash
git add overseas_costing/page/overseas_cost_workbench overseas_costing/overseas_costing/page/overseas_cost_workbench overseas_costing/tests/test_workbench_frontend_state.py
git commit -m "feat: show excluded approval audit section"
```

### Task 7: Verify, deploy, refresh, and audit production history

**Files:**
- No new source files.

- [ ] **Step 1: Run the full local verification suite**

```bash
.venv/bin/python -m pytest -q overseas_costing/tests
.venv/bin/python -m compileall -q overseas_costing
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
cmp -s overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
cmp -s overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
git diff --check
```

Expected: all tests pass and all asset checks exit 0.

- [ ] **Step 2: Push deployment branches**

```bash
git push production HEAD:codex/dingtalk-db-source
git push origin HEAD:codex/dingtalk-db-source
git push origin HEAD:overseas_costing
```

Wait for the `Overseas Costing CI/CD` run to succeed.

- [ ] **Step 3: Run the PostgreSQL-backed 2026 refresh**

On the Vultr backend, execute the existing all-mode import for `2026-01-01` through `2026-09-04`. Confirm the response says `data_source=postgres` and `fallback_used=false`.

- [ ] **Step 4: Audit production results**

Verify:

```text
International logistics source rows: 72
Excluded TERMINATED rows: 7
Active logistics rows: 65
Direct DingTalk API calls from Vultr: 0
```

Count linked purchase approvals with `result=refuse`, confirm they appear only in `excluded_linked_purchase_approvals`, and confirm active mapped purchase rows contain none of their instance IDs.

- [ ] **Step 5: Verify the production UI**

Open a batch with an excluded linked approval. Confirm the valid batch remains in the workbench, the rejected purchase appears under `已排除审批`, its status/result are visible, and it cannot be selected as a packing or costing source.

- [ ] **Step 6: Confirm key preservation**

Verify the existing deployment key files and Aliyun `authorized_keys` entries still exist. Do not delete, rotate, rewrite, or commit any key material.
