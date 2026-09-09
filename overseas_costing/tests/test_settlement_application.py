import pytest
from overseas_costing.services.logistics_settlement.application import plan_application
from overseas_costing.tests.test_logistics_settlement import source
from overseas_costing.services.logistics_settlement.model import parse_source


def expense(amount='0', text='海运 MXT500174'):
    return parse_source(source('E', amount=amount, text=text), logistics_codes={'logistics'})


def test_final_zero_replaces_only_freight_and_keeps_packing():
    items = [{'name': 'I', 'material_code': 'A', 'quantity': 2, 'gross_weight_kg': 3, 'volume_m3': 4}]
    plan = plan_application(expense(), items, [{'name': 'F', 'rule_code': 'oa_logistics_freight', 'amount': 200}, {'name': 'M', 'rule_code': 'mexico_misc_mxn', 'amount': 10}], binding_id='B')
    assert plan['ready']
    assert plan['disable_rules'] == ['F']
    assert plan['rules'][0]['amount'] == '0'
    assert plan['goods_updates'] == []
    assert items[0]['gross_weight_kg'] == 3


def test_unknown_ddp_scope_requires_resolution():
    assert not plan_application(expense('100', '双清 MXT500174'), [], [], binding_id='B')['ready']
    plan = plan_application(expense('100', '双清 MXT500174'), [], [], binding_id='B', coverage=['freight', 'customs', 'tax'])
    assert plan['ready']
    assert plan['rules'][0]['covered_scopes'] == 'freight,customs,tax'


def test_partial_goods_does_not_remove_existing_rows():
    parsed = expense()
    parsed['goods'] = [{'material_code': 'A', 'quantity': '2', 'unit': '件', 'line_key': 'a'}]
    parsed['goods_complete'] = False
    plan = plan_application(parsed, [{'name': 'B', 'material_code': 'B', 'quantity': 4}], [], binding_id='B')
    assert plan['remove_items'] == []
    assert plan['goods_updates'] == []
    assert plan['goods_pending']


def test_complete_goods_updates_identity_preserves_packing_and_invalidates_derived():
    parsed = expense()
    parsed['goods'] = [{'material_code': 'A', 'product_name': '鞋', 'spec_model': '', 'quantity': '4', 'unit': '件', 'line_key': 'a'}]
    parsed['goods_complete'] = True
    plan = plan_application(parsed, [{'name': 'I', 'material_code': 'A', 'product_name': '鞋', 'quantity': 2, 'unit': '件', 'gross_weight_kg': 3, 'goods_value': 20, 'unit_price': 10}], [], binding_id='B')
    assert plan['goods_updates'][0]['name'] == 'I'
    assert plan['goods_updates'][0]['values']['quantity'] == '4'
    assert 'gross_weight_kg' not in plan['goods_updates'][0]['values']
    assert plan['packing_review']


def test_customs_fee_line_requires_scope_review_before_any_estimate_is_replaced():
    from overseas_costing.tests.test_logistics_settlement import source
    from overseas_costing.services.logistics_settlement.model import parse_source
    row=source('E',amount='100')
    row['raw_payload']['formComponentValues'].append({'name':'费用明细','componentType':'TableField','value':[{'rowId':'r','rowValue':[{'name':'费用名称','value':'清关费'},{'name':'金额','value':'100'}]}]})
    parsed=parse_source(row,logistics_codes={'logistics'})
    plan=plan_application(parsed,[],[{'name':'old','rule_code':'customs_fee','amount':20}],binding_id='b')
    assert parsed['coverage']=='unknown' and not plan['ready']
    reviewed=plan_application(parsed,[],[{'name':'old','rule_code':'customs_fee','amount':20}],binding_id='b',coverage=['customs'])
    assert reviewed['ready'] and reviewed['disable_rules']==['old'] and reviewed['rules'][0]['covered_scopes']=='customs'


def test_material_punctuation_is_not_erased_during_stable_mapping():
    from overseas_costing.tests.test_logistics_settlement import source,table_row
    from overseas_costing.services.logistics_settlement.model import parse_source
    raw=source('E',amount='100')
    row=table_row('one');row['rowValue'][0]['value']='AB'
    raw['raw_payload']['formComponentValues'].append({'name':'货物明细','componentType':'TableField','value':[row]})
    expense=parse_source(raw,logistics_codes={'logistics'})
    result=plan_application(expense,[{'name':'old','material_code':'A-B','unit':'件','quantity':2,'unit_price':99}],[],binding_id='b')
    assert not result['goods_updates'] and result['remove_items']==['old'] and len(result['goods_additions'])==1


def test_six_decimal_fee_rounding_preserves_rounded_total_with_stable_tail():
    from overseas_costing.tests.test_logistics_settlement import source
    from overseas_costing.services.logistics_settlement.model import parse_source
    from decimal import Decimal
    raw=source('E',amount='0.999999999')
    raw['raw_payload']['formComponentValues'].append({'name':'费用明细','componentType':'TableField','value':[{'rowId':i,'rowValue':[{'name':'费用名称','value':'运费'},{'name':'金额','value':'0.333333333'}]} for i in ('a','b','c')]})
    parsed=parse_source(raw,logistics_codes={'logistics'})
    plan=plan_application(parsed,[],[],binding_id='b')
    amounts={r['rule_code']:r['amount'] for r in plan['rules']}
    assert sum(Decimal(v) for v in amounts.values())==Decimal('1.000000')
    assert all(Decimal(v).as_tuple().exponent>=-6 for v in amounts.values())
    parsed['fees'].reverse()
    again=plan_application(parsed,[],[],binding_id='b')
    assert {r['rule_code']:r['amount'] for r in again['rules']}==amounts
