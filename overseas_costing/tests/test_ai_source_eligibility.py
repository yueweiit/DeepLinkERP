"""Active DingTalk archives stay usable while invalid decisions remain excluded."""
from copy import deepcopy
import json

import pytest

from overseas_costing.services import material_ai_source_dependencies as deps
from overseas_costing.services.logistics_settlement.model import dumps
from overseas_costing.services.source_review_manifest_service import prepare_source_manifest, source_progress_manifest
from overseas_costing.tests.test_settlement_writer import setup as settlement_fixture


def pending_archive(kind='expense'):
    store, ledger, batch, *_ = settlement_fixture.__wrapped__()
    source = store.find('source', instance='E')[0]
    source.update(kind=kind, status='RUNNING', approval_result='agree', approved=False,
                  approval_no='202604300126000526723')
    store.put('source', {'id': source['id'], 'kind':kind, 'data': dumps(source)})
    return store, ledger, batch, source


@pytest.mark.parametrize('kind', ['expense', 'logistics', 'unclassified'])
@pytest.mark.parametrize('source_kind', ['approval_form', 'approval_comment', 'approval_attachment', 'approval_comment_attachment'])
def test_pending_archives_allow_final_fees_without_becoming_approved(kind, source_kind):
    store, ledger, batch, source = pending_archive(kind)
    raw = {'source_id': 'S', 'process_instance_id': 'E', 'source_kind': source_kind,
           'source_label': '关联采购资料', 'available': True, 'approval_role': 'purchase'}
    if 'attachment' in source_kind:
        attachment = ledger.create('attachment', {'batch': batch['name'], 'file_url': '/private/files/a.txt'})
        raw['source_id'] = attachment['name']
    sources = deps.annotate_source_eligibility([raw], store=store, ledger=ledger, batch_name=batch['name'])
    assert sources[0]['analysis_allowed'] and sources[0]['adoption_allowed']
    assert sources[0]['final_fee_allowed'] is True
    assert sources[0]['adoption_restriction'] == ''
    assert source['approved'] is False
    manifest = prepare_source_manifest(sources)
    assert manifest[0]['selected'] and source_progress_manifest(manifest)[0]['analysis_allowed']
    baseline = deps.capture_dependencies(manifest, store=store, ledger=ledger,
        batch_name=batch['name'], source_context={}, purpose='analysis')
    assert not deps.dependency_issues({'dependencies': baseline}, store=store, ledger=ledger,
        batch_name=batch['name'], purpose='analysis')
    assert not deps.dependency_issues(
        {'dependencies': baseline}, store=store, ledger=ledger, batch_name=batch['name'])
    source['raw']['comments'] = [{'text': 'Changed'}]
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    assert deps.dependency_issues({'dependencies': baseline}, store=store, ledger=ledger,
        batch_name=batch['name'], purpose='analysis')


@pytest.mark.parametrize('state,result', [
    ('REJECTED', 'agree'),
    ('REFUSED', 'agree'),
    ('DENIED', 'agree'),
    ('TERMINATED', 'agree'),
    ('CANCELED', 'agree'),
    ('CANCELLED', 'agree'),
    ('WITHDRAWN', 'agree'),
    ('WITHDRAW', 'agree'),
    ('REVOKED', 'agree'),
    ('ABORTED', 'agree'),
    ('DELETED', 'agree'),
    ('COMPLETED', 'refuse'),
    ('RUNNING', 'refuse'),
    ('RUNNING', 'refused'),
    ('RUNNING', 'reject'),
    ('RUNNING', 'rejected'),
    ('RUNNING', 'deny'),
    ('RUNNING', 'denied'),
    ('RUNNING', 'disagree'),
    ('已撤销', 'agree'),
    ('已拒绝', 'agree'),
    ('已终止', 'agree'),
    ('已取消', 'agree'),
    ('已作废', 'agree'),
    ('RUNNING', '驳回'),
])
def test_invalid_status_is_rejected_even_if_cached_flags_are_wrong(state, result):
    store, ledger, batch, source = pending_archive()
    source.update(status=state, approval_result=result, approved=True, invalid=False)
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    raw = {'source_id':'FORM', 'source_kind':'approval_form', 'process_instance_id':'E', 'source_label':'失效正文'}
    annotated = deps.annotate_source_eligibility([raw], store=store, ledger=ledger, batch_name=batch['name'])
    assert not annotated[0]['analysis_allowed']
    assert not prepare_source_manifest(annotated)[0]['selectable']


@pytest.mark.parametrize('state,result', [
    ('RUNNING', 'agree'),
    ('PENDING', ''),
    ('', ''),
    ('UNKNOWN', ''),
    ('COMPLETED', 'agree'),
])
def test_non_invalid_status_is_allowed_as_final_fee(state, result):
    eligibility = deps.approval_eligibility({
        'id': 'DINGTALK', 'status': state, 'approval_result': result,
        'approved': state == 'COMPLETED', 'invalid': False,
    })

    assert eligibility == {
        'analysis_allowed': True,
        'analysis_reason': '',
        'analysis_code': '',
        'adoption_allowed': True,
        'final_fee_allowed': True,
        'adoption_restriction': '',
    }


def test_analysis_only_archive_is_readable_but_never_final_fee_authority():
    store, ledger, batch, _source = pending_archive()
    raw = {
        'source_id': 'ATTACHMENT',
        'source_kind': 'approval_attachment',
        'process_instance_id': 'E',
        'available': True,
        'analysis_only': True,
        'adoption_restriction': '只读审批附件',
    }
    monkeypatch_source = ledger.create('attachment', {
        'batch': batch['name'],
        'file_url': '/private/files/fuel.png',
    })
    raw['source_id'] = monkeypatch_source['name']

    annotated = deps.annotate_source_eligibility(
        [raw], store=store, ledger=ledger, batch_name=batch['name']
    )[0]

    assert annotated['analysis_allowed'] is True
    assert annotated['adoption_allowed'] is False
    assert annotated['final_fee_allowed'] is False
    assert annotated['adoption_restriction'] == '只读审批附件'


@pytest.mark.parametrize('field,value', [
    ('invalid', True),
    ('disabled', True),
    ('excluded', True),
    ('retired_at', '2026-09-18T00:00:00+00:00'),
    ('available', False),
    ('is_active', 0),
])
def test_disabled_or_retired_source_remains_excluded(field, value):
    source = {'id': 'DINGTALK', 'status': 'RUNNING', 'approval_result': 'agree'}
    source[field] = value

    eligibility = deps.approval_eligibility(source)

    assert eligibility['analysis_allowed'] is False
    assert eligibility['adoption_allowed'] is False
    assert eligibility['final_fee_allowed'] is False


def test_missing_required_source_has_actionable_error_instead_of_false_network_message():
    store, ledger, batch, source = pending_archive()
    raw = {'source_id':'FORM', 'source_kind':'approval_form', 'process_instance_id':'MISSING',
           'approval_no':'MISSING-NO', 'source_label':'国际物流正文', 'approval_role':'international_logistics'}
    annotated = deps.annotate_source_eligibility([raw], store=store, ledger=ledger, batch_name=batch['name'])
    with pytest.raises(ValueError, match='MISSING-NO.*归档'):
        prepare_source_manifest(annotated)


def test_adoption_allows_active_source_then_rechecks_current_invalid_status():
    store, ledger, batch, source = pending_archive()
    baseline = deps.capture_dependencies(
        [{'source_id':'F','source_kind':'approval_form','process_instance_id':'E'}],
        store=store, ledger=ledger, batch_name=batch['name'], source_context={})
    assert not deps.dependency_issues(
        {'dependencies': baseline}, store=store, ledger=ledger, batch_name=batch['name'])

    source.update(status='REJECTED', approval_result='refuse', approved=False, invalid=True)
    store.put('source', {'id': source['id'], 'data': dumps(source)})

    issues = deps.dependency_issues(
        {'dependencies': baseline}, store=store, ledger=ledger, batch_name=batch['name'])
    assert issues and '审批已拒绝、撤销或停用' in issues[0]


def test_pending_expense_rows_remain_saved_and_become_review_only_after_rejection(monkeypatch):
    from overseas_costing.services.effective_logistics_source import load_source_bundle
    from overseas_costing.services.effective_source_values import project_source_values
    from overseas_costing.services import packing_snapshot_service as packing
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement import ledger as ledger_module
    from overseas_costing.services.material_ai_selection_writer import write_rows
    from overseas_costing.tests.test_ai_row_review_regressions import preview

    store, ledger, batch, source = pending_archive()
    version = ledger.rows('version', batch=batch['name'])[0]
    bundle = load_source_bundle(batch['name'], version['name'], store=store, ledger=ledger)
    items = ledger.rows('item', batch=batch['name'], version=version['name'])
    selected = preview(items, [], batch, version, mode='replace_all', source_context=bundle['context'])
    selected['sources'] = [{'source_id':'FORM','source_kind':'approval_form',
        'process_instance_id':source['instance'],'selected':True}]

    new_version = write_rows(store, ledger, selected, {})

    current = load_source_bundle(batch['name'], new_version, store=store, ledger=ledger)
    saved = ledger.rows('item', batch=batch['name'], version=new_version)
    assert saved and project_source_values(saved[0], current['context'])['material_code'] == items[0]['material_code']
    assert current['context']['separate_adoption']
    assert current['context']['available']
    assert not current['context']['approved']
    assert not current['context']['packing']['dependency_issues']

    monkeypatch.setattr(Store, 'frappe', lambda: store)
    monkeypatch.setattr(ledger_module, 'FrappeLedger', lambda: ledger)
    monkeypatch.setattr(packing, '_list_material_ai_sources',
                        lambda *args, **kwargs: packing.selected_packing_ai_sources(batch['name'], current))
    listed = packing.list_material_ai_sources(batch['name'], new_version)
    assert listed[0]['analysis_allowed'] and listed[0]['adoption_allowed']
    assert listed[0]['final_fee_allowed'] is True
    manifest = prepare_source_manifest(listed)
    progress = source_progress_manifest(manifest)
    assert manifest[0]['selected'] and manifest[0]['selectable']
    assert progress[0]['analysis_allowed'] and progress[0]['adoption_allowed']
    assert progress[0]['final_fee_allowed'] is True
    adoption = json.loads(current['version']['extra_json'])['ai_row_adoption']
    baseline = deps.capture_dependencies(manifest, store=store, ledger=ledger,
        batch_name=batch['name'], source_context=current['context'],
        inherited=adoption, purpose='analysis')
    assert not deps.dependency_issues({'dependencies': baseline}, store=store, ledger=ledger,
        batch_name=batch['name'], purpose='analysis')

    source.update(status='REJECTED', approval_result='refuse', approved=False, invalid=True)
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    invalidated = load_source_bundle(batch['name'], new_version, store=store, ledger=ledger)
    retained = ledger.rows('item', batch=batch['name'], version=new_version)
    assert retained and retained[0]['material_code'] == saved[0]['material_code']
    assert invalidated['context']['packing']['available'] is False
    assert invalidated['context']['packing']['dependency_issues']


def test_public_listing_and_real_repository_worker_use_same_analysis_checks(monkeypatch):
    from overseas_costing.services import material_ai_fill_service as ai, packing_snapshot_service as packing
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement import ledger as ledger_module
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    store, ledger, batch, source = pending_archive()
    monkeypatch.setattr(Store, 'frappe', lambda: store)
    monkeypatch.setattr(ledger_module, 'FrappeLedger', lambda: ledger)
    raw = [{'source_id':'COMMENT', 'process_instance_id':'E', 'source_kind':'approval_comment',
            'source_label':'本票评论', 'approval_no':source['approval_no'], 'comment_text':'本票指环扣装箱 12 kg',
            'source_hash':'SAME', 'available':True, 'approval_role':'purchase'}]
    monkeypatch.setattr(packing, '_list_material_ai_sources', lambda *a, **kw: deepcopy(raw))
    listed = packing.list_material_ai_sources('B1','V1')
    assert listed[0]['analysis_allowed'] and listed[0]['adoption_allowed']
    assert listed[0]['final_fee_allowed']
    assert listed[0]['adoption_restriction'] == ''

    class Repo(_LifecycleRepository):
        capture_row_dependencies = ai.FrappeMaterialAIFillRepository.capture_row_dependencies
        assert_row_dependencies = ai.FrappeMaterialAIFillRepository.assert_row_dependencies
        assert_adoption_dependencies = ai.FrappeMaterialAIFillRepository.assert_adoption_dependencies
        list_sources = ai.FrappeMaterialAIFillRepository.list_sources
        def create_run(self, payload):
            self.run = super().create_run(payload)
            return self.run

    repo=Repo(status='QUEUED');requests=[]
    def model(items, documents, **kwargs):
        requests.append(ai.build_source_review_messages(items, documents, **kwargs))
        return {'ok':True, 'proposals':[]}
    monkeypatch.setattr(ai, '_call_source_review_ai', model)
    started=ai.start_source_ai_review('B1','V1',repository=repo,enqueue=lambda run:None)
    assert started['status']=='QUEUED'
    result=ai.execute_material_ai_fill('RUN-1',repository=repo)
    assert result['status']=='READY_WITH_WARNINGS',repo.run.get('error_message')
    assert requests and '本票指环扣' in str(requests)
    assert '相邻票' not in str(requests)
    baseline=ai._load_json(repo.run['draft_json'],{})['review_input']['source_dependencies']
    repo.assert_row_dependencies('B1',baseline)
    repo.assert_adoption_dependencies('B1',baseline)

    source.update(status='REJECTED', approval_result='refuse', approved=False, invalid=True)
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    with pytest.raises(ValueError,match='审批已拒绝'):
        repo.assert_adoption_dependencies('B1',baseline)


def test_forced_start_response_loss_reuses_committed_task(monkeypatch):
    from overseas_costing.services import material_ai_fill_service as ai
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.tests.test_material_ai_fill_service import _StartRepository
    store, *_ = pending_archive()
    monkeypatch.setattr(Store,'frappe',lambda:store)
    class Repo(_StartRepository):
        find_start_request = ai.FrappeMaterialAIFillRepository.find_start_request
        save_start_request = ai.FrappeMaterialAIFillRepository.save_start_request
        def create_run(self,payload):
            run=super().create_run(payload)
            run['name']=f'RUN-{len(self.created)}'
            self.created[-1]=run
            return run
        def get_start_request_run(self,name):
            return next(r for r in self.created if r['name']==name)
    repo=Repo();queued=[]
    def start(key):
        return ai.start_source_ai_review('B1','V1',force=True,selected_source_ids=['A'],
            request_id=key,repository=repo,enqueue=queued.append)
    first=start('same-logical-request');second=start('same-logical-request')
    assert first['run_id']==second['run_id'] and second['reused']
    assert len(repo.created)==len(queued)==1
    assert start('new-explicit-analysis')['run_id']!=first['run_id']
