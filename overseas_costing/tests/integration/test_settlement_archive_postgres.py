"""Opt-in PostgreSQL verification against the upstream migration contract.

Only SETTLEMENT_ADAPTER_TEST_DSN on loopback with database settlement_test* is accepted.
Fixtures truncate the disposable contract tables; never point this at a live archive.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

psycopg = pytest.importorskip('psycopg')
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from overseas_costing.integrations.dingtalk_approval_source import ApprovalSourceConfig, PostgresApprovalSource
from overseas_costing.integrations.logistics_settlement_source import SettlementArchive
from overseas_costing.services.logistics_settlement.jobs import start_job, run_step
from overseas_costing.services.logistics_settlement.model import parse_source
from overseas_costing.services.logistics_settlement.store import Store

DSN = os.environ.get('SETTLEMENT_ADAPTER_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='Requires an explicitly configured disposable PostgreSQL database')
UPPER = '2099-01-01T00:00:00+00:00'
MIGRATIONS = [
    '20260703000001_create_ding_approval_instance',
    '1788492000000_create_costing_archive',
    '1788492060000_limit_archive_to_logistics',
    '1788505200000_add_archive_diagnostics',
    '20260909000000_logistics_settlement_archive',
]


@pytest.fixture(scope='module')
def pg_config():
    values = conninfo_to_dict(DSN)
    if values.get('host') not in {'127.0.0.1', 'localhost'} or not values.get('dbname', '').startswith('settlement_test'):
        pytest.fail('Refuse anything except a disposable loopback settlement_test* database')
    upstream = Path(os.environ.get('SETTLEMENT_UPSTREAM_WORKTREE') or
                    Path(__file__).resolve().parents[3].parent / 'dingtalk-settlement-upstream')
    if not shutil.which('node') or not (upstream / 'node_modules/node-pg-migrate').exists():
        pytest.skip('Requires Node and installed dependencies in the upstream migration worktree')
    script = '''
        import pg from 'pg'; import { runner } from 'node-pg-migrate';
        const client = new pg.Client({connectionString:process.env.SETTLEMENT_ADAPTER_TEST_DSN});
        await client.connect();
        await client.query(`DO $role$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='costing_reader') THEN CREATE ROLE costing_reader LOGIN; END IF;
        END $role$`);
        for (const file of JSON.parse(process.env.SETTLEMENT_ADAPTER_MIGRATIONS)) {
            await runner({dbClient:client,dir:'migrations',file,checkOrder:false,
                migrationsTable:'settlement_adapter_test_migrations',direction:'up',log:()=>undefined});
        }
        await client.end();
    '''
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=upstream,
                            env={**os.environ, 'SETTLEMENT_ADAPTER_MIGRATIONS': json.dumps(MIGRATIONS)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return values


class TrackedSource(PostgresApprovalSource):
    def __init__(self, config):
        super().__init__(config)
        self.hydrated = 0

    def _raw_payload(self, row):
        self.hydrated += 1
        return super()._raw_payload(row)


class TrackedArchive(SettlementArchive):
    def __init__(self, source):
        super().__init__(source)
        self.full_pages = 0
        self.requested_pairs = []

    def page(self, **kwargs):
        if not kwargs.get('lightweight'):
            self.full_pages += 1
        return super().page(**kwargs)

    def get_sources(self, pairs):
        self.requested_pairs.extend(pairs)
        return super().get_sources(pairs)


@pytest.fixture
def fixture(pg_config):
    admin = psycopg.connect(DSN, autocommit=True, row_factory=dict_row)
    admin.execute('TRUNCATE ding_approval_instance, costing_read.allowed_process_template, costing_read.attachment_archive RESTART IDENTITY CASCADE')
    admin.execute("INSERT INTO costing_read.allowed_process_template(process_code,purpose,archive_attachments) VALUES ('LOG','international_logistics',true),('BUY','purchase_expense',false)")
    config = ApprovalSourceConfig(pg_config['host'], int(pg_config.get('port', 5432)), pg_config['dbname'], 'costing_reader', '')
    archive = TrackedArchive(TrackedSource(config))
    yield admin, archive
    admin.close()


def approval(admin, instance, corp='corp-a', raw=None, deleted=False):
    fields = [{'name': '运输说明', 'value': '海运 MXT500174'}]
    admin.execute('''INSERT INTO ding_approval_instance(corp_id,process_instance_id,process_code,status,result,
        create_time,updated_at,raw_payload,form_component_values,deleted_at)
        VALUES (%s,%s,'LOG','COMPLETED','agree','2025-01-01','2026-01-01',%s,%s,
                CASE WHEN %s THEN '2026-01-02'::timestamptz END)''',
        (corp, instance, Jsonb(raw or {'operationRecords': [{'remark': '完整评论'}]}), Jsonb(fields), deleted))


def attachment(admin, instance, corp='corp-a', file_id='file-1', retired=False):
    admin.execute('''INSERT INTO costing_read.attachment_archive(corp_id,process_instance_id,process_code,
        attachment_origin,file_id,file_name,bucket,object_key,actual_size,sha256,archive_status,content_quality,updated_at,retired_at)
        VALUES (%s,%s,'LOG','comment',%s,'bill.pdf','original-bucket',%s,123,%s,'archived','original','2026-01-03',
                CASE WHEN %s THEN '2026-01-03'::timestamptz END)''',
        (corp, instance, file_id, corp + '/' + instance + '/' + file_id + '/revision-4/claim-7', 'a' * 64, retired))


def all_pages(archive, lightweight=False):
    rows, sizes, cursor = [], [], None
    for _ in range(20):
        page = (archive.inventory_page if lightweight else archive.page)(cursor=cursor, limit=200, upper=UPPER)
        rows.extend(page['items']); sizes.append(len(page['items'])); cursor = page['next_cursor']
        if not page['has_more']:
            return rows, sizes
    raise AssertionError('Pagination did not terminate')


def test_real_v2_columns_full_payload_hydration_and_tenant_attachment_keys(fixture):
    admin, archive = fixture
    for corp in ('corp-a', 'corp-b'):
        approval(admin, 'same-id', corp=corp)
        attachment(admin, 'same-id', corp=corp)
    rows = archive.page(upper=UPPER)['items']
    assert len(rows) == 2
    for row in rows:
        assert row['raw_payload']['operationRecords'] == [{'remark': '完整评论'}]
        assert row['raw_payload']['formComponentValues'][0]['value'] == '海运 MXT500174'
        assert row['raw_payload']['corpId'] == row['corp_id']
        assert row['raw_payload']['processInstanceId'] == 'same-id'
        assert row['raw_payload']['status'] == 'COMPLETED'
        assert len(row['attachments']) == 1
        manifest = row['attachments'][0]
        assert manifest['corp_id'] == row['corp_id']
        assert manifest['bucket'] == 'original-bucket' and manifest['content_quality'] == 'original'
        assert manifest['object_key'].endswith('/revision-4/claim-7')
    selected = archive.get_sources([('corp-b', 'same-id')])
    assert [row['corp_id'] for row in selected] == ['corp-b']
    with archive.source._connection() as connection:
        assert connection.execute('SHOW default_transaction_read_only').fetchone()['default_transaction_read_only'] == 'on'
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('SELECT * FROM public.ding_approval_instance')


def test_preflight_is_accessible_with_migration_granted_reader_role(fixture):
    admin, archive = fixture
    approval(admin, 'alive'); approval(admin, 'deleted', deleted=True)
    result = archive.preflight()
    assert sum(row['count'] for row in result['inventory']) == 2
    assert result['data_source'] == 'postgres'


def test_preflight_sql_is_valid_with_readonly_connection_independent_of_reader_grants(fixture, pg_config):
    admin, _ = fixture
    approval(admin, 'alive'); approval(admin, 'deleted', deleted=True)
    archive = SettlementArchive(PostgresApprovalSource(ApprovalSourceConfig(pg_config['host'], int(pg_config.get('port', 5432)),
        pg_config['dbname'], pg_config.get('user', 'postgres'), pg_config.get('password', ''))))
    result = archive.preflight()
    assert sum(row['count'] for row in result['inventory']) == 2


def test_keyset_paging_over_200_equal_timestamps_retains_tombstones(fixture):
    admin, archive = fixture
    for index in range(205):
        approval(admin, f'I{index:04d}', deleted=index == 204)
    approval(admin, 'I0000', corp='corp-b')
    rows, sizes = all_pages(archive)
    assert sizes == [200, 6]
    assert len({(row['corp_id'], row['process_instance_id']) for row in rows}) == 206
    assert sum(row['deleted_at'] is not None for row in rows) == 1
    inventory, inventory_sizes = all_pages(archive, lightweight=True)
    assert inventory_sizes == [200, 6]
    assert all(set(row) == {'corp_id', 'process_instance_id', 'changed_at', 'archive_revision'} for row in inventory)


def test_attachment_change_and_retirement_wake_unchanged_old_approval(fixture):
    admin, archive = fixture
    approval(admin, 'old'); attachment(admin, 'old')
    original = archive.page(upper=UPPER)['items'][0]
    boundary = admin.execute('SELECT clock_timestamp() AS boundary').fetchone()['boundary']
    admin.execute("UPDATE costing_read.attachment_archive SET retired_at=clock_timestamp(), updated_at=clock_timestamp(), content_quality='preview' WHERE process_instance_id='old'")
    changed = archive.page(lower=boundary.isoformat(), upper=UPPER)['items']
    assert len(changed) == 1
    assert changed[0]['archive_revision'] != original['archive_revision']
    assert changed[0]['attachments'][0]['retired_at'] is not None
    assert changed[0]['attachments'][0]['content_quality'] == 'preview'
    assert changed[0]['updated_at'] == changed[0]['changed_at']
    assert admin.execute("SELECT updated_at FROM ding_approval_instance WHERE process_instance_id='old'").fetchone()['updated_at'].year == 2026
    boundary = admin.execute('SELECT clock_timestamp() AS boundary').fetchone()['boundary']
    admin.execute("UPDATE ding_approval_instance SET deleted_at=clock_timestamp() WHERE process_instance_id='old'")
    deleted = archive.page(lower=boundary.isoformat(), upper=UPPER)['items']
    assert len(deleted) == 1 and deleted[0]['deleted_at'] is not None


def test_weekly_inventory_noops_do_not_hydrate_or_transfer_complete_payloads(fixture):
    admin, archive = fixture
    for index in range(205):
        approval(admin, f'I{index:04d}', raw={'large': 'not-transferred-' * 1000})
    local = Store.sqlite(sqlite3.connect(':memory:')); local.install()
    for row in all_pages(archive)[0]:
        local.ingest(parse_source(row, logistics_codes={'LOG'}))
    archive.full_pages = archive.source.hydrated = 0
    job = start_job(local, mode='reconcile', actor='local-test', now=UPPER)
    for _ in range(10):
        job = run_step(local, archive, job['id'], logistics_codes={'LOG'}, now=UPPER)
        if job['status'] in {'completed', 'failed', 'partial'}:
            break
    assert job['status'] == 'completed', job
    assert job['unchanged_count'] == 205 and job['processed_count'] == 0
    assert archive.full_pages == archive.source.hydrated == 0
    assert not archive.requested_pairs
    assert all(set(row['raw']) == {'corp_id', 'process_instance_id', 'changed_at', 'archive_revision'}
               for row in local.find('manifest', job_id=job['id']))


def test_weekly_reconcile_fetches_only_one_changed_manifest_source(fixture):
    admin, archive = fixture
    for instance in ('unchanged', 'changed'):
        approval(admin, instance); attachment(admin, instance)
    local = Store.sqlite(sqlite3.connect(':memory:')); local.install()
    for row in all_pages(archive)[0]:
        local.ingest(parse_source(row, logistics_codes={'LOG'}))
    admin.execute("UPDATE costing_read.attachment_archive SET sha256=%s, updated_at=clock_timestamp() WHERE process_instance_id='changed'", ('b' * 64,))
    archive.full_pages = archive.source.hydrated = 0
    job = start_job(local, mode='reconcile', actor='local-test', now=UPPER)
    for _ in range(10):
        job = run_step(local, archive, job['id'], logistics_codes={'LOG'}, now=UPPER)
        if job['status'] in {'completed', 'failed', 'partial'}:
            break
    assert job['status'] == 'completed', job
    assert job['unchanged_count'] == 1 and job['processed_count'] == 1
    assert archive.requested_pairs == [('corp-a', 'changed')]
    assert archive.source.hydrated == 1


def test_empty_changed_source_request_returns_no_rows(fixture):
    admin, archive = fixture
    approval(admin, 'unrelated')
    assert archive.get_sources([]) == []
