# Cost Review Remediation Collaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** 在现有海外成本工作台中增加财务退回整改、采购/墨西哥同事回复与再次提交、财务逐项确认的闭环，并把未解决整改项纳入 ERP 服务端硬门禁。

**Architecture:** 保留现有成本试算、人工确认和 ERP 推送链路；新增独立的整改轮次与问题记录作为可审计业务数据。服务端以当前批次、版本和试算快照为权威，列表状态由试算就绪度与活动整改轮次实时投影。前端只在抽屉中暂存财务草稿，正式“退回整改”后通过“复核沟通”页签完成协作。

**Tech Stack:** Python 3.12、Frappe/ERPNext DocType、pytest、浏览器端 JavaScript/jQuery、CSS、Node 语法检查、现有资源构建器与 GitHub Actions 生产发布流水线。

---

### Task 1: Define remediation records and pure state projection

**Files:**
- Create: `overseas_costing/doctype/overseas_cost_review_round/overseas_cost_review_round.json`
- Create: `overseas_costing/doctype/overseas_cost_review_round/overseas_cost_review_round.py`
- Create: `overseas_costing/doctype/overseas_cost_review_round/__init__.py`
- Create: `overseas_costing/doctype/overseas_cost_review_issue/overseas_cost_review_issue.json`
- Create: `overseas_costing/doctype/overseas_cost_review_issue/overseas_cost_review_issue.py`
- Create: `overseas_costing/doctype/overseas_cost_review_issue/__init__.py`
- Mirror: `overseas_costing/overseas_costing/doctype/overseas_cost_review_round/*`
- Mirror: `overseas_costing/overseas_costing/doctype/overseas_cost_review_issue/*`
- Create: `overseas_costing/services/review_communication_service.py`
- Test: `overseas_costing/tests/test_review_communication_service.py`
- Modify: `overseas_costing/tests/test_erp_sync_doctypes.py`

- [ ] **Step 1: Write failing schema and pure projection tests**

Cover required links, statuses, no responsibility field, optional anchor/attachments, actor timestamps, and the projection rules:

```python
assert project_review_state(None) == {"remediation_state": "none", "unresolved_count": 0}
assert project_review_state(returned_round)["remediation_state"] == "returned"
assert project_review_state(resubmitted_round)["remediation_state"] == "resubmitted"
assert project_review_state(resolved_round)["erp_blocked"] is False
```

Run: `python3 -m pytest -q overseas_costing/tests/test_review_communication_service.py overseas_costing/tests/test_erp_sync_doctypes.py`

Expected: FAIL because the DocTypes and service do not exist.

- [ ] **Step 2: Add minimal DocTypes and pure validation/projection helpers**

`Overseas Cost Review Round` stores `batch`, `version`, `round_no`, `status`, `trial_signature`, return/resubmit/resolve actors and times. `Overseas Cost Review Issue` stores ordered issue text, optional target tab/field/row/item metadata, attachment metadata, reply, handled/resolved actors and times, and `Open/Addressed/Resolved` status. Neither record contains responsibility or claim ownership.

- [ ] **Step 3: Run focused tests and mirror checks**

Run the focused pytest command again and compare each source DocType file to its deployed mirror.

Expected: PASS and byte-identical mirrors.

- [ ] **Step 4: Commit**

```bash
git add overseas_costing/doctype overseas_costing/overseas_costing/doctype overseas_costing/services/review_communication_service.py overseas_costing/tests
git commit -m "feat: define cost review remediation records"
```

### Task 2: Implement transactional remediation commands and audit history

**Files:**
- Modify: `overseas_costing/services/review_communication_service.py`
- Create: `overseas_costing/api/review.py`
- Modify: `overseas_costing/doctype/overseas_cost_audit_log/overseas_cost_audit_log.json`
- Mirror: `overseas_costing/overseas_costing/doctype/overseas_cost_audit_log/overseas_cost_audit_log.json`
- Test: `overseas_costing/tests/test_review_communication_service.py`
- Create: `overseas_costing/tests/test_review_api.py`

- [ ] **Step 1: Write failing command tests**

Cover:
- finance return creates one round plus ordered issues atomically;
- empty descriptions, stale version/trial signature, duplicate active return and foreign anchors fail before writes;
- attachment IDs must belong to uploaded `File` records and are linked only after issue creation;
- procurement/Mexico can address one issue with a required reply;
- resubmit requires every issue addressed and a current valid saved trial;
- finance resolves issues only after resubmit, with audit events for every transition;
- stale optimistic revision and concurrent requests fail cleanly without partial state.

Run: `python3 -m pytest -q overseas_costing/tests/test_review_communication_service.py overseas_costing/tests/test_review_api.py`

Expected: FAIL on missing commands/API.

- [ ] **Step 2: Implement short locked transactions**

Use a fixed lock order `Batch -> Version -> active Round -> Issues`, re-read authoritative version/trial data inside the transaction, and commit exactly once. Expose:

```python
return_for_remediation(batch_name, version_name, trial_signature, issues_json)
get_review_communication(batch_name)
address_review_issue(batch_name, issue_name, reply, expected_modified)
resubmit_review_round(batch_name, round_name, expected_modified)
resolve_review_issue(batch_name, issue_name, expected_modified)
```

Only `return_for_remediation` changes the batch into the returned workflow; opening/closing the drawer has no server write.

- [ ] **Step 3: Extend audit action options and API permissions**

Add explicit `REVIEW_RETURN`, `REVIEW_REPLY`, `REVIEW_RESUBMIT`, and `REVIEW_RESOLVE` action types. Every API calls `require_batch_permission` with read/write as appropriate and records actual `frappe.session.user` and server time.

- [ ] **Step 4: Run focused tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_review_communication_service.py overseas_costing/tests/test_review_api.py
git add overseas_costing
git commit -m "feat: add cost review remediation transactions"
```

### Task 3: Project remediation into pending/cost queues and ERP gates

**Files:**
- Modify: `overseas_costing/services/workbench_service.py`
- Modify: `overseas_costing/services/cost_review_service.py`
- Modify: `overseas_costing/services/batch_service.py`
- Modify: `overseas_costing/tests/test_workbench_service.py`
- Modify: `overseas_costing/tests/test_cost_review_service.py`
- Modify: `overseas_costing/tests/test_batch_service.py`

- [ ] **Step 1: Write failing queue projection tests**

Assert:
- a successful current trial without a review round appears only in cost review;
- `Returned` appears in procurement/Mexico pending and remains visible to finance;
- all replies alone do not leave pending;
- `Resubmitted` appears only in cost review;
- `Resolved` restores the normal cost-review/ERP-ready path;
- batches without purchase value never enter cost review;
- returned/resubmitted counts and the next-action label are returned in bulk without N+1 queries.

- [ ] **Step 2: Write failing ERP gate tests**

Both `confirm_calculation_result` and `writeback_to_erp` must reject an active round or unresolved issue, even if the client hides the warning or calls the API directly.

- [ ] **Step 3: Implement bulk review loading and authoritative gates**

Load active rounds/issues once per workbench chunk, merge `remediation_state`, `unresolved_count`, `addressed_count`, `round_name`, and task-specific primary actions into each row, and add the same authoritative check under the final-action locks.

- [ ] **Step 4: Run focused tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_cost_review_service.py overseas_costing/tests/test_batch_service.py
git add overseas_costing/services overseas_costing/tests
git commit -m "feat: gate queues and ERP on review remediation"
```

### Task 4: Simplify list actions and route users to the correct detail tab

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/05-workbench-state.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/10-shell.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/35-workbench-view.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/25-workbench-redesign.css`
- Modify: `overseas_costing/tests/test_review_workbench_ui.py`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`

- [ ] **Step 1: Write failing Node-backed UI tests**

Verify there is no row-level “补资料” plus “更多” pair; the batch number/general row opens `documents`; and exactly one rightmost button renders:
- pending incomplete: `继续处理` -> `documents`;
- pending returned: `待整改 N` -> `review`;
- cost ready: `成本核算` -> `documents`;
- finance returned/resubmitted: `待整改` or `待财务复核` -> `review`.

- [ ] **Step 2: Implement state routing and one action column**

Add `review` to allowed detail tabs. Keep inline result expansion separate. Preserve list filters/history state when opening or returning.

- [ ] **Step 3: Run focused tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_workbench_frontend_state.py
git add overseas_costing/page/overseas_cost_workbench/parts overseas_costing/tests
git commit -m "feat: streamline workbench review navigation"
```

### Task 5: Add finance remediation drawer and contextual feedback anchors

**Files:**
- Create: `overseas_costing/page/overseas_cost_workbench/parts/88-review-communication.js`
- Create: `overseas_costing/page/overseas_cost_workbench/parts/52-review-communication.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/10-shell.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js`
- Modify: `overseas_costing/tests/test_review_workbench_ui.py`

- [ ] **Step 1: Write failing drawer tests**

Verify the finance-only orange-outline “提出整改” action appears beside the single ERP action; generic add contains only description and optional attachment; `反馈此项` pre-populates immutable target metadata without issue type/responsibility; drafts are client-only until `退回整改 (N)`; non-empty unsaved drafts warn before close, refresh, or navigation; only the body scrolls at desktop/tablet/phone widths.

- [ ] **Step 2: Implement shared draft drawer**

Keep the draft in `reviewDraftState`, upload attachments using the existing Frappe file flow, and submit all issues in one API call. Do not navigate when opening or submitting the drawer. On success refresh detail/list projection and select the stable `review` tab.

- [ ] **Step 3: Add contextual “反馈此项” hooks**

Add hooks only where a stable tab/field/row identity exists. No guessed mapping and no automatic edit/save.

- [ ] **Step 4: Run tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py
git add overseas_costing/page/overseas_cost_workbench/parts overseas_costing/tests
git commit -m "feat: add finance remediation drawer"
```

### Task 6: Add the stable review communication tab and direct-target workflow

**Files:**
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/88-review-communication.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/45-detail-page.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/52-review-communication.css`
- Modify: `overseas_costing/tests/test_review_workbench_ui.py`

- [ ] **Step 1: Write failing communication-tab tests**

Cover unresolved badge, current round, collapsed history, finance text and attachments, partial reply persistence, addressed/resolved states, submit-to-finance gate, finance per-item resolution, and audit actor/time rendering.

- [ ] **Step 2: Write failing direct-target tests**

`去修改` must switch within the same batch to the stored tab, wait for render, center-scroll and temporarily highlight the exact target, focus only editable inputs, preserve reply drafts, and show “返回整改问题 N”. A missing/stale target opens the original tab and shows the explicit manual-check warning.

- [ ] **Step 3: Implement tab, reply/resubmit/resolve actions, and focus restoration**

Before resubmit, require all issues addressed and then let the server revalidate the current trial. Do not auto-recalculate or auto-resubmit.

- [ ] **Step 4: Run tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_workbench_frontend_state.py
git add overseas_costing/page/overseas_cost_workbench/parts overseas_costing/tests
git commit -m "feat: add review communication workspace"
```

### Task 7: Integrate, regenerate, and verify the complete change

**Files:**
- Generated: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Generated: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Generated mirrors: `overseas_costing/overseas_costing/page/overseas_cost_workbench/*`
- Verify: all changed Python, JSON, JavaScript, CSS, tests, and docs

- [ ] **Step 1: Bring in the newest production branch before release**

```bash
git fetch production overseas_costing
git merge-base --is-ancestor production/overseas_costing HEAD || git rebase production/overseas_costing
```

Stop on unknown conflicts; never overwrite unrelated front-end changes from the other conversation.

- [ ] **Step 2: Build twice and require idempotence**

```bash
python3 overseas_costing/scripts/build_workbench_assets.py
python3 overseas_costing/scripts/build_workbench_assets.py
```

Expected: the second command returns `"changed": []`.

- [ ] **Step 3: Run focused, full, syntax, and diff validation**

```bash
python3 -m pytest -q overseas_costing/tests/test_review_communication_service.py overseas_costing/tests/test_review_api.py overseas_costing/tests/test_cost_review_service.py overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py overseas_costing/tests/test_review_workbench_ui.py overseas_costing/tests/test_workbench_frontend_state.py
python3 -m pytest -q overseas_costing/tests
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
git diff --check
```

- [ ] **Step 4: Browser acceptance at 375, 768, and 1440 widths**

Verify one list action, finance drawer sizing, fixed drawer controls, review tab badge, partial replies, target navigation/highlight/focus, and no horizontal page overflow. Use local/mock data only; do not create a real production remediation round during pre-release testing.

- [ ] **Step 5: Commit generated assets and release candidate**

```bash
git add overseas_costing docs/superpowers/plans/2026-09-21-cost-review-remediation-collaboration.md
git commit -m "build: regenerate cost review workbench assets"
```

### Task 8: Deploy once through the existing production pipeline

**Files:**
- Deploy workflow: `.github/workflows/deploy-overseas-costing.yml`
- Production branch: `production/overseas_costing`
- Production site: `https://deeplinkerp.com`

- [ ] **Step 1: Record target and rollback ancestry**

```bash
git fetch production overseas_costing
git rev-parse HEAD
git rev-parse production/overseas_costing
git merge-base --is-ancestor production/overseas_costing HEAD
```

Expected: the release is a fast-forward descendant. Stop instead of force-pushing if production diverged.

- [ ] **Step 2: Push once and monitor the exact workflow SHA**

```bash
git push production HEAD:overseas_costing
gh run list --repo yueweiit/DeepLinkERP --workflow deploy-overseas-costing.yml --branch overseas_costing --limit 3
```

Wait for both `Run tests` and `Deploy to DeepLinkERP`, including rollback backup, migration, asset sync, service restart, and login check.

- [ ] **Step 3: Perform read-only production verification**

Confirm deployed SHA/code hashes, DocType metadata, login HTTP 200, and authenticated UI rendering. Inspect an existing cost-review batch only; do not click “退回整改”, “提交财务复核”, “确认并推送 ERP”, or any formal business action.

- [ ] **Step 4: Report evidence**

Report release SHA, baseline/full/focused tests, second-build idempotence, workflow URL/status, migration and asset results, production UI checks, and explicit confirmation that production acceptance created no remediation round and performed no ERP push.
