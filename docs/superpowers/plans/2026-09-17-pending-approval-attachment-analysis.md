# Pending Approval Attachment Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a readable, still-running approval attachment to participate in material estimate analysis without relaxing final-fee adoption or rewriting historical archive policy.

**Architecture:** Keep archived attachment metadata immutable and make dependency validation purpose-aware. Server-generated approval attachment dependencies carry an `approval_source_id`; an attachment carrying audit/final-cost restrictions may pass `analysis` or `estimate` only when that source still matches its `process_instance_id` and optional `corp_id` and remains readable. `adoption`, manual attachments, invalid approvals, and retired documents remain fail-closed.

**Tech Stack:** Python 3, Frappe/MariaDB production adapter, SQLite service tests, pytest, GitHub Actions production deployment.

---

### Task 1: Reproduce the pending-approval attachment failure

**Files:**
- Modify: `overseas_costing/tests/test_ai_download_dependencies.py`

- [ ] **Step 1: Write the failing analysis-purpose regression test**

Add a helper that creates an archived approval document and an `Overseas Cost Attachment` carrying `approval_excluded=true` and `cost_source_allowed=false`. Change the linked approval to `RUNNING`/`agree`/`approved=False`, then call `capture_dependencies` with `purpose="analysis"` and assert that it returns both `approval` and `attachment` dependencies.

```python
def restricted_approval_attachment(store, ledger, batch, version):
    source = store.find("source", instance="E")[0]
    source.update(status="RUNNING", approval_result="agree", approved=False, invalid=False)
    document = {"id": "DOC-1", "source_id": source["id"], "status": "review"}
    source["documents"] = [document]
    store.put("source", {"id": source["id"], "data": dumps(source)})
    store.insert("document", {
        "id": document["id"], "source_id": source["id"],
        "fingerprint": "DOC-1", "status": "review", "data": dumps(document),
    })
    attachment = ledger.create("attachment", {
        "batch": batch["name"], "version": version["name"],
        "source_type": "OA", "file_name": "fuel.png", "file_url": "/private/files/fuel.png",
        "parse_result_json": dumps({
            "process_instance_id": "E", "corp_id": source["corp"],
            "approval_excluded": True, "cost_source_allowed": False,
            "settlement_document": {"document_id": "DOC-1", "status": "review", "audit_only": True},
        }),
    })
    return source, [{
        "source_kind": "approval_attachment", "source_id": attachment["name"],
        "resolver_source_id": attachment["name"], "process_instance_id": "E",
        "selected": True, "available": True, "download_required": False,
    }]


def test_running_approval_audit_attachment_is_readable_for_analysis():
    store, ledger, batch, version, *_ = settlement_fixture.__wrapped__()
    _source, selected = restricted_approval_attachment(store, ledger, batch, version)

    dependencies = capture_dependencies(
        selected, store=store, ledger=ledger, batch_name=batch["name"],
        source_context={}, purpose="analysis",
    )

    assert {row["kind"] for row in dependencies} == {"approval", "attachment"}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m pytest -q overseas_costing/tests/test_ai_download_dependencies.py::test_running_approval_audit_attachment_is_readable_for_analysis
```

Expected: FAIL with `SourceEligibilityError` containing `附件来源已被排除`.

- [ ] **Step 3: Add safety tests before implementation**

Using the same fixture helper, add these complete safety tests:

```python
def test_running_approval_audit_attachment_remains_blocked_for_adoption():
    store, ledger, batch, version, *_ = settlement_fixture.__wrapped__()
    _source, selected = restricted_approval_attachment(store, ledger, batch, version)
    options = dict(store=store, ledger=ledger, batch_name=batch["name"], source_context={})
    with pytest.raises(ValueError):
        capture_dependencies(selected, purpose="adoption", **options)


def test_rejected_approval_audit_attachment_remains_blocked_for_analysis():
    store, ledger, batch, version, *_ = settlement_fixture.__wrapped__()
    source, selected = restricted_approval_attachment(store, ledger, batch, version)
    source.update(status="COMPLETED", approval_result="refuse", approved=False, invalid=True)
    store.put("source", {"id": source["id"], "data": dumps(source)})
    options = dict(store=store, ledger=ledger, batch_name=batch["name"], source_context={})
    with pytest.raises(ValueError):
        capture_dependencies(selected, purpose="analysis", **options)


def test_manual_audit_attachment_cannot_borrow_approval_analysis_policy():
    store, ledger, batch, version, *_ = settlement_fixture.__wrapped__()
    _source, selected = restricted_approval_attachment(store, ledger, batch, version)
    manual = [{**selected[0], "source_kind": "manual_attachment", "process_instance_id": ""}]
    options = dict(store=store, ledger=ledger, batch_name=batch["name"], source_context={})
    with pytest.raises(ValueError):
        capture_dependencies(manual, purpose="analysis", **options)
```

### Task 2: Make attachment dependency validation purpose-aware

**Files:**
- Modify: `overseas_costing/services/material_ai_source_dependencies.py:101-119,220-240`
- Test: `overseas_costing/tests/test_ai_download_dependencies.py`

- [ ] **Step 1: Add a current-approval resolver for restricted archived attachments**

Add a private helper next to `_read_dependency`:

```python
def _current_attachment_approval(dependency, metadata, store):
    source_id = str(dependency.get("approval_source_id") or "")
    if not source_id:
        return None
    instance = str(metadata.get("process_instance_id") or metadata.get("instance_id") or "")
    if not instance:
        return None
    source = store.get("source", source_id) or {}
    if source.get("instance") != instance:
        raise ValueError("附件的当前审批身份不一致。")
    if metadata.get("corp_id") and source.get("corp") != metadata.get("corp_id"):
        raise ValueError("附件的当前审批企业身份不一致。")
    return source
```

- [ ] **Step 2: Apply the minimal purpose-aware rule**

Replace the unconditional policy rejection in the `attachment` branch with:

```python
policy_restricted = (
    metadata.get("approval_excluded")
    or metadata.get("cost_source_allowed") is False
    or not _enabled(metadata or {"present": True})
)
if policy_restricted:
    current_approval = _current_attachment_approval(dependency, metadata, store)
    if purpose not in {"analysis", "estimate"} or not current_approval:
        raise ValueError("附件来源已被排除。")
    eligibility = approval_eligibility(current_approval)
    if not eligibility["analysis_allowed"]:
        raise SourceEligibilityError(
            eligibility["analysis_reason"], source=current_approval,
            code=eligibility["analysis_code"],
        )
```

Do not change `approval_eligibility`, `document_retired`, attachment bytes, or the adoption path.

When `capture_dependencies` builds an attachment descriptor for `approval_attachment` or `approval_comment_attachment`, include the server-resolved approval source identity:

```python
descriptor = {"kind": "attachment", "attachment_id": source_id}
if kind in {"approval_attachment", "approval_comment_attachment"} and approval_source:
    descriptor["approval_source_id"] = approval_source["id"]
add(descriptor)
```

- [ ] **Step 3: Run the focused regression tests and verify GREEN**

Run:

```bash
python3 -m pytest -q overseas_costing/tests/test_ai_download_dependencies.py
```

Expected: all tests pass.

- [ ] **Step 4: Run adjacent source-policy tests**

Run:

```bash
python3 -m pytest -q \
  overseas_costing/tests/test_dingtalk_approval_service.py \
  overseas_costing/tests/test_ai_download_dependencies.py \
  overseas_costing/tests/test_material_ai_fill_service.py \
  overseas_costing/tests/test_import_service.py \
  overseas_costing/tests/test_packing_snapshot_service.py \
  overseas_costing/tests/test_packing_source_service.py
```

Expected: all tests pass with no new skips or warnings.

- [ ] **Step 5: Commit the implementation**

```bash
git add overseas_costing/services/material_ai_source_dependencies.py \
  overseas_costing/tests/test_ai_download_dependencies.py
git commit -m "fix: allow pending approval attachments in AI analysis"
```

### Task 3: Verify, deploy, and accept the production order

**Files:**
- Verify: repository-wide tests and generated assets
- Deploy: `production/overseas_costing`
- Accept: production batch `mth4886h4g`, version `mthbk64qgb`, approval `202609121455000173161`

- [ ] **Step 1: Run release verification**

Run:

```bash
python3 overseas_costing/scripts/build_workbench_assets.py
python3 overseas_costing/scripts/build_workbench_assets.py --check
python3 overseas_costing/scripts/run_affected_tests.py production/overseas_costing
python3 -m pytest -q
python3 -m compileall -q overseas_costing
git diff --check
git status --short
```

Expected: generated assets are unchanged on the second build, all executed tests pass, compilation and diff checks exit 0, and only intentional commits are present.

- [ ] **Step 2: Push the verified commit to production**

```bash
git push production HEAD:overseas_costing
```

Expected: the `Overseas Costing CI/CD` workflow starts for the pushed SHA.

- [ ] **Step 3: Wait for the production workflow and verify deployed code**

Use the newest DeepLinkERP workflow for the pushed SHA. Require both test and deploy jobs to succeed. On the production host, compare the deployed `material_ai_source_dependencies.py` hash with the committed file and confirm the site health check returns HTTP 200.

- [ ] **Step 4: Re-run the target order through the real UI**

Open `deeplinkerp.com`, locate approval `202609121455000173161`, start one fresh AI analysis, and verify:

- progress passes 18%;
- `燃油附加费(8).png` leaves `DOWNLOADING` and reaches a terminal read status;
- the run reaches `READY` or `READY_WITH_WARNINGS`, not `STALE`;
- the UI still states that approval-in-progress fees cannot be used as final settlement fees.

- [ ] **Step 5: Read back production evidence**

Read the newest `Overseas Cost Material AI Run` for batch `mth4886h4g` and record its run id, status, progress, source progress for file id `236029869695`, and error message. Confirm the attachment row was not rewritten solely to clear audit/final-cost policy.

- [ ] **Step 6: Record the release commit**

```bash
git status --short
git log -3 --oneline
```

Expected: clean worktree and a traceable design, test, and implementation commit sequence.
