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


def test_deploy_prewarms_packing_cache_before_switching_frontend_assets() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy = workflow.split("\n  deploy:\n", maxsplit=1)[1]

    prewarm = "overseas_costing.services.packing_sheet_cache_service.prewarm_catalog_cache"
    assets = "Synchronize and verify frontend assets"
    assert prewarm in deploy
    assert deploy.index("Upgrade and migrate ERP") < deploy.index(prewarm) < deploy.index(assets)


def test_deploy_cleans_legacy_route_revision_before_migrate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy = workflow.split("\n  deploy:\n", maxsplit=1)[1]

    cleanup = "bench --site deeplinkerp.com execute overseas_costing.install.before_migrate"
    assert cleanup in deploy
    assert deploy.index("upgrade_bench.sh") < deploy.index(cleanup) < deploy.index("migrate_site.sh")
    assert "Inspect and normalize route revision before upgrade" in deploy
    assert ".github/scripts/prepare_route_revision_migration.sh" in deploy
    assert deploy.index("Prepare production rollback point") < deploy.index(
        "Inspect and normalize route revision before upgrade"
    ) < deploy.index("Upgrade and migrate ERP")


def test_route_revision_migration_script_backups_and_bounds_legacy_values() -> None:
    script = (
        WORKFLOW_PATH.parent.parent
        / "scripts"
        / "prepare_route_revision_migration.sh"
    ).read_text(encoding="utf-8")

    assert "backup --with-files" in script
    assert "information_schema.columns" in script
    assert "ALTER COLUMN `route_revision` SET DEFAULT 0" in script
    assert "NOT REGEXP ''^[0-9]+$''" in script
    assert "`route_revision` IS NULL" in script
    assert "SQL_SAFE_UPDATES = 0" in script
    assert "2147483647" in script


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
    assert "--kwargs '\"'\"'{\"check_connection\": True}'\"'\"'" in deploy
    assert "--kwargs '\"'\"'{\"check_connection\": true}'\"'\"'" not in deploy


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
    assert installer.count('restart frontend') >= 2
    assert 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in installer
    assert 'asset_sync_script="${ASSET_SYNC_SCRIPT:-}"' in installer
    assert 'asset_sync_script="$script_dir/sync_and_verify_assets.sh"' in installer
    assert 'COMPOSE_FILE="$compose_file" SITE_NAME="$site_name" bash "$asset_sync_script"' in installer


def test_material_ai_configuration_reloads_frontend_after_backend_restart() -> None:
    scripts = WORKFLOW_PATH.parent.parent / "scripts"
    configurator = (scripts / "configure_material_ai.sh").read_text(encoding="utf-8")

    assert configurator.index("restart backend") < configurator.index("restart frontend")
    assert 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in configurator
    assert 'asset_sync_script="${ASSET_SYNC_SCRIPT:-}"' in configurator
    assert 'asset_sync_script="$script_dir/sync_and_verify_assets.sh"' in configurator
    assert 'COMPOSE_FILE="$compose_file" SITE_NAME="$site_name" bash "$asset_sync_script"' in configurator


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
    assert "backend websocket queue-short queue-long scheduler frontend" in release


def test_login_smoke_waits_for_restarted_backend() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "--retry-all-errors" in workflow
    assert "--retry-max-time 90" in workflow
    assert "--retry-delay 5" in workflow


def test_deepseek_preflight_reads_secret_from_environment_without_printing_it() -> None:
    script = (WORKFLOW_PATH.parent.parent / "scripts" / "preflight_deepseek.py").read_text(encoding="utf-8")
    assert 'os.environ.get("DEEPSEEK_API_KEY"' in script
    assert '"Authorization": f"Bearer {api_key}"' in script
    assert "print(api_key)" not in script


def test_deepseek_preflight_disables_thinking_and_retries_empty_json_output() -> None:
    script = (WORKFLOW_PATH.parent.parent / "scripts" / "preflight_deepseek.py").read_text(encoding="utf-8")

    assert '"thinking": {"type": "disabled"}' in script
    assert '"response_format": {"type": "json_object"}' in script
    assert '"max_tokens": 128' in script
    assert "MAX_ATTEMPTS = 3" in script
    assert "DEEPSEEK_VISION_MODEL" in script
    assert "deepseek-v4-flash-vision-exp" in script
    assert '"type": "image_url"' in script
    vision_payload = script.split("def _vision_request_payload", 1)[1].split("def _call", 1)[0]
    assert '"thinking"' not in vision_payload
    assert '"response_format"' not in vision_payload


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
    assert "rm -f '/tmp/manage_material_ai_release-" in deploy_block
    assert "'/tmp/sync_and_verify_assets-" in deploy_block


def test_container_restart_scripts_reuse_asset_sync_gate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy_block = workflow.split("\n  deploy:\n", maxsplit=1)[1]
    release = (WORKFLOW_PATH.parents[1] / "scripts" / "manage_material_ai_release.sh").read_text(encoding="utf-8")
    asset_script = (WORKFLOW_PATH.parents[1] / "scripts" / "sync_and_verify_assets.sh").read_text(encoding="utf-8")

    assert "ASSET_SYNC_SCRIPT='/tmp/sync_and_verify_assets-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}.sh'" in deploy_block
    assert deploy_block.index("sync_and_verify_assets.sh") < deploy_block.index("Install document parsing runtime")
    assert 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in release
    assert 'asset_sync_script="$script_dir/sync_and_verify_assets.sh"' in release
    assert "VERIFY_APP_RELEASE=0" in release
    assert 'VERIFY_APP_RELEASE="${VERIFY_APP_RELEASE:-1}"' in asset_script
    assert "Skip overseas costing application release verification" in asset_script


def test_asset_script_rejects_stale_overseas_costing_release():
    script_path = WORKFLOW_PATH.parents[1] / "scripts" / "sync_and_verify_assets.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "get_batch_dingtalk_approval_detail" in script
    assert "renderDingtalkApprovalTab" in script
