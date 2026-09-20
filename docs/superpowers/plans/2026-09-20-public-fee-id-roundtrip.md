# AI 草稿费用公开 ID 回传修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 AI 填充预览中脱敏费用 `proposal_id` 无法通过服务端锁内校验的问题，并安全发布到 `deeplinkerp.com`。

**Architecture:** 继续使用现有 `_public_ai_payload` 隐藏原始钉钉流程 ID。预览服务在同一个锁内 catalog 上同时生成公开视图，以公开 `proposal_id` 验证客户端输入，再映射回原始 ID 执行现有投影、收据和确认逻辑。

**Tech Stack:** Python 3.12, pytest, Frappe/ERPNext, GitHub Actions, SSH/Docker 生产发布。

---

## File Map

- Modify: `overseas_costing/services/material_ai_selection_service.py` — 公开费用 ID 的锁内验证与内部 ID 映射。
- Modify: `overseas_costing/tests/test_ai_selection_service.py` — 脱敏费用 ID 回传成功、伪造 ID 拒绝、原始流程 ID 不泄露的回归测试。
- Verify only: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js` and deployed mirror — 本次无前端逻辑变更，仅验证生成资源幂等。

### Task 1: Add the failing public fee ID round-trip regression

**Files:**
- Modify: `overseas_costing/tests/test_ai_selection_service.py`

- [ ] **Step 1: Write the failing test**

Add a test next to `test_unknown_row_and_fee_ids_are_rejected`:

```python
def test_public_approval_fee_id_round_trips_into_locked_preview_without_leaking_process_id():
    repo = Repo()
    raw_process_id = "P7BgLg53TRSLsYElgdX4Dg04891788440826"
    raw_fee_id = f"approval-fee:{raw_process_id}:1"
    repo.run["candidates_json"].append({
        "proposal_id": raw_fee_id,
        "proposal_type": "fee_update",
        "process_instance_id": raw_process_id,
        "default_selected": True,
        "payload": {
            "logical_fee_key": "international_sea_freight",
            "amount": "7756.2",
            "currency": "RMB",
            "amount_status": "ESTIMATED",
        },
    })

    catalog = service.review_catalog(repo, "B1", repo.run)
    public_fee_id = catalog["fees"][0]["proposal_id"]

    assert public_fee_id != raw_fee_id
    assert raw_process_id not in json.dumps(catalog, ensure_ascii=False)
    response = service.prepare(
        "B1", repo.run["name"], [], [public_fee_id],
        "update_selected", "V1", repository=repo,
    )
    receipt = repo.run["draft_json"]["row_previews"][response["preview"]["id"]]

    assert response["preview"]["fees"][0]["proposal_id"] == public_fee_id
    assert receipt["selected_fee_ids"] == [raw_fee_id]
    assert raw_process_id not in json.dumps(response, ensure_ascii=False)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m pytest -q overseas_costing/tests/test_ai_selection_service.py::test_public_approval_fee_id_round_trips_into_locked_preview_without_leaking_process_id
```

Expected: FAIL with `ValueError: 所选内容不属于当前草稿，请刷新预览。`

### Task 2: Normalize public fee IDs inside the locked preview

**Files:**
- Modify: `overseas_costing/services/material_ai_selection_service.py`
- Test: `overseas_costing/tests/test_ai_selection_service.py`

- [ ] **Step 1: Add the minimal mapping helper**

Add immediately before `prepare`:

```python
def _internal_fee_ids(catalog, public_fee_ids):
    public_fees = public_catalog(catalog).get("fees") or []
    internal_fees = catalog.get("fees") or []
    if len(public_fees) != len(internal_fees):
        raise ValueError("当前草稿费用标识无效，请刷新预览。")
    pairs = [
        (
            str(public_fee.get("proposal_id") or ""),
            str(internal_fee.get("proposal_id") or ""),
        )
        for public_fee, internal_fee in zip(public_fees, internal_fees, strict=True)
    ]
    mapping = {
        public_id: internal_id
        for public_id, internal_id in pairs
    }
    if (
        any(not public_id or not internal_id for public_id, internal_id in pairs)
        or len(mapping) != len(public_fees)
        or set(public_fee_ids) - mapping.keys()
    ):
        raise ValueError("所选内容不属于当前草稿，请刷新预览。")
    return [mapping[value] for value in public_fee_ids]
```

- [ ] **Step 2: Apply the mapping only at the preview boundary**

Change the projection call in `prepare` to:

```python
    internal_fee_ids = _internal_fee_ids(catalog, fee_ids)
    projection = rows.project(
        items, catalog, row_ids, internal_fee_ids, mode,
        field_choices=field_choices,
    )
```

Do not change `confirm`: the preview receipt intentionally stores authenticated internal IDs, and confirmation already rebuilds the locked catalog before reconstructing the projection.

- [ ] **Step 3: Run the new test and verify GREEN**

Run the Task 1 command again.

Expected: `1 passed`.

- [ ] **Step 4: Re-run forged-ID and public-payload safety tests**

Run:

```bash
python3 -m pytest -q \
  overseas_costing/tests/test_ai_selection_service.py::test_unknown_row_and_fee_ids_are_rejected \
  overseas_costing/tests/test_ai_selection_service.py::test_public_process_id_prefix_cannot_bypass_opaque_digest_validation \
  overseas_costing/tests/test_material_ai_fill_service.py::test_public_payload_sanitizes_unsafe_text_at_any_dict_or_list_depth
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the isolated fix**

```bash
git add overseas_costing/services/material_ai_selection_service.py \
  overseas_costing/tests/test_ai_selection_service.py
git commit -m "fix: round trip public fee proposal ids"
```

### Task 3: Run release verification

**Files:**
- Verify: `overseas_costing/tests`
- Verify generated assets: `overseas_costing/page/overseas_cost_workbench` and deployed mirror

- [ ] **Step 1: Run the complete Python suite**

```bash
python3 -m pytest -q overseas_costing/tests
```

Expected: exit code 0 with no failed tests.

- [ ] **Step 2: Rebuild generated workbench assets twice**

```bash
python3 overseas_costing/scripts/build_workbench_assets.py
python3 overseas_costing/scripts/build_workbench_assets.py
```

Expected: the second JSON result contains `"changed": []`.

- [ ] **Step 3: Verify syntax, generated mirrors, and working tree scope**

```bash
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
git diff --exit-code -- overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js \
  overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js \
  overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css \
  overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
git status --short
```

Expected: syntax checks pass; generated assets have no diff; only the pre-existing untracked `HANDOFF.md` may remain.

### Task 4: Deploy and verify production

**Files:**
- Deploy workflow: `.github/workflows/deploy-overseas-costing.yml`
- Production site: `https://deeplinkerp.com`

- [ ] **Step 1: Push the verified commit to the deployment and mirror remotes**

```bash
git push production overseas_costing:overseas_costing
git push origin overseas_costing:overseas_costing
```

Expected: both pushes succeed; the `production` push starts `Overseas Costing CI/CD` for `yueweiit/DeepLinkERP`.

- [ ] **Step 2: Watch the exact deployment run**

```bash
gh run list --repo yueweiit/DeepLinkERP \
  --workflow deploy-overseas-costing.yml --branch overseas_costing --limit 3
gh run watch <run-id> --repo yueweiit/DeepLinkERP --exit-status
```

Expected: test and `Deploy to DeepLinkERP` jobs complete successfully.

- [ ] **Step 3: Verify deployed code and service health read-only**

Use the configured SSH identity to verify the production checkout/image contains the new helper and that the login page returns successfully. Do not run migrations, trial calculation, confirmation, or ERP push manually; those remain controlled by the deployment workflow and the user.

- [ ] **Step 4: Verify the real READY draft on batch `vunn2lvq4k`**

Open batch `202609032107000062462`, reuse the existing READY draft, and request the server preview. Verify:

- the red “所选内容不属于当前草稿” error disappears;
- the final material preview renders;
- `确认填充` becomes available when the preview is applicable;
- do not click `确认填充`;
- reread batch/version/fee/calculation/confirmation/ERP fields and verify they are unchanged.

- [ ] **Step 5: Report evidence**

Report the implementation commit, focused/full test results, asset idempotence, GitHub deployment run URL/status, live preview result, and explicit proof that no business confirmation, trial calculation, or ERP push was performed.
