"""小型 SQL 存储层：生产使用 Frappe/MariaDB，SQLite 用于真实事务约束测试。"""
from __future__ import annotations
from contextlib import contextmanager
import json
import uuid
import re

from .model import digest, dumps

TABLES = {
    'freight_line': 'source_id VARCHAR(64) NOT NULL, snapshot VARCHAR(64) NOT NULL, line_key VARCHAR(64) NOT NULL, waybill VARCHAR(160) NOT NULL, approval_no VARCHAR(160) NOT NULL, charge_key VARCHAR(64) NOT NULL',
    'freight_candidate': 'logistics_id VARCHAR(64) NOT NULL, expense_id VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, UNIQUE(logistics_id, expense_id)',
    'freight_claim': 'batch VARCHAR(140) NOT NULL, logistics_id VARCHAR(64) NOT NULL, source_id VARCHAR(64) NOT NULL, line_id VARCHAR(64) NOT NULL, charge_key VARCHAR(64) NOT NULL UNIQUE',
    'freight_application': 'batch VARCHAR(140) NOT NULL, version VARCHAR(140) NOT NULL, revision VARCHAR(64) NOT NULL, UNIQUE(batch, version, revision)',
    'packing_review': 'batch VARCHAR(140) NOT NULL, version VARCHAR(140) NOT NULL, source_id VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL',
    'source': 'corp VARCHAR(128) NOT NULL, instance VARCHAR(160) NOT NULL, kind VARCHAR(32) NOT NULL, snapshot VARCHAR(64) NOT NULL, match_hash VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL, UNIQUE(corp, instance)',
    'snapshot': 'source_id VARCHAR(64) NOT NULL, fingerprint VARCHAR(64) NOT NULL, UNIQUE(source_id, fingerprint)',
    'document': 'source_id VARCHAR(64) NOT NULL, fingerprint VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL',
    'attachment_map': 'document_id VARCHAR(64) NOT NULL, version VARCHAR(140) NOT NULL, attachment VARCHAR(140) NOT NULL, UNIQUE(document_id, version)',
    'document_sync': 'source_id VARCHAR(64) NOT NULL UNIQUE, batch VARCHAR(140) NOT NULL, status VARCHAR(32) NOT NULL',
    'detail': 'source_id VARCHAR(64) NOT NULL, snapshot VARCHAR(64) NOT NULL, detail_type VARCHAR(32) NOT NULL, line_key VARCHAR(160) NOT NULL',
    'reference': 'source_id VARCHAR(64) NOT NULL, corp VARCHAR(128) NOT NULL, target_instance VARCHAR(160) NOT NULL, UNIQUE(source_id, target_instance)',
    'identifier': 'source_id VARCHAR(64) NOT NULL, corp VARCHAR(128) NOT NULL, token VARCHAR(160) NOT NULL, token_type VARCHAR(32) NOT NULL, UNIQUE(source_id, token, token_type)',
    'candidate': 'logistics_id VARCHAR(64) NOT NULL, expense_id VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, UNIQUE(logistics_id, expense_id)',
    'binding': 'logistics_id VARCHAR(64) NOT NULL UNIQUE, expense_id VARCHAR(64) NOT NULL UNIQUE',
    'application': 'binding_id VARCHAR(64) NOT NULL, snapshot VARCHAR(64) NOT NULL, version VARCHAR(140) NOT NULL, status VARCHAR(32) NOT NULL, UNIQUE(binding_id, snapshot, version)',
    'job': 'job_key VARCHAR(64) NOT NULL UNIQUE, status VARCHAR(32) NOT NULL, phase VARCHAR(32) NOT NULL',
    'job_item': 'job_id VARCHAR(64) NOT NULL, source_id VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, UNIQUE(job_id, source_id)',
    'manifest': 'job_id VARCHAR(64) NOT NULL, source_id VARCHAR(64) NOT NULL, round_no INTEGER NOT NULL, UNIQUE(job_id, source_id, round_no)',
    'batch_map': 'source_id VARCHAR(64) NOT NULL UNIQUE, batch VARCHAR(140) NOT NULL UNIQUE',
    'audit': 'binding_id VARCHAR(64) NOT NULL, action VARCHAR(64) NOT NULL, created_at VARCHAR(64) NOT NULL',
    'state': 'updated_at VARCHAR(64) NOT NULL',
}


class Store:
    def __init__(self, db, sqlite=False):
        self.db, self.is_sqlite = db, sqlite

    @classmethod
    def sqlite(cls, connection):
        import sqlite3
        connection.row_factory = sqlite3.Row
        return cls(connection, True)

    @classmethod
    def frappe(cls):
        import frappe
        return cls(frappe.db)

    def sql(self, query, params=()):
        if self.is_sqlite:
            cursor = self.db.execute(query.replace('%s', '?').replace(' FOR UPDATE', ''), params)
            return [dict(r) for r in cursor.fetchall()] if cursor.description else []
        return self.db.sql(query, tuple(params), as_dict=True)

    def install(self):
        for table, fields in TABLES.items():
            self.sql(f'CREATE TABLE IF NOT EXISTS oc_ls_{table} (id VARCHAR(64) PRIMARY KEY, data LONGTEXT NOT NULL, {fields})')
        for name, table, columns in [('token', 'identifier', 'corp, token'), ('candidate_status', 'candidate', 'status'), ('job_status', 'job_item', 'job_id, status'), ('source_kind', 'source', 'kind'), ('reference_target', 'reference', 'corp, target_instance'), ('detail_snapshot', 'detail', 'snapshot, detail_type'), ('audit_binding', 'audit', 'binding_id, created_at'), ('document_sync_status', 'document_sync', 'status, source_id')]:
            if self.is_sqlite:
                self.sql(f'CREATE INDEX IF NOT EXISTS oc_ls_{name} ON oc_ls_{table} ({columns})')
            elif not self.sql(f"SHOW INDEX FROM oc_ls_{table} WHERE Key_name=%s", (f'oc_ls_{name}',)):
                self.sql(f'CREATE INDEX oc_ls_{name} ON oc_ls_{table} ({columns})')
        for lock_id in ('job_lock', 'match_lock'):
            if not self.get('state', lock_id):
                self.insert('state', {'id': lock_id, 'updated_at': '', 'data': '{}'})
        for column in ('waybill','approval_no','source_id','charge_key'):
            name='oc_ls_freight_'+column
            if self.is_sqlite:
                self.sql(f'CREATE INDEX IF NOT EXISTS {name} ON oc_ls_freight_line ({column})')
            elif not self.sql('SHOW INDEX FROM oc_ls_freight_line WHERE Key_name=%s',(name,)):
                self.sql(f'CREATE INDEX {name} ON oc_ls_freight_line ({column})')

    @staticmethod
    def validate_columns(table, keys):
        if table not in TABLES:
            raise ValueError('未知数据表')
        columns = set(re.findall(r'(\w+) (?:VARCHAR|INTEGER)', TABLES[table])) | {'id', 'data'}
        if set(keys) - columns:
            raise ValueError('未知查询字段')

    def commit(self):
        self.db.commit()

    @contextmanager
    def atomic(self):
        name = 'ls_' + uuid.uuid4().hex
        self.sql(f'SAVEPOINT {name}')
        try:
            yield
            self.sql(f'RELEASE SAVEPOINT {name}')
        except Exception:
            self.sql(f'ROLLBACK TO SAVEPOINT {name}')
            self.sql(f'RELEASE SAVEPOINT {name}')
            raise

    def insert(self, table, values):
        self.validate_columns(table, values)
        keys = list(values)
        self.sql(f"INSERT INTO oc_ls_{table} ({','.join(keys)}) VALUES ({','.join(['%s']*len(keys))})", [values[k] for k in keys])

    def put(self, table, values):
        self.validate_columns(table, values)
        if self.get(table, values['id']):
            keys = [k for k in values if k != 'id']
            self.sql(f"UPDATE oc_ls_{table} SET {','.join(k+'=%s' for k in keys)} WHERE id=%s", [values[k] for k in keys] + [values['id']])
        else:
            self.insert(table, values)

    def get(self, table, id, lock=False):
        assert table in TABLES
        rows = self.sql(f'SELECT * FROM oc_ls_{table} WHERE id=%s' + (' FOR UPDATE' if lock else ''), (id,))
        return self.unpack(rows[0]) if rows else None

    @staticmethod
    def unpack(row):
        return {**json.loads(row['data']), **{k: v for k, v in row.items() if k != 'data'}}

    def find(self, table, *, limit=None, after=None, **filters):
        self.validate_columns(table, filters)
        where = ' AND '.join(k+'=%s' for k in filters) or '1=1'
        params = list(filters.values())
        if after:
            where += ' AND id>%s'
            params.append(after)
        suffix = ' ORDER BY id'
        if limit is not None:
            suffix += ' LIMIT %s'
            params.append(max(1, min(1000, int(limit))))
        return [self.unpack(r) for r in self.sql(f'SELECT * FROM oc_ls_{table} WHERE {where}' + suffix, params)]

    def count(self, table, **filters):
        self.validate_columns(table, filters)
        where = ' AND '.join(k+'=%s' for k in filters) or '1=1'
        return self.sql(f'SELECT COUNT(*) AS n FROM oc_ls_{table} WHERE {where}', list(filters.values()))[0]['n']

    def audit(self, binding_id, action, actor, **details):
        from .jobs import utcnow
        self.insert('audit', {'id': uuid.uuid4().hex, 'binding_id': binding_id, 'action': action,
                             'created_at': utcnow(), 'data': dumps({'actor': actor, **details})})

    def ingest(self, parsed):
        source_id = parsed['id']
        with self.atomic():
            self.get('state', 'match_lock', lock=True)
            prior = self.get('source', source_id, lock=True)
            # A delayed worker may not move the current source backwards.
            if prior and prior['source_updated_at'] > parsed['source_updated_at']:
                return prior
            snapshot = digest(source_id, parsed['fingerprint'])
            if not self.get('snapshot', snapshot):
                self.insert('snapshot', {'id': snapshot, 'source_id': source_id, 'fingerprint': parsed['fingerprint'], 'data': dumps(parsed)})
                for detail_type, lines in [('goods', parsed['goods']), ('fee', parsed['fees']), ('billing', parsed.get('billing', []))]:
                    for index, line in enumerate(lines):
                        line_key = line.get('line_key') or digest(line)
                        self.insert('detail', {'id': digest(snapshot, detail_type, line_key, index), 'source_id': source_id, 'snapshot': snapshot,
                                               'detail_type': detail_type, 'line_key': line_key, 'data': dumps(line)})
            result = {**parsed, 'snapshot': snapshot}
            self.put('source', {'id': source_id, 'corp': parsed['corp'], 'instance': parsed['instance'], 'kind': parsed['kind'], 'snapshot': snapshot, 'match_hash': parsed['match_hash'], 'updated_at': parsed['source_updated_at'], 'data': dumps(result)})
            self.sql('DELETE FROM oc_ls_identifier WHERE source_id=%s', (source_id,))
            for token_type, token in parsed['identifiers']:
                self.insert('identifier', {'id': digest(source_id, token_type, token), 'source_id': source_id, 'corp': parsed['corp'], 'token_type': token_type, 'token': token, 'data': '{}'})
            self.sql('DELETE FROM oc_ls_reference WHERE source_id=%s', (source_id,))
            for instance in parsed['related']:
                self.insert('reference', {'id': digest(source_id, instance), 'source_id': source_id, 'corp': parsed['corp'], 'target_instance': instance, 'data': '{}'})
            if result['kind'] == 'expense':
                from .freight_matching import index_source
                index_source(self,result)
        return result
