import json
import pytest
from overseas_costing.tests.test_logistics_settlement import store, source, ingest
from overseas_costing.services.logistics_settlement import batch_matching as bm
from overseas_costing.services.logistics_settlement.matching import match_source, reject_candidate


def pair(store, text='鞋子大墨仓'):
    return ingest(store, source('L', 'logistics', text=text)), ingest(store, source('E', text=text))


def reply(messages):
    group = json.loads(messages[-1]['content'])
    return {'matches': [{'expense_id': e['id'], 'logistics_id': group['logistics'][0]['id'],
                         'confidence': .9, 'reason': '仓库和货物一致'} for e in group['expenses']]}


def test_single_batch_rules_save_candidates_without_touching_another_logistics(store):
    l, e = pair(store, 'MXT500174')
    other = ingest(store, source('other', 'logistics', text='MXT500174'))
    job = bm.start(store, l['id'], 'human')
    result = bm.run(store, job['id'], reply)
    assert result['status'] == 'completed'
    assert all(c['logistics_id'] == l['id'] for c in store.find('candidate'))
    assert not store.find('candidate', logistics_id=other['id'])
    assert not store.find('binding')


def test_clear_rules_do_not_call_ai_and_reopening_reuses_result(store):
    l, e = pair(store, 'MXT500174')
    job = bm.start(store, l['id'], 'human')
    bm.run(store, job['id'], lambda _: pytest.fail('clear rule sent to AI'))
    again = bm.start(store, l['id'], 'human')
    assert again['status'] == 'completed' and again['cached']
    assert again['id'] == job['id'] and store.count('candidate') == 1


def test_ai_receives_only_this_logistics_same_corp_active_expenses_and_caches_no_match(store):
    l, e = pair(store)
    ingest(store, source('other', 'logistics', text='OTHER LOGISTICS PRIVATE'))
    ingest(store, source('other-corp', corp='D', text='OTHER CORP PRIVATE'))
    ingest(store, {**source('rejected', text='REJECTED PRIVATE'), 'result': 'refuse'})
    job = bm.start(store, l['id'], 'human')
    seen = []
    def model(messages):
        group = json.loads(messages[-1]['content']); seen.append(group)
        assert [v['id'] for v in group['logistics']] == [l['id']]
        assert [v['id'] for v in group['expenses']] == [e['id']]
        assert 'PRIVATE' not in json.dumps(messages)
        return {'matches': [{'expense_id': e['id'], 'logistics_id': None, 'confidence': 0, 'reason': '证据不足'}]}
    result = bm.run(store, job['id'], model)
    assert result['status'] == 'completed' and result['no_match'] == 1
    assert bm.start(store, l['id'], 'human')['cached'] and len(seen) == 1
    ingest(store, source('new-expense', text='新支出'))
    assert bm.status(store, l['id'])['status'] == 'stale'
    assert bm.start(store, l['id'], 'human')['status'] == 'queued'


def test_changed_source_during_paid_request_fences_writeback(store):
    l, e = pair(store)
    job = bm.start(store, l['id'], 'human')
    def model(messages):
        ingest(store, source('E', text='已经修改'))
        return reply(messages)
    assert bm.run(store, job['id'], model)['status'] == 'stale'
    assert store.count('candidate') == 0


def test_existing_ai_candidate_is_reused_and_rejection_not_recommended_again(store):
    l, e = pair(store)
    job = bm.start(store, l['id'], 'human'); bm.run(store, job['id'], reply)
    c = store.find('candidate')[0]
    reject_candidate(store, c['id'], c['revision'], 'human', '不是同一票')
    job = bm.start(store, l['id'], 'human')
    result = bm.run(store, job['id'], lambda _: pytest.fail('unchanged rejected pair sent to AI'))
    assert result['status'] == 'completed' and store.get('candidate', c['id'])['status'] == 'rejected'


def test_partial_ai_retry_only_sends_failed_expense(store):
    l, e = pair(store); e2 = ingest(store, source('E2', text='另一张'))
    job = bm.start(store, l['id'], 'human')
    result = bm.run(store, job['id'], lambda _: {'matches': [{'expense_id': e['id'], 'logistics_id': None, 'confidence': 0, 'reason': '无匹配'}]})
    assert result['status'] == 'partial'
    retry = bm.start(store, l['id'], 'human')
    def model(messages):
        assert [v['id'] for v in json.loads(messages[-1]['content'])['expenses']] == [e2['id']]
        return reply(messages)
    assert bm.run(store, retry['id'], model)['status'] == 'completed'


def test_existing_global_candidate_reused_without_new_paid_request(store):
    l, e = pair(store, 'MXT500174'); match_source(store, e['id'])
    result = bm.start(store, l['id'], 'human')
    assert result['status'] == 'completed' and result['cached']


def test_recommended_partial_result_does_not_skip_remaining_ai_on_retry(store):
    l,e=pair(store);e2=ingest(store,source('E2',text='更多信息'))
    job=bm.start(store,l['id'],'u')
    result=bm.run(store,job['id'],lambda messages:{'matches':[reply(messages)['matches'][0]]})
    assert result['status']=='partial'
    job=bm.start(store,l['id'],'u')
    calls=[]
    result=bm.run(store,job['id'],lambda messages:calls.append(messages) or reply(messages))
    assert len(calls)==1 and result['status']=='completed' and result['recommended']==2


def test_new_pool_after_ai_recommendation_is_reanalysed(store):
    l,e=pair(store);job=bm.start(store,l['id'],'u');bm.run(store,job['id'],reply)
    ingest(store,source('E2',text='另一票描述'))
    job=bm.start(store,l['id'],'u');calls=[]
    result=bm.run(store,job['id'],lambda messages:calls.append(messages) or reply(messages))
    assert calls and result['recommended']==2


def test_matching_summary_includes_only_local_source_comment_evidence(store):
    row=source('L','logistics',text='本票');row['raw_payload']['operationRecords']=[{'remark':'本票劳保鞋补充装箱说明'}]
    row['raw_payload']['comments']=[{'text':'本票空运补充'}, {'text':'银行账户 1234567890123456'}]
    data=bm.source_summary(ingest(store,row))
    assert '本票劳保鞋' in json.dumps(data,ensure_ascii=False) and '本票空运' in json.dumps(data,ensure_ascii=False)
    assert '1234567890123456' not in json.dumps(data)


def test_invalidated_candidate_does_not_leave_completed_cache_trapping_user(store):
    from overseas_costing.services.logistics_settlement.matching import invalidate_source_candidates
    l,e=pair(store);job=bm.start(store,l['id'],'u');bm.run(store,job['id'],reply)
    invalidate_source_candidates(store,e['id']);match_source(store,e['id'])
    assert bm.status(store,l['id'])['status']=='stale'
    retry=bm.start(store,l['id'],'u')
    assert retry['status']=='queued'
    assert bm.run(store,retry['id'],reply)['recommended']==1
    assert bm.candidates(store,l)


def test_ai_skips_other_logistics_clear_candidate(store):
    l,e=pair(store)
    other=ingest(store,source('OTHER','logistics',text='MXT500999'))
    clear=ingest(store,source('CLEAR',text='MXT500999'));match_source(store,clear['id'])
    job=bm.start(store,l['id'],'u')
    def model(messages):
        assert clear['id'] not in [r['id'] for r in json.loads(messages[-1]['content'])['expenses']]
        return reply(messages)
    assert bm.run(store,job['id'],model)['status']=='completed'


def test_same_expense_ai_candidates_require_explicit_conflict_confirmation(store):
    from overseas_costing.services.logistics_settlement.matching import confirm_candidate, save_candidate
    l,e=pair(store);other=ingest(store,source('OTHER','logistics',text='其他票'))
    job=bm.start(store,l['id'],'u');bm.run(store,job['id'],reply)
    c=store.find('candidate')[0]
    from overseas_costing.services.logistics_settlement.model import digest
    save_candidate(store,{**c,'id':digest(other['id'],e['id']),'logistics_id':other['id'],'logistics_snapshot':other['snapshot']})
    with pytest.raises(ValueError,match='关联冲突'):
        confirm_candidate(store,c['id'],c['revision'],'u')


def test_imported_multi_candidate_cache_checks_every_recommendation(store):
    from overseas_costing.services.logistics_settlement.matching import invalidate_source_candidates
    from overseas_costing.services.logistics_settlement.model import digest
    l,e=pair(store);ingest(store,source('E2',text='更多'))
    job=bm.start(store,l['id'],'u');bm.run(store,job['id'],reply)
    store.sql('DELETE FROM oc_ls_state WHERE id IN (%s,%s)',(job['id'],digest('batch-match-pointer',l['id'])))
    assert bm.start(store,l['id'],'u')['stage']=='saved'
    invalidate_source_candidates(store,e['id'])
    assert bm.status(store,l['id'])['status']=='stale'
    retry=bm.start(store,l['id'],'u');calls=[]
    result=bm.run(store,retry['id'],lambda messages:calls.append(messages) or reply(messages))
    assert len(calls)==1 and result['status']=='completed' and len(bm.candidates(store,l))==2
