import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from overseas_costing.tests.test_settlement_writer import setup
from overseas_costing.services.effective_logistics_source import load_source_bundle
from overseas_costing.services.logistics_settlement.model import dumps


def wiki_fixture(setup,sheets=('W:S',)):
    store,ledger,batch,version,item,rule,binding=setup
    source=store.get('source',binding['expense_id'])
    source['raw']['wiki']=[{'workbookId':s.partition(':')[0],'sheetId':s.partition(':')[2]} for s in sheets]
    store.put('source',{'id':source['id'],'data':dumps(source)})
    return load_source_bundle(batch['name'],store=store,ledger=ledger)


def clients(sha='a',quantity=4,download=None):
    manifest={'id':'SN-'+sha,'corp_id':'C','content_sha256':sha*64}
    payload={'schemaVersion':1,'workbookId':'W','sheetId':'S','sheetName':'pack',
             'values':[['物料编码','数量','单位','毛重','体积'],['A',quantity,'件',8,2]],'mergeRangesAvailable':True}
    return SimpleNamespace(catalog=SimpleNamespace(get_latest_snapshot=lambda *a:manifest),
                           archive=SimpleNamespace(download=download or (lambda m:payload)))


def test_refresh_cas_does_not_allow_delayed_old_worker_to_overwrite_new_cache(setup):
    from overseas_costing.services.packing_source_service import refresh_bound_wiki_snapshot,load_bound_wiki_snapshot
    s,l,b,v,*_=setup
    ctx=wiki_fixture(setup)['context']
    newer=clients('b',6)
    def delayed_old(_manifest):
        refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=newer)
        return clients('a',4).archive.download({})
    with pytest.raises(ValueError,match='刷新'):
        refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients('a',download=delayed_old))
    cached=load_bound_wiki_snapshot(ctx,'W:S',store=s)
    assert cached['source_hash']=='b'*64 and cached['preview']['material_rows'][0]['quantity']=='6'


def test_changed_cache_invalidates_context_but_identical_refresh_is_noop(setup):
    from overseas_costing.services.packing_source_service import refresh_bound_wiki_snapshot
    from overseas_costing.services.logistics_settlement.bound_wiki_service import pending_wiki_issues
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    from overseas_costing.services.effective_source_values import project_source_values
    s,l,b,v,item,rule,binding=setup
    wiki_fixture(setup)
    refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients())
    apply_binding(s,l,binding['id'],'u')
    prior=load_source_bundle(b['name'],store=s,ledger=l)['context']
    old=l.get('item',item['name']);meta=json.loads(old['extra_json'])
    meta['settlement_physical']={'source_context_fingerprint':prior['fingerprint'],'values':{'gross_weight_kg':8}}
    l.put('item',item['name'],{'extra_json':dumps(meta)})
    refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients())
    assert s.get('binding',binding['id'])['revision']==1
    changed=refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients('b',6))
    current=load_source_bundle(b['name'],store=s,ledger=l)['context']
    assert changed['changed'] and current['binding_revision']==2 and prior['fingerprint']!=current['fingerprint']
    assert pending_wiki_issues(s,s.get('binding',binding['id']))
    assert project_source_values(l.get('item',item['name']),current)['gross_weight_kg'] is None
    assert l.get('item',item['name'])['gross_weight_kg']==4
    assert l.get('batch',b['name'])['status']=='Dirty'


def test_round_robin_advances_past_failure_and_rotates_sheets(setup):
    from overseas_costing.services.logistics_settlement.bound_wiki_service import refresh_bound_wiki_round
    s,l,b,v,*_=setup
    wiki_fixture(setup,('W:A','W:B','W:C'))
    calls=[]
    def refresh(batch,sheet,**kwargs):
        calls.append(sheet)
        if sheet=='W:A': raise RuntimeError('temporary archive failure')
        return {'ok':True,'changed':False}
    first=refresh_bound_wiki_round(s,l,refresh=refresh,limit=1)
    second=refresh_bound_wiki_round(s,l,refresh=refresh,limit=1)
    third=refresh_bound_wiki_round(s,l,refresh=refresh,limit=1)
    assert calls==['W:A','W:B','W:C'] and first['failed']==1 and second['checked']==third['checked']==1
    refresh_bound_wiki_round(s,l,refresh=refresh,limit=1)
    refresh_bound_wiki_round(s,l,refresh=refresh,limit=1)
    assert calls[-1]=='W:A'


def test_fresh_review_clears_only_matching_pending_wiki_and_old_review_stays_historical(setup):
    from overseas_costing.services.packing_source_service import refresh_bound_wiki_snapshot,load_bound_wiki_snapshot
    from overseas_costing.services.logistics_settlement.reviewed_cargo import cargo_review_for_preview,confirm_reviewed_cargo,resolve_reviewed_source
    from overseas_costing.services.logistics_settlement.bound_wiki_service import pending_wiki_issues
    s,l,b,v,item,rule,binding=setup
    wiki_fixture(setup)
    def preview():
        bundle=load_source_bundle(b['name'],store=s,ledger=l);context=bundle['context']
        trusted=load_bound_wiki_snapshot(context,'W:S',store=s)
        trusted['source_hash']=hashlib.sha256(f"{trusted['source_hash']}|{context['fingerprint']}".encode()).hexdigest()
        return bundle,cargo_review_for_preview(trusted,context)
    refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients())
    bundle,review=preview()
    first=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],review['rows'],review,True,'u')
    l.put('version',v['name'],{'status':'Confirmed'})
    refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients('b',6))
    binding=s.get('binding',binding['id'])
    assert pending_wiki_issues(s,binding)
    assert not resolve_reviewed_source(s,s.get('source',binding['expense_id']),binding).get('review_id')
    old=resolve_reviewed_source(s,s.get('source',binding['expense_id']),binding,v['name'])
    assert old['review_id']==first['review_id'] and old['goods'][0]['quantity']=='4'
    bundle,review=preview()
    result=confirm_reviewed_cargo(s,l,b['name'],bundle['context'],review['rows'],review,True,'u')
    assert result['ok'] and result['version']!=v['name']
    assert not pending_wiki_issues(s,s.get('binding',binding['id']))
    assert l.get('version',v['name'])['status']=='Confirmed'


def test_automatic_reapply_of_changed_wiki_creates_one_draft_and_cannot_revive_old_adoption(setup):
    from overseas_costing.services.packing_source_service import refresh_bound_wiki_snapshot
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    s,l,b,v,item,rule,binding=setup
    wiki_fixture(setup)
    refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients())
    apply_binding(s,l,binding['id'],'u')
    before=copy.deepcopy(l.get('item',item['name']))
    l.put('version',v['name'],{'status':'Confirmed'})
    refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients('b',6))
    first=apply_binding(s,l,binding['id'],'pending-sync')
    second=apply_binding(s,l,binding['id'],'pending-sync')
    assert first['application_status']==second['application_status']=='pending'
    assert len(l.rows('version'))==2 and l.get('item',item['name'])==before
    current=l.get('batch',b['name'])['current_version']
    for row in l.rows('item',batch=b['name'],version=current):
        assert not json.loads(row['extra_json']).get('settlement_physical')


def test_round_pause_keeps_cursor_before_unread_sheet(setup):
    from overseas_costing.services.logistics_settlement.bound_wiki_service import refresh_bound_wiki_round
    s,l,b,v,*_=setup
    wiki_fixture(setup,('W:A','W:B'))
    s.put('state',{'id':'control','updated_at':'','data':dumps({'enabled':False})})
    calls=[]
    paused=refresh_bound_wiki_round(s,l,refresh=lambda *a,**k:calls.append(a[1]) or {},limit=1)
    assert paused['paused'] and not calls
    s.put('state',{'id':'control','updated_at':'','data':dumps({'enabled':True})})
    refresh_bound_wiki_round(s,l,refresh=lambda *a,**k:calls.append(a[1]) or {},limit=1)
    assert calls==['W:A']


def test_bound_xls_path_does_not_enter_xlsx_only_parser(setup,monkeypatch,tmp_path):
    from overseas_costing.services import packing_source_service as packing,attachment_parse_service
    s,l,b,v,*_=setup
    bundle=wiki_fixture(setup)
    bundle['source']['documents']=[{'id':'D'}]
    context=bundle['context']
    row={'source_type':'OA','version':v['name'],'file_name':'pack.xls','file_url':'/private/files/pack.xls',
         'parse_result_json':dumps({'corp_id':context['corp_id'],'process_instance_id':context['instance_id'],
             'settlement_document':{'document_id':'D','source_id':context['root_source_id']}})}
    path=tmp_path/'pack.xls';path.write_bytes(b'local')
    monkeypatch.setattr(attachment_parse_service,'_resolve_source_file_path',lambda **kw:path)
    monkeypatch.setattr(packing.import_service,'_resolve_excel_file_path',lambda **kw:pytest.fail('legacy xlsx resolver'))
    assert packing.resolve_packing_attachment_path(row,bundle)==path
    with pytest.raises(ValueError,match='当前'):
        packing.resolve_packing_attachment_path({**row,'version':'OLD'},bundle)


def test_failed_wiki_refresh_is_visible_in_local_catalogue_without_changing_content_hash(setup,monkeypatch):
    from overseas_costing.services import packing_source_service as packing,packing_snapshot_service as catalog
    from overseas_costing.services.logistics_settlement.bound_wiki_service import refresh_bound_wiki_round
    from overseas_costing.services.logistics_settlement.store import Store
    s,l,b,v,*_=setup
    bundle=wiki_fixture(setup)
    monkeypatch.setattr(Store,'frappe',classmethod(lambda cls:s))
    monkeypatch.setattr(catalog,'frappe',SimpleNamespace(get_list=lambda *a,**k:[]))
    packing.refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients())
    first=next(row for row in catalog._bound_material_sources(b['name'],bundle) if row['source_kind']=='wiki_sheet')
    assert first['cache_refreshed_at'] and first['refresh_last_success_at']
    assert first['approval_no']==bundle['source']['approval_no']
    def failed(*a,**k): raise RuntimeError('archive temporarily unavailable')
    refresh_bound_wiki_round(s,l,refresh=failed)
    failed_row=next(row for row in catalog._bound_material_sources(b['name'],bundle) if row['source_kind']=='wiki_sheet')
    assert failed_row['refresh_error']=='archive temporarily unavailable'
    assert failed_row['refresh_last_success_at']==first['refresh_last_success_at']
    assert failed_row['available'] and failed_row['source_hash']==first['source_hash']
    assert failed_row['refresh_last_checked_at']
    packing.refresh_bound_wiki_snapshot(b['name'],'W:S',store=s,ledger=l,clients=clients())
    assert packing.wiki_refresh_status(bundle['context'],'W:S',store=s)['refresh_error']==''
    other={**bundle['context'],'source_snapshot':'new-snapshot'}
    assert not any(packing.wiki_refresh_status(other,'W:S',store=s).values())
