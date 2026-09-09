import pytest
from overseas_costing.tests.test_settlement_writer import setup
from overseas_costing.tests.test_logistics_settlement import source, ingest
from overseas_costing.services.logistics_settlement.writer import apply_binding
from overseas_costing.services.logistics_settlement import runtime


def attach_runtime(monkeypatch, s, ledger):
    monkeypatch.setattr(runtime, 'installed', lambda: True)
    monkeypatch.setattr(runtime.Store, 'frappe', lambda: s)
    monkeypatch.setattr(runtime, 'FrappeLedger', lambda: ledger)
    monkeypatch.setattr(runtime, 'archive', lambda: pytest.fail('normal page query contacted upstream'))


def test_normal_batch_query_uses_only_local_persisted_data(setup, monkeypatch):
    s,l,b,v,i,r,binding = setup
    attach_runtime(monkeypatch,s,l)
    result=runtime.batch_status(b['name'])
    assert result['expense']['amount']=='100'
    assert result['binding']['application_status']=='pending'
    assert result['expense']['open_url'].startswith('dingtalk://')


def test_invalid_or_changed_source_blocks_current_result_without_restoring_estimates(setup, monkeypatch):
    s,l,b,v,i,r,binding=setup
    attach_runtime(monkeypatch,s,l)
    apply_binding(s,l,binding['id'],'u')
    row=source('E',amount='0');row.update(status='COMPLETED',result='refuse')
    ingest(s,row)
    assert runtime.calculation_blockers(b['name'],v['name'])
    assert l.get('rule',r['name'])['is_enabled']==0


def test_confirmed_final_version_cannot_be_recalculated(setup, monkeypatch):
    s,l,b,v,i,r,binding=setup
    attach_runtime(monkeypatch,s,l)
    apply_binding(s,l,binding['id'],'u')
    l.put('version',v['name'],{'status':'Confirmed'})
    assert any('已确认' in reason for reason in runtime.calculation_blockers(b['name'],v['name'],for_calculation=True))


def test_final_rule_and_quantity_cannot_diverge_from_adopted_source(setup, monkeypatch):
    s,l,b,v,i,r,binding=setup
    attach_runtime(monkeypatch,s,l)
    apply_binding(s,l,binding['id'],'u')
    final=next(rule for rule in l.rows('rule') if rule.get('is_final'))
    l.put('rule',final['name'],{'amount':999})
    assert any('费用' in reason and '不一致' in reason for reason in runtime.calculation_blockers(b['name'],v['name']))
    l.put('rule',final['name'],{'amount':'100'})
    import json
    meta=json.loads(l.get('item',i['name'])['extra_json']);meta['settlement_cargo']['quantity']='999'
    l.put('item',i['name'],{'extra_json':json.dumps(meta)})
    assert any('数量' in reason and '不一致' in reason for reason in runtime.calculation_blockers(b['name'],v['name']))


def test_historical_version_shows_its_adopted_expense_snapshot(setup, monkeypatch):
    from copy import deepcopy
    s,l,b,v,i,r,binding=setup
    attach_runtime(monkeypatch,s,l)
    apply_binding(s,l,binding['id'],'u')
    l.put('version',v['name'],{'status':'Confirmed'})
    original=s.get('source',binding['expense_id'])
    row=source('E',amount='120');row['updated_at']='2026-09-09T04:00:00+00:00'
    ingest(s,row);apply_binding(s,l,binding['id'],'u')
    old=runtime.batch_status(b['name'],v['name'])
    current=runtime.batch_status(b['name'])
    assert old['historical'] and old['expense']['amount']=='100'
    assert old['binding']['application_status']=='historical' and not old['item_reviews']
    assert not current['historical'] and current['expense']['amount']=='120'


def test_scheduler_cannot_undo_stop_while_upstream_health_is_in_flight(setup,monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services.logistics_settlement.model import dumps
    s,l,*_=setup;attach_runtime(monkeypatch,s,l)
    s.put('state',{'id':'control','updated_at':'t','data':dumps({'enabled':True})})
    class Archive:
        def health(self):
            s.put('state',{'id':'control','updated_at':'later','data':dumps({'enabled':False})})
            return {}
    monkeypatch.setattr(runtime,'archive',lambda:Archive())
    monkeypatch.setattr(runtime,'frappe',SimpleNamespace(session=SimpleNamespace(user='u')))
    monkeypatch.setattr(runtime,'enqueue',lambda _:pytest.fail('stopped scheduler enqueued work'))
    assert runtime.scheduled_sync()['skipped']
    assert not s.get('state','control')['enabled'] and s.count('job')==0


def test_pending_worker_cannot_reapply_a_rollback_from_stale_inventory(setup,monkeypatch):
    from overseas_costing.services.logistics_settlement.rollback import restore_application
    from overseas_costing.services.logistics_settlement.model import dumps
    s,l,b,v,i,r,binding=setup;attach_runtime(monkeypatch,s,l)
    applied=apply_binding(s,l,binding['id'],'u')
    s.put('state',{'id':'control','updated_at':'t','data':dumps({'enabled':True})})
    original_find=s.find; rolled_back=[]
    def interleave(table,**filters):
        rows=original_find(table,**filters)
        if table=='binding' and filters.get('limit')==50 and not rolled_back:
            rolled_back.append(True)
            restore_application(s,l,applied['last_application'],applied['revision'],'worker inventory race','u')
        return rows
    monkeypatch.setattr(s,'find',interleave)
    runtime.resume_pending()
    assert rolled_back and not s.get('state','control')['enabled']
    assert s.get('binding',binding['id'])['application_status']=='rolled_back'
    assert str(l.get('item',i['name'])['quantity'])=='2'


def test_queued_document_resume_rechecks_stop_after_inventory(setup,monkeypatch):
    from overseas_costing.services.logistics_settlement.model import dumps
    s,l,b,v,i,r,binding=setup;attach_runtime(monkeypatch,s,l)
    s.put('state',{'id':'control','updated_at':'t','data':dumps({'enabled':True})})
    s.put('document_sync',{'id':'queue','source_id':binding['logistics_id'],'batch':b['name'],'status':'queued','data':'{}'})
    original_find=s.find
    def interleave(table,**filters):
        rows=original_find(table,**filters)
        if table=='document_sync' and filters.get('status')=='queued':
            s.put('state',{'id':'control','updated_at':'stop','data':dumps({'enabled':False})})
        return rows
    monkeypatch.setattr(s,'find',interleave)
    monkeypatch.setattr(runtime,'apply_source',lambda _:pytest.fail('stopped document queue applied work'))
    runtime.resume_pending()
    assert s.get('document_sync','queue')['status']=='queued'
