import importlib
import sys
from types import ModuleType

import pytest
from overseas_costing.tests.test_settlement_writer import setup


@pytest.fixture
def batch_api(setup, monkeypatch):
    from types import SimpleNamespace
    s,l,*_=setup
    fake=ModuleType('frappe');fake.whitelist=lambda *args,**kwargs:lambda fn:fn
    fake.session=SimpleNamespace(user='u')
    monkeypatch.setitem(sys.modules,'frappe',fake)
    name='overseas_costing.api.logistics_settlement';sys.modules.pop(name,None)
    api=importlib.import_module(name)
    monkeypatch.setattr(api.runtime,'store',lambda:s)
    monkeypatch.setattr(api,'FrappeLedger',lambda:l)
    monkeypatch.setattr(api,'require_batch_permission',lambda name,*args:name)
    yield api
    sys.modules.pop(name,None)


def test_empty_single_batch_search_does_not_list_global_expenses(setup,batch_api):
    s,l,b,*_=setup
    result=batch_api.find_expenses(b['name'])
    assert result['items'] == [] and result['message']


def test_confirm_checks_candidate_belongs_to_submitted_batch(setup,batch_api):
    s,l,b,v,i,r,binding=setup
    c=s.get('candidate',binding['candidate_id'])
    result=batch_api.confirm_matches([{'id':c['id'],'revision':c['revision']}],batch_name='another-batch')
    assert not result['ok'] and '本票' in result['results'][0]['message']


def test_confirm_keeps_binding_when_adoption_fails(setup,batch_api):
    from overseas_costing.services.logistics_settlement.matching import save_candidate
    s,l,b,v,i,r,binding=setup
    s.sql('DELETE FROM oc_ls_binding')
    c=s.get('candidate',binding['candidate_id']);c['status']='pending';save_candidate(s,c)
    l.fail_rules=True
    result=batch_api.confirm_matches([{'id':c['id'],'revision':c['revision']}],batch_name=b['name'])
    assert result['ok'] and result['confirmed_count'] == 1
    assert result['results'][0]['application_status'] == 'pending'
    assert s.find('binding')[0]['issues'] and s.get('candidate',c['id'])['status'] == 'confirmed'
    assert s.count('application') == 0 and l.get('item',i['name'])['quantity'] == 2


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


def test_per_batch_payment_apis_separate_rules_from_explicit_ai(batch_api, monkeypatch):
    calls = []
    monkeypatch.setattr(
        batch_api.runtime,
        "run_payment_rule_matching",
        lambda batch, version=None: calls.append(("rules", batch, version)) or {"ok": True, "matching": {"status": "completed"}},
    )
    monkeypatch.setattr(
        batch_api.runtime,
        "start_batch_matching",
        lambda batch, version=None: calls.append(("rules", batch, version)) or {"ok": True, "matching": {"status": "completed"}},
    )
    monkeypatch.setattr(
        batch_api.runtime,
        "start_payment_ai_matching",
        lambda batch, version=None, hints=None, offset=0, limit=30: calls.append(("ai", batch, version, hints, offset, limit))
        or {"ok": True, "payment_matching": {"status": "queued"}},
    )
    permissions = []
    monkeypatch.setattr(batch_api, "require_batch_permission", lambda batch, permission="read": permissions.append(permission) or batch)

    legacy = batch_api.start_batch_matching("B", "V")
    direct = batch_api.run_payment_rule_matching("B", "V")
    ai = batch_api.start_payment_ai_matching("B", "V", '{"project":"P"}', "2", "7")

    assert legacy["matching"]["status"] == direct["matching"]["status"] == "completed"
    assert ai["payment_matching"]["status"] == "queued"
    assert calls == [("rules", "B", "V"), ("rules", "B", "V"), ("ai", "B", "V", {"project": "P"}, 2, 7)]
    assert permissions == ["write", "write", "write"]


def test_global_ai_entry_does_not_schedule_freight_payment_ai(batch_api, monkeypatch):
    role_checks = []
    monkeypatch.setattr(batch_api.frappe, "only_for", role_checks.append, raising=False)
    monkeypatch.setattr(batch_api.runtime, "freight_enabled", lambda: True)
    monkeypatch.setattr(
        batch_api.runtime,
        "start_payment_ai_matching",
        lambda *_args, **_kwargs: pytest.fail("global entry scheduled per-batch payment AI"),
    )

    result = batch_api.start_ai_matching()

    assert result["ok"] is False
    assert result["code"] == "PER_BATCH_AI_REQUIRED"
    assert "start_payment_ai_matching" in result["message"]
    assert role_checks == []


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


def test_expected_amendment_conflict_returns_inline_message(batch_api, monkeypatch):
    from overseas_costing.services.logistics_settlement import freight_adoption
    monkeypatch.setattr(batch_api.runtime,'freight_enabled',lambda:True)
    def stale(*args,**kwargs):raise ValueError('费用或成本版本已变化，请刷新后更正')
    monkeypatch.setattr(freight_adoption,'amend',stale)
    result=batch_api.amend_freight_claim('B','V','claim','old','amount','review',amount='10')
    assert result=={'ok':False,'code':'REVIEW_REQUIRED','message':'费用或成本版本已变化，请刷新后更正'}


def test_database_concurrency_conflict_has_safe_inline_error(batch_api, monkeypatch):
    from overseas_costing.services.logistics_settlement import freight_adoption
    class QueryDeadlockError(Exception):pass
    monkeypatch.setattr(batch_api.runtime,'freight_enabled',lambda:True)
    def conflict(*args,**kwargs):raise QueryDeadlockError('private SQL')
    monkeypatch.setattr(freight_adoption,'amend',conflict)
    result=batch_api.amend_freight_claim('B','V','claim','old','amount','review',amount='10')
    assert not result['ok'] and result['code']=='REVIEW_CONFLICT' and '未保存' in result['message']
    assert 'private' not in str(result)
