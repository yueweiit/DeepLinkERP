"""Selected AI rows must track locally archived contributing evidence."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from overseas_costing.services import material_ai_selected_scope as scope
from overseas_costing.services.effective_logistics_source import load_source_bundle
from overseas_costing.services.logistics_settlement.model import dumps
from overseas_costing.services.packing_source_service import _bound_wiki_cache_key
from overseas_costing.tests.test_settlement_writer import setup as settlement_fixture


def local_context():
    store, ledger, batch, version, *_ = settlement_fixture.__wrapped__()
    bundle = load_source_bundle(batch['name'], version['name'], store=store, ledger=ledger)
    return store, ledger, batch, bundle


def adopt(store, ledger, batch, bundle, sources):
    return {'id': 'ADOPTED', 'revision': 'REV', 'source_context': bundle['context'],
            'selected_row_ids': ['ROW'], 'goods': [{'material_code': 'A', 'quantity': 2}],
            'sources': sources, 'dependencies': scope.capture_dependencies(
                sources, store=store, ledger=ledger, batch_name=batch['name'],
                source_context=bundle['context'])}


def project(store, ledger, batch, bundle, adoption, **options):
    return scope.apply_scope(bundle, adoption, store=store, ledger=ledger,
                             batch_name=batch['name'], **options)


def test_old_adoption_without_dependency_baseline_is_pending_but_history_is_readable():
    _, _, _, bundle = local_context()
    adoption = {'id': 'OLD', 'revision': 'R', 'source_context': bundle['context'],
                'selected_row_ids': ['ROW'], 'goods': [{'material_code': 'A'}],
                'sources': [{'source_kind': 'approval_attachment', 'source_id': 'FILE'}]}
    assert not scope.apply_scope(bundle, adoption)['context']['available']
    historical = scope.apply_scope(bundle, adoption, historical=True)
    assert historical['context']['available']
    assert historical['source']['goods'] == adoption['goods']


@pytest.mark.parametrize('change', ['text', 'removed', 'invalid'])
def test_comment_dependency_changes_invalidate_without_root_snapshot_change(change):
    store, ledger, batch, bundle = local_context()
    source = deepcopy(bundle['source'])
    source['raw']['comments'] = [{'commentId': 'C1', 'text': 'two cartons'}]
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    manifest = [{'source_kind': 'approval_comment', 'source_id': 'PUBLIC-C1',
                 'resolver_source_id': 'C1', 'process_instance_id': source['instance'], 'selected': True}]
    adoption = adopt(store, ledger, batch, bundle, manifest)
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    if change == 'text': source['raw']['comments'][0]['text'] = 'three cartons'
    elif change == 'removed': source['raw']['comments'] = []
    else: source['invalid'] = True
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    result = project(store, ledger, batch, bundle, adoption)
    assert not result['context']['available']
    assert result['context']['packing']['dependency_issues']
    assert project(store, ledger, batch, bundle, adoption, historical=True)['source']['goods'] == adoption['goods']


@pytest.mark.parametrize('change', ['content_hash', 'removed', 'retired', 'failed'])
def test_local_attachment_updates_or_retirement_invalidate_scope(change, monkeypatch):
    store, ledger, batch, bundle = local_context()
    from overseas_costing.services import attachment_parse_service
    monkeypatch.setattr(attachment_parse_service, '_resolve_source_file_path',
                        lambda **kwargs: pytest.fail('Scope reads must not reopen attachment bytes'))
    document = {'id': 'DOC', 'source_id': bundle['source']['id'], 'fingerprint': 'H', 'status': 'parsed',
                'manifest': {'archive_quality': 'original_complete'}}
    store.put('document', {k: document[k] for k in ('id', 'source_id', 'fingerprint', 'status')} | {'data': dumps(document)})
    attachment = ledger.create('attachment', {'batch': batch['name'], 'file_url': '/private/files/packing.txt',
        'file_name': 'packing.txt', 'source_type': 'OA', 'parse_result_json': dumps({'settlement_document': {'document_id': 'DOC'}})})
    manifest = [{'source_kind': 'approval_attachment', 'source_id': 'PUBLIC:sheet:HASH',
                 'resolver_source_id': attachment['name'], 'process_instance_id': bundle['source']['instance'],
                 'sheet_name': 'sheet A', 'selected': True}]
    adoption = adopt(store, ledger, batch, bundle, manifest)
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    if change == 'removed': ledger.put('attachment', attachment['name'], {'file_url': ''})
    else:
        if change == 'content_hash': document['manifest']['content_sha256'] = 'NEW-HASH'
        elif change == 'retired': document['manifest']['retired_at'] = 'now'
        else: document['status'] = 'failed'
        store.put('document', {k: document[k] for k in ('id', 'source_id', 'fingerprint', 'status')} | {'data': dumps(document)})
    assert not project(store, ledger, batch, bundle, adoption)['context']['available']


@pytest.mark.parametrize('change', ['hash', 'missing', 'disabled'])
def test_bound_wiki_cache_updates_or_disabling_invalidate_scope(change):
    store, ledger, batch, bundle = local_context()
    ctx = bundle['context']
    cache_key = _bound_wiki_cache_key(ctx, 'W:S')
    cached = {'source_context': ctx, 'trusted': {'source_hash': 'OLD', 'grid': {'cells': [[1]]}}}
    store.put('state', {'id': cache_key, 'updated_at': '1', 'data': dumps(cached)})
    manifest = [{'source_kind': 'wiki_sheet', 'source_id': 'W:S:sheet:PUBLIC',
                 'resolver_source_id': 'W:S', 'source_context': ctx, 'selected': True}]
    adoption = adopt(store, ledger, batch, bundle, manifest)
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    # A successful read of the same archive must not expire the adopted rows.
    store.put('state', {'id': cache_key, 'updated_at': '2', 'data': dumps(cached)})
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    if change == 'hash': cached['trusted']['source_hash'] = 'NEW'
    elif change == 'missing': cached['trusted'] = None
    else: cached['disabled'] = True
    store.put('state', {'id': cache_key, 'updated_at': '3', 'data': dumps(cached)})
    assert not project(store, ledger, batch, bundle, adoption)['context']['available']


def test_replacing_synthetic_scope_inherits_and_rechecks_original_dependencies():
    store, ledger, batch, bundle = local_context()
    manifest = [{'source_kind': 'approval_form', 'source_id': 'FORM',
                 'process_instance_id': bundle['source']['instance'], 'selected': True}]
    original = adopt(store, ledger, batch, bundle, manifest)
    synthetic = [{'source_kind': 'approval_form', 'source_id': original['id'],
                  'scoped_packing': True, 'selected': True}]
    inherited = scope.capture_dependencies(synthetic, store=store, ledger=ledger, batch_name=batch['name'],
        source_context=bundle['context'], inherited=original)
    assert inherited == original['dependencies']
    changed = deepcopy(bundle['source'])
    changed['raw']['comments'] = [{'text': 'changed'}]
    store.put('source', {'id': changed['id'], 'data': dumps(changed)})
    with pytest.raises(ValueError, match='来源'):
        scope.capture_dependencies(synthetic, store=store, ledger=ledger, batch_name=batch['name'],
            source_context=bundle['context'], inherited=original)


def test_unselected_unavailable_manifest_rows_are_not_dependencies():
    store, ledger, batch, bundle = local_context()
    sources = [{'source_kind': 'approval_attachment', 'source_id': 'MISSING',
                'selected': False, 'excluded': True}]
    assert scope.capture_dependencies(sources, store=store, ledger=ledger, batch_name=batch['name'],
                                      source_context=bundle['context']) == []


def test_prior_selected_packing_attachment_uses_document_identity_instead_of_public_id():
    store, ledger, batch, bundle = local_context()
    document = {'id': 'DOC', 'source_id': bundle['source']['id'], 'fingerprint': 'H', 'status': 'parsed',
                'manifest': {'archive_quality': 'original_complete'}}
    store.put('document', {k: document[k] for k in ('id', 'source_id', 'fingerprint', 'status')} | {'data': dumps(document)})
    sources = [{'source_kind': 'approval_attachment', 'source_id': 'SELECTED-SLICE',
                'scoped_packing': True, 'selected': True, 'process_instance_id': bundle['source']['instance'],
                'selected_source': {'id': 'SELECTED-SLICE', 'document_id': 'DOC'}}]
    adoption = adopt(store, ledger, batch, bundle, sources)
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    document['manifest']['retired_at'] = 'now'
    store.put('document', {k: document[k] for k in ('id', 'source_id', 'fingerprint', 'status')} | {'data': dumps(document)})
    assert not project(store, ledger, batch, bundle, adoption)['context']['available']


def test_unbound_wiki_uses_local_confirmed_snapshot_without_upstream(monkeypatch):
    store, ledger, batch, bundle = local_context()
    bundle['context']['root_kind'] = 'logistics'
    snapshot = {'name': 'WIKI-LOCAL', 'batch': batch['name'], 'source_kind': 'wiki_sheet',
                'source_id': 'W:S', 'source_hash': 'OLD', 'status': 'Confirmed', 'is_current': 1,
                'material_rows_json': '[{"material_code":"A"}]'}
    ledger.frappe = SimpleNamespace(get_all=lambda *args, **kwargs: [deepcopy(snapshot)])
    from overseas_costing.integrations import dingtalk_packing_source
    monkeypatch.setattr(dingtalk_packing_source, 'get_packing_runtime_clients',
                        lambda: pytest.fail('Scope validation must never read upstream'))
    sources = [{'source_kind': 'wiki_sheet', 'source_id': 'W:S:sheet:PUBLIC',
                'resolver_source_id': 'W:S', 'selected': True}]
    adoption = adopt(store, ledger, batch, bundle, sources)
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    snapshot['source_hash'] = 'NEW'
    assert not project(store, ledger, batch, bundle, adoption)['context']['available']


def test_writer_preserves_manifest_resolver_identity_with_captured_dependencies():
    from overseas_costing.tests.test_ai_row_review_regressions import preview
    from overseas_costing.services.material_ai_selection_writer import write_rows
    store, ledger, batch, bundle = local_context()
    version = bundle['version']
    items = ledger.rows('item', batch=batch['name'], version=version['name'])
    selected = preview(items, [], batch, version, mode='replace_all', source_context=bundle['context'])
    selected['sources'] = [{'source_kind': 'approval_form', 'source_id': 'PUBLIC',
        'resolver_source_id': 'REAL', 'logical_source_id': 'LOGICAL', 'source_hash': 'H',
        'process_instance_id': bundle['source']['instance'], 'selected': True}]
    new_version = write_rows(store, ledger, selected, {})
    metadata = json.loads(ledger.get('version', new_version)['extra_json'])['ai_row_adoption']
    assert metadata['sources'][0]['resolver_source_id'] == 'REAL'
    assert metadata['sources'][0]['logical_source_id'] == 'LOGICAL'
    assert metadata['dependencies']
    current = load_source_bundle(batch['name'], new_version, store=store, ledger=ledger)
    assert current['context']['available']


def test_batch_approval_reference_disabling_invalidates_contributor():
    store, ledger, batch, bundle = local_context()
    ledger.put('batch', batch['name'], {'source_instance_id': bundle['source']['instance'],
                                      'source_approval_status': 'COMPLETED'})
    sources = [{'source_kind': 'approval_form', 'source_id': 'FORM',
                'process_instance_id': bundle['source']['instance'], 'selected': True}]
    adoption = adopt(store, ledger, batch, bundle, sources)
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    ledger.put('batch', batch['name'], {'source_approval_status': 'TERMINATED'})
    assert not project(store, ledger, batch, bundle, adoption)['context']['available']


@pytest.mark.parametrize('change', ['removed', 'retired', 'hash'])
def test_real_selected_packing_manifest_can_track_document_embedded_in_source(change):
    from overseas_costing.services.packing_snapshot_service import selected_packing_ai_sources
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    store, ledger, batch, bundle = local_context()
    source = deepcopy(bundle['source'])
    source['documents'] = [{'id': 'real-dhl-doc', 'status': 'parsed',
        'manifest': {'archive_quality': 'original', 'sha256': 'ARCHIVE-HASH'},
        'tables': [], 'freight_tables': [{'title': 'DHL快递', 'rows': [{'position': 11}]}]}]
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    selected = {'id': 'SELECTED-SLICE', 'source_id': source['id'], 'revision': 'REV',
        'source_kind': 'approval_attachment', 'source_label': 'DHL明细.xlsx · DHL快递',
        'approval_no': 'APPROVAL', 'document_id': 'real-dhl-doc', 'sheet': 'DHL快递',
        'evidence': {'document_id': 'real-dhl-doc', 'file_name': 'DHL明细.xlsx', 'sheet': 'DHL快递'}}
    bundle['source'] = source
    bundle['context']['packing'] = {**bundle['context'], 'selected_source': selected}
    sources = prepare_source_manifest(selected_packing_ai_sources(batch['name'], bundle))
    assert sources[0]['resolver_source_id'] == 'SELECTED-SLICE'
    assert sources[0]['source_id'] != sources[0]['resolver_source_id']
    assert store.get('document', 'real-dhl-doc') is None
    assert store.find('attachment_map', document_id='real-dhl-doc') == []

    adoption = adopt(store, ledger, batch, bundle, sources)
    assert project(store, ledger, batch, bundle, adoption)['context']['available']
    assert any(d['kind'] == 'source_document' and d['document_id'] == 'real-dhl-doc'
               for d in adoption['dependencies'])

    if change == 'removed': source['documents'] = []
    elif change == 'retired': source['documents'][0]['manifest']['retired_at'] = 'now'
    else: source['documents'][0]['manifest']['sha256'] = 'NEW-HASH'
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    assert not project(store, ledger, batch, bundle, adoption)['context']['available']
