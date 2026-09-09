"""Real local XLSX preview/adoption on the guarded disposable site; no AI/OA calls."""
from decimal import Decimal
from io import BytesIO
from hashlib import sha256
import uuid
from copy import deepcopy

import frappe
from openpyxl import Workbook

from overseas_costing.tests.integration.run_settlement_frappe_integration import connect, report, SITE


def main():
    connect()
    from frappe.utils.file_manager import save_file
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
    from overseas_costing.services.logistics_settlement.model import parse_source,dumps,digest
    from overseas_costing.services.logistics_settlement.matching import match_source,confirm_candidate
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    from overseas_costing.services.logistics_settlement.runtime import calculation_blockers
    from overseas_costing.services.material_import_service import preview_material_import,apply_material_import
    from overseas_costing.services.packing_snapshot_service import list_packing_sources
    from overseas_costing.services.edit_session_service import acquire_edit_session,release_edit_session
    from overseas_costing.services.material_input_service import present_material_row
    from overseas_costing.services.calculate_service import recalculate_batch

    run=uuid.uuid4().hex[:10]; corp='LOCAL-UNIFIED-'+run
    store,ledger=Store.frappe(),FrappeLedger()
    batch=ledger.create('batch',{'batch_no':corp,'status':'Draft','transport_mode':'SEA','source_corp_id':corp,'confirm_status':'Pending'})
    version=ledger.create('version',{'batch':batch['name'],'version_code':'INITIAL','status':'Active','is_current':1,'fx_rmb_to_mxn':3})
    ledger.put('batch',batch['name'],{'current_version':version['name']})
    item=ledger.create('item',{'batch':batch['name'],'version':version['name'],'row_no':1,'material_code':'SKU-A',
        'product_name':'旧物流名称','unit':'件','quantity':2,'actual_shipped_qty':999,'gross_weight_kg':888,'volume_m3':777,
        'unit_price':10,'goods_value':20,'purchase_currency':'RMB','purchase_uom':'件','unit_price_uom':'件','source_doc_no':'INDEPENDENT-PURCHASE',
        'extra_json':dumps({'goods_value_source':'derived_quantity_unit_price'})})
    workbook=Workbook();sheet=workbook.active;sheet.title='装箱计划'
    sheet.append(['物料编码','产品名称','数量','单位','毛重(kg)','体积(m3)'])
    sheet.append(['SKU-A','采购支出新名称',6,'件',12,3])
    content=BytesIO();workbook.save(content)
    file=save_file('current-expense-packing-'+run+'.xlsx',content.getvalue(),None,None,is_private=1)
    document={'id':sha256(content.getvalue()).hexdigest(),'file_name':file.file_name,'file_url':file.file_url,'status':'parsed',
        'manifest':{'file_id':run,'sha256':sha256(content.getvalue()).hexdigest(),'object_key':run,
                    'archive_status':'archived','archive_quality':'original','source_kind':'form'},'tables':[]}
    def source(kind,documents=None,hour='00'):
        fields=[{'name':'运输说明','value':'海运 MXT500174'}]
        if kind=='expense':
            fields += [{'name':'采购支出','value':'服务类采购Compra De Servicios'},
                {'name':'服务类采购','value':'物流及运输服务Servicios de logística y transporte'},
                {'name':'金额importe','value':'0'},{'name':'币种Moneda','value':'RMB'}]
        return {'corp_id':corp,'process_instance_id':corp+'-'+kind,'process_code':kind,'status':'COMPLETED','result':'agree',
            'updated_at':'2026-09-10T'+hour+':00:00+00:00','raw_payload':{'formComponentValues':fields},
            'settlement_documents':documents or [],'attachments':[d['manifest'] for d in documents or []]}
    logistics=store.ingest(parse_source(source('logistics'),logistics_codes={'logistics'}))
    expense=store.ingest(parse_source(source('expense',[document]),logistics_codes={'logistics'}))
    store.insert('batch_map',{'id':logistics['id'],'source_id':logistics['id'],'batch':batch['name'],'data':'{}'})
    candidate=match_source(store,expense['id'])[0]
    binding=confirm_candidate(store,candidate['id'],candidate['revision'],'Administrator')
    first=apply_binding(store,ledger,binding['id'],'Administrator')
    assert first['application_status']=='applied_pending'
    assert present_material_row(ledger.get('item',item['name']))['gross_weight_kg'] is None
    assert calculation_blockers(batch['name'],version['name'])
    store.commit()

    listing=list_packing_sources(batch['name'])
    assert listing['source_context']['root_kind']=='expense'
    sources=[row for row in listing['approval_sources'] if row['source_kind']=='approval_attachment']
    assert len(sources)==1 and not listing.get('manual_attachments')
    preview=preview_material_import(batch['name'],'approval_attachment',sources[0]['source_id'],sheet_name='装箱计划')
    assert preview['cargo_review']['complete'],preview['cargo_review']
    assert preview['cargo_review']['row_count']==1
    assert '888' not in dumps(preview.get('autofill_preview') or {})
    lease=acquire_edit_session(batch['name']);assert lease['ok']
    adopted=apply_material_import(batch['name'],preview['preview_revision'],{'confirm_complete_cargo':True},
        lease['edit_token'],str(lease['modified']))
    assert adopted['ok'],adopted
    release_edit_session(batch['name'],lease['edit_token'])
    current=ledger.rows('item',batch=batch['name'],version=version['name'])
    assert len(current)==1
    row=present_material_row(current[0])
    assert row['material_code']=='SKU-A' and Decimal(row['effective_shipping_quantity'])==6
    assert Decimal(str(row['gross_weight_kg']))==12 and Decimal(row['shipment_value_rmb'])==60
    assert Decimal(str(current[0]['gross_weight_kg']))==888 and Decimal(str(current[0]['quantity']))==2
    assert not calculation_blockers(batch['name'],version['name'])
    assert recalculate_batch(batch['name'])['ok']
    store.commit()
    report('actual_xlsx_signed_preview_and_atomic_adoption',ok=True,batch=batch['name'],source=sources[0]['source_id'])

    stale_preview=preview_material_import(batch['name'],'approval_attachment',sources[0]['source_id'],sheet_name='装箱计划')
    changed=source('expense',[document],hour='01');changed['raw_payload']['operationRecords']=[{'remark':'采购支出新补充评论'}]
    store.ingest(parse_source(changed,logistics_codes={'logistics'}));store.commit()
    before=deepcopy(ledger.rows('item',batch=batch['name'],version=version['name']))
    lease=acquire_edit_session(batch['name']);store.commit()
    rejected=apply_material_import(batch['name'],stale_preview['preview_revision'],{'confirm_complete_cargo':True},lease['edit_token'],str(lease['modified']))
    assert not rejected['ok'] and rejected.get('source_changed'),rejected
    assert ledger.rows('item',batch=batch['name'],version=version['name'])==before
    release_edit_session(batch['name'],lease['edit_token']);store.commit()
    report('actual_source_update_rejects_stale_import',ok=True,batch=batch['name'])
    report('unified_source_integration_complete',ok=True,run=run,site=SITE)
    frappe.destroy()


if __name__=='__main__':
    main()
