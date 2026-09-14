import json
import pytest

from overseas_costing.services import material_ai_row_selection as rows
from overseas_costing.services.material_ai_row_recovery import confirm_recovery, preview_recovery
from overseas_costing.services.material_ai_selection_writer import write_rows
from overseas_costing.services.effective_logistics_source import load_source_bundle
from overseas_costing.tests.test_freight_lines import setup_cost


def _replace_one_of_eight():
    store, ledger, batch, version, first, *_ = setup_cost()
    for index in range(2, 9):
        ledger.create('item', {
            'batch': batch['name'], 'version': version['name'], 'row_no': index,
            'material_code': f'SKU-{index}', 'product_name': f'Product {index}',
            'unit': '件', 'quantity': index, 'gross_weight_kg': index,
        })
    items = ledger.rows('item', batch=batch['name'], version=version['name'])
    proposal = {
        'proposal_id': 'BAD-REPLACE', 'proposal_type': 'item_update',
        'target_item_name': first['name'], 'default_selected': True,
        'source_refs': [{'source_id': 'PACKING-LIST'}],
        'payload': {'fields': {'gross_weight_kg': 99}},
    }
    catalog = rows.catalog(items, [proposal], [], {}, run_id='RUN')
    selected = next(row for row in catalog['rows'] if row['origin'] == 'source')
    projected = rows.project(items, catalog, [selected['row_id']], [], 'replace_all')
    projected.update(id='BAD-PREVIEW', revision='BAD-REV', run_id='RUN', batch=batch['name'],
                     version=version['name'], source_context=load_source_bundle(
                         batch['name'], version['name'], store=store, ledger=ledger)['context'], sources=[])
    current_version = write_rows(store, ledger, projected, {})
    store.audit(batch['name'], 'ai_rows_adopted', 'original-user', run_id='RUN',
                preview_id='BAD-PREVIEW', mode='replace_all', old_version=version['name'],
                version=current_version, selected_row_ids=[selected['row_id']], selected_fee_ids=[])
    return store, ledger, batch, version, current_version


def test_recovery_preview_restores_unselected_rows_without_writing_business_data():
    store, ledger, batch, old_version, current_version = _replace_one_of_eight()
    before_versions = ledger.rows('version', batch=batch['name'])
    before_items = ledger.rows('item', batch=batch['name'], version=current_version)

    preview = preview_recovery(store, ledger, batch['name'], current_version)

    assert preview['ok'] and preview['can_confirm']
    assert preview['old_version'] == old_version['name']
    assert preview['current_version'] == current_version
    assert preview['current_count'] == 1
    assert preview['restored_count'] == 7
    assert len(preview['rows']) == 8
    assert len(preview['before_rows']) == 1
    assert len(preview['after_rows']) == 8
    assert ledger.rows('version', batch=batch['name']) == before_versions
    assert ledger.rows('item', batch=batch['name'], version=current_version) == before_items


def test_confirmed_recovery_creates_audited_version_and_preserves_selected_row_update():
    store, ledger, batch, _old_version, current_version = _replace_one_of_eight()
    preview = preview_recovery(store, ledger, batch['name'], current_version)

    applied = confirm_recovery(store, ledger, batch['name'], current_version,
        preview['id'], preview['revision'], 'finance-user')

    recovered = ledger.rows('item', batch=batch['name'], version=applied['version_name'])
    assert len(recovered) == 8
    assert next(row for row in recovered if row['material_code'] == 'AA100')['gross_weight_kg'] == 99
    assert {row['material_code'] for row in recovered} == {'AA100', *{f'SKU-{index}' for index in range(2, 9)}}
    metadata = json.loads(ledger.get('version', applied['version_name']).get('extra_json') or '{}')
    assert 'ai_row_adoption' not in metadata
    assert metadata['material_row_recovery']['preview_id'] == preview['id']
    assert ledger.get('batch', batch['name'])['current_version'] == applied['version_name']
    assert confirm_recovery(store, ledger, batch['name'], applied['version_name'],
        preview['id'], preview['revision'], 'finance-user')['idempotent']


def test_recovery_stops_when_current_row_cannot_match_history_uniquely():
    store, ledger, batch, old_version, current_version = _replace_one_of_eight()
    current = ledger.rows('item', batch=batch['name'], version=current_version)[0]
    metadata = json.loads(current.get('extra_json') or '{}')
    metadata.pop('ai_fill_original_values', None)
    metadata.pop('settlement_original_values', None)
    ledger.put('item', current['name'], {'stable_line_key': '', 'extra_json': json.dumps(metadata)})
    historical = ledger.rows('item', batch=batch['name'], version=old_version['name'])
    ledger.put('item', historical[1]['name'], {
        'material_code': current['material_code'], 'product_name': current['product_name'],
        'spec_model': current.get('spec_model'), 'unit': current.get('unit'),
    })

    preview = preview_recovery(store, ledger, batch['name'], current_version)

    assert not preview['can_confirm']
    assert any('无法唯一匹配' in issue for issue in preview['issues'])
    with pytest.raises(ValueError, match='历史或当前物料已变化'):
        confirm_recovery(store, ledger, batch['name'], current_version,
            preview['id'], preview['revision'], 'finance-user')


def test_recovery_is_unavailable_without_a_legacy_replace_audit():
    store, ledger, batch, version, *_ = setup_cost()

    with pytest.raises(ValueError, match='没有可恢复'):
        preview_recovery(store, ledger, batch['name'], version['name'])
