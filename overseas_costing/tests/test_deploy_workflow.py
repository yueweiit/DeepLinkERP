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
