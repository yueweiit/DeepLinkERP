import json
import pytest

from overseas_costing.tests.test_settlement_writer import setup
from overseas_costing.services.effective_logistics_source import load_source_bundle
from overseas_costing.services.logistics_settlement.model import dumps


def review_input(setup):
    s, l, batch, version, item, rule, binding = setup
    source = s.get('source', binding['expense_id'])
    source.update(goods=[], goods_complete=False)
    s.put('source', {'id':source['id'], 'data':dumps(source)})
    bundle = load_source_bundle(batch['name'], store=s, ledger=l)
    evidence = {'source_context':bundle['context'], 'source_id':'doc', 'source_kind':'approval_attachment',
                'source_hash':'a'*64, 'sheet':'完整货物清单', 'full_table':True, 'row_count':2}
    rows = [{'source_row':2,'material_code':'A','quantity':'4','unit':'件','gross_weight_kg':8,'volume_m3':2},
            {'source_row':3,'material_code':'B','quantity':'6','unit':'件','gross_weight_kg':9,'volume_m3':3}]
    return bundle, evidence, rows


def test_review_creates_final_cargo_atomically_and_repeated_request_is_noop(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo, resolve_reviewed_source
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    first=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    assert first['ok'] and first['changed_count']==2
    assert s.get('binding',binding['id'])['revision']==2
    current=l.rows('item',batch=b['name'],version=first['version'])
    assert sorted(json.loads(row['extra_json'])['settlement_cargo']['quantity'] for row in current)==['4','6']
    assert l.get('item',i['name'])['quantity']==2
    source=s.get('source',binding['expense_id'])
    assert source['goods']==[]
    effective=resolve_reviewed_source(s,source,s.get('binding',binding['id']))
    assert effective['review_id']==first['review_id'] and effective['goods_complete']
    before=[dict(row) for row in l.rows('item')]
    repeat=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    assert repeat['idempotent'] and s.get('binding',binding['id'])['revision']==2
    assert before==l.rows('item') and s.count('application')==1


def test_partial_and_unapproved_reviews_never_retire_or_report_zero_success(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    result=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,False,'u')
    assert not result['ok'] and result['candidate_only']
    assert l.get('item',i['name']) and s.get('binding',binding['id'])['revision']==1
    source=s.get('source',binding['expense_id']);source['approved']=False
    s.put('source',{'id':source['id'],'data':dumps(source)})
    with pytest.raises(ValueError):
        confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')


def test_review_stale_binding_and_rule_write_failure_roll_back_review(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    l.fail_rules=True
    with pytest.raises(RuntimeError):
        confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    assert s.get('binding',binding['id'])['revision']==1 and s.count('application')==0
    assert s.count('state')==2


def test_review_fee_decomposition_is_final_and_conserved_without_double_count(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    fees=[{'source_row':1,'label':'运费','amount':'70','currency':'RMB'}, {'source_row':2,'label':'操作费','amount':'30','currency':'RMB'}]
    result=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],None,evidence,False,'u',fees=fees)
    assert result['ok'] and result['fee_count']==2
    active=[x for x in l.rows('rule') if x.get('is_enabled')]
    assert len(active)==2 and all(x['is_final'] for x in active)
    assert sum(float(x['amount']) for x in active)==100


def test_fee_mismatch_and_negative_without_ack_cannot_write(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    for fees in [[{'source_row':1,'amount':'99','currency':'RMB'}],
                 [{'source_row':1,'amount':'110','currency':'RMB'},{'source_row':2,'amount':'-10','currency':'RMB'}]]:
        result=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],None,evidence,False,'u',fees=fees)
        assert not result['ok'] and not result.get('review_saved')
    assert s.get('binding',binding['id'])['revision']==1


def test_frozen_review_uses_immutable_id_and_duplicate_source_position_rejected(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo, resolve_reviewed_source
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    first=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    l.put('version',first['version'],{'status':'Confirmed'})
    bundle=load_source_bundle(b['name'],store=s,ledger=l)
    evidence['source_context']=bundle['context'];rows[0]['quantity']='5'
    second=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    assert second['version']!=first['version']
    historical=resolve_reviewed_source(s,s.get('source',binding['expense_id']),s.get('binding',binding['id']),first['version'])
    assert historical['review_id']==first['review_id'] and historical['goods'][0]['quantity']=='4'
    fresh=load_source_bundle(b['name'],store=s,ledger=l);evidence['source_context']=fresh['context']
    rows[1]['source_row']=2
    with pytest.raises(ValueError,match='唯一'):
        confirm_reviewed_cargo(s,l,b['name'],fresh['context'],rows,evidence,True,'u')


def test_cargo_preview_never_drops_unmatched_rows_and_incomplete_grid_stays_candidate():
    from overseas_costing.services.logistics_settlement.reviewed_cargo import cargo_review_for_preview
    trusted={'source_hash':'a'*64,'source':{'source_id':'A','sheet_name':'装箱表'},'grid':{'cells':[[1],[2],[3]]},
             'preview':{'material_rows':[{'source_row':2,'material_code':'SKU','quantity':4,'unit':'件'}], 'validation':{}}}
    review=cargo_review_for_preview(trusted,{'root_kind':'expense'})
    assert review['complete'] and review['rows'][0]['quantity']==4
    trusted['preview']['validation']['blocking']=[{'code':'unresolved_formula'}]
    review=cargo_review_for_preview(trusted,{'root_kind':'expense'})
    assert not review['complete'] and review['reason']


def test_current_source_resolves_reviewed_goods_and_retired_manifest_blocks_old_attachment(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    from overseas_costing.services.effective_logistics_source import attachment_allowed
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    current=load_source_bundle(b['name'],store=s,ledger=l)
    assert len(current['source']['goods'])==2
    current['source']['documents']=[{'id':'D','manifest':{'retired_at':'2026-09-10'}}]
    ctx=current['context']
    attachment={'source_type':'OA','version':ctx['cost_version'],'parse_result_json':dumps({
        'corp_id':ctx['corp_id'],'process_instance_id':ctx['instance_id'],
        'settlement_document':{'source_id':ctx['root_source_id'],'document_id':'D'}})}
    assert not attachment_allowed(attachment,current,for_analysis=True)


def test_signed_import_adopts_attachment_only_goods_through_shared_transaction(setup, monkeypatch):
    from overseas_costing.services import material_import_service as service, approval_link_service
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    monkeypatch.setattr(approval_link_service,'attach_preview_approval_links',lambda *a:None)
    class Repository:
        committed=0
        def get_context(self,*a): return {'batch':b['name'],'version':v['name'],'batch_modified':'BM','version_modified':'VM','source_context':bundle['context']}
        def get_items(self,*a): return []
        def assert_write(self,*a): pass
        def lock(self,*a): pass
        def rollback(self): pass
        def commit(self): self.committed+=1
        def adopt_reviewed_cargo(self,ctx,review,choices):
            return confirm_reviewed_cargo(s,l,b['name'],ctx['source_context'],review['rows'],review,choices['confirm_complete_cargo'],'u')
        def update_item(self,*a): pytest.fail('ordinary unmatched import must not run')
    repo=Repository()
    trusted={'source_hash':'a'*64,'source':{'source_id':'D','sheet_name':'装箱表','source_kind':'approval_attachment'},
             'grid':{'cells':[]},'preview':{'material_rows':rows,'validation':{}}}
    # No UI-supplied rows: resolver reparses the same server-owned table both times.
    monkeypatch.setattr(service,'_review_trusted_grid',lambda t,*a:t)
    monkeypatch.setattr(service,'_attach_source_grid',lambda *a:None)
    trusted['grid']['cells']=[[1],[2],[3]]
    resolver=lambda **kw:trusted
    preview=service.preview_material_import(b['name'],'approval_attachment','D','装箱表',repository=repo,resolver=resolver,signing_key=b'key')
    assert preview['cargo_review']['complete']
    missing=service.apply_material_import(b['name'],preview['preview_revision'],{},'EDIT','BM',repository=repo,resolver=resolver,signing_key=b'key')
    assert not missing['ok'] and s.get('binding',binding['id'])['revision']==1
    result=service.apply_material_import(b['name'],preview['preview_revision'],{'confirm_complete_cargo':True},'EDIT','BM',repository=repo,resolver=resolver,signing_key=b'key')
    assert result['ok'] and result['changed_count']==2 and repo.committed==1


def test_bound_fee_api_never_saves_nonfinal_rule_when_adoption_needs_review():
    from overseas_costing.services import fee_evidence_review_service as fee
    from overseas_costing.tests.test_fee_evidence_review_service import _ApplyRepository
    repo=_ApplyRepository()
    original=repo.get_context
    repo.get_context=lambda *a:{**original(*a),'effective_source':{'root_kind':'expense','approved':True,'available':True}}
    repo.adopt_reviewed_fees=lambda *a:({'ok':False,'candidate_only':True,'message':'合计不一致'}, {})
    repo.save_fee_split=lambda **kw:pytest.fail('ordinary fee bypassed current-source adoption')
    result=fee.apply_fee_evidence_review('B1','RUN-1',['evidence:classification','fee:import_tax'],{},'EDIT','m1',repository=repo)
    assert not result['ok'] and repo.saved_evidence is None and not repo.commits


def test_same_sku_without_native_identity_blocks_and_reorder_preserves_keys():
    from overseas_costing.services.logistics_settlement.reviewed_cargo import normalize_goods
    evidence={'source_id':'doc','sheet':'pack'}
    rows=[{'source_row':2,'material_code':'A','quantity':4,'unit':'件'}, {'source_row':3,'material_code':'B','quantity':6,'unit':'件'}]
    before=normalize_goods(rows,evidence)
    after=normalize_goods([{**rows[1],'source_row':2},{**rows[0],'source_row':3}],evidence)
    assert {r['material_code']:r['line_key'] for r in before}=={r['material_code']:r['line_key'] for r in after}
    with pytest.raises(ValueError,match='原生'):
        normalize_goods([rows[0],{**rows[0],'source_row':3}],evidence)


def test_bound_legacy_xls_preserves_cells_and_enforces_size(monkeypatch,tmp_path):
    import sys
    from types import SimpleNamespace
    from overseas_costing.services.packing_source_service import _read_archived_xls_grid
    sheet=SimpleNamespace(nrows=2,ncols=2,name='清单',merged_cells=[],cell_value=lambda r,c:[['SKU','数量'],['A',4]][r][c],cell_type=lambda r,c:1)
    book=SimpleNamespace(sheet_names=lambda:['清单'],sheet_by_name=lambda name:sheet,release_resources=lambda:None)
    monkeypatch.setitem(sys.modules,'xlrd',SimpleNamespace(open_workbook=lambda *a,**kw:book,XL_CELL_ERROR=5))
    path=tmp_path/'pack.xls';path.write_bytes(b'local')
    grid=_read_archived_xls_grid(path,'清单',max_rows=1000,max_columns=120)
    assert grid['cells'][1][1]['raw_value']==4
    with pytest.raises(ValueError,match='限制'):
        _read_archived_xls_grid(path,'清单',max_rows=1,max_columns=120)


def test_ai_complete_table_confirm_uses_shared_cargo_not_ordinary_create(setup,monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import material_ai_fill_service as ai, packing_source_service
    from overseas_costing.services.logistics_settlement.reviewed_cargo import cargo_review_for_preview
    from overseas_costing.services.logistics_settlement import store, ledger
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    trusted={'source_hash':'a'*64,'source':{'source_id':'D','sheet_name':'装箱表','source_kind':'approval_attachment'},
             'grid':{'cells':[[1],[2],[3]]},'preview':{'material_rows':rows,'validation':{}}}
    review=cargo_review_for_preview(trusted,bundle['context'])
    run=SimpleNamespace(name='RUN',draft_json=dumps({'cargo_review':review}),save=lambda **kw:None)
    monkeypatch.setattr(store.Store,'frappe',lambda:s)
    monkeypatch.setattr(ledger,'FrappeLedger',lambda:l)
    monkeypatch.setattr(packing_source_service,'resolve_trusted_packing_source',lambda **kw:trusted)
    monkeypatch.setattr(ai,'frappe',SimpleNamespace(db=SimpleNamespace(get_value=lambda *a:'m2',commit=lambda:None)))
    repo=ai.FrappeMaterialAIFillRepository()
    result=repo._apply_bound_source_review(run,[],[],{'batch':b['name'],'version':v['name'],'operator':'u',
        'input_fingerprint':'b'*64,'source_review':{'complete_cargo':True},'application_fingerprint':'APPLY'},bundle)
    assert result['ok'] and result['changed_count']==2 and run.status=='APPLIED'
    assert all(json.loads(item['extra_json'])['settlement_cargo'] for item in l.rows('item'))


def test_pending_same_review_can_add_coverage_without_second_revision_or_draft(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    src=s.get('source',binding['expense_id']);src['coverage']='unknown'
    s.put('source',{'id':src['id'],'data':dumps(src)})
    first=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    assert not first['ok'] and first['review_saved'] and first['version']==v['name']
    result=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u',coverage=['freight'])
    assert result['ok'] and result['idempotent'] and result['changed_count']==2
    assert s.get('binding',binding['id'])['revision']==2 and len(l.rows('version'))==1


def test_packing_review_preserves_current_expense_explicit_merchandise_price(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    source=s.get('source',binding['expense_id'])
    source['goods'][0]['merchandise_price']={'present':True,'price':'12','currency':'RMB','price_uom':'件','evidence':{'field':'商品单价'}}
    s.put('source',{'id':source['id'],'data':dumps(source)})
    bundle=load_source_bundle(b['name'],store=s,ledger=l)
    evidence={'source_context':bundle['context'],'source_id':'D','source_hash':'a'*64,'sheet':'装箱表','table_kind':'packing','full_table':True,'row_count':1}
    result=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],[{'source_row':2,'material_code':'A','quantity':6,'unit':'件'}],evidence,True,'u')
    assert result['ok']
    meta=json.loads(l.get('item',i['name'])['extra_json'])
    assert meta['settlement_cargo']['merchandise_price']['price']=='12'
    assert meta['settlement_valuation']['amount_rmb']=='72.000000'


def test_duplicate_native_keys_rejected_before_any_review_write(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    for row in rows: row['native_line_id']='DUP'
    with pytest.raises(ValueError,match='唯一'):
        confirm_reviewed_cargo(s,l,b['name'],bundle['context'],rows,evidence,True,'u')
    assert s.count('state')==2 and s.get('binding',binding['id'])['revision']==1


def test_reviewed_fees_clear_only_resolved_total_mismatch_and_keep_raw_issues(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo,resolve_reviewed_source
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    raw=s.get('source',binding['expense_id'])
    raw['issues']=['费用明细与总额未核对一致','商品币种待核对']
    s.put('source',{'id':raw['id'],'data':dumps(raw)})
    result=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],None,evidence,False,'u',fees=[{'source_row':1,'amount':100,'currency':'RMB'}])
    assert result['ok']
    source=s.get('source',binding['expense_id'])
    assert source['issues']==raw['issues']
    effective=resolve_reviewed_source(s,source,s.get('binding',binding['id']))
    assert effective['issues']==['商品币种待核对']


def test_bound_source_listing_never_opens_even_corrupt_workbooks(setup,monkeypatch):
    from overseas_costing.services import packing_snapshot_service as packing,effective_logistics_source as effective
    from types import SimpleNamespace
    s,l,b,v,i,r,binding=setup
    bundle=load_source_bundle(b['name'],store=s,ledger=l)
    bundle['source']['documents']=[{'id':'D','file_name':'bad.xlsx','status':'failed','issues':['BadZipFile']}]
    ctx=bundle['context']
    attachment={'name':'A','source_type':'OA','version':v['name'],'file_name':'bad.xlsx','file_url':'/private/files/bad.xlsx',
        'parse_result_json':dumps({'corp_id':ctx['corp_id'],'process_instance_id':ctx['instance_id'],
            'settlement_document':{'document_id':'D','source_id':ctx['root_source_id']}})}
    monkeypatch.setattr(effective,'current_source_bundle',lambda *a,**kw:bundle)
    monkeypatch.setattr(packing,'frappe',SimpleNamespace(get_list=lambda *a,**kw:[attachment]))
    monkeypatch.setattr(packing,'_attachment_sheet_names',lambda *a:pytest.fail('catalogue opened workbook'))
    result=packing.list_material_ai_sources(b['name'],v['name'])
    card=next(row for row in result if row.get('source_id')=='A')
    assert not card['available'] and card['exclude_reason']


def test_real_xlsx_sku_prefix_is_data_not_repeated_header(tmp_path):
    from openpyxl import Workbook
    from overseas_costing.utils.excel_workbook import read_packing_grid
    from overseas_costing.services.packing_parse_service import parse_packing_grid
    from overseas_costing.services.logistics_settlement.reviewed_cargo import cargo_review_for_preview
    path=tmp_path/'expense.xlsx';book=Workbook();sheet=book.active;sheet.title='装箱表'
    sheet.append(['物料编码','产品名称','数量','单位','毛重(kg)','体积(m3)'])
    sheet.append(['SKU-A','采购支出新名称',6,'件',12,3]);book.save(path);book.close()
    grid=read_packing_grid(path,sheet_name='装箱表',require_exact_sheet=True)
    preview=parse_packing_grid(grid)
    review=cargo_review_for_preview({'source_hash':'a'*64,'source':{'source_id':'D','sheet_name':'装箱表'},'grid':grid,'preview':preview},{'root_kind':'expense'})
    assert review['complete'] and review['rows'][0]['material_code']=='SKU-A' and review['rows'][0]['quantity']=='6'


def test_bound_ai_rejects_raw_purchase_fields_before_shared_adoption(setup,monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import material_ai_fill_service as ai
    s,l,b,v,i,r,binding=setup
    bundle,evidence,rows=review_input(setup)
    run=SimpleNamespace(name='RUN',draft_json='{}')
    with pytest.raises(ValueError,match='采购事实'):
        ai.FrappeMaterialAIFillRepository()._apply_bound_source_review(run,
            [{'proposal_type':'item_update','payload':{'item_name':i['name'],'fields':{'quantity':6}}}],[],
            {'batch':b['name'],'version':v['name'],'operator':'u','input_fingerprint':'a'*64,'source_review':{'complete_cargo':True}},bundle)
    assert l.get('item',i['name'])['quantity']==2 and s.get('binding',binding['id'])['revision']==1


@pytest.mark.parametrize('native',[False,True])
def test_review_price_inheritance_can_cross_document_line_namespace(setup,native):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import inherit_expense_prices,normalize_goods
    s,l,b,v,i,r,binding=setup
    source=s.get('source',binding['expense_id'])
    source['goods'][0]['merchandise_price']={'present':True,'price':'12','currency':'RMB','price_uom':'件'}
    row={'material_code':'A','quantity':6,'unit':'件','source_row':1,**({'native_line_id':'packing-row-1'} if native else {})}
    goods=inherit_expense_prices(normalize_goods([row],{'source_id':'packing','sheet':'表','table_kind':'packing'}),source)
    assert goods[0]['merchandise_price']['price']=='12'


def test_bound_wiki_refresh_is_explicit_and_local_cache_fences_root_and_sha(setup,monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import packing_source_service as packing,effective_logistics_source as effective
    s,l,b,v,i,r,binding=setup
    source=s.get('source',binding['expense_id']);source['raw']['wiki']={'workbookId':'W','sheetId':'S'}
    s.put('source',{'id':source['id'],'data':dumps(source)})
    bundle=load_source_bundle(b['name'],store=s,ledger=l)
    manifest={'id':'SN','corp_id':'C','content_sha256':'a'*64}
    payload={'schemaVersion':1,'workbookId':'W','sheetId':'S','sheetName':'装箱表','values':[['物料编码','数量','单位'],['SKU-A',6,'件']]}
    clients=SimpleNamespace(catalog=SimpleNamespace(get_latest_snapshot=lambda *a:manifest),archive=SimpleNamespace(download=lambda m:payload))
    assert packing.load_bound_wiki_snapshot(bundle['context'],'W:S',store=s) is None
    packing.refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients)
    cached=packing.load_bound_wiki_snapshot(bundle['context'],'W:S',store=s)
    assert cached['source_hash']=='a'*64 and cached['preview']['material_rows'][0]['quantity']=='6'
    manifest['content_sha256']='b'*64
    assert packing.load_bound_wiki_snapshot(bundle['context'],'W:S',store=s)['source_hash']=='a'*64
    packing.refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients)
    assert packing.load_bound_wiki_snapshot(bundle['context'],'W:S',store=s)['source_hash']=='b'*64
    assert packing.load_bound_wiki_snapshot({**bundle['context'],'source_snapshot':'NEW'},'W:S',store=s) is None
    manifest['corp_id']='OTHER'
    with pytest.raises(ValueError,match='本企业'):
        packing.refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients)


def test_complete_cargo_never_retires_unread_rows_after_first_total(tmp_path):
    from openpyxl import Workbook
    from overseas_costing.utils.excel_workbook import read_packing_grid
    from overseas_costing.services.packing_parse_service import parse_packing_grid
    from overseas_costing.services.logistics_settlement.reviewed_cargo import cargo_review_for_preview
    path=tmp_path/'partial.xlsx';book=Workbook();sheet=book.active;sheet.title='pack'
    for row in [['物料编码','数量','单位'],['SKU-A',6,'件'],['合计',6,''],['SKU-B',7,'件']]:sheet.append(row)
    book.save(path);book.close()
    grid=read_packing_grid(path,sheet_name='pack',require_exact_sheet=True)
    review=cargo_review_for_preview({'source_hash':'a'*64,'source':{'source_id':'D','sheet_name':'pack'},'grid':grid,'preview':parse_packing_grid(grid)},{'root_kind':'expense'})
    assert not review['complete'] and '未解析' in review['reason']


def test_ambiguous_expense_price_lines_cannot_fall_back_to_independent_purchase(setup):
    from overseas_costing.services.logistics_settlement.reviewed_cargo import confirm_reviewed_cargo
    s,l,b,v,i,r,binding=setup
    source=s.get('source',binding['expense_id'])
    first={**source['goods'][0],'merchandise_price':{'present':True,'price':'12','currency':'RMB','price_uom':'件'}}
    source['goods']=[first,{**first,'line_key':'SECOND','merchandise_price':{**first['merchandise_price'],'price':'13'}}]
    s.put('source',{'id':source['id'],'data':dumps(source)})
    ctx=load_source_bundle(b['name'],store=s,ledger=l)['context']
    evidence={'source_id':'packing','source_kind':'approval_attachment','source_context':ctx,'source_hash':'a'*64,
              'table_kind':'packing','full_table':True,'row_count':1}
    result=confirm_reviewed_cargo(s,l,b['name'],ctx,[{'source_row':1,'native_line_id':'packing-A','material_code':'A','quantity':6,'unit':'件'}],evidence,True,'u')
    assert result['application_status']=='applied_pending'
    meta=json.loads(l.get('item',i['name'])['extra_json'])
    assert meta['settlement_cargo']['merchandise_price']['ambiguous']
    assert meta['settlement_valuation']['error'] and meta['settlement_valuation']['amount_rmb'] is None
