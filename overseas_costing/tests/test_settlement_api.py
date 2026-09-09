import importlib
import sys
from types import ModuleType

import pytest
from overseas_costing.tests.test_settlement_writer import setup


def test_manual_selection_of_current_expense_preserves_confirmed_candidate(setup, monkeypatch):
    s,l,b,v,i,r,binding=setup
    fake=ModuleType('frappe');fake.whitelist=lambda *args,**kwargs:lambda fn:fn
    monkeypatch.setitem(sys.modules,'frappe',fake)
    module_name='overseas_costing.api.logistics_settlement'
    sys.modules.pop(module_name,None)
    api=importlib.import_module(module_name)
    monkeypatch.setattr(api.runtime,'store',lambda:s)
    monkeypatch.setattr(api,'require_batch_permission',lambda name,*args:name)
    before=s.get('candidate',binding['candidate_id'])
    try:
        with pytest.raises(ValueError,match='已经关联'):
            api.prepare_manual_candidate(b['name'],binding['expense_id'],'重复选择')
        assert s.get('candidate',binding['candidate_id'])==before
    finally:
        sys.modules.pop(module_name,None)
