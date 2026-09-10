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
from overseas_costing.services.logistics_settlement.model import is_logistics_expense, parse_source
from overseas_costing.services.logistics_settlement.store import Store

DSN = os.environ.get('SETTLEMENT_ADAPTER_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='Requires an explicitly configured disposable PostgreSQL database')
UPPER = '2099-01-01T00:00:00+00:00'
MIGRATIONS = [
    '20260703000000_create_ding_process_template',
    '20260703000001_create_ding_approval_instance',
    '1788492000000_create_costing_archive',
    '1788492060000_limit_archive_to_logistics',
    '1788505200000_add_archive_diagnostics',
    '20260909000000_logistics_settlement_archive',
    '20260910000000_purchase_template_scope',
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
        super().__init__(source, logistics_codes={'LOG'})
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
    admin.execute('TRUNCATE ding_process_template, ding_approval_instance, costing_read.allowed_process_template, costing_read.attachment_archive RESTART IDENTITY CASCADE')
    admin.execute('TRUNCATE costing_read.purchase_template_scope, costing_read.purchase_approval_exposure')
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
    assert sum(row['count'] for row in result['inventory']) == 1
    assert result['data_source'] == 'postgres'


def test_inventory_excludes_unrelated_purchases_before_hydration(fixture):
    admin, archive = fixture
    approval(admin, 'logistics')
    categories = {
        'sea': [{'name': '采购支出Gastos de Compra', 'value': '服务类采购Compra De Servicios'},
                {'name': '服务类采购 Adquisiciones de servicios', 'value': '物流及运输服务Servicios de logística y transporte'},
                {'name': '物流及运输服务', 'value': '海运费用'}],
        'air': [{'name': '采购类别', 'value': ['服务类采购', '物流及运输服务']},
                {'name': '物流及运输服务', 'value': '空运费用'}],
        'courier': [{'name': '采购支出', 'value': '服务类采购'}, {'name': '服务类采购', 'value': '物流及运输服务'},
                    {'name': '物流及运输服务', 'value': '快递费用'}],
        'road': [{'name': '采购支出', 'value': '服务类采购'}, {'name': '服务类采购', 'value': '物流及运输服务'},
                 {'name': '物流及运输服务', 'value': '陆运费用'}],
        'unspecified': [{'name': '采购支出', 'value': '服务类采购'}, {'name': '服务类采购', 'value': '物流及运输服务'}],
        'commodity': [{'name': '采购支出', 'value': '商品采购'}, {'name': '备注', 'value': '物流及运输服务 海运 MXT500174'}],
        'consulting': [{'name': '采购支出', 'value': '服务类采购'}, {'name': '服务类采购', 'value': '咨询服务'}],
    }
    for instance, fields in categories.items():
        approval(admin, instance)
        admin.execute("UPDATE ding_approval_instance SET process_code='BUY',form_component_values=%s WHERE process_instance_id=%s", (Jsonb(fields), instance))
    admin.execute("UPDATE ding_approval_instance SET status='RUNNING' WHERE process_instance_id='air'")
    page = archive.page(upper=UPPER)
    assert {r['process_instance_id'] for r in page['items']} == {'logistics', 'sea', 'air', 'courier', 'road', 'unspecified'}
    assert archive.source.hydrated == 6
    counts = archive.preflight()['scope_counts']
    assert counts == {'logistics': 1, 'expense': 5, 'approved_expense': 4, 'excluded': 2, 'invalid': 0}


def test_tracked_expense_category_loss_is_still_read_and_tenant_scoped(fixture):
    admin, archive = fixture
    for corp in ('corp-a', 'corp-b'):
        approval(admin, 'changed-expense', corp=corp)
    admin.execute("UPDATE ding_approval_instance SET process_code='BUY',form_component_values='[]'::jsonb")
    archive.tracked_pairs = [('corp-a', 'changed-expense')]
    rows = archive.inventory_page(upper=UPPER)['items']
    assert [(r['corp_id'], r['process_instance_id']) for r in rows] == [('corp-a', 'changed-expense')]
    assert len(archive.get_sources([('corp-b', 'changed-expense')])) == 1
    archive.tracked_pairs = lambda: [('corp-b', 'changed-expense')]
    rows = archive.page(upper=UPPER)['items']
    assert [(r['corp_id'], r['process_instance_id']) for r in rows] == [('corp-b', 'changed-expense')]


def test_initial_inventory_excludes_invalid_but_follows_tracked_revocation(fixture):
    admin, archive = fixture
    fields = Jsonb([{'name':'采购支出','value':'服务类采购'}, {'name':'服务类采购','value':'物流及运输服务'}])
    for instance, status, result, deleted in [
        ('valid','COMPLETED','agree',False), ('pending','RUNNING','',False),
        ('refused','COMPLETED','refuse',False), ('withdrawn','TERMINATED','agree',False),
        ('deleted','COMPLETED','agree',True)]:
        approval(admin, instance, deleted=deleted)
        admin.execute("UPDATE ding_approval_instance SET process_code='BUY',form_component_values=%s,status=%s,result=%s WHERE process_instance_id=%s", (fields,status,result,instance))
    rows = archive.page(upper=UPPER)['items']
    assert {r['process_instance_id'] for r in rows} == {'valid','pending'}
    counts = archive.preflight()['scope_counts']
    assert counts['expense'] == 2 and counts['approved_expense'] == 1 and counts['invalid'] == 3
    archive.tracked_pairs = [('corp-a','withdrawn')]
    rows = archive.page(upper=UPPER)['items']
    assert {r['process_instance_id'] for r in rows} == {'valid','pending','withdrawn'}


def test_preflight_sql_is_valid_with_readonly_connection_independent_of_reader_grants(fixture, pg_config):
    admin, _ = fixture
    approval(admin, 'alive'); approval(admin, 'deleted', deleted=True)
    archive = SettlementArchive(PostgresApprovalSource(ApprovalSourceConfig(pg_config['host'], int(pg_config.get('port', 5432)),
        pg_config['dbname'], pg_config.get('user', 'postgres'), pg_config.get('password', ''))), logistics_codes={'LOG'})
    result = archive.preflight()
    assert sum(row['count'] for row in result['inventory']) == 1


def test_keyset_paging_over_200_equal_timestamps_retains_tombstones(fixture):
    admin, archive = fixture
    for index in range(205):
        approval(admin, f'I{index:04d}', deleted=index == 204)
    for index in range(7):
        approval(admin, f'EXCLUDED{index:04d}')
    admin.execute("UPDATE ding_approval_instance SET process_code='BUY' WHERE process_instance_id LIKE 'EXCLUDED%'")
    approval(admin, 'I0000', corp='corp-b')
    archive.tracked_pairs = [('corp-a', 'I0204')]
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
    archive.tracked_pairs = [('corp-a', 'old')]
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


def test_purchase_classifier_contract_matches_upstream_sql_and_python(fixture):
    admin, _ = fixture
    local_fixture = Path(__file__).resolve().parent.parent / 'fixtures/purchase-category-cases.json'
    upstream = Path(os.environ.get('SETTLEMENT_UPSTREAM_WORKTREE') or
                    Path(__file__).resolve().parents[3].parent / 'dingtalk-settlement-upstream')
    cases = json.loads(local_fixture.read_text())
    assert cases == json.loads((upstream / 'src/db/fixtures/purchase-category-cases.json').read_text())
    for case in cases:
        sql_result = admin.execute('SELECT costing_read.is_logistics_purchase(%s) AS eligible',
                                   (Jsonb(case['components']),)).fetchone()['eligible']
        python_result = is_logistics_expense({c['name']: c['value'] for c in case['components']})
        assert sql_result is python_result is case['expected'], case['description']


def test_new_purchase_template_exposes_old_approval_in_incremental_consumer(fixture):
    admin, archive = fixture
    fields = [{'name':'采购支出Gastos de Compra','value':'服务商采购Compra de proveedores'},
              {'name':'服务类采购 Adquisiciones de servicios','value':'物流及运输服务Servicios de logística y transporte'}]
    admin.execute("""INSERT INTO ding_approval_instance(corp_id,process_instance_id,process_code,status,result,
        updated_at,form_component_values,raw_payload) VALUES
        ('corp-a','newly-visible','FUTURE','COMPLETED','agree','2025-01-01',%s,'{}')""", (Jsonb(fields),))
    assert archive.page(upper=UPPER)['items'] == []
    boundary = admin.execute('SELECT clock_timestamp() AS boundary').fetchone()['boundary']
    admin.execute("INSERT INTO ding_process_template(corp_id,process_code,name) VALUES ('corp-a','FUTURE','未来公司采购支出')")
    rows = archive.page(lower=boundary.isoformat(), upper=UPPER)['items']
    assert [row['process_instance_id'] for row in rows] == ['newly-visible']
    assert parse_source(rows[0], logistics_codes={'LOG'})['kind'] == 'expense'
    admin.execute("UPDATE ding_process_template SET name='历史模板',is_deleted=true,enabled=false WHERE process_code='FUTURE'")
    assert [row['process_instance_id'] for row in archive.page(upper=UPPER)['items']] == ['newly-visible']
