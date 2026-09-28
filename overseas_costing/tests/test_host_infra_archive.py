"""宿主基础设施工件归档：保住"线上跑哪一版"的证据。

这三个文件在宿主机上不受任何版本控制，而 2026-09-27 的 compose pin 事故正是从这里发生的
（流水线全绿、release_id 前进，容器跑的还是旧代码）。归档本身的时效性靠人工重同步
（`deploy/host/README.md`），这里只守住归档内部的几条硬不变量。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "deploy" / "host"

WORKFLOW = ROOT / ".github" / "workflows" / "deploy-overseas-costing.yml"
RESOLVER = ROOT / ".github" / "scripts" / "resolve_base_image.sh"


def test_host_archive_covers_every_file_the_handover_called_out():
    for name in ("compose.custom.yaml", "apps.json", "upgrade_bench.sh", "README.md"):
        assert (ARCHIVE / name).is_file(), name


def test_archived_compose_declares_the_tag_the_deploy_chain_reads_from_compose():
    compose = (ARCHIVE / "compose.custom.yaml").read_text(encoding="utf-8")

    # 宿主 upgrade_bench.sh 只打这一个 tag，代码版本由 apps.json 的分支决定。
    # compose pin 成别的 tag 就会出现"构建了新镜像，容器重建后仍跑老镜像"。
    assert "image: deeplinkerp-custom:v16.23.0-latest" in compose
    assert "deeplinkerp-custom:v16.23.0-" in compose
    for pinned in compose.splitlines():
        if "deeplinkerp-custom:" in pinned:
            assert pinned.strip().endswith("deeplinkerp-custom:v16.23.0-latest")

    # 归档的 tag 就是部署脚本唯一真源读出来的那一行。
    assert "deeplinkerp-custom:" in RESOLVER.read_text(encoding="utf-8")
    assert ".github/scripts/resolve_base_image.sh" in WORKFLOW.read_text(encoding="utf-8")


def test_archived_compose_does_not_leak_production_credentials():
    compose = (ARCHIVE / "compose.custom.yaml").read_text(encoding="utf-8")

    # 仓库是公开的：口令类字段只允许留下占位符，宿主上那份才是真的。
    credential_lines = [
        line for line in compose.splitlines() if "PASSWORD" in line.upper()
    ]
    assert credential_lines == [
        '      MYSQL_ROOT_PASSWORD: "<redacted: only set on the production host>"'
    ]


def test_archived_apps_json_pins_the_overseas_costing_branch_in_a_shared_image():
    entries = json.loads((ARCHIVE / "apps.json").read_text(encoding="utf-8"))

    branches = [entry["branch"] for entry in entries]
    assert "overseas_costing" in branches
    # 12 个 app 烘在同一个镜像里：我们的部署会连带发布别人，别人重建也会覆盖我们。
    assert len(branches) == 12
    assert len(set(branches)) == 12
    assert all(entry["url"].endswith("yueweiit/DeepLinkERP.git") for entry in entries)


def test_archived_upgrade_script_still_matches_what_the_readme_claims():
    script = (ARCHIVE / "upgrade_bench.sh").read_text(encoding="utf-8")
    readme = (ARCHIVE / "README.md").read_text(encoding="utf-8")

    # README 说"只保留最近 2 份 .bak 备份"，脚本就得真的是这么做的。
    assert 'ls -1t "${COMPOSE_FILE}".bak.* 2>/dev/null' in script
    assert "| tail -n +3 " in script
    assert "只保留最近 2 份" in readme
    # README 说回收只碰本项目悬空镜像，脚本里的 label 过滤就得对得上。
    assert 'IMAGE_LABEL="com.deeplinkerp.project=deeplinkerp"' in script
    assert '--filter "label=$IMAGE_LABEL"' in script
    assert 'com.deeplinkerp.project=deeplinkerp' in readme
    assert "--no-cache" in script
