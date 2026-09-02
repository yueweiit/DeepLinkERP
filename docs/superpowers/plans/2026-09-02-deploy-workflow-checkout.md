# Deploy Workflow Checkout and Script Transfer Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the production deploy job checks out the exact pushed commit and executes the complete frontend asset synchronization script without stdin truncation.

**Architecture:** Keep the existing two-job GitHub Actions workflow, add the official checkout action to the deploy job, and transfer the asset script to a unique remote temporary file before executing it over a separate SSH connection. Protect checkout order and file-based execution with focused source-level pytest regression tests, then use the real GitHub Actions run as the integration verification.

**Tech Stack:** GitHub Actions YAML, `actions/checkout@v4`, Python 3.12, pytest, Git, GitHub CLI.

---

### Task 1: Add checkout-order and file-transfer regression tests

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
    asset_script = ".github/scripts/sync_and_verify_assets.sh"

    assert checkout in deploy_block
    assert deploy_block.index(checkout) < deploy_block.index(asset_script)


def test_asset_script_is_uploaded_and_executed_as_a_remote_file():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy_block = workflow.split("\n  deploy:\n", maxsplit=1)[1]

    assert "< .github/scripts/sync_and_verify_assets.sh" not in deploy_block
    assert 'remote_asset_script="/tmp/sync_and_verify_assets-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.sh"' in deploy_block
    assert "scp -o BatchMode=yes -o StrictHostKeyChecking=yes" in deploy_block
    assert "bash '$remote_asset_script'" in deploy_block
    assert "rm -f '$remote_asset_script'" in deploy_block
```

- [ ] **Step 2: Run the test and verify the current workflow fails for the intended reason**

Run:

```bash
python -m pytest -q overseas_costing/tests/test_deploy_workflow.py
```

Expected for the original workflow: checkout-order failure. After the checkout fix is present, the new file-transfer test fails because the workflow still contains `< .github/scripts/sync_and_verify_assets.sh`.

- [ ] **Step 3: Commit the regression test**

```bash
git add overseas_costing/tests/test_deploy_workflow.py
git commit -m "test: require checkout before deploy asset sync"
```

### Task 2: Add checkout and reliable script transfer

**Files:**
- Modify: `.github/workflows/deploy-overseas-costing.yml`
- Test: `overseas_costing/tests/test_deploy_workflow.py`

- [ ] **Step 1: Insert checkout as the first deploy step and transfer the asset script as a file**

Under `deploy.steps`, add:

```yaml
      - name: Checkout
        uses: actions/checkout@v4

      # Existing secret and SSH setup steps stay unchanged.

      - name: Synchronize and verify frontend assets
        env:
          DEPLOY_HOST: ${{ secrets.DEPLOY_HOST }}
          DEPLOY_USER: ${{ secrets.DEPLOY_USER }}
        run: |
          remote_asset_script="/tmp/sync_and_verify_assets-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.sh"
          scp -o BatchMode=yes -o StrictHostKeyChecking=yes \
            .github/scripts/sync_and_verify_assets.sh \
            "$DEPLOY_USER@$DEPLOY_HOST:$remote_asset_script"
          ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
            "$DEPLOY_USER@$DEPLOY_HOST" \
            "cd /home/yuewei/ERPNext-Docker/frappe_docker && bash '$remote_asset_script'; script_exit_code=\$?; rm -f '$remote_asset_script'; exit \$script_exit_code"
```

Keep every existing test, secret check, server upgrade command, asset script implementation, and login-page check unchanged.

- [ ] **Step 2: Run the focused test and verify it passes**

Run:

```bash
python -m pytest -q overseas_costing/tests/test_deploy_workflow.py
```

Expected: `2 passed`.

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
git remote add production https://github.com/yueweiit/DeepLinkERP.git
git push production backup/overseas-costing-before-density-20260902
git push production overseas_costing
```

Expected: the rollback branch resolves to `3276f6f`, the production `overseas_costing` branch advances, and `Overseas Costing CI/CD` starts in `yueweiit/DeepLinkERP`.

- [ ] **Step 2: Follow the new workflow run to completion**

Run:

```bash
DEPLOY_RUN_ID="$(gh run list -R yueweiit/DeepLinkERP --workflow "Overseas Costing CI/CD" --branch overseas_costing --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch -R yueweiit/DeepLinkERP "$DEPLOY_RUN_ID" --exit-status --interval 5
```

Expected: `Run tests` and `Deploy to DeepLinkERP` both succeed, including upgrade/migration, asset synchronization, and login-page checks.

- [ ] **Step 3: Verify the deployed server commit**

Run:

```bash
ssh -i ~/.ssh/overseas_cost_deploy -o IdentitiesOnly=yes yuewei@155.138.234.129 \
  'cd /home/yuewei/ERPNext-Docker/frappe_docker && backend_container_id=$(docker compose -f compose.custom.yaml ps -q backend) && docker exec "$backend_container_id" sha256sum /home/frappe/frappe-bench/apps/overseas_costing/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css /home/frappe/frappe-bench/apps/overseas_costing/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js'
```

Expected: both hashes equal the corresponding files in the pushed commit.

- [ ] **Step 4: Confirm the rollback reference remains available**

Run:

```bash
git ls-remote --heads production backup/overseas-costing-before-density-20260902
```

Expected: the branch resolves to `3276f6f...`.
