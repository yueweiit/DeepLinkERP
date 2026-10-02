"""Exercise release command routing without Docker, SSH or production changes."""
import ast
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/manage_material_ai_release.sh"
INSTALL_SCRIPT = ROOT / ".github/scripts/install_document_runtime.sh"
RECLAIM_SCRIPT = ROOT / ".github/scripts/reclaim_docker_space.sh"
RESOLVER = ROOT / ".github/scripts/resolve_base_image.sh"
# A tag the scripts cannot have hardcoded, so the assertions prove the image comes
# from the compose file rather than from a literal in the script.
COMPOSE_IMAGE = "deeplinkerp-custom:v16.23.0-testbase"
COMPOSE_FILE_BODY = f"""services:
  backend:
    image: {COMPOSE_IMAGE}
  frontend:
    image: {COMPOSE_IMAGE}
"""


def run_rollback(tmp_path, *, missing_image=False, compose_body=COMPOSE_FILE_BODY):
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "workbench-release-test-release.json").write_text(
        json.dumps({"present": True, "value": "previous-release"})
    )
    (tmp_path / "compose.custom.yaml").write_text(compose_body)
    docker = tmp_path / "docker"
    docker.write_text("""#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
with open(os.environ['ROLLBACK_COMMAND_LOG'],'a') as handle:
    handle.write(json.dumps(args)+'\\n')
if args[:2]==['image','inspect'] and os.environ.get('ROLLBACK_MISSING_IMAGE'):
    sys.exit(1)
if 'ps' in args and '-q' in args:
    print('old-'+args[-1])
if args and args[0]=='cp' and args[1].startswith('old-backend:'):
    path=pathlib.Path(args[2]);path.mkdir(parents=True,exist_ok=True)
    (path/'assets.json').write_text('{}')
if 'python' in ' '.join(args) and args[-1]=='-':
    python_log = pathlib.Path(os.environ['ROLLBACK_PYTHON_LOG'])
    with python_log.open('a') as handle:
        handle.write(sys.stdin.read())
        handle.write('\\n# --- next python payload ---\\n')
""")
    docker.chmod(0o755)
    commands = tmp_path / "commands.jsonl"
    python_body = tmp_path / "rollback.py"
    environment = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "ROLLBACK_COMMAND_LOG": str(commands), "ROLLBACK_PYTHON_LOG": str(python_body)}
    if missing_image:
        environment["ROLLBACK_MISSING_IMAGE"] = "1"
    result = subprocess.run(["bash", str(SCRIPT), "rollback-code", str(tmp_path), "example.test", "test-release"],
        env=environment, capture_output=True, text=True)
    return result, [json.loads(line) for line in commands.read_text().splitlines()] if commands.exists() else [], python_body


def test_code_rollback_restores_old_image_assets_and_ui_without_restoring_database(tmp_path):
    result, commands, python_body = run_rollback(tmp_path)
    assert result.returncode == 0, result.stderr
    rendered = [" ".join(command) for command in commands]
    inspect = next(i for i, command in enumerate(commands) if command[:2] == ["image", "inspect"])
    tag = next(i for i, command in enumerate(commands) if command[:2] == ["image", "tag"])
    assert inspect < tag
    assert commands[tag][-2:] == ["deeplinkerp-custom:pre-material-ai-release-test-release", COMPOSE_IMAGE]
    assert any("up -d --no-deps --force-recreate backend" in command for command in rendered[tag + 1:])
    assert any(command[0] == "cp" and command[1].startswith("old-backend:") for command in commands)
    assert any(command[0] == "cp" and command[-1].startswith("old-frontend:") for command in commands)
    assert any("clear-cache" in command for command in rendered)
    assert any("clear-website-cache" in command for command in rendered)
    assert any("backend websocket queue-short queue-long scheduler frontend" in command for command in rendered)
    assert not any(token in command for command in commands for token in ("restore", "migrate", "--with-public-files", "--with-private-files"))
    bodies = python_body.read_text().split("\n# --- next python payload ---\n")
    rollback_body = next(body for body in bodies if "install.ensure_workspace_sidebar()" in body)
    ast.parse(rollback_body)
    assert "install._set_workspace_content(" in rollback_body
    assert "install.ensure_workspace()" not in rollback_body
    assert "drop" not in rollback_body.lower() and "delete" not in rollback_body.lower()
    assert any(
        "set-config overseas_costing_release_id previous-release" in command
        for command in rendered
    )


def test_code_rollback_with_missing_backup_image_stops_before_service_changes(tmp_path):
    result, commands, _ = run_rollback(tmp_path, missing_image=True)
    assert result.returncode != 0
    assert len(commands) == 1 and commands[0][:2] == ["image", "inspect"]


def test_migrating_workflow_uses_state_aware_rollback_and_retains_recovery_modes():
    workflow = (ROOT / ".github/workflows/deploy-overseas-costing.yml").read_text()
    rollback = workflow.split("- name: Rollback failed ERP release", 1)[1].split("\n      - name:", 1)[0]
    assert "' rollback-safe " in rollback
    assert "' rollback " not in rollback
    assert "' rollback-code " not in rollback
    script = SCRIPT.read_text()
    assert "prepare) prepare_release" in script
    assert "rollback-safe) rollback_safe_release" in script
    assert "rollback) rollback_release" in script
    assert "rollback-code) rollback_code_release" in script
    assert 'restore "$remote_dir/' in script


def test_finish_marks_database_as_committed_before_reopening_the_site():
    script = SCRIPT.read_text()
    finish = script.split("finish_release()", 1)[1].split("rollback_release()", 1)[0]
    assert finish.index("mark_database_committed") < finish.index("restore_maintenance_mode")

    safe_rollback = script.split("rollback_safe_release()", 1)[1].split("rollback_code_release()", 1)[0]
    assert "database_is_committed" in safe_rollback
    committed_branch = safe_rollback.split("database_is_committed", 1)[1].split("fi", 1)[0]
    assert "restore_maintenance_mode" in committed_branch
    assert "rollback_release" not in committed_branch


def _resolve(tmp_path, compose_body):
    compose = tmp_path / "compose.custom.yaml"
    if compose_body is not None:
        compose.write_text(compose_body)
    return subprocess.run(
        ["bash", "-c", '. "$1"; resolve_base_image "$2"', "_", str(RESOLVER), str(compose)],
        capture_output=True,
        text=True,
    )


def test_resolver_reads_the_image_the_compose_file_actually_runs(tmp_path):
    result = _resolve(tmp_path, COMPOSE_FILE_BODY)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == COMPOSE_IMAGE


def test_resolver_reports_when_compose_declares_no_custom_image(tmp_path):
    result = _resolve(tmp_path, "services:\n  db:\n    image: mariadb:11.8\n")
    assert result.returncode != 0
    assert "No deeplinkerp-custom image" in result.stderr


def test_resolver_reports_a_missing_compose_file(tmp_path):
    result = _resolve(tmp_path, None)
    assert result.returncode != 0
    assert "Compose file not found" in result.stderr


def test_deploy_scripts_take_the_base_image_from_compose_not_a_literal():
    for script in (SCRIPT, INSTALL_SCRIPT, RECLAIM_SCRIPT):
        body = script.read_text()
        assert 'base_image="deeplinkerp-custom:' not in body
        assert 'base_image="$(resolve_base_image "$compose_file"' in body
    workflow = (ROOT / ".github/workflows/deploy-overseas-costing.yml").read_text()
    assert ".github/scripts/resolve_base_image.sh" in workflow
    assert workflow.count("BASE_IMAGE_SCRIPT=") == 7


def test_install_script_explains_a_base_image_that_was_reclaimed():
    # A bare `docker image inspect` failed with "No such image" and nothing else,
    # which is how a repinned compose file and the build-cache reclaim step in
    # front of it turned into an unexplained deploy failure.
    body = INSTALL_SCRIPT.read_text()
    assert 'if ! docker image inspect "$base_image" >/dev/null 2>&1; then' in body
    assert "declared by $compose_file) is missing on this host" in body
    assert "recreate the containers first" in body
    assert '\ndocker image inspect "$base_image" >/dev/null\n' not in body
