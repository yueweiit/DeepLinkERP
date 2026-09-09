"""归档只读适配器；v2 包含删除记录，附件变化可唤醒历史审批。"""
from overseas_costing.services.logistics_settlement.model import dumps


class SettlementArchive:
    def __init__(self, source):
        self.source = source

    def health(self):
        with self.source._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT * FROM costing_read.sync_health_v1 LIMIT 1')
                rows = cursor.fetchall()
                return dict(rows[0]) if rows else {}

    def inventory_page(self, **kwargs):
        return self.page(**kwargs, lightweight=True)

    def page(self, *, cursor=None, limit=200, lower='', upper, start='', end='', lightweight=False, pairs=None):
        where = ['changed_at < %s']
        args = [upper]
        if lower:
            where.append('changed_at >= %s'); args.append(lower)
        if start:
            where.append('create_time >= %s'); args.append(start)
        if end:
            where.append('create_time < %s'); args.append(end)
        if cursor:
            where.append('(changed_at, corp_id, process_instance_id) > (%s, %s, %s)')
            args.extend(cursor)
        if pairs:
            where.append('(' + ' OR '.join('(corp_id=%s AND process_instance_id=%s)' for _ in pairs) + ')')
            args.extend(v for pair in pairs for v in pair)
        projection = 'corp_id, process_instance_id, changed_at, archive_revision' if lightweight else '*'
        sql = '''WITH changed AS (
            SELECT a.*, GREATEST(a.updated_at, COALESCE(f.attachment_updated_at, a.updated_at)) AS changed_at,
                   md5(jsonb_build_array(a.raw_payload, a.form_component_values, a.status, a.result, a.deleted_at, f.manifest_hash)::text) AS archive_revision
            FROM costing_read.approval_instances_v2 a
            LEFT JOIN (SELECT corp_id, process_instance_id, MAX(updated_at) AS attachment_updated_at,
                       string_agg(md5(jsonb_build_array(file_id, object_key, bucket, sha256, actual_size, archive_status, content_quality, retired_at)::text), ',' ORDER BY file_id) AS manifest_hash
                       FROM costing_read.attachment_archives_v2 GROUP BY corp_id, process_instance_id) f
              USING (corp_id, process_instance_id)
        ) SELECT ''' + projection + ' FROM changed WHERE ' + ' AND '.join(where) + ' ORDER BY changed_at, corp_id, process_instance_id LIMIT %s'
        args.append(min(200, int(limit)) + 1)
        with self.source._connection() as connection:
            with connection.cursor() as cur:
                cur.execute(sql, tuple(args))
                rows = [dict(r) for r in cur.fetchall()]
                has_more = len(rows) > limit
                rows = rows[:limit]
                if rows and not lightweight:
                    # Batch lookup includes tenant keys; never resolve by instance ID alone.
                    pairs = [(r['corp_id'], r['process_instance_id']) for r in rows]
                    predicates = ' OR '.join('(corp_id=%s AND process_instance_id=%s)' for _ in pairs)
                    cur.execute('SELECT * FROM costing_read.attachment_archives_v2 WHERE ' + predicates, tuple(v for p in pairs for v in p))
                    attachments = [dict(r) for r in cur.fetchall()]
                    for row in rows:
                        row['attachments'] = [a for a in attachments if (a['corp_id'], a['process_instance_id']) == (row['corp_id'], row['process_instance_id'])]
                        row['updated_at'] = row['changed_at']
                        row['raw_payload'] = self.source._raw_payload(row)
        next_cursor = [str(rows[-1]['changed_at']), rows[-1]['corp_id'], rows[-1]['process_instance_id']] if rows else cursor
        return {'items': rows, 'has_more': has_more, 'next_cursor': next_cursor}

    def get_sources(self, pairs):
        if not pairs:
            return []
        from datetime import datetime, timezone, timedelta
        # Refresh selected changed rows only; a transient absence is never a tombstone.
        return self.page(pairs=pairs, upper=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), limit=200)['items']

    def preflight(self):
        with self.source._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute('''SELECT process_code, EXTRACT(YEAR FROM create_time)::int AS year,
                    status, result, COUNT(*)::int AS count, MIN(create_time) AS first_created,
                    MAX(create_time) AS last_created FROM costing_read.approval_instances_v2
                    GROUP BY process_code, EXTRACT(YEAR FROM create_time), status, result ORDER BY year, process_code''')
                inventory = [dict(r) for r in cursor.fetchall()]
        return {'inventory': inventory, 'health': self.health(), 'data_source': 'postgres'}
