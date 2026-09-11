import json
from overseas_costing.services.material_input_service import present_material_row
from overseas_costing.services.shipment_cost_service import shipment_value


def shipment(**changes):
    return {'name':'I','stable_line_key':'I','material_code':'A','quantity':100,'goods_value':1000,
            'unit_price':10,'purchase_currency':'RMB','purchase_uom':'件','unit_price_uom':'件','unit':'件',
            'source_doc_no':'GOODS-PURCHASE','actual_shipped_qty':4,'actual_shipped_qty_mode':'EXPLICIT_SOURCE',
            'shipped_uom':'件', **changes}


def cargo(**changes):
    return {'binding_id':'B','source_snapshot':'S','line_key':'L','quantity':'6','unit':'件',**changes}


def test_effective_final_quantity_preserves_purchase_and_packing_values():
    item=shipment(extra_json=json.dumps({'settlement_cargo':cargo()}))
    row=present_material_row(item)
    assert row['quantity']==100 and row['goods_value']==1000 and row['actual_shipped_qty']==4
    assert row['effective_shipping_quantity']=='6'
    assert row['effective_shipping']['mode']=='SETTLEMENT_FINAL'
    assert row['settlement_cargo']['source_snapshot']=='S'


def test_invalid_final_quantity_never_falls_back_to_purchase_or_packing():
    item=shipment(extra_json=json.dumps({'settlement_cargo':cargo(quantity=None)}))
    row=present_material_row(item)
    assert row['effective_shipping_quantity']=='' and row['effective_shipping']['blocking']


def test_final_quantity_cannot_reuse_old_packing_valuation_or_full_purchase_total():
    item=shipment(extra_json=json.dumps({'settlement_cargo':cargo(), 'shipment_valuation':{
        'quantity':'4','uom':'件','amount_rmb':'40','currency':'RMB','method':'purchase_unit_price'}}))
    value=shipment_value(present_material_row(item))
    assert value['amount_rmb'] is None and value['error']


def test_final_shipment_valuation_uses_independent_price_with_explicit_evidence():
    from overseas_costing.services.logistics_settlement.valuation import value_final_cargo
    item=shipment()
    valuation=value_final_cargo(item,cargo(),{})
    assert valuation['amount_rmb']=='60.000000' and valuation['quantity']=='6'
    assert valuation['input_evidence']['purchase_source']=='GOODS-PURCHASE'
    item['extra_json']=json.dumps({'settlement_cargo':cargo(),'settlement_valuation':valuation})
    assert shipment_value(present_material_row(item))['amount_rmb']=='60.000000'
    assert item['quantity']==100 and item['goods_value']==1000 and item['actual_shipped_qty']==4


def test_final_valuation_blocks_missing_currency_or_incompatible_units():
    from overseas_costing.services.logistics_settlement.valuation import value_final_cargo
    assert value_final_cargo(shipment(purchase_currency=''),cargo(),{})['error']
    assert value_final_cargo(shipment(unit_price_uom='KG'),cargo(),{})['error']


def test_final_valuation_accepts_settlement_currency_aliases():
    from overseas_costing.services.logistics_settlement.valuation import value_final_cargo

    for alias in ('人民币RMB', '人民币', 'CNY', 'RMB'):
        valuation = value_final_cargo(shipment(purchase_currency=alias), cargo(), {})
        assert valuation['error'] == ''
        assert valuation['amount_rmb'] == '60.000000'
        assert valuation['input_evidence']['original_currency'] == 'RMB'

from overseas_costing.tests.test_settlement_writer import setup


def test_application_adopts_final_cargo_overlay_without_rewriting_purchase_or_packing(setup):
    from overseas_costing.tests.test_logistics_settlement import source, ingest, table_row
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    s,l,b,v,i,r,binding=setup
    l.put('item',i['name'],shipment(name=i['name']))
    expense=source('E',amount='100')
    expense['updated_at']='2026-09-09T05:00:00+00:00'
    expense['raw_payload']['formComponentValues'].append({'name':'货物明细','componentType':'TableField','value':[table_row('a',quantity='6')]})
    ingest(s,expense)
    applied=apply_binding(s,l,binding['id'],'u')
    row=l.get('item',i['name'])
    assert row['quantity']==100 and row['goods_value']==1000 and row['actual_shipped_qty']==4
    presented=present_material_row(row)
    assert presented['effective_shipping_quantity']=='6' and presented['shipment_value_rmb']=='60.000000'
    assert applied['application_status']=='applied_pending' # packing4 vs settlement6 requires review


def test_frozen_adjustment_keeps_independent_fee_evidence_and_sku_components(setup):
    from copy import deepcopy
    from overseas_costing.services.logistics_settlement.writer import mutable_version
    s,l,b,v,i,r,binding=setup
    tax=l.create('rule',{'batch':b['name'],'version':v['name'],'rule_code':'import_tax','logical_fee_key':'import_tax','amount':100,'currency':'RMB','is_enabled':1})
    evidence=l.create('evidence',{'batch':b['name'],'version':v['name'],'fee_rule':tax['name'],'attachment':'ORIGINAL-FILE','validation_status':'VALID'})
    component=l.create('component',{'batch':b['name'],'version':v['name'],'fee_rule':tax['name'],'item':i['name'],'evidence':evidence['name'],'amount_rmb':'80','is_active':1,'status':'CONFIRMED'})
    old=deepcopy(component)
    l.put('version',v['name'],{'status':'Confirmed'})
    draft=mutable_version(l,l.get('batch',b['name']))
    copied=l.rows('component',version=draft['name'])
    assert len(copied)==1 and copied[0]['amount_rmb']=='80'
    assert copied[0]['item']!=i['name'] and copied[0]['fee_rule']!=tax['name'] and copied[0]['evidence']!=evidence['name']
    assert l.get('evidence',copied[0]['evidence'])['attachment']=='ORIGINAL-FILE'
    assert l.get('component',component['name'])==old


def test_rollback_removes_only_final_quantity_overlay_and_preserves_raw_evidence(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    from overseas_costing.services.logistics_settlement.rollback import restore_application
    s,l,b,v,i,r,binding=setup
    l.put('item',i['name'],shipment(name=i['name']))
    applied=apply_binding(s,l,binding['id'],'u')
    assert present_material_row(l.get('item',i['name']))['effective_shipping']['mode']=='SETTLEMENT_FINAL'
    restore_application(s,l,applied['last_application'],applied['revision'],'回退测试','u')
    item=l.get('item',i['name'])
    assert 'settlement_cargo' not in json.loads(item['extra_json'])
    assert item['quantity']==100 and item['actual_shipped_qty']==4 and item['goods_value']==1000


def test_public_metadata_edit_cannot_create_or_remove_final_quantity_overlay():
    import pytest
    from overseas_costing.services.calculate_service import assert_server_metadata_unchanged
    with pytest.raises(ValueError,match='服务器来源'):
        assert_server_metadata_unchanged({}, {'settlement_cargo':cargo()})
    with pytest.raises(ValueError,match='服务器来源'):
        assert_server_metadata_unchanged({'settlement_cargo':cargo()}, {})

    manual = {'amount_rmb': '10', 'currency': 'RMB', 'confirmed': True, 'manual': True}
    with pytest.raises(ValueError, match='服务器来源'):
        assert_server_metadata_unchanged({}, {'manual_shipment_valuation': manual})
    with pytest.raises(ValueError, match='服务器来源'):
        assert_server_metadata_unchanged({'manual_shipment_valuation': manual}, {})


def test_reconciliation_cannot_copy_one_final_cargo_identity_to_two_rows():
    from copy import deepcopy
    import pytest
    from overseas_costing.services.logistics_autofill_service import apply_reconciliation
    item=shipment(extra_json=json.dumps({'settlement_cargo':cargo()}))
    original={**item,'_existing_name':'I'}
    duplicate={**deepcopy(item),'name':'NEW','stable_line_key':'NEW','_existing_name':''}
    proposal={'proposal_id':'P','payload':{'original_item_names':['I'],'rows':[original,duplicate]}}
    with pytest.raises(ValueError,match='结算'):
        apply_reconciliation(None,proposal,batch='B',version='V',current=[item],run_id='R')


def test_final_project_summary_keeps_six_decimal_pool():
    from overseas_costing.services.shipment_cost_service import project_summaries
    rows=[{'name':'I','allocated_fees_rmb':'0.000001','total_cost_rmb':'10.000001'}]
    assert project_summaries(rows)[0]['allocated_fees_rmb']=='0.00'
    assert project_summaries(rows,precision=6)[0]['allocated_fees_rmb']=='0.000001'
    assert project_summaries(rows,precision=6)[0]['total_cost_rmb']=='10.000001'


def test_manual_shipment_valuation_has_priority_and_zero_is_explicit():
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    item = shipment(actual_shipped_qty=4, shipped_uom='件')
    automatic = {
        'status': 'automatic', 'amount_rmb': '40', 'currency': 'RMB', 'quantity': '4',
        'uom': '件', 'method': 'purchase_unit_price', 'input_fingerprint': 'automatic-fingerprint',
        'error': '',
    }
    manual = build_manual_shipment_valuation(item, 0, actor='finance@example.com', reason='财务确认', confirmed_at='2026-09-11T10:00:00')
    item['extra_json'] = json.dumps({'shipment_valuation': automatic, 'manual_shipment_valuation': manual})

    value = shipment_value(item)

    assert value['status'] == 'manual'
    assert value['amount_rmb'] == '0'
    assert value['currency'] == 'RMB'
    assert value['quantity'] == '4'
    assert value['uom'] == '件'
    assert value['confirmed'] is True and value['manual'] is True
    assert value['actor'] == 'finance@example.com'
    assert value['confirmed_at'] == '2026-09-11T10:00:00'
    assert value['reason'] == '财务确认'


def test_manual_shipment_valuation_becomes_stale_without_deleting_original_value():
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    item = shipment(actual_shipped_qty=4, shipped_uom='件')
    manual = build_manual_shipment_valuation(item, '25', actor='u', reason='checked', confirmed_at='now')
    item['extra_json'] = json.dumps({'manual_shipment_valuation': manual})
    item['actual_shipped_qty'] = 5

    value = shipment_value(item)

    assert value['status'] == 'stale'
    assert value['amount_rmb'] is None
    assert value['error'] == 'MANUAL_SHIPMENT_VALUATION_STALE'
    assert value['prior_amount_rmb'] == '25'
    assert json.loads(item['extra_json'])['manual_shipment_valuation']['amount_rmb'] == '25'


def test_manual_fingerprint_uses_effective_shipping_before_raw_actual_quantity():
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    row = shipment(actual_shipped_qty=4, shipped_uom='件')
    row['effective_shipping'] = {'quantity': '6', 'uom': '箱', 'mode': 'EXPLICIT_SOURCE'}

    manual = build_manual_shipment_valuation(row, 25, actor='u', confirmed_at='now')

    assert manual['quantity'] == '6'
    assert manual['uom'] == '箱'


def test_settlement_cargo_change_stales_manual_value_even_when_raw_quantity_is_unchanged():
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    item = shipment(actual_shipped_qty=4, shipped_uom='件', extra_json=json.dumps({'settlement_cargo': cargo(quantity='6')}))
    manual = build_manual_shipment_valuation(item, 25, actor='u', confirmed_at='now')
    metadata = json.loads(item['extra_json'])
    metadata['manual_shipment_valuation'] = manual
    item['extra_json'] = json.dumps(metadata)
    assert shipment_value(item)['status'] == 'manual'
    metadata['settlement_cargo']['quantity'] = '7'
    item['extra_json'] = json.dumps(metadata)

    value = shipment_value(item)

    assert manual['quantity'] == '6'
    assert value['status'] == 'stale'
    assert value['amount_rmb'] is None
    assert value['prior_amount_rmb'] == '25'


def test_shipment_value_normalizes_legacy_metadata_statuses_and_candidates():
    item = shipment(extra_json=json.dumps({'shipment_valuation': {
        'amount_rmb': None, 'currency': 'RMB', 'quantity': '4', 'uom': '件',
        'method': 'purchase_unit_price', 'status': 'conflict',
        'error': 'SETTLEMENT_SHIPMENT_VALUE_CONFLICT', 'prior_amount_rmb': '40',
        'calculated_amount_rmb': '60',
    }}))

    value = shipment_value(item)

    assert value['status'] == 'conflict'
    assert value['amount_rmb'] is None
    assert value['prior_amount_rmb'] == '40'
    assert value['calculated_amount_rmb'] == '60'
    legacy = shipment_value(shipment(extra_json='{}'))
    assert legacy['status'] == 'automatic'
    assert legacy['amount_rmb'] == 1000


def test_existing_shipment_valuation_accepts_settlement_currency_aliases():
    for alias in ('人民币RMB', '人民币', 'CNY', 'RMB'):
        item = shipment(extra_json=json.dumps({'shipment_valuation': {
            'amount_rmb': '40', 'currency': alias, 'quantity': '4', 'uom': '件',
            'method': 'purchase_unit_price', 'error': '',
        }}))
        value = shipment_value(item)
        assert value['status'] == 'automatic'
        assert value['amount_rmb'] == '40'
        assert value['error'] == ''


def test_settlement_automatic_value_reports_stale_status_after_evidence_changes():
    from overseas_costing.services.logistics_settlement.valuation import value_final_cargo

    item = shipment()
    valuation = value_final_cargo(item, cargo(), {})
    item['extra_json'] = json.dumps({'settlement_cargo': cargo(), 'settlement_valuation': valuation})
    item['unit_price'] = 11

    value = shipment_value(item)

    assert value['status'] == 'stale'
    assert value['amount_rmb'] is None
    assert value['error'] == 'SETTLEMENT_SHIPMENT_VALUE_STALE'


def test_settlement_conflict_keeps_error_and_candidates_while_inputs_are_current():
    from overseas_costing.services.logistics_settlement.valuation import reconcile_replacement_value

    item = shipment(goods_value=40)
    valuation = reconcile_replacement_value(item, cargo(), {}, item)
    item['extra_json'] = json.dumps({'settlement_cargo': cargo(), 'settlement_valuation': valuation})

    value = shipment_value(item)

    assert value['status'] == 'conflict'
    assert value['error'] == 'SETTLEMENT_SHIPMENT_VALUE_CONFLICT'
    assert value['amount_rmb'] is None
    assert value['prior_amount_rmb'] == '40'
    assert value['calculated_amount_rmb'] == '60.000000'


def test_adjustment_remaps_related_evidence_within_the_new_version(setup):
    from overseas_costing.services.logistics_settlement.writer import mutable_version
    s,l,b,v,i,r,binding=setup
    original=l.create('evidence',{'batch':b['name'],'version':v['name'],'fee_rule':r['name'],'evidence_role':'PAYMENT'})
    refund=l.create('evidence',{'batch':b['name'],'version':v['name'],'fee_rule':r['name'],'evidence_role':'REFUND','related_evidence':original['name']})
    l.put('version',v['name'],{'status':'Confirmed'})
    draft=mutable_version(l,l.get('batch',b['name']))
    copied={x['evidence_role']:x for x in l.rows('evidence',version=draft['name'])}
    assert copied['REFUND']['related_evidence']==copied['PAYMENT']['name']
    assert l.get('evidence',refund['name'])['related_evidence']==original['name']


def test_replay_does_not_refresh_valuation_in_frozen_batch(setup):
    from copy import deepcopy
    from overseas_costing.services.logistics_settlement.writer import apply_binding,refresh_application_state
    s,l,b,v,i,r,binding=setup
    applied=apply_binding(s,l,binding['id'],'u')
    l.put('batch',b['name'],{'confirm_status':'Confirmed'})
    l.put('item',i['name'],{'unit_price':99})
    before=deepcopy(l.get('item',i['name']))
    refresh_application_state(s,l,applied,s.get('source',binding['expense_id']))
    assert l.get('item',i['name'])==before


def test_settled_placeholder_cannot_be_replaced_by_material_ai():
    from overseas_costing.services.material_ai_fill_service import _is_unverified_placeholder_item
    item=shipment(source_type='AI_PLACEHOLDER',extra_json=json.dumps({'settlement_cargo':cargo()}))
    assert not _is_unverified_placeholder_item(item)


def test_public_delete_cannot_remove_final_source_row(monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import calculate_service, edit_session_service
    row=shipment(extra_json=json.dumps({'settlement_cargo':cargo()}),batch='B',version='V')
    monkeypatch.setattr(calculate_service,'_frappe',SimpleNamespace(get_doc=lambda *a:SimpleNamespace(**row)))
    monkeypatch.setattr(edit_session_service,'assert_batch_write',lambda *a,**kw:None)
    result=calculate_service.delete_item('I')
    assert not result['ok'] and '结算' in result['message']


def test_public_identity_edit_cannot_replace_final_source_identity(monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import calculate_service
    row=shipment(extra_json=json.dumps({'settlement_cargo':cargo()}),batch='B',version='V')
    monkeypatch.setattr(calculate_service,'_frappe',SimpleNamespace(get_doc=lambda *a:SimpleNamespace(**row)))
    result=calculate_service.update_item_field('I','material_code','OTHER',remark='correction',_skip_edit_check=True)
    assert not result['ok'] and '结算' in result['message']


def change_goods(s, quantity, code='A', hour=1):
    from overseas_costing.tests.test_logistics_settlement import source,ingest,table_row
    expense=source('E',amount='100')
    expense['updated_at']=f'2026-09-09T{hour:02d}:00:00+00:00'
    expense['raw_payload']['formComponentValues'].append({'name':'货物明细','componentType':'TableField','value':[table_row(code.lower(),code=code,quantity=str(quantity))]})
    return ingest(s,expense)


def test_rebinding_retained_source_created_row_removes_old_final_overlay(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding,reverse_binding
    s,l,b,v,i,r,binding=setup
    change_goods(s,6,code='B')
    applied=apply_binding(s,l,binding['id'],'u')
    created=l.rows('item')[0]
    l.put('item',created['name'],{'actual_shipped_qty':2,'actual_shipped_qty_mode':'EXPLICIT_SOURCE','shipped_uom':'件','total_cost_rmb':99})
    reverse_binding(s,l,applied,{},'u')
    retained=l.get('item',created['name'])
    assert retained['actual_shipped_qty']==2 and retained['total_cost_rmb']==0
    assert 'settlement_cargo' not in json.loads(retained['extra_json'])
    assert present_material_row(retained)['effective_shipping']['mode']!='SETTLEMENT_FINAL'


def test_rollback_deleted_row_restores_selected_beforeimage_overlay_with_latest_packing(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    from overseas_costing.services.logistics_settlement.rollback import restore_application
    s,l,b,v,i,r,binding=setup
    apply_binding(s,l,binding['id'],'u') # A4
    change_goods(s,6,hour=1)
    second=apply_binding(s,l,binding['id'],'u') # A6, before A4
    l.put('item',i['name'],{'actual_shipped_qty':9,'gross_weight_kg':90})
    change_goods(s,8,code='B',hour=2)
    latest=apply_binding(s,l,binding['id'],'u') # A retired
    restore_application(s,l,second['last_application'],latest['revision'],'选择应用前版本','u')
    restored=next(x for x in l.rows('item') if x['material_code']=='A')
    assert json.loads(restored['extra_json'])['settlement_cargo']['quantity']=='4'
    assert restored['actual_shipped_qty']==9 and restored['gross_weight_kg']==90


from overseas_costing.tests.test_source_metadata_security import controllers


def test_generic_item_delete_cannot_remove_final_source(controllers):
    import pytest
    item_class,_=controllers
    row=shipment(batch='B',version='V',extra_json=json.dumps({'settlement_cargo':cargo()}))
    doc=item_class(row,row)
    with pytest.raises(ValueError,match='结算'):
        doc.on_trash()


def test_generic_item_save_cannot_change_final_identity(controllers):
    import pytest
    item_class,_=controllers
    row=shipment(batch='B',version='V',extra_json=json.dumps({'settlement_cargo':cargo()}))
    doc=item_class({**row,'material_code':'OTHER'},row)
    with pytest.raises(ValueError,match='结算'):
        doc.save()


def test_draft_lease_cannot_edit_old_confirmed_item(monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import calculate_service
    row=shipment(name='OLD',batch='B',version='OLD-V',gross_weight_kg=4)
    item=SimpleNamespace(**row)
    fake=SimpleNamespace(get_doc=lambda *args:item, db=SimpleNamespace(sql=lambda *a,**k:[{'current_version':'NEW-V','version_status':'Confirmed','confirm_status':'Pending','writeback_status':'Not Started'}]))
    monkeypatch.setattr(calculate_service,'_frappe',fake)
    result=calculate_service.update_item_field('OLD','gross_weight_kg','99',version_name='NEW-V',_skip_edit_check=True)
    assert not result['ok'] and item.gross_weight_kg==4


def test_adjustment_preserves_legacy_stable_row_key_and_direct_fee_scope(setup):
    from overseas_costing.services.logistics_settlement.writer import mutable_version
    from overseas_costing.services.fee_allocation_service import resolve_eligible_items
    s,l,b,v,i,r,binding=setup
    key='legacy:'+i['name']
    fee=l.create('rule',{'batch':b['name'],'version':v['name'],'logical_fee_key':'other','scope_type':'DIRECT_ITEM','scope_value_json':json.dumps([key])})
    l.put('version',v['name'],{'status':'Confirmed'})
    draft=mutable_version(l,l.get('batch',b['name']))
    row=present_material_row(l.rows('item',version=draft['name'])[0])
    copied=next(x for x in l.rows('rule',version=draft['name']) if x.get('logical_fee_key')=='other')
    assert row['stable_line_key']==key
    assert len(resolve_eligible_items(copied,[row]))==1


def test_rebinding_preserves_explicit_zero_packing_evidence(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding,reverse_binding
    s,l,b,v,i,r,binding=setup
    change_goods(s,6,code='B')
    applied=apply_binding(s,l,binding['id'],'u')
    created=l.rows('item')[0]
    l.put('item',created['name'],{'actual_shipped_qty':0,'actual_shipped_qty_mode':'EXPLICIT_SOURCE','shipped_uom':'件'})
    reverse_binding(s,l,applied,{},'u')
    retained=l.get('item',created['name'])
    assert retained is not None and retained['actual_shipped_qty']==0
    assert 'settlement_cargo' not in json.loads(retained['extra_json'])


def test_changed_final_material_cannot_reuse_old_material_purchase_price():
    from overseas_costing.services.logistics_settlement.valuation import value_final_cargo
    changed=cargo(material_code='B')
    assert value_final_cargo(shipment(),changed,{})['amount_rmb'] is None
    persisted=shipment(material_code='B',extra_json=json.dumps({'settlement_original_values':{'material_code':'A'}}))
    assert value_final_cargo(persisted,changed,{})['amount_rmb'] is None
