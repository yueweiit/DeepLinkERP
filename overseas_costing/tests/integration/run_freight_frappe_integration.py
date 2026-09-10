"""Synthetic fee/packing adoption on the isolated settlement-test.local database only."""
import json
import uuid
import sys
import subprocess
import os
import time
from pathlib import Path
from decimal import Decimal
import frappe
from overseas_costing.tests.integration.run_settlement_frappe_integration import connect, report


def main():
    connect()
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
    from overseas_costing.services.logistics_settlement.model import parse_source,dumps
    from overseas_costing.services.logistics_settlement.freight_matching import rule_pass
    from overseas_costing.services.logistics_settlement.freight_adoption import confirm,source_updated,context
    from overseas_costing.services.logistics_settlement.freight_packing import preview,confirm as packing_confirm
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    from overseas_costing.services.logistics_settlement.fee_policy import select_fees
    def source(instance,kind='expense',corp='test',text='DHL运费',amount='9000'):
        return {'corp_id':corp,'process_instance_id':instance,'process_code':kind,'title':'月结付款' if kind=='expense' else '国际物流','status':'COMPLETED','result':'agree','updated_at':'2026-09-09T00:00:00+00:00','raw_payload':{'formComponentValues':[{'name':'运输说明','value':text},{'name':'总金额','value':amount},{'name':'币种','value':'RMB'}]}}
    def monthly():
        raw=source('monthly');raw['settlement_documents']=[{'id':'doc','file_id':'file','file_name':'synthetic.xlsx','manifest':{'archive_quality':'original','sha256':'synthetic'},'freight_tables':[{'title':'DHL快递','rows':[{'position':11,'fields':{'运单号':'1234567890','运费金额RMB':'2600','发货明细':'AA100 Oppo TPU 1pcs\nAA200 Oppo PC 1pcs\n手机壳样品 3pcs'}},{'position':12,'fields':{'运单号':'1234567891','运费金额RMB':'6400','发货明细':'BB100 HONOR 1pcs'}}]}]}];return raw
    frappe.set_user('Administrator');frappe.conf.overseas_costing_freight_lines_enabled=1
    db=Store.frappe();frappe.db.commit();db.install();frappe.db.commit();ledger=FrappeLedger()
    tag='FREIGHT-TEST-'+uuid.uuid4().hex[:10]
    batch=ledger.create('batch',{'batch_no':tag,'status':'Draft','transport_mode':'EXPRESS','confirm_status':'Pending','source_corp_id':tag})
    version=ledger.create('version',{'batch':batch['name'],'version_code':tag,'status':'Active','is_current':1,'fx_rmb_to_mxn':2.5,'fx_usd_to_rmb':7})
    ledger.put('batch',batch['name'],{'current_version':version['name']})
    item=ledger.create('item',{'batch':batch['name'],'version':version['name'],'row_no':1,'material_code':'BB100','product_name':'HONOR','quantity':1,'unit':'pcs','actual_shipped_qty':1,'gross_weight_kg':4,'unit_price':10,'goods_value':10,'purchase_currency':'RMB','purchase_uom':'pcs','unit_price_uom':'pcs'})
    for key,amount in [('international_express_fee',3000),('customs_service',100)]:
        ledger.create('rule',{'batch':batch['name'],'version':version['name'],'rule_code':key,'logical_fee_key':key,'amount':amount,'currency':'RMB','is_enabled':1,'is_active':1,'allocation_basis':'gross_weight','scope_type':'ALL_ITEMS'})
    raw=source('L','logistics',corp=tag,text='DHL运单号1234567890');raw['business_id']='202601010000000000001'
    logistics=db.ingest(parse_source(raw,logistics_codes={'logistics'}));expense_raw=monthly();expense_raw['corp_id']=tag
    expense=db.ingest(parse_source(expense_raw,logistics_codes={'logistics'}))
    db.insert('batch_map',{'id':logistics['id'],'source_id':logistics['id'],'batch':batch['name'],'data':'{}'})
    candidate=rule_pass(db,logistics['id'])[0]
    result=confirm(db,ledger,batch['name'],version['name'],candidate['id'],candidate['revision'],candidate['line_ids'],'test')
    assert result['status']=='applied'
    assert ledger.get('item',item['name'])['gross_weight_kg']==4
    ctx=resolve_source_context(batch['name'],version['name'],store=db,ledger=ledger)
    fees=select_fees(ledger.rows('rule',batch=batch['name'],version=version['name']),source_context=ctx)
    assert sum(Decimal(str(f['amount'])) for f in fees)==2700
    again=confirm(db,ledger,batch['name'],version['name'],candidate['id'],candidate['revision'],candidate['line_ids'],'test')
    assert again['cached']
    report('fee_only_and_customs_preservation',ok=True,claims=len(result['claims']))
    pr=preview(db,ledger,batch['name'],version['name'],candidate['id'],candidate['revision'])
    assert 'HONOR' not in dumps(pr['goods']) and len(pr['goods'])==3
    saved=packing_confirm(db,ledger,batch['name'],version['name'],pr['id'],pr['revision'],[{'line_key':pr['goods'][0]['line_key'],'item_name':item['name']}],'test')
    assert saved['status']=='applied'
    ctx=resolve_source_context(batch['name'],version['name'],store=db,ledger=ledger)
    assert len(select_fees(ledger.rows('rule',batch=batch['name'],version=version['name']),source_context=ctx))==2
    assert not ledger.get('item',item['name']).get('unit_price')
    from overseas_costing.services.shipment_cost_service import shipment_value
    assert shipment_value(ledger.get('item',item['name']))['error']
    report('packing_separate_no_cross_sku_price',ok=True)
    ledger.put('version',version['name'],{'status':'Confirmed'})
    expense_raw['result']='refuse';expense_raw['updated_at']='2026-09-10T00:00:00+00:00'
    db.ingest(parse_source(expense_raw,logistics_codes={'logistics'}));source_updated(db,ledger,expense['id']);source_updated(db,ledger,expense['id'])
    assert len(ledger.rows('version',batch=batch['name']))==2
    assert ledger.get('version',version['name'])['status']=='Confirmed'
    assert not context(db,ledger,batch['name'])['available']
    report('invalidation_unique_adjustment',ok=True)
    frappe.db.rollback();frappe.destroy()


def worker():
    connect()
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
    from overseas_costing.services.logistics_settlement.freight_adoption import confirm
    request=json.loads(Path(sys.argv[2]).read_text());barrier=Path(sys.argv[3]);Path(sys.argv[4]).touch()
    deadline=time.monotonic()+20
    while not barrier.exists():
        assert time.monotonic()<deadline
        time.sleep(.02)
    try:
        result=confirm(Store.frappe(),FrappeLedger(),**request);frappe.db.commit();report('concurrent_confirm',ok=True)
    except Exception as exc:
        frappe.db.rollback();report('concurrent_confirm',ok=False,error=str(exc))
    finally:frappe.destroy()


def concurrency():
    import tempfile
    connect();frappe.set_user('Administrator')
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
    from overseas_costing.services.logistics_settlement.model import parse_source
    from overseas_costing.services.logistics_settlement.freight_matching import rule_pass
    db=Store.frappe();ledger=FrappeLedger();tag='FREIGHT-RACE-'+uuid.uuid4().hex[:10]
    def raw(instance,kind):
        fields=[{'name':'运输说明','value':'DHL运单号1234567890'}]
        if kind=='expense':fields += [{'name':'采购支出','value':'服务类采购'},{'name':'服务类采购','value':'物流及运输服务'},{'name':'金额','value':'300'},{'name':'币种','value':'RMB'}]
        return {'corp_id':tag,'process_instance_id':instance,'process_code':kind,'status':'COMPLETED','result':'agree','updated_at':'2026-09-09T00:00:00+00:00','raw_payload':{'formComponentValues':fields}}
    db.ingest(parse_source(raw('E','expense'),logistics_codes={'logistics'}));requests=[]
    for index in range(2):
        source=db.ingest(parse_source(raw('L'+str(index),'logistics'),logistics_codes={'logistics'}))
        b=ledger.create('batch',{'batch_no':tag+'-'+str(index),'status':'Draft','confirm_status':'Pending'})
        v=ledger.create('version',{'batch':b['name'],'version_code':tag+'-'+str(index),'status':'Active','is_current':1})
        ledger.put('batch',b['name'],{'current_version':v['name']});db.insert('batch_map',{'id':source['id'],'source_id':source['id'],'batch':b['name'],'data':'{}'})
        c=rule_pass(db,source['id'])[0];requests.append({'batch_name':b['name'],'version_name':v['name'],'candidate_id':c['id'],'candidate_revision':c['revision'],'line_ids':c['line_ids'],'actor':'test'})
    frappe.db.commit()
    with tempfile.TemporaryDirectory(prefix='freight-race-') as directory:
        root=Path(directory);workers=[]
        for i,request in enumerate(requests):
            path=root/str(i);path.write_text(json.dumps(request));workers.append(subprocess.Popen([sys.executable,__file__,'worker',str(path),str(root/'go'),str(root/('ready'+str(i)))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ))
        deadline=time.monotonic()+20
        while not all((root/('ready'+str(i))).exists() for i in range(2)):
            assert time.monotonic()<deadline
            time.sleep(.02)
        (root/'go').touch();outcomes=[]
        for process in workers:
            out,err=process.communicate(timeout=30);assert process.returncode==0,err
            outcomes.append(json.loads(out.strip().splitlines()[-1])['ok'])
        assert sorted(outcomes)==[False,True],outcomes
    report('mariadb_concurrent_unique_claim',ok=True)
    frappe.destroy()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='worker':worker()
    else:main();concurrency()
