import copy
import json
from types import SimpleNamespace

import pytest

from overseas_costing.tests.test_settlement_writer import setup


def test_context_is_public_and_fences_binding_snapshot_and_cost_version():
    from overseas_costing.services.effective_logistics_source import context_for_source
    source = {'id': 'expense', 'corp': 'C', 'instance': 'E', 'snapshot': 's1',
              'approved': True, 'invalid': False, 'raw': {'secret': 'object/path'}}
    binding = {'id': 'bind', 'expense_id': 'expense', 'revision': 2}
    context = context_for_source(source, binding, 'v1', 'batch')
    assert context['policy_version'] == 'procurement-source-2'
    assert context['root_kind'] == 'expense' and context['available']
    assert context['root_source_id'] == 'expense' and context['instance_id'] == 'E'
    assert 'secret' not in str(context) and 'raw' not in context
    for changed_source, changed_binding, version in [
        ({**source, 'snapshot': 's2'}, binding, 'v1'),
        (source, {**binding, 'revision': 3}, 'v1'),
        (source, binding, 'v2'),
        ({**source, 'approved': False}, binding, 'v1'),
        ({**source, 'invalid': True}, binding, 'v1'),
    ]:
        assert context_for_source(changed_source, changed_binding, version, 'batch')['fingerprint'] != context['fingerprint']
    missing = context_for_source(None, binding, 'v1', 'batch')
    assert missing['root_kind'] == 'expense' and missing['root_source_id'] == 'expense'
    assert not missing['available'] and not missing['approved']


def test_resolver_binding_wins_and_missing_expense_never_falls_back(setup):
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    store, ledger, batch, version, _item, _rule, binding = setup
    context = resolve_source_context(batch['name'], store=store, ledger=ledger)
    assert context['root_kind'] == 'expense' and context['root_source_id'] == binding['expense_id']
    assert context['cost_version'] == version['name']
    store.sql('DELETE FROM oc_ls_source WHERE id=%s', (binding['expense_id'],))
    missing = resolve_source_context(batch['name'], store=store, ledger=ledger)
    assert missing['root_kind'] == 'expense' and not missing['available']


def test_candidate_does_not_change_legacy_root(setup):
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    store, ledger, batch, _version, _item, _rule, binding = setup
    store.sql('DELETE FROM oc_ls_binding WHERE id=%s', (binding['id'],))
    context = resolve_source_context(batch['name'], store=store, ledger=ledger)
    assert context['root_kind'] == 'logistics' and context['root_source_id'] == binding['logistics_id']
    assert not context['binding_id']


def test_bound_manifest_reads_only_expense_body_comments_and_current_documents(monkeypatch, setup):
    from overseas_costing.services import effective_logistics_source as effective, packing_snapshot_service as packing
    store, ledger, batch, version, *_ = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    bundle['source']['raw']['operationRecords'] = [{'remark': 'EXPENSE COMMENT', 'userId': 'u'}]
    bundle['source']['documents'] = [{'id': 'DOC', 'file_name': 'expense.txt', 'file_url': '/private/files/e.txt', 'manifest': {'file_id': 'f'}}]
    row = {'name': 'A', 'version': version['name'], 'source_type': 'OA', 'file_name': 'expense.txt', 'file_url': '/private/files/e.txt',
           'parse_result_json': json.dumps({'process_instance_id': 'E', 'corp_id': 'C', 'settlement_document': {'document_id': 'DOC', 'source_id': bundle['source']['id']}})}
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *a, **kw: bundle)
    monkeypatch.setattr(packing, 'frappe', SimpleNamespace(get_list=lambda *a, **kw: [row, {**row, 'name': 'OLD', 'version': 'old'}, {'name': 'manual', 'source_type': 'Manual', 'file_name': 'OLD.txt'}]))
    monkeypatch.setattr(packing.packing_source_service.dingtalk_approval_service, 'get_batch_dingtalk_approval_detail', lambda *a: pytest.fail('read old Intl approval'))
    sources = packing._list_material_ai_sources(batch['name'], version['name'])
    assert {s['source_kind'] for s in sources} == {'approval_form', 'approval_comment', 'approval_attachment'}
    assert {s['process_instance_id'] for s in sources} == {'E'}
    assert 'OLD' not in json.dumps(sources) and 'manual' not in json.dumps(sources)
    assert any(s.get('comment_text') == 'EXPENSE COMMENT' for s in sources)
    assert all(s['source_context'] == bundle['context'] for s in sources)


def test_bound_direct_attachment_and_wiki_ids_are_rejected_before_read(monkeypatch, setup):
    from overseas_costing.services import effective_logistics_source as effective, packing_source_service as packing
    store, ledger, batch, version, *_ = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *a, **kw: bundle)
    monkeypatch.setattr(packing, '_attachment_source_v2', lambda *a: {'name': 'OLD', 'file_url': '/never', 'source_type': 'OA', 'parse_result_json': '{}'})
    monkeypatch.setattr(packing.import_service, '_resolve_excel_file_path', lambda **kw: pytest.fail('read old bytes'))
    for kind, id in [('approval_attachment', 'OLD'), ('manual_attachment', 'OLD'), ('wiki_sheet', 'OLD:sheet')]:
        with pytest.raises(ValueError, match='当前|关联'):
            packing.resolve_trusted_packing_source(batch_name=batch['name'], source_kind=kind, source_id=id)


def test_packing_preview_revision_changes_on_binding_revision_even_same_bytes(monkeypatch, setup):
    from overseas_costing.services import effective_logistics_source as effective, packing_source_service as packing
    store, ledger, batch, _version, *_ = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *a, **kw: bundle)
    monkeypatch.setattr(packing, '_resolve_trusted_packing_source', lambda **kw: {'source_hash': 'a' * 64, 'preview': {}, 'source': {}}, raising=False)
    first = packing.resolve_trusted_packing_source(batch_name=batch['name'], source_kind='approval_comment', source_id='comment')
    bundle['binding']['revision'] += 1
    bundle['context'] = effective.context_for_source(bundle['source'], bundle['binding'], bundle['context']['cost_version'], batch['name'])
    second = packing.resolve_trusted_packing_source(batch_name=batch['name'], source_kind='approval_comment', source_id='comment')
    assert first['source_hash'] != second['source_hash']
    assert second['source_context']['binding_revision'] == bundle['binding']['revision']


def test_packing_snapshot_saves_cost_version_and_context(monkeypatch):
    from overseas_costing.services import packing_snapshot_service as packing
    from overseas_costing.tests.test_packing_snapshot_service import FakeRepository, _preview
    context = {'policy_version': 'procurement-source-2', 'cost_version': 'VERSION-1', 'fingerprint': 'context'}
    resolver = lambda **kw: {'source_hash': 'a' * 64, 'source_context': context, 'source': {}, 'preview': _preview()}
    monkeypatch.setattr(packing.packing_source_service, '_revision_signing_key', lambda: b'key')
    result = packing.preview_packing_source_v2('B', 'wiki_sheet', 'WB:S', resolver=resolver)
    repo = FakeRepository()
    assert packing.confirm_packing_snapshot('B', result['source_revision'], {}, repository=repo, resolver=resolver)['ok']
    assert repo.saved[0]['cost_version'] == 'VERSION-1'
    assert json.loads(repo.saved[0]['source_context_json']) == context


def test_historical_version_uses_frozen_root_after_binding_changes(setup):
    from overseas_costing.services import effective_logistics_source as effective
    store, ledger, batch, version, *_ = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    ledger.put('version', version['name'], {'extra_json': json.dumps({'effective_logistics_source': bundle['context']})})
    current = ledger.create('version', {'batch': batch['name'], 'status': 'Active'})
    ledger.put('batch', batch['name'], {'current_version': current['name']})
    store.sql('DELETE FROM oc_ls_binding WHERE id=%s', (bundle['binding']['id'],))
    old = effective.resolve_source_context(batch['name'], version['name'], store=store, ledger=ledger)
    assert old == bundle['context']


@pytest.mark.parametrize('approved', [True, False])
@pytest.mark.parametrize('repeated_sku', [False, True])
def test_ai_complete_deepseek_payload_excludes_old_values_and_has_expense_body(monkeypatch, setup, approved, repeated_sku):
    from overseas_costing.services import effective_logistics_source as effective, material_ai_fill_service as ai, packing_snapshot_service as packing, allocation_service
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    store, ledger, batch, version, item, _rule, _binding = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    bundle['source']['approved'] = approved
    bundle['context'] = effective.context_for_source(bundle['source'], bundle['binding'], version['name'], batch['name'])
    bundle['source']['raw']['operationRecords'] = [{'remark': 'EXPENSE_ONLY_COMMENT'}]
    old_item = {**ledger.get('item', item['name']), 'source_doc_no': 'OLD_INTL_DOC', 'product_name': 'OLD_INTL_NAME', 'actual_shipped_qty': 999, 'gross_weight_kg': 888, 'quantity': 777}
    input_items = [old_item]
    if repeated_sku:
        first_key = bundle['source']['goods'][0]['line_key']
        bundle['source']['goods'].append({**bundle['source']['goods'][0], 'line_key': 'second-line', 'quantity': '6'})
        old_item['extra_json'] = json.dumps({'settlement_line_key': first_key})
        input_items.append({**old_item, 'name': 'I2', 'extra_json': json.dumps({'settlement_line_key': 'second-line'})})
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *a, **kw: bundle)
    monkeypatch.setattr(packing, 'frappe', SimpleNamespace(get_list=lambda *a, **kw: []))
    sources = packing._list_material_ai_sources(batch['name'], version['name'])
    repo = _LifecycleRepository(status='QUEUED')
    repo.sources = sources
    repo.get_items = lambda *a: copy.deepcopy(input_items)
    repo.get_context = lambda *a: {'batch': 'B1', 'version': 'V1', 'effective_source': copy.deepcopy(bundle['context'])}
    manifest = prepare_source_manifest(sources)
    repo.run.update(proposal_version=1, source_manifest_json=manifest,
                    input_fingerprint=ai._source_review_fingerprint('B1', 'V1', input_items, manifest, '', context=repo.get_context()))
    captured = []
    monkeypatch.setattr(allocation_service, '_ai_config', lambda: {'api_key': 'local-test-key', 'model': 'test'})
    monkeypatch.setattr(allocation_service, '_call_chat_completions', lambda config, messages: captured.append(copy.deepcopy(messages)) or '{"proposals":[]}')
    monkeypatch.setattr(ai, '_call_vision_style_descriptions', lambda documents: {'observations': []})
    result = ai.execute_material_ai_fill('RUN-1', repository=repo)
    assert result['status'] == 'READY', repo.run.get('error_message')
    assert captured
    text = json.dumps(captured, ensure_ascii=False)
    assert 'OLD_INTL' not in text
    payload = json.loads(captured[-1][-1]['content'])
    assert any(doc.get('approval_role') == 'logistics_expense' for doc in payload['untrusted_documents'])
    assert 'EXPENSE_ONLY_COMMENT' in text
    assert str(payload['items'][0]['values']['quantity']) == '4'
    assert payload['items'][0]['values']['gross_weight_kg'] is None
    assert payload['items'][0]['values']['actual_shipped_qty'] is None
    if repeated_sku:
        assert len(payload['items']) == 2 and len({row['item_name'] for row in payload['items']}) == 2
        assert str(payload['items'][1]['values']['quantity']) == '6'
    preview = repo.run['draft_json']['autofill_preview']
    assert 'OLD_INTL' not in json.dumps(preview)
    assert not preview['cost_summary']['is_complete']


def test_ai_ready_draft_stales_on_binding_revision_with_identical_items_and_sources():
    from overseas_costing.services import material_ai_fill_service as ai
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    repo = _LifecycleRepository()
    context = {'batch': 'B1', 'version': 'V1', 'effective_source': {'root_kind': 'expense', 'fingerprint': 'before'}}
    repo.get_context = lambda *a: copy.deepcopy(context)
    manifest = prepare_source_manifest(repo.sources)
    repo.run.update(proposal_version=1, source_manifest_json=manifest,
        input_fingerprint=ai._source_review_fingerprint('B1', 'V1', repo.get_items('B1','V1'), manifest, '', context=context))
    context['effective_source']['fingerprint'] = 'after'
    result = ai.apply_source_ai_review('B1', 'RUN-1', [], {}, 'TOKEN', 'M1', repository=repo)
    assert result['status'] == 'STALE' and not repo.applied


def test_manifest_rejects_mixed_roots_before_reading():
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    context = {'root_kind': 'expense', 'instance_id': 'E', 'fingerprint': 'f'}
    with pytest.raises(ValueError, match='来源'):
        prepare_source_manifest([
            {'source_id': 'E', 'source_kind': 'approval_form', 'process_instance_id': 'E', 'source_context': context},
            {'source_id': 'L', 'source_kind': 'approval_comment', 'process_instance_id': 'L'},
        ])


def test_legacy_ai_fingerprint_includes_empty_manifest_binding_context():
    from overseas_costing.services.material_ai_fill_service import build_input_fingerprint
    before = build_input_fingerprint('B', 'V', [], [], context={'effective_source': {'fingerprint': 'one'}})
    after = build_input_fingerprint('B', 'V', [], [], context={'effective_source': {'fingerprint': 'two'}})
    assert before != after


def test_bound_legacy_packing_write_refuses_raw_mutation(monkeypatch):
    from overseas_costing.services import import_service, effective_logistics_source as effective
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *a, **kw: {'context': {'root_kind': 'expense'}})
    result = import_service.apply_packing_list_fillable_fields(batch_name='B', attachment_name='OLD')
    assert result['ok'] is False and result['code'] == 'EFFECTIVE_SOURCE_REQUIRED'
    assert '物料' in result['message']


def test_physical_write_preserves_raw_and_marks_current_context():
    from overseas_costing.services.effective_logistics_source import physical_update_values, context_for_source
    source = {'id': 'E', 'snapshot': 'S', 'approved': True}
    context = context_for_source(source, {'id': 'B', 'expense_id': 'E', 'revision': 1}, 'V', 'batch')
    row = {'gross_weight_kg': 999, 'quantity': 777, 'extra_json': json.dumps({'effective_logistics_source': context})}
    result = physical_update_values(row, {'gross_weight_kg': 12, 'actual_shipped_qty': 4}, context, {'source_id': 'DOC'})
    assert set(result) == {'extra_json'}
    meta = json.loads(result['extra_json'])
    assert meta['effective_logistics_source'] == context
    assert meta['settlement_physical']['values'] == {'gross_weight_kg': 12, 'actual_shipped_qty': 4}
    assert row['gross_weight_kg'] == 999


def test_schema_contains_source_context_and_cost_version():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for prefix in ('', 'overseas_costing/'):
        schema = json.loads((root / f'{prefix}doctype/overseas_packing_snapshot/overseas_packing_snapshot.json').read_text())
        fields = {f['fieldname']: f for f in schema['fields']}
        assert fields['cost_version']['options'] == 'Overseas Cost Version'
        assert fields['source_context_json']['read_only'] == 1


def test_fee_evidence_rejects_old_attachment_before_reading_file(monkeypatch, setup):
    from overseas_costing.services import effective_logistics_source as effective, fee_evidence_review_service as fee
    store, ledger, batch, version, *_ = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    monkeypatch.setattr(effective, 'current_source_bundle', lambda *a, **kw: bundle)
    row = {'name': 'OLD', 'batch': batch['name'], 'version': version['name'], 'source_type': 'OA', 'file_url': '/old'}
    def get_value(doctype, *a, **kw):
        assert doctype != 'File', 'old file was read'
        return row
    monkeypatch.setattr(fee, 'frappe', SimpleNamespace(db=SimpleNamespace(get_value=get_value)))
    with pytest.raises(ValueError, match='当前'):
        fee.FrappeFeeEvidenceReviewRepository().get_attachment(batch['name'], 'OLD')


def test_fee_evidence_fingerprint_tracks_context_even_same_bytes():
    from overseas_costing.services.fee_evidence_review_service import build_input_fingerprint
    kwargs = {'batch_name': 'B', 'version_name': 'V', 'logical_fee_key': 'freight'}
    before = build_input_fingerprint(**kwargs, attachment={'name': 'A', 'source_context': {'fingerprint': 'before'}})
    after = build_input_fingerprint(**kwargs, attachment={'name': 'A', 'source_context': {'fingerprint': 'after'}})
    assert before != after


def test_pre_policy_history_resolves_snapshot_id_and_missing_snapshot_keeps_expense_identity(setup):
    from overseas_costing.services import effective_logistics_source as effective
    from overseas_costing.services.logistics_settlement.model import dumps
    store, ledger, batch, version, _item, _rule, binding = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    ctx = bundle['context']
    store.insert('application', {'id': 'app', 'binding_id': binding['id'], 'snapshot': ctx['source_snapshot'], 'version': version['name'], 'status': 'applied',
                                'data': dumps({'source_snapshot': ctx['source_snapshot']})})
    current = ledger.create('version', {'batch': batch['name']})
    ledger.put('batch', batch['name'], {'current_version': current['name']})
    historical = effective.resolve_source_context(batch['name'], version['name'], store=store, ledger=ledger)
    assert historical['root_kind'] == 'expense' and historical['instance_id'] == 'E'
    ledger.put('version', version['name'], {'extra_json': dumps({'effective_logistics_source': ctx})})
    store.sql('DELETE FROM oc_ls_snapshot WHERE id=%s', (ctx['source_snapshot'],))
    missing = effective.resolve_source_context(batch['name'], version['name'], store=store, ledger=ledger)
    assert not missing['available'] and missing['instance_id'] == 'E' and missing['source_snapshot'] == ctx['source_snapshot']


def test_explicit_but_ambiguous_expense_price_never_uses_independent_price(setup):
    from overseas_costing.services import effective_logistics_source as effective
    store, ledger, batch, version, item, *_ = setup
    bundle = effective.load_source_bundle(batch['name'], store=store, ledger=ledger)
    goods = bundle['source']['goods'][0]
    goods['merchandise_price'] = {'present': True, 'price': None, 'ambiguous': True}
    assert effective.project_ai_items([ledger.get('item', item['name'])], bundle)[0]['unit_price'] is None
    goods['merchandise_price'] = {'present': True, 'price': '0', 'currency': 'USD', 'price_uom': '件'}
    row = effective.project_ai_items([ledger.get('item', item['name'])], bundle)[0]
    assert row['unit_price'] == '0' and row['purchase_currency'] == 'USD'


def test_ai_binding_change_during_read_rejects_before_outbound_ai(monkeypatch):
    from overseas_costing.services import material_ai_fill_service as ai
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    repo = _LifecycleRepository(status='QUEUED')
    context = {'batch': 'B1', 'version': 'V1', 'effective_source': {'fingerprint': 'before'}}
    repo.get_context = lambda *a: copy.deepcopy(context)
    repo.sources = [{'source_id': 'comment', 'source_kind': 'approval_comment', 'source_hash': 'h', 'comment_text': 'TEST'}]
    manifest = prepare_source_manifest(repo.sources)
    repo.run.update(proposal_version=1, source_manifest_json=manifest,
        input_fingerprint=ai._source_review_fingerprint('B1', 'V1', repo.get_items('B1','V1'), manifest, '', context=context))
    original = ai._read_source
    def read(items, source):
        result = original(items, source)
        context['effective_source']['fingerprint'] = 'after'
        return result
    monkeypatch.setattr(ai, '_read_source', read)
    called = []
    monkeypatch.setattr(ai, '_call_source_review_ai', lambda *a, **kw: called.append(True) or {'ok': True, 'proposals': []})
    result = ai.execute_material_ai_fill('RUN-1', repository=repo)
    assert result['status'] == 'STALE'
    assert not called


def test_fee_ready_draft_rejected_after_binding_change_with_same_attachment_bytes():
    from overseas_costing.services import fee_evidence_review_service as fee
    from overseas_costing.tests.test_fee_evidence_review_service import _ApplyRepository
    repo = _ApplyRepository()
    repo.attachment['source_context'] = {'fingerprint': 'before'}
    repo.run['input_fingerprint'] = fee.build_input_fingerprint(batch_name='B1', version_name='V1', logical_fee_key='', attachment=repo.attachment)
    repo.attachment['source_context'] = {'fingerprint': 'after'}
    repo.mark_stale = lambda id: repo.run.update(status='STALE')
    result = fee.apply_fee_evidence_review('B1', 'RUN-1', ['evidence:classification'], {}, 'EDIT', 'm1', repository=repo)
    assert result['status'] == 'STALE' and repo.saved_evidence is None


def test_pending_source_packing_snapshot_cannot_be_confirmed(monkeypatch):
    from overseas_costing.services import packing_snapshot_service as packing
    from overseas_costing.tests.test_packing_snapshot_service import FakeRepository, _preview
    context = {'root_kind': 'expense', 'available': True, 'approved': False, 'invalid': False, 'fingerprint': 'pending'}
    resolver = lambda **kw: {'source_hash': 'a' * 64, 'source_context': context, 'source': {}, 'preview': _preview()}
    monkeypatch.setattr(packing.packing_source_service, '_revision_signing_key', lambda: b'key')
    preview = packing.preview_packing_source_v2('B', 'approval_attachment', 'A', resolver=resolver)
    repo = FakeRepository()
    result = packing.confirm_packing_snapshot('B', preview['source_revision'], {}, repository=repo, resolver=resolver)
    assert not result['ok'] and not repo.saved


def test_pending_source_ai_candidates_cannot_be_applied():
    from overseas_costing.services import material_ai_fill_service as ai
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    repo = _LifecycleRepository()
    context = {'batch': 'B1', 'version': 'V1', 'effective_source': {'root_kind': 'expense', 'available': True, 'approved': False, 'fingerprint': 'pending'}}
    repo.get_context = lambda *a: copy.deepcopy(context)
    manifest = prepare_source_manifest(repo.sources)
    repo.run.update(proposal_version=1, source_manifest_json=manifest,
        input_fingerprint=ai._source_review_fingerprint('B1', 'V1', repo.get_items('B1','V1'), manifest, '', context=context))
    with pytest.raises(ValueError, match='未批准'):
        ai.apply_source_ai_review('B1', 'RUN-1', [], {}, 'TOKEN', 'M1', repository=repo)
    assert not repo.applied
