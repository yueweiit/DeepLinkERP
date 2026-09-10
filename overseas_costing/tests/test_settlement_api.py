import importlib
import sys
from types import ModuleType

import pytest
from overseas_costing.tests.test_settlement_writer import setup


def test_ai_rpc_enqueues_unresolved_second_pass_with_nonreserved_worker_argument(setup, monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services.logistics_settlement import ai_matching
    from overseas_costing.services.logistics_settlement.jobs import start_job, save_job
    from overseas_costing.services import allocation_service
    s,*_=setup
    job=start_job(s,mode='initialize',actor='u');job['status']='completed';save_job(s,job)
    calls=[]
    fake=ModuleType('frappe');fake.whitelist=lambda *args,**kwargs:lambda fn:fn
    fake.only_for=lambda role:calls.append(role)
    fake.session=SimpleNamespace(user='u');fake.enqueue=lambda method,**kwargs:calls.append((method,kwargs))
    monkeypatch.setitem(sys.modules,'frappe',fake)
    module_name='overseas_costing.api.logistics_settlement';sys.modules.pop(module_name,None)
    api=importlib.import_module(module_name)
    monkeypatch.setattr(api.runtime,'store',lambda:s)
    monkeypatch.setattr(ai_matching,'start',lambda db,actor:{'id':'ai-job','status':'queued'})
    monkeypatch.setattr(allocation_service,'_ai_config',lambda:{'api_key':'test-only'})
    try:
        assert api.start_ai_matching()['ok']
        assert calls[0]=='System Manager'
        assert calls[1][1]['matching_ai_job_id']=='ai-job'
    finally:
        sys.modules.pop(module_name,None)


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
