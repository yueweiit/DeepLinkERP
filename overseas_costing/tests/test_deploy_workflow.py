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
    assert (
        'remote_asset_script="/tmp/sync_and_verify_assets-'
        '${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.sh"'
        in deploy_block
    )
    assert "scp -o BatchMode=yes -o StrictHostKeyChecking=yes" in deploy_block
    assert "bash '$remote_asset_script'" in deploy_block
    assert "rm -f '$remote_asset_script'" in deploy_block


def test_asset_script_rejects_stale_overseas_costing_release():
    script_path = WORKFLOW_PATH.parents[1] / "scripts" / "sync_and_verify_assets.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "get_batch_dingtalk_approval_detail" in script
    assert "renderDingtalkApprovalTab" in script
