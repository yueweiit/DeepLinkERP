"""Local-only reads and background archive synchronization for logistics settlement."""
from decimal import Decimal
import json

try:
    import frappe
except ImportError:
    frappe = None

from .store import Store
from .model import digest, dumps, norm, identity
from .matching import save_binding
from .writer import apply_binding
from .ledger import FrappeLedger
from .jobs import start_job, run_step, retry_job, utcnow


def installed():
    return bool(frappe is not None and getattr(frappe, 'db', None) and frappe.db.sql("SHOW TABLES LIKE 'oc_ls_binding'"))


def store():
    if not installed():
        raise ValueError('物流结算数据库尚未迁移')
    return Store.frappe()


def enabled():
    return bool(installed() and (Store.frappe().get('state', 'control') or {}).get('enabled'))


def archive():
    from overseas_costing.scripts.import_oa_logistics import _get_postgres_approval_source
    from overseas_costing.integrations.logistics_settlement_source import SettlementArchive
    return SettlementArchive(_get_postgres_approval_source())


def logistics_codes():
    from overseas_costing.scripts.import_oa_logistics import resolve_logistics_process_code
    configured = frappe.conf.get('overseas_costing_settlement_logistics_codes') or []
    if isinstance(configured, str):
        configured = [code.strip() for code in configured.split(',') if code.strip()]
    return set(configured or [resolve_logistics_process_code()])


def for_batch(batch_name, *, lock=False):
    if not installed():
        return None
    db = Store.frappe()
    mappings = db.find('batch_map', batch=batch_name, limit=1)
    if not mappings:
        return None
    bindings = db.find('binding', logistics_id=mappings[0]['source_id'], limit=1)
    return db.get('binding', bindings[0]['id'], lock=lock) if bindings else None


def calculation_blockers(batch_name, version_name=None, *, for_calculation=False, lock=False):
    """No upstream requests. Invalid/stale final sources cannot silently revive estimates."""
    binding = for_batch(batch_name, lock=lock)
    if not installed():
        return []
    db = Store.frappe()
    mappings = db.find('batch_map', batch=batch_name, limit=1)
    logistics_source = db.get('source', mappings[0]['source_id'], lock=lock) if mappings else None
    if logistics_source and logistics_source.get('invalid'):
        return ['国际物流来源已失效，当前结果不能确认或推送']
    document_states = db.find('document_sync', batch=batch_name, limit=1)
    if document_states and document_states[0].get('blocking'):
        return list(document_states[0].get('issues') or ['新装箱资料待核对'])
    if not binding:
        return ['尚未关联审批通过的物流结算采购支出，当前为初始录入或暂估'] if mappings and not for_calculation else []
    expense = db.get('source', binding['expense_id'], lock=lock)
    logistics = db.get('source', binding['logistics_id'], lock=lock)
    if for_calculation:
        version = FrappeLedger().get('version', version_name or binding.get('version'), lock=lock)
        if version and version.get('status') == 'Confirmed':
            return ['已确认版本保留历史，请在调整草稿中重新核算']
    if not expense or not logistics or expense['invalid'] or logistics['invalid'] or expense['kind'] != 'expense' or not expense['approved']:
        return ['关联采购支出尚未通过、已失效或不再属于物流结算，不能确认或推送']
    if binding.get('applied_cost_hash') != expense['cost_hash'] or binding.get('application_status') not in {'applied', 'applied_pending'}:
        return list(binding.get('issues') or ['最终采购支出尚未完整应用，请先核对资料'])
    if version_name and version_name != binding.get('version'):
        return ['当前最终采购支出已生成新版本；历史版本仅供追溯']
    issues = []
    application = db.get('application', binding.get('last_application', '')) or {}
    issues.extend((application.get('plan') or {}).get('goods_pending') or [])
    planned_rules = (application.get('plan') or {}).get('rules') or []
    actual_rules = [r for r in FrappeLedger().rows('rule', batch=batch_name, version=binding.get('version')) if r.get('is_final')]
    def rule_value(rule):
        try:
            amount = Decimal(str(rule.get('amount')))
        except Exception:
            amount = str(rule.get('amount'))
        return (rule.get('rule_code'), amount, rule.get('currency'), rule.get('source_binding_id'), rule.get('source_snapshot'), rule.get('covered_scopes'), bool(rule.get('is_enabled')), bool(rule.get('is_active')))
    if sorted(map(rule_value, actual_rules), key=str) != sorted(map(rule_value, planned_rules), key=str):
        issues.append('当前费用与已采用的采购支出来源不一致，请重新核对应用记录')
    source_goods = {g['line_key']: g for g in expense['goods']}
    seen_goods = []
    for item in FrappeLedger().rows('item', batch=batch_name, version=binding.get('version')):
        from .application import row_meta
        meta = row_meta(item)
        source_row = source_goods.get(meta.get('settlement_line_key'))
        if source_row:
            seen_goods.append(source_row['line_key'])
        if source_row and (source_row.get('quantity') is None or Decimal(str(item.get('quantity') or 0)) != Decimal(str(source_row['quantity'])) or
                           any(identity(item.get(key)) != identity(source_row.get(key)) for key in ('material_code', 'unit'))):
            issues.append('当前货物或数量与最终采购支出不一致，请核对来源')
        if meta.get('settlement_packing_review'):
            issues.append('采购数量或物料已变化，请核对保留的装箱重量、体积')
        if meta.get('settlement_purchase_value_review'):
            issues.append('数量变化，请核对独立来源商品货值')
    if expense.get('goods_complete') and (set(seen_goods) != set(source_goods) or len(seen_goods) != len(set(seen_goods))):
        issues.append('当前货物清单与最终采购支出不一致，存在缺行或重复行')
    return sorted(set(issues))


def has_final_binding(batch_name):
    """Legacy import must not replace settlement-owned item rows or restore initial fees."""
    return bool(for_batch(batch_name))


def source_summary(source):
    from overseas_costing.utils.dingtalk import build_desktop_approval_url
    return {'open_url': build_desktop_approval_url(source['instance']), **{key: source.get(key) for key in ('id', 'corp', 'instance', 'approval_no', 'kind', 'status', 'approved', 'invalid',
             'amount', 'currency', 'fees', 'goods', 'goods_complete', 'issues', 'coverage', 'source_updated_at', 'snapshot', 'documents')}}


def batch_status(batch_name, version_name=None):
    db = store()
    ledger = FrappeLedger()
    batch = ledger.get('batch', batch_name) or {}
    viewed_version = version_name or batch.get('current_version')
    if version_name and (ledger.get('version', version_name) or {}).get('batch') != batch_name:
        raise ValueError('版本不属于当前批次')
    historical = bool(version_name and version_name != batch.get('current_version'))
    mappings = db.find('batch_map', batch=batch_name, limit=1)
    if not mappings:
        return {'ok': True, 'mapped': False, 'binding': None, 'historical': historical, 'viewed_version': viewed_version, 'candidates': [], 'message': '尚未整理此批次的国际物流来源'}
    source = db.get('source', mappings[0]['source_id'])
    bindings = db.find('binding', logistics_id=source['id'], limit=1)
    binding = bindings[0] if bindings else None
    candidates = db.find('candidate', logistics_id=source['id'], limit=100)
    candidates = [candidate_view(db, c) for c in candidates if c['status'] not in {'stale', 'rejected'}]
    result = {'ok': True, 'mapped': True, 'historical': historical, 'viewed_version': viewed_version, 'logistics': source_summary(source), 'candidates': candidates,
              'binding': {k: binding.get(k) for k in ('id', 'revision', 'application_status', 'issues', 'version', 'source_snapshot', 'coverage')} if binding else None,
              'sync': db.get('state', 'sync') or {}, 'health': db.get('state', 'health') or {},
              'document_sync': next(iter(db.find('document_sync', batch=batch_name, limit=1)), None)}
    if binding:
        result['expense'] = source_summary(db.get('source', binding['expense_id']))
        result['blocking_reasons'] = calculation_blockers(batch_name, binding.get('version'))
        app = db.get('application', binding.get('last_application', '')) or {}
        result['application'] = {k: app.get(k) for k in ('source_snapshot', 'applied_at', 'version', 'status', 'plan')}
        from .writer import item_review
        result['item_reviews'] = [item_review(i) for i in FrappeLedger().rows('item', batch=batch_name, version=viewed_version)]
        result['audit'] = db.find('audit', binding_id=binding['id'], limit=30)
    if historical:
        apps = db.find('application', binding_id=binding['id'], version=viewed_version) if binding else []
        app = max(apps, key=lambda a: a.get('applied_at', ''), default=None)
        result.update(candidates=[], item_reviews=[], blocking_reasons=[], application=app)
        if app:
            snapshot = db.get('snapshot', app['source_snapshot'])
            result['expense'] = source_summary({**snapshot, 'id': snapshot['source_id'], 'snapshot': app['source_snapshot']})
            result['binding'] = {**result['binding'], 'version': viewed_version, 'application_status': 'historical', 'issues': [], 'coverage': (app.get('plan') or {}).get('coverage'), 'source_snapshot': app['source_snapshot']}
        else:
            result.update(binding=None, expense=None, message='此历史版本尚未采用物流结算采购支出')
    return result


def candidate_view(db, candidate):
    return {**{k: candidate.get(k) for k in ('id', 'revision', 'status', 'method', 'reason', 'evidence')},
            'logistics': source_summary(db.get('source', candidate['logistics_id'])),
            'expense': source_summary(db.get('source', candidate['expense_id']))}


def ensure_batch(db, source):
    mapping = db.find('batch_map', source_id=source['id'], limit=1)
    if mapping:
        return mapping[0]['batch']
    ledger = FrappeLedger()
    matches = ledger.rows('batch', source_instance_id=source['instance'])
    exact = [b for b in matches if b.get('source_corp_id') == source['corp']]
    legacy_corp = str(frappe.conf.get('overseas_costing_settlement_legacy_corp_id') or frappe.conf.get('overseas_costing_dingtalk_corp_id') or '')
    eligible = exact or [b for b in matches if not b.get('source_corp_id') and legacy_corp == source['corp']]
    if len(eligible) > 1 or (matches and len(eligible) != 1):
        raise ValueError('国际物流存在重复批次或旧批次缺企业信息；请核对批次映射及历史企业配置')
    if eligible:
        batch = eligible[0]
        ledger.put('batch', batch['name'], {'source_corp_id': source['corp']})
    else:
        from overseas_costing.scripts.import_oa_logistics import summarize_approval, build_batch_values_from_approval
        payload = dict(source['raw'], processInstanceId=source['instance'], corpId=source['corp'], status=source['status'])
        summary = summarize_approval(payload)
        values = build_batch_values_from_approval(summary)
        values.update(source_corp_id=source['corp'], source_instance_id=source['instance'], source_type='oa_logistics', status='Draft', confirm_status='Pending')
        values['batch_no'] = values.get('batch_no') or source['approval_no'] or source['instance']
        batch = ledger.create('batch', values)
        version = ledger.create('version', {'batch': batch['name'], 'version_code': '初始录入', 'version_type': 'Estimated',
                               'status': 'Active', 'is_current': 1, 'source_type': 'Import', 'fx_usd_to_rmb': None, 'fx_rmb_to_mxn': None})
        ledger.put('batch', batch['name'], {'current_version': version['name'], 'version_count': 1})
        for index, goods in enumerate(source['goods']):
            if goods.get('quantity') is None:
                continue
            ledger.create('item', {**{k: goods.get(k) for k in ('material_code', 'product_name', 'spec_model', 'unit', 'quantity')},
                                  'batch': batch['name'], 'version': version['name'], 'row_no': index+1, 'source_type': 'oa_logistics',
                                  'extra_json': dumps({'initial_logistics_line': goods['line_key']})})
        if source['amount'] is not None and source['currency']:
            ledger.create('rule', {'batch': batch['name'], 'version': version['name'], 'rule_code': 'oa_logistics_freight',
                                  'expense_category': '初始物流暂估', 'amount': source['amount'], 'currency': source['currency'],
                                  'allocation_basis': 'goods_value', 'is_enabled': 1, 'is_active': 1})
    db.insert('batch_map', {'id': source['id'], 'source_id': source['id'], 'batch': batch['name'], 'data': '{}'})
    return batch['name']


def apply_source(source_id):
    db = Store.frappe()
    with db.atomic():
        db.get('state', 'match_lock', lock=True)
        source = db.get('source', source_id)
        lookup = {'logistics_id':source_id} if source['kind']=='logistics' else {'expense_id':source_id}
        for existing in db.find('binding', **lookup):
            binding = db.get('binding', existing['id'], lock=True)
            db.get('source', binding['expense_id'], lock=True)
            db.get('source', binding['logistics_id'], lock=True)
        return _apply_source_locked(db, source_id)


def _apply_source_locked(db, source_id):
    source = db.get('source', source_id)
    if source['kind'] == 'logistics':
        batch_name = ensure_batch(db, source)
        from .document_writer import sync_logistics_documents
        sync_logistics_documents(db, FrappeLedger(), source, batch_name, 'archive-sync')
        bindings = db.find('binding', logistics_id=source_id, limit=1)
    else:
        bindings = db.find('binding', expense_id=source_id, limit=1)
    for binding in bindings:
        logistics = db.get('source', binding['logistics_id'])
        ensure_batch(db, logistics)
        apply_binding(db, FrappeLedger(), binding['id'], 'archive-sync')


def begin(mode='initialize', start='', end='', request_key=None):
    db = store()
    upstream = archive()
    preflight = upstream.preflight() if mode == 'initialize' else {'health': upstream.health(), 'data_source': 'postgres'}
    with db.atomic():
        db.get('state', 'job_lock', lock=True)
        control = db.get('state', 'control') or {}
        if mode != 'initialize' and not control.get('enabled'):
            return {'ok': True, 'skipped': True, 'message': '物流结算同步已暂停'}
        db.put('state', {'id': 'health', 'updated_at': utcnow(), 'data': dumps(preflight)})
        job = start_job(db, mode=mode, actor=frappe.session.user, start=start, end=end, request_key=request_key)
        if mode == 'initialize':
            db.put('state', {'id': 'control', 'updated_at': utcnow(), 'data': dumps({'enabled': True})})
        enqueue(job['id'])
        return {'ok': True, 'job': job, 'preflight': preflight}


def enqueue(job_id):
    frappe.enqueue('overseas_costing.services.logistics_settlement.runtime.run_job', queue='long',
                   timeout=900, settlement_job_id=job_id, enqueue_after_commit=True)


def run_job(settlement_job_id):
    job_id = settlement_job_id
    db = store()
    try:
        upstream = None if db.get('job', job_id)['mode'] == 'reparse' else archive()
        for _ in range(4):
            job = run_step(db, upstream, job_id, logistics_codes=logistics_codes(), apply_source=apply_source, prepare_source=prepare_source)
            db.commit()
            if job['status'] not in {'queued', 'running'}:
                return job
        enqueue(job_id)
        db.commit()
    except Exception as exc:
        frappe.db.rollback()
        from .jobs import save_job
        job = db.get('job', job_id)
        if job:
            job.update(status='failed', error=str(exc), last_step_at=utcnow())
            save_job(db, job); db.commit()
        frappe.log_error(title='物流采购支出同步失败', message=str(exc))
        raise


def scheduled_sync():
    if not enabled():
        if installed() and Store.frappe().get('state', 'control'):
            return {'skipped': True, 'message': '物流结算同步已暂停'}
        from overseas_costing.scripts.import_oa_logistics import scheduled_pull_logistics_approvals
        return scheduled_pull_logistics_approvals()
    return begin('incremental')


def resume_pending():
    if not enabled():
        return
    db = store()
    document_cursor = (db.get('state', 'document_cursor') or {}).get('cursor')
    document_rows = db.find('document_sync', status='queued', limit=50, after=document_cursor)
    for state in document_rows:
        try:
            with db.atomic():
                db.get('state', 'job_lock', lock=True)
                if not (db.get('state', 'control', lock=True) or {}).get('enabled'):
                    return
                db.get('state', 'match_lock', lock=True)
                current = db.get('document_sync', state['id'])
                if current and current['status'] == 'queued':
                    apply_source(current['source_id'])
        except Exception as exc:
            db.audit(state['source_id'], 'document_sync_failed', 'pending-sync', reason=str(exc))
    db.put('state', {'id':'document_cursor', 'updated_at':utcnow(), 'data':dumps({'cursor':document_rows[-1]['id'] if len(document_rows)==50 else None})})
    cursor = (db.get('state', 'application_cursor') or {}).get('cursor')
    rows = db.find('binding', limit=50, after=cursor)
    for binding in rows:
        try:
            with db.atomic():
                # Inventory is only a hint: an operator may have rolled back or
                # stopped sync since it was read. Serialize with that operation.
                db.get('state', 'job_lock', lock=True)
                if not (db.get('state', 'control', lock=True) or {}).get('enabled'):
                    return
                db.get('state', 'match_lock', lock=True)
                current = db.get('binding', binding['id'], lock=True)
                if current and current.get('application_status') in {'pending', 'queued', 'applied_pending'}:
                    apply_binding(db, FrappeLedger(), current['id'], 'pending-sync')
        except Exception as exc:
            db.audit(binding['id'], 'application_failed', 'pending-sync', reason=str(exc))
    db.put('state', {'id': 'application_cursor', 'updated_at': utcnow(), 'data': dumps({'cursor': rows[-1]['id'] if len(rows) == 50 else None})})


def weekly_reconcile():
    if enabled():
        return begin('reconcile')


def lock_for_final_action(batch_name, version_name=None):
    binding = for_batch(batch_name, lock=True)
    if not binding:
        return []
    db = Store.frappe()
    db.get('source', binding['expense_id'], lock=True)
    db.get('source', binding['logistics_id'], lock=True)
    batch = FrappeLedger().get('batch', batch_name, lock=True)
    return calculation_blockers(batch_name, version_name or batch.get('current_version'), lock=True)


def guard_legacy_item_write(batch_name, version_name):
    binding = for_batch(batch_name, lock=True)
    if not binding:
        return
    batch = FrappeLedger().get('batch', batch_name, lock=True)
    version = FrappeLedger().get('version', version_name, lock=True)
    if not version or version.get('status') == 'Confirmed' or batch.get('writeback_status') == 'Success' or version_name != batch.get('current_version'):
        raise ValueError('采购支出关联批次的已确认版本保留历史，请在当前调整草稿补充资料')


def prepare_source(raw):
    from .model import parse_source
    from .documents import enrich_raw
    from overseas_costing.services.import_service import _get_minio_archive_client
    from overseas_costing.integrations.dingtalk_approval_source import MinioArchiveClient
    from frappe.utils.file_manager import save_file
    from pathlib import Path
    if parse_source(raw, logistics_codes=logistics_codes())['kind'] == 'unclassified':
        return raw
    client = None
    def read(manifest):
        nonlocal client
        if not manifest.get('bucket') or not manifest.get('object_key'):
            raise ValueError('归档缺少明确 bucket/object_key，不能推测附件地址')
        if client is None:
            client = _get_minio_archive_client().client
        content, _ = MinioArchiveClient(bucket=manifest['bucket'], client=client).download(manifest)
        return content
    def cache_file(content, file_name):
        return save_file(Path(file_name).name, content, None, None, is_private=1).file_url
    return enrich_raw(Store.frappe(), raw, reader=read, cache_file=cache_file)
