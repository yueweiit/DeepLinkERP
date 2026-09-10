from decimal import Decimal
import pytest

from overseas_costing.tests.test_freight_lines import setup_cost
from overseas_costing.services.logistics_settlement import freight_matching as matching, freight_adoption as adoption
from overseas_costing.services.logistics_settlement.fee_policy import select_fees


def adopted():
    s, l, b, v, item, logistics, expense = setup_cost()
    c = matching.rule_pass(s, logistics['id'])[0]
    result = adoption.confirm(s, l, b['name'], v['name'], c['id'], c['revision'], c['line_ids'], 'user')
    return s, l, b, v, item, c, result


def amend(s, l, b, v, previous, action='amount', **values):
    assert callable(getattr(adoption, 'amend', None)), 'Fee amendments require a dedicated operation'
    return adoption.amend(s, l, b['name'], v['name'], previous['claims'][0]['id'], previous['revision'], action,
                          'user', reason='核对原始凭证后更正', **values)


def test_amount_correction_keeps_original_and_repeated_request_is_noop():
    s,l,b,v,item,c,result = adopted()
    original = s.get('freight_line', c['line_ids'][0])
    updated = amend(s,l,b,v,result,amount='2500.123456')
    claim = updated['claims'][0]
    assert claim['amount'] == '2500.123456' and claim['original_amount'] == '2600'
    assert claim['manual_corrected'] and s.get('freight_line', c['line_ids'][0]) == original
    assert l.get('item', item['name'])['gross_weight_kg'] == 10
    count = s.count('freight_application')
    assert amend(s,l,b,v,result,amount='2500.123456')['cached']
    assert s.count('freight_application') == count
    # An ordinary re-adopt of the same immutable evidence cannot undo an override.
    same = adoption.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'user')
    assert adoption.context(s,l,b['name'],same['version'])['claims'][0]['amount'] == '2500.123456'


def test_zero_and_revoke_do_not_revive_estimate_or_pause_sync():
    s,l,b,v,item,c,result = adopted()
    zero = amend(s,l,b,v,result,amount='0')
    fees = select_fees(l.rows('rule'), source_context={'freight':adoption.context(s,l,b['name'],v['name'])})
    assert sum(Decimal(str(x['amount'])) for x in fees) == 30
    gone = amend(s,l,b,v,zero,action='revoke')
    context = adoption.context(s,l,b['name'],v['name'])
    assert context['selected'] and not context['available'] and not context['claims']
    assert not s.get('state','control') and not s.find('freight_claim')
    assert any('待核对' in x for x in adoption.blockers(s,l,b['name'],v['name']))
    assert l.get('item',item['name'])['quantity'] == 1
    assert amend(s,l,b,v,zero,action='revoke')['cached']


def test_stale_and_invalid_corrections_fail_but_revocation_is_allowed():
    s,l,b,v,item,c,result = adopted()
    updated = amend(s,l,b,v,result,amount='2000')
    with pytest.raises(ValueError): amend(s,l,b,v,result,amount='2100')
    source = s.get('source',c['expense_id']); source['invalid']=True
    from overseas_costing.services.logistics_settlement.model import dumps
    s.put('source',{'id':source['id'],'data':dumps(source)})
    with pytest.raises(ValueError): amend(s,l,b,v,updated,amount='2200')
    assert amend(s,l,b,v,updated,action='revoke')['status']=='applied'


def test_correction_freezes_confirmed_version_and_negative_requires_confirmation():
    s,l,b,v,item,c,result = adopted()
    with pytest.raises(ValueError): amend(s,l,b,v,result,amount='-1')
    for invalid in ('NaN','Infinity','1.1234567',''):
        with pytest.raises(ValueError): amend(s,l,b,v,result,amount=invalid)
    l.put('version',v['name'],{'status':'Confirmed'})
    update=amend(s,l,b,v,result,amount='-10',negative_confirmed=True)
    assert update['version'] != v['name']
    assert adoption.context(s,l,b['name'],v['name'])['claims'][0]['amount']=='2600'
    assert adoption.context(s,l,b['name'],update['version'])['claims'][0]['amount']=='-10'


def test_replace_releases_only_old_line_and_failed_change_rolls_back():
    from overseas_costing.tests.test_freight_lines import monthly
    from overseas_costing.services.logistics_settlement.model import parse_source
    s,l,b,v,item,c,result=adopted()
    replacement=monthly();replacement['process_instance_id']='PAY-REPLACEMENT'
    doc=replacement['settlement_documents'][0];doc['id']='replacement-document';doc['file_id']='replacement-file'
    doc['freight_tables'][0]['rows'][0]['fields']['运费金额RMB']='2200'
    expense=s.ingest(parse_source(replacement,logistics_codes={'logistics'}))
    candidate=next(x for x in matching.rule_pass(s,c['logistics_id']) if x['expense_id']==expense['id'])
    kwargs=dict(action='replace',candidate_id=candidate['id'],candidate_revision=candidate['revision'],line_ids=candidate['line_ids'])
    l.fail_rules=True
    with pytest.raises(RuntimeError):amend(s,l,b,v,result,**kwargs)
    assert adoption.context(s,l,b['name'],v['name'])['claims']==result['claims']
    assert s.find('freight_claim')[0]['source_id']==c['expense_id']
    l.fail_rules=False
    updated=amend(s,l,b,v,result,**kwargs)
    assert len(updated['claims'])==1 and updated['claims'][0]['source_id']==expense['id']
    assert s.find('freight_claim')[0]['source_id']==expense['id']
    assert amend(s,l,b,v,result,**kwargs)['cached']


def test_revoked_fee_keeps_workspace_readable_and_preview_incomplete():
    from overseas_costing.services.fee_service import compose_fee_worklist_rows
    from overseas_costing.services.cost_preview_service import preview_comprehensive_cost_data
    from overseas_costing.services.logistics_settlement.fee_policy import row_scopes
    s,l,b,v,item,c,result=adopted();amend(s,l,b,v,result,action='revoke')
    items=l.rows('item',batch=b['name'],version=v['name'])
    from overseas_costing.services.effective_source_values import item_source_context
    ctx=item_source_context(items[0])
    rows=compose_fee_worklist_rows(l.rows('rule'), 'EXPRESS',source_context=ctx)
    assert not any('freight' in row_scopes(r) for r in rows)
    preview=preview_comprehensive_cost_data(items,rows,{'fx_usd_to_rmb':7,'fx_rmb_to_mxn':2.5})
    assert preview['ok'] and not preview['summary']['is_complete']
    assert any(r['reason_code']=='FINAL_FEE_REVIEW_REQUIRED' for r in preview['incomplete_reasons'])


def test_readopt_same_bill_after_revocation_has_new_audited_revision():
    s,l,b,v,item,c,first=adopted();amend(s,l,b,v,first,action='revoke')
    second=adoption.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'user')
    assert second['revision']!=first['revision']
    assert len(s.find('freight_application'))==3
    assert second['claims'][0]['amount']==first['claims'][0]['amount']


def test_database_deadlock_is_not_masked_by_missing_savepoint():
    from overseas_costing.services.logistics_settlement.store import Store
    class QueryDeadlockError(Exception):pass
    store=object.__new__(Store);queries=[]
    def sql(query,*args):
        queries.append(query)
        if query.startswith('ROLLBACK'):raise RuntimeError('SAVEPOINT does not exist')
    store.sql=sql
    with pytest.raises(QueryDeadlockError):
        with store.atomic():raise QueryDeadlockError('InnoDB rolled back transaction')
    assert len(queries)==1
