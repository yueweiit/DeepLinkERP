from overseas_costing.tests.test_settlement_writer import setup
from overseas_costing.services.logistics_settlement.writer import apply_binding


def test_application_rollback_preserves_packing_and_stops_new_sync(setup):
    from overseas_costing.services.logistics_settlement.rollback import restore_application
    s,l,b,v,i,r,binding=setup
    applied=apply_binding(s,l,binding['id'],'u')
    l.put('item',i['name'],{'gross_weight_kg':55})
    result=restore_application(s,l,applied['last_application'],applied['revision'],'选择此应用记录回退','u')
    item=l.get('item',i['name'])
    assert str(item['quantity'])=='2' and item['gross_weight_kg']==55 and item['unit_price']==10
    assert not s.get('state','control')['enabled']
    assert result['application_status']=='rolled_back'
    assert not l.get('rule',r['name'])['is_enabled']
    assert s.count('audit',action='restore_application')==1
