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
