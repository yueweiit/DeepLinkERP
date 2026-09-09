from copy import deepcopy
import json

import pytest

from overseas_costing.services.logistics_settlement.model import digest, dumps
from overseas_costing.tests.test_settlement_writer import setup


def document(identity='doc1', **values):
    fields = {'物料编码': 'A', '规格': '', '单位': '件', '装箱数量': '4', '毛重(kg)': '8', '体积(m³)': '2', '单价': '999', **values}
    return {'id': identity, 'file_name': '装箱单.xlsx', 'file_url': '/private/files/packing.xlsx', 'status': 'parsed',
            'manifest': {'file_id': 'file1', 'archive_status': 'archived', 'archive_quality': 'original', 'source_kind': 'comment', 'sha256': identity, 'object_key': identity},
            'tables': [{'kind': 'packing', 'title': '装箱单', 'complete': False,
                        'rows': [{'position': 2, 'rowValue': [{'name': k, 'value': v} for k, v in fields.items()]}]}]}


def logistics(store, documents, **changes):
    source = deepcopy(store.find('source', kind='logistics')[0])
    source.update(documents=documents, attachments=[d['manifest'] for d in documents], packing_hash=digest(documents), **changes)
    return source


def sync(s, l, source, batch, **kwargs):
    from overseas_costing.services.logistics_settlement.document_writer import sync_logistics_documents
    return sync_logistics_documents(s, l, source, batch['name'], 'tester', **kwargs)


def test_local_document_fills_only_absent_physical_values_with_provenance(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'gross_weight_kg': None, 'volume_m3': None, 'actual_shipped_qty': 0})
    src = logistics(s, [document()]); before = deepcopy(src); registrations = []
    result = sync(s, l, src, batch, register_file=lambda attachment, doc: registrations.append((attachment['name'], doc['file_url'])))
    row = l.get('item', item['name']); meta = json.loads(row['extra_json'])
    assert row['quantity'] == 2 and row['unit_price'] == 10 and row['goods_value'] == 20
    assert row['actual_shipped_qty'] == '4' and row['gross_weight_kg'] == '8' and row['volume_m3'] == '2'
    assert meta['settlement_packing_provenance']['gross_weight_kg']['document_id'] == 'doc1'
    assert meta['settlement_packing_provenance']['gross_weight_kg']['source_snapshot'] == src['snapshot']
    assert meta['settlement_packing_review']  # shipped quantity differs from final quantity
    attachment = l.rows('attachment')[0]; parsed = json.loads(attachment['parse_result_json'])
    assert attachment['source_type'] == 'OA' and attachment['attachment_type'] == 'Packing List'
    assert parsed['manual_document']['slot_code'] == 'sea_packing_list'
    assert parsed['cost_source_allowed'] is True and attachment['oa_attachment_origin'] == 'Comment'
    assert registrations == [(attachment['name'], '/private/files/packing.xlsx')]
    assert result['version'] == version['name'] and src == before


def test_duplicate_item_identity_or_duplicate_document_rows_do_not_guess(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'gross_weight_kg': None})
    l.create('item', {'batch': batch['name'], 'version': version['name'], 'material_code': 'A', 'spec_model': '', 'unit': '件', 'quantity': 3})
    result = sync(s, l, logistics(s, [document()]), batch)
    assert result['issues'] and all(not row.get('gross_weight_kg') for row in l.rows('item'))
    assert len(l.rows('item')) == 2


def test_partial_unmatched_packing_never_creates_or_deletes_items(setup):
    s, l, batch, version, item, *_ = setup
    result = sync(s, l, logistics(s, [document(物料编码='UNKNOWN')]), batch)
    assert len(l.rows('item')) == 1 and l.get('item', item['name'])['quantity'] == 2
    assert result['issues']
    parsed = json.loads(l.rows('attachment')[0]['parse_result_json'])
    assert parsed['settlement_document']['reviews'][0]['reason']


def test_existing_weights_are_preserved_and_conflict_is_reviewable(setup):
    s, l, batch, version, item, *_ = setup
    result = sync(s, l, logistics(s, [document()]), batch)
    row = l.get('item', item['name'])
    assert row['gross_weight_kg'] == 4 and row['volume_m3'] == 3
    assert json.loads(row['extra_json'])['settlement_packing_review']
    assert result['issues']


def test_identical_retry_makes_no_database_writes_or_extra_file_registration(setup):
    s, l, batch, version, item, *_ = setup
    src = logistics(s, [document()]); registrations = []
    sync(s, l, src, batch, register_file=lambda a, d: registrations.append(a['name']))
    writes = s.db.total_changes
    result = sync(s, l, src, batch, register_file=lambda a, d: registrations.append(a['name']))
    assert result['changed'] is False and s.db.total_changes == writes
    assert len(l.rows('attachment')) == 1 and len(registrations) == 1


def test_confirmed_version_gets_one_adjustment_only_for_physical_changes(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'gross_weight_kg': None, 'volume_m3': None})
    l.put('version', version['name'], {'status': 'Confirmed'})
    l.put('batch', batch['name'], {'confirm_status': 'Confirmed', 'writeback_status': 'Success'})
    src = logistics(s, [document()]); result = sync(s, l, src, batch)
    assert result['version'] != version['name'] and len(l.rows('version')) == 2
    assert l.get('item', item['name'])['gross_weight_kg'] is None
    assert l.rows('item', version=result['version'])[0]['gross_weight_kg'] == '8'
    sync(s, l, src, batch)
    assert len(l.rows('version')) == 2 and len(l.rows('attachment')) == 1


def test_conflict_on_frozen_version_preserves_history_and_marks_adjustment_for_review(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'actual_shipped_qty': 4})
    sync(s, l, logistics(s, [document(**{'毛重(kg)': '4', '体积(m³)': '3'})]), batch)
    old_attachment = deepcopy(l.rows('attachment')[0]); old_item = deepcopy(l.get('item', item['name']))
    l.put('version', version['name'], {'status': 'Confirmed'})
    l.put('batch', batch['name'], {'confirm_status': 'Confirmed'})
    result = sync(s, l, logistics(s, [document('doc2')]), batch)
    assert len(l.rows('version')) == 2 and result['issues'] and result['blocking']
    assert l.get('item', item['name']) == old_item
    assert l.get('attachment', old_attachment['name']) == old_attachment
    current_item = l.rows('item', version=result['version'])[0]
    assert current_item['gross_weight_kg'] == old_item['gross_weight_kg']
    assert json.loads(current_item['extra_json'])['settlement_packing_review']


def test_edit_lock_durably_queues_then_resume_materializes(setup):
    s, l, batch, version, item, *_ = setup
    l.put('batch', batch['name'], {'edit_lock_owner': 'other', 'edit_lock_expires_at': '2099-01-01 00:00:00'})
    src = logistics(s, [document()]); result = sync(s, l, src, batch)
    assert result['status'] == 'queued' and not l.rows('attachment')
    assert s.find('document_sync', status='queued')[0]['source_id'] == src['id']
    l.put('batch', batch['name'], {'edit_lock_expires_at': None})
    sync(s, l, src, batch)
    assert l.rows('attachment') and not s.find('document_sync', status='queued')


@pytest.mark.parametrize('approval', [{'invalid': True}, {'approved': False}])
def test_invalid_or_unapproved_logistics_is_audit_only_and_validity_change_is_observed(setup, approval):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'gross_weight_kg': None})
    src = logistics(s, [document()], **approval); sync(s, l, src, batch)
    assert l.get('item', item['name'])['gross_weight_kg'] is None
    assert json.loads(l.rows('attachment')[0]['parse_result_json'])['cost_source_allowed'] is False
    valid = {**src, 'approved': True, 'invalid': False}; sync(s, l, valid, batch)
    assert l.get('item', item['name'])['gross_weight_kg'] == '8'
    assert json.loads(l.rows('attachment')[0]['parse_result_json'])['cost_source_allowed'] is True


def test_file_registration_failure_rolls_back_attachment_item_and_sync_record(setup):
    s, l, batch, version, item, *_ = setup
    before = deepcopy(l.get('item', item['name']))
    def fail(*args): raise RuntimeError('private File registration failed')
    with pytest.raises(RuntimeError, match='registration'):
        sync(s, l, logistics(s, [document()]), batch, register_file=fail)
    assert not l.rows('attachment') and not s.find('document_sync')
    assert l.get('item', item['name']) == before


def test_explicit_retirement_is_audit_only_without_deleting_historical_bytes(setup):
    s, l, batch, version, item, *_ = setup
    src = logistics(s, [document()]); sync(s, l, src, batch)
    attachment = l.rows('attachment')[0]
    retired = {**src, 'documents': [], 'packing_hash': 'retired', 'attachments': [{**src['attachments'][0], 'retired_at': '2026-09-09'}]}
    result = sync(s, l, retired, batch)
    current = l.get('attachment', attachment['name'])
    assert current['file_url'] == attachment['file_url']
    assert json.loads(current['parse_result_json'])['cost_source_allowed'] is False
    assert json.loads(current['parse_result_json'])['settlement_document']['retired']
    assert result['blocking']  # retained physical values no longer have active packing evidence


def test_missing_document_list_alone_does_not_retire_prior_card(setup):
    s, l, batch, version, item, *_ = setup
    src = logistics(s, [document()]); sync(s, l, src, batch)
    old = deepcopy(l.rows('attachment')[0])
    sync(s, l, {**src, 'documents': [], 'attachments': [], 'packing_hash': 'missing'}, batch)
    assert l.get('attachment', old['name']) == old


def test_unrecognized_nonpacking_evidence_on_frozen_version_creates_audit_card_without_draft(setup):
    s, l, batch, version, item, *_ = setup
    l.put('version', version['name'], {'status': 'Confirmed'})
    doc = document(); doc.update(tables=[], status='review', issues=['图片内容待核对'])
    result = sync(s, l, logistics(s, [doc]), batch)
    assert len(l.rows('version')) == 1 and not result['blocking']
    attachment = l.rows('attachment')[0]
    assert attachment['version'] == '' and json.loads(attachment['parse_result_json'])['cost_source_allowed'] is False
    assert result['status'] == 'review' and result['issues']


def test_duplicate_packing_rows_and_preview_bytes_never_fill_physical_values(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'gross_weight_kg': None})
    doc = document(); doc['tables'][0]['rows'] *= 2
    assert sync(s, l, logistics(s, [doc]), batch)['blocking']
    assert l.get('item', item['name'])['gross_weight_kg'] is None
    doc = document('preview'); doc['manifest']['archive_quality'] = 'preview'
    assert sync(s, l, logistics(s, [doc]), batch)['blocking']
    assert l.get('item', item['name'])['gross_weight_kg'] is None


def test_material_identity_preserves_punctuation_without_position_fallback(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'material_code': 'A-1', 'gross_weight_kg': None})
    result = sync(s, l, logistics(s, [document(物料编码='A1')]), batch)
    assert result['blocking'] and l.get('item', item['name'])['gross_weight_kg'] is None


def test_matching_unchanged_physical_values_on_frozen_version_do_not_create_empty_draft(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'quantity': 4, 'actual_shipped_qty': 4})
    l.put('version', version['name'], {'status': 'Confirmed'})
    src = logistics(s, [document(**{'毛重(kg)': 4, '体积(m³)': 3})])
    result = sync(s, l, src, batch)
    assert not result['blocking'] and len(l.rows('version')) == 1


def test_private_file_adapter_creates_own_link_without_reparenting_cached_file(setup):
    from types import SimpleNamespace
    from overseas_costing.services.logistics_settlement.document_writer import register_private_file
    s, l, *_ = setup
    writes = []
    def value(doctype, filters, field):
        return None if 'attached_to_name' in filters else 'cached-original'
    l.frappe = SimpleNamespace(db=SimpleNamespace(get_value=value), get_doc=lambda values: SimpleNamespace(insert=lambda **kwargs: writes.append(values)))
    register_private_file(l, {'name': 'attachment-new'}, document())
    assert writes[0]['attached_to_name'] == 'attachment-new' and writes[0]['is_private'] == 1
    assert writes[0]['file_url'] == '/private/files/packing.xlsx'
    with pytest.raises(ValueError, match='私有'):
        register_private_file(l, {'name': 'bad'}, {**document(), 'file_url': 'https://elsewhere/file.xlsx'})
    with pytest.raises(ValueError, match='私有'):
        register_private_file(l, {'name': 'bad'}, {**document(), 'file_url': '/private/files/%2e%2e/secret'})


def test_same_source_replans_after_final_goods_changes_item_identity(setup):
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'material_code': 'OTHER', 'gross_weight_kg': None})
    src = logistics(s, [document()])
    assert sync(s, l, src, batch)['blocking']
    l.put('item', item['name'], {'material_code': 'A'})
    result = sync(s, l, src, batch)
    assert result['changed'] and l.get('item', item['name'])['gross_weight_kg'] == '8'
    writes = s.db.total_changes
    assert not sync(s, l, src, batch)['changed'] and s.db.total_changes == writes


def test_acknowledged_packing_hash_prevents_replay_from_reviving_conflicts(setup):
    from overseas_costing.services.logistics_settlement.writer import resolve_document_checks
    s, l, batch, version, item, *_ = setup
    src = logistics(s, [document()]); sync(s, l, src, batch)
    row = l.get('item', item['name']); meta = json.loads(row['extra_json']); meta.pop('settlement_packing_review', None)
    l.put('item', item['name'], {'extra_json': dumps(meta)})
    resolve_document_checks(s, batch['name'], version['name'], [{'item_name': item['name'], 'packing_confirmed': True}], 'u', '核对现有物理值', ledger=l)
    writes = s.db.total_changes
    result = sync(s, l, src, batch)
    assert not result['changed'] and not result['blocking'] and s.db.total_changes == writes
    assert 'settlement_packing_review' not in json.loads(l.get('item', item['name'])['extra_json'])


def test_packing_state_hash_ignores_cost_calculation_and_timestamps(setup):
    from overseas_costing.services.logistics_settlement.document_writer import packing_state_hash
    s, l, batch, version, item, *_ = setup
    before = packing_state_hash([item])
    assert before == packing_state_hash([{**item, 'modified': 'tomorrow', 'total_cost_rmb': 999, 'unit_price': 400}])
    assert before != packing_state_hash([{**item, 'gross_weight_kg': 400}])


def test_formal_recalculation_does_not_revive_acknowledged_packing_conflict(setup):
    from overseas_costing.services.logistics_settlement.writer import resolve_document_checks
    s, l, batch, version, item, *_ = setup
    l.put('item', item['name'], {'weight_ratio': 0})
    src = logistics(s, [document()])
    assert sync(s, l, src, batch)['blocking']
    row = l.get('item', item['name']); meta = json.loads(row['extra_json'])
    meta.pop('settlement_packing_review', None)
    l.put('item', item['name'], {'extra_json': dumps(meta)})
    resolve_document_checks(s, batch['name'], version['name'], [{'item_name': item['name'], 'packing_confirmed': True}],
                            'u', '已核对保留现有数量与物理值', ledger=l)
    # Formal calculation writes this allocation ratio from the unchanged gross weights.
    l.put('item', item['name'], {'weight_ratio': 100, 'goods_value_ratio': 100,
                              'total_cost_rmb': 20, 'total_unit_rmb': 10, 'derived_json': '{"calculated":true}'})
    writes = s.db.total_changes
    result = sync(s, l, src, batch)
    assert not result['changed'] and not result['blocking'] and s.db.total_changes == writes
    assert 'settlement_packing_review' not in json.loads(l.get('item', item['name'])['extra_json'])


def test_expense_application_replans_previously_unmatched_local_packing(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    s, l, batch, version, item, rule, binding = setup
    l.put('item', item['name'], {'material_code': 'OTHER', 'gross_weight_kg': None})
    src = logistics(s, [document()]); src['fingerprint'] = digest(src['fingerprint'], src['documents'])
    src = s.ingest(src)
    assert sync(s, l, src, batch)['blocking']
    apply_binding(s, l, binding['id'], 'u')
    target = next(row for row in l.rows('item', version=version['name']) if row['material_code'] == 'A')
    assert target['gross_weight_kg'] == '8' and str(target['quantity']) == '4'
    state = s.find('document_sync')[0]
    assert all('未找到' not in row.get('reason', '') for rows in state['reviews'].values() for row in rows)
