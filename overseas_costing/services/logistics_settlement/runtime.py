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
from .application import row_meta


def installed():
    return bool(frappe is not None and getattr(frappe, 'db', None) and frappe.db.sql("SHOW TABLES LIKE 'oc_ls_binding'"))


def store():
    if not installed():
        raise ValueError('物流结算数据库尚未迁移')
    return Store.frappe()


def enabled():
    return bool(installed() and (Store.frappe().get('state', 'control') or {}).get('enabled'))


def freight_enabled():
    return bool(frappe is not None and getattr(frappe,'conf',None) and frappe.conf.get('overseas_costing_freight_lines_enabled'))


def archive():
    from overseas_costing.scripts.import_oa_logistics import _get_postgres_approval_source
    from overseas_costing.integrations.logistics_settlement_source import SettlementArchive
    def tracked_pairs():
        tracked = store().sql("SELECT s.corp,s.instance FROM oc_ls_source s WHERE (s.kind IN ('logistics','expense') AND CAST(JSON_EXTRACT(s.data,'$.invalid') AS CHAR) IN ('false','0')) OR EXISTS (SELECT 1 FROM oc_ls_binding b WHERE b.expense_id=s.id OR b.logistics_id=s.id) OR EXISTS(SELECT 1 FROM oc_ls_freight_claim f WHERE f.source_id=s.id OR f.logistics_id=s.id) OR EXISTS(SELECT 1 FROM oc_ls_packing_review p WHERE p.source_id=s.id AND p.status='applied')")
        return [(r['corp'], r['instance']) for r in tracked]
    return SettlementArchive(_get_postgres_approval_source(), logistics_codes=logistics_codes(), financial=freight_enabled(),
                             tracked_pairs=tracked_pairs)


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
    if freight_enabled():
        from .freight_adoption import blockers
        db=store();ledger=FrappeLedger()
        version=ledger.get('version',version_name or (ledger.get('batch',batch_name) or {}).get('current_version')) or {}
        if row_meta(version).get('freight_settlement') or not for_batch(batch_name):
            issues=blockers(db,ledger,batch_name,version.get('name'),for_calculation)
            from overseas_costing.services.effective_logistics_source import resolve_source_context
            ctx=resolve_source_context(batch_name,version.get('name'),store=db,ledger=ledger,lock=lock)
            mapping=db.find('batch_map',batch=batch_name)
            original=db.get('source',mapping[0]['source_id'],lock=lock) if mapping else None
            if original and original.get('invalid'):issues.append('本票国际物流已撤销或失效')
            if ctx.get('root_kind')=='expense' and (ctx.get('invalid') or not ctx.get('available')):issues.append('已采用装箱来源已变化，请重新核对')
            return issues
    binding = for_batch(batch_name, lock=lock)
    if not installed():
        return []
    db = Store.frappe()
    mappings = db.find('batch_map', batch=batch_name, limit=1)
    logistics_source = db.get('source', mappings[0]['source_id'], lock=lock) if mappings else None
    if not binding and logistics_source and logistics_source.get('invalid'):
        return ['国际物流来源已失效，当前结果不能确认或推送']
    effective_id = binding['expense_id'] if binding else (logistics_source or {}).get('id')
    document_states = db.find('document_sync', batch=batch_name, source_id=effective_id, limit=1) if effective_id else []
    if document_states and document_states[0].get('blocking'):
        return list(document_states[0].get('issues') or ['新装箱资料待核对'])
    if not binding:
        return ['尚未关联审批通过的物流结算采购支出，当前为初始录入或暂估'] if mappings and not for_calculation else []
    from .bound_wiki_service import pending_wiki_issues
    wiki_issues = pending_wiki_issues(db, binding)
    if wiki_issues:
        return wiki_issues
    expense = db.get('source', binding['expense_id'], lock=lock)
    logistics = db.get('source', binding['logistics_id'], lock=lock)
    from .reviewed_cargo import resolve_reviewed_source
    expense = resolve_reviewed_source(db, expense, binding)
    if for_calculation:
        version = FrappeLedger().get('version', version_name or binding.get('version'), lock=lock)
        if version and version.get('status') == 'Confirmed':
            return ['已确认版本保留历史，请在调整草稿中重新核算']
    if not expense or expense['invalid'] or expense['kind'] != 'expense' or not expense['approved']:
        return ['关联采购支出尚未通过、已失效或不再属于物流结算，不能确认或推送']
    if binding.get('applied_cost_hash') != expense['cost_hash'] or binding.get('application_status') not in {'applied', 'applied_pending'}:
        return list(binding.get('issues') or ['最终采购支出尚未完整应用，请先核对资料'])
    if version_name and version_name != binding.get('version'):
        return ['当前最终采购支出已生成新版本；历史版本仅供追溯']
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    context = resolve_source_context(batch_name,version_name or binding.get('version'),store=db,ledger=FrappeLedger(),lock=lock)
    issues = []
    application = db.get('application', binding.get('last_application', '')) or {}
    if (application.get('source_context') or {}).get('fingerprint') != context.get('fingerprint'):
        issues.append('当前来源策略或资料快照已变化，请重新采用采购支出资料')
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
        meta = row_meta(item)
        source_row = source_goods.get(meta.get('settlement_line_key'))
        if source_row:
            seen_goods.append(source_row['line_key'])
        cargo = meta.get('settlement_cargo') or {}
        if source_row and (source_row.get('quantity') is None or Decimal(str(cargo.get('quantity') or 0)) != Decimal(str(source_row['quantity'])) or
                           identity(item.get('material_code')) != identity(source_row.get('material_code')) or identity(cargo.get('unit')) != identity(source_row.get('unit'))):
            issues.append('当前货物或数量与最终采购支出不一致，请核对来源')
        if meta.get('settlement_packing_review'):
            issues.append('采购数量或物料已变化，请核对保留的装箱重量、体积')
        from overseas_costing.services.effective_source_values import project_source_values
        physical = project_source_values(item,context)
        if not any(physical.get(key) is not None for key in ('gross_weight_kg','volume_m3','chargeable_weight_kg')):
            issues.append('当前采购支出装箱资料待补，不能采用旧物流重量和体积')
        if meta.get('settlement_purchase_value_review'):
            issues.append('结算数量变化，请核对独立来源商品单价与发货货值')
        if cargo:
            from .valuation import value_final_cargo
            current_version = FrappeLedger().get('version',binding.get('version')) or {}
            valuation = value_final_cargo(item,cargo,{k:v for k,v in current_version.items() if k.startswith('fx_')})
            if valuation.get('error') or valuation.get('input_fingerprint') != (meta.get('settlement_valuation') or {}).get('input_fingerprint'):
                issues.append('最终发货货值缺少依据或已失效，请核对商品单价、单位和汇率后重新采用')
    if expense.get('goods_complete') and (set(seen_goods) != set(source_goods) or len(seen_goods) != len(set(seen_goods))):
        issues.append('当前货物清单与最终采购支出不一致，存在缺行或重复行')
    return sorted(set(issues))


def has_final_binding(batch_name):
    """Legacy import must not replace settlement-owned item rows or restore initial fees."""
    if for_batch(batch_name):return True
    if not installed():return False
    batch=FrappeLedger().get('batch',batch_name) or {}
    version=FrappeLedger().get('version',batch.get('current_version')) or {}
    return bool(row_meta(version).get('freight_settlement'))


def source_summary(source):
    from overseas_costing.utils.dingtalk import build_desktop_approval_url
    source = source or {}
    return {'open_url': build_desktop_approval_url(source.get('instance') or ''), **{key: source.get(key) for key in ('id', 'corp', 'instance', 'approval_no', 'kind', 'status', 'approved', 'invalid',
             'title', 'process_code', 'amount', 'currency', 'fees', 'goods', 'goods_complete', 'issues', 'coverage', 'source_updated_at', 'snapshot', 'documents')}}


def batch_status(batch_name, version_name=None):
    if freight_enabled():
        from .freight_runtime import batch_status as freight_status
        return freight_status(store(),FrappeLedger(),batch_name,version_name)
    from . import batch_matching
    db = store()
    ledger = FrappeLedger()
    batch = ledger.get('batch', batch_name) or {}
    viewed_version = version_name or batch.get('current_version')
    if version_name and (ledger.get('version', version_name) or {}).get('batch') != batch_name:
        raise ValueError('版本不属于当前批次')
    historical = bool(version_name and version_name != batch.get('current_version'))
    mappings = db.find('batch_map', batch=batch_name, limit=1)
    if not mappings:
        return {'ok': True, 'mapped': False, 'binding': None, 'historical': historical, 'viewed_version': viewed_version, 'candidates': [],
                'matching': {'status': 'not_started', 'cached': False}, 'message': '尚未整理此批次的国际物流来源；匹配时仅补读本票审批'}
    source = db.get('source', mappings[0]['source_id'])
    bindings = db.find('binding', logistics_id=source['id'], limit=1)
    binding = bindings[0] if bindings else None
    candidates = [candidate_view(db, c) for c in batch_matching.candidates(db, source)]
    result = {'ok': True, 'mapped': True, 'historical': historical, 'viewed_version': viewed_version, 'logistics': source_summary(source), 'candidates': candidates,
              'binding': {k: binding.get(k) for k in ('id', 'revision', 'application_status', 'issues', 'version', 'source_snapshot', 'coverage')} if binding else None,
              'sync': db.get('state', 'sync') or {}, 'health': db.get('state', 'health') or {},
              'document_sync': next(iter(db.find('document_sync', batch=batch_name, limit=1)), None)}
    result['matching'] = batch_matching.status(db, source['id']) if not historical else {'status': 'historical', 'cached': True}
    if binding:
        from .reviewed_cargo import resolve_reviewed_source
        result['expense'] = source_summary(resolve_reviewed_source(db, db.get('source', binding['expense_id']), binding))
        result['blocking_reasons'] = calculation_blockers(batch_name, binding.get('version'))
        app = db.get('application', binding.get('last_application', '')) or {}
        result['application'] = {k: app.get(k) for k in ('source_snapshot', 'applied_at', 'version', 'status', 'plan', 'source_context', 'review_id')}
        from .writer import item_review
        result['item_reviews'] = [item_review(i) for i in FrappeLedger().rows('item', batch=batch_name, version=viewed_version)]
        result['audit'] = db.find('audit', binding_id=binding['id'], limit=30)
    if historical:
        apps = db.find('application', binding_id=binding['id'], version=viewed_version) if binding else []
        app = max(apps, key=lambda a: a.get('applied_at', ''), default=None)
        result.update(candidates=[], item_reviews=[], blocking_reasons=[], application=app)
        if app:
            snapshot = db.get('snapshot', app['source_snapshot'])
            result['expense'] = source_summary(resolve_reviewed_source(db, {**snapshot, 'id': snapshot['source_id'], 'snapshot': app['source_snapshot']}, binding, version_name=viewed_version))
            result['binding'] = {**result['binding'], 'version': viewed_version, 'application_status': 'historical', 'issues': [], 'coverage': (app.get('plan') or {}).get('coverage'), 'source_snapshot': app['source_snapshot']}
        else:
            result.update(binding=None, expense=None, message='此历史版本尚未采用物流结算采购支出')
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    result['source_context'] = resolve_source_context(batch_name,viewed_version,store=db,ledger=ledger)
    result['document_sync'] = next(iter(db.find('document_sync',batch=batch_name,source_id=result['source_context']['root_source_id'],limit=1)),None)
    return result


def candidate_view(db, candidate):
    return {**{k: candidate.get(k) for k in ('id', 'revision', 'status', 'method', 'reason', 'evidence')},
            'logistics': source_summary(db.get('source', candidate['logistics_id'])),
            'expense': source_summary(db.get('source', candidate['expense_id']))}


def ensure_batch_source(db, batch_name):
    """Explicit match action only: hydrate one exact approval, never create a batch."""
    from .model import parse_source
    ledger = FrappeLedger()
    batch = ledger.get('batch', batch_name) or {}
    mapping = db.find('batch_map', batch=batch_name, limit=1)
    if mapping:
        return db.get('source', mapping[0]['source_id'])
    instance = str(batch.get('source_instance_id') or '').strip()
    if not instance:
        raise ValueError('本票缺少国际物流审批实例，请先补齐原单身份')
    corp = str(batch.get('source_corp_id') or '').strip()
    if not corp:
        corp = str(frappe.conf.get('overseas_costing_settlement_legacy_corp_id') or frappe.conf.get('overseas_costing_dingtalk_corp_id') or '')
    if not corp:
        raise ValueError('本票缺少企业信息，无法安全确定国际物流原单')
    source = db.get('source', digest(corp, instance))
    if not source:
        rows = archive().get_sources([(corp, instance)])
        exact = [r for r in rows if r.get('corp_id') == corp and r.get('process_instance_id') == instance]
        if len(exact) != 1:
            raise ValueError('上游归档尚未提供本票国际物流审批，请等待归档补齐后重试')
        raw = exact[0]
        if parse_source(raw, logistics_codes=logistics_codes())['kind'] != 'logistics':
            raise ValueError('本票原单不是国际物流流程，需核对批次来源')
        try:
            raw = prepare_source(raw)
        except Exception as exc:
            # A document problem must not erase the approval identity or trigger
            # a global initialization. Keep the source explicitly pending review.
            raw = {**raw, 'settlement_fee_issues': ['本票附件待处理：' + str(exc)[:300]]}
        source = db.ingest(parse_source(raw, logistics_codes=logistics_codes()))
    if source['kind'] != 'logistics' or source['invalid']:
        raise ValueError('本票国际物流来源已失效或类型不符')
    with db.atomic():
        db.get('state', 'match_lock', lock=True)
        current_batch = ledger.get('batch', batch_name, lock=True) or {}
        if current_batch.get('source_instance_id') != instance or current_batch.get('source_corp_id') not in (None, '', corp):
            raise ValueError('批次原单已变化，请刷新后重试')
        mappings = db.find('batch_map', source_id=source['id'])
        if mappings and mappings[0]['batch'] != batch_name:
            raise ValueError('该国际物流已对应其他批次，请先处理重复批次')
        existing = db.find('batch_map', batch=batch_name)
        if existing and existing[0]['source_id'] != source['id']:
            raise ValueError('本票来源映射已变化，请刷新')
        if not existing:
            db.insert('batch_map', {'id': source['id'], 'source_id': source['id'], 'batch': batch_name, 'data': '{}'})
        ledger.put('batch', batch_name, {'source_corp_id': corp})
    return source


def start_batch_matching(batch_name, version_name=None):
    from . import batch_matching
    if freight_enabled():
        from . import freight_matching as batch_matching
    db = store()
    batch = FrappeLedger().get('batch', batch_name) or {}
    if version_name and version_name != batch.get('current_version'):
        raise ValueError('历史版本只读，请返回当前版本匹配')
    source = ensure_batch_source(db, batch_name)
    with db.atomic():
        db.get('state', 'match_lock', lock=True)
        batch = FrappeLedger().get('batch', batch_name, lock=True) or {}
        if version_name and version_name != batch.get('current_version'):
            raise ValueError('成本版本已变化，请刷新当前版本后匹配')
        job = batch_matching.start(db, source['id'], frappe.session.user)
    if job.get('status') == 'queued':
        frappe.enqueue('overseas_costing.services.logistics_settlement.runtime.run_batch_matching', queue='long',
                       timeout=600, batch_matching_job_id=job['id'], enqueue_after_commit=True)
    return {'ok': True, 'matching': job}


def run_batch_matching(batch_matching_job_id):
    from . import batch_matching
    if freight_enabled():
        from . import freight_matching as batch_matching
    from overseas_costing.services import allocation_service
    config = allocation_service._ai_config()
    config['timeout'] = min(120, max(60, float(config.get('timeout') or 60)))
    def call_model(messages):
        if not config.get('api_key'):
            raise ValueError('未配置 DeepSeek API 密钥，规则候选已保存，可人工搜索关联')
        return allocation_service._extract_json_object(allocation_service._call_chat_completions(config, messages))
    return batch_matching.run(store(), batch_matching_job_id, call_model, config.get('model', ''))


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
    if freight_enabled():
        from .freight_adoption import source_updated
        source_updated(db,FrappeLedger(),source_id)
        # Never send broader monthly bills through the old whole-source writer.
        if source['kind']!='logistics':return
    if source['kind'] == 'logistics':
        batch_name = ensure_batch(db, source)
        if freight_enabled():
            from overseas_costing.services.effective_logistics_source import resolve_source_context
            ctx=resolve_source_context(batch_name,store=db,ledger=FrappeLedger())
            if ctx.get('root_source_id')!=source_id:return
        from .document_writer import sync_logistics_documents
        bindings = db.find('binding', logistics_id=source_id, limit=1)
        if bindings:
            # Continue archiving Intl; its changes cannot adopt data into a bound batch.
            return
        sync_logistics_documents(db, FrappeLedger(), source, batch_name, 'archive-sync')
    else:
        bindings = db.find('binding', expense_id=source_id, limit=1)
    for binding in bindings:
        logistics = db.get('source', binding['logistics_id'])
        ensure_batch(db, logistics)
        apply_binding(db, FrappeLedger(), binding['id'], 'archive-sync')


def begin(mode='initialize', start='', end='', request_key=None):
    if freight_enabled() and mode=='initialize':
        start=start or '2026-01-01'
        request_key=request_key or 'shipment-freight-1'
    db = store()
    upstream = archive()
    preflight = upstream.preflight() if mode == 'initialize' else {'health': upstream.health(), 'data_source': 'postgres'}
    with db.atomic():
        db.get('state', 'job_lock', lock=True)
        control = db.get('state', 'control') or {}
        if mode != 'initialize' and not control.get('enabled'):
            return {'ok': True, 'skipped': True, 'message': '物流结算同步已暂停'}
        if mode != 'initialize':
            previous_health = db.get('state', 'health') or {}
            if 'scope_counts' in previous_health:
                preflight['scope_counts'] = previous_health['scope_counts']
        db.put('state', {'id': 'health', 'updated_at': utcnow(), 'data': dumps(preflight)})
        job = start_job(db, mode=mode, actor=frappe.session.user, start=start, end=end, request_key=request_key)
        if mode == 'initialize':
            db.put('state', {'id': 'control', 'updated_at': utcnow(), 'data': dumps({'enabled': True})})
        enqueue(job['id'])
        return {'ok': True, 'job': job, 'preflight': preflight}


def enqueue(job_id):
    frappe.enqueue('overseas_costing.services.logistics_settlement.runtime.run_job', queue='long',
                   timeout=900, settlement_job_id=job_id, enqueue_after_commit=True)


def run_ai_matching(matching_ai_job_id):
    from . import ai_matching
    from overseas_costing.services import allocation_service
    config = allocation_service._ai_config()
    config['timeout'] = min(120, max(60, float(config.get('timeout') or 60)))
    def call_model(messages):
        if not config.get('api_key'):
            raise ValueError('未配置 DeepSeek API 密钥')
        return allocation_service._extract_json_object(allocation_service._call_chat_completions(config, messages))
    return ai_matching.run(store(), matching_ai_job_id, call_model, config.get('model', ''))


def run_job(settlement_job_id):
    job_id = settlement_job_id
    db = store()
    try:
        upstream = None if db.get('job', job_id)['mode'] == 'reparse' else archive()
        for _ in range(4):
            job = run_step(db, upstream, job_id, logistics_codes=logistics_codes(), apply_source=apply_source, prepare_source=prepare_source, freight_mode=freight_enabled())
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
    if freight_enabled():
        from .freight_runtime import resume
        resume(db,FrappeLedger())
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
                    from overseas_costing.services.effective_logistics_source import resolve_source_context
                    context = resolve_source_context(current['batch'],store=db,ledger=FrappeLedger())
                    if context.get('root_source_id') != current['source_id']:
                        db.put('document_sync',{'id':current['id'],'status':'historical','data':dumps({**current,'blocking':False})})
                    else:
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
                if current and not freight_enabled() and current.get('application_status') in {'pending', 'queued', 'applied_pending'}:
                    apply_binding(db, FrappeLedger(), current['id'], 'pending-sync')
        except Exception as exc:
            db.audit(binding['id'], 'application_failed', 'pending-sync', reason=str(exc))
    db.put('state', {'id': 'application_cursor', 'updated_at': utcnow(), 'data': dumps({'cursor': rows[-1]['id'] if len(rows) == 50 else None})})


def weekly_reconcile():
    if enabled():
        return begin('reconcile')


def lock_for_final_action(batch_name, version_name=None):
    if installed():
        db=Store.frappe();ledger=FrappeLedger()
        db.get('state','match_lock',lock=True)
        batch=ledger.get('batch',batch_name,lock=True) or {}
        version=ledger.get('version',version_name or batch.get('current_version'),lock=True) or {}
        managed=row_meta(version).get('freight_settlement')
        if managed:
            from .freight_adoption import blockers
            issues=blockers(db,ledger,batch_name,version.get('name'))
            mapping=db.find('batch_map',batch=batch_name)
            original=db.get('source',mapping[0]['source_id'],lock=True) if mapping else None
            if not original or original.get('invalid'):issues.append('本票国际物流缺失、撤销或失效')
            review=db.get('packing_review',managed.get('packing_review_id') or '')
            refs=[(c['source_id'],c['source_snapshot']) for c in managed.get('claims',[])]
            if review:
                refs.append((review['source_id'],review['source_snapshot']))
                if not original or original.get('snapshot')!=review['logistics_snapshot']:issues.append('本票物流与装箱核对时的版本不同，请重新比对')
            for sid,snapshot in refs:
                source=db.get('source',sid,lock=True) or {}
                if not source.get('approved') or source.get('invalid') or source.get('snapshot')!=snapshot:issues.append('采用的费用或装箱来源更新／失效，请先核对调整草稿')
            return sorted(set(issues))
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
    if not binding and not has_final_binding(batch_name):
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
