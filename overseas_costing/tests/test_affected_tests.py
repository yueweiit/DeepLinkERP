from pathlib import Path
from overseas_costing.scripts.run_affected_tests import select_tests


def test_changed_dependency_selects_transitive_test_and_keeps_unrelated_out(tmp_path):
    files={'overseas_costing/services/base.py':'def value(): return 1',
           'overseas_costing/services/consumer.py':'from .base import value',
           'overseas_costing/tests/test_consumer.py':'from overseas_costing.services.consumer import value',
           'overseas_costing/tests/test_other.py':'def test_other(): pass'}
    for name,text in files.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    selected,_=select_tests(tmp_path,['overseas_costing/services/base.py'])
    assert selected==['overseas_costing/tests/test_consumer.py']
    all_tests,_=select_tests(tmp_path,['requirements.txt'])
    assert len(all_tests)==2


def test_workbench_changes_include_browser_behavior_tests():
    root=Path(__file__).resolve().parents[2]
    selected,_=select_tests(root,['overseas_costing/page/overseas_cost_workbench/parts/87-freight.js'])
    assert 'overseas_costing/tests/test_freight_workspace_ui.py' in selected
    assert 'overseas_costing/tests/test_settlement_frontend.py' in selected


def test_github_deploy_scripts_do_not_force_the_full_suite():
    """改动 .github 下的部署脚本不该触发全量测试。

    部署脚本不是 Python、也不属于 overseas_costing，一旦被当成“未映射的运行时
    改动”，测试选择会退化成全量。全量里含既有的红，CI 会因此判失败，Deploy 步骤
    被整体跳过 —— 2026-09-23 新增 .github/scripts/upgrade_and_migrate_erp.sh 时
    正是这个下场。工作流文件仍应牵连 test_affected_tests 自身。
    """
    root=Path(__file__).resolve().parents[2]
    scripts,reason=select_tests(root,['.github/scripts/upgrade_and_migrate_erp.sh'])
    assert scripts==[],f'部署脚本不应选中任何测试，实际选中 {len(scripts)} 个：{reason}'
    workflow,_=select_tests(root,['.github/workflows/deploy-overseas-costing.yml'])
    assert 'overseas_costing/tests/test_affected_tests.py' in workflow
    full,_=select_tests(root,['requirements.txt'])
    assert len(full)>len(scripts)
