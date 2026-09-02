# Deploy Workflow Checkout Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the production deploy job checks out the exact pushed commit before it reads the repository-owned frontend asset synchronization script.

**Architecture:** Keep the existing two-job GitHub Actions workflow and add the official checkout action only to the deploy job. Protect the ordering requirement with a focused source-level pytest regression test, then use the real GitHub Actions run as the integration verification.

**Tech Stack:** GitHub Actions YAML, `actions/checkout@v4`, Python 3.12, pytest, Git, GitHub CLI.

---

### Task 1: Add the checkout-order regression test

**Files:**
- Create: `overseas_costing/tests/test_deploy_workflow.py`
- Read: `.github/workflows/deploy-overseas-costing.yml`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "deploy-overseas-costing.yml"
)


def test_deploy_job_checks_out_repository_before_running_asset_script():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy_block = workflow.split("\n  deploy:\n", maxsplit=1)[1]

    checkout = "uses: actions/checkout@v4"
    asset_script = "< .github/scripts/sync_and_verify_assets.sh"

    assert checkout in deploy_block
    assert deploy_block.index(checkout) < deploy_block.index(asset_script)
```

- [ ] **Step 2: Run the test and verify the current workflow fails for the intended reason**

Run:

```bash
python -m pytest -q overseas_costing/tests/test_deploy_workflow.py
```

Expected: one failure at `assert checkout in deploy_block`, proving the deploy job lacks a checkout step.

- [ ] **Step 3: Commit the regression test**

```bash
git add overseas_costing/tests/test_deploy_workflow.py
git commit -m "test: require checkout before deploy asset sync"
```

### Task 2: Add the minimal deploy checkout step

**Files:**
- Modify: `.github/workflows/deploy-overseas-costing.yml`
- Test: `overseas_costing/tests/test_deploy_workflow.py`

- [ ] **Step 1: Insert checkout as the first deploy step**

Under `deploy.steps`, add:

```yaml
      - name: Checkout
        uses: actions/checkout@v4
```

Keep every existing test, secret check, SSH command, asset synchronization command, and login-page check unchanged.

- [ ] **Step 2: Run the focused test and verify it passes**

Run:

```bash
python -m pytest -q overseas_costing/tests/test_deploy_workflow.py
```

Expected: `1 passed`.

- [ ] **Step 3: Run the full local verification suite**

Run:

```bash
python -m pytest -q overseas_costing/tests
python -m compileall -q overseas_costing
git diff --check
```

Expected: all pytest tests pass, compileall exits zero, and `git diff --check` prints no errors.

- [ ] **Step 4: Commit the workflow fix**

```bash
git add .github/workflows/deploy-overseas-costing.yml
git commit -m "fix: checkout repository before deploy asset sync"
```

### Task 3: Push and verify production deployment

**Files:**
- No file changes.

- [ ] **Step 1: Push the verified commits**

Run:

```bash
git push origin overseas_costing
```

Expected: the remote `overseas_costing` branch advances and starts `Overseas Costing CI/CD`.

- [ ] **Step 2: Follow the new workflow run to completion**

Run:

```bash
DEPLOY_RUN_ID="$(gh run list --workflow "Overseas Costing CI/CD" --branch overseas_costing --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$DEPLOY_RUN_ID" --exit-status --interval 5
```

Expected: `Run tests` and `Deploy to DeepLinkERP` both succeed, including upgrade/migration, asset synchronization, and login-page checks.

- [ ] **Step 3: Verify the deployed server commit**

Run:

```bash
ssh -i ~/.ssh/overseas_cost_deploy -o IdentitiesOnly=yes yuewei@155.138.234.129 \
  'cd /home/yuewei/ERPNext-Docker/frappe_docker && git rev-parse HEAD && git status --short'
```

Expected: `HEAD` equals the pushed `overseas_costing` commit and no tracked deployment files are modified.

- [ ] **Step 4: Confirm the rollback reference remains available**

Run:

```bash
git ls-remote --heads origin backup/overseas-costing-before-density-20260902
```

Expected: the branch resolves to `3276f6f...`.
