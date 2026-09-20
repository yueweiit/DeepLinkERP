# Cost Review Transition, Waybill Sync, and Compact Status Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make every successfully saved trial enter the cost-review workspace, keep editable stale results inside cost review while ERP stays blocked, safely adopt the unique DHL comment waybill, and replace the oversized status warning with the approved compact A layout.

**Architecture:** Introduce one canonical saved-fee projection shared by result persistence and readiness hashing. Keep result validity separate from cost-review-stage membership: a valid saved schema-2 snapshot starts cost review, while existing readiness blockers continue to guard confirmation and ERP. Extend the existing audited comment-waybill writer only for active non-invalid logistics approvals, and keep the frontend change local to the detail page and its tests.

**Tech Stack:** Python 3, Frappe/ERPNext service layer, Decimal-based costing, pytest, vanilla JavaScript, CSS, Node syntax checks, existing asset builder and GitHub Actions production workflow.

---

### Task 1: Canonicalize Saved Material and Fee Inputs

**Files:**
- Modify: overseas_costing/services/cost_preview_service.py
- Modify: overseas_costing/services/cost_review_service.py
- Test: overseas_costing/tests/test_cost_review_service.py

- [ ] **Step 1: Add a failing production-shaped fingerprint regression**

Add a test with a separate-adoption international logistics source embedded in item extra_json. Project the source context before saving, persist the item update returned by build_saved_cost_data, and immediately evaluate review readiness using the same source context.

~~~python
def test_saved_result_with_persisted_and_virtual_fees_is_immediately_current():
    context = saved_context()
    source_context = {
        "root_kind": "logistics",
        "available": True,
        "approved": False,
        "invalid": False,
        "separate_adoption": True,
        "fingerprint": "source-fingerprint",
        "source_snapshot": "source-snapshot",
        "freight": {"selected": False},
        "packing": {},
    }
    context["source_context"] = source_context
    context["items"][0]["extra_json"] = json.dumps(
        {"effective_logistics_source": source_context}
    )
    save_result(context)

    result = evaluate(context)

    assert result["result_is_current"] is True
    assert result["review_state"] == "ready"
    assert "RESULT_STALE" not in codes(result)
~~~

- [ ] **Step 2: Run the regression and prove it fails before the fix**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_cost_review_service.py::test_saved_result_with_persisted_and_virtual_fees_is_immediately_current
~~~

Expected: FAIL with RESULT_STALE because saving canonicalizes extra_json to a persisted string while readiness currently hashes the equivalent projected object.

- [ ] **Step 3: Extract one canonical saved-input projection**

Add this public pure helper next to cost_input_hash:

~~~python
def normalize_saved_cost_inputs(items, fees, fx_context, transport_mode):
    mode = fee_service.resolve_transport_mode(transport_mode)
    normalized_items = [persist_calculated_item(row) for row in items]
    decorated = fee_service._decorate_historical_rules(fees, mode)
    selected = select_fees(
        decorated,
        fx_context,
        source_context=source_context_from_items(normalized_items),
    )
    normalized_fees = supplement_legacy_fees(normalized_items, selected)
    return normalized_items, normalized_fees
~~~

Use normalize_saved_cost_inputs inside build_saved_cost_data instead of separately pruning item metadata and repeating decorate, select, and supplement inline.

- [ ] **Step 4: Make readiness hash exactly what the saver hashes**

After applying any saved AI trial projection, call normalize_saved_cost_inputs and use both returned lists for current_hash. Keep build_saved_cost_data as the authoritative expected-result calculator.

~~~python
saved_items, saved_fees = cost_preview_service.normalize_saved_cost_inputs(
    inputs,
    calculation_fees,
    fx,
    mode,
)
current_hash = cost_preview_service.cost_input_hash(
    saved_items,
    saved_fees,
    fx,
    mode,
    components,
)
~~~

- [ ] **Step 5: Run readiness tests**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_cost_review_service.py
~~~

Expected: all tests pass, including true input and FX changes still producing RESULT_STALE.

- [ ] **Step 6: Commit the canonicalization**

~~~bash
git add overseas_costing/services/cost_preview_service.py overseas_costing/services/cost_review_service.py overseas_costing/tests/test_cost_review_service.py
git commit -m "fix: share canonical cost input projection"
~~~

### Task 2: Separate Cost-Review Membership from ERP Readiness

**Files:**
- Modify: overseas_costing/services/cost_review_service.py
- Modify: overseas_costing/services/workbench_service.py
- Test: overseas_costing/tests/test_cost_review_service.py
- Test: overseas_costing/tests/test_workbench_service.py

- [ ] **Step 1: Add failing stage-membership tests**

Add assertions that a schema-2 saved snapshot starts cost review even if a later fee edit makes the current result stale.

~~~python
def test_saved_trial_starts_cost_review_even_after_input_change():
    context = saved_context()
    context["items"][0]["goods_value"] = 110

    result = evaluate(context)

    assert result["cost_review_started"] is True
    assert result["review_state"] == "processing"
    assert result["result_is_current"] is False
~~~

Add workbench filtering coverage:

~~~python
def test_stale_saved_trial_stays_in_cost_review_not_pending():
    row = {"review_state": "processing", "cost_review_started": True}
    assert filter_batches_for_task([row], "pending") == []
    assert filter_batches_for_task([row], "cost", "pending") == [row]
~~~

- [ ] **Step 2: Run the two focused tests and verify RED**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_cost_review_service.py::test_saved_trial_starts_cost_review_even_after_input_change overseas_costing/tests/test_workbench_service.py::test_stale_saved_trial_stays_in_cost_review_not_pending
~~~

Expected: FAIL because cost_review_started does not yet exist and cost filtering only accepts review_state ready.

- [ ] **Step 3: Derive cost_review_started without a new database field**

In evaluate_review_readiness, derive the flag from a real saved schema-2 result:

~~~python
cost_review_started = bool(
    snapshot.get("calculation_schema") == 2
    and snapshot.get("input_hash")
    and isinstance(snapshot.get("comprehensive_cost"), dict)
    and version.get("calculated_at")
)
~~~

Return this flag with readiness. Do not let it override result_is_current, blockers, confirmation, or ERP gates.

- [ ] **Step 4: Update workbench task filtering**

Use stage membership for list placement while preserving confirmed history:

~~~python
if task == "pending":
    return [row for row in rows if row.get("review_state") == "processing" and not row.get("cost_review_started")]
if task == "cost":
    if str(review_status).lower() == "confirmed":
        return [row for row in rows if row.get("review_state") == "confirmed"]
    return [row for row in rows if row.get("cost_review_started") and row.get("review_state") != "confirmed"]
~~~

Keep confirm_calculation_result unchanged: it must still require review_state ready before confirming and enabling ERP.

- [ ] **Step 5: Run service and workbench tests**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_cost_review_service.py overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py
~~~

Expected: all tests pass; stale saved trials remain editable in cost review and are not confirmable.

- [ ] **Step 6: Commit stage membership**

~~~bash
git add overseas_costing/services/cost_review_service.py overseas_costing/services/workbench_service.py overseas_costing/tests/test_cost_review_service.py overseas_costing/tests/test_workbench_service.py
git commit -m "fix: keep saved trials in cost review"
~~~

### Task 3: Refresh Classification after Every Successful Trial

**Files:**
- Modify: overseas_costing/page/overseas_cost_workbench/parts/30-calculation-erp.js
- Modify: overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js
- Test: overseas_costing/tests/test_review_workbench_ui.py
- Test: overseas_costing/tests/test_trial_ai_boundary_ui.py

- [ ] **Step 1: Add failing AI-confirm navigation coverage**

Create a Node-backed test where confirm_cost_trial returns saved true, the authoritative cost list returns the batch, and the current detail remains open.

~~~javascript
await v.confirmCostTrialAI();
console.log(JSON.stringify({
  task: v.viewState.task,
  batch: v.viewState.batch,
  classificationCalls: calls.filter(row => row.method.endsWith("get_batches")),
}));
~~~

Assert task is cost, batch remains B, and no automatic confirmation or ERP method was called.

- [ ] **Step 2: Verify the AI-confirm test fails**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_trial_ai_boundary_ui.py -k classification
~~~

Expected: FAIL because confirmCostTrialAI saves and rerenders locally without refreshing authoritative classification.

- [ ] **Step 3: Share the post-save classification path**

Keep direct recalculate using refreshRecalculatedDetailClassification. After AI trial confirmation has accepted the saved result and verified the view is still current, call the same method before the final local render:

~~~javascript
if (isUnchangedView()) {
  await this.refreshRecalculatedDetailClassification(batchName);
}
~~~

Guard against stale views using the existing request, fee request, input revision, batch, and version checks. A classification refresh failure may show a warning, but must not report the already committed trial as failed.

- [ ] **Step 4: Run navigation tests**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_trial_ai_boundary_ui.py
~~~

Expected: all tests pass for first trial, repeated trial, stale view, and direct recalculate.

- [ ] **Step 5: Commit post-save navigation**

~~~bash
git add overseas_costing/page/overseas_cost_workbench/parts/30-calculation-erp.js overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_trial_ai_boundary_ui.py
git commit -m "fix: enter cost review after saved trial"
~~~

### Task 4: Allow Audited Waybill Adoption from Active Logistics Approvals

**Files:**
- Modify: overseas_costing/services/logistics_settlement/runtime.py
- Test: overseas_costing/tests/test_settlement_runtime.py

- [ ] **Step 1: Replace the obsolete approval test with active-source cases**

Add a positive RUNNING / agree case and explicit negative terminal cases:

~~~python
def test_comment_waybill_sync_accepts_active_noninvalid_logistics_source(monkeypatch):
    s, ledger, batch, parsed = waybill_runtime_context()
    parsed.update(kind="logistics", status="RUNNING", approval_result="agree", approved=False, invalid=False)
    attach_runtime(monkeypatch, s, ledger)

    with s.atomic():
        runtime.ensure_batch(s, parsed)

    assert ledger.get("batch", batch["name"])["waybill_no"] == "3080665836"
    assert s.count("audit", action="batch_waybill_synced") == 1
~~~

Parametrize rejection for expense sources, invalid sources, rejected/withdrawn/terminated statuses, ambiguous comments, and existing manual values.

- [ ] **Step 2: Run the active-source test and verify RED**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_settlement_runtime.py::test_comment_waybill_sync_accepts_active_noninvalid_logistics_source
~~~

Expected: FAIL because _sync_comment_waybill currently requires approved is True.

- [ ] **Step 3: Add a narrow eligibility predicate**

~~~python
def _comment_waybill_source_eligible(source):
    if source.get("kind") != "logistics" or bool(source.get("invalid")):
        return False
    status = str(source.get("status") or "").upper()
    if status == "RUNNING":
        return True
    return status == "COMPLETED" and source.get("approved") is True
~~~

Use this predicate in _sync_comment_waybill. Keep the strict carrier regexes, unique-candidate requirement, source ownership, manual conflict audit, atomic write, and update_modified false behavior unchanged.

- [ ] **Step 4: Run all settlement runtime tests**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_settlement_runtime.py overseas_costing/tests/test_freight_lines.py
~~~

Expected: all tests pass, including rollback and manual-value protection.

- [ ] **Step 5: Commit waybill eligibility**

~~~bash
git add overseas_costing/services/logistics_settlement/runtime.py overseas_costing/tests/test_settlement_runtime.py
git commit -m "fix: adopt waybill from active logistics comments"
~~~

### Task 5: Implement Compact A Status Bar and One Dynamic Trial Action

**Files:**
- Modify: overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js
- Modify: overseas_costing/page/overseas_cost_workbench/parts/45-detail-page.css
- Modify: overseas_costing/page/overseas_cost_workbench/parts/50-responsive-and-drawer.css
- Test: overseas_costing/tests/test_review_workbench_ui.py
- Test: overseas_costing/tests/test_detail_erp_header_ui.py

- [ ] **Step 1: Add failing compact-layout tests**

Assert:

- the detail shell has exactly one data-primary-action recalculation entry;
- the entry is inside the status row, not duplicated in the header or overview;
- the label is “开始试算” before any saved result and “重新试算” after a saved result;
- the cost task still shows the action while the batch is unconfirmed and unlocked;
- the compact warning shows the first blocker and “更多 N” for additional blockers;
- no blockers produce no warning strip.

~~~python
assert shell.count('data-primary-action="recalculate"') == 1
assert "重新试算" in shell
assert "ocw-detail-review-strip" in shell
assert "更多 2" in shell
assert "ocw-erp-block-dialog" not in shell
~~~

- [ ] **Step 2: Run focused UI tests and verify RED**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_detail_erp_header_ui.py
~~~

Expected: FAIL on the old “重新计算” label, cost-task action suppression, and large blocker panel markup.

- [ ] **Step 3: Make the trial action dynamic and available in cost review**

In detailCalculationAction, hide only for ERP, confirmed, or locked batches. Return “开始试算” when no saved result exists and “重新试算” otherwise. Remove the button from ocw-detail-header-actions and render it once at the right side of ocw-detail-statusbar.

- [ ] **Step 4: Replace the blocker card with a compact strip**

Render the first blocker inline. Put remaining blockers in a native details element so keyboard and screen-reader behavior remains available without new global state.

~~~javascript
const [first, ...rest] = blockers;
return [
  '<section class="ocw-detail-review-strip" role="status">',
  '<strong>待处理</strong>',
  '<span>' + this.escape(first.message || first.code || "待补信息") + '</span>',
  rest.length ? '<details><summary>更多 ' + rest.length + '</summary><ul>...</ul></details>' : '',
  '</section>',
].join('');
~~~

Show this strip in pending and cost details. In cost review, stale results remain editable and the existing ERP action stays disabled by authoritative readiness.

- [ ] **Step 5: Add compact responsive CSS**

Use 7px vertical padding, one-line desktop alignment, no empty reserved space, and a wrapped narrow-screen layout. Remove any detail-only dependency on the generic ocw-erp-block-dialog card styles.

- [ ] **Step 6: Run UI tests and Node syntax checks**

Run:

~~~bash
python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_detail_erp_header_ui.py
node --check overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js
node --check overseas_costing/page/overseas_cost_workbench/parts/30-calculation-erp.js
node --check overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js
~~~

Expected: all tests and syntax checks pass.

- [ ] **Step 7: Commit the compact UI**

~~~bash
git add overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js overseas_costing/page/overseas_cost_workbench/parts/45-detail-page.css overseas_costing/page/overseas_cost_workbench/parts/50-responsive-and-drawer.css overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_detail_erp_header_ui.py
git commit -m "fix: compact cost review status controls"
~~~

### Task 6: Build, Verify, Integrate, and Release

**Files:**
- Modify generated workbench assets using the repository asset builder
- Verify all source and generated files

- [ ] **Step 1: Run the complete backend and frontend suite**

~~~bash
python3 -m pytest -q overseas_costing/tests
~~~

Expected: 3970 or more tests pass and only the existing skips remain.

- [ ] **Step 2: Build workbench assets twice**

Run:

~~~bash
python3 overseas_costing/scripts/build_workbench_assets.py
python3 overseas_costing/scripts/build_workbench_assets.py
~~~

The second command must report:

~~~text
changed: []
~~~

- [ ] **Step 3: Check generated JavaScript and repository whitespace**

~~~bash
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
cmp overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
cmp overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
git diff --check
~~~

- [ ] **Step 4: Commit generated assets**

~~~bash
git add overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
git commit -m "build: refresh cost workbench assets"
~~~

Skip the commit only if the builder produces no tracked changes.

- [ ] **Step 5: Review the final branch**

Check:

~~~bash
git status --short
git log --oneline --decorate -8
git diff overseas_costing..HEAD --stat
~~~

Expected: clean feature worktree, isolated commits, and no HANDOFF.md changes.

- [ ] **Step 6: Integrate the feature branch**

Fast-forward or cherry-pick the verified commits onto the production source branch without modifying the user-owned HANDOFF.md, then rerun the focused smoke tests on the integrated tree.

- [ ] **Step 7: Push and monitor the existing production workflow**

Push the target production branch, identify the exact workflow run and commit SHA, and wait for completion. Do not report success from CI alone.

- [ ] **Step 8: Perform production acceptance**

Verify migrations/assets, service health, login HTTP 200, and the live batch 202609121455000173161. Re-sync its authoritative logistics source so the audited unique candidate 3080665836 is adopted. Confirm:

- the batch is listed under cost review after a saved trial;
- editing a fee keeps it in cost review but disables ERP until another successful trial;
- the status area uses compact A layout with one dynamic trial action;
- the waybill is 3080665836 with comment-derived provenance;
- no cost confirmation, version confirmation, or ERP push was executed.
