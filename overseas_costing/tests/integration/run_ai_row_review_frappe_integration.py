"""Disposable real-database regression: selected AI rows never reactivate old freight."""
import uuid
from decimal import Decimal
import frappe
from overseas_costing.tests.integration.run_settlement_frappe_integration import connect, report
from overseas_costing.services import material_ai_fill_service as ai, material_ai_selection_service as review, edit_session_service
from overseas_costing.services.logistics_settlement.store import Store
from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
from overseas_costing.services.logistics_settlement.model import parse_source,dumps
from overseas_costing.services.logistics_settlement import freight_matching, freight_adoption
from overseas_costing.services.effective_logistics_source import load_source_bundle, project_ai_items
from overseas_costing.services.effective_source_values import project_source_values


def main():
    connect();db=Store.frappe();ledger=FrappeLedger();tag='AI-ROWS-'+uuid.uuid4().hex[:10]
    try:
        batch=ledger.create('batch',{'batch_no':tag,'status':'Draft','transport_mode':'EXPRESS','confirm_status':'Pending','source_corp_id':tag})
        version=ledger.create('version',{'batch':batch['name'],'version_code':tag,'status':'Active','is_current':1,'fx_rmb_to_mxn':2.5,'fx_usd_to_rmb':7})
        ledger.put('batch',batch['name'],{'current_version':version['name']})
        for n,(code,name) in enumerate([('AA100','Oppo TPU'),('AA100','Oppo PC'),('BB100','HONOR')],1):
            ledger.create('item',{'batch':batch['name'],'version':version['name'],'stable_line_key':tag+str(n),'row_no':n,'material_code':code,'product_name':name,'spec_model':name,'quantity':1,'actual_shipped_qty':1,'unit':'件','shipped_uom':'件',
                'gross_weight_kg':0,'volume_m3':0,'unit_price':10,'purchase_currency':'RMB','purchase_uom':'件','unit_price_uom':'件','source_doc_no':'independent-purchase',
                'extra_json':dumps({'settlement_packing_missing':['gross_weight_kg','volume_m3']})})
        old=ledger.create('rule',{'batch':batch['name'],'version':version['name'],'rule_code':'old-freight','logical_fee_key':'international_express_fee','expense_category':'国际快递费','amount':2701.66984,'currency':'RMB','amount_status':'ESTIMATED','is_active':1,'is_enabled':1})
        def raw(instance,kind,text):
            return {'corp_id':tag,'process_instance_id':tag+instance,'process_code':kind,'title':'月结付款' if kind=='expense' else '国际物流','status':'COMPLETED','result':'agree',
                'raw_payload':{'formComponentValues':[{'name':'运输说明','value':text},{'name':'币种','value':'RMB'}]}}
        logistics=db.ingest(parse_source(raw('L','logistics','DHL运单号1234567890'),logistics_codes={'logistics'}))
        expense=raw('E','expense','DHL月结账单');expense['settlement_documents']=[{'id':tag+'doc','file_id':tag+'file','file_name':'monthly.xlsx','manifest':{'archive_quality':'original'},'freight_tables':[{'title':'DHL','rows':[
            {'position':11,'fields':{'运单号':'1234567890','运费金额RMB':'2602.82','发货明细':'AA100 Oppo TPU 1pcs\nAA100 Oppo PC 1pcs\n手机壳样品 3pcs'}},
            {'position':12,'fields':{'运单号':'1234567891','运费金额RMB':'3000','发货明细':'BB100 HONOR 1pcs'}}]}]}]
        db.ingest(parse_source(expense,logistics_codes={'logistics'}));db.insert('batch_map',{'id':logistics['id'],'source_id':logistics['id'],'batch':batch['name'],'data':'{}'})
        c=freight_matching.rule_pass(db,logistics['id'])[0]
        actual=freight_adoption.confirm(db,ledger,batch['name'],version['name'],c['id'],c['revision'],c['line_ids'],'Administrator')
        assert not ledger.get('rule',old['name'])['is_active']
        repo=ai.FrappeMaterialAIFillRepository()
        # Use a deterministic local manifest; real source resolver/context, ledger,
        # edit lease, server preview and confirmation remain unchanged.
        repo.list_sources=lambda *args:[]
        def new_run(proposals):
            v=ledger.get('batch',batch['name'])['current_version'];ctx=repo.get_context(batch['name'],v);items=repo.get_items(batch['name'],v)
            run=repo.create_run({'batch':batch['name'],'version':v,'status':'READY','proposal_version':1,'clarification_text':'','source_manifest_json':'[]',
                'input_fingerprint':ai._source_review_fingerprint(batch['name'],v,items,[],'',context=ctx),'candidates_json':dumps(proposals),
                'draft_json':dumps({'material_input_fingerprint':review.material_fingerprint(items,[],ctx)})})
            return run,v
        item=repo.get_items(batch['name'],version['name'])[0]
        run,v=new_run([{'proposal_id':'P','proposal_type':'item_update','target_item_name':item['name'],'default_selected':True,'payload':{'fields':{'volume_m3':2}}},
            {'proposal_id':'OLD','proposal_type':'fee_update','default_selected':True,'payload':{'logical_fee_key':'international_express_fee','amount':'2701.66984','currency':'RMB'}}])
        cat=review.review_catalog(repo,batch['name'],run)
        assert not cat['fees'][0]['can_apply'] and '实际运费' in cat['fees'][0]['blocked_reason']
        ids=[r['row_id'] for r in cat['rows'] if r['default_selected']]
        p=review.prepare(batch['name'],run.name,ids,[],'fill_missing',v,repository=repo)['preview']
        lease=edit_session_service.acquire_edit_session(batch['name'])
        applied=review.confirm(batch['name'],run.name,p['id'],p['revision'],lease['edit_token'],str(lease['modified']),repository=repo)
        assert applied['ok'] and applied['version_name']==v
        saved=ledger.get('item',item['name']);assert saved['volume_m3']==2
        assert project_source_values(saved)['gross_weight_kg'] is None
        assert not ledger.get('rule',old['name'])['is_active']
        assert freight_adoption.context(db,ledger,batch['name'],v)['claims'][0]['amount']=='2602.82'
        assert review.confirm(batch['name'],run.name,p['id'],p['revision'],lease['edit_token'],str(lease['modified']),repository=repo)['idempotent']
        report('ai_fill_real_database',ok=True,disabled_quote='2701.66984',actual='2602.82',partial_fill=True,missing_weight=True,idempotent=True)
        old_items=ledger.rows('item',batch=batch['name'],version=v)
        run,v=new_run([]);cat=review.review_catalog(repo,batch['name'],run)
        ids=[r['row_id'] for r in cat['rows'] if r['origin']=='current' and r['values']['material_code']=='AA100']
        p=review.prepare(batch['name'],run.name,ids,[],'replace_all',v,repository=repo)['preview']
        lease=edit_session_service.acquire_edit_session(batch['name'])
        result=review.confirm(batch['name'],run.name,p['id'],p['revision'],lease['edit_token'],str(lease['modified']),repository=repo)
        assert result['version_name']!=v
        assert ledger.rows('item',batch=batch['name'],version=v)==old_items
        saved=ledger.rows('item',batch=batch['name'],version=result['version_name']);assert len(saved)==2
        bundle=load_source_bundle(batch['name'],result['version_name'],store=db,ledger=ledger)
        assert len(project_ai_items(saved,bundle))==2
        assert all('HONOR' not in x['product_name'] for x in saved)
        assert freight_adoption.context(db,ledger,batch['name'],result['version_name'])['claims'][0]['amount']=='2602.82'
        report('ai_replace_real_database',ok=True,rows=2,old_rows=3,duplicate_sku=True,old_version_preserved=True,freight_preserved=True)
        previous=result['version_name']
        run,v=new_run([{'proposal_id':'NEW','proposal_type':'logistics_reconcile','default_selected':True,'payload':{'rows':[
            {'material_code':'AA100','product_name':'Oppo TPU','spec_model':'Oppo TPU','package_count':7,'packaging_type':'纸箱','quantity':2,'actual_shipped_qty':2,'unit':'件','shipped_uom':'件','_review_origin':'source'},
            {'product_name':'Uncatalogued sample','quantity':3,'actual_shipped_qty':3,'unit':'件','shipped_uom':'件','_review_origin':'source'}]}}])
        cat=review.review_catalog(repo,batch['name'],run);ids=[r['row_id'] for r in cat['rows'] if r['origin']=='source']
        p=review.prepare(batch['name'],run.name,ids,[],'replace_all',v,repository=repo)['preview']
        lease=edit_session_service.acquire_edit_session(batch['name'])
        result=review.confirm(batch['name'],run.name,p['id'],p['revision'],lease['edit_token'],str(lease['modified']),repository=repo)
        source_rows=ledger.rows('item',batch=batch['name'],version=result['version_name'])
        assert len(source_rows)==2 and len(ledger.rows('item',batch=batch['name'],version=previous))==2
        assert all(project_source_values(i)['gross_weight_kg'] is None for i in source_rows)
        from overseas_costing.services.shipment_cost_service import shipment_value
        priced=next(i for i in source_rows if i['material_code']=='AA100')
        assert shipment_value(priced)['amount_rmb']=='20.000000'
        assert project_source_values(priced)['package_count']==7 and project_source_values(priced)['packaging_type']=='纸箱'
        unknown=next(i for i in source_rows if not i['material_code'])
        assert shipment_value(unknown)['amount_rmb'] is None
        report('ai_replace_source_rows_real_database',ok=True,rows=2,unknown_sku_pending=True,price_evidence_preserved=True,missing_packing_cleared=True)

        run,v=new_run([{'proposal_id':'WEIGHT','proposal_type':'item_update','target_item_name':priced['name'],
            'default_selected':True,'payload':{'fields':{'gross_weight_kg':10}}}])
        cat=review.review_catalog(repo,batch['name'],run)
        ids=[r['row_id'] for r in cat['rows'] if r['default_selected']]
        p=review.prepare(batch['name'],run.name,ids,[],'fill_missing',v,repository=repo)['preview']
        lease=edit_session_service.acquire_edit_session(batch['name'])
        result=review.confirm(batch['name'],run.name,p['id'],p['revision'],lease['edit_token'],str(lease['modified']),repository=repo)
        saved=ledger.get('item',priced['name'])
        assert project_source_values(saved)['gross_weight_kg']==10
        reread=repo.get_items(batch['name'],result['version_name'])
        assert project_source_values(next(row for row in reread if row['name']==priced['name']))['gross_weight_kg']==10
        assert project_source_values(saved)['package_count']==7
        assert freight_adoption.context(db,ledger,batch['name'],result['version_name'])['claims'][0]['amount']=='2602.82'
        report('ai_fill_selected_source_overlay_real_database',ok=True,gross_weight=10,package_count=7,freight_preserved=True)

    finally:
        frappe.db.rollback();frappe.destroy()


if __name__=='__main__':main()
