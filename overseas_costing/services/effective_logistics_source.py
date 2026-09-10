"""Server-owned logistics evidence root. A confirmed binding never falls back."""
from __future__ import annotations
import json
from copy import deepcopy
from urllib.parse import urlparse, parse_qs

from .logistics_settlement.model import digest

POLICY_VERSION = 'procurement-source-2'
CONTEXT_FIELDS = ('separate_adoption', 'freight', 'packing', 'policy_version', 'batch', 'cost_version', 'root_kind', 'root_source_id', 'corp_id', 'instance_id',
                  'binding_id', 'binding_revision', 'source_snapshot', 'approved', 'invalid', 'available', 'fingerprint')


def public_context(context):
    return {key: context[key] for key in CONTEXT_FIELDS if key in (context or {})}


def context_for_source(source, binding=None, version_name=None, batch_name=None):
    """Pure, public context: no raw fields, objects, URLs or filesystem paths."""
    source = source or {}
    binding = binding or {}
    result = {
        'policy_version': POLICY_VERSION,
        'batch': str(batch_name or ''),
        'cost_version': str(version_name or ''),
        'root_kind': 'expense' if binding else 'logistics',
        'root_source_id': str(binding.get('expense_id') or source.get('id') or ''),
        'corp_id': str(source.get('corp') or source.get('corp_id') or ''),
        'instance_id': str(source.get('instance') or source.get('instance_id') or ''),
        'binding_id': str(binding.get('id') or ''),
        'binding_revision': binding.get('revision') if binding else None,
        'source_snapshot': str(source.get('snapshot') or ''),
        'approved': bool(source.get('approved') and (not binding or source.get('kind') in (None, 'expense'))),
        'invalid': bool(source.get('invalid')),
        'available': bool(source.get('id') and source.get('snapshot') and source.get('available', True)),
    }
    result['fingerprint'] = digest(result)
    return result


def _legacy_source_bundle(batch_name, version_name=None, *, store=None, ledger=None, lock=False):
    """Internal local read, returning context plus source. No upstream clients."""
    from .logistics_settlement.reviewed_cargo import resolve_reviewed_source
    if ledger is None:
        from .logistics_settlement.ledger import FrappeLedger
        ledger = FrappeLedger()
    if store is None:
        from .logistics_settlement.runtime import installed
        if installed():
            from .logistics_settlement.store import Store
            store = Store.frappe()
    # Same order as settlement binding mutations: match lock before batch lock.
    if store is not None and lock:
        store.get('state', 'match_lock', lock=True)
    mapping = store.find('batch_map', batch=batch_name, limit=1) if store is not None else []
    bindings = store.find('binding', logistics_id=mapping[0]['source_id'], limit=1) if mapping else []
    binding = store.get('binding', bindings[0]['id'], lock=lock) if bindings else None
    source_id = binding['expense_id'] if binding else mapping[0]['source_id'] if mapping else ''
    source = store.get('source', source_id, lock=lock) if store is not None and source_id else None
    batch = ledger.get('batch', batch_name, lock=lock) or {}
    version_name = version_name or batch.get('current_version') or ''
    version = ledger.get('version', version_name, lock=lock) if version_name else None
    if version and version.get('batch') != batch_name:
        raise ValueError('版本不属于当前批次。')
    if version and version_name != batch.get('current_version'):
        frozen = json_dict(version.get('extra_json')).get('effective_logistics_source') or {}
        if frozen and frozen.get('policy_version') == POLICY_VERSION:
            snapshot = store.get('snapshot', frozen.get('source_snapshot', '')) if store is not None else None
            source = {**snapshot, 'id': snapshot['source_id'], 'snapshot': snapshot['id']} if snapshot else {
                'id': frozen['root_source_id'], 'snapshot': frozen.get('source_snapshot'), 'corp': frozen.get('corp_id'),
                'instance': frozen.get('instance_id'), 'approved': False, 'invalid': frozen.get('invalid'), 'available': False}
            binding = {'id': frozen['binding_id'], 'revision': frozen['binding_revision'], 'expense_id': frozen['root_source_id']} if frozen.get('binding_id') else None
            source = resolve_reviewed_source(store, source, binding, version_name)
            context = context_for_source(source, binding, version_name, batch_name)
            return {'context': context, 'source': source, 'binding': binding, 'batch': batch, 'version': version}
        # Pre-policy history can only use its own adopted application snapshot.
        applications = store.find('application', version=version_name) if store is not None else []
        if applications:
            app = max(applications, key=lambda a: str(a.get('applied_at') or ''))
            snapshot_id = app.get('source_snapshot') or app.get('snapshot')
            snapshot = store.get('snapshot', snapshot_id) if isinstance(snapshot_id, str) else snapshot_id
            source = ({**snapshot, 'id': snapshot.get('source_id') or snapshot.get('id'), 'snapshot': snapshot_id}
                      if snapshot else None)
            historical_binding = store.get('binding', app['binding_id']) or {}
            binding = {'id': app['binding_id'], 'revision': app.get('binding_revision'),
                       'expense_id': (source or {}).get('id') or historical_binding.get('expense_id')}
        else:
            binding = None
            source = store.get('source', mapping[0]['source_id']) if mapping else None
    source = resolve_reviewed_source(store, source, binding,
        version_name if version_name != batch.get('current_version') else None)
    return {'context': context_for_source(source, binding, version_name, batch_name),
            'source': source, 'binding': binding, 'batch': batch, 'version': version}


def load_source_bundle(batch_name, version_name=None, *, store=None, ledger=None, lock=False):
    if store is None:
        from .logistics_settlement.runtime import installed
        if installed():
            from .logistics_settlement.store import Store
            store=Store.frappe()
    if ledger is None:
        from .logistics_settlement.ledger import FrappeLedger
        ledger=FrappeLedger()
    bundle=_legacy_source_bundle(batch_name,version_name,store=store,ledger=ledger,lock=lock)
    if store is None:return bundle
    version=bundle['version'] or {};meta=json_dict(version.get('extra_json'))
    if bundle.get('binding') and not meta.get('freight_settlement'):return bundle
    from .logistics_settlement.freight_adoption import context as freight_context
    freight=freight_context(store,ledger,batch_name,version.get('name'))
    ctx=dict(bundle['context']);packing=dict(ctx)
    frozen=(meta.get('effective_logistics_source') or {}).get('packing') or {}
    if freight['historical'] and frozen:
        snapshot=store.get('snapshot',frozen.get('source_snapshot',''))
        source={**(snapshot or {}),'id':frozen.get('root_source_id'),'snapshot':frozen.get('source_snapshot'),'available':bool(snapshot)}
        binding={'id':frozen['binding_id'],'revision':frozen['binding_revision'],'expense_id':frozen['root_source_id']} if frozen.get('binding_id') else None
        packing=context_for_source(source,binding,version.get('name'),batch_name);ctx=dict(packing)
        bundle.update(source=source,binding=binding)
    review=store.get('packing_review',freight.get('packing_review_id') or '')
    if review and review.get('status')=='applied':
        snapshot=store.get('snapshot',review['source_snapshot'])
        current=store.get('source',review['source_id']) or {}
        active=snapshot if freight['historical'] else current
        mapping=store.find('batch_map',batch=batch_name)
        original=store.get('source',mapping[0]['source_id']) if mapping else {}
        logistics_ok=freight['historical'] or (original and not original.get('invalid') and original.get('snapshot')==review['logistics_snapshot'])
        available=bool(logistics_ok and active and active.get('approved') and not active.get('invalid') and (freight['historical'] or current.get('snapshot')==review['source_snapshot']))
        # Only adopted shipment rows, never the raw monthly workbook or another ticket's comments.
        goods=[]
        for item in review.get('adopted_items') or []:
            row=json_dict(item.get('extra_json')).get('settlement_cargo') or {}
            goods.append(row or {k:item.get(k) for k in ('material_code','product_name','spec_model','quantity','unit')})
        source={**(snapshot or {}),'id':review['source_id'],'snapshot':review['source_snapshot'],'available':available,'approved':available,
                'invalid':bool(active.get('invalid')),'goods':goods,'goods_complete':False,'documents':[],'attachments':[],
                'fields':{'本票已采用装箱明细':goods},'raw':{'formComponentValues':[{'name':'本票已采用装箱明细','componentType':'TableField','value':goods}],'comments':[]}}
        binding={'id':review['id'],'revision':review['revision'],'expense_id':review['source_id']}
        packing=context_for_source(source,binding,version.get('name'),batch_name)
        bundle.update(source=source,binding=binding)
        ctx=dict(packing)
    ctx.update(policy_version='shipment-sources-1',separate_adoption=True,freight=freight,packing=packing)
    ctx['fingerprint']=digest({k:v for k,v in ctx.items() if k not in ('fingerprint','freight')}, {k:v for k,v in freight.items() if k!='historical'})
    bundle['context']=ctx
    return bundle


def resolve_source_context(batch_name, version_name=None, *, store=None, ledger=None, lock=False):
    return load_source_bundle(batch_name, version_name, store=store, ledger=ledger, lock=lock)['context']


def current_source_bundle(batch_name, version_name=None, *, lock=False):
    """Legacy sites without the local settlement schema retain their old resolver."""
    from .logistics_settlement.runtime import installed
    return load_source_bundle(batch_name, version_name, lock=lock) if installed() else None


def require_available(context):
    if context.get('root_kind') == 'expense' and (
        not context.get('available') or not context.get('approved') or context.get('invalid')
    ):
        raise ValueError('当前关联采购支出缺失、未批准或已失效，不能使用资料；请核对当前来源。')


def require_readable(context):
    if context.get('root_kind') == 'expense' and not context.get('available'):
        raise ValueError('当前关联采购支出缺少本地归档，暂时无法分析；请等待同步。')


def json_dict(value):
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def attachment_allowed(row, bundle, *, for_analysis=False):
    from .logistics_settlement.document_writer import document_retired
    context = bundle['context']
    if context['root_kind'] != 'expense':
        return True
    meta = json_dict(row.get('parse_result_json'))
    descriptor = meta.get('settlement_document') or {}
    documents = {str(d.get('id')) for d in (bundle.get('source') or {}).get('documents') or [] if not document_retired(d)}
    return bool(
        str(row.get('source_type') or '').upper() == 'OA'
        and str(row.get('version') or '') == context['cost_version']
        and str(meta.get('process_instance_id') or meta.get('instance_id') or '') == context['instance_id']
        and str(meta.get('corp_id') or '') == context['corp_id']
        and descriptor.get('source_id') == context['root_source_id']
        and str(descriptor.get('document_id') or '') in documents
        and not descriptor.get('retired')
        and (for_analysis or (not descriptor.get('audit_only') and not meta.get('approval_excluded') and meta.get('cost_source_allowed') is not False))
    )


def explicit_wiki_sources(source):
    """Only exact workbook+sheet pairs explicitly present in the effective root."""
    result = set()
    def visit(value):
        if isinstance(value, dict):
            workbook = value.get('workbookId') or value.get('workbook_id')
            sheet = value.get('sheetId') or value.get('sheet_id')
            if workbook and sheet:
                result.add(f'{workbook}:{sheet}')
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            # No catalogue similarity or old snapshot inference.
            for token in value.split():
                if token.startswith(('https://', 'http://')):
                    query = parse_qs(urlparse(token).query)
                    workbook = (query.get('workbookId') or query.get('workbook_id') or [''])[0]
                    sheet = (query.get('sheetId') or query.get('sheet_id') or [''])[0]
                    if workbook and sheet:
                        result.add(f'{workbook}:{sheet}')
    visit((source or {}).get('raw') or {})
    return result


def approval_detail_for_bundle(bundle):
    from .dingtalk_approval_service import _approval
    context = bundle['context']
    source = bundle.get('source') or {}
    raw = deepcopy(source.get('raw') or {})
    raw.update(processInstanceId=context['instance_id'], corpId=context['corp_id'],
               status=source.get('status'), result=source.get('approval_result'), businessId=source.get('approval_no'))
    operations = []
    for key in ('operationRecords', 'operation_records', 'comments'):
        value = raw.get(key) or []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = []
        for row in value if isinstance(value, list) else []:
            if row not in operations:
                operations.append(row)
    raw['operationRecords'] = operations
    approval = _approval(raw, [])
    approval['excluded'] = not context['available']
    approval['analysis_only'] = not context['approved'] or context['invalid']
    approval['exclusion_reason'] = '当前采购支出缺少本地归档' if approval['excluded'] else ''
    return {'ok': True, 'main_approval': approval, 'linked_purchase_approvals': [],
            'excluded_linked_purchase_approvals': [], 'source_context': context,
            'source_updated_at': source.get('source_updated_at') or ''}


def validate_packing_source(batch_name, kind, source_id, *, attachment=None, bundle=None):
    bundle = bundle if bundle is not None else current_source_bundle(batch_name)
    if not bundle or bundle['context']['root_kind'] != 'expense':
        return bundle
    require_readable(bundle['context'])
    if kind in {'manual_attachment', 'approval_attachment'}:
        if not attachment or not attachment_allowed(attachment, bundle, for_analysis=True):
            raise ValueError('所选附件不属于当前关联采购支出及成本版本。')
    elif kind == 'wiki_sheet':
        if source_id not in explicit_wiki_sources(bundle.get('source')):
            raise ValueError('该装箱计划表没有由当前关联采购支出明确链接。')
    elif kind == 'approval_comment':
        comments = approval_detail_for_bundle(bundle)['main_approval']['timeline']
        if not any(row.get('source_id') == source_id for row in comments):
            raise ValueError('所选评论不属于当前关联采购支出。')
    return bundle


PHYSICAL_FIELDS = ('actual_shipped_qty', 'shipped_uom', 'net_weight_kg', 'gross_weight_kg',
                   'volume_m3', 'volume_weight_kg', 'chargeable_weight_kg', 'weight_ratio')


def project_ai_items(items, bundle):
    """Independent AI input projection; raw historical fields never enter prompts."""
    if not bundle or bundle['context']['root_kind'] != 'expense':
        return items
    context = bundle['context']
    require_readable(context)
    source = bundle.get('source') or {}
    result = []
    from .logistics_settlement.model import identity
    from overseas_costing.utils.field_mapper import normalize_unit
    def key(row):
        return (identity(row.get('material_code')), identity(row.get('spec_model')), normalize_unit(row.get('unit') or row.get('purchase_uom')))
    goods_rows = source.get('goods') or []
    used = set()
    for goods in goods_rows:
        matches = [item for item in items if goods.get('line_key') and json_dict(item.get('extra_json')).get('settlement_line_key') == goods['line_key']]
        if not matches and sum(key(row) == key(goods) for row in goods_rows) == 1:
            matches = [item for item in items if key(item) == key(goods)]
        if len(matches) != 1:
            continue
        item = matches[0]
        if item.get('name') in used:
            continue
        used.add(item.get('name'))
        meta = json_dict(item.get('extra_json'))
        projected = {key: goods.get(key) for key in ('material_code', 'product_name', 'spec_model', 'quantity')}
        projected.update(unit_price=None, goods_value=None)
        projected.update(name=item['name'], source_doc_no=source.get('approval_no') or source.get('instance'),
                         purchase_uom=goods.get('unit'), unit_price_uom=goods.get('unit'), purchase_currency=goods.get('currency'))
        # A traceable standalone purchase may contribute price only, never its quantity/value/packing.
        price = goods.get('merchandise_price') or {}
        if price.get('present'):
            if not price.get('ambiguous'):
                projected.update(unit_price=price.get('price'), unit_price_uom=price.get('price_uom'), purchase_currency=price.get('currency'))
        else:
            association = meta.get('logistics_row') or {}
            fact = association.get('purchase_fact') or {}
            if not (fact.get('source_doc_no') or association.get('purchase_source_id')):
                fact = item if item.get('source_doc_no') and meta.get('goods_value_source') else {}
            if fact:
                projected.update(unit_price=fact.get('unit_price'), unit_price_uom=fact.get('unit_price_uom') or fact.get('purchase_uom'), purchase_currency=fact.get('purchase_currency'))
        from .effective_source_values import project_source_values
        values = project_source_values(item, context)
        projected.update({key: values.get(key) for key in PHYSICAL_FIELDS})
        projected['extra_json'] = {'effective_logistics_source': context,
            'settlement_cargo': {**goods, 'source_snapshot': context['source_snapshot'], 'binding_id': context['binding_id']},
            'settlement_physical': deepcopy((values.get('extra_json') or {}).get('settlement_physical') or {})}
        result.append(projected)
    return result


def physical_update_values(item, updates, context, evidence):
    """Persist current packing adoption without overwriting any raw historical field."""
    from .effective_source_values import PHYSICAL_FIELDS as physical_fields, physical_overlay_update
    if context.get('root_kind') != 'expense':
        return updates
    meta = physical_overlay_update(item, context, updates, evidence=evidence)
    result = dict(updates) if context.get('separate_adoption') else {key: value for key, value in updates.items() if key not in physical_fields}
    result['extra_json'] = json.dumps(meta, ensure_ascii=False, default=str, separators=(',', ':'))
    return result
