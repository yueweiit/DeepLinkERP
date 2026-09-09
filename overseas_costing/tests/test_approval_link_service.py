from copy import deepcopy
from types import SimpleNamespace

import pytest

from overseas_costing.services import dingtalk_approval_service as approvals


@pytest.fixture
def archive(monkeypatch):
    batch = dict(name='B1', batch_no='LOG1', source_type='oa_logistics',
                 source_approval_no='LOG1', source_instance_id='LOG',
                 extra_json={'linked_purchase_approvals': [{'source_instance_id': 'BUY'}]})
    bundle = {'instances': {
        'LOG': {'processInstanceId': 'LOG', 'businessId': 'LOG1'},
        'BUY': {'processInstanceId': 'BUY', 'businessId': 'PO1', 'status': 'RUNNING'},
    }}
    calls = []
    def lookup(ids):
        calls.append(ids)
        return bundle
    monkeypatch.setattr(approvals, 'frappe', SimpleNamespace(db=SimpleNamespace(get_value=lambda *a, **k: batch)))
    monkeypatch.setattr(approvals, '_trusted_linked_instance_ids', lambda payload: ['BUY'])
    monkeypatch.setattr(approvals, '_get_approval_source', lambda: SimpleNamespace(get_instance_bundle=lookup))
    return batch, bundle, calls


def test_batch_resolution_linked_running_legacy_logistics_and_missing(archive):
    from overseas_costing.services import approval_link_service as service
    rows = [{}, {'source_doc_no': 'PO1', 'dingtalk_instance_id': 'LOG'},
            {'dingtalk_instance_id': 'BUY'}, {'source_doc_no': 'UNKNOWN'},
            {'source_doc_no': 'LOG1', 'dingtalk_instance_id': 'LOG'}]
    original = deepcopy(rows)
    result = service.attach_approval_links('B1', rows)
    assert [r['approval_link']['status'] for r in result] == ['unlinked', 'linked', 'linked', 'unresolved', 'unresolved']
    assert result[1]['approval_link'] == dict(status='linked', label='', reason='', approval_no='PO1', instance_id='BUY')
    assert rows == original
    assert len(archive[2]) == 1


def test_missing_local_purchase_is_unresolved(archive):
    from overseas_costing.services import approval_link_service as service
    del archive[1]['instances']['BUY']
    assert service.attach_approval_links('B1', [{'dingtalk_instance_id': 'BUY'}])[0]['approval_link']['status'] == 'unresolved'


def test_archive_failure_is_nonblocking_and_empty_rows_remain_unlinked(archive, monkeypatch):
    from overseas_costing.services import approval_link_service as service
    def fail():
        raise RuntimeError('source unavailable')
    monkeypatch.setattr(approvals, '_get_approval_source', fail)
    rows = service.attach_approval_links('B1', [{}, {'source_doc_no': 'PO1'}])
    assert [r['approval_link']['status'] for r in rows] == ['unlinked', 'error']


def test_untrusted_purchase_and_mismatched_main_never_link(archive, monkeypatch):
    from overseas_costing.services import approval_link_service as service
    monkeypatch.setattr(approvals, '_trusted_linked_instance_ids', lambda payload: [])
    assert service.attach_approval_links('B1', [{'dingtalk_instance_id': 'BUY'}])[0]['approval_link']['status'] == 'unresolved'
    archive[1]['instances']['LOG']['businessId'] = 'OTHER'
    assert service.attach_approval_links('B1', [{'source_doc_no': 'PO1'}])[0]['approval_link']['status'] == 'unresolved'


def test_packing_metadata_preserves_unmatched_rows_and_hash(archive):
    from overseas_costing.services import approval_link_service as service
    comparison = {'preview_hash': 'signed', 'rows': [
        {'match_status': 'matched', 'target_stable_line_key': 'L1', 'source_rows': [2, 3]},
        {'match_status': 'choice_required', 'target_stable_line_key': ''}],
        'source_grid': {'sheet_name': 'Sheet A', 'row_states': [
            {'source_row': 2, 'state': 'matched', 'target_stable_line_keys': ['L1']},
            {'source_row': 3, 'state': 'matched', 'target_stable_line_keys': ['L1']},
            {'source_row': 4, 'state': 'outside', 'target_stable_line_keys': []},
            {'source_row': 5, 'state': 'choice_required', 'target_stable_line_keys': ['L1', 'L2']}]}}
    service.attach_preview_approval_links('B1', comparison, [{'stable_line_key': 'L1', 'source_doc_no': 'PO1'}])
    assert comparison['preview_hash'] == 'signed'
    assert comparison['rows'][0]['source_rows'] == [2, 3]
    assert comparison['rows'][0]['approval_link']['status'] == 'linked'
    assert comparison['rows'][1]['approval_link']['status'] == 'ambiguous'
    states = comparison['source_grid']['row_states']
    assert states[2]['match_status'] == 'unmatched'
    assert states[2]['match_label'] == '未匹配本批采购明细'
    assert 'approval_link' not in states[2]
    assert states[3]['approval_link']['status'] == 'ambiguous'
    assert states[1]['approval_link']['status'] == 'linked'


def test_material_and_sku_endpoints_expose_readonly_link(archive, monkeypatch):
    from overseas_costing.services import material_input_service as material, workbench_service as sku, batch_service, fee_service
    calls = []
    def query(doctype, **kwargs):
        calls.append(kwargs['fields'])
        if any(isinstance(field, dict) for field in kwargs['fields']):
            return [{'total': 1}]
        assert 'approval_link' not in kwargs['fields']
        assert 'dingtalk_instance_id' in kwargs['fields']
        return [{'name': 'I1', 'stable_line_key': 'L1', 'source_doc_no': 'PO1', 'dingtalk_instance_id': 'BUY'}]
    fake = SimpleNamespace(get_all=query, db=SimpleNamespace(count=lambda *a, **k: 1, get_value=lambda *a, **k: 'SEA'))
    monkeypatch.setattr(material, 'frappe', fake)
    monkeypatch.setattr(sku, 'frappe', fake)
    monkeypatch.setattr(batch_service, '_resolve_batch_name', lambda value: 'B1')
    monkeypatch.setattr(batch_service, '_resolve_version_name', lambda *a: 'V1')
    monkeypatch.setattr(batch_service, '_build_item_query_args', lambda *a, **k: ({}, []))
    monkeypatch.setattr(sku, '_load_sku_batch_meta', lambda *a: {})
    monkeypatch.setattr(fee_service, '_query_rules', lambda *a: [])
    monkeypatch.setattr(fee_service, 'compose_fee_worklist_rows', lambda *a: [])
    assert material.get_material_grid('B1')['items'][0]['approval_link']['status'] == 'linked'
    result = sku.get_batch_items_page('B1')
    assert result['items'][0]['approval_link']['status'] == 'linked'
    assert {'excel_col': '', 'fieldname': 'approval_link', 'label': '采购审批来源', 'read_only': 1} in result['columns']


def test_preview_dynamic_archive_state_does_not_change_revision(archive):
    from overseas_costing.tests.test_material_import_service import FakeRepository, _resolver_with_quantity
    from overseas_costing.services.material_import_service import preview_material_import
    repo = FakeRepository()
    def preview():
        return preview_material_import('B1', 'manual_xlsx', 'FILE-1', repository=repo,
                                       resolver=_resolver_with_quantity(), signing_key=b'secret')
    first = preview()
    assert first['rows'][0]['approval_link']['status'] == 'linked'
    del archive[1]['instances']['BUY']
    second = preview()
    assert second['rows'][0]['approval_link']['status'] == 'unresolved'
    assert first['preview_hash'] == second['preview_hash']
    assert first['preview_revision'] == second['preview_revision']
    assert not repo.writes and not repo.commits


def test_conflicting_trusted_identifiers_are_ambiguous(archive, monkeypatch):
    from overseas_costing.services import approval_link_service as service
    archive[0]['extra_json']['linked_purchase_approvals'].append({'source_instance_id': 'BUY2'})
    archive[1]['instances']['BUY2'] = {'processInstanceId': 'BUY2', 'businessId': 'PO2'}
    monkeypatch.setattr(approvals, '_trusted_linked_instance_ids', lambda payload: ['BUY', 'BUY2'])
    row = service.attach_approval_links('B1', [{'source_doc_no': 'PO1', 'dingtalk_instance_id': 'BUY2'}])[0]
    assert row['approval_link']['status'] == 'ambiguous'


def test_corrupt_archived_purchase_identity_cannot_link(archive):
    from overseas_costing.services import approval_link_service as service
    archive[1]['instances']['BUY']['processInstanceId'] = 'OTHER'
    assert service.attach_approval_links('B1', [{'source_doc_no': 'PO1'}])[0]['approval_link']['status'] == 'unresolved'


def test_packing_raw_unmatched_source_row_survives_real_preview(archive, tmp_path):
    from openpyxl import Workbook
    from overseas_costing.tests.test_material_import_service import FakeRepository
    from overseas_costing.services.material_import_service import preview_material_import
    from overseas_costing.utils.excel_workbook import read_packing_grid
    book = Workbook()
    sheet = book.active
    sheet.title = '原始装箱单'
    sheet.append(['物料编码', '中文品名', '数量', '单位', '总净重', '总毛重', '总体积'])
    sheet.append(['M1', '本批', 10, '桶', 1, 2, 3])
    sheet.append(['OUTSIDE', '其他物料', 20, '桶', 2, 4, 6])
    path = tmp_path / 'packing.xlsx'
    book.save(path)
    grid = read_packing_grid(str(path), sheet_name=sheet.title, require_exact_sheet=True)
    result = preview_material_import('B1', 'approval_attachment', 'ATT-1', repository=FakeRepository(),
        resolver=lambda **kwargs: {'source_hash': 'a' * 64, 'source': {'sheet_name': sheet.title}, 'grid': grid},
        signing_key=b'secret')
    source = result['source_grid']
    assert source['sheet_name'] == sheet.title
    assert source['cells'][2][0]['raw_value'] == 'OUTSIDE'
    assert source['row_states'][2]['source_row'] == 3
    assert source['row_states'][2]['match_label'] == '未匹配本批采购明细'
    assert source['row_states'][1]['approval_link']['status'] == 'linked'


def test_merged_choice_preview_has_links_without_changing_confirmation_hash(archive, monkeypatch):
    from overseas_costing.tests.test_material_grid_reviews import _grid, _preview, _resolver
    from overseas_costing.tests.test_material_import_service import FakeRepository
    from overseas_costing.services.material_import_service import apply_material_import
    repo = FakeRepository()
    repo.items.append({'name': 'I2', 'stable_line_key': 'L2', 'material_code': 'M1', 'source_doc_no': 'PO1'})
    grid = _grid(rows=[['M1', 'PO1', 'A', 6, 8, 10, 0.3], ['M1', 'PO1', 'A', 4, 8, 10, 0.3]])
    preview = _preview(grid, repo=repo)
    assert preview['rows'][0]['approval_link']['status'] == 'ambiguous'
    choices = {'matches': {'2': 'L1', '3': 'L1'}}
    def apply():
        return apply_material_import('B1', preview['preview_revision'], choices, 'edit', 'BM1',
                                     repository=repo, resolver=_resolver(grid), signing_key=b'key')
    result = apply()
    assert result['code'] == 'MERGED_PREVIEW_CONFIRMATION_REQUIRED'
    merged = result['merged_preview']
    assert merged['rows'][0]['source_rows'] == [2, 3]
    assert merged['rows'][0]['approval_link']['status'] == 'linked'
    assert merged['source_grid']['cells'] == preview['source_grid']['cells']
    assert all(state['approval_link']['status'] == 'linked' for state in merged['source_grid']['row_states'][1:])
    assert all(state['match_status'] == 'matched' for state in merged['source_grid']['row_states'][1:])
    assert all(state['state'] == 'choice_required' for state in merged['source_grid']['row_states'][1:])
    failed_lookups = []
    def fail():
        failed_lookups.append(True)
        raise RuntimeError('archive unavailable')
    monkeypatch.setattr(approvals, '_get_approval_source', fail)
    failed_source = apply()
    assert failed_source['code'] == 'MERGED_PREVIEW_CONFIRMATION_REQUIRED'
    assert failed_source['merged_preview']['rows'][0]['approval_link']['status'] == 'error'
    assert failed_source['merged_preview_hash'] == result['merged_preview_hash']
    assert not repo.writes and not repo.commits
    choices['merged_preview_hash'] = result['merged_preview_hash']
    choices['fields'] = {str(row['source_row']): {change['field']: 'use_source' for change in row['changes']}
                         for row in merged['rows']}
    calls_before = (len(archive[2]), len(failed_lookups))
    approved = apply()
    assert approved['ok'] is True
    assert (len(archive[2]), len(failed_lookups)) == calls_before
    assert len(repo.writes) == 1
