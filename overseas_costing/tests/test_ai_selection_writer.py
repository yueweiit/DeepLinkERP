from copy import deepcopy
from overseas_costing.tests.test_freight_lines import setup_cost
from overseas_costing.services import material_ai_row_selection as rows
from overseas_costing.services.material_ai_selection_writer import write_rows
from overseas_costing.services.effective_logistics_source import load_source_bundle
from overseas_costing.services.logistics_settlement.model import dumps


def selection(items,ctx,version,batch,mode='replace_all'):
    row={'name':'draft-A','material_code':'AA100','product_name':'Oppo','actual_shipped_qty':'2','unit':'件','_review_origin':'source'}
    proposal={'proposal_id':'P','proposal_type':'logistics_reconcile','default_selected':True,'payload':{'rows':[row]}}
    cat=rows.catalog(items,[proposal],[],ctx,run_id='R')
    plan=rows.project(items,cat,[cat['rows'][0]['row_id']],[],mode)
    return {**plan,'id':'preview','revision':'revision','batch':batch,'version':version,'run_id':'R','source_context':ctx,'sources':[]}


def test_replace_keeps_old_table_and_invalidates_directed_costs_without_reassigning():
    store,ledger,b,v,i,ls,e=setup_cost()
    removed=ledger.create('item',{'batch':b['name'],'version':v['name'],'material_code':'BB100','product_name':'other','unit':'件','quantity':1})
    ledger.create('component',{'batch':b['name'],'version':v['name'],'item':removed['name'],'amount':20,'is_active':1})
    old=ledger.rows('item',batch=b['name'],version=v['name']);ctx=load_source_bundle(b['name'],v['name'],store=store,ledger=ledger)['context']
    p=selection(old,ctx,v['name'],b['name']);new=write_rows(store,ledger,p,ctx)
    assert new!=v['name'] and ledger.rows('item',batch=b['name'],version=v['name'])==old
    current=ledger.rows('item',batch=b['name'],version=new)
    assert len(current)==1 and current[0]['gross_weight_kg']==0
    assert 'gross_weight_kg' in current[0]['extra_json']
    component=ledger.rows('component',version=new)[0]
    assert not component['is_active'] and not component['item']
    assert len(ledger.rows('rule',version=new))==2
    bundle=load_source_bundle(b['name'],new,store=store,ledger=ledger)
    assert len(bundle['source']['goods'])==1 and 'other' not in dumps(bundle['source']['goods'])
    assert bundle['context']['packing']['selected_source']['row_ids']==p['selected_row_ids']


def test_fill_retains_unselected_existing_rows_byte_for_byte():
    store,ledger,b,v,i,ls,e=setup_cost()
    before=deepcopy(ledger.get('item',i['name']))
    rows0=ledger.rows('item',version=v['name']);ctx=load_source_bundle(b['name'],v['name'],store=store,ledger=ledger)['context']
    p=selection(rows0,ctx,v['name'],b['name'],'fill_missing')
    # Existing row only lacks actual quantity; its real weight and volume must survive.
    new=write_rows(store,ledger,p,ctx)
    assert new==v['name']
    current=ledger.get('item',i['name'])
    assert current['gross_weight_kg']==before['gross_weight_kg'] and current['volume_m3']==before['volume_m3']


def test_frozen_version_write_is_rejected():
    import pytest
    store,ledger,b,v,i,ls,e=setup_cost();ctx=load_source_bundle(b['name'],v['name'],store=store,ledger=ledger)['context']
    p=selection(ledger.rows('item',version=v['name']),ctx,v['name'],b['name'])
    ledger.put('version',v['name'],{'status':'Confirmed'})
    with pytest.raises(ValueError,match='冻结'):write_rows(store,ledger,p,ctx)
