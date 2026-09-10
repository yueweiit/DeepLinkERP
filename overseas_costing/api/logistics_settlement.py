"""Settlement RPCs: server-owned source data, optimistic revisions, per-batch permissions."""
import json
import frappe

from overseas_costing.services.access_control import require_batch_permission, require_overseas_cost_access
from overseas_costing.services.logistics_settlement import runtime
from overseas_costing.services.logistics_settlement.model import digest, dumps
from overseas_costing.services.logistics_settlement.matching import confirm_candidate, reject_candidate, replace_binding, save_binding, save_candidate, match_source, configure_binding
from overseas_costing.services.logistics_settlement.writer import apply_binding, reverse_binding
from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
from overseas_costing.services.logistics_settlement.jobs import retry_job, pause_job


def _decode(value, expected):
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, expected):
        raise ValueError('请求参数格式错误')
    return result


def _authorize_source(db, logistics_id, write=False):
    mapping = db.find('batch_map', source_id=logistics_id, limit=1)
    if mapping:
        if write:
            from overseas_costing.services.logistics_settlement.application import row_meta
            batch=FrappeLedger().get('batch',mapping[0]['batch'],lock=True) or {}
            if row_meta(FrappeLedger().get('version',batch.get('current_version')) or {}).get('freight_settlement'):
                raise ValueError('此批次已按费用明细采用，不能改回旧整单关联')
        return require_batch_permission(mapping[0]['batch'], 'write' if write else 'read')
    frappe.only_for('System Manager')
    return runtime.ensure_batch(db, db.get('source', logistics_id)) if write else None


@frappe.whitelist()
def get_batch_settlement(batch_name, version_name=None):
    return runtime.batch_status(require_batch_permission(batch_name), version_name)


@frappe.whitelist(methods=['POST'])
def start_batch_matching(batch_name, version_name=None):
    return runtime.start_batch_matching(require_batch_permission(batch_name, 'write'), version_name)


@frappe.whitelist(methods=['POST'])
def start_history_matching():
    frappe.only_for('System Manager')
    return runtime.begin('initialize')


@frappe.whitelist(methods=['POST'])
def start_ai_matching():
    frappe.only_for('System Manager')
    if runtime.freight_enabled():
        from overseas_costing.services.logistics_settlement.freight_matching import candidates
        scheduled=0
        for mapping in runtime.store().find('batch_map'):
            cs=candidates(runtime.store(),mapping['source_id'])
            if cs and all(c['status'] in ('pending','rejected') for c in cs):continue
            runtime.start_batch_matching(mapping['batch']);scheduled+=1
        return {'ok':True,'message':f'已为 {scheduled} 票未解决或冲突物流安排本票分析'}
    from overseas_costing.services.logistics_settlement import ai_matching
    from overseas_costing.services import allocation_service
    db = runtime.store()
    rule_job = db.get('job', (db.get('state', 'latest_job') or {}).get('job_id', '')) or {}
    if rule_job.get('status') not in {'completed', 'partial'}:
        raise ValueError('请先完成规则匹配，再分析未匹配和冲突单据')
    if not allocation_service._ai_config().get('api_key'):
        raise ValueError('未配置 DeepSeek API 密钥')
    job = ai_matching.start(db, frappe.session.user)
    if job.get('status') == 'queued':
        frappe.enqueue('overseas_costing.services.logistics_settlement.runtime.run_ai_matching', queue='long',
                       timeout=600, matching_ai_job_id=job['id'], enqueue_after_commit=True)
    return {'ok': True, 'ai_job': job, 'message': job.get('message')}


@frappe.whitelist()
def get_matching_status(job_id=None, after=None, status=None):
    frappe.only_for('System Manager')
    db = runtime.store()
    if runtime.freight_enabled():
        from overseas_costing.services.logistics_settlement.freight_runtime import history_status
        return history_status(db,job_id)
    from overseas_costing.services.logistics_settlement import ai_matching
    job = db.get('job', job_id) if job_id else None
    if not job:
        latest = db.get('state', 'latest_job') or {}
        job = db.get('job', latest.get('job_id', ''))
    filters = {'status': status} if status in {'pending', 'conflict', 'confirmed', 'rejected'} else {}
    candidates = db.find('candidate', limit=51, after=after, **filters)
    counts = {s: db.count('candidate', status=s) for s in ('pending', 'conflict', 'confirmed', 'rejected')}
    unmatched = db.sql("SELECT COUNT(*) AS n FROM oc_ls_source s WHERE s.kind='expense' AND CAST(JSON_EXTRACT(s.data,'$.invalid') AS CHAR) IN ('false','0') AND NOT EXISTS (SELECT 1 FROM oc_ls_binding b WHERE b.expense_id=s.id) AND NOT EXISTS (SELECT 1 FROM oc_ls_candidate c WHERE c.expense_id=s.id AND c.status IN ('pending','conflict'))")[0]['n']
    return {'ok': True, 'job': job, 'ai_job': ai_matching.latest(db), 'counts': {**counts, 'unmatched': unmatched},
            'candidates': [runtime.candidate_view(db, c) for c in candidates[:50]],
            'has_more': len(candidates) > 50, 'next_cursor': candidates[49]['id'] if len(candidates) > 50 else None,
            'failures': db.find('job_item', job_id=job['id'], status='failed', limit=50) if job else [],
            'sync': db.get('state', 'sync') or {}, 'health': db.get('state', 'health') or {},
            'pending_failure_count': db.count('job_item', status='failed'), 'control': db.get('state', 'control') or {}}


@frappe.whitelist(methods=['POST'])
def control_job(job_id, action):
    frappe.only_for('System Manager')
    db = runtime.store()
    if action == 'pause':
        job = pause_job(db, job_id)
    elif action == 'retry':
        job = retry_job(db, job_id)
        runtime.enqueue(job_id)
    else:
        raise ValueError('不支持的任务操作')
    return {'ok': True, 'job': job}


@frappe.whitelist(methods=['POST'])
def confirm_matches(selections, batch_name=None, version_name=None):
    if runtime.freight_enabled():raise ValueError('请在本票资料与费用中分别核对费用明细和装箱变更')
    selections = _decode(selections, list)
    if not selections or len(selections) > 200:
        raise ValueError('每次确认 1 至 200 组候选')
    db = runtime.store()
    results = []
    for selection in selections:
        try:
            with db.atomic():
                db.get('state', 'match_lock', lock=True)
                candidate = db.get('candidate', selection['id'], lock=True)
                if not candidate:
                    raise ValueError('候选不存在')
                if batch_name:
                    require_batch_permission(batch_name, 'write')
                    if not db.find('batch_map', batch=batch_name, source_id=candidate['logistics_id']):
                        raise ValueError('候选不属于本票国际物流')
                    if version_name and (FrappeLedger().get('batch', batch_name, lock=True) or {}).get('current_version') != version_name:
                        raise ValueError('成本版本已变化，请刷新当前版本后确认')
                _authorize_source(db, candidate['logistics_id'], write=True)
                binding = confirm_candidate(db, candidate['id'], selection['revision'], frappe.session.user,
                                            resolve=selection.get('resolve') is True, reason=str(selection.get('reason') or ''))
                if candidate['status'] != 'confirmed':
                    binding = configure_binding(db, binding,
                        coverage=_decode(selection['coverage'], list) if selection.get('coverage') is not None else None,
                        negative_confirmed=selection.get('negative_confirmed') is True, actor=frappe.session.user)
            # Association and adoption are distinct durable states. A document/fee
            # failure rolls back only adoption; current source gates block old costs.
            applied = _apply_saved_binding(db, binding)
            results.append({'candidate_id': candidate['id'], 'ok': True, 'application_status': applied['application_status'], 'issues': applied.get('issues', [])})
        except Exception as exc:
            results.append({'candidate_id': selection.get('id'), 'ok': False, 'message': str(exc)})
    return {'ok': all(r['ok'] for r in results), 'results': results,
            'confirmed_count': sum(r['ok'] for r in results), 'failed_count': sum(not r['ok'] for r in results)}


def _apply_saved_binding(db, binding):
    try:
        return apply_binding(db, FrappeLedger(), binding['id'], frappe.session.user)
    except Exception as exc:
        from overseas_costing.services.logistics_settlement.writer import pending
        with db.atomic():
            current = db.get('binding', binding['id'], lock=True)
            if current['revision'] != binding['revision'] or current['expense_id'] != binding['expense_id']:
                return current
            issue = '关联已保存，资料采用待重试：' + str(exc)[:300]
            pending(db, current, 'pending', [issue])
            db.audit(binding['id'], 'application_failed', frappe.session.user, reason=issue)
            return current


@frappe.whitelist(methods=['POST'])
def reject_match(candidate_id, revision, reason):
    db = runtime.store()
    candidate = db.get('candidate', candidate_id)
    _authorize_source(db, candidate['logistics_id'], write=True)
    reject_candidate(db, candidate_id, revision, frappe.session.user, str(reason))
    return {'ok': True}


@frappe.whitelist(methods=['POST'])
def correct_match(batch_name, binding_id, expected_revision, candidate_id, candidate_revision, reason):
    if runtime.freight_enabled():raise ValueError('请在本票资料与费用中分别核对费用明细和装箱变更')
    batch_name = require_batch_permission(batch_name, 'write')
    db = runtime.store()
    current = runtime.for_batch(batch_name)
    if not current or current['id'] != binding_id:
        raise ValueError('关联不属于当前批次')
    with db.atomic():
        binding = replace_binding(db, binding_id, expected_revision, candidate_id, candidate_revision,
                                  frappe.session.user, reason,
                                  on_replace=lambda old,new: reverse_binding(db, FrappeLedger(), old, new, frappe.session.user))
    applied = _apply_saved_binding(db, binding)
    return {'ok': True, 'application_status': applied['application_status'], 'issues': applied.get('issues', [])}


@frappe.whitelist()
def find_expenses(batch_name, query='', after=None):
    batch_name = require_batch_permission(batch_name)
    if not str(query or '').strip():
        return {'ok': True, 'items': [], 'has_more': False, 'message': '请输入审批号、物流标识或货物关键词；搜索结果仅用于关联本票'}
    db = runtime.store()
    mapping = db.find('batch_map', batch=batch_name, limit=1)
    if not mapping:
        return {'ok': True, 'items': [], 'message': '请先点击本票匹配以整理当前国际物流原单'}
    logistics = db.get('source', mapping[0]['source_id'])
    token = '%' + str(query).strip().replace('%', '\\%').replace('_', '\\_') + '%'
    params = [logistics['corp'], token, token, after or '']
    rows = db.sql("SELECT * FROM oc_ls_source WHERE kind='expense' AND CAST(JSON_EXTRACT(data,'$.invalid') AS CHAR) IN ('false','0') AND corp=%s AND (instance LIKE %s OR data LIKE %s) AND id>%s ORDER BY id LIMIT 51", params)
    sources = [db.unpack(row) for row in rows]
    return {'ok': True, 'items': [{**runtime.source_summary(s), 'occupied': bool(db.find('binding', expense_id=s['id'], limit=1))} for s in sources[:50]],
            'has_more': len(sources)>50, 'next_cursor': sources[49]['id'] if len(sources)>50 else None}


@frappe.whitelist(methods=['POST'])
def prepare_manual_candidate(batch_name, expense_id, reason):
    batch_name = require_batch_permission(batch_name, 'write')
    if not str(reason).strip():
        raise ValueError('请填写人工核对依据')
    if runtime.freight_enabled():
        from overseas_costing.services.logistics_settlement.freight_runtime import manual_candidate
        return {'ok':True,'candidate':manual_candidate(runtime.store(),FrappeLedger(),batch_name,expense_id,str(reason)),'freight_mode':True}
    db = runtime.store()
    db.get('state', 'match_lock', lock=True)
    mapping = db.find('batch_map', batch=batch_name, limit=1)
    if not mapping:
        raise ValueError('此批次尚未初始化来源')
    logistics = db.get('source', mapping[0]['source_id'])
    expense = db.get('source', expense_id)
    if not expense or expense['kind'] != 'expense' or expense['corp'] != logistics['corp'] or expense['invalid']:
        raise ValueError('采购支出企业、类别或状态不符')
    key = digest(logistics['id'], expense_id)
    if db.find('binding', logistics_id=logistics['id'], expense_id=expense_id, limit=1):
        raise ValueError('此采购支出已经关联当前物流，请直接查看已关联明细')
    occupied = bool(db.find('binding', logistics_id=logistics['id'], limit=1) or db.find('binding', expense_id=expense_id, limit=1))
    evidence_hash = digest(logistics['match_hash'], expense['match_hash'], reason)
    candidate = {'id': key, 'logistics_id': logistics['id'], 'expense_id': expense_id, 'status': 'conflict' if occupied else 'pending',
                 'method': 'manual', 'evidence': [{'type': 'manual', 'value': reason}], 'evidence_hash': evidence_hash,
                 'logistics_snapshot': logistics['snapshot'], 'expense_snapshot': expense['snapshot'],
                 'revision': digest(logistics['snapshot'], expense['snapshot'], evidence_hash), 'reason': reason}
    save_candidate(db, candidate)
    return {'ok': True, 'candidate': runtime.candidate_view(db, candidate)}


@frappe.whitelist(methods=['POST'])
def confirm_freight_lines(batch_name,version_name,candidate_id,candidate_revision,line_ids,replace_claim_ids=None,expected_revision=None,reason='',negative_confirmed=False):
    if not runtime.freight_enabled():raise ValueError('本票费用明细功能尚未启用')
    batch_name=require_batch_permission(batch_name,'write')
    from overseas_costing.services.logistics_settlement.freight_adoption import confirm
    result=confirm(runtime.store(),FrappeLedger(),batch_name,version_name,candidate_id,candidate_revision,_decode(line_ids,list),frappe.session.user,
        replace_claim_ids=_decode(replace_claim_ids,list) if replace_claim_ids else [],expected_revision=expected_revision,
        reason=str(reason),negative_confirmed=negative_confirmed in (True,1,'1','true'))
    return {'ok':True,**result}


@frappe.whitelist(methods=['POST'])
def preview_freight_packing(batch_name,version_name,candidate_id,candidate_revision):
    if not runtime.freight_enabled():raise ValueError('本票费用明细功能尚未启用')
    batch_name=require_batch_permission(batch_name,'write')
    from overseas_costing.services.logistics_settlement.freight_packing import preview
    return {'ok':True,'preview':preview(runtime.store(),FrappeLedger(),batch_name,version_name,candidate_id,candidate_revision)}


@frappe.whitelist(methods=['POST'])
def confirm_freight_packing(batch_name,version_name,preview_id,revision,selections,complete_confirmed=False):
    if not runtime.freight_enabled():raise ValueError('本票费用明细功能尚未启用')
    batch_name=require_batch_permission(batch_name,'write')
    from overseas_costing.services.logistics_settlement.freight_packing import confirm
    return {'ok':True,**confirm(runtime.store(),FrappeLedger(),batch_name,version_name,preview_id,revision,_decode(selections,list),frappe.session.user,
                              complete_confirmed=complete_confirmed in (True,1,'1','true'))}


@frappe.whitelist(methods=['POST'])
def reject_freight_candidate(batch_name,candidate_id,revision,reason):
    if not runtime.freight_enabled():raise ValueError('本票费用明细功能尚未启用')
    batch_name=require_batch_permission(batch_name,'write');db=runtime.store()
    with db.atomic():
        db.get('state','match_lock',lock=True);c=db.get('freight_candidate',candidate_id,lock=True)
        if not c or not db.find('batch_map',batch=batch_name,source_id=c['logistics_id']) or c['revision']!=revision:raise ValueError('候选不属于本票或已变化')
        if not str(reason).strip():raise ValueError('请填写否决原因')
        c.update(status='rejected',rejection_reason=str(reason),actor=frappe.session.user)
        db.put('freight_candidate',{'id':c['id'],'status':c['status'],'data':dumps(c)})
        db.audit(batch_name,'freight_candidate_rejected',frappe.session.user,candidate_id=c['id'],reason=str(reason))
    return {'ok':True}


@frappe.whitelist(methods=['POST'])
def retry_application(batch_name, expected_revision, expected_snapshot, expected_version, coverage=None, negative_confirmed=False):
    if runtime.freight_enabled():raise ValueError('请在本票资料与费用中分别核对费用明细和装箱变更')
    batch_name = require_batch_permission(batch_name, 'write')
    db = runtime.store()
    with db.atomic():
        binding = runtime.for_batch(batch_name, lock=True)
        if not binding or binding['revision'] != int(expected_revision):
            raise ValueError('关联已变化，请刷新')
        from overseas_costing.services.logistics_settlement.writer import validate_application_preview
        validate_application_preview(db, FrappeLedger(), binding, expected_snapshot, expected_version)
        binding = configure_binding(db, binding,
            coverage=_decode(coverage, list) if coverage is not None else None,
            negative_confirmed=negative_confirmed in (True, 1, '1'), actor=frappe.session.user)
        applied = apply_binding(db, FrappeLedger(), binding['id'], frappe.session.user)
    return {'ok': True, 'application_status': applied['application_status'], 'issues': applied.get('issues', [])}


@frappe.whitelist(methods=['POST'])
def resolve_item_checks(batch_name, expected_revision, selections, reason):
    if runtime.freight_enabled():raise ValueError('请在本票资料与费用中分别核对费用明细和装箱变更')
    batch_name = require_batch_permission(batch_name, 'write')
    from overseas_costing.services.logistics_settlement.writer import resolve_item_checks as resolve
    db = runtime.store()
    binding = runtime.for_batch(batch_name)
    if not binding:
        raise ValueError('当前批次没有已确认关联')
    result = resolve(db, FrappeLedger(), binding['id'], expected_revision, _decode(selections, list), str(reason), frappe.session.user)
    return {'ok': True, 'application_status': result['application_status'], 'issues': result.get('issues', [])}


@frappe.whitelist(methods=['POST'])
def reparse_sources(source_ids):
    frappe.only_for('System Manager')
    from overseas_costing.services.logistics_settlement.jobs import start_reparse_job
    job = start_reparse_job(runtime.store(), _decode(source_ids, list), actor=frappe.session.user)
    runtime.enqueue(job['id'])
    return {'ok': True, 'job': job}


@frappe.whitelist(methods=['POST'])
def set_sync_enabled(is_enabled):
    frappe.only_for('System Manager')
    from overseas_costing.services.logistics_settlement.jobs import utcnow
    db = runtime.store()
    db.get('state', 'job_lock', lock=True)
    enabled = is_enabled in (True, 1, '1')
    db.put('state', {'id':'control', 'updated_at':utcnow(), 'data':dumps({'enabled':enabled})})
    if not enabled:
        for status in ('queued','running'):
            for job in db.find('job', status=status):
                pause_job(db, job['id'])
    db.audit('', 'sync_control', frappe.session.user, enabled=enabled)
    return {'ok': True, 'enabled': enabled}


@frappe.whitelist(methods=['POST'])
def restore_application(batch_name, application_id, expected_revision, reason):
    frappe.only_for('System Manager')
    batch_name = require_batch_permission(batch_name, 'write')
    from overseas_costing.services.logistics_settlement.rollback import restore_application as restore
    db = runtime.store()
    app = db.get('application', application_id)
    binding = runtime.for_batch(batch_name)
    if not app or not binding or app['binding_id'] != binding['id']:
        raise ValueError('应用记录不属于当前批次')
    restored = restore(db, FrappeLedger(), application_id, expected_revision, reason, frappe.session.user)
    return {'ok':True, 'application_status':restored['application_status'], 'issues':restored['issues'], 'version':restored['version']}


@frappe.whitelist()
def freight_line_evidence(batch_name,version_name,line_id):
    batch_name=require_batch_permission(batch_name)
    from overseas_costing.services.logistics_settlement.freight_runtime import line_evidence
    return {'ok':True,'evidence':line_evidence(runtime.store(),FrappeLedger(),batch_name,version_name,line_id)}


@frappe.whitelist(methods=['POST'])
def resolve_freight_packing_checks(batch_name,version_name,selections,reason):
    batch_name=require_batch_permission(batch_name,'write')
    from overseas_costing.services.logistics_settlement.freight_packing import resolve_checks
    return {'ok':True,**resolve_checks(runtime.store(),FrappeLedger(),batch_name,version_name,_decode(selections,list),str(reason),frappe.session.user)}


@frappe.whitelist(methods=['POST'])
def restore_freight_application(batch_name,version_name,application_id,expected_revision,reason):
    frappe.only_for('System Manager')
    batch_name=require_batch_permission(batch_name,'write')
    from overseas_costing.services.logistics_settlement.freight_recovery import restore_fee_application
    return {'ok':True,**restore_fee_application(runtime.store(),FrappeLedger(),batch_name,version_name,application_id,expected_revision,str(reason),frappe.session.user)}
