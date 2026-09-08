from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "deploy-overseas-costing.yml"
)


def test_only_production_repository_deploys_and_rebuilds_cannot_overlap():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy = workflow.split("\n  deploy:\n", maxsplit=1)[1]
    assert "if: github.repository == 'yueweiit/DeepLinkERP'" in deploy
    assert "group: overseas-costing-production-deploy" in deploy
    assert "cancel-in-progress: false" in deploy
    assert "github.repository" not in workflow.split("\n  deploy:\n", maxsplit=1)[0]


def test_deploy_job_checks_out_repository_before_running_asset_script():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy_block = workflow.split("\n  deploy:\n", maxsplit=1)[1]

    checkout = "uses: actions/checkout@v4"
    asset_script = ".github/scripts/sync_and_verify_assets.sh"

    assert checkout in deploy_block
    assert deploy_block.index(checkout) < deploy_block.index(asset_script)


def test_production_deploy_requires_deepseek_and_installs_document_runtime() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy = workflow.split("\n  deploy:\n", maxsplit=1)[1]
    assert "DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}" in deploy
    assert 'test -n "$DEEPSEEK_API_KEY"' in deploy
    assert ".github/scripts/install_document_runtime.sh" in deploy
    assert ".github/scripts/configure_material_ai.sh" in deploy
    assert "verify_material_ai_runtime" in deploy
    assert "Preflight DeepSeek connection" in deploy
    assert deploy.index("Preflight DeepSeek connection") < deploy.index("Upgrade and migrate ERP")
    assert "Rollback failed material AI release" in deploy
    assert "if: failure()" in deploy


def test_runtime_installer_backs_up_image_and_requires_ocr_tools() -> None:
    scripts = WORKFLOW_PATH.parent.parent / "scripts"
    installer = (scripts / "install_document_runtime.sh").read_text(encoding="utf-8")
    dockerfile = (scripts / "material-ai-runtime.Containerfile").read_text(encoding="utf-8")
    for package in ("poppler-utils", "tesseract-ocr", "tesseract-ocr-chi-sim", "antiword"):
        assert package in dockerfile
    assert "docker image tag" in installer
    assert "pre-material-ai" in installer
    assert "bench --site" in installer and "backup --with-files" in installer
    assert "tesseract --list-langs" in installer
    assert "chi_sim" in installer
    assert 'mode="${5:-install}"' in installer
    assert 'if [ "$mode" = "preflight" ]' in installer


def test_failed_release_can_restore_image_database_files_and_site_config() -> None:
    scripts = WORKFLOW_PATH.parent.parent / "scripts"
    release = (scripts / "manage_material_ai_release.sh").read_text(encoding="utf-8")
    assert "pre-material-ai-release" in release
    assert "backup --with-files" in release
    assert 'restore "$remote_dir/' in release
    assert "--with-public-files" in release
    assert "--with-private-files" in release
    assert "site_config.json" in release
    assert "docker image tag \"$backup_image\" \"$base_image\"" in release


def test_deepseek_preflight_reads_secret_from_environment_without_printing_it() -> None:
    script = (WORKFLOW_PATH.parent.parent / "scripts" / "preflight_deepseek.py").read_text(encoding="utf-8")
    assert 'os.environ.get("DEEPSEEK_API_KEY"' in script
    assert '"Authorization": f"Bearer {api_key}"' in script
    assert "print(api_key)" not in script


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
