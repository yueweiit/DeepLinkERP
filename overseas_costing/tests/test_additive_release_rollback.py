"""Exercise release command routing without Docker, SSH or production changes."""
import ast
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/manage_material_ai_release.sh"


def run_rollback(tmp_path, *, missing_image=False):
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
    pathlib.Path(os.environ['ROLLBACK_PYTHON_LOG']).write_text(sys.stdin.read())
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
    assert commands[tag][-2:] == ["deeplinkerp-custom:pre-material-ai-release-test-release", "deeplinkerp-custom:v16.23.0-latest"]
    assert any("up -d --no-deps --force-recreate backend" in command for command in rendered[tag + 1:])
    assert any(command[0] == "cp" and command[1].startswith("old-backend:") for command in commands)
    assert any(command[0] == "cp" and command[-1].startswith("old-frontend:") for command in commands)
    assert any("clear-cache" in command for command in rendered)
    assert any("clear-website-cache" in command for command in rendered)
    assert any("backend websocket queue-short queue-long scheduler frontend" in command for command in rendered)
    assert not any(token in command for command in commands for token in ("restore", "migrate", "--with-public-files", "--with-private-files"))
    body = python_body.read_text()
    ast.parse(body)
    assert "install.ensure_workspace_sidebar()" in body
    assert "install._set_workspace_content(" in body
    assert "install.ensure_workspace()" not in body
    assert "drop" not in body.lower() and "delete" not in body.lower()


def test_code_rollback_with_missing_backup_image_stops_before_service_changes(tmp_path):
    result, commands, _ = run_rollback(tmp_path, missing_image=True)
    assert result.returncode != 0
    assert len(commands) == 1 and commands[0][:2] == ["image", "inspect"]


def test_additive_workflow_uses_code_rollback_and_retains_legacy_recovery_mode():
    workflow = (ROOT / ".github/workflows/deploy-overseas-costing.yml").read_text()
    rollback = workflow.split("- name: Rollback failed material AI release", 1)[1].split("\n      - name:", 1)[0]
    assert "' rollback-code " in rollback
    assert "' rollback " not in rollback
    script = SCRIPT.read_text()
    assert "prepare) prepare_release" in script
    assert "rollback) rollback_release" in script
    assert "rollback-code) rollback_code_release" in script
    assert 'restore "$remote_dir/' in script
