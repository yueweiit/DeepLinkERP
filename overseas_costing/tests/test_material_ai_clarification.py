"""Saved interpretation is a versioned input, never a material/cost edit."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from overseas_costing.services import material_ai_fill_service as service
from overseas_costing.tests.test_material_ai_context_fingerprint import ContextRepository


class NoteRepository(ContextRepository):
    def __init__(self):
        super().__init__()
        self.note = {"text": "", "revision": 0}
        self.note_writes = []

    def lock_review_scope(self, *_args):
        pass

    def get_clarification(self, _batch):
        return deepcopy(self.note)

    def write_clarification(self, _batch, note):
        self.note = deepcopy(note)
        self.note_writes.append(deepcopy(note))

    def invalidate_clarification_runs(self, _batch):
        for run in self.created:
            if run['status'] in service.ACTIVE_STATES:
                run['status'] = 'STALE'

    def get_context(self, *_args):
        return {**super().get_context(), 'clarification_revision': self.note['revision']}


def save(repo, text, revision=0):
    return service.save_source_ai_clarification('B1', text, revision, repository=repo)


def start(repo, **kwargs):
    return service.start_source_ai_review('B1', 'V1', repository=repo, enqueue=lambda _run: None, **kwargs)


def test_save_reload_is_durable_idempotent_and_does_not_start_ai_or_change_costs():
    repo = NoteRepository()
    before = deepcopy(repo.context), deepcopy(repo.items)
    first = save(repo, ' 两款是一套，共四套 ')
    assert first['ok'] and first['clarification']['revision'] == 1
    assert first['clarification']['text'] == '两款是一套，共四套'
    repeated = save(repo, '两款是一套，共四套', 0)
    assert repeated['unchanged'] is True
    assert len(repo.note_writes) == 1
    assert service.get_source_ai_clarification('B1', repository=repo)['clarification'] == first['clarification']
    assert (repo.context, repo.items) == before
    assert repo.created == repo.writes == []


def test_concurrent_note_save_rejects_stale_revision_without_losing_saved_note():
    repo = NoteRepository()
    save(repo, '第一人的说明')
    conflict = save(repo, '第二人的说明', 0)
    assert conflict['ok'] is False and conflict['conflict'] is True
    assert conflict['clarification']['revision'] == 1
    assert repo.note['text'] == '第一人的说明'
    assert len(repo.note_writes) == 1


@pytest.mark.parametrize('status', ['QUEUED', 'RUNNING', 'READY'])
def test_saving_new_note_invalidates_old_runs_and_same_input_rerun_reuses_result(status):
    repo = NoteRepository()
    save(repo, '旧说明')
    old = start(repo)
    repo.run['status'] = status
    same = start(repo)
    assert same['reused'] and same['run_id'] == old['run_id']
    save(repo, '新说明', 1)
    assert repo.created[0]['status'] == 'STALE'
    assert len(repo.created) == 1  # saving alone does not enqueue
    fresh = start(repo, expected_clarification_revision=2)
    assert not fresh['reused'] and fresh['run_id'] != old['run_id']
    assert repo.run['clarification_text'] == '新说明'
    metadata = json.loads(repo.run['draft_json'])['review_input']
    assert metadata['clarification_revision'] == 2
    assert metadata['cost_version'] == 'V1'
    assert 'source_context' in metadata


def test_stale_start_revision_does_not_launch_or_overwrite_note():
    repo = NoteRepository()
    save(repo, '保存的说明')
    result = start(repo, expected_clarification_revision=0)
    assert not result['ok'] and result['conflict']
    assert not repo.created and repo.note['text'] == '保存的说明'


def test_legacy_start_cannot_overwrite_another_pages_saved_note():
    repo=NoteRepository()
    save(repo,'另一页面已保存')
    result=start(repo,clarification_text='迟到的旧页面输入')
    assert not result['ok'] and result['conflict']
    assert repo.note['text']=='另一页面已保存' and not repo.created


def test_ready_status_checks_changed_source_and_cost_context():
    repo=NoteRepository();start(repo);repo.run.update(status='READY',candidates_json=[])
    repo.context['version_modified']='LATER'
    result=service.get_source_ai_review_status('B1',repo.run['name'],repository=repo)
    assert result['status']=='STALE'


@pytest.mark.parametrize('timing', ['before_worker', 'during_worker'])
def test_worker_rejects_changed_note_without_auto_reanalysis(timing, monkeypatch):
    repo = NoteRepository()
    save(repo, '旧说明')
    start(repo)
    reads = []
    # Simulate a concurrent committed note save, bypassing eager invalidation.
    def change():
        repo.note = {'text': '新说明', 'revision': 2}
    def read(*_args, **kwargs):
        reads.append(kwargs['clarification_text'])
        if timing == 'during_worker':
            change()
        return {'ok': True, 'proposals': []}
    monkeypatch.setattr(service, '_call_source_review_ai', read)
    if timing == 'before_worker':
        change()
    result = service.execute_material_ai_fill(repo.run['name'], repository=repo)
    assert result['status'] == 'STALE'
    assert reads == ([] if timing == 'before_worker' else ['旧说明'])
    assert len(repo.created) == 1 and repo.writes == []


def test_status_and_apply_reject_old_note_even_if_eager_invalidation_was_missed():
    repo = NoteRepository()
    save(repo, '旧说明')
    start(repo)
    repo.run.update(status='READY', candidates_json=[])
    repo.note = {'text': '新说明', 'revision': 2}
    status = service.get_source_ai_review_status('B1', repo.run['name'], after_revision=0, repository=repo)
    assert status['status'] == 'STALE'
    assert status['clarification_text'] == '旧说明'  # historical input stays inspectable
    assert status['clarification']['text'] == '新说明'
    result = service.apply_source_ai_review('B1', repo.run['name'], [], {}, 'TOKEN', 'M1', repository=repo)
    assert result['status'] == 'STALE'
    assert repo.writes == []


def test_worker_retains_revision_metadata_when_draft_becomes_ready(monkeypatch):
    repo = NoteRepository()
    save(repo, '当前说明')
    start(repo)
    monkeypatch.setattr(service, '_call_source_review_ai', lambda *_a, **_k: {'ok': True, 'proposals': []})
    assert service.execute_material_ai_fill(repo.run['name'], repository=repo)['status'] == 'READY'
    assert repo.run['draft_json']['review_input']['clarification_revision'] == 1


def test_repository_note_write_merges_batch_metadata_without_touching_modified(monkeypatch):
    extra = {'preserved': {'a': 1}}
    writes = []
    class DB:
        def sql(self, sql, params, **kwargs):
            assert 'FOR UPDATE' in sql
            return [{'name': 'B1', 'extra_json': json.dumps(extra)}]
        def get_value(self, *args, **kwargs):
            return json.dumps(extra)
        def set_value(self, doctype, name, field, value, **kwargs):
            writes.append((doctype, name, field, value, kwargs))
            extra.clear()
            extra.update(json.loads(value))
    monkeypatch.setattr(service, 'frappe', SimpleNamespace(db=DB()))
    first = service.FrappeMaterialAIFillRepository()
    first.write_clarification('B1', {'text': '说明', 'revision': 1})
    reloaded = service.FrappeMaterialAIFillRepository().get_clarification('B1')
    assert reloaded['text'] == '说明' and reloaded['revision'] == 1
    assert extra['preserved'] == {'a': 1}
    assert len(writes) == 1
    assert writes[0][0:3] == ('Overseas Cost Batch', 'B1', 'extra_json')
    assert writes[0][4] == {'update_modified': False}


@pytest.mark.parametrize('kind', ['approval_form', 'approval_comment', 'approval_attachment', 'approval_comment_attachment'])
def test_scoped_packing_reader_uses_only_selected_shipment_without_fetching_full_attachment(kind, monkeypatch):
    goods = [{'product_name': '本次货物', 'quantity': '2', 'unit': '箱', 'source_row': 7}]
    source = {'source_kind': kind, 'source_id': 'S1', 'scoped_packing': True,
              'scoped_goods': goods, 'scoped_text': '本次发货二箱',
              'form_fields': {'历史货物': '不得读取'}, 'comment_text': '整条评论不得读取',
              'selected_source': {'document_id': 'D1', 'batch_selector': 'SHIP1'}}
    monkeypatch.setattr(service, '_ensure_local_attachment', lambda *_: pytest.fail('must not fetch full attachment'))
    candidates, document = service._read_source([], source)
    assert document['structured_rows'] == goods
    assert document['text'] == '本次发货二箱' and document['ai_eligible'] is True
    assert 'form_fields' not in document
    assert document['source_ref']['selected_source'] == source['selected_source']


def test_background_schedule_uses_saved_note(monkeypatch):
    repo = NoteRepository()
    save(repo, '保存的理解')
    monkeypatch.setattr(service, 'FrappeMaterialAIFillRepository', lambda: repo)
    monkeypatch.setattr(service, '_default_enqueue', lambda *_: None)
    result = service.schedule_source_ai_review('B1', 'V1')
    assert result['ok'] and repo.run['clarification_text'] == '保存的理解'
    assert repo.note['revision'] == 1


def test_worker_preserves_input_revision_during_partial_source_progress(monkeypatch):
    repo = NoteRepository()
    repo.list_sources = lambda *_: [{'source_kind': 'approval_form', 'source_id': 'FORM1',
                                    'source_hash': 'H1', 'form_fields': {'资料': '一箱'}}]
    save(repo, '当前说明')
    start(repo)
    monkeypatch.setattr(service, '_call_source_review_ai', lambda *_a, **_k: {'ok': True, 'proposals': []})
    result = service.execute_material_ai_fill(repo.run['name'], repository=repo)
    assert result['status'] == 'READY'
    assert repo.run['draft_json']['review_input']['clarification_revision'] == 1


def test_save_checks_current_locked_revision_instead_of_earlier_transaction_snapshot():
    repo = NoteRepository()
    repo.note = {'text': '其他页面刚保存', 'revision': 2}
    repo.get_locked_clarification = repo.get_clarification
    repo.get_clarification = lambda *_: {'text': '事务较早读取', 'revision': 1}
    result = save(repo, '不应覆盖并发修改', 1)
    assert result['ok'] is False and result['conflict']
    assert not repo.note_writes


def test_apply_checks_current_locked_note_after_waiting_for_batch_lock():
    repo = NoteRepository()
    save(repo, '旧说明')
    start(repo)
    repo.run.update(status='READY', candidates_json=[])
    repo.get_locked_clarification = lambda *_: {'text': '并发保存的说明', 'revision': 2}
    result = service.apply_source_ai_review('B1', repo.run['name'], [], {}, 'TOKEN', 'M1', repository=repo)
    assert result['status'] == 'STALE' and repo.writes == []
