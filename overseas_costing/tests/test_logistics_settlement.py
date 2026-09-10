import sqlite3
from decimal import Decimal

import pytest

from overseas_costing.services.logistics_settlement.model import parse_source
from overseas_costing.services.logistics_settlement.store import Store
from overseas_costing.services.logistics_settlement.matching import match_source, confirm_candidate


def source(instance, kind='expense', corp='C', text='海运 MXT500174', amount='0'):
    fields = [{'name': '运输说明', 'value': text}]
    if kind == 'expense':
        fields += [{'name': '采购支出', 'value': '服务类采购Compra De Servicios'},
                   {'name': '服务类采购', 'value': '物流及运输服务Servicios de logística y transporte'},
                   {'name': '总金额Monto Total', 'value': amount},
                   {'name': '币种Moneda', 'value': 'RMB'}]
    return {'corp_id': corp, 'process_instance_id': instance, 'process_code': kind,
            'updated_at': '2026-09-09T00:00:00+00:00', 'status': 'COMPLETED', 'result': 'agree',
            'raw_payload': {'formComponentValues': fields}}


@pytest.fixture
def store():
    value = Store.sqlite(sqlite3.connect(':memory:'))
    value.install()
    return value


def ingest(store, row):
    return store.ingest(parse_source(row, logistics_codes={'logistics'}))


def test_zero_final_is_not_missing_and_service_rate_is_not_goods():
    parsed = parse_source(source('E'), logistics_codes={'logistics'})
    assert parsed['kind'] == 'expense'
    assert parsed['approved'] is True
    assert parsed['amount'] == '0'
    assert parsed['goods_complete'] is False
    assert parsed['goods'] == []
    assert ('waybill', 'MXT500174') in [tuple(i) for i in parsed['identifiers']]


def test_commodity_purchase_with_logistics_text_is_not_settlement():
    row = source('E')
    row['raw_payload']['formComponentValues'][1:3] = [{'name': '采购支出', 'value': '物资采购'}]
    assert parse_source(row, logistics_codes={'logistics'})['kind'] == 'unclassified'


def test_old_inventory_skips_unrelated_purchase_without_parsing_attachments(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job, run_step
    row = source('unrelated')
    row['raw_payload']['formComponentValues'][1:3] = [{'name': '采购支出', 'value': '商品采购'}]
    class Archive:
        def page(self, **kwargs):
            return {'items': [row, source('E')], 'has_more': False, 'next_cursor': None}
    prepared = []
    def prepare(raw):
        prepared.append(raw['process_instance_id'])
        return raw
    job = start_job(store, mode='incremental', actor='u')
    for _ in range(4):
        job = run_step(store, Archive(), job['id'], logistics_codes={'logistics'}, prepare_source=prepare)
    assert prepared == ['E']
    assert store.count('source') == 1
    assert job['excluded_count'] == 1
    assert job['processed_count'] == 1


def test_category_loss_of_previous_expense_invalidates_existing_candidate(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job, run_step
    ingest(store, source('L', 'logistics'))
    expense = ingest(store, source('E'))
    candidate = match_source(store, expense['id'])[0]
    changed = source('E')
    changed['updated_at'] = '2026-09-10T00:00:00+00:00'
    changed['raw_payload']['formComponentValues'][1:3] = [{'name': '采购支出', 'value': '商品采购'}]
    class Archive:
        def page(self, **kwargs):
            return {'items': [changed], 'has_more': False, 'next_cursor': None}
    job = start_job(store, mode='incremental', actor='u')
    for _ in range(4):
        job = run_step(store, Archive(), job['id'], logistics_codes={'logistics'})
    assert store.get('source', expense['id'])['kind'] == 'unclassified'
    assert store.get('candidate', candidate['id'])['status'] == 'stale'


def test_pending_refused_and_deleted_never_approved():
    for status, result, deleted in [('RUNNING', '', None), ('COMPLETED', 'refuse', None), ('COMPLETED', 'agree', '2026-09-09')]:
        row = {**source('E'), 'status': status, 'result': result, 'deleted_at': deleted}
        assert not parse_source(row, logistics_codes={'logistics'})['approved']


def test_snapshots_idempotent_and_comment_only_change_preserves_matching_hash(store):
    row = source('E')
    first = ingest(store, row)
    again = ingest(store, {**row, 'updated_at': '2026-09-09T01:00:00+00:00'})
    assert first['snapshot'] == again['snapshot']
    row['raw_payload']['operationRecords'] = [{'remark': '补充装箱资料'}]
    row['updated_at'] = '2026-09-09T02:00:00+00:00'
    changed = ingest(store, row)
    assert changed['snapshot'] != first['snapshot']
    assert changed['match_hash'] == first['match_hash']
    assert store.count('snapshot') == 2


def test_one_to_one_database_and_confirmation_guards(store):
    logistics = ingest(store, source('L', 'logistics'))
    expense = ingest(store, source('E'))
    candidates = match_source(store, expense['id'])
    assert len(candidates) == 1
    assert candidates[0]['status'] == 'pending'
    binding = confirm_candidate(store, candidates[0]['id'], candidates[0]['revision'], 'tester')
    assert binding['logistics_id'] == logistics['id']
    assert binding['expense_id'] == expense['id']
    assert confirm_candidate(store, candidates[0]['id'], candidates[0]['revision'], 'tester')['id'] == binding['id']
    another = ingest(store, source('E2'))
    assert match_source(store, another['id'])[0]['status'] == 'conflict'
    with pytest.raises(sqlite3.IntegrityError):
        store.insert('binding', {'id': 'duplicate', 'logistics_id': logistics['id'], 'expense_id': another['id'], 'data': '{}'})


def test_same_identifier_in_two_logistics_is_conflict_and_cross_corp_excluded(store):
    ingest(store, source('L', 'logistics'))
    ingest(store, source('L2', 'logistics'))
    ingest(store, source('OTHER', 'logistics', corp='D'))
    expense = ingest(store, source('E'))
    candidates = match_source(store, expense['id'])
    assert len(candidates) == 2
    assert all(c['status'] == 'conflict' for c in candidates)


def test_source_changed_after_preview_requires_new_preview(store):
    ingest(store, source('L', 'logistics'))
    expense = ingest(store, source('E'))
    candidate = match_source(store, expense['id'])[0]
    ingest(store, source('E', amount='500'))
    with pytest.raises(ValueError, match='来源'):
        confirm_candidate(store, candidate['id'], candidate['revision'], 'tester')


def test_container_only_match_is_review_not_explicit(store):
    ingest(store, source('L', 'logistics', text='柜号 ABCD1234567'))
    expense = ingest(store, source('E', text='柜号 ABCD1234567'))
    candidate = match_source(store, expense['id'])[0]
    assert candidate['method'] == 'container'
    assert candidate['status'] == 'pending'


def test_initialization_over_200_and_catchup(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job, run_step
    class Archive:
        def __init__(self):
            self.rows = [source(f'L{i}', 'logistics', text=f'MXT{10000+i}') for i in range(205)]
        def page(self, *, cursor, limit, lower, upper, start='', end=''):
            rows = self.rows if not lower else [source('late', 'logistics', text='MXT99999')]
            position = int(cursor or 0)
            page = rows[position:position+limit]
            return {'items': page, 'next_cursor': position+len(page), 'has_more': position+len(page)<len(rows)}
    archive = Archive()
    job = start_job(store, mode='initialize', actor='tester', now='2026-09-09T03:00:00+00:00')
    assert start_job(store, mode='initialize', actor='tester', now='2026-09-09T04:00:00+00:00')['id'] == job['id']
    for _ in range(20):
        job = run_step(store, archive, job['id'], logistics_codes={'logistics'}, now='2026-09-09T05:00:00+00:00')
        if job['status'] == 'completed':
            break
    assert job['status'] == 'completed'
    assert store.count('source') == 206
    assert job['caught_up'] is True
    assert store.get('state', 'sync')['watermark'] == '2026-09-09T05:00:00+00:00'


def test_job_failure_is_durable_and_retryable(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job, run_step, retry_job
    class Archive:
        def page(self, **kwargs):
            return {'items': [{**source('bad'), 'corp_id': ''}], 'next_cursor': 1, 'has_more': False}
    job = start_job(store, mode='incremental', actor='tester', now='2026-09-09T05:00:00+00:00')
    for _ in range(8):
        job = run_step(store, Archive(), job['id'], logistics_codes={'logistics'})
        if job['status'] == 'partial':
            break
    assert job['status'] == 'partial'
    failed = store.find('job_item', job_id=job['id'], status='failed')
    assert len(failed) == 1
    assert '企业' in failed[0]['error']
    assert retry_job(store, job['id'])['status'] == 'queued'


def table_row(row_id, code='A', quantity='2', unit='件'):
    return {'rowId': row_id, 'rowValue': [
        {'name': '物料编码', 'value': code}, {'name': '数量', 'value': quantity},
        {'name': '单位', 'value': unit}]}


def test_same_code_native_rows_and_reordering_are_stable():
    row = source('E')
    table = {'name': '货物明细', 'componentType': 'TableField', 'value': [table_row('a'), table_row('b')]}
    row['raw_payload']['formComponentValues'].append(table)
    first = parse_source(row, logistics_codes={'logistics'})
    assert first['goods_complete']
    assert len({g['line_key'] for g in first['goods']}) == 2
    table['value'].reverse()
    second = parse_source(row, logistics_codes={'logistics'})
    assert first['cost_hash'] == second['cost_hash']


def test_one_malformed_goods_table_cannot_be_hidden_by_valid_table():
    row = source('E')
    row['raw_payload']['formComponentValues'] += [
        {'name': '货物明细一', 'componentType': 'TableField', 'value': [table_row('bad', quantity='?')]},
        {'name': '货物明细二', 'componentType': 'TableField', 'value': [table_row('good')]}]
    assert not parse_source(row, logistics_codes={'logistics'})['goods_complete']


def test_attachment_poll_metadata_does_not_reapply_unchanged_content():
    row = source('E')
    row['attachments'] = [{'file_id': 'f', 'object_key': 'x', 'sha256': 'hash', 'status': 'archived', 'updated_at': '2026-09-09', 'attempts': 1}]
    first = parse_source(row, logistics_codes={'logistics'})
    row['attachments'][0].update(updated_at='2026-09-10', attempts=2)
    second = parse_source(row, logistics_codes={'logistics'})
    assert first['cost_hash'] == second['cost_hash']
    assert first['fingerprint'] == second['fingerprint']


def test_details_are_persisted_with_snapshot_identity(store):
    row = source('E')
    row['raw_payload']['formComponentValues'].append({'name': '货物明细', 'componentType': 'TableField', 'value': [table_row('a'), table_row('b')]})
    parsed = ingest(store, row)
    details = store.find('detail', snapshot=parsed['snapshot'], detail_type='goods')
    assert len(details) == 2
    assert all(d['source_position'] for d in details)
    ingest(store, row)
    assert store.count('detail') == 2


def test_two_expenses_for_one_logistics_both_require_conflict_resolution(store):
    ingest(store, source('L', 'logistics'))
    a = ingest(store, source('E1'))
    b = ingest(store, source('E2'))
    assert match_source(store, a['id'])[0]['status'] == 'conflict'
    assert match_source(store, b['id'])[0]['status'] == 'conflict'


def test_reject_evidence_is_not_recommended_until_identifiers_change(store):
    from overseas_costing.services.logistics_settlement.matching import reject_candidate
    ingest(store, source('L', 'logistics'))
    a = ingest(store, source('E'))
    candidate = match_source(store, a['id'])[0]
    reject_candidate(store, candidate['id'], candidate['revision'], 'user', '不是同票')
    assert match_source(store, a['id']) == []
    changed = source('E', text='MXT500174 补充柜号 ABCD1234567')
    ingest(store, changed)
    assert match_source(store, a['id'])


def test_job_retry_repeats_failed_matching_even_if_source_already_saved(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job, run_step, retry_job
    class Archive:
        def page(self, **kwargs):
            return {'items': [source('E')], 'next_cursor': 1, 'has_more': False}
    job = start_job(store, mode='incremental', actor='u')
    calls = []
    def apply(id):
        calls.append(id)
        if len(calls) == 1:
            raise ValueError('temporary')
    for _ in range(8):
        job = run_step(store, Archive(), job['id'], logistics_codes={'logistics'}, apply_source=apply)
        if job['status'] == 'partial':
            break
    retry_job(store, job['id'])
    for _ in range(8):
        job = run_step(store, Archive(), job['id'], logistics_codes={'logistics'}, apply_source=apply)
        if job['status'] == 'completed':
            break
    assert job['status'] == 'completed'
    assert len(calls) == 2


def test_store_limit_and_filtered_count_are_database_bounded(store):
    for i in range(5):
        ingest(store, source(str(i)))
    assert len(store.find('source', limit=2, kind='expense')) == 2
    assert store.count('source', kind='logistics') == 0


def test_explanatory_text_cannot_override_commodity_parent():
    row = source('E')
    row['raw_payload']['formComponentValues'][1:3] = [
        {'name': '采购支出Gastos de Compra', 'value': '商品类采购Compra de mercancías'},
        {'name': '采购支出说明', 'value': '上次使用服务类采购→物流及运输服务，本次为普通物料'}]
    assert parse_source(row, logistics_codes={'logistics'})['kind'] == 'unclassified'


def test_rebinding_is_atomic_and_requires_explicit_correction(store):
    from overseas_costing.services.logistics_settlement.matching import replace_binding
    ingest(store, source('L', 'logistics'))
    a = ingest(store, source('E'))
    candidate = match_source(store, a['id'])[0]
    binding = confirm_candidate(store, candidate['id'], candidate['revision'], 'user')
    b = ingest(store, source('E2'))
    new = match_source(store, b['id'])[0]
    def fail(*args):
        raise ValueError('failed application reversal')
    with pytest.raises(ValueError, match='reversal'):
        replace_binding(store, binding['id'], 1, new['id'], new['revision'], 'user', '原关联错误', on_replace=fail)
    assert store.get('binding', binding['id'])['expense_id'] == a['id']
    changed = replace_binding(store, binding['id'], 1, new['id'], new['revision'], 'user', '原关联错误')
    assert changed['expense_id'] == b['id']
    assert changed['revision'] == 2
    assert store.count('binding') == 1
    assert store.count('audit', action='replace') == 1


def test_initialization_manifest_and_pause_resume_are_durable(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job, run_step, pause_job, retry_job
    class Archive:
        def page(self, **kwargs):
            return {'items': [source('E')], 'next_cursor': 1, 'has_more': False}
    job = start_job(store, mode='initialize', actor='u', now='2026-09-09T00:00:00+00:00')
    run_step(store, Archive(), job['id'], logistics_codes={'logistics'})
    assert store.count('manifest', job_id=job['id']) == 1
    pause_job(store, job['id'])
    assert run_step(store, Archive(), job['id'], logistics_codes={'logistics'})['status'] == 'paused'
    retry_job(store, job['id'])
    for _ in range(10):
        job = run_step(store, Archive(), job['id'], logistics_codes={'logistics'})
        if job['status'] == 'completed':
            break
    assert store.count('manifest', job_id=job['id']) == 2
    assert start_job(store, mode='initialize', actor='u')['id'] == job['id']


def test_category_requires_parent_and_accepts_exact_structured_path():
    from overseas_costing.services.logistics_settlement.model import is_logistics_expense
    assert not is_logistics_expense({'服务类采购':'物流及运输服务'})
    for value in [['服务类采购','物流及运输服务'], '["服务类采购","物流及运输服务"]', '服务类采购→物流及运输服务']:
        assert is_logistics_expense({'采购类别':value})
    assert not is_logistics_expense({'采购支出':'商品类采购','采购类别':['服务类采购','物流及运输服务']})


def test_numeric_explanation_cannot_supply_final_amount():
    row=source('E')
    row['raw_payload']['formComponentValues']=[c for c in row['raw_payload']['formComponentValues'] if not c['name'].startswith('总金额')]
    row['raw_payload']['formComponentValues'].append({'name':'总金额说明','value':'12345'})
    assert parse_source(row,logistics_codes={'logistics'})['amount'] is None


def test_malformed_payment_table_blocks_total_fallback():
    from overseas_costing.services.logistics_settlement.application import plan_application
    row=source('E',amount='100')
    row['raw_payload']['formComponentValues'].append({'name':'付款明细','componentType':'TableField','value':'malformed rows'})
    parsed=parse_source(row,logistics_codes={'logistics'})
    assert not plan_application(parsed,[],[],binding_id='b')['ready']


def test_new_competitor_prevents_confirming_previously_clean_preview(store):
    ingest(store,source('L','logistics')); a=ingest(store,source('A'))
    c=match_source(store,a['id'])[0]
    b=ingest(store,source('B')); match_source(store,b['id'])
    with pytest.raises(ValueError):
        confirm_candidate(store,c['id'],c['revision'],'u')


def test_weekly_light_inventory_fetches_only_changed_sources(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job,run_step
    same=source('E');same['archive_revision']='r1';ingest(store,same)
    changed=source('E2');changed['archive_revision']='r2'
    class Archive:
        def inventory_page(self,**kwargs):
            return {'items':[{'corp_id':'C','process_instance_id':'E','archive_revision':'r1'},{'corp_id':'C','process_instance_id':'E2','archive_revision':'r2'}], 'has_more':False,'next_cursor':None}
        def page(self,**kwargs):
            pytest.fail('weekly inventory fetched full payload page')
        def get_sources(self,pairs):
            assert pairs==[('C','E2')]
            return [changed]
    archive=Archive();job=start_job(store,mode='reconcile',actor='u')
    for _ in range(5):
        job=run_step(store,archive,job['id'],logistics_codes={'logistics'})
        if job['status']=='completed':break
    assert job['status']=='completed' and job['unchanged_count']==1 and job['processed_count']==1


def test_unchanged_identifiers_refresh_preview_after_amount_update(store):
    from overseas_costing.services.logistics_settlement.matching import refresh_candidate_snapshots
    ingest(store,source('L','logistics'));expense=ingest(store,source('E'));c=match_source(store,expense['id'])[0]
    updated=source('E',amount='99');updated['updated_at']='2026-09-09T02:00:00+00:00';expense=ingest(store,updated)
    refresh_candidate_snapshots(store,expense['id']);fresh=store.get('candidate',c['id'])
    assert fresh['revision']!=c['revision']
    assert confirm_candidate(store,fresh['id'],fresh['revision'],'u')['expense_id']==expense['id']


def test_second_logistics_source_blocks_clean_candidate_even_before_matching(store):
    ingest(store,source('L','logistics'));expense=ingest(store,source('E'));c=match_source(store,expense['id'])[0]
    ingest(store,source('L2','logistics'))
    with pytest.raises(ValueError):confirm_candidate(store,c['id'],c['revision'],'u')


def test_reparse_only_requested_local_sources_does_not_advance_upstream_cursor(store):
    from overseas_costing.services.logistics_settlement.jobs import start_reparse_job,run_step
    from overseas_costing.services.logistics_settlement.model import dumps
    a=ingest(store,source('A'));ingest(store,source('B'))
    store.put('state',{'id':'sync','updated_at':'t','data':dumps({'watermark':'2026-09-01T00:00:00+00:00'})})
    job=start_reparse_job(store,[a['id']],actor='u')
    again=start_reparse_job(store,[a['id']],actor='u')
    assert again['id']==job['id']
    for _ in range(4):job=run_step(store,None,job['id'],logistics_codes={'logistics'})
    assert job['status']=='completed' and job['item_count']==1
    assert store.get('state','sync')['watermark']=='2026-09-01T00:00:00+00:00'


def test_paused_matching_retry_reloads_failed_items_before_completion(store):
    from overseas_costing.services.logistics_settlement.jobs import start_job,run_step,pause_job,retry_job
    rows=[source(f'L{i}','logistics',text=f'MXT{10000+i}') for i in range(201)]
    class Archive:
        def page(self,**kwargs):
            offset=int(kwargs.get('cursor') or 0);page=rows[offset:offset+200]
            return {'items':page,'next_cursor':offset+len(page),'has_more':offset+len(page)<len(rows)}
    job=start_job(store,mode='incremental',actor='u')
    while job['phase']!='match':job=run_step(store,Archive(),job['id'],logistics_codes={'logistics'})
    calls=[]
    def flaky(sid):
        calls.append(sid)
        if len(calls)==1:raise RuntimeError('temporary')
    job=run_step(store,Archive(),job['id'],logistics_codes={'logistics'},apply_source=flaky)
    assert store.count('job_item',job_id=job['id'],status='failed')==1
    pause_job(store,job['id']);job=retry_job(store,job['id'])
    assert job['phase']=='load'
    for _ in range(5):job=run_step(store,Archive(),job['id'],logistics_codes={'logistics'},apply_source=flaky)
    assert job['status']=='completed' and job['processed_count']==201
    assert store.count('job_item',job_id=job['id'],status='pending')==0
