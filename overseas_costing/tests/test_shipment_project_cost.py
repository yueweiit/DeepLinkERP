from copy import deepcopy
from decimal import Decimal
import json
import pytest

from overseas_costing.services import cost_preview_service, fee_allocation_service, fee_service


def shipment_items():
    codes = ['FL000429','FL000429','FL000427','FL000427','FL000428','FL000430','FL003377','CW000191']
    quantities = [96000,4000,4000,96000,100000,100000,22000,2400]
    values = [14496,604,604,14496,15100,15100,2860,10560]
    weights = [388,4.85,4.85,32,150,89,77,130]
    projects = ['超队1.0项目'] * 6 + ['亮甲2.0项目','TK宠物用品项目']
    return [dict(name=f'I{i}', stable_line_key=f'K{i}', row_no=i+1, material_code=code,
                 quantity=200000 if i == 6 else (0 if i == 7 else qty),
                 actual_shipped_qty=qty, actual_shipped_qty_mode='EXPLICIT_SOURCE', shipped_uom='个', unit='个',
                 goods_value=26000 if i == 6 else (0 if i == 7 else value),
                 gross_weight_kg=weight, volume_m3=1, project_collection=project,
                 extra_json=json.dumps({'shipment_valuation': {'amount_rmb':str(value), 'currency':'RMB',
                     'quantity':str(qty), 'uom':'个', 'method':'SYSTEM_EXCEL', 'source_refs':[{'source_id':'X'}]}}))
            for i,(code,qty,value,weight,project) in enumerate(zip(codes,quantities,values,weights,projects))]


def project_fee():
    return dict(name='F', logical_fee_key='international_sea_freight', expense_category='国际海运费',
                amount='7756.20', currency='RMB', amount_status='ESTIMATED', scope_type='ALL_ITEMS',
                allocation_basis='gross_weight', scope_value_json=json.dumps({'item_keys':[],
                'project_allocation':{'method':'PROJECT_GROSS_WEIGHT', 'projects':['超队1.0项目','亮甲2.0项目','TK宠物用品项目'],
                'source_refs':[{'source_id':'approval:1'}]}}))


def test_project_freight_two_levels_and_shipment_values_conserve():
    items, fee = shipment_items(), project_fee()
    original = deepcopy(items)
    result = cost_preview_service.preview_comprehensive_cost_data(items, [fee], {})
    assert result['summary']['purchase_goods_value_rmb'] == '73820.00'
    assert result['summary']['total_cost_rmb'] == '81576.20'
    assert {r['reason_code'] for r in result['incomplete_reasons']} == {'ESTIMATED_AMOUNT'}
    projects = {r['project_collection']:r for r in result['project_summary']}
    assert {p:r['allocated_fees_rmb'] for p,r in projects.items()} == {
        '超队1.0项目':'5922.77','亮甲2.0项目':'682.00','TK宠物用品项目':'1151.43'}
    assert sum(Decimal(r['allocated_fees_rmb']) for r in result['items']) == Decimal('7756.20')
    assert items == original


def test_explicit_project_policy_does_not_fallback_on_missing_weight_or_project():
    for field,value in [('gross_weight_kg',None),('project_collection','')]:
        items=shipment_items();items[-1][field]=value
        result=fee_allocation_service.allocate_fee(project_fee(),items)
        assert result['status'] == 'BLOCKED'
        assert result['code'].startswith('PROJECT_')


def test_project_policy_preserved_by_normalization_and_in_revision():
    fee=project_fee()
    saved=fee_service.normalize_fee_payload(fee, trusted_project_policy=True)
    assert json.loads(saved['scope_value_json'])['project_allocation']['method'] == 'PROJECT_GROSS_WEIGHT'
    old={**fee,'scope_value_json':'[]'}
    result=fee_service.merge_logical_fee([old],saved,revision='policy-new')
    assert result['fee']['scope_revision'] == 'policy-new'


def test_stale_shipment_quantity_does_not_use_old_value_or_full_purchase():
    items=shipment_items();items[-1]['actual_shipped_qty']=2401
    result=cost_preview_service.preview_comprehensive_cost_data(items,[project_fee()],{})
    assert not result['summary']['is_complete']
    assert any(r['reason_code']=='SHIPMENT_VALUATION_STALE' for r in result['incomplete_reasons'])


def test_legacy_goods_value_behavior_unchanged():
    items=shipment_items()
    for r in items:r.pop('extra_json')
    result=cost_preview_service.preview_comprehensive_cost_data(items,[],{})
    assert result['summary']['purchase_goods_value_rmb']=='86400.00'


def test_untrusted_project_policy_rejected():
    with pytest.raises(ValueError, match='可信资料'):
        fee_service.normalize_fee_payload(project_fee())


def test_normal_amount_edit_retains_server_policy():
    fee=project_fee()
    payload=fee_service.normalize_fee_payload({**fee,'scope_value_json':'[]','amount':'8000'})
    result=fee_service.merge_logical_fee([fee],payload)
    assert json.loads(result['fee']['scope_value_json'])['project_allocation']


def test_source_quote_issues_weight_policy_not_volume_default():
    from overseas_costing.services.material_ai_fill_service import build_approval_fee_proposals
    source={'source_id':'A','form_fields':{'物流报价': '大墨仓报价：3100元/立方，费用：7756.20元\n重量 重量占比\n超队1.0项目 668.7kg 76.36% ¥5922.77\n亮甲2.0项目 77kg 8.79% ¥520.79\nTK宠物用品项目130kg 14.85% ¥77.31'},
        'approval_decisions':[{'operation_result':'AGREE','remark':'走大墨仓'}]}
    proposal=build_approval_fee_proposals(source,transport_mode='SEA')[0]
    assert proposal['_project_policy']['projects']==['超队1.0项目','亮甲2.0项目','TK宠物用品项目']
    assert proposal['payload']['allocation_basis']=='gross_weight'


def test_both_grid_and_cost_read_persisted_shipment_metadata():
    from overseas_costing.services.material_input_service import GRID_FIELDS
    assert 'extra_json' in GRID_FIELDS
    assert 'extra_json' in cost_preview_service.COST_INPUT_FIELDS


def test_review_binding_serializes_excel_date_evidence():
    from datetime import datetime
    from overseas_costing.services.shipment_review_service import merge_shipment_fills
    p={'payload':{'rows':[{'name':'I','extra_json':'{}'}], 'unresolved':[]},'source_refs':[]}
    docs=[{'shipment_fills':[{'source_id':'X','sheet_name':'S','valuations':{'I':{'amount_rmb':'1',
        'quantity':'1','uom':'个','input_evidence':{'date':datetime(2026,9,5)}}}}]}]
    merge_shipment_fills(p,docs,{('X','S')})
    assert '2026-09-05' in p['payload']['rows'][0]['extra_json']


def test_goods_based_other_fee_uses_shipment_not_full_purchase_value():
    items=shipment_items()
    fee={'logical_fee_key':'customs_clearance_fee','amount':738.20,'currency':'RMB',
         'amount_status':'ACTUAL','scope_type':'ALL_ITEMS','allocation_basis':'goods_value'}
    result=cost_preview_service.preview_comprehensive_cost_data(items,[fee],{})
    assert result['items'][-1]['allocated_fees_rmb']=='105.60'
    assert result['items'][-2]['allocated_fees_rmb']=='28.60'


def test_pricing_unit_cost_uses_shipped_quantity_for_shipment_valuation():
    items=shipment_items();items[6].update(purchase_uom='个',unit_price_uom='个')
    result=cost_preview_service.preview_comprehensive_cost_data(items,[],{})
    assert result['items'][6]['purchase_pricing_unit_cost']['amount_rmb']=='0.130000'


@pytest.mark.parametrize('prior', [True, False])
def test_failed_or_excluded_source_never_retains_old_automatic_or_full_purchase_value(prior):
    from overseas_costing.services.shipment_review_service import merge_shipment_fills
    from overseas_costing.services.shipment_cost_service import shipment_value
    row=shipment_items()[6]
    if not prior: row['extra_json']='{}'
    draft={'payload':{'rows':[row], 'unresolved':[]},'source_refs':[]}
    docs=[{'shipment_fills':[{'source_id':'X','sheet_name':'S','attempted_item_names':[row['name']],
        'valuations':{},'warnings':['币种冲突']}]}]
    merge_shipment_fills(draft,docs,{('X','S')})
    assert shipment_value(row)['amount_rmb'] is None
    assert shipment_value(row)['error']=='SHIPMENT_VALUATION_SOURCE_UNAVAILABLE'
    assert '币种冲突' in str(draft['payload']['unresolved'])


def test_source_exclusion_invalidates_automatic_but_preserves_confirmed_manual():
    from overseas_costing.services.shipment_review_service import merge_shipment_fills
    from overseas_costing.services.shipment_cost_service import shipment_value
    rows=shipment_items()[-2:]
    metadata=json.loads(rows[-1]['extra_json'])
    metadata['shipment_valuation'].update(method='manual',manual=True,confirmed=True)
    rows[-1]['extra_json']=json.dumps(metadata)
    draft={'payload':{'rows':rows, 'unresolved':[]},'source_refs':[]}
    merge_shipment_fills(draft,[],set())
    assert shipment_value(rows[0])['amount_rmb'] is None
    assert shipment_value(rows[1])['amount_rmb']=='10560'


def test_produced_normalized_unit_valuation_is_immediately_consumable():
    from overseas_costing.tests.test_shipment_valuation import _item, _preview, _match, _build
    from overseas_costing.services.shipment_cost_service import shipment_value
    item=_item(uom='pcs',shipped_uom='pcs')
    fill=_build([item],_match(_preview([['FL001',10,'pcs',2,20,'P']]),[item]))
    item['extra_json']=json.dumps({'shipment_valuation':fill['valuations'][item['name']]})
    assert shipment_value(item)['error']==''
    assert Decimal(shipment_value(item)['amount_rmb'])==20


def test_goods_basis_requirements_accept_valid_shipment_value_without_purchase_value():
    from overseas_costing.services.material_input_service import analyze_material_requirements
    result=analyze_material_requirements(shipment_items(),[{'amount':100,'currency':'RMB',
        'amount_status':'ACTUAL','allocation_basis':'goods_value','scope_type':'ALL_ITEMS'}])
    assert not result['rows']['K7']['missing_fields']


def test_unselected_sheet_and_failed_dedicated_attachment_mark_value_unavailable():
    from overseas_costing.services.shipment_review_service import merge_shipment_fills
    from overseas_costing.services.shipment_cost_service import shipment_value
    for documents, required in [([], ['I6']), ([{'shipment_fills':[{'source_id':'X','sheet_name':'S',
        'attempted_item_names':['I6'], 'valuations':{}}]}], [])]:
        row=shipment_items()[6];row['extra_json']='{}'
        draft={'payload':{'rows':[row],'unresolved':[]},'source_refs':[]}
        merge_shipment_fills(draft,documents,set(),required_item_names=required)
        assert shipment_value(row)['amount_rmb'] is None


def test_discovered_sheet_id_binds_valuation_evidence():
    from overseas_costing.services.shipment_review_service import merge_shipment_fills
    row=shipment_items()[6];row['extra_json']='{}'
    draft={'payload':{'rows':[row],'unresolved':[]},'source_refs':[]}
    value={'amount_rmb':'2860','quantity':'22000','uom':'个','currency':'RMB',
        'source_refs':[{'source_id':'X','sheet':'S'}]}
    docs=[{'sheet_source_ids':{'S':'X:sheet:S'},'shipment_fills':[{'source_id':'X','sheet_name':'S',
        'valuations':{'I6':value}}]}]
    merge_shipment_fills(draft,docs,{('X:sheet:S','S')})
    assert json.loads(row['extra_json'])['shipment_valuation']['amount_rmb']=='2860'
    assert draft['source_refs'][0]['source_id']=='X:sheet:S'


def test_autofill_summary_uses_saved_fx_rates_and_reports_unresolved_project_rule():
    from overseas_costing.services.logistics_autofill_service import autofill_preview
    fee={**project_fee(),'amount':10,'currency':'USD'}
    result=autofill_preview(shipment_items(),[],[fee],fx_rates={'USD':'7','MXN':'.5'})
    assert result['cost_summary']['allocated_fees_rmb']=='70.00'
    rows=shipment_items();rows[0]['gross_weight_kg']=None
    result=autofill_preview(rows,[],[project_fee()])
    assert any('毛重' in r['message'] for r in result['unresolved'])


def test_confirming_later_fee_evidence_retains_only_server_project_policy(monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import fee_evidence_review_service as evidence
    saved=[]
    monkeypatch.setattr(evidence,'frappe',SimpleNamespace(db=SimpleNamespace(
        set_value=lambda *a,**kw: saved.append(a), get_value=lambda *a,**kw: 'E')))
    monkeypatch.setattr(evidence,'_now',lambda: '2026-09-09')
    monkeypatch.setattr(evidence,'_session_user',lambda: 'tester')
    fee={**project_fee(),'amount_status':'ACTUAL'}
    monkeypatch.setattr(fee_service,'_query_rules',lambda *a: [deepcopy(fee)])
    repo=evidence.FrappeFeeEvidenceReviewRepository()
    monkeypatch.setattr(repo,'materialize_fee_rule',lambda *a: deepcopy(fee))
    result=repo.save_fee_split(context={'batch':'B','version':'V','transport_mode':'SEA'},
        fee_row={'logical_fee_key':'international_sea_freight','amount':7756.2,'currency':'RMB','amount_status':'ACTUAL',
            'scope_value_json':{'project_allocation':{'method':'FORGED'}}}, evidence_values={},
        attachment={'name':'A','file_name':'invoice.pdf'},draft={},run_id='RUN')
    assert saved
    assert json.loads(saved[0][2]['scope_value_json'])['project_allocation']['method']=='PROJECT_GROSS_WEIGHT'


def test_autofill_never_silently_deduplicates_existing_freight():
    from overseas_costing.services.logistics_autofill_service import autofill_preview
    result=autofill_preview(shipment_items(),[],[project_fee(),{**project_fee(),'name':'F2','amount':500}])
    assert result['cost_summary']['allocated_fees_rmb']=='0.00'
    assert any(r.get('reason_code')=='DUPLICATE_LOGICAL_FEE' for r in result['unresolved'])


def test_explicit_project_rule_has_priority_over_invoice_sku_components():
    result=cost_preview_service.preview_comprehensive_cost_data(shipment_items(),[project_fee()],{},fee_components=[{
        'fee_rule':'F','logical_fee_key':'international_sea_freight','component_kind':'SKU_DIRECT',
        'stable_line_key':'K7','amount_rmb':'1000','status':'CONFIRMED','is_active':1}])
    assert [p['allocated_fees_rmb'] for p in result['project_summary']]==['5922.77','682.00','1151.43']
    fee=result['included_fees'][0]
    assert fee['project_allocations']=={p['project_collection']:p['allocated_fees_rmb'] for p in result['project_summary']}


def test_processing_revision_invalidates_predeployment_ready_draft(monkeypatch):
    from overseas_costing.services import material_ai_fill_service as service
    old=service._source_review_fingerprint('B','V',[],[],'')
    monkeypatch.setattr(service,'SOURCE_REVIEW_PROCESSING_VERSION','new-parser',raising=False)
    assert old != service._source_review_fingerprint('B','V',[],[],'')
