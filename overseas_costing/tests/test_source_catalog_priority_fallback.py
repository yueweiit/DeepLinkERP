"""Bound sources rank evidence without hiding other verified batch sources."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from overseas_costing.services import effective_logistics_source as effective
from overseas_costing.services import packing_snapshot_service as catalog
from overseas_costing.services import packing_source_service as resolver
from overseas_costing.services import source_priority_service as priority
from overseas_costing.services.logistics_settlement.model import dumps
from overseas_costing.tests.test_logistics_settlement import ingest, source
from overseas_costing.tests.test_settlement_writer import setup


def _fail_external(*_args, **_kwargs):
    pytest.fail("source listing must not read upstream or write")


def _local_catalog(monkeypatch, setup):
    store, ledger, batch, version, *_ = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *_args, **_kwargs: bundle)
    monkeypatch.setattr(resolver, 'frappe', SimpleNamespace())
    monkeypatch.setattr(catalog, 'frappe', SimpleNamespace(get_list=lambda *_args, **_kwargs: []))
    monkeypatch.setattr(resolver.dingtalk_approval_service, 'get_batch_dingtalk_approval_detail', _fail_external)
    monkeypatch.setattr(catalog, 'get_current_packing_snapshot', lambda *_args: {})
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement import ledger as ledger_module
    monkeypatch.setattr(Store, 'frappe', lambda: store)
    monkeypatch.setattr(ledger_module, 'FrappeLedger', lambda: ledger)
    return store, ledger, batch, version, bundle


def test_bound_catalog_keeps_current_logistics_body_and_own_context(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    before = store.db.total_changes

    rows = catalog._list_material_ai_sources(batch['name'], version['name'])

    assert [row['workflow_stage'] for row in rows] == ['payment', 'international_logistics']
    assert rows[0]['source_context'] == bundle['context']
    assert rows[1]['process_instance_id'] == 'L'
    assert rows[1]['source_context']['instance_id'] == 'L'
    assert rows[1]['source_context']['root_source_id'] == bundle['binding']['logistics_id']
    assert rows[1]['source_context']['root_kind'] == 'logistics'
    assert store.db.total_changes == before


def test_missing_bound_archive_does_not_hide_other_current_sources(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    bundle['source'] = {}
    bundle['context'] = {**bundle['context'], 'available': False, 'approved': False}

    rows = catalog._list_material_ai_sources(batch['name'], version['name'])

    logistics = next(row for row in rows if row.get('process_instance_id') == 'L')
    assert logistics['available'] is True
    assert not logistics['excluded']
    assert logistics['source_context']['available'] is True


def test_related_detail_uses_only_current_same_corp_links(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    logistics['raw']['formComponentValues'].append({
        'name': '关联审批单', 'componentType': 'RelateField',
        'value': ['采购支出'], 'extValue': [{'procInstId': 'BUY', 'businessId': 'PO-1'}],
    })
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    purchase = ingest(store, source('BUY', kind='purchase'))
    foreign = ingest(store, source('BUY', kind='purchase', corp='FOREIGN'))
    ingest(store, source('UNRELATED', kind='purchase'))
    before = store.db.total_changes

    detail = resolver.related_approval_detail(batch['name'], version['name'], bundle=bundle)

    assert detail['main_approval']['instance_id'] == 'L'
    assert [row['instance_id'] for row in detail['linked_purchase_approvals']] == ['BUY']
    assert detail['linked_purchase_approvals'][0]['corp_id'] == 'C'
    assert detail['linked_purchase_approvals'][0]['source_context']['root_source_id'] == purchase['id']
    assert foreign['id'] not in repr(detail)
    assert 'UNRELATED' not in repr(detail)
    assert store.db.total_changes == before


def test_rejected_related_approval_remains_excluded(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    logistics['invalid'] = True
    logistics['status'] = 'TERMINATED'
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})

    rows = catalog._list_material_ai_sources(batch['name'], version['name'])

    logistics_row = next(row for row in rows if row.get('process_instance_id') == 'L')
    assert logistics_row['excluded'] is True
    assert logistics_row['source_context']['invalid'] is True


def test_combining_actual_source_preserves_all_evidence_and_workbook_sheets():
    payment_context = {'root_kind': 'expense', 'instance_id': 'PAY', 'corp_id': 'C'}
    actual = [{'source_id': 'PAY', 'source_kind': 'approval_form', 'approval_role': 'payment',
               'source_context': payment_context}]
    own_context = {'root_kind': 'logistics', 'instance_id': 'L', 'corp_id': 'C'}
    fallback = [
        {'source_id': 'BODY', 'source_kind': 'approval_form', 'approval_role': 'international_logistics', 'source_context': own_context},
        *({'source_id': 'FILE', 'logical_source_id': 'oa:L:F', 'source_kind': 'approval_attachment',
           'approval_role': 'international_logistics', 'sheet_name': sheet, 'source_context': own_context}
          for sheet in ('Sheet 1', 'Sheet 2')),
        {'source_id': 'BUY', 'source_kind': 'approval_form', 'approval_role': 'purchase'},
        {'source_id': 'MANUAL', 'source_kind': 'manual_attachment'},
    ]
    before = deepcopy(fallback)

    result = catalog._combine_actual_packing_with_fallbacks(actual, fallback, payment_context)

    assert len(result) == 6
    assert result[0]['source_id'] == 'PAY'
    assert {row['sheet_name'] for row in result if row['source_id'] == 'FILE'} == {'Sheet 1', 'Sheet 2'}
    assert next(row for row in result if row['source_id'] == 'BODY')['source_context'] == own_context
    assert not next(row for row in result if row['source_id'] == 'MANUAL').get('source_context')
    assert fallback == before


def test_bound_comment_resolver_finds_current_logistics_comment(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    logistics['raw']['operationRecords'] = [{'remark': '重量42kg，体积1方', 'userId': 'U'}]
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    comment = resolver.related_approval_detail(batch['name'], version['name'], bundle=bundle)['main_approval']['timeline'][0]

    found = resolver._find_comment_source(batch['name'], comment['source_id'])

    assert found['instance_id'] == 'L'
    assert found['remark'] == '重量42kg，体积1方'
    assert found['source_context']['instance_id'] == 'L'


def test_field_policy_exposes_defaults_and_lower_priority_choice():
    policy = priority.get_source_priority_policy()

    assert policy['workflow_order'] == ['payment', 'international_logistics', 'purchase', 'other']
    assert policy['defaults_only'] is True
    assert policy['preserve_manual_choices'] is True
    assert '低优先级' in policy['short_summary']
    rule = next(row for row in policy['rules'] if row['code'] == 'purchase_price')
    assert '支付' in rule['authoritative_source']
    assert '行总额' in rule['summary']


def test_bound_catalog_keeps_related_local_attachments_without_opening_bytes(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    document = {'id': 'D-L', 'source_id': logistics['id'], 'file_name': 'packing.xlsx',
                'file_url': '/private/files/packing.xlsx', 'status': 'parsed',
                'tables': [{'title': '本票装箱', 'kind': 'packing'}],
                'manifest': {'file_id': 'F-L', 'sha256': 'a' * 64}}
    logistics['documents'] = [document]
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    row = {'name': 'ATT-L', 'batch': batch['name'], 'version': version['name'], 'source_type': 'OA',
           'file_name': document['file_name'], 'file_url': document['file_url'],
           'parse_result_json': dumps({'process_instance_id': 'L', 'corp_id': 'C', 'file_id': 'F-L',
                                     'settlement_document': document})}
    unrelated = {**row, 'name': 'UNRELATED', 'parse_result_json': dumps({'process_instance_id': 'OTHER', 'file_id': 'F-X'})}
    manual = {**row, 'name': 'MANUAL', 'source_type': 'Manual', 'parse_result_json': '{}'}
    rows = [row, unrelated, manual, {**manual, 'name': 'OLD', 'version': 'V-OLD'}]
    monkeypatch.setattr(catalog, 'frappe', SimpleNamespace(get_list=lambda *_args, **_kwargs: rows))
    monkeypatch.setattr(resolver, '_attachment_is_audit_only', lambda row, **_kwargs: False)
    monkeypatch.setattr(catalog, '_attachment_sheet_names', _fail_external)
    monkeypatch.setattr(resolver, '_attachment_hash', _fail_external)

    found = catalog._list_material_ai_sources(batch['name'], version['name'])

    attachments = [item for item in found if item['source_kind'].endswith('attachment')]
    assert {item['source_id'] for item in attachments} == {'ATT-L', 'MANUAL'}
    picked = next(item for item in attachments if item['source_id'] == 'ATT-L')
    assert picked['sheet_name'] == '本票装箱'
    assert picked['content_hash'] == 'a' * 64
    assert picked['source_context']['instance_id'] == 'L'
    assert next(item for item in attachments if item['source_id'] == 'MANUAL')['source_context']['root_kind'] == 'manual'

    picker = catalog.list_packing_sources(batch['name'])
    assert 'ATT-L' in {item['source_id'] for item in picker['approval_sources']}
    assert 'MANUAL' in {item['source_id'] for item in picker['manual_sources']}
    assert 'UNRELATED' not in repr(picker)


def test_current_catalog_never_merges_new_evidence_into_historical_version(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    ledger.put('batch', batch['name'], {'current_version': 'NEW-VERSION'})
    bundle['batch']['current_version'] = 'NEW-VERSION'

    detail = resolver.related_approval_detail(batch['name'], version['name'], bundle=bundle)

    assert detail['ok'] is False
    assert detail['main_approval'] == {}
    assert not detail['linked_purchase_approvals']


def test_unbound_current_catalog_also_reads_local_approval_archive(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    store.sql('DELETE FROM oc_ls_binding WHERE id=%s', (bundle['binding']['id'],))
    current = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *_args, **_kwargs: current)

    rows = catalog._list_material_ai_sources(batch['name'], version['name'])

    assert [row['process_instance_id'] for row in rows] == ['L']
    assert rows[0]['source_context']['instance_id'] == 'L'


def test_bound_catalog_uses_local_current_wiki_hash_without_upstream_read(monkeypatch, setup):
    _local_catalog(monkeypatch, setup)
    from overseas_costing.integrations import dingtalk_packing_source
    from overseas_costing.services import packing_sheet_cache_service
    monkeypatch.setattr(catalog, 'get_current_packing_snapshot', lambda *_args: {
        'source_kind': 'wiki_sheet', 'source_id': 'WB:S', 'source_hash': 'old-snapshot'})
    monkeypatch.setattr(dingtalk_packing_source, 'get_packing_runtime_clients', _fail_external)
    monkeypatch.setattr(packing_sheet_cache_service, 'get_cached_sheet', lambda source_id: {
        'source_hash': 'b' * 64, 'source': {'source_id': source_id}})

    rows = catalog._list_material_ai_sources(setup[2]['name'], setup[3]['name'])

    wiki = next(row for row in rows if row['source_kind'] == 'wiki_sheet')
    assert wiki['content_hash'] == 'b' * 64
    assert wiki['available'] is True
    assert wiki['source_context']['root_kind'] == 'wiki'


def test_manifest_accepts_verified_local_related_roots_and_excludes_only_failed_source(monkeypatch, setup):
    _, _, batch, version, _ = _local_catalog(monkeypatch, setup)
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    rows = catalog._list_material_ai_sources(batch['name'], version['name'])
    rows[0].update(analysis_required=True, analysis_allowed=False, analysis_reason='支付资料归档缺失')

    manifest = prepare_source_manifest(rows)

    assert len(manifest) == 2
    assert manifest[0]['excluded'] and not manifest[0]['selected']
    assert manifest[1]['selected'] is True
    assert manifest[1]['source_context']['instance_id'] == 'L'
    with pytest.raises(ValueError, match='不可选'):
        prepare_source_manifest(rows, selected_source_ids=[manifest[0]['source_id']])


def test_manifest_rejects_other_batch_or_unverified_related_context(monkeypatch, setup):
    _, _, batch, version, _ = _local_catalog(monkeypatch, setup)
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    rows = catalog._list_material_ai_sources(batch['name'], version['name'])
    for change in ({'batch': 'OTHER'}, {'instance_id': 'OTHER'}, {'source_lineage': {}}):
        invalid = deepcopy(rows)
        invalid[1]['source_context'].update(change)
        with pytest.raises(ValueError, match='来源'):
            prepare_source_manifest(invalid)


def test_manifest_rechecks_local_lineage_even_without_a_payment_root(monkeypatch, setup):
    _, _, batch, version, _ = _local_catalog(monkeypatch, setup)
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    logistics = catalog._list_material_ai_sources(batch['name'], version['name'])[1]
    foreign = {**logistics, 'source_id': 'FOREIGN', 'logical_source_id': 'FOREIGN',
               'process_instance_id': 'FOREIGN',
               'source_context': {**logistics['source_context'], 'instance_id': 'FOREIGN', 'fingerprint': 'different'}}

    with pytest.raises(ValueError, match='来源'):
        prepare_source_manifest([logistics, foreign])


def test_selected_related_comment_can_be_read_when_payment_archive_missing(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    logistics['raw']['operationRecords'] = [{'remark': '规格33*20*23，重量42.05kg，1套模具', 'userId': 'U'}]
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    comment = resolver.related_approval_detail(batch['name'], version['name'], bundle=bundle)['main_approval']['timeline'][0]
    bundle['context'] = {**bundle['context'], 'available': False}
    bundle['source'] = {}

    trusted = resolver.resolve_trusted_packing_source(
        batch_name=batch['name'], source_kind='approval_comment', source_id=comment['source_id'])

    assert trusted['source_context']['instance_id'] == 'L'
    assert trusted['source_context']['available'] is True
    assert len(trusted['source_hash']) == 64


def test_related_attachment_resolution_rejects_foreign_retired_and_changed_hash(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    manifest = {'file_id': 'F-L', 'sha256': 'a' * 64, 'corp_id': 'C', 'process_instance_id': 'L'}
    document = {'id': 'D-L', 'source_id': logistics['id'], 'file_name': 'packing.xlsx',
                'file_url': '/private/files/packing.xlsx', 'status': 'parsed', 'fingerprint': 'doc-fp',
                'manifest': manifest}
    logistics['documents'] = [document]
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    row = {'name': 'ATT-L', 'batch': batch['name'], 'version': version['name'], 'source_type': 'OA',
           'file_name': document['file_name'], 'file_url': document['file_url'],
           'parse_result_json': dumps({'process_instance_id': 'L', 'corp_id': 'C', 'file_id': 'F-L',
                                     'settlement_document': document})}

    chosen = effective.validate_packing_source(batch['name'], 'approval_attachment', 'ATT-L', attachment=row, bundle=bundle)

    assert chosen['context']['instance_id'] == 'L'
    assert effective.attachment_allowed(row, chosen, for_analysis=True)
    for bad in (
        {**row, 'batch': 'OTHER'},
        {**row, 'parse_result_json': dumps({'process_instance_id': 'L', 'corp_id': 'FOREIGN', 'file_id': 'F-L', 'settlement_document': document})},
        {**row, 'parse_result_json': dumps({'process_instance_id': 'L', 'corp_id': 'C', 'file_id': 'F-L', 'settlement_document': {**document, 'retired': True}})},
        {**row, 'parse_result_json': dumps({'process_instance_id': 'L', 'corp_id': 'C', 'file_id': 'F-L', 'settlement_document': {**document, 'manifest': {**manifest, 'sha256': 'b' * 64}}})},
    ):
        with pytest.raises(ValueError):
            effective.validate_packing_source(batch['name'], 'approval_attachment', 'ATT-L', attachment=bad, bundle=bundle)


def test_confirmed_related_snapshot_is_rechecked_against_its_own_source(monkeypatch, setup):
    original_getter = catalog.get_current_packing_snapshot
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    logistics['raw']['operationRecords'] = [{'remark': '重量42kg，体积1方', 'userId': 'U'}]
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    approval = resolver.related_approval_detail(batch['name'], version['name'], bundle=bundle)['main_approval']
    snapshot = {'name': 'SNAP-L', 'batch': batch['name'], 'status': 'Confirmed', 'is_current': 1,
                'source_kind': 'approval_comment', 'source_id': approval['timeline'][0]['source_id'],
                'source_context_json': dumps(approval['source_context']), 'cost_version': version['name']}
    monkeypatch.setattr(catalog, 'frappe', SimpleNamespace(
        db=SimpleNamespace(get_value=lambda *_args, **_kwargs: 'SNAP-L'),
        get_doc=lambda *_args: snapshot))

    assert original_getter(batch['name'], version['name']) == snapshot
    assert snapshot['source_context_json'] == dumps(approval['source_context'])
    logistics['invalid'] = True
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    assert original_getter(batch['name'], version['name']) is None


def test_unbound_picker_keeps_existing_cached_wiki_selection_scope(monkeypatch, setup):
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    store.sql('DELETE FROM oc_ls_binding WHERE id=%s', (bundle['binding']['id'],))
    current = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)

    assert effective.validate_packing_source(batch['name'], 'wiki_sheet', 'WB:S', bundle=current) == current


def test_payment_catalog_binds_validated_preview_to_its_own_local_lineage(monkeypatch):
    from overseas_costing.tests.test_freight_lines import setup_cost
    from overseas_costing.services.logistics_settlement import ledger as ledger_module, runtime, freight_matching
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    store, ledger, batch, version, _item, logistics, payment = setup_cost()
    candidate = freight_matching.rule_pass(store, logistics['id'])[0]
    reference = {'candidate_id': candidate['id'], 'revision': candidate['revision'], 'version': version['name']}
    bound_context = effective.context_for_source(payment, {'id': 'BIND', 'expense_id': payment['id'], 'revision': 1}, version['name'], batch['name'])
    bound = {'source_id': 'BOUND', 'source_kind': 'approval_form', 'process_instance_id': payment['instance'],
             'source_context': bound_context, 'approval_role': 'payment'}
    monkeypatch.setattr(Store, 'frappe', lambda: store)
    monkeypatch.setattr(ledger_module, 'FrappeLedger', lambda: ledger)
    monkeypatch.setattr(runtime, 'freight_enabled', lambda: True)
    monkeypatch.setattr(catalog, '_list_material_ai_sources', lambda *_args, **_kwargs: [bound])
    before = store.db.total_changes

    rows = catalog.list_material_ai_sources(batch['name'], version['name'], payment_references=[reference])

    previews = [row for row in rows if row.get('payment_match_candidate')]
    assert previews
    for preview in previews:
        context = preview['source_context']
        assert context['root_source_id'] == payment['id']
        assert context['instance_id'] == payment['instance']
        assert context['source_lineage']['logistics_source_id'] == logistics['id']
        assert context['source_lineage']['candidate_id'] == candidate['id']
    assert prepare_source_manifest(rows)
    assert store.db.total_changes == before


def test_verified_related_xls_keeps_structured_parsing():
    from overseas_costing.services.source_review_manifest_service import source_parse_method

    assert source_parse_method({'source_kind': 'approval_attachment', 'file_name': '本票装箱.xls',
        'source_context': {'root_kind': 'logistics', 'source_lineage': {'logistics_source_id': 'L'}}}) == 'SYSTEM_EXCEL'


def _related_material_import():
    from overseas_costing.tests.test_material_import_service import FakeRepository, _resolver_with_quantity
    repository = FakeRepository()
    repository.context['source_context'] = {
        'root_kind': 'expense', 'instance_id': 'PAY', 'corp_id': 'C',
        'batch': 'B1', 'cost_version': 'V1', 'available': False,
        'approved': False, 'fingerprint': 'payment-unavailable',
    }
    trusted = _resolver_with_quantity()()
    trusted['source'].update(source_kind='approval_attachment', source_id='ATT-L')
    trusted['source_context'] = {
        'root_kind': 'logistics', 'root_source_id': 'SOURCE-L', 'source_snapshot': 'SNAP-L',
        'instance_id': 'L', 'corp_id': 'C', 'batch': 'B1', 'cost_version': 'V1',
        'available': True, 'approved': True, 'invalid': False, 'fingerprint': 'logistics-current',
        'source_lineage': {'batch': 'B1', 'cost_version': 'V1', 'instance_id': 'L',
                           'logistics_source_id': 'SOURCE-L', 'logistics_snapshot': 'SNAP-L'},
    }
    return repository, trusted


def test_material_preview_signs_selected_source_context_not_payment_context():
    from overseas_costing.services import material_import_service as material
    repository, trusted = _related_material_import()

    preview = material.preview_material_import('B1', 'approval_attachment', 'ATT-L',
        repository=repository, resolver=lambda **_kwargs: deepcopy(trusted), signing_key=b'key')

    claims = material.decode_material_preview_revision(preview['preview_revision'], signing_key=b'key')
    assert preview['source_context'] == trusted['source_context']
    assert claims['source_context'] == trusted['source_context']
    assert 'cargo_review' not in preview
    assert repository.writes == []


def test_material_confirmation_uses_selected_source_and_records_its_provenance():
    from overseas_costing.services import material_import_service as material
    repository, trusted = _related_material_import()
    resolve = lambda **_kwargs: deepcopy(trusted)
    preview = material.preview_material_import('B1', 'approval_attachment', 'ATT-L',
        repository=repository, resolver=resolve, signing_key=b'key')

    result = material.apply_material_import('B1', preview['preview_revision'],
        {'fields': {'9': {'actual_shipped_qty': 'use_source'}}}, 'EDIT-1', 'BM1',
        repository=repository, resolver=resolve, signing_key=b'key')

    assert result['ok'] is True
    assert repository.writes[0][1]['actual_shipped_qty'] == '15'
    assert repository.writes[0][2]['source_context'] == trusted['source_context']
    assert repository.import_audits[0]['source_context'] == trusted['source_context']
    assert repository.commits == 1


@pytest.mark.parametrize('change, expected', [
    ('context', 'EFFECTIVE_SOURCE_CHANGED'), ('hash', 'SOURCE_CHANGED'),
    ('identity', 'SOURCE_CHANGED'), ('version', 'BATCH_VERSION_CHANGED'),
])
def test_related_material_confirmation_rejects_changed_dependency(change, expected):
    from overseas_costing.services import material_import_service as material
    repository, trusted = _related_material_import()
    resolve = lambda **_kwargs: deepcopy(trusted)
    preview = material.preview_material_import('B1', 'approval_attachment', 'ATT-L',
        repository=repository, resolver=resolve, signing_key=b'key')
    if change == 'context':
        trusted['source_context'].update(source_snapshot='NEW-SNAPSHOT', fingerprint='changed')
    elif change == 'hash':
        trusted['source_hash'] = 'b' * 64
    elif change == 'identity':
        trusted['source']['source_id'] = 'FOREIGN-ATTACHMENT'
    else:
        repository.context['version_modified'] = 'VM2'

    result = material.apply_material_import('B1', preview['preview_revision'], {}, 'EDIT-1', 'BM1',
        repository=repository, resolver=resolve, signing_key=b'key')

    assert result['code'] == expected
    assert not result['ok']
    assert repository.writes == []
    assert repository.import_audits == []
    assert repository.commits == 0


@pytest.mark.parametrize('field, value', [('batch', 'OTHER'), ('cost_version', 'OTHER'), ('corp_id', 'OTHER')])
def test_material_preview_rejects_selected_source_from_another_scope(field, value):
    from overseas_costing.services import material_import_service as material
    repository, trusted = _related_material_import()
    trusted['source_context'][field] = value

    with pytest.raises(ValueError, match='来源'):
        material.preview_material_import('B1', 'approval_attachment', 'ATT-L',
            repository=repository, resolver=lambda **_kwargs: deepcopy(trusted), signing_key=b'key')
    assert repository.writes == []


def _archived_related_attachment(monkeypatch, setup, tmp_path, flags):
    from hashlib import sha256
    from openpyxl import Workbook
    store, ledger, batch, version, bundle = _local_catalog(monkeypatch, setup)
    path = tmp_path / 'packing.xlsx'
    book = Workbook()
    book.active.title = 'Packing'
    book.active.append(['物料编码', '数量', '单位'])
    book.active.append(['M1', 2, '件'])
    book.save(path)
    logistics = store.get('source', bundle['binding']['logistics_id'])
    manifest = {'file_id': 'F-L', 'sha256': sha256(path.read_bytes()).hexdigest(),
                'corp_id': 'C', 'process_instance_id': 'L'}
    document = {'id': 'D-L', 'source_id': logistics['id'], 'file_name': 'packing.xlsx',
                'file_url': '/private/files/packing.xlsx', 'status': 'parsed',
                'fingerprint': 'document-current', 'manifest': manifest}
    logistics['documents'] = [document]
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})
    row = {'name': 'ATT-L', 'batch': batch['name'], 'version': version['name'], 'source_type': 'OA',
           'file_name': document['file_name'], 'file_url': document['file_url'],
           'parse_result_json': dumps({'process_instance_id': 'L', 'corp_id': 'C', 'file_id': 'F-L',
                                      'settlement_document': document, **flags})}
    monkeypatch.setattr(resolver, '_attachment_source_v2', lambda *_args: row)
    monkeypatch.setattr(resolver.import_service, '_resolve_excel_file_path', lambda **_kwargs: path)
    return store, batch, bundle, logistics, row


@pytest.mark.parametrize('flags', [
    {'approval_excluded': True},
    {'approval_excluded': True, 'cost_source_allowed': False, 'exclusion_reason': '审批结果为拒绝'},
])
def test_current_local_approval_restores_only_proven_old_approval_exclusion(monkeypatch, setup, tmp_path, flags):
    store, batch, bundle, logistics, row = _archived_related_attachment(monkeypatch, setup, tmp_path, flags)
    before = store.db.total_changes
    original = row['parse_result_json']
    assert resolver._attachment_is_audit_only(row) is True

    trusted = resolver.resolve_trusted_packing_source(batch_name=batch['name'],
        source_kind='approval_attachment', source_id='ATT-L', sheet_name='Packing')

    assert trusted['source_context']['instance_id'] == 'L'
    assert trusted['grid']['sheet_name'] == 'Packing'
    assert row['parse_result_json'] == original
    assert store.db.total_changes == before


@pytest.mark.parametrize('flags', [
    {'approval_excluded': True, 'cost_source_allowed': False},
    {'approval_excluded': True, 'exclusion_reason': '人工停用'},
    {'approval_excluded': True, 'disabled': True},
    {'approval_excluded': True, 'excluded': True},
    {'approval_excluded': True, 'is_active': 0},
    {'approval_excluded': True, 'audit_only': True},
    {'cost_source_allowed': False},
])
def test_current_local_approval_does_not_clear_other_audit_restrictions(monkeypatch, setup, tmp_path, flags):
    _, batch, _, _, row = _archived_related_attachment(monkeypatch, setup, tmp_path, flags)
    original = row['parse_result_json']

    with pytest.raises(ValueError, match='审计|排除|停用'):
        resolver.resolve_trusted_packing_source(batch_name=batch['name'],
            source_kind='approval_attachment', source_id='ATT-L', sheet_name='Packing')

    assert row['parse_result_json'] == original


@pytest.mark.parametrize('change', ['rejected', 'revoked', 'disabled', 'wrong_batch', 'wrong_hash'])
def test_stale_approval_flag_never_bypasses_current_source_validation(monkeypatch, setup, tmp_path, change):
    store, batch, _, logistics, row = _archived_related_attachment(monkeypatch, setup, tmp_path,
        {'approval_excluded': True})
    if change == 'rejected':
        logistics['approval_result'] = 'refuse'
    elif change == 'revoked':
        logistics['status'] = 'TERMINATED'
    elif change == 'disabled':
        logistics['disabled'] = True
    elif change == 'wrong_batch':
        row['batch'] = 'OTHER'
    else:
        meta = effective.json_dict(row['parse_result_json'])
        meta['settlement_document']['manifest']['sha256'] = '0' * 64
        row['parse_result_json'] = dumps(meta)
    store.put('source', {'id': logistics['id'], 'data': dumps(logistics)})

    with pytest.raises(ValueError):
        resolver.resolve_trusted_packing_source(batch_name=batch['name'],
            source_kind='approval_attachment', source_id='ATT-L', sheet_name='Packing')
