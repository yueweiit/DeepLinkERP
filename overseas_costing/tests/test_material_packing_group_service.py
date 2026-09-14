from decimal import Decimal

import pytest

from overseas_costing.services.material_packing_group_service import (
    adopt_xlsx_group_candidates,
    allocate_group_values,
    build_group_preview,
    confirm_group_preview,
    prepare_group_preview,
    project_packing_groups,
)


def rows():
    return [
        {'name':'I1','stable_line_key':'L1','row_no':1,'package_count':20,'net_weight_kg':380,
         'gross_weight_kg':388,'volume_m3':'.4002','actual_shipped_qty':96000,'shipment_value_rmb':'14496'},
        {'name':'I2','stable_line_key':'L2','row_no':2,'package_count':1,'net_weight_kg':9,
         'gross_weight_kg':'9.7','volume_m3':'.00864','actual_shipped_qty':4000,'shipment_value_rmb':'604'},
        {'name':'I3','stable_line_key':'L3','row_no':3,'package_count':0,'net_weight_kg':0,
         'gross_weight_kg':0,'volume_m3':0,'actual_shipped_qty':4000,'shipment_value_rmb':'604'},
        {'name':'I4','stable_line_key':'L4','row_no':4,'package_count':4,'net_weight_kg':'31.2',
         'gross_weight_kg':32,'volume_m3':'.032016','actual_shipped_qty':96000,'shipment_value_rmb':'14496'},
    ]


def test_manual_group_preview_sums_first_three_rows_and_requires_confirmation():
    preview = build_group_preview(rows(), [], ['L1','L2','L3'], action='create', version='V1')

    assert preview['can_confirm'] is True
    assert preview['group']['member_keys'] == ['L1','L2','L3']
    assert preview['group']['package_count'] == '21'
    assert preview['group']['net_weight_kg'] == '389'
    assert preview['group']['gross_weight_kg'] == '397.7'
    assert preview['group']['volume_m3'] == '0.40884'
    assert preview['group']['creation_method'] == 'manual'


def test_group_preview_canonicalizes_click_order_and_keeps_integer_trailing_zeroes():
    preview = build_group_preview(rows(), [], ['L3','L1','L2'], action='create', version='V1',
                                  values={'package_count':'20'})

    assert preview['group']['member_keys'] == ['L1','L2','L3']
    assert preview['group']['package_count'] == '20'


def test_group_members_must_be_contiguous_unique_and_not_overlap():
    with pytest.raises(ValueError, match='连续'):
        build_group_preview(rows(), [], ['L1','L3'], action='create', version='V1')
    existing = [build_group_preview(rows(), [], ['L1','L2'], action='create', version='V1')['group']]
    with pytest.raises(ValueError, match='已属于'):
        build_group_preview(rows(), existing, ['L2','L3'], action='create', version='V1')
    with pytest.raises(ValueError, match='原因'):
        build_group_preview(rows(), existing, ['L1','L2'], action='remove',
                            version='V1', group_id=existing[0]['group_id'])


def test_group_allocation_prefers_shipment_value_and_keeps_exact_tail():
    allocated = allocate_group_values(rows()[:3], {'gross_weight_kg':'397.7','volume_m3':'0.40884'})

    assert allocated['basis'] == 'shipment_value_rmb'
    assert sum(Decimal(row['gross_weight_kg']) for row in allocated['rows']) == Decimal('397.7')
    assert sum(Decimal(row['volume_m3']) for row in allocated['rows']) == Decimal('0.40884')
    assert Decimal(allocated['rows'][0]['gross_weight_kg']) > Decimal(allocated['rows'][1]['gross_weight_kg'])


def test_group_allocation_falls_back_to_quantity_and_projection_counts_group_once():
    material_rows = rows()[:3]
    for row in material_rows:
        row['shipment_value_rmb'] = None
    group = build_group_preview(material_rows, [], ['L1','L2','L3'], action='create', version='V1')['group']

    projected = project_packing_groups(material_rows, [group])

    assert projected['groups'][0]['allocation_basis'] == 'actual_shipped_qty'
    assert sum(Decimal(str(row['gross_weight_kg'])) for row in projected['items']) == Decimal('397.7')
    assert [row['packing_group_position'] for row in projected['items']] == [0,1,2]
    assert projected['items'][0]['packing_group']['rowspan'] == 3
    assert [row['package_count'] for row in projected['items']] == ['21', '0', '0']


def test_group_without_value_or_quantity_basis_blocks_projection():
    material_rows = rows()[:2]
    for row in material_rows:
        row.update(shipment_value_rmb=None, actual_shipped_qty=0)
    group = build_group_preview(material_rows, [], ['L1','L2'], action='create', version='V1')['group']

    with pytest.raises(ValueError, match='分摊'):
        project_packing_groups(material_rows, [group])

    visible = project_packing_groups(material_rows, [group], strict=False)
    assert visible['groups'][0]['blocking'] is True
    assert '分摊' in visible['groups'][0]['blocking_reason']
    assert not any(row.get('packing_group_id') for row in visible['items'])


def test_only_real_xlsx_merge_candidates_are_adopted_without_overwriting_manual_groups():
    existing = [build_group_preview(rows(), [], ['L3', 'L4'], action='create', version='V1')['group']]
    candidates = [
        {'candidate_id':'XLSX-1','member_keys':['L1','L2'],'gross_weight_kg':'397.7',
         'volume_m3':'0.40884','package_count':'21','source_fingerprint':'HASH',
         'evidence':[{'kind':'xlsx_merge','field':'gross_weight_kg','start_row':2,'end_row':3}]},
        {'candidate_id':'GUESS','member_keys':['L2','L3'],'evidence':[{'kind':'blank_continuation_suggestion'}]},
    ]

    groups = adopt_xlsx_group_candidates(rows(), existing, candidates, 'PREVIEW', actor='source-confirmation')

    assert [group['group_id'] for group in groups] == [existing[0]['group_id'], 'XLSX-1']
    assert groups[1]['creation_method'] == 'xlsx_merge'
    assert groups[1]['confirmed_by'] == 'source-confirmation'
    assert groups[1]['source_fingerprint'] == 'HASH'

    partial = adopt_xlsx_group_candidates(rows(), [], candidates[:1], 'PREVIEW',
                                          confirmed_member_keys={'L1'})
    assert partial == [], 'A source group must not be created when only part of its rows was confirmed'


class Repo:
    def __init__(self):
        self.state = {'batch':'B1','batch_modified':'BM1','version':'V1','version_modified':'VM1',
                      'version_status':'Active','editable':True,'groups':[],'items':rows()}
        self.previews = {}
        self.saved = []

    def load(self, batch, version, *, lock=False):
        return {**self.state, 'groups':[dict(group) for group in self.state['groups']],
                'items':[dict(row) for row in self.state['items']]}

    def save_preview(self, preview):
        self.previews[preview['preview_id']] = preview

    def get_preview(self, preview_id):
        return self.previews.get(preview_id)

    def assert_write(self, batch, edit_token, expected_modified):
        if expected_modified != self.state['batch_modified']:
            raise ValueError('批次已变化')

    def save_groups(self, state, groups, preview, actor):
        self.state['groups'] = groups
        self.state['version_modified'] = 'VM2'
        self.state['batch_modified'] = 'BM2'
        self.saved.append(preview['preview_id'])
        return 'BM2'


def test_server_held_group_preview_confirms_once_and_rejects_stale_state():
    repo = Repo()
    prepared = prepare_group_preview('B1','V1',['L1','L2','L3'],'create',repository=repo)
    assert repo.state['groups'] == []

    result = confirm_group_preview('B1', prepared['preview_id'], prepared['revision'],
                                   'TOKEN', 'BM1', repository=repo, actor='user@example.com')
    assert result['ok'] and repo.state['groups'][0]['status'] == 'confirmed'
    assert repo.state['groups'][0]['last_preview_id'] == prepared['preview_id']

    stale_repo = Repo()
    stale = prepare_group_preview('B1','V1',['L1','L2'],'create',repository=stale_repo)
    stale_repo.state['items'][0]['gross_weight_kg'] = 999
    with pytest.raises(ValueError, match='已变化'):
        confirm_group_preview('B1', stale['preview_id'], stale['revision'],
                              'TOKEN', 'BM1', repository=stale_repo, actor='user@example.com')
