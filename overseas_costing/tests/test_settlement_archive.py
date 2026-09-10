"""Adapter pagination against a stateful DB cursor, without an external database."""
from copy import deepcopy

import pytest

from overseas_costing.integrations.logistics_settlement_source import SettlementArchive


UPPER = '2099-01-01T00:00:00+00:00'


def row_key(row):
    return row['changed_at'], row['corp_id'], row['process_instance_id']


class ArchiveSource:
    def __init__(self, count=205):
        self.rows = sorted([
            {'corp_id': f'corp-{index % 2}', 'process_instance_id': f'I{index // 2:04d}',
             'changed_at': '2026-01-01T00:00:00+00:00', 'archive_revision': f'rev-{index}',
             'raw_payload': {'comments': [f'comment-{index}']}}
            for index in range(count)], key=row_key)
        self.page_requests, self.attachment_requests, self.hydrated = [], [], []

    def _connection(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return ArchiveCursor(self)

    def _raw_payload(self, row):
        self.hydrated.append((row['corp_id'], row['process_instance_id']))
        return row['raw_payload']


class ArchiveCursor:
    def __init__(self, source):
        self.source = source
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, args):
        pair_count = sql.count('(corp_id=%s AND process_instance_id=%s)')
        if sql.startswith('WITH changed AS'):
            offset, after = 1, None
            if '(changed_at, corp_id, process_instance_id) >' in sql:
                after = tuple(args[offset:offset + 3])
                offset += 3
            pairs = {tuple(args[offset + 2 * index:offset + 2 * index + 2])
                     for index in range(pair_count)}
            limit = args[-1]
            self.source.page_requests.append({'limit': limit, 'after': after, 'upper': args[0], 'pairs': pairs})
            rows = [row for row in self.source.rows if row['changed_at'] < args[0]
                    and (after is None or row_key(row) > after)
                    and (not pairs or (row['corp_id'], row['process_instance_id']) in pairs)]
            self.rows = deepcopy(rows[:limit])
            if ') SELECT corp_id, process_instance_id, changed_at, archive_revision FROM changed' in sql:
                self.rows = [{key: row[key] for key in ('corp_id', 'process_instance_id', 'changed_at', 'archive_revision')}
                             for row in self.rows]
        else:
            assert sql.startswith('SELECT * FROM costing_read.attachment_archives_v2 WHERE ')
            pairs = [tuple(args[2 * index:2 * index + 2]) for index in range(pair_count)]
            self.source.attachment_requests.append(pairs)
            self.rows = [{'corp_id': corp, 'process_instance_id': instance, 'file_id': f'{corp}/{instance}'}
                         for corp, instance in pairs]

    def fetchall(self):
        return self.rows


@pytest.mark.parametrize('financial,lightweight,requested,effective', [
    (True, False, 200, 20), (True, False, 7, 7), (True, False, '7', 7),
    (True, False, 0, 1), (True, False, -1, 1),
    (False, False, 200, 200), (False, False, 500, 200),
    (True, True, 200, 200), (True, True, 7, 7),
])
def test_effective_page_limit_preserves_all_205_rows(financial, lightweight, requested, effective):
    source = ArchiveSource()
    archive = SettlementArchive(source, logistics_codes={'LOG'}, financial=financial)
    found, cursor = [], None
    for _ in range(210):
        page = archive.page(cursor=cursor, limit=requested, upper=UPPER, lightweight=lightweight)
        assert source.page_requests[-1]['limit'] == effective + 1
        assert 0 < len(page['items']) <= effective
        found.extend(page['items'])
        assert page['has_more'] == (len(found) < 205)
        cursor = page['next_cursor']
        assert cursor == list(row_key(page['items'][-1]))
        if not page['has_more']:
            break
    assert [row_key(row) for row in found] == [row_key(row) for row in source.rows]
    if lightweight:
        assert not source.attachment_requests and not source.hydrated
        assert all(set(row) == {'corp_id', 'process_instance_id', 'changed_at', 'archive_revision'} for row in found)
    else:
        assert len(source.hydrated) == 205
        assert all(row['attachments'] == [{'corp_id': row['corp_id'], 'process_instance_id': row['process_instance_id'],
                                         'file_id': f'{row["corp_id"]}/{row["process_instance_id"]}'}] for row in found)
        assert all(len(pairs) <= effective for pairs in source.attachment_requests)


@pytest.mark.parametrize('financial,effective', [(True, 20), (False, 200)])
def test_explicit_pairs_read_all_pages_without_duplicates_or_other_tenants(financial, effective):
    source = ArchiveSource(210)
    archive = SettlementArchive(source, logistics_codes={'LOG'}, financial=financial)
    selected = source.rows[:205]
    pairs = [(row['corp_id'], row['process_instance_id']) for row in reversed(selected)]
    requested = pairs + pairs[:2] + [('missing-corp', 'I0000')]
    found = archive.get_sources(requested)
    assert [row_key(row) for row in found] == [row_key(row) for row in selected]
    assert all(request['limit'] == effective + 1 for request in source.page_requests)
    assert len({request['upper'] for request in source.page_requests}) == 1
    assert all(request['pairs'] == set(requested) for request in source.page_requests)
    assert len(source.hydrated) == len(set(source.hydrated)) == 205


def test_empty_pair_selection_never_queries_archive():
    source = ArchiveSource()
    archive = SettlementArchive(source, logistics_codes={'LOG'}, financial=True)
    assert archive.get_sources([]) == []
    assert not source.page_requests
