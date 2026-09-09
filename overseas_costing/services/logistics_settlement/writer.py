"""Apply one confirmed source atomically; freeze confirmed versions and retain beforeimages."""
from datetime import datetime
from decimal import Decimal

from .application import plan_application, row_meta
from .matching import save_binding
from .model import digest, dumps, timestamp
from .jobs import utcnow

GOODS_FIELDS = ('material_code', 'product_name', 'spec_model', 'quantity', 'unit')
SYSTEM_FIELDS = {'name', 'doctype', 'owner', 'creation', 'modified', 'modified_by', 'docstatus', 'idx', '_user_tags', '_comments', '_assign', '_liked_by'}
DERIVED_FIELDS = ('freight_alloc_rmb', 'freight_alloc_mxn', 'total_logistics_mxn', 'total_cost_rmb', 'total_unit_rmb', 'total_cost_mxn', 'total_unit_mxn')


def clean_copy(doc):
    return {k: v for k, v in doc.items() if k not in SYSTEM_FIELDS and not k.startswith('_')}


def locked(batch):
    from overseas_costing.services.edit_session_service import lock_is_active
    return lock_is_active(batch)


def mutable_version(ledger, batch):
    current = ledger.get('version', batch['current_version'])
    if current['status'] != 'Confirmed' and batch.get('confirm_status') != 'Confirmed' and batch.get('writeback_status') != 'Success':
        return current
    values = clean_copy(current)
    values.update(version_code='ADJ-' + datetime.now().strftime('%Y%m%d%H%M%S%f'), version_type='Adjustment',
                  status='Active', is_current=1, source_type='Clone', calculated_at=None,
                  summary_snapshot_json='{}', rule_snapshot_json='[]', remark='采购支出更新；原确认版本保留')
    draft = ledger.create('version', values)
    for kind in ('item', 'rule'):
        for doc in ledger.rows(kind, batch=batch['name'], version=current['name']):
            values = clean_copy(doc)
            values['version'] = draft['name']
            if kind == 'item':
                meta = row_meta(doc)
                meta['settlement_origin_item'] = meta.get('settlement_origin_item') or doc['name']
                values['extra_json'] = dumps(meta)
            ledger.create(kind, values)
    ledger.put('version', current['name'], {'is_current': 0})
    ledger.put('batch', batch['name'], {'current_version': draft['name'], 'confirm_status': 'Pending',
                                      'status': 'Dirty', 'is_locked': 0, 'writeback_status': 'Not Started',
                                      'version_count': len(ledger.rows('version', batch=batch['name']))})
    return draft


def application_context(store, ledger, binding):
    mappings = store.find('batch_map', source_id=binding['logistics_id'], limit=1)
    if not mappings:
        return None
    batch = ledger.get('batch', mappings[0]['batch'], lock=True)
    if not batch:
        raise ValueError('来源对应的成本批次不存在')
    return batch


def pending(store, binding, status, issues):
    binding.update(application_status=status, issues=issues)
    save_binding(store, binding)
    return binding


def apply_binding(store, ledger, binding_id, actor):
    with store.atomic():
        binding = store.get('binding', binding_id, lock=True)
        expense = store.get('source', binding['expense_id'], lock=True)
        logistics = store.get('source', binding['logistics_id'], lock=True)
        if expense['invalid'] or logistics['invalid'] or expense['kind'] != 'expense':
            return pending(store, binding, 'invalid', ['采购支出或国际物流已失效，历史结果保留，当前不能确认或推送'])
        if not expense['approved']:
            return pending(store, binding, 'pending', ['采购支出尚未审批通过'])
        batch = application_context(store, ledger, binding)
        if not batch:
            return pending(store, binding, 'pending', ['国际物流尚未对应唯一成本批次'])
        if locked(batch):
            return pending(store, binding, 'queued', ['批次正在编辑，已排队等待应用'])
        # All entry points (manual confirmation, retry and background sync) use the
        # same locally cached packing evidence. It may itself create an adjustment.
        from .document_writer import sync_logistics_documents
        has_documents = bool(logistics.get('documents') or store.find('document_sync', source_id=logistics['id'], limit=1))
        if has_documents:
            sync_logistics_documents(store, ledger, logistics, batch['name'], actor)
            batch = ledger.get('batch', batch['name'], lock=True)
        if (expense.get('coverage') == 'unknown' or binding.get('coverage')) and binding.get('coverage_cost_hash') != expense['cost_hash']:
            return pending(store, binding, 'pending', ['采购支出已变化，请重新核对费用覆盖范围'])
        negative_confirmed = bool(binding.get('negative_confirmed') and binding.get('negative_cost_hash') == expense['cost_hash'])
        effective_hash = digest(expense['cost_hash'], binding['revision'], binding.get('coverage'), binding.get('negative_confirmed'))
        if binding.get('applied_hash') == effective_hash and binding.get('version') == batch['current_version']:
            return refresh_application_state(store, ledger, binding, expense)
        items = ledger.rows('item', batch=batch['name'], version=batch['current_version'])
        rules = ledger.rows('rule', batch=batch['name'], version=batch['current_version'])
        plan = plan_application(expense, items, rules, binding_id=binding_id, coverage=binding.get('coverage'), negative_confirmed=negative_confirmed)
        if not plan['ready']:
            return pending(store, binding, 'pending', plan['blocking'])
        version = mutable_version(ledger, batch)
        items = ledger.rows('item', batch=batch['name'], version=version['name'])
        rules = ledger.rows('rule', batch=batch['name'], version=version['name'])
        plan = plan_application(expense, items, rules, binding_id=binding_id, coverage=binding.get('coverage'), negative_confirmed=negative_confirmed)
        before = {'items': items, 'rules': rules, 'batch': batch}
        if not binding.get('baseline'):
            binding['baseline'] = before
        added_items = []
        for update in plan['goods_updates']:
            item = next(i for i in items if i['name'] == update['name'])
            meta = row_meta(item)
            if meta.get('settlement_binding_id') != binding_id:
                meta['settlement_original_values'] = {field: item.get(field) for field in GOODS_FIELDS}
            meta.update(settlement_binding_id=binding_id, settlement_line_key=update['line_key'], settlement_source_snapshot=expense['snapshot'])
            changed_identity = any(str(item.get(k) or '') != str(update['values'].get(k) or '') for k in ('material_code', 'unit', 'spec_model'))
            quantity_changed = Decimal(str(item.get('quantity') or 0)) != Decimal(str(update['values']['quantity']))
            if changed_identity or quantity_changed:
                meta['settlement_packing_review'] = True
                meta.setdefault('settlement_packing_quantity_at_change', item.get('actual_shipped_qty'))
            values = dict(update['values'])
            if quantity_changed:
                if meta.get('goods_value_source') == 'derived_quantity_unit_price':
                    values['goods_value'] = str(Decimal(str(item.get('unit_price') or 0)) * Decimal(str(values['quantity'])))
                elif item.get('goods_value'):
                    meta['settlement_purchase_value_review'] = True
            meta['settlement_applied_values'] = dict(update['values'])
            values.update({key: 0 for key in DERIVED_FIELDS})
            values['extra_json'] = dumps(meta)
            ledger.put('item', item['name'], values)
        for index, addition in enumerate(plan['goods_additions']):
            meta = {'settlement_binding_id': binding_id, 'settlement_line_key': addition['line_key'],
                    'settlement_source_snapshot': expense['snapshot'], 'settlement_created': True, 'settlement_packing_review': True,
                    'settlement_applied_values': addition['values']}
            values = dict(addition['values'], batch=batch['name'], version=version['name'], row_no=len(items)+index+1, source_type='oa_logistics', extra_json=dumps(meta))
            added_items.append(ledger.create('item', values)['name'])
        # Only a positively identified complete table may retire rows. Their full evidence is retained below.
        retired = binding.setdefault('retired_items', {})
        for name in plan['remove_items']:
            item = next(i for i in items if i['name'] == name)
            meta = row_meta(item)
            retired[meta.get('settlement_origin_item') or name] = item
            ledger.delete('item', name)
        for rule in rules:
            if rule['name'] in plan['disable_rules'] or rule.get('source_binding_id') == binding_id:
                ledger.put('rule', rule['name'], {'is_enabled': 0, 'is_active': 0, **({'is_final': 0} if rule.get('source_binding_id') == binding_id else {})})
        basis = next((r.get('allocation_basis') for r in rules if r['name'] in plan['disable_rules'] and r.get('allocation_basis')), 'goods_value')
        for index, rule in enumerate(plan['rules']):
            # Include snapshot in the physical rule identity; prior rows remain auditable and disabled.
            ledger.create('rule', {**rule, 'batch': batch['name'], 'version': version['name'],
                                   'allocation_basis': basis, 'basis_field': '', 'priority_no': index,
                                   'remark': '最终物流采购支出；费用范围：' + ','.join(plan['coverage'])})
        if has_documents:
            # Complete final cargo may add/change identities that were unmatched
            # in the initial logistics entry. Replan before this atomic apply ends.
            sync_logistics_documents(store, ledger, logistics, batch['name'], actor)
        remaining = ledger.rows('item', batch=batch['name'], version=version['name'])
        issues = application_issues(ledger, version, expense, remaining, plan)
        application_id = digest(binding_id, expense['snapshot'], version['name'], effective_hash)
        store.insert('application', {'id': application_id, 'binding_id': binding_id,
                     'snapshot': digest(expense['snapshot'], effective_hash), 'version': version['name'], 'status': 'applied',
                     'data': dumps({'source_snapshot': expense['snapshot'], 'expense_id': expense['id'], 'cost_hash': expense['cost_hash'],
                                   'effective_hash': effective_hash, 'actor': actor, 'before': before, 'plan': plan,
                                   'fx_evidence': {k: v for k, v in version.items() if k.startswith('fx_')},
                                   'added_items': added_items, 'applied_at': utcnow()})})
        binding.update(application_status='applied_pending' if issues else 'applied', issues=issues,
                       applied_hash=effective_hash, applied_cost_hash=expense['cost_hash'], source_snapshot=expense['snapshot'],
                       version=version['name'], last_application=application_id)
        save_binding(store, binding)
        ledger.put('version', version['name'], {'calculated_at': None, 'summary_snapshot_json': '{}'})
        ledger.put('batch', batch['name'], {'status': 'Dirty', 'confirm_status': 'Pending', 'is_locked': 0, 'item_count': len(remaining)})
        store.audit(binding_id, 'apply', actor, application_id=application_id, snapshot=expense['snapshot'], version=version['name'])
        return binding


def reverse_binding(store, ledger, old, new, actor):
    """Called inside the replacement transaction. Restore only fields still owned by old source."""
    batch = application_context(store, ledger, old)
    if not batch:
        return
    if locked(batch):
        raise ValueError('批次正在编辑，请结束编辑后更正关联')
    version = mutable_version(ledger, batch)
    items = ledger.rows('item', batch=batch['name'], version=version['name'])
    baseline = old.get('baseline') or {}
    for item in items:
        meta = row_meta(item)
        if meta.get('settlement_binding_id') != old['id']:
            continue
        if meta.get('settlement_created'):
            # Retain manually supplemented rows pending explicit mapping rather than discard them.
            if item.get('manual_override_flag') or any(item.get(k) for k in PACKING_FIELDS):
                meta['settlement_packing_review'] = True
                meta.pop('settlement_binding_id', None)
                ledger.put('item', item['name'], {'extra_json': dumps(meta), 'manual_override_flag': 1})
            else:
                ledger.delete('item', item['name'])
            continue
        original = meta.get('settlement_original_values') or {}
        applied = meta.get('settlement_applied_values') or {}
        values = {k: v for k, v in original.items() if str(item.get(k) or '') == str(applied.get(k) or '')}
        for key in list(meta):
            if key.startswith('settlement_') and key != 'settlement_origin_item':
                meta.pop(key)
        values['extra_json'] = dumps(meta)
        values.update({key: 0 for key in DERIVED_FIELDS})
        if 'quantity' in values and meta.get('goods_value_source') == 'derived_quantity_unit_price':
            values['goods_value'] = str(Decimal(str(values['quantity'] or 0)) * Decimal(str(item.get('unit_price') or 0)))
        ledger.put('item', item['name'], values)
    current_origins = {row_meta(i).get('settlement_origin_item') or i['name'] for i in ledger.rows('item', batch=batch['name'], version=version['name'])}
    for origin, retired in (old.get('retired_items') or {}).items():
        if origin in current_origins:
            continue
        meta = row_meta(retired)
        if meta.get('settlement_created'):
            continue
        values = clean_copy(retired)
        values.update(meta.get('settlement_original_values') or {})
        meta = {k: v for k, v in meta.items() if not k.startswith('settlement_')}
        meta['settlement_origin_item'] = origin
        values.update(version=version['name'], extra_json=dumps(meta))
        values.update({key: 0 for key in DERIVED_FIELDS})
        ledger.create('item', values)
    for rule in ledger.rows('rule', batch=batch['name'], version=version['name']):
        if rule.get('source_binding_id') == old['id']:
            ledger.put('rule', rule['name'], {'is_final': 0, 'is_enabled': 0, 'is_active': 0})
    # Preserve retired rows and rule beforeimages in audit; do not silently reactivate estimates.
    new.update(baseline=None, retired_items={}, version=version['name'], last_application=None, applied_hash=None, applied_cost_hash=None,
               issues=['关联已更正，等待新采购支出资料应用'], application_status='pending')
    ledger.put('batch', batch['name'], {'status': 'Dirty', 'confirm_status': 'Pending', 'is_locked': 0})
    store.audit(old['id'], 'reverse', actor, old=old, retired_evidence=baseline, version=version['name'])


PACKING_FIELDS = ('actual_shipped_qty', 'gross_weight_kg', 'volume_m3', 'volume_weight_kg', 'chargeable_weight_kg', 'weight_ratio')


def application_issues(ledger, version, expense, items, plan):
    issues = list(plan.get('goods_pending') or [])
    if any(row_meta(i).get('settlement_packing_review') for i in items):
        issues.append('采购数量或物料变化，需核对原重量、体积及装箱数量')
    if any(row_meta(i).get('settlement_purchase_value_review') for i in items):
        issues.append('数量变化，需核对独立来源商品货值')
    currencies = {r['currency'] for r in plan.get('rules', [])}
    for field, label, required in [('fx_usd_to_rmb', 'USD 兑 RMB', 'USD' in currencies), ('fx_rmb_to_mxn', 'RMB 兑 MXN', True)]:
        if required:
            try:
                value = Decimal(str(version.get(field) or 0))
                valid = value.is_finite() and value > 0
            except Exception:
                valid = False
            if not valid:
                issues.append('缺少有效 ' + label + ' 汇率')
    return sorted(set(issues))


def refresh_application_state(store, ledger, binding, expense):
    application = store.get('application', binding.get('last_application', '')) or {}
    version = ledger.get('version', binding['version'])
    items = ledger.rows('item', batch=version['batch'], version=version['name'])
    issues = application_issues(ledger, version, expense, items, application.get('plan') or {})
    return pending(store, binding, 'applied_pending' if issues else 'applied', issues)


def item_review(item):
    meta = row_meta(item)
    return {'item_name': item['name'], 'revision': digest(item),
            **{k: item.get(k) for k in GOODS_FIELDS + PACKING_FIELDS + ('unit_price', 'goods_value')},
            'packing_quantity': item.get('actual_shipped_qty') if item.get('actual_shipped_qty') is not None else meta.get('packing_quantity') or meta.get('packing_list_quantity'),
            'packing_pending': bool(meta.get('settlement_packing_review')),
            'goods_value_pending': bool(meta.get('settlement_purchase_value_review')),
            'packing_candidates': list((meta.get('settlement_packing_candidates') or {}).values())}


def resolve_item_checks(store, ledger, binding_id, expected_revision, selections, reason, actor):
    if not reason.strip() or not selections or len(selections) > 200:
        raise ValueError('请选择待核对行并填写核对说明')
    with store.atomic():
        binding = store.get('binding', binding_id, lock=True)
        if not binding or binding['revision'] != int(expected_revision):
            raise ValueError('关联已变化，请刷新')
        batch = application_context(store, ledger, binding)
        if not batch or locked(batch):
            raise ValueError('批次正在编辑或尚未对应，请结束编辑后核对')
        version = ledger.get('version', batch['current_version'], lock=True)
        if version['status'] == 'Confirmed' or batch.get('writeback_status') == 'Success' or binding.get('version') != version['name']:
            raise ValueError('只能核对当前调整草稿，已确认版本保留历史')
        for selection in selections:
            item = ledger.get('item', selection['item_name'], lock=True)
            if not item or item.get('batch') != batch['name'] or item.get('version') != version['name']:
                raise ValueError('物料不属于当前版本')
            if item_review(item)['revision'] != selection.get('expected_item_hash'):
                raise ValueError('物料或装箱资料已变化，请刷新后核对')
            meta = row_meta(item)
            for flag, check in [('settlement_packing_review', 'packing_confirmed'), ('settlement_purchase_value_review', 'goods_value_confirmed')]:
                if selection.get(check) is True:
                    meta.pop(flag, None)
            ledger.put('item', item['name'], {'extra_json': dumps(meta)})
            store.audit(binding_id, 'verify_item', actor, item_name=item['name'], before=item_review(item), choices=selection, reason=reason)
        resolve_document_checks(store, batch['name'], version['name'], selections, actor, reason, ledger=ledger)
        ledger.put('version', version['name'], {'calculated_at': None, 'summary_snapshot_json': '{}'})
        ledger.put('batch', batch['name'], {'status': 'Dirty'})
        return refresh_application_state(store, ledger, binding, store.get('source', binding['expense_id']))


def validate_application_preview(store, ledger, binding, expected_snapshot, expected_version):
    expense = store.get('source', binding['expense_id'], lock=True)
    batch = application_context(store, ledger, binding)
    if not expected_snapshot or expense['snapshot'] != expected_snapshot:
        raise ValueError('采购支出已变化，请刷新明细和费用后重新确认')
    if not expected_version or not batch or batch.get('current_version') != expected_version:
        raise ValueError('当前成本版本已变化，请刷新后重新确认')


def resolve_document_checks(store, batch_name, version_name, selections, actor, reason, *, ledger):
    from .document_writer import packing_state_hash
    acknowledged = {s['item_name'] for s in selections if s.get('packing_confirmed') is True}
    for candidate in store.find('document_sync', batch=batch_name, limit=1):
        state = store.get('document_sync', candidate['id'], lock=True)
        if state.get('version') != version_name or state['status'] == 'queued':
            continue
        remaining = {key: [row for row in rows if row.get('item_name') not in acknowledged] for key,rows in (state.get('reviews') or {}).items()}
        remaining = {key: rows for key,rows in remaining.items() if rows}
        if remaining == state.get('reviews'):
            continue
        state.update(reviews=remaining, blocking=bool(remaining), status='review' if remaining else 'applied',
                     items_hash=packing_state_hash(ledger.rows('item', batch=batch_name, version=version_name)),
                     issues=sorted({row.get('reason') or '装箱行待核对' for rows in remaining.values() for row in rows} | set(state.get('document_issues') or [])))
        store.put('document_sync', {key:state[key] for key in ('id','source_id','batch','status')} | {'data':dumps(state)})
        store.audit(state['source_id'],'verify_document_rows',actor,items=sorted(acknowledged),reason=reason,remaining=remaining)
