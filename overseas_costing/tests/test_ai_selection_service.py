"""Server preview fences, idempotence and fee-only reuse without an AI call."""
from copy import deepcopy
import json
import pytest
from overseas_costing.services import material_ai_selection_service as service, material_ai_fill_service as ai
from overseas_costing.tests.test_material_ai_context_fingerprint import ContextRepository


class Repo(ContextRepository):
    def __init__(self):
        super().__init__()
        self.context['effective_source']={'root_kind':'logistics','fingerprint':'SOURCE','packing':{'root_kind':'logistics','source_snapshot':'S1','available':True},'freight':{'revision':'F1'}}
        self.items[0].update(gross_weight_kg=None,quantity=1,actual_shipped_qty=1,unit='件',shipped_uom='件')
        self.fees=[];self.sources=[{'source_id':'DOC','source_kind':'approval_form','source_hash':'HASH'}]
        self.rolled_back=False
        self.create_run({'batch':'B1','version':'V1','status':'READY','clarification_text':'','source_manifest_json':self.sources,
            'input_fingerprint':ai._source_review_fingerprint('B1','V1',self.items,self.sources,'',context=self.context),
            'draft_json':{'material_input_fingerprint':service.material_fingerprint(self.items,self.sources,self.context)},
            'candidates_json':[{'proposal_id':'P1','proposal_type':'item_update','target_item_name':'I1','default_selected':True,'payload':{'fields':{'gross_weight_kg':2}}}]})
    def list_sources(self,*args):return deepcopy(self.sources)
    def get_fees(self,*args):return deepcopy(self.fees)
    def lock_review_scope(self,*args):pass
    def lock_review_inputs(self,*args):pass
    def save_row_review_draft(self,run,draft):run['draft_json']=deepcopy(draft)
    def rollback(self):self.rolled_back=True;self.writes=[]
    def apply_row_selection(self,run,preview,draft,context):
        self.writes.append(deepcopy(preview))
        result={'ok':True,'preview_id':preview['id'],'version_name':'V1'}
        run.update(status='APPLIED',draft_json={**draft,'row_application':result})
        return result


def prepare(repo,ids=None,fees=None,mode='fill_missing'):
    catalog=service.review_catalog(repo,'B1',repo.run)
    ids=ids if ids is not None else [r['row_id'] for r in catalog['rows'] if r['default_selected']]
    return service.prepare('B1',repo.run['name'],ids,fees or [],mode,'V1',repository=repo)['preview']


def confirm(repo,preview):
    return service.confirm('B1',repo.run['name'],preview['id'],preview['revision'],'TOKEN','M1',repository=repo)


def test_only_server_preview_is_written_and_same_confirmation_reuses_result():
    repo=Repo();preview=prepare(repo)
    public=deepcopy(preview);public['rows'][0]['gross_weight_kg']=999
    confirm(repo,public);confirm(repo,public)
    assert len(repo.writes)==1 and repo.writes[0]['rows'][0]['gross_weight_kg']==2


def test_new_selection_supersedes_older_preview():
    repo=Repo();old=prepare(repo);prepare(repo,ids=[])
    with pytest.raises(ValueError,match='最新预览'):confirm(repo,old)
    assert not repo.writes


@pytest.mark.parametrize('change',['fee','item','source','note'])
def test_changes_after_preview_block_all_writes(change):
    repo=Repo();preview=prepare(repo)
    if change=='fee':repo.fees=[{'name':'F','logical_fee_key':'international_express_fee','amount':0,'is_active':1}]
    elif change=='item':repo.items[0]['gross_weight_kg']=0
    elif change=='source':repo.sources[0]['source_hash']='new'
    else:repo.context['clarification_revision']=1
    with pytest.raises(ValueError):confirm(repo,preview)
    assert not repo.writes


def test_fee_amendment_keeps_material_recognition_but_requires_new_selection_preview():
    repo=Repo();old=prepare(repo)
    repo.context['effective_source']['freight']['revision']='F2';repo.context['effective_source']['fingerprint']='SOURCE2'
    repo.context['version_modified']='VM2'
    catalog=service.review_catalog(repo,'B1',repo.run)
    assert catalog['rows'][0]['can_fill']
    with pytest.raises(ValueError,match='刷新预览'):confirm(repo,old)
    new=prepare(repo);assert new['id']!=old['id']
    assert confirm(repo,new)['ok']


def test_unknown_row_and_fee_ids_are_rejected():
    repo=Repo()
    for kwargs in ({'ids':['forged']},{'fees':['forged']}):
        with pytest.raises(ValueError,match='不属于'):prepare(repo,**kwargs)
    assert not repo.writes


def test_material_apply_failure_rolls_back_entire_selection():
    repo=Repo();preview=prepare(repo)
    def fail(*args):repo.writes.append('partial');raise RuntimeError('persist failure')
    repo.apply_row_selection=fail
    with pytest.raises(RuntimeError):confirm(repo,preview)
    assert repo.rolled_back and not repo.writes


def test_archived_dependency_change_blocks_preview_confirmation_even_with_same_manifest_hash():
    repo=Repo();archive={'hash':'first'}
    repo.capture_row_dependencies=lambda *args:[deepcopy(archive)]
    def validate(batch,snapshot,**kwargs):
        if snapshot!=[archive]:raise ValueError('来源内容已更新')
    repo.assert_row_dependencies=validate
    preview=prepare(repo);archive['hash']='second'
    with pytest.raises(ValueError,match='来源内容已更新'):confirm(repo,preview)
    assert not repo.writes


def test_run_dependency_baseline_blocks_reusing_analysis_after_document_changes():
    repo=Repo();repo.run['draft_json']['review_input']={'source_dependencies':[{'hash':'first'}]}
    def validate(*args,**kwargs):raise ValueError('来源内容已更新')
    repo.assert_row_dependencies=validate
    with pytest.raises(ValueError,match='来源内容已更新'):prepare(repo)


def test_legacy_fee_only_proposal_cannot_bypass_controlled_selection_preview():
    repo=ContextRepository();repo.supports_row_selection=True
    ai.start_source_ai_review('B1','V1',repository=repo,enqueue=lambda _:None)
    repo.run.update(status='READY',candidates_json=[{'proposal_id':'F1','proposal_type':'fee_update',
        'payload':{'logical_fee_key':'international_express_fee','amount':100,'currency':'RMB'}}])
    with pytest.raises(ValueError,match='预览'):
        ai.apply_source_ai_review('B1',repo.run['name'],['F1'],{},'TOKEN','M1',repository=repo)
    assert not repo.writes
