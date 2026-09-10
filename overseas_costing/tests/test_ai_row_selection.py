import json
import pytest
from overseas_costing.services import material_ai_row_selection as service


def item(name='I1', code='A1', **fields):
    return {'name':name,'material_code':code,'product_name':code,'quantity':'1','actual_shipped_qty':'1','unit':'件','shipped_uom':'件',**fields}


def reconcile(rows):
    return {'proposal_id':'P','proposal_type':'logistics_reconcile','default_selected':True,
            'source_refs':[{'source_id':'L','field':'goods'}], 'payload':{'rows':rows}}


def catalog(items, proposals):
    return service.catalog(items,proposals,[],{},run_id='R')


def source(code='A1', **fields):
    return item('draft-'+code,code,_review_origin='source',**fields)


def test_fill_missing_preserves_real_zero_and_existing_quantity():
    rows=[item(gross_weight_kg=0,volume_m3=None)]
    c=catalog(rows,[reconcile([source(actual_shipped_qty='4',gross_weight_kg='7',volume_m3='2')])])
    selected=next(r for r in c['rows'] if r['origin']=='source')
    p=service.project(rows,c,[selected['row_id']],[],'fill_missing')
    assert p['rows'][0]['actual_shipped_qty']=='1'
    assert p['rows'][0]['gross_weight_kg']==0
    assert p['rows'][0]['volume_m3']=='2'


def test_explicit_missing_zero_is_fillable():
    rows=[item(gross_weight_kg=0,extra_json=json.dumps({'settlement_packing_missing':['gross_weight_kg']}))]
    c=catalog(rows,[reconcile([source(gross_weight_kg='7')])])
    p=service.project(rows,c,[c['rows'][0]['row_id']],[],'fill_missing')
    assert p['rows'][0]['gross_weight_kg']=='7'


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
    c=service.catalog([item()], [reconcile([source('B1')]),fee],[],{'freight':{'selected':True,'available':True}},run_id='R')
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
