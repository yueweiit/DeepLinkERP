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
        self.create_run({'batch':'B1','version':'V1','status':'READY','proposal_version':1,'clarification_text':'','source_manifest_json':self.sources,
            'input_fingerprint':ai._source_review_fingerprint('B1','V1',self.items,self.sources,'',context=self.context),
            'draft_json':{'material_input_fingerprint':service.material_fingerprint(self.items,self.sources,self.context),
                          'row_review_policy':'ai-field-review-1'},
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


def prepare(repo,ids=None,fees=None,mode='fill_missing',packing_group_ids=None):
    catalog=service.review_catalog(repo,'B1',repo.run)
    ids=ids if ids is not None else [r['row_id'] for r in catalog['rows'] if r['default_selected']]
    return service.prepare('B1',repo.run['name'],ids,fees or [],mode,'V1',
                           packing_group_ids=packing_group_ids,repository=repo)['preview']


def confirm(repo,preview):
    return service.confirm('B1',repo.run['name'],preview['id'],preview['revision'],'TOKEN','M1',repository=repo)


def pending_adopted_scope(repo):
    repo.context['effective_source']={
        'root_kind':'expense','available':True,'approved':False,'invalid':False,
        'separate_adoption':True,'fingerprint':'PENDING-SCOPE',
        'packing':{'selected_source':{'id':'ADOPTED'},'available':True,'approved':False},
    }
    repo.run['input_fingerprint']=ai._source_review_fingerprint(
        'B1','V1',repo.items,repo.sources,'',context=repo.context)
    repo.run['draft_json']['material_input_fingerprint']=service.material_fingerprint(
        repo.items,repo.sources,repo.context)


def test_unselected_source_materialization_does_not_invalidate_review_fingerprints():
    context = {'batch': 'B1', 'version': 'V1', 'transport_mode': 'AIR'}
    items = [{'name': 'I1', 'material_code': 'SKU1'}]
    before = [
        {'source_id': 'SELECTED', 'source_kind': 'approval_form', 'source_hash': 'S1', 'selected': True},
        {'source_id': 'IGNORED', 'source_kind': 'approval_attachment', 'source_hash': 'OLD', 'selected': False},
    ]
    after = deepcopy(before)
    after[1]['source_hash'] = 'MATERIALIZED'

    assert ai._source_review_fingerprint('B1', 'V1', items, before, '', context=context) == (
        ai._source_review_fingerprint('B1', 'V1', items, after, '', context=context)
    )
    assert service.material_fingerprint(items, before, context) == (
        service.material_fingerprint(items, after, context)
    )


def test_pending_adopted_material_scope_can_reenter_review_prepare_and_confirm():
    repo=Repo();pending_adopted_scope(repo)

    catalog=service.review_catalog(repo,'B1',repo.run)
    row_ids=[row['row_id'] for row in catalog['rows'] if row['default_selected']]
    preview=service.prepare('B1',repo.run['name'],row_ids,[],'fill_missing','V1',repository=repo)['preview']

    assert confirm(repo,preview)['ok']
    assert len(repo.writes)==1


def test_confirmation_recomputes_preview_cleans_receipt_and_reuses_result():
    repo=Repo();preview=prepare(repo)
    public=deepcopy(preview);public['rows'][0]['gross_weight_kg']=999
    confirm(repo,public);confirm(repo,public)
    assert len(repo.writes)==1 and repo.writes[0]['rows'][0]['gross_weight_kg']==2
    assert 'row_previews' not in repo.run['draft_json']
    assert 'current_row_preview' not in repo.run['draft_json']


def test_public_catalog_and_compact_receipt_deeply_hide_purchase_evidence():
    repo=Repo()
    repo.items[0]['extra_json']=json.dumps({
        'logistics_row':{'identity':'LINE','purchase_fact':{'unit_price':12},
                         'purchase_fact_history':[{'purchase_fact':{'unit_price':10}}]},
        'settlement_original_values':{'name':'OLD-ITEM','goods_value':20},
        'ai_fill_original_values':{'name':'OLDER-ITEM','goods_value':10},
    })
    repo.run['input_fingerprint']=ai._source_review_fingerprint(
        'B1','V1',repo.items,repo.sources,'',context=repo.context)
    repo.run['draft_json']['material_input_fingerprint']=service.material_fingerprint(
        repo.items,repo.sources,repo.context)

    catalog=service.review_catalog(repo,'B1',repo.run)
    source_row=next(row for row in catalog['rows'] if row['origin']=='source')
    assert catalog['policy']=='ai-field-review-1'
    assert source_row['meaningful_field_count']==1
    assert '已默认选择' in source_row['default_selection_reason']
    selected=[row['row_id'] for row in catalog['rows'] if row['default_selected']]
    response=service.prepare('B1',repo.run['name'],selected,[],'update_selected','V1',repository=repo)

    for public_payload in (catalog,response['row_review'],response['preview']):
        serialized=json.dumps(public_payload,ensure_ascii=False)
        assert '_review_' not in serialized
        assert '_price_metadata' not in serialized
        assert '_verified_prior_item' not in serialized
        assert 'purchase_fact' not in serialized
        assert 'settlement_original_values' not in serialized
        assert 'ai_fill_original_values' not in serialized
        assert 'OLD-ITEM' not in serialized and 'OLDER-ITEM' not in serialized
    receipt=repo.run['draft_json']['row_previews'][response['preview']['id']]
    internal=json.dumps(receipt,ensure_ascii=False)
    assert 'purchase_fact' not in internal
    assert not ({'rows','changes','actual_sources','fees','sources'} & receipt.keys())
    assert 'packing_group_candidates' not in receipt
    assert 'merged_amount_groups' not in receipt
    assert receipt['selected_row_ids']==selected
    assert receipt['revision']==response['preview']['revision']


def test_field_choices_are_authenticated_without_persisting_business_values():
    repo = Repo()
    catalog = service.review_catalog(repo, 'B1', repo.run)
    candidate = next(row for row in catalog['field_candidates'] if row['default_selected'])
    choices = {f"{candidate['item_name']}:{candidate['fieldname']}": candidate['candidate_id']}

    response = service.prepare(
        'B1', repo.run['name'], [], [], 'update_selected', 'V1',
        field_choices=choices, repository=repo,
    )
    preview = response['preview']
    receipt = repo.run['draft_json']['row_previews'][preview['id']]

    assert preview['rows'][0]['gross_weight_kg'] == 2
    assert receipt['selected_field_choices'] == choices
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert 'suggested_value' not in serialized
    assert len(serialized) < 32_000
    assert confirm(repo, preview)['ok']
    assert repo.writes[0]['rows'][0]['gross_weight_kg'] == 2


def test_new_selection_supersedes_older_preview():
    repo=Repo();old=prepare(repo);prepare(repo,ids=[])
    assert old['id'] not in repo.run['draft_json']['row_previews']
    assert len(repo.run['draft_json']['row_previews'])==1
    with pytest.raises(ValueError,match='最新预览'):confirm(repo,old)
    assert not repo.writes


def test_legacy_full_preview_receipt_is_accepted_but_its_rows_are_not_trusted():
    repo=Repo();preview=prepare(repo)
    receipt=repo.run['draft_json']['row_previews'][preview['id']]
    receipt['rows']=deepcopy(preview['rows'])
    receipt['rows'][0]['gross_weight_kg']=999
    receipt['changes']=deepcopy(preview['changes'])
    receipt['actual_sources']=deepcopy(preview['actual_sources'])

    assert confirm(repo,preview)['ok']
    assert repo.writes[0]['rows'][0]['gross_weight_kg']==2


def test_large_private_projection_adds_only_a_bounded_receipt_and_can_confirm():
    repo=Repo()
    large_private='x'*(11*1024*1024)
    repo.run['draft_json']['large_analysis']=large_private
    repo.run['candidates_json']=[{
        'proposal_id':'P-LARGE','proposal_type':'logistics_reconcile','default_selected':True,
        'payload':{'rows':[{
            'name':'draft-large','material_code':'SKU1','product_name':'Large',
            'gross_weight_kg':2,'actual_shipped_qty':1,'unit':'件','_review_origin':'source',
            '_review_price_metadata':{'logistics_row':{'purchase_fact':large_private}},
        }]},
    }]
    before_size=len(json.dumps(repo.run['draft_json'],ensure_ascii=False))

    preview=prepare(repo,mode='update_selected')

    after_size=len(json.dumps(repo.run['draft_json'],ensure_ascii=False))
    receipt=repo.run['draft_json']['row_previews'][preview['id']]
    assert after_size-before_size < 128*1024
    assert not ({'rows','changes','actual_sources','fees','sources'} & receipt.keys())
    assert large_private not in json.dumps(receipt,ensure_ascii=False)
    assert confirm(repo,preview)['ok']


def test_packing_group_default_can_be_deselected_before_confirmation():
    repo=Repo()
    repo.items=[
        {**repo.items[0],'stable_line_key':'LINE-1','row_no':1},
        {'name':'I2','material_code':'SKU2','stable_line_key':'LINE-2','row_no':2,
         'quantity':1,'actual_shipped_qty':1,'unit':'件','shipped_uom':'件'},
    ]
    repo.run['input_fingerprint']=ai._source_review_fingerprint(
        'B1','V1',repo.items,repo.sources,'',context=repo.context)
    repo.run['draft_json']['material_input_fingerprint']=service.material_fingerprint(
        repo.items,repo.sources,repo.context)
    repo.run['draft_json']['packing_group_candidates']=[{
        'candidate_id':'GROUP-1','member_keys':['LINE-1','LINE-2'],
        'gross_weight_kg':'42.05','package_count':None,
        'default_selected':True,'can_apply':True,
        'evidence':[{'kind':'trusted_comment_text'}],
    }]

    selected=prepare(repo,ids=[],mode='update_selected')
    assert selected['selected_packing_group_ids']==['GROUP-1']
    assert selected['can_apply'] is True

    deselected=prepare(repo,ids=[],mode='update_selected',packing_group_ids=[])
    assert deselected['selected_packing_group_ids']==[]
    assert deselected['packing_group_candidates']==[]
    assert deselected['can_apply'] is False


def test_packing_group_selection_tolerates_unrelated_legacy_rows_without_stored_keys():
    repo=Repo()
    repo.items=[
        {**repo.items[0],'stable_line_key':'LINE-1','row_no':1},
        {'name':'I2','material_code':'SKU2','stable_line_key':'LINE-2','row_no':2,
         'quantity':1,'actual_shipped_qty':1,'unit':'件','shipped_uom':'件'},
        {'name':'LEGACY-3','material_code':'SKU3','stable_line_key':'','row_no':3,
         'quantity':1,'actual_shipped_qty':1,'unit':'件','shipped_uom':'件'},
    ]
    repo.run['input_fingerprint']=ai._source_review_fingerprint(
        'B1','V1',repo.items,repo.sources,'',context=repo.context)
    repo.run['draft_json']['material_input_fingerprint']=service.material_fingerprint(
        repo.items,repo.sources,repo.context)
    repo.run['draft_json']['packing_group_candidates']=[{
        'candidate_id':'GROUP-1','member_keys':['LINE-1','LINE-2'],
        'gross_weight_kg':'42.05','package_count':None,
        'default_selected':True,'can_apply':True,
        'evidence':[{'kind':'xlsx_merge'}],
    }]

    preview=prepare(repo,ids=[],mode='update_selected')

    assert preview['selected_packing_group_ids']==['GROUP-1']
    assert preview['packing_group_candidates'][0]['member_keys']==['LINE-1','LINE-2']


def test_preview_cleanup_shallow_copies_top_level_without_copying_large_nested_draft():
    payload='x'*1024
    large_analysis=[
        {'documents':[{'rows':[{'evidence':payload} for _ in range(32)]}]}
        for _ in range(352)
    ]
    assert len(json.dumps(large_analysis)) > 11*1024*1024
    draft={
        'large_analysis':large_analysis,
        'row_previews':{'P1':{'id':'P1'}},
        'current_row_preview':'P1',
    }

    cleaned=service._clean_preview_draft(draft)

    assert cleaned is not draft
    assert cleaned['large_analysis'] is large_analysis
    assert cleaned['large_analysis'][0]['documents'] is large_analysis[0]['documents']
    assert 'row_previews' not in cleaned and 'current_row_preview' not in cleaned
    cleaned['row_application']={'preview_id':'P1'}
    assert 'row_application' not in draft


def test_policy_upgrade_rejects_preview_created_by_previous_row_policy(monkeypatch):
    repo=Repo()
    preview=prepare(repo)
    monkeypatch.setattr(service.rows,'POLICY','ai-row-review-4')

    with pytest.raises(ValueError,match='(?:不属于|刷新预览|规则已升级)'):
        confirm(repo,preview)

    assert not repo.writes


def test_ready_draft_from_previous_review_policy_requires_reanalysis():
    repo=Repo()
    repo.run['draft_json']['row_review_policy']='ai-row-review-previous'

    with pytest.raises(ValueError,match='规则已升级'):
        service.review_catalog(repo,'B1',repo.run)


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


def test_ordinary_ai_selection_rejects_whole_table_replacement():
    repo = Repo()
    catalog = service.review_catalog(repo, 'B1', repo.run)
    selected = [row['row_id'] for row in catalog['rows'] if row['origin'] == 'source']

    with pytest.raises(ValueError, match='独立的整源采纳'):
        service.prepare('B1', repo.run['name'], selected, [], 'replace_all', 'V1', repository=repo)


def test_unrelated_unverified_merged_amount_group_does_not_block_physical_fill():
    repo = Repo()
    repo.run['draft_json']['merged_amount_groups'] = [{
        'source_id': 'OLD-WORKBOOK-SHEET',
        'sheet_name': '历史装箱单',
        'member_item_names': ['OTHER-ITEM'],
        'unit_price_range': 'Z2:Z7',
        'total_amount_range': 'AA2:AA7',
        'control_total': 60400,
        'computed_total': 59800,
        'status': 'needs_allocation',
    }]

    preview = prepare(repo)

    assert preview['merged_amount_blocking'] is False
    assert preview['can_apply'] is True
    assert not any(
        isinstance(reason, dict) and reason.get('code') == 'MERGED_AMOUNT_ALLOCATION_REQUIRED'
        for reason in preview['unresolved']
    )
    assert confirm(repo, preview)['ok'] is True
    assert len(repo.writes) == 1


def test_unverified_group_for_same_item_but_other_source_does_not_block_value_fill():
    repo = Repo()
    repo.run['candidates_json'] = [{
        'proposal_id': 'VALUE',
        'proposal_type': 'item_update',
        'target_item_name': 'I1',
        'default_selected': True,
        'source_refs': [{'source_id': 'CURRENT-SHEET', 'sheet_name': '本次清单'}],
        'payload': {'fields': {'shipment_value_rmb': '100'}},
    }]
    repo.run['draft_json']['merged_amount_groups'] = [{
        'source_id': 'OLD-SHEET',
        'sheet_name': '历史清单',
        'member_item_names': ['I1'],
        'status': 'needs_allocation',
    }]

    preview = prepare(repo)

    assert preview['merged_amount_blocking'] is False
    assert preview['can_apply'] is True


def test_relevant_unverified_merged_amount_group_blocks_confirmation_without_writing():
    repo = Repo()
    repo.items=[
        {**repo.items[0],'stable_line_key':'LINE-1','row_no':1},
        {'name':'I2','material_code':'SKU2','stable_line_key':'LINE-2','row_no':2,
         'quantity':1,'actual_shipped_qty':1,'unit':'件','shipped_uom':'件'},
    ]
    repo.run['input_fingerprint']=ai._source_review_fingerprint(
        'B1','V1',repo.items,repo.sources,'',context=repo.context)
    repo.run['draft_json']['material_input_fingerprint']=service.material_fingerprint(
        repo.items,repo.sources,repo.context)
    repo.run['candidates_json'] = [{
        'proposal_id': 'VALUE',
        'proposal_type': 'item_update',
        'target_item_name': 'I1',
        'default_selected': True,
        'source_refs': [{'source_id': 'PACKING-SHEET', 'sheet_name': '装箱单'}],
        'payload': {'fields': {'shipment_value_rmb': '100'}},
    }]
    repo.run['draft_json']['merged_amount_groups'] = [{
        'source_id': 'PACKING-SHEET',
        'sheet_name': '装箱单',
        'member_item_names': ['I1'],
        'unit_price_range': 'Z2:Z7',
        'total_amount_range': 'AA2:AA7',
        'control_total': 60400,
        'computed_total': 59800,
        'status': 'needs_allocation',
    }]
    repo.run['draft_json']['packing_group_candidates'] = [{
        'candidate_id': 'PACKING-GROUP',
        'member_keys': ['LINE-1', 'LINE-2'],
        'default_selected': True,
        'can_apply': True,
        'evidence': [{'kind': 'trusted_comment_text'}],
    }]

    preview = prepare(repo)

    assert preview['merged_amount_blocking'] is True
    assert preview['can_apply'] is False
    assert preview['blocking_merged_amount_groups'][0]['source_id'] == 'PACKING-SHEET'
    assert preview['unresolved'][0]['code'] == 'MERGED_AMOUNT_ALLOCATION_REQUIRED'
    with pytest.raises(ValueError, match='人工分摊'):
        confirm(repo, preview)
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


def test_prepare_reuses_successful_analysis_dependencies_without_recapturing_failed_optional_sources():
    repo = Repo()
    successful = [{"kind": "attachment", "attachment_id": "READY", "fingerprint": "SEALED"}]
    repo.run["draft_json"]["review_input"] = {"source_dependencies": deepcopy(successful)}
    checks = []
    repo.assert_row_dependencies = lambda batch, dependencies, **kwargs: checks.append(
        (deepcopy(dependencies), kwargs.get("lock", False))
    )
    repo.capture_row_dependencies = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("failed optional sources must not be recaptured")
    )

    preview = prepare(repo)

    assert checks
    assert all(dependencies == successful for dependencies, _locked in checks)
    assert any(locked for _dependencies, locked in checks)
    internal = repo.run["draft_json"]["row_previews"][preview["id"]]
    assert internal["dependencies"] == successful


def test_pending_source_confirmation_uses_estimate_dependency_check_only():
    repo=Repo();pending_adopted_scope(repo);checks=[]
    repo.capture_row_dependencies=lambda *args,**kwargs:[{'kind':'approval','source_id':'PENDING','fingerprint':'LOCKED'}]
    repo.assert_row_dependencies=lambda batch,dependencies,**kwargs:checks.append(kwargs.get('purpose','analysis'))
    repo.assert_adoption_dependencies=lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('审批中，仅供分析'))
    preview=prepare(repo)

    assert confirm(repo,preview)['ok']
    assert checks==['analysis','estimate']
    assert len(repo.writes)==1


def test_pending_source_estimated_fee_confirmation_uses_estimate_dependency_check():
    repo=Repo();pending_adopted_scope(repo)
    repo.run['candidates_json'].append({'proposal_id':'F1','proposal_type':'fee_update',
        'default_selected':True,'payload':{'logical_fee_key':'international_express_fee',
            'amount':'100','currency':'RMB','amount_status':'ESTIMATED'}})
    repo.capture_row_dependencies=lambda *args,**kwargs:[{'kind':'approval','source_id':'PENDING','fingerprint':'LOCKED'}]
    checks=[]
    repo.assert_row_dependencies=lambda batch,dependencies,**kwargs:checks.append(kwargs.get('purpose','analysis'))
    repo.assert_adoption_dependencies=lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('审批中，费用不能采用'))
    preview=prepare(repo,fees=['F1'])

    assert confirm(repo,preview)['ok']
    assert checks==['analysis','estimate']
    assert len(repo.writes)==1


def test_pending_source_actual_fee_confirmation_requires_final_adoption_check():
    repo=Repo();pending_adopted_scope(repo)
    repo.run['candidates_json'].append({'proposal_id':'F1','proposal_type':'fee_update',
        'default_selected':True,'payload':{'logical_fee_key':'international_express_fee',
            'amount':'100','currency':'RMB','amount_status':'ACTUAL'}})
    repo.capture_row_dependencies=lambda *args,**kwargs:[{'kind':'approval','source_id':'PENDING','fingerprint':'LOCKED'}]
    repo.assert_row_dependencies=lambda *args,**kwargs:None
    repo.assert_adoption_dependencies=lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('审批中，实际费用不能采用'))
    preview=prepare(repo,fees=['F1'])

    with pytest.raises(ValueError,match='审批中'):
        confirm(repo,preview)
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
