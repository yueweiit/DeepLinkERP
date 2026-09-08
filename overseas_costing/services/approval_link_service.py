"""Read-only purchase provenance; archive availability never gates costing or imports."""
from __future__ import annotations

from overseas_costing.services import dingtalk_approval_service as approvals


LABELS = {
    'linked': '', 'unlinked': '未关联采购审批', 'unresolved': '采购审批待核实',
    'ambiguous': '采购明细匹配不唯一', 'error': '来源核验失败，请重试',
}


def _text(value):
    return str(value or '').strip()


def _link(status, approval_no='', instance_id='', reason=''):
    return dict(status=status, label=LABELS[status], reason=reason,
                approval_no=approval_no, instance_id=instance_id)


def _purchase_index(batch_name):
    if approvals.frappe is None:
        return []
    batch = approvals.frappe.db.get_value(
        'Overseas Cost Batch', batch_name,
        ['name', 'batch_no', 'source_type', 'source_approval_no', 'source_instance_id', 'extra_json'],
        as_dict=True,
    ) or {}
    main_id = _text(batch.get('source_instance_id'))
    if not main_id:
        return []
    candidates = [value for value in approvals._linked_instance_ids(batch.get('extra_json')) if value != main_id]
    bundle = approvals._get_approval_source().get_instance_bundle([main_id, *candidates])
    instances = bundle.get('instances') or {}
    main = instances.get(main_id)
    if not isinstance(main, dict) or not approvals._approval_matches_batch(batch, main):
        return []
    trusted = set(approvals._trusted_linked_instance_ids(main))
    result = []
    for instance_id in candidates:
        payload = instances.get(instance_id)
        if instance_id not in trusted or not isinstance(payload, dict):
            continue
        actual_id = _text(payload.get('processInstanceId') or payload.get('process_instance_id'))
        if actual_id != instance_id:
            continue
        result.append((_text(payload.get('businessId') or payload.get('business_id')), instance_id))
    return result


def attach_approval_links(batch_name, rows):
    """Return copies annotated with one batched local archive read, no persistence."""
    items = [dict(row) for row in rows]
    index, failed = [], False
    if any(_text(row.get('source_doc_no')) or _text(row.get('dingtalk_instance_id')) for row in items):
        try:
            index = _purchase_index(batch_name)
        except Exception:
            failed = True
    for row in items:
        number, instance = _text(row.get('source_doc_no')), _text(row.get('dingtalk_instance_id'))
        matches = [(no, iid) for no, iid in index if (number and number in (no, iid)) or (instance and instance == iid)]
        if not number and not instance:
            link = _link('unlinked', reason='当前物料没有可用的采购审批标识。')
        elif failed:
            link = _link('error', number, instance, '本地审批来源暂不可用。')
        elif len(matches) == 1:
            link = _link('linked', *matches[0])
        elif len(matches) > 1:
            link = _link('ambiguous', number, instance, '物料标识对应多个采购审批，需核实来源。')
        else:
            link = _link('unresolved', number, instance, '当前本地可信采购审批来源无法核实此标识。')
        row['approval_link'] = link
    return items


def attach_preview_approval_links(batch_name, comparison, existing):
    """Decorate only after signing the financial comparison, preserving raw source rows."""
    from overseas_costing.services.material_import_service import _stable_item_key
    links = {_stable_item_key(row): row['approval_link'] for row in attach_approval_links(batch_name, existing)}
    for row in comparison.get('rows') or []:
        _attach_match(row, row.get('match_status'), links.get(row.get('target_stable_line_key')))
    selected_by_source_row = {}
    if comparison.get('is_merged_preview'):
        for row in comparison.get('rows') or []:
            if row.get('match_status') == 'matched':
                for number in row.get('source_rows') or [row.get('source_row')]:
                    selected_by_source_row[str(number)] = row.get('target_stable_line_key')
    for state in (comparison.get('source_grid') or {}).get('row_states') or []:
        status = state.get('state')
        if status in {'header', 'other'}:
            continue
        keys = state.get('target_stable_line_keys') or []
        selected_key = selected_by_source_row.get(str(state.get('source_row')))
        if selected_key:
            _attach_match(state, 'matched', links.get(selected_key))
            continue
        _attach_match(state, 'unmatched' if status == 'outside' else status,
                      links.get(keys[0]) if len(keys) == 1 else None)


def _attach_match(row, status, link):
    row['match_status'] = status
    row['match_label'] = {'unmatched': '未匹配本批采购明细', 'choice_required': '采购明细匹配不唯一'}.get(status, '')
    row['match_reason'] = row['match_label']
    if status == 'matched' and link:
        row['approval_link'] = dict(link)
    elif status == 'choice_required':
        row['approval_link'] = _link('ambiguous', reason='来源行对应多个本批采购明细，需选择目标。')
