"""Incremental amendment/source replacement checks on the isolated local database."""
import uuid
from decimal import Decimal
import frappe
from overseas_costing.tests.integration.run_settlement_frappe_integration import connect, report
from overseas_costing.services.logistics_settlement.store import Store
from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
from overseas_costing.services.logistics_settlement.model import parse_source,dumps
from overseas_costing.services.logistics_settlement import freight_matching as matching,freight_adoption as fees,packing_selection as packing
from overseas_costing.services.effective_logistics_source import load_source_bundle
from overseas_costing.services.packing_snapshot_service import selected_packing_ai_sources
from overseas_costing.services.material_ai_fill_service import _read_source


def main():
    connect();db=Store.frappe();ledger=FrappeLedger();tag='REVIEW-'+uuid.uuid4().hex[:10]
    try:
        batch=ledger.create('batch',{'batch_no':tag,'status':'Draft','transport_mode':'EXPRESS','confirm_status':'Pending','source_corp_id':tag})
        version=ledger.create('version',{'batch':batch['name'],'version_code':tag,'status':'Active','is_current':1,'fx_rmb_to_mxn':2.5,'fx_usd_to_rmb':7})
        ledger.put('batch',batch['name'],{'current_version':version['name']})
        for code,name in [('AA100','Oppo TPU'),('BB100','HONOR')]:
            ledger.create('item',{'batch':batch['name'],'version':version['name'],'material_code':code,'product_name':name,'quantity':1,'unit':'件',
                                 'gross_weight_kg':9,'volume_m3':1,'unit_price':10,'purchase_currency':'RMB','purchase_uom':'件','unit_price_uom':'件','source_doc_no':'independent-purchase'})
        def raw(instance,kind,text):
            return {'corp_id':tag,'process_instance_id':tag+instance,'process_code':kind,'title':'月结付款' if kind=='expense' else '国际物流',
                    'status':'COMPLETED','result':'agree','raw_payload':{'formComponentValues':[{'name':'运输说明','value':text},{'name':'币种','value':'RMB'}]}}
        logistics=db.ingest(parse_source(raw('L','logistics','DHL运单号1234567890'),logistics_codes={'logistics'}))
        expense=raw('E','expense','DHL月结账单');expense['settlement_documents']=[{'id':tag+'doc','file_id':tag+'file','file_name':'monthly.xlsx',
            'manifest':{'archive_quality':'original'},'freight_tables':[{'title':'DHL','rows':[
                {'position':11,'fields':{'运单号':'1234567890','运费金额RMB':'2600','发货明细':'AA100 Oppo TPU 1pcs\nAA200 Oppo PC 1pcs\n手机壳样品 3pcs'}},
                {'position':12,'fields':{'运单号':'1234567891','运费金额RMB':'3000','发货明细':'BB100 HONOR 1pcs'}}]}]}]
        db.ingest(parse_source(expense,logistics_codes={'logistics'}))
        db.insert('batch_map',{'id':logistics['id'],'source_id':logistics['id'],'batch':batch['name'],'data':'{}'})
        c=matching.rule_pass(db,logistics['id'])[0]
        first=fees.confirm(db,ledger,batch['name'],version['name'],c['id'],c['revision'],c['line_ids'],'Administrator')
        corrected=fees.amend(db,ledger,batch['name'],version['name'],first['claims'][0]['id'],first['revision'],'amount','Administrator',amount='2500.123456',reason='test')
        assert corrected['claims'][0]['original_amount']=='2600'
        assert Decimal(str(ledger.rows('rule',batch=batch['name'],version=version['name'])[0]['amount']))==Decimal('2500.123456')
        chosen=next(r for r in packing.list_sources(db,ledger,batch['name'],version['name'])['sources'] if r['row_count']==3)
        pr=packing.preview_selection(db,ledger,batch['name'],version['name'],chosen['id'],chosen['revision'])
        applied=packing.confirm_selection(db,ledger,batch['name'],version['name'],pr['id'],pr['revision'],'Administrator',replace_all=True)
        current=ledger.rows('item',batch=batch['name'],version=applied['version'])
        assert len(current)==3 and all('HONOR' not in i['product_name'] for i in current)
        from overseas_costing.services.effective_source_values import project_source_values
        assert all(project_source_values(i).get('gross_weight_kg') is None and project_source_values(i).get('volume_m3') is None for i in current)
        assert len(ledger.rows('item',batch=batch['name'],version=version['name']))==2
        from overseas_costing.services.batch_service import get_batch_items
        exported=get_batch_items(batch['name'])
        assert exported['total']==3 and all(i['gross_weight_kg'] is None for i in exported['items'])
        bundle=load_source_bundle(batch['name'],applied['version'],store=db,ledger=ledger)
        manifest=selected_packing_ai_sources(batch['name'],bundle)
        candidates,document=_read_source(current,manifest[0])
        assert 'HONOR' not in dumps(document) and 'monthly.xlsx' in dumps(document)
        assert bundle['context']['freight']['claims'][0]['amount']=='2500.123456'
        assert packing.confirm_selection(db,ledger,batch['name'],version['name'],pr['id'],pr['revision'],'Administrator',replace_all=True)['cached']
        report('shipment_review_database',ok=True,packing_rows=3,old_rows=2,fee='2500.123456',missing_weight_preserved=True,scoped_ai=True)
    finally:
        frappe.db.rollback();frappe.destroy()


if __name__=='__main__':main()
