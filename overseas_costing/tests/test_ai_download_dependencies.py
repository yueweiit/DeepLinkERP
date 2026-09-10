"""Downloading selected OA files preserves both identity and local evidence fences."""
import pytest

from overseas_costing.services import material_ai_fill_service as ai
from overseas_costing.services.material_ai_source_dependencies import capture_dependencies, dependency_issues
from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
from overseas_costing.services.logistics_settlement.model import dumps
from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
from overseas_costing.tests.test_settlement_writer import setup as settlement_fixture


def pending_source():
    return {'source_kind': 'approval_attachment', 'source_id': 'oa:E:FILE',
            'logical_source_id': 'oa:E:FILE', 'process_instance_id': 'E', 'file_id': 'FILE',
            'source_label': 'packing.txt', 'file_name': 'packing.txt', 'source_hash': 'archive',
            'content_hash': 'original-content', 'available': False, 'can_download': True,
            'download_required': True}


def test_download_identity_can_be_captured_but_is_not_a_final_attachment_dependency():
    store, ledger, batch, *_ = settlement_fixture.__wrapped__()
    manifest = prepare_source_manifest([pending_source()])
    options = dict(store=store, ledger=ledger, batch_name=batch['name'], source_context={})
    baseline = capture_dependencies(manifest, allow_pending=True, **options)
    assert {row['kind'] for row in baseline} == {'approval', 'pending_attachment'}
    assert not dependency_issues({'dependencies': baseline}, store=store, ledger=ledger, batch_name=batch['name'])
    with pytest.raises(ValueError):
        capture_dependencies(manifest, **options)
    source = store.find('source', instance='E')[0]
    source['raw']['comments'] = [{'text': 'changed before download'}]
    store.put('source', {'id': source['id'], 'data': dumps(source)})
    assert dependency_issues({'dependencies': baseline}, store=store, ledger=ledger, batch_name=batch['name'])


@pytest.mark.parametrize('change', ['', 'during_download', 'during_read'])
def test_worker_seals_downloaded_file_before_read_and_rechecks_it(monkeypatch, tmp_path, change):
    store, ledger, *_ = settlement_fixture.__wrapped__()
    path = tmp_path / 'packing.txt'
    path.write_text('packing details', encoding='utf-8')

    class Repo(_LifecycleRepository):
        def __init__(self):
            super().__init__(status='QUEUED')
            self.sources = [pending_source()]

        def create_run(self, payload):
            self.run = super().create_run(payload)
            return self.run

        def capture_row_dependencies(self, sources, context, *, allow_pending=False):
            return capture_dependencies(sources, store=store, ledger=ledger, batch_name='B1',
                                        source_context={}, allow_pending=allow_pending)

        def assert_row_dependencies(self, batch, dependencies, *, lock=False):
            if dependency_issues({'dependencies': dependencies}, store=store, ledger=ledger,
                                 batch_name=batch, lock=lock):
                raise ValueError('来源内容已更新')

    repo = Repo()
    local = {}
    read_baselines = []

    def download(source):
        attachment = ledger.create('attachment', {'batch': 'B1', 'version': 'V1',
            'file_url': str(path), 'file_name': 'packing.txt', 'parse_result_json': '{}'})
        local.update(attachment)
        repo.sources = [{**pending_source(), 'source_id': attachment['name'],
                         'source_hash': 'downloaded', 'available': True, 'download_required': False}]
        if change == 'during_download':
            archived = store.find('source', instance='E')[0]
            archived['raw']['comments'] = [{'text': 'source changed during download'}]
            store.put('source', {'id': archived['id'], 'data': dumps(archived)})
        return {**source, **attachment, 'source_id': attachment['name']}

    def read_document(**kwargs):
        saved = ai._load_json(repo.run['draft_json'], {})['review_input']['source_dependencies']
        read_baselines.append(any(row['kind'] == 'attachment' and row['attachment_id'] == local['name'] for row in saved))
        if change == 'during_read':
            ledger.put('attachment', local['name'], {'file_name': 'changed.txt'})
        return {'text_content': 'packing details', 'extraction_method': 'text'}

    from overseas_costing.services import attachment_parse_service
    monkeypatch.setattr(ai, '_ensure_local_attachment', download)
    monkeypatch.setattr(attachment_parse_service, '_resolve_source_file_path', lambda **kwargs: path)
    monkeypatch.setattr(attachment_parse_service, 'preview_source_document', read_document)
    monkeypatch.setattr(ai, '_call_source_review_ai', lambda *args, **kwargs: {'ok': True, 'proposals': []})
    queued = []
    started = ai.start_source_ai_review('B1', 'V1', repository=repo, enqueue=queued.append)
    assert started['status'] == 'QUEUED' and queued == ['RUN-1']
    result = ai.execute_material_ai_fill('RUN-1', repository=repo)
    assert result['status'] == ('STALE' if change else 'READY'), repo.run.get('error_message')
    assert read_baselines == ([] if change == 'during_download' else [True])
    if not change:
        from overseas_costing.services.material_ai_selection_service import material_fingerprint
        final_draft = ai._load_json(repo.run['draft_json'], {})
        final_sources = ai._load_json(repo.run['source_manifest_json'], [])
        assert final_draft['material_input_fingerprint'] == material_fingerprint(
            repo.get_items('B1', 'V1'), final_sources, repo.get_context('B1', 'V1'))
        final = ai._load_json(repo.run['draft_json'], {})['review_input']['source_dependencies']
        assert {row['kind'] for row in final} == {'approval', 'attachment'}
        repo.assert_row_dependencies('B1', final)
        ledger.put('attachment', local['name'], {'file_name': 'after-ready.txt'})
        with pytest.raises(ValueError, match='来源'):
            repo.assert_row_dependencies('B1', final)
