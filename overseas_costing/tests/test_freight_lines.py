"""Synthetic monthly statements: no customer attachments or identifiers."""
from io import BytesIO
from decimal import Decimal
import sqlite3

from openpyxl import Workbook

from overseas_costing.services.logistics_settlement.documents import parse_document
from overseas_costing.services.logistics_settlement.model import parse_source, dumps
from overseas_costing.services.logistics_settlement.store import Store
from overseas_costing.tests.test_logistics_settlement import source
from overseas_costing.tests.test_settlement_writer import Ledger
import pytest
import json


def monthly():
    row = source('monthly', text='DHL 月结账单', amount='9000')
    row['title'] = '月结付款'
    row['raw_payload']['formComponentValues'] = [
        {'name': '付款分类', 'value': '物流费用'}, {'name': '付款事由', 'value': 'DHL月结账单'},
        {'name': '总金额', 'value': '9000'}, {'name': '币种', 'value': '["人民币"]'}]
    wb = Workbook(); sh = wb.active; sh.title = 'DHL快递'
    sh.append(['发件日期', '运单号', '重量', '件数', '运费金额（RMB）', '单价/KG', '发货明细', '所属项目', '钉钉流程'])
    sh.append(['2026-07-01','1234567890',33.5,1,2600,77.6,'AA100 Oppo TPU 1pcs\nAA200 Oppo PC 1pcs\n手机壳样品 3pcs','项目甲','202601010000000000001'])
    sh.append(['2026-07-01','1234567891',33.5,1,6400,191,'BB100 HONOR TPU 1pcs','项目乙','202601010000000000002'])
    sh.append(['总计',None,None,None,9000])
    out=BytesIO(); wb.save(out)
    doc = {'id':'doc', 'file_name':'monthly.xlsx', 'file_id':'file', 'manifest':{'archive_quality':'original','sha256':'hash'}, **parse_document(out.getvalue(),'monthly.xlsx')}
    row['settlement_documents'] = [doc]
    return row


def test_monthly_and_wrong_category_financial_sources_are_discovered():
    parsed=parse_source(monthly(),logistics_codes={'logistics'})
    assert parsed['kind']=='expense'
    assert parsed['currency']=='RMB'
    wrong=source('misc'); wrong['title']='Gastos费用支出'
    wrong['raw_payload']['formComponentValues']=[{'name':'分类','value':'cfe'},{'name':'明细','value':'PAGO DHL guía 1234567890'},{'name':'金额','value':'10'}]
    assert parse_source(wrong,logistics_codes={'logistics'})['kind']=='expense'


def test_comment_waybill_is_indexed_without_treating_bank_account_as_waybill():
    row=source('L','logistics',text='发货')
    row['raw_payload']['comments']=[{'text':'DHL单号1234567890，已到工厂。Código de rastreo: 1 2 3 4 5 6 7 8 9 0\n银行账号 9876543210'}]
    tokens=parse_source(row,logistics_codes={'logistics'})['identifiers']
    assert ('waybill','1234567890') in tokens
    assert not any(t[1]=='9876543210' for t in tokens)


def test_monthly_extracts_own_row_and_never_total_project_or_other_goods():
    from overseas_costing.services.logistics_settlement.freight_lines import lines_for_source, matching_lines
    s=parse_source(monthly(),logistics_codes={'logistics'})
    lines=lines_for_source(s)
    assert len(lines)==2
    assert sum(Decimal(x['amount']) for x in lines)==Decimal('9000')
    l=parse_source(source('L','logistics',text='DHL运单号1234567890'),logistics_codes={'logistics'})
    selected=matching_lines(l,lines)
    assert len(selected)==1 and selected[0]['amount']=='2600'
    assert selected[0]['evidence']['row']==2
    assert 'Oppo' in selected[0]['cargo_text'] and 'HONOR' not in selected[0]['cargo_text']
    assert selected[0]['billing_weight']=='33.5'
    assert 'gross_weight_kg' not in selected[0]


def test_reordered_rows_keep_identity_zero_and_credits_are_not_discarded():
    from overseas_costing.services.logistics_settlement.freight_lines import lines_for_source
    raw=monthly(); source1=parse_source(raw,logistics_codes={'logistics'})
    lines=lines_for_source(source1)
    table=raw['settlement_documents'][0]['freight_tables'][0]
    table['rows'].reverse()
    reordered=lines_for_source(parse_source(raw,logistics_codes={'logistics'}))
    assert {x['line_key'] for x in lines}=={x['line_key'] for x in reordered}


def test_summary_only_multi_shipment_never_becomes_whole_ticket_fee():
    from overseas_costing.services.logistics_settlement.freight_lines import lines_for_source
    raw=monthly(); raw['settlement_documents']=[]
    raw['raw_payload']['formComponentValues'].append({'name':'关联国际物流','componentType':'RelateField','value':[{'processInstanceId':'L1'},{'processInstanceId':'L2'}]})
    assert lines_for_source(parse_source(raw,logistics_codes={'logistics'}))==[]


def setup_cost():
    s=Store.sqlite(sqlite3.connect(':memory:'));s.install();l=Ledger(s)
    b=l.create('batch',{'status':'Dirty','confirm_status':'Pending'})
    v=l.create('version',{'batch':b['name'],'status':'Active','fx_rmb_to_mxn':2.6})
    l.put('batch',b['name'],{'current_version':v['name']})
    item=l.create('item',{'batch':b['name'],'version':v['name'],'material_code':'AA100','product_name':'Oppo','unit':'件','quantity':1,'gross_weight_kg':10,'volume_m3':2})
    l.create('rule',{'batch':b['name'],'version':v['name'],'rule_code':'oa_logistics_freight','amount':3000,'currency':'RMB','is_enabled':1,'is_active':1})
    l.create('rule',{'batch':b['name'],'version':v['name'],'rule_code':'customs_fee','amount':30,'currency':'RMB','is_enabled':1,'is_active':1})
    ls=s.ingest(parse_source(source('L','logistics',text='DHL运单号1234567890'),logistics_codes={'logistics'}))
    s.insert('batch_map',{'id':ls['id'],'source_id':ls['id'],'batch':b['name'],'data':'{}'})
    expense=s.ingest(parse_source(monthly(),logistics_codes={'logistics'}))
    return s,l,b,v,item,ls,expense


def test_confirm_fee_only_preserves_packing_and_customs_and_is_idempotent():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a
    from overseas_costing.services.logistics_settlement.fee_policy import select_fees
    s,l,b,v,item,ls,e=setup_cost(); c=m.rule_pass(s,ls['id'])[0]
    result=a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],[c['line_ids'][0]],'user')
    assert result['status']=='applied'
    assert l.get('item',item['name'])['gross_weight_kg']==10
    assert l.get('item',item['name'])['quantity']==1
    fees=select_fees(l.rows('rule'),{'fx_rmb_to_mxn':2.6},source_context={'freight':a.context(s,l,b['name'],v['name'])})
    assert sum(Decimal(str(r['amount'])) for r in fees)==Decimal('2630')
    again=a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],[c['line_ids'][0]],'user')
    assert again['status']=='applied' and s.count('freight_claim')==1 and s.count('freight_application')==1


def test_same_monthly_bill_two_shipments_and_no_whole_bill_occupancy():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a
    s,l,b,v,item,ls,e=setup_cost(); c=m.rule_pass(s,ls['id'])[0]
    a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'user')
    other=s.ingest(parse_source(source('L2','logistics',text='DHL运单号1234567891'),logistics_codes={'logistics'}))
    c2=m.rule_pass(s,other['id'])[0]
    assert c2['status']=='pending' and len(c2['line_ids'])==1


def test_failed_rule_write_rolls_back_claims_and_confirmed_draft():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a
    s,l,b,v,item,ls,e=setup_cost(); c=m.rule_pass(s,ls['id'])[0]
    l.put('version',v['name'],{'status':'Confirmed'});l.fail_rules=True
    with pytest.raises(RuntimeError):a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'user')
    assert s.count('freight_claim')==0 and len(l.rows('version'))==1


def test_stale_candidate_and_nonapproved_expense_cannot_adopt():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a
    s,l,b,v,item,ls,e=setup_cost(); c=m.rule_pass(s,ls['id'])[0]
    row=monthly();row['status']='RUNNING';row['updated_at']='2026-09-10T00:00:00+00:00'
    s.ingest(parse_source(row,logistics_codes={'logistics'}))
    with pytest.raises(ValueError):a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'user')
    assert s.count('freight_claim')==0


def test_final_zero_and_invalid_source_never_revive_estimate():
    from overseas_costing.services.logistics_settlement.fee_policy import select_fees
    actual={'rule_code':'freight_a','source_binding_id':'claim','source_snapshot':'s','amount':0,'currency':'RMB','covered_scopes':'freight','is_final':1,'amount_status':'ACTUAL'}
    old={'rule_code':'oa_logistics_freight','amount':100}
    ctx={'freight':{'policy':'shipment-freight-1','selected':True,'available':True,'claims':[{'id':'claim','source_snapshot':'s'}]}}
    assert select_fees([old,actual],source_context=ctx)==[actual]
    ctx['freight']['available']=False
    with pytest.raises(ValueError):select_fees([old,actual],source_context=ctx)


def test_packing_preview_is_separate_scoped_and_does_not_change_items():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_packing as p
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    preview=p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])
    assert preview['status']=='pending' and not preview['complete']
    assert len(preview['goods'])==3
    assert 'HONOR' not in dumps(preview['goods'])
    assert l.get('item',item['name'])['quantity']==1
    assert s.count('freight_claim')==0


def test_packing_confirm_preserves_missing_physical_and_cannot_apply_stale_preview():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_packing as p
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    preview=p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])
    l.put('item',item['name'],{'quantity':2})
    with pytest.raises(ValueError):p.confirm(s,l,b['name'],v['name'],preview['id'],preview['revision'],[],'user')
    assert s.count('freight_claim')==0


def test_split_source_context_tracks_freight_while_retaining_original_packing():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    from overseas_costing.services.effective_source_values import source_context_from_items
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'user')
    ctx=resolve_source_context(b['name'],v['name'],store=s,ledger=l)
    assert ctx['freight']['selected'] and ctx['packing']['root_source_id']==ls['id']
    assert source_context_from_items(l.rows('item'))['freight']['selected']


def test_packing_only_does_not_disable_fees_and_logistics_changes_fence_preview():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_packing as p
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    from overseas_costing.services.logistics_settlement.fee_policy import select_fees
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    pr=p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])
    p.confirm(s,l,b['name'],v['name'],pr['id'],pr['revision'],[{'line_key':pr['goods'][0]['line_key'],'item_name':item['name']}],'u')
    ctx=resolve_source_context(b['name'],v['name'],store=s,ledger=l)
    assert len(select_fees(l.rows('rule'),source_context=ctx))==2
    pr=p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])
    row=source('L','logistics',text='DHL运单号1234567891');row['updated_at']='2026-09-10T00:00:00+00:00'
    s.ingest(parse_source(row,logistics_codes={'logistics'}))
    with pytest.raises(ValueError):p.confirm(s,l,b['name'],v['name'],pr['id'],pr['revision'],[{'line_key':pr['goods'][0]['line_key'],'item_name':item['name']}],'u')


def test_packing_only_source_invalidation_creates_one_adjustment():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_packing as p,freight_adoption as a
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    pr=p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])
    p.confirm(s,l,b['name'],v['name'],pr['id'],pr['revision'],[{'line_key':pr['goods'][0]['line_key'],'item_name':item['name']}],'u')
    l.put('version',v['name'],{'status':'Confirmed'})
    row=monthly();row['result']='refuse';row['updated_at']='2026-09-10T00:00:00+00:00';s.ingest(parse_source(row,logistics_codes={'logistics'}))
    a.source_updated(s,l,e['id']);a.source_updated(s,l,e['id'])
    assert len(l.rows('version'))==2 and l.get('version',v['name'])['status']=='Confirmed'


def test_subtotal_and_duplicate_form_attachment_cannot_be_adopted_twice():
    from overseas_costing.services.logistics_settlement.freight_lines import lines_for_source
    raw=monthly();table=raw['settlement_documents'][0]['freight_tables'][0]
    subtotal=dict(table['rows'][0]);subtotal['fields']={**subtotal['fields'],'费用名称':'运费小计'};subtotal['position']=20;table['rows'].append(subtotal)
    lines=lines_for_source(parse_source(raw,logistics_codes={'logistics'}))
    assert len(lines)==2


def test_confirmed_fee_only_packing_snapshot_is_frozen_after_logistics_update():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_adoption as a
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'u')
    before=resolve_source_context(b['name'],v['name'],store=s,ledger=l)
    l.put('version',v['name'],{'status':'Confirmed'})
    row=source('L','logistics',text='DHL运单号1234567891');row['updated_at']='2026-09-10T00:00:00+00:00'
    s.ingest(parse_source(row,logistics_codes={'logistics'}));a.source_updated(s,l,ls['id'])
    after=resolve_source_context(b['name'],v['name'],store=s,ledger=l)
    assert len(l.rows('version'))==2
    assert after['packing']['source_snapshot']==before['packing']['source_snapshot']


def test_ai_request_does_not_include_whole_bill_cargo_and_rejected_packing_cannot_apply():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_packing as p
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    e['goods']=[{'material_code':'SECRET','product_name':'FOREIGN HONOR'}]
    messages=m.ai_messages(ls,e,[s.get('freight_line',c['line_ids'][0])])
    assert 'FOREIGN HONOR' not in dumps(messages)
    pr=p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])
    s.put('freight_candidate',{'id':c['id'],'status':'rejected'})
    with pytest.raises(ValueError):p.confirm(s,l,b['name'],v['name'],pr['id'],pr['revision'],[{'line_key':pr['goods'][0]['line_key'],'item_name':item['name']}],'u')


def test_transport_identifiers_must_agree_and_duplicate_economic_evidence_is_review_only():
    from copy import deepcopy
    from overseas_costing.services.logistics_settlement.freight_lines import lines_for_source, matching_lines
    raw=monthly();second=deepcopy(raw['settlement_documents'][0]);second.update(id='copied',file_id='newfile');second['manifest']['sha256']='newbytes';raw['settlement_documents'].append(second)
    parsed=parse_source(raw,logistics_codes={'logistics'});lines=lines_for_source(parsed)
    assert all(r.get('ambiguous') for r in lines)
    logistics={'identifiers':[('waybill','1234567890'),('approval','202601010000000000001')]}
    bad={**lines[0],'approval_no':'202601010000000000002'}
    matched=matching_lines(logistics,[bad])
    assert matched and matched[0].get('identifier_conflict')


def test_total_fallback_never_labels_customs_or_lastmile_as_main_freight():
    from overseas_costing.services.logistics_settlement.freight_lines import lines_for_source
    for text in ('墨西哥末端派送费','进口清关费用','DHL双清包税'):
        parsed=parse_source(source('other',text=text,amount='300'),logistics_codes={'logistics'})
        assert all(line['scope']!='freight' for line in lines_for_source(parsed))


def test_summary_becoming_monthly_does_not_reuse_old_amount_index():
    from overseas_costing.services.logistics_settlement import freight_matching as m
    s,l,b,v,item,ls,e=setup_cost()
    raw=source('single',text='DHL 运单号1234567890',amount='9000');raw['title']='费用付款'
    first=s.ingest(parse_source(raw,logistics_codes={'logistics'}))
    assert m.current_lines(s,first)
    raw['title']='月结付款';raw['updated_at']='2026-09-10T00:00:00+00:00'
    new=s.ingest(parse_source(raw,logistics_codes={'logistics'}))
    assert first['snapshot']!=new['snapshot'] and not m.current_lines(s,new)


def test_new_history_never_confirms_source_links_automatically():
    from overseas_costing.services.logistics_settlement.jobs import start_job,run_step
    s,l,b,v,item,ls,e=setup_cost()
    raw=monthly();raw['raw_payload']['formComponentValues'].append({'name':'关联国际物流','componentType':'RelateField','value':[{'processInstanceId':'L'}]})
    class Archive:
        def page(self,**kwargs):return {'items':[raw],'has_more':False,'next_cursor':None}
    job=start_job(s,mode='incremental',actor='u')
    for _ in range(4):job=run_step(s,Archive(),job['id'],logistics_codes={'logistics'},freight_mode=True)
    assert job['failed_count']==0 and s.count('binding')==0 and s.count('freight_claim')==0
    assert m_candidates(s,ls['id'])


def m_candidates(store,source_id):
    from overseas_costing.services.logistics_settlement.freight_matching import candidates
    return candidates(store,source_id)


def test_multiline_cargo_preserves_full_sku_prefix():
    from overseas_costing.services.logistics_settlement.freight_packing import text_goods
    rows=text_goods('ABC101283ABC模具 steel mold Oppo\n TPU 1pcs\nABC201283\n模具 Oppo\n PC 1pcs\n手机壳样品 3pcs',{'document_id':'d'})
    assert [r['material_code'] for r in rows]==['ABC101283','ABC201283','']


def test_new_sku_cannot_inherit_price_fact_without_identity():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_packing as p
    from overseas_costing.services.shipment_cost_service import shipment_value
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    l.put('item',item['name'],{'material_code':'OLD100','extra_json':dumps({'logistics_row':{'purchase_fact':{'source_doc_no':'PO-OLD','unit_price':10,'purchase_currency':'RMB','unit_price_uom':'件'}}})})
    pr=p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])
    p.confirm(s,l,b['name'],v['name'],pr['id'],pr['revision'],[{'line_key':pr['goods'][0]['line_key'],'item_name':item['name']}],'u')
    assert shipment_value(l.get('item',item['name']))['error']=='SETTLEMENT_PURCHASE_MATERIAL_MISMATCH'


def test_edit_locked_source_refresh_remains_queued_until_adjustment():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_adoption as a,freight_runtime as r
    from datetime import datetime,timedelta
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'u');l.put('version',v['name'],{'status':'Confirmed'})
    l.put('batch',b['name'],{'edit_lock_token':'token','edit_lock_owner':'editor','edit_lock_expires_at':datetime.now()+timedelta(hours=1)})
    raw=monthly();raw['result']='refuse';s.ingest(parse_source(raw,logistics_codes={'logistics'}));a.source_updated(s,l,e['id']);r.resume(s,l)
    queued=[r for r in s.find('state') if r.get('kind')=='freight_refresh'];assert queued[0]['status']=='queued'
    l.put('batch',b['name'],{'edit_lock_token':None,'edit_lock_owner':None,'edit_lock_expires_at':None});r.resume(s,l)
    assert len(l.rows('version'))==2


def test_foreign_waybill_cargo_and_other_physical_edits_fence_packing():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_packing as p
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    pr=p.preview(s,l,b['name'],v['name'],c['id'],c['revision']);l.put('item',item['name'],{'chargeable_weight_kg':20})
    with pytest.raises(ValueError):p.confirm(s,l,b['name'],v['name'],pr['id'],pr['revision'],[{'line_key':pr['goods'][0]['line_key'],'item_name':item['name']}],'u')
    original=source('L','logistics',text='DHL运单号1234567890');original['business_id']='202601010000000000001';s.ingest(parse_source(original,logistics_codes={'logistics'}))
    raw=monthly();raw['settlement_documents'][0]['freight_tables'][0]['rows'][0]['fields']['运单号']='1234567891'
    s.ingest(parse_source(raw,logistics_codes={'logistics'}));c=m.rule_pass(s,ls['id'])[0]
    with pytest.raises(ValueError):p.preview(s,l,b['name'],v['name'],c['id'],c['revision'])


def test_changed_waybill_draft_cannot_use_previous_ticket_fee():
    from overseas_costing.services.logistics_settlement import freight_matching as m,freight_adoption as a
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'u');l.put('version',v['name'],{'status':'Confirmed'})
    raw=source('L','logistics',text='DHL运单号1234567891');s.ingest(parse_source(raw,logistics_codes={'logistics'}));a.source_updated(s,l,ls['id'])
    assert not a.context(s,l,b['name'])['available']
    assert a.blockers(s,l,b['name'],l.get('batch',b['name'])['current_version'],for_calculation=True)


def test_evidence_view_rejects_neighbor_bill_row_and_other_version():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_runtime as r
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    result=r.line_evidence(s,l,b['name'],v['name'],c['line_ids'][0])
    assert result['amount']=='2600' and result['evidence']['row']==2
    assert 'HONOR' not in dumps(result)
    assert not {'goods','fees','documents'} & set(result['source'])
    assert not {'goods','fees','documents'} & set(r.candidate_view(s,c)['expense'])
    other=next(row for row in m.current_lines(s,e) if row['id'] not in c['line_ids'])
    with pytest.raises(ValueError):r.line_evidence(s,l,b['name'],v['name'],other['id'])
    with pytest.raises(ValueError):r.line_evidence(s,l,b['name'],'unrelated',c['line_ids'][0])


def test_packing_pending_blocks_until_explicit_current_item_review():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a, freight_packing as p
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'tester')
    current=l.get('item',item['name']);meta=json.loads(current['extra_json']);meta['settlement_packing_review']=True
    l.put('item',item['name'],{'extra_json':dumps(meta)})
    assert any('装箱' in issue for issue in a.blockers(s,l,b['name'],v['name'],True))
    selection={'item_name':item['name'],'expected_item_hash':p.item_fingerprint([l.get('item',item['name'])])}
    l.put('item',item['name'],{'gross_weight_kg':11})
    with pytest.raises(ValueError):p.resolve_checks(s,l,b['name'],v['name'],[selection],'已核对','tester')
    selection['expected_item_hash']=p.item_fingerprint([l.get('item',item['name'])])
    p.resolve_checks(s,l,b['name'],v['name'],[selection],'已核对现有重量与体积','tester')
    assert not a.blockers(s,l,b['name'],v['name'],True)


def test_fee_application_recovery_preserves_packing_and_never_restores_estimates():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a
    from overseas_costing.services.logistics_settlement.freight_recovery import restore_fee_application
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    adopted=a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'tester')
    app=s.find('freight_application',batch=b['name'])[0]
    l.put('version',v['name'],{'status':'Confirmed'});l.put('batch',b['name'],{'confirm_status':'Confirmed'})
    restored=restore_fee_application(s,l,b['name'],v['name'],app['id'],adopted['revision'],'核对后撤回','tester')
    assert restored['version']!=v['name'] and l.get('version',v['name'])['status']=='Confirmed'
    assert l.rows('item',batch=b['name'],version=restored['version'])[0]['gross_weight_kg']==10
    ctx=a.context(s,l,b['name'],restored['version'])
    assert ctx['selected'] and not ctx['available'] and not ctx['claims']
    assert not s.find('freight_claim',batch=b['name'])
    assert all(not r.get('is_enabled') for r in l.rows('rule',batch=b['name'],version=restored['version']) if 'freight' in r['rule_code'])
    assert s.get('state','control')['enabled'] is False


def test_active_fee_recovery_can_readopt_same_lines_without_duplicate_application():
    from overseas_costing.services.logistics_settlement import freight_matching as m, freight_adoption as a
    from overseas_costing.services.logistics_settlement.freight_recovery import restore_fee_application
    s,l,b,v,item,ls,e=setup_cost();c=m.rule_pass(s,ls['id'])[0]
    first=a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'tester')
    app=s.find('freight_application',batch=b['name'])[0]
    restore_fee_application(s,l,b['name'],v['name'],app['id'],first['revision'],'先撤回再核对','tester')
    second=a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'tester')
    assert second['revision']!=first['revision']
    assert a.context(s,l,b['name'],v['name'])['available']
    assert a.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'tester')['cached']
    assert len(s.find('freight_application',batch=b['name']))==3


def test_archive_content_quality_contract_indexes_original_and_excludes_converted():
    from overseas_costing.services.logistics_settlement.freight_lines import lines_for_source
    raw=monthly();manifest=raw['settlement_documents'][0]['manifest'];manifest.pop('archive_quality')
    manifest['content_quality']='original'
    parsed=parse_source(raw,logistics_codes={'logistics'})
    assert len(lines_for_source(parsed))==2
    manifest['content_quality']='preview_only'
    assert lines_for_source(parse_source(raw,logistics_codes={'logistics'}))==[]
