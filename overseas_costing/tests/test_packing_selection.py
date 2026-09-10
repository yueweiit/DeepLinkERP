import importlib
from copy import deepcopy
import pytest
from overseas_costing.tests.test_freight_lines import setup_cost, monthly
from overseas_costing.tests.test_logistics_settlement import source, table_row
from overseas_costing.services.logistics_settlement import freight_matching as matching, freight_adoption as adoption
from overseas_costing.services.logistics_settlement.model import parse_source, dumps
from overseas_costing.services.effective_logistics_source import load_source_bundle


def selection_service():
    assert importlib.util.find_spec('overseas_costing.services.logistics_settlement.packing_selection'), 'Whole-source selection service is required'
    return importlib.import_module('overseas_costing.services.logistics_settlement.packing_selection')


def test_monthly_source_preview_and_whole_replacement_keep_history_not_old_weight():
    p=selection_service();s,l,b,v,item,ls,e=setup_cost();matching.rule_pass(s,ls['id'])
    l.create('item',{'batch':b['name'],'version':v['name'],'material_code':'BB100','product_name':'HONOR','quantity':1,'unit':'件','gross_weight_kg':15,'manual_override_flag':1})
    l.put('batch',b['name'],{'item_count':2})
    catalog=p.list_sources(s,l,b['name'],v['name'])
    attachment=next(r for r in catalog['sources'] if r['source_kind']=='approval_attachment')
    assert attachment['row_count']==3
    pr=p.preview_selection(s,l,b['name'],v['name'],attachment['id'],attachment['revision'])
    assert pr['removed_count']==1 and not pr['complete']
    assert 'HONOR' not in dumps(pr['goods'])
    applied=p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'user',replace_all=True)
    assert applied['version']!=v['name'] and len(l.rows('item',version=v['name']))==2
    current=l.rows('item',version=applied['version']);assert len(current)==3
    assert l.get('batch',b['name'])['item_count']==3
    assert {r['material_code'] for r in current}=={'AA100','AA200',''}
    from overseas_costing.services.effective_source_values import project_source_values, physical_overlay_update
    assert all(r.get('gross_weight_kg') == 0 for r in current)
    assert all(project_source_values(r).get('gross_weight_kg') is None and project_source_values(r).get('volume_m3') is None for r in current)
    row=current[0]; ctx=project_source_values(row)['source_context']
    meta=physical_overlay_update(row,ctx,{'gross_weight_kg':0},evidence={'kind':'manual'})
    assert project_source_values({**row,'extra_json':meta})['gross_weight_kg']==0
    assert all('HONOR' not in r['product_name'] for r in current)
    bundle=load_source_bundle(b['name'],applied['version'],store=s,ledger=l)
    assert bundle['context']['packing']['selected_source']['source_kind']=='approval_attachment'
    assert 'HONOR' not in dumps(bundle['source'])
    assert len(l.rows('rule',version=applied['version']))==2
    again=p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'user',replace_all=True)
    assert again['cached'] and len(l.rows('version'))==2


def test_four_origins_are_separate_and_comment_does_not_inherit_other_sources():
    p=selection_service();s,l,b,v,item,ls,e=setup_cost()
    raw=source('L','logistics',text='DHL运单号1234567890')
    raw['raw_payload']['formComponentValues'].append({'name':'货物明细','componentType':'TableField','value':[table_row('body',quantity='2')]})
    raw['raw_payload']['comments']=[{'commentId':'comment1','text':'CC100 手机壳 4pcs','userName':'测试人'}, {'commentId':'foreign','text':'DHL运单号1234567891\nDD100 HONOR 1pcs'}]
    doc=deepcopy(monthly()['settlement_documents'][0]);doc['id']='commentdoc';doc['file_id']='commentfile';doc['manifest']['source_type']='comment_attachment'
    raw['settlement_documents']=[doc]
    ls=s.ingest(parse_source(raw,logistics_codes={'logistics'}));matching.rule_pass(s,ls['id'])
    rows=p.list_sources(s,l,b['name'],v['name'])['sources']
    assert {r['source_kind'] for r in rows}=={'approval_form','approval_attachment','approval_comment_attachment','approval_comment'}
    comment=next(r for r in rows if r.get('comment_id')=='comment1')
    pr=p.preview_selection(s,l,b['name'],v['name'],comment['id'],comment['revision'])
    assert len(pr['goods'])==1 and pr['goods'][0]['material_code']=='CC100'
    assert not next(r for r in rows if r.get('comment_id')=='foreign')['can_adopt']


def test_stale_or_empty_source_cannot_clear_materials():
    p=selection_service();s,l,b,v,item,ls,e=setup_cost();matching.rule_pass(s,ls['id'])
    rows=p.list_sources(s,l,b['name'],v['name'])['sources']
    empty=next(r for r in rows if r['source_kind']=='approval_form' and r['source_id']==e['id'])
    assert not empty['can_adopt']
    pr=p.preview_selection(s,l,b['name'],v['name'],empty['id'],empty['revision'])
    with pytest.raises(ValueError):p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'u',replace_all=True)
    chosen=next(r for r in rows if r['row_count'])
    pr=p.preview_selection(s,l,b['name'],v['name'],chosen['id'],chosen['revision'])
    l.put('item',item['name'],{'quantity':7})
    with pytest.raises(ValueError):p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'u',replace_all=True)
    assert len(l.rows('version'))==1


def test_fee_only_keeps_packing_and_whole_packing_preserves_claims():
    p=selection_service();s,l,b,v,item,ls,e=setup_cost();c=matching.rule_pass(s,ls['id'])[0]
    adopted=adoption.confirm(s,l,b['name'],v['name'],c['id'],c['revision'],c['line_ids'],'u')
    rows=p.list_sources(s,l,b['name'],v['name'])['sources']; chosen=next(r for r in rows if r['row_count'])
    pr=p.preview_selection(s,l,b['name'],v['name'],chosen['id'],chosen['revision'])
    applied=p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'u',replace_all=True)
    assert adoption.context(s,l,b['name'],applied['version'])['claims']==adopted['claims']


def test_attachment_fallback_rejects_conflicting_waybill_and_approval_identifiers():
    p=selection_service();s,l,b,v,item,ls,e=setup_cost()
    raw=source('L','logistics',text='DHL运单号1234567890')
    raw['business_id']='202601010000000000001'
    fields={'运单号':'1234567890','钉钉流程':'202601010000000000999',
            '物料编码':'FOREIGN100','物品名称':'其他票货物','数量':'4','单位':'件'}
    raw['settlement_documents']=[{'id':'conflicting-packing','file_id':'conflicting-file','file_name':'packing.xlsx',
        'manifest':{'archive_quality':'original'},'tables':[{'title':'Sheet1','kind':'packing',
        'rows':[{'position':1,'rowValue':[{'name':key,'value':value} for key,value in fields.items()]}]}]}]
    s.ingest(parse_source(raw,logistics_codes={'logistics'}))
    chosen=next(row for row in p.list_sources(s,l,b['name'],v['name'])['sources'] if row.get('document_id')=='conflicting-packing')
    assert not chosen['can_adopt']
    pr=p.preview_selection(s,l,b['name'],v['name'],chosen['id'],chosen['revision'])
    with pytest.raises(ValueError):
        p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'u',replace_all=True)
    assert len(l.rows('version'))==1 and l.get('item',item['name'])['material_code']=='AA100'


def test_missing_quantity_source_row_is_not_silently_dropped_by_whole_replacement():
    p=selection_service();s,l,b,v,item,ls,e=setup_cost()
    second=l.create('item',{'batch':b['name'],'version':v['name'],'material_code':'BB100','product_name':'待核对物料','quantity':1,'unit':'件'})
    raw=source('L','logistics',text='DHL运单号1234567890')
    raw['raw_payload']['formComponentValues'].append({'name':'货物明细','componentType':'TableField','value':[
        table_row('valid',code='AA100',quantity='2'),table_row('missing-quantity',code='BB100',quantity='')]})
    s.ingest(parse_source(raw,logistics_codes={'logistics'}))
    chosen=next(row for row in p.list_sources(s,l,b['name'],v['name'])['sources'] if row['source_kind']=='approval_form')
    assert chosen['can_adopt'] and not chosen['complete']
    assert any('数量' in issue for issue in chosen['issues'])
    pr=p.preview_selection(s,l,b['name'],v['name'],chosen['id'],chosen['revision'])
    assert len(pr['goods'])==2
    applied=p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'u',replace_all=True)
    current=l.rows('item',batch=b['name'],version=applied['version'])
    assert len(current)==2 and {row['material_code'] for row in current}=={'AA100','BB100'}
    from overseas_costing.services.effective_source_values import project_source_values
    pending=project_source_values(next(row for row in current if row['material_code']=='BB100'))
    assert pending['quantity'] is None and pending['actual_shipped_qty'] is None
    assert l.get('item',second['name'])['quantity']==1


def test_repeated_native_source_id_keeps_distinct_rows_with_different_quantities():
    p=selection_service();s,l,b,v,item,ls,e=setup_cost()
    raw=source('L','logistics',text='DHL运单号1234567890')
    raw['raw_payload']['formComponentValues'].append({'name':'货物明细','componentType':'TableField','value':[
        table_row('duplicate-id',code='AA100',quantity='2'),table_row('duplicate-id',code='AA100',quantity='3')]})
    s.ingest(parse_source(raw,logistics_codes={'logistics'}))
    chosen=next(row for row in p.list_sources(s,l,b['name'],v['name'])['sources'] if row['source_kind']=='approval_form')
    pr=p.preview_selection(s,l,b['name'],v['name'],chosen['id'],chosen['revision'])
    assert len(pr['goods'])==2 and len({row['line_key'] for row in pr['goods']})==2
    applied=p.confirm_selection(s,l,b['name'],v['name'],pr['id'],pr['revision'],'u',replace_all=True)
    current=l.rows('item',batch=b['name'],version=applied['version'])
    assert sorted(row['quantity'] for row in current)==['2','3']
