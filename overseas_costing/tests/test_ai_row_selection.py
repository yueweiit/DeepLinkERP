import json
import pytest
from overseas_costing.services import material_ai_row_selection as service


def item(name='I1', code='A1', **fields):
    return {'name':name,'material_code':code,'product_name':code,'quantity':'1','actual_shipped_qty':'1','unit':'件','shipped_uom':'件',**fields}


def reconcile(rows):
    return {'proposal_id':'P','proposal_type':'logistics_reconcile','default_selected':True,
            'source_refs':[{'source_id':'L','field':'goods'}], 'payload':{'rows':rows}}


def catalog(items, proposals, sources=None):
    return service.catalog(items,proposals,[],{},run_id='R',sources=sources)


def source(code='A1', **fields):
    return item('draft-'+code,code,_review_origin='source',**fields)


def test_fill_missing_replaces_weight_placeholder_zero_and_preserves_quantity():
    rows=[item(gross_weight_kg=0,volume_m3=None)]
    c=catalog(rows,[reconcile([source(actual_shipped_qty='4',gross_weight_kg='7',volume_m3='2')])])
    selected=next(r for r in c['rows'] if r['origin']=='source')
    p=service.project(rows,c,[selected['row_id']],[],'fill_missing')
    assert p['rows'][0]['actual_shipped_qty']=='1'
    assert p['rows'][0]['gross_weight_kg']=='7'
    assert p['rows'][0]['volume_m3']=='2'


def test_fill_missing_preserves_explicitly_confirmed_zero_shipped_quantity():
    rows=[item(actual_shipped_qty=0,actual_shipped_qty_mode='MANUAL_CONFIRMED',gross_weight_kg=None)]
    c=catalog(rows,[reconcile([source(actual_shipped_qty='4',gross_weight_kg='7')])])
    selected=next(r for r in c['rows'] if r['origin']=='source')

    projected=service.project(rows,c,[selected['row_id']],[],'fill_missing')

    assert projected['rows'][0]['actual_shipped_qty']==0
    assert projected['rows'][0]['gross_weight_kg']=='7'


@pytest.mark.parametrize('proposal', [
    reconcile([source(actual_shipped_qty=0,actual_shipped_qty_mode='EXPLICIT_SOURCE',gross_weight_kg=7)]),
    {'proposal_id':'SYSTEM','proposal_type':'item_update','target_item_name':'I1',
     'default_selected':True,'result_origin':'SYSTEM',
     'payload':{'fields':{'actual_shipped_qty':0,'gross_weight_kg':7}}},
])
def test_explicit_source_zero_quantity_counts_and_projects_as_meaningful(proposal):
    rows=[item(actual_shipped_qty=3,gross_weight_kg=None)]

    review=catalog(rows,[proposal])
    selected=next(row for row in review['rows'] if row['origin']=='source')
    projected=service.project(rows,review,[selected['row_id']],[],'update_selected')

    assert selected['meaningful_field_count'] >= 2
    assert projected['rows'][0]['actual_shipped_qty']==0
    assert projected['rows'][0]['gross_weight_kg']==7


def test_placeholder_quantity_does_not_block_other_meaningful_fields():
    rows=[item(actual_shipped_qty=3,gross_weight_kg=None)]

    review=catalog(rows,[reconcile([source(actual_shipped_qty='/',gross_weight_kg=7)])])
    selected=next(row for row in review['rows'] if row['origin']=='source')
    projected=service.project(rows,review,[selected['row_id']],[],'update_selected')

    assert selected['can_update']
    assert selected['default_update_selected']
    assert projected['rows'][0]['actual_shipped_qty']==3
    assert projected['rows'][0]['gross_weight_kg']==7


def test_explicit_missing_zero_is_fillable():
    rows=[item(gross_weight_kg=0,extra_json=json.dumps({'settlement_packing_missing':['gross_weight_kg']}))]
    c=catalog(rows,[reconcile([source(gross_weight_kg='7')])])
    p=service.project(rows,c,[c['rows'][0]['row_id']],[],'fill_missing')
    assert p['rows'][0]['gross_weight_kg']=='7'


def test_catalog_keeps_a_safe_default_for_whole_table_replacement():
    items=[item(gross_weight_kg='1')]
    proposal={'proposal_id':'P','proposal_type':'item_update','target_item_name':'I1',
              'default_selected':True,'payload':{'fields':{'gross_weight_kg':'2'}}}

    selected=next(row for row in catalog(items,[proposal])['rows'] if row['origin']=='source')

    assert not selected['default_selected']
    assert selected['default_replace_selected']


def test_update_selected_changes_one_of_eight_without_removing_other_rows():
    items = [item(f'I{index}', f'SKU-{index}', gross_weight_kg=index) for index in range(1, 9)]
    proposal = {
        'proposal_id': 'P-UPDATE',
        'proposal_type': 'item_update',
        'target_item_name': 'I4',
        'default_selected': True,
        'source_refs': [{'source_id': 'PACKING-LIST', 'field': '毛重'}],
        'payload': {'fields': {'gross_weight_kg': '99'}},
    }
    review = catalog(items, [proposal])
    selected = next(row for row in review['rows'] if row['origin'] == 'source')

    assert selected['action'] == 'update'
    assert selected['can_update']
    assert selected['default_update_selected']

    projected = service.project(items, review, [selected['row_id']], [], 'update_selected')

    assert len(projected['rows']) == 8
    assert [row['name'] for row in projected['rows']] == [f'I{index}' for index in range(1, 9)]
    assert next(row for row in projected['rows'] if row['name'] == 'I4')['gross_weight_kg'] == '99'
    assert [row['gross_weight_kg'] for row in projected['rows'] if row['name'] != 'I4'] == [1, 2, 3, 5, 6, 7, 8]
    assert projected['updated_count'] == 1
    assert projected['added_count'] == 0
    assert projected['removed_count'] == 0


def test_update_selected_carries_trusted_price_lineage_for_server_writer():
    items = [item('I1', 'SKU-1', unit_price=10)]
    proposal = reconcile([source(
        'SKU-1',
        unit_price=12,
        _review_purchase_values={'unit_price': 12},
        _review_price_metadata={'logistics_row': {'purchase_fact': {'unit_price': 12}}},
    )])

    review = catalog(items, [proposal])
    selected = next(row for row in review['rows'] if row['origin'] == 'source')
    projected = service.project(items, review, [selected['row_id']], [], 'update_selected')

    assert projected['rows'][0]['unit_price'] == 12
    assert projected['rows'][0]['_price_metadata']['logistics_row']['purchase_fact']['unit_price'] == 12


def test_update_matching_prefers_stable_line_then_unique_material_code():
    by_stable = [item('I1', 'OLD', stable_line_key='LINE-1', spec_model='OLD-SPEC')]
    stable_review = catalog(by_stable, [reconcile([
        source('NEW', stable_line_key='LINE-1', spec_model='NEW-SPEC', gross_weight_kg=5)
    ])])
    stable_row = next(row for row in stable_review['rows'] if row['origin'] == 'source')
    assert stable_row['target_item_name'] == 'I1' and stable_row['action'] == 'update'

    by_code = [item('I2', 'SKU-2', spec_model='OLD-SPEC', unit='件', shipped_uom='件')]
    code_review = catalog(by_code, [reconcile([
        source('SKU-2', spec_model='NEW-SPEC', unit='箱', shipped_uom='箱', gross_weight_kg=6)
    ])])
    code_row = next(row for row in code_review['rows'] if row['origin'] == 'source')
    assert code_row['target_item_name'] == 'I2' and code_row['action'] == 'update'


def test_update_selected_marks_unmatched_source_as_separate_add_candidate():
    items = [item('I1', 'SKU-1')]
    review = catalog(items, [reconcile([source('SKU-NEW')])])
    selected = next(row for row in review['rows'] if row['origin'] == 'source')

    assert selected['action'] == 'add_candidate'
    assert not selected['can_update']
    assert not selected['can_fill']
    assert selected['can_add']
    assert '新增' in selected['blocked_reason']
    with pytest.raises(ValueError, match='单独确认新增'):
        service.project(items, review, [selected['row_id']], [], 'update_selected')
    with pytest.raises(ValueError, match='单独确认新增'):
        service.project(items, review, [selected['row_id']], [], 'fill_missing')


def test_unmatched_source_adds_only_in_separate_add_selected_mode():
    items = [item('I1', 'SKU-1')]
    review = catalog(items, [reconcile([source('SKU-NEW', gross_weight_kg=7)])])
    selected = next(row for row in review['rows'] if row['origin'] == 'source')

    projected = service.project(items, review, [selected['row_id']], [], 'add_selected')

    assert len(projected['rows']) == 2
    assert projected['rows'][0]['name'] == 'I1'
    assert projected['rows'][1]['material_code'] == 'SKU-NEW'
    assert projected['added_count'] == 1
    assert projected['removed_count'] == 0
    with pytest.raises(ValueError, match='不能同时采用费用'):
        service.project(items, review, [selected['row_id']], ['FEE'], 'add_selected')


def test_catalog_groups_sources_by_priority_and_marks_lower_priority_conflicts():
    items = [item('I1', 'SKU-1', gross_weight_kg=None, volume_m3=None)]
    sources = [
        {'source_id': 'LOGISTICS-OA', 'source_kind': 'approval_form',
         'source_label': '国际物流审批', 'approval_role': 'international_logistics'},
        {'source_id': 'PACKING-LIST', 'source_kind': 'approval_attachment',
         'source_label': '装箱清单.xlsx', 'approval_role': 'international_logistics',
         'source_field': '装箱单附件（Excel）'},
    ]
    proposals = [
        {'proposal_id': 'HIGH', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'PACKING-LIST'}],
         'payload': {'fields': {'gross_weight_kg': 9}}},
        {'proposal_id': 'LOW', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'LOGISTICS-OA'}],
         'payload': {'fields': {'gross_weight_kg': 8, 'volume_m3': 2}}},
    ]

    review = catalog(items, proposals, sources)
    source_rows = {row['proposal_id']: row for row in review['rows'] if row['origin'] == 'source'}

    assert [group['source_id'] for group in review['source_groups'][:2]] == ['PACKING-LIST', 'LOGISTICS-OA']
    assert source_rows['HIGH']['source_priority'] < source_rows['LOW']['source_priority']
    assert source_rows['HIGH']['default_update_selected']
    assert source_rows['LOW']['default_update_selected']
    assert source_rows['HIGH']['meaningful_field_count'] == 1
    assert source_rows['LOW']['meaningful_field_count'] == 2
    assert '逐字段' in source_rows['LOW']['default_selection_reason']
    assert source_rows['LOW']['conflict_fields'] == ['gross_weight_kg']

    choices = {
        f"I1:{candidate['fieldname']}": candidate['candidate_id']
        for candidate in review['field_candidates'] if candidate['default_selected']
    }
    projected = service.project(items, review, [], [], 'update_selected', field_choices=choices)
    assert projected['rows'][0]['gross_weight_kg'] == 9
    assert projected['rows'][0]['volume_m3'] == 2
    adopted = {(row['item_name'], row['fieldname']): row for row in projected['actual_sources']}
    assert adopted[('I1', 'gross_weight_kg')]['row_id'] == source_rows['HIGH']['row_id']


def test_distinct_fields_are_combined_from_each_best_available_source():
    items = [item('I1', 'SKU-1', gross_weight_kg=None, volume_m3=None)]
    sources = [
        {'source_id': 'PACK', 'source_kind': 'approval_attachment',
         'source_field': '装箱单附件（Excel）'},
        {'source_id': 'OA', 'source_kind': 'approval_form', 'approval_role': 'international_logistics'},
    ]
    proposals = [
        {'proposal_id': 'PACK', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'PACK'}],
         'payload': {'fields': {'gross_weight_kg': 9}}},
        {'proposal_id': 'OA', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'OA'}],
         'payload': {'fields': {'volume_m3': 2}}},
    ]

    review = catalog(items, proposals, sources)
    candidates = {row['proposal_id']: row for row in review['rows'] if row['origin'] == 'source'}

    assert candidates['PACK']['default_update_selected']
    assert candidates['OA']['default_update_selected']
    assert candidates['PACK']['meaningful_field_count'] == 1
    assert candidates['OA']['meaningful_field_count'] == 1
    defaults = {
        candidate['fieldname']: candidate
        for candidate in review['field_candidates'] if candidate['default_selected']
    }
    assert defaults['gross_weight_kg']['row_id'] == candidates['PACK']['row_id']
    assert defaults['volume_m3']['row_id'] == candidates['OA']['row_id']
    assert not candidates['OA']['conflict_fields']


def test_lower_priority_fills_missing_fields_without_overriding_higher_priority_values():
    items = [item('I1', 'FL004107', gross_weight_kg=None, volume_m3=None)]
    sources = [
        {'source_id': 'PACK', 'source_kind': 'approval_attachment',
         'source_field': '装箱单附件（Excel）'},
        {'source_id': 'OA', 'source_kind': 'approval_form', 'approval_role': 'international_logistics'},
    ]
    proposals = [
        {'proposal_id': 'PACK', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'PACK'}],
         'payload': {'fields': {'actual_shipped_qty': 200, 'shipped_uom': '个',
                                'package_count': 0, 'net_weight_kg': '-',
                                'gross_weight_kg': '/', 'volume_m3': '—'}}},
        {'proposal_id': 'OA', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'OA'}],
         'payload': {'fields': {'actual_shipped_qty': 500, 'shipped_uom': '个',
                                'package_count': 1, 'net_weight_kg': 12.9,
                                'gross_weight_kg': 13.4, 'volume_m3': 0.03528,
                                'project_collection': '贸易项目'}}},
    ]

    review = catalog(items, proposals, sources)
    candidates = {row['proposal_id']: row for row in review['rows'] if row['origin'] == 'source'}

    assert candidates['PACK']['meaningful_field_count'] == 2
    assert candidates['OA']['meaningful_field_count'] == 7
    assert candidates['PACK']['default_update_selected']
    assert candidates['OA']['default_update_selected']

    choices = {
        f"I1:{candidate['fieldname']}": candidate['candidate_id']
        for candidate in review['field_candidates'] if candidate['default_selected']
    }
    projected = service.project(items, review, [], [], 'update_selected', field_choices=choices)
    assert projected['rows'][0]['actual_shipped_qty'] == 200
    assert projected['rows'][0]['package_count'] == 1
    assert projected['rows'][0]['gross_weight_kg'] == 13.4

    placeholder_projection = service.project(items, review, [candidates['PACK']['row_id']], [], 'update_selected')
    assert placeholder_projection['rows'][0]['actual_shipped_qty'] == 200
    assert placeholder_projection['rows'][0].get('package_count') is None
    assert placeholder_projection['rows'][0].get('net_weight_kg') is None
    assert placeholder_projection['rows'][0].get('gross_weight_kg') is None
    assert placeholder_projection['rows'][0].get('volume_m3') is None


def test_payment_logistics_purchase_priority_is_applied_per_field_and_lower_value_can_be_chosen():
    items = [item('I1', 'SKU-1', gross_weight_kg=None, volume_m3=None)]
    sources = [
        {'source_id': 'PURCHASE', 'source_kind': 'approval_form', 'approval_role': 'purchase',
         'approval_title': '商品采购支出'},
        {'source_id': 'LOGISTICS', 'source_kind': 'approval_form',
         'approval_role': 'international_logistics', 'approval_title': '国际物流审批'},
        {'source_id': 'PAYMENT', 'source_kind': 'approval_form',
         'approval_role': 'logistics_expense', 'approval_title': '费用支出'},
    ]
    proposals = [
        {'proposal_id': 'PURCHASE', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'confidence': .99, 'default_selected': True, 'source_refs': [{'source_id': 'PURCHASE'}],
         'payload': {'fields': {'gross_weight_kg': 7, 'volume_m3': 1}}},
        {'proposal_id': 'LOGISTICS', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'confidence': .99, 'default_selected': True, 'source_refs': [{'source_id': 'LOGISTICS'}],
         'payload': {'fields': {'gross_weight_kg': 8, 'volume_m3': 2}}},
        {'proposal_id': 'PAYMENT', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'confidence': .99, 'default_selected': True, 'source_refs': [{'source_id': 'PAYMENT'}],
         'payload': {'fields': {'gross_weight_kg': 9}}},
    ]

    review = catalog(items, proposals, sources)
    by_field = {}
    for candidate in review['field_candidates']:
        by_field.setdefault(candidate['fieldname'], []).append(candidate)
    assert next(row for row in by_field['gross_weight_kg'] if row['default_selected'])['workflow_stage'] == 'payment'
    assert next(row for row in by_field['volume_m3'] if row['default_selected'])['workflow_stage'] == 'international_logistics'

    selected = {
        'I1:gross_weight_kg': next(row for row in by_field['gross_weight_kg'] if row['workflow_stage'] == 'international_logistics')['candidate_id'],
        'I1:volume_m3': next(row for row in by_field['volume_m3'] if row['default_selected'])['candidate_id'],
    }
    projected = service.project(items, review, [], [], 'update_selected', field_choices=selected)
    assert projected['rows'][0]['gross_weight_kg'] == 8
    assert projected['rows'][0]['volume_m3'] == 2


def test_unreadable_higher_priority_source_does_not_block_lower_priority_default():
    items = [item('I1', 'SKU-1', gross_weight_kg=None)]
    sources = [
        {'source_id': 'PAYMENT-FAILED', 'source_kind': 'approval_attachment',
         'source_label': '费用支出附件.xlsx', 'approval_role': 'logistics_expense',
         'approval_title': '费用支出', 'read_status': 'FAILED', 'error': '无权读取'},
        {'source_id': 'LOGISTICS', 'source_kind': 'approval_form',
         'source_label': '国际物流审批正文', 'approval_role': 'international_logistics',
         'approval_title': '国际物流审批', 'read_status': 'READ'},
    ]
    proposals = [
        {'proposal_id': 'LOGISTICS', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'confidence': .99, 'default_selected': True, 'source_refs': [{'source_id': 'LOGISTICS'}],
         'payload': {'fields': {'gross_weight_kg': 8}}},
    ]

    review = catalog(items, proposals, sources)
    candidates = [row for row in review['field_candidates'] if row['fieldname'] == 'gross_weight_kg']

    assert len(candidates) == 1
    assert candidates[0]['workflow_stage'] == 'international_logistics'
    assert candidates[0]['default_selected'] is True


def test_evidence_priority_is_applied_per_field_within_one_workflow_source():
    items = [item('I1', 'SKU-1', gross_weight_kg=None, volume_m3=None)]
    sources = [
        {'source_id': 'PAY-ATTACHMENT', 'parent_source_id': 'PAY',
         'source_kind': 'approval_attachment', 'source_field': '装箱单附件（Excel）',
         'source_label': '费用支出·装箱单.xlsx', 'approval_role': 'logistics_expense'},
        {'source_id': 'PAY-COMMENT', 'parent_source_id': 'PAY',
         'source_kind': 'approval_comment', 'source_label': '费用支出·评论',
         'approval_role': 'logistics_expense'},
    ]
    proposals = [
        {'proposal_id': 'ATTACHMENT', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'confidence': .99, 'default_selected': True,
         'source_refs': [{'source_id': 'PAY-ATTACHMENT'}],
         'payload': {'fields': {'gross_weight_kg': 9}}},
        {'proposal_id': 'COMMENT', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'confidence': .99, 'default_selected': True,
         'source_refs': [{'source_id': 'PAY-COMMENT'}],
         'payload': {'fields': {'gross_weight_kg': 8, 'volume_m3': 2}}},
    ]

    review = catalog(items, proposals, sources)
    by_field = {}
    for candidate in review['field_candidates']:
        by_field.setdefault(candidate['fieldname'], []).append(candidate)

    gross_default = next(row for row in by_field['gross_weight_kg'] if row['default_selected'])
    volume_default = next(row for row in by_field['volume_m3'] if row['default_selected'])
    comment_gross = next(row for row in by_field['gross_weight_kg'] if row['row_id'] != gross_default['row_id'])
    assert gross_default['evidence_kind'] == 'dedicated_attachment'
    assert volume_default['evidence_kind'] == 'comment'
    assert comment_gross['evidence_kind'] == 'comment'
    assert comment_gross['can_apply'] is True
    assert len(review['source_groups']) == 1


def test_same_rank_conflicting_values_require_manual_field_choice():
    items = [item('I1', 'SKU-1', gross_weight_kg=None)]
    sources = [
        {'source_id': source_id, 'source_kind': 'approval_form',
         'approval_role': 'logistics_expense', 'approval_title': '费用支出'}
        for source_id in ('PAY-A', 'PAY-B')
    ]
    proposals = [
        {'proposal_id': source_id, 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'confidence': .99, 'default_selected': False, 'conflict': True,
         'source_refs': [{'source_id': source_id}], 'payload': {'fields': {'gross_weight_kg': value}}}
        for source_id, value in (('PAY-A', 8), ('PAY-B', 9))
    ]

    review = catalog(items, proposals, sources)
    candidates = [row for row in review['field_candidates'] if row['fieldname'] == 'gross_weight_kg']

    assert len(candidates) == 2
    assert not any(row['default_selected'] for row in candidates)
    assert all(row['can_apply'] for row in candidates)
    assert all('同级' in row['resolution_reason'] for row in candidates)


def test_existing_confirmed_value_is_not_replaced_by_a_default_field_choice():
    items = [item('I1', 'SKU-1', gross_weight_kg=5, manual_override_flag=1)]
    proposal = {
        'proposal_id':'P','proposal_type':'item_update','target_item_name':'I1',
        'confidence':.99,'default_selected':False,'conflict':True,
        'existing_value_conflict_fields':['gross_weight_kg'],
        'source_refs':[{'source_id':'PAY'}],'payload':{'fields':{'gross_weight_kg':9}},
    }
    review = catalog(items, [proposal], [{
        'source_id':'PAY','source_kind':'approval_form','approval_role':'logistics_expense',
    }])

    candidate = next(row for row in review['field_candidates'] if row['fieldname']=='gross_weight_kg')
    assert candidate['can_apply'] is True
    assert candidate['default_selected'] is False


def test_same_source_conflicting_field_values_do_not_use_stable_id_as_business_decision():
    items = [item('I1', 'SKU-1', gross_weight_kg=None, volume_m3=None)]
    sources = [{'source_id': 'PACK', 'source_kind': 'approval_attachment',
                'source_field': '装箱单附件（Excel）'}]
    proposals = [
        {'proposal_id': proposal_id, 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'PACK'}],
         'payload': {'fields': {'gross_weight_kg': value}}}
        for proposal_id, value in [('FIRST', 9), ('SECOND', 8)]
    ]

    review = catalog(items, proposals, sources)
    candidates = [row for row in review['rows'] if row['origin'] == 'source']

    assert not [row for row in candidates if row['default_update_selected']]
    field_candidates = [row for row in review['field_candidates'] if row['fieldname'] == 'gross_weight_kg']
    assert len(field_candidates) == 2
    assert not any(row['default_selected'] for row in field_candidates)


def test_more_complete_unsafe_candidate_is_not_promoted():
    items = [item('I1', 'SKU-1', gross_weight_kg=None, volume_m3=None)]
    sources = [
        {'source_id': 'PACK', 'source_kind': 'approval_attachment',
         'source_field': '装箱单附件（Excel）'},
        {'source_id': 'OA', 'source_kind': 'approval_form', 'approval_role': 'international_logistics'},
    ]
    proposals = [
        {'proposal_id': 'SAFE', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': True, 'source_refs': [{'source_id': 'PACK'}],
         'payload': {'fields': {'gross_weight_kg': 9}}},
        {'proposal_id': 'UNSAFE', 'proposal_type': 'item_update', 'target_item_name': 'I1',
         'default_selected': False, 'source_refs': [{'source_id': 'OA'}],
         'payload': {'fields': {'gross_weight_kg': 8, 'volume_m3': 2}}},
    ]

    review = catalog(items, proposals, sources)
    candidates = {row['proposal_id']: row for row in review['rows'] if row['origin'] == 'source'}

    assert candidates['SAFE']['default_update_selected']
    assert not candidates['UNSAFE']['default_update_selected']


def test_source_groups_expose_server_priority_reason_and_actual_match_status():
    from overseas_costing.services.source_priority_service import rank_material_packing_sources

    items = [item('I1', 'SKU-1', gross_weight_kg=None)]
    sources = rank_material_packing_sources([
        {'source_id': 'ACTUAL', 'source_kind': 'approval_attachment',
         'actual_packing_source': True, 'actual_packing_match_status': 'matched'},
        {'source_id': 'FLOW', 'source_kind': 'approval_attachment',
         'source_field': '装箱单附件（Excel）'},
    ])
    proposals = [{
        'proposal_id': 'ACTUAL', 'proposal_type': 'item_update', 'target_item_name': 'I1',
        'default_selected': True, 'source_refs': [{'source_id': 'ACTUAL'}],
        'payload': {'fields': {'gross_weight_kg': 9}},
    }]

    review = catalog(items, proposals, sources)

    assert review['source_groups'][0]['source_id'] == 'ACTUAL'
    assert review['source_groups'][0]['priority_reason'] == '实际运费／装箱变更已匹配当前单据'
    assert review['source_groups'][0]['actual_packing_match_status'] == 'matched'


def test_replace_selected_rows_removes_unselected_and_clears_missing():
    rows=[item(gross_weight_kg=9),item('I2','B1')]
    c=catalog(rows,[reconcile([source()])])
    p=service.project(rows,c,[c['rows'][0]['row_id']],[],'replace_all')
    assert len(p['rows'])==1 and p['rows'][0]['gross_weight_kg'] is None
    assert p['removed_count']==1


def test_kept_current_rows_preserve_values_and_are_not_default_selected():
    rows=[item(gross_weight_kg=9)]
    c=catalog(rows,[]);r=c['rows'][0]
    assert r['origin']=='current' and not r['default_selected']
    assert service.project(rows,c,[r['row_id']],[],'replace_all')['rows'][0]['gross_weight_kg']==9


def test_ambiguous_sku_fill_is_blocked_but_replace_has_no_inherited_price():
    rows=[item(unit_price='10'),item('I2',unit_price='20')]
    c=catalog(rows,[reconcile([source()])]);r=c['rows'][0]
    assert not r['can_fill'] and r['can_replace']
    with pytest.raises(ValueError):service.project(rows,c,[r['row_id']],[],'fill_missing')
    assert service.project(rows,c,[r['row_id']],[],'replace_all')['rows'][0].get('unit_price') is None


def test_split_child_selection_does_not_adopt_other_children():
    rows=[item()]
    proposal={'proposal_id':'split','proposal_type':'material_replace','target_item_name':'I1','default_selected':False,
              'payload':{'replacement_rows':[{'product_name':'left','quantity':'1','purchase_uom':'件'},{'product_name':'right','quantity':'2','purchase_uom':'件'}]}}
    c=catalog(rows,[proposal]);selected=next(r for r in c['rows'] if r['values'].get('product_name')=='right')
    p=service.project(rows,c,[selected['row_id']],[],'replace_all')
    assert [r['product_name'] for r in p['rows']]==['right']
    assert p['rows'][0].get('material_code') in ('',None)


def test_composite_sku_is_pending_instead_of_made_up_catalog_code():
    c=catalog([], [reconcile([source('A1/B1')])])
    assert not c['rows'][0]['values']['material_code']
    assert 'SKU' in service.project([],c,[c['rows'][0]['row_id']],[],'replace_all')['missing_fields']


def test_empty_replacement_and_unknown_selection_rejected():
    c=catalog([item()],[])
    with pytest.raises(ValueError):service.project([item()],c,[],[],'replace_all')
    with pytest.raises(ValueError):service.project([item()],c,['forged'],[],'fill_missing')


def test_blocked_fees_never_join_material_only_plan():
    fee={'proposal_id':'F','proposal_type':'fee_update','default_selected':True,'payload':{'logical_fee_key':'international_express_fee','amount':'100'}}
    c=service.catalog([item(gross_weight_kg=None)], [reconcile([source('A1',gross_weight_kg=2)]),fee],[],{'freight':{'selected':True,'available':True}},run_id='R')
    r=next(r for r in c['rows'] if r['origin']=='source')
    assert service.project([item()],c,[r['row_id']],[],'fill_missing')['fees']==[]
    with pytest.raises(ValueError):service.project([item()],c,[r['row_id']],['F'],'fill_missing')


def test_identical_duplicate_source_rows_keep_separate_stable_ids():
    c=catalog([], [reconcile([source(),source()])])
    assert len({r['row_id'] for r in c['rows']})==2


def test_mutually_exclusive_fee_quotes_cannot_both_be_adopted():
    fees=[{'proposal_id':f'F{i}','proposal_type':'fee_update','payload':{'logical_fee_key':'international_express_fee','amount':amount,'currency':'RMB'}} for i,amount in enumerate(['100','200'])]
    c=service.catalog([],fees,[],{},run_id='R')
    with pytest.raises(ValueError,match='只选择一份'):service.project([],c,[],['F0','F1'],'fill_missing')


def test_different_fee_keys_covering_same_scope_cannot_both_be_adopted():
    fees = [
        {'proposal_id': 'AIR', 'proposal_type': 'fee_update',
         'payload': {'logical_fee_key': 'international_air_freight', 'amount': '100', 'currency': 'RMB'}},
        {'proposal_id': 'PORT', 'proposal_type': 'fee_update',
         'payload': {'logical_fee_key': 'port_and_forwarder_charges', 'amount': '20', 'currency': 'RMB'}},
    ]
    review = service.catalog([], fees, [], {}, run_id='R')

    with pytest.raises(ValueError, match='只选择一份'):
        service.project([], review, [], ['AIR', 'PORT'], 'fill_missing')
