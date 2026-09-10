import importlib
import pytest
from overseas_costing.tests.test_logistics_settlement import store, source, ingest
from overseas_costing.services.logistics_settlement.matching import match_source, confirm_candidate


def ai():
    return importlib.import_module('overseas_costing.services.logistics_settlement.ai_matching')


def pair(store):
    logistics = ingest(store, source('L', 'logistics', text='大墨仓劳保鞋装箱'))
    expense = ingest(store, source('E', text='劳保鞋大墨仓运输结算'))
    return logistics, expense


def test_second_pass_excludes_clear_matches_invalid_bound_and_other_tenants(store):
    logistics, expense = pair(store)
    ingest(store, {**source('bad'), 'status':'TERMINATED'})
    ingest(store, source('clear-L','logistics',text='MXT500999'))
    clear = ingest(store, source('clear-E',text='MXT500999'))
    match_source(store, clear['id'])
    other = ingest(store, source('other-L','logistics',corp='OTHER'))
    prepared = ai().prepare(store)
    assert [e['id'] for e in prepared['groups'][0]['expenses']] == [expense['id']]
    assert other['id'] not in {l['id'] for l in prepared['groups'][0]['logistics']}
    assert 'raw' not in prepared['groups'][0]['expenses'][0]


def test_model_payload_contains_matching_evidence_not_account_or_raw_secrets(store):
    from overseas_costing.services.logistics_settlement.model import dumps
    pair(store)
    row=source('private',text='劳保鞋运输')
    row['raw_payload']['api_key']='PRIVATE_RAW_SECRET'
    row['raw_payload']['formComponentValues'].append({'name':'付款账号','value':'PRIVATE_ACCOUNT'})
    row['raw_payload']['formComponentValues'].extend([
        {'name':'物流收款账号','value':'PRIVATE_LOGISTICS_ACCOUNT'},
        {'name':'付款说明','value':'凭证口令 PRIVATE_PASSWORD'},
        {'name':'运输描述','value':'access_token=PRIVATE_TOKEN'},
    ])
    ingest(store,row)
    payload=dumps(ai().prepare(store)['groups'])
    assert 'PRIVATE_RAW_SECRET' not in payload and 'PRIVATE_ACCOUNT' not in payload
    assert 'PRIVATE_LOGISTICS_ACCOUNT' not in payload
    assert 'PRIVATE_PASSWORD' not in payload and 'PRIVATE_TOKEN' not in payload
    assert '劳保鞋' in payload


def test_deepseek_suggestion_is_persisted_without_binding_and_reused(store):
    logistics, expense = pair(store)
    job = ai().start(store, 'tester')
    calls = []
    def model(messages):
        calls.append(messages)
        return {'matches':[{'expense_id':expense['id'],'logistics_id':logistics['id'],'confidence':0.93,'reason':'仓库、货物名称及发运说明一致'}]}
    result = ai().run(store, job['id'], model)
    assert result['status'] == 'completed' and result['recommended'] == 1
    assert store.count('binding') == 0
    candidate = store.find('candidate')[0]
    assert candidate['method'] == 'deepseek'
    assert 'DeepSeek' in candidate['reason']
    assert ai().start(store, 'tester')['status'] == 'no_work'
    assert len(calls) == 1
    binding = confirm_candidate(store, candidate['id'], candidate['revision'], 'human')
    assert binding['expense_id'] == expense['id']


def test_source_change_during_request_discards_response(store):
    logistics, expense = pair(store)
    job = ai().start(store, 'tester')
    def model(messages):
        ingest(store, {**source('E',text='changed'), 'status':'TERMINATED'})
        return {'matches':[{'expense_id':expense['id'],'logistics_id':logistics['id'],'confidence':1,'reason':'相同'}]}
    assert ai().run(store, job['id'], model)['status'] == 'stale'
    assert store.count('candidate') == 0 and store.count('binding') == 0


def test_source_revoked_before_execution_is_never_sent_to_model(store):
    _, expense=pair(store)
    job=ai().start(store,'u')
    ingest(store,{**source('E'),'status':'TERMINATED'})
    result=ai().run(store,job['id'],lambda messages:pytest.fail('stale evidence was sent to DeepSeek'))
    assert result['status']=='stale'


def test_unknown_target_and_duplicate_response_are_not_accepted(store):
    _, expense = pair(store)
    job = ai().start(store, 'tester')
    bad={'expense_id':expense['id'],'logistics_id':'invented','confidence':1,'reason':'猜测'}
    result=ai().run(store, job['id'], lambda messages:{'matches':[bad,bad]})
    assert result['status'] == 'partial' and result['failed'] == 1
    assert store.count('candidate') == 0


def test_ai_cannot_override_a_manual_rejection(store):
    from overseas_costing.services.logistics_settlement.matching import reject_candidate
    logistics,expense=pair(store)
    # Produce a reviewed AI proposal, then explicitly reject it.
    job=ai().start(store,'u')
    ai().run(store,job['id'],lambda messages:{'matches':[{'expense_id':expense['id'],'logistics_id':logistics['id'],'confidence':.9,'reason':'文字一致'}]})
    candidate=store.find('candidate')[0]
    reject_candidate(store,candidate['id'],candidate['revision'],'u','不同票')
    changed=source('E',text='updated description');changed['updated_at']='2026-09-10T00:00:00+00:00';ingest(store,changed)
    job=ai().start(store,'u')
    result=ai().run(store,job['id'],lambda messages:{'matches':[{'expense_id':expense['id'],'logistics_id':logistics['id'],'confidence':1,'reason':'再猜一次'}]})
    assert result['recommended']==0
    assert store.get('candidate',candidate['id'])['status']=='rejected'


def test_two_expenses_suggesting_one_logistics_require_conflict_review(store):
    logistics,a=pair(store);b=ingest(store,source('E2',text='大墨仓劳保鞋第二张结算'))
    job=ai().start(store,'u')
    ai().run(store,job['id'],lambda messages:{'matches':[{'expense_id':e['id'],'logistics_id':logistics['id'],'confidence':.9,'reason':'文字一致'} for e in (a,b)]})
    assert all(c['status']=='conflict' for c in store.find('candidate'))


def test_partial_response_retries_only_the_remaining_expense(store):
    logistics,a=pair(store);b=ingest(store,source('E2',text='第二批独立货物'))
    first=ai().start(store,'u')
    result=ai().run(store,first['id'],lambda messages:{'matches':[{'expense_id':a['id'],'logistics_id':None,'confidence':0,'reason':'证据不足'}]})
    assert result['status']=='partial' and result['no_match']==1
    second=ai().start(store,'u')
    stored=store.get('state',second['id'])
    assert [e['id'] for g in stored['input']['groups'] for e in g['expenses']]==[b['id']]


def test_source_description_update_invalidates_ai_candidate_and_allows_reanalysis(store):
    from overseas_costing.services.logistics_settlement.matching import refresh_candidate_snapshots
    logistics, expense = pair(store)
    job = ai().start(store, 'u')
    model = lambda messages: {'matches':[{'expense_id':expense['id'],'logistics_id':logistics['id'],'confidence':.9,'reason':'大墨仓鞋子一致'}]}
    ai().run(store, job['id'], model)
    old = store.find('candidate')[0]
    changed = ingest(store, source('E', text='加拿大仓家具'))
    refresh_candidate_snapshots(store, expense['id'])
    current = store.get('candidate', old['id'])
    assert current['status'] == 'stale'
    assert current['expense_snapshot'] != changed['snapshot']
    with pytest.raises(ValueError):
        confirm_candidate(store, old['id'], old['revision'], 'human')
    assert ai().start(store, 'u')['status'] == 'queued'


def test_ai_can_reconsider_stale_rule_pair_using_current_evidence(store):
    logistics = ingest(store, source('L', 'logistics'))
    expense = ingest(store, source('E'))
    old = match_source(store, expense['id'])[0]
    expense = ingest(store, source('E', text='大墨仓劳保鞋'))
    match_source(store, expense['id'])
    assert store.get('candidate', old['id'])['status'] == 'stale'
    job = ai().start(store, 'u')
    result = ai().run(store, job['id'], lambda messages: {'matches':[{'expense_id':expense['id'],'logistics_id':logistics['id'],'confidence':.9,'reason':'货物与发运说明一致'}]})
    assert result['recommended'] == 1
    current = store.get('candidate', old['id'])
    assert current['status'] == 'pending' and current['method'] == 'deepseek'
    assert current['expense_snapshot'] == expense['snapshot']
    assert confirm_candidate(store, current['id'], current['revision'], 'human')['expense_id'] == expense['id']


def test_rule_candidate_loses_old_ai_annotation_after_source_update(store):
    from overseas_costing.services.logistics_settlement.matching import refresh_candidate_snapshots
    logistics = ingest(store, source('L', 'logistics'))
    expense = ingest(store, source('E'))
    ingest(store, source('E2'))
    candidate = match_source(store, expense['id'])[0]
    job = ai().start(store, 'u')
    ai().run(store, job['id'], lambda messages: {'matches':[{'expense_id':expense['id'],'logistics_id':logistics['id'],'confidence':.9,'reason':'OLD_AI_REASON'}]})
    ingest(store, source('E', text='MXT500174 加拿大仓家具'))
    refresh_candidate_snapshots(store, expense['id'])
    current = store.get('candidate', candidate['id'])
    assert all(e['type'] != 'deepseek' for e in current['evidence'])
    assert 'OLD_AI_REASON' not in current['reason']
