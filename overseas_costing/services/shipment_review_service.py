"""Bind deterministic workbook valuations to the server-owned reconciliation."""
import json
from copy import deepcopy
from overseas_costing.services.shipment_cost_service import object_json
from overseas_costing.services.shipment_valuation_service import _confirmed_manual


def merge_shipment_fills(reconciliation, documents, selected_sheets, *, required_item_names=()):
    by_name = {row['name']:row for row in reconciliation['payload']['rows']}
    choices = {}
    attempted, errors = set(required_item_names), []
    for document in documents:
        for fill in document.get('shipment_fills') or []:
            attempted.update(fill.get('attempted_item_names') or [])
            source_id = (document.get('sheet_source_ids') or {}).get(fill.get('sheet_name')) or fill.get('source_id')
            if (source_id, fill.get('sheet_name')) not in selected_sheets:
                continue
            errors.extend(fill.get('warnings') or [])
            for name, valuation in fill.get('valuations', {}).items():
                if name in by_name:
                    valuation = deepcopy(valuation)
                    for ref in valuation.get('source_refs') or []:
                        if ref.get('source_id') == fill.get('source_id'):
                            ref['source_id'] = source_id
                    choices.setdefault(name, []).append(valuation)
    for name, row in by_name.items():
        metadata = object_json(row.get('extra_json'))
        saved = metadata.get('shipment_valuation')
        if _confirmed_manual(saved):
            continue
        values = choices.get(name, [])
        if not values and name not in attempted and saved is None:
            continue  # Untouched legacy data keeps its existing purchase-value semantics.
        signatures = {json.dumps({k:v.get(k) for k in ('amount_rmb','quantity','uom')},sort_keys=True) for v in values}
        if len(signatures) != 1:
            message = '装箱货值来源不一致' if values else '未能从本次所选资料核实发货货值'
            detail = '；'.join(dict.fromkeys(str(error) for error in errors))
            message = f'{row.get("material_code")} {message}；不会沿用旧自动估值或采购全额。{detail}'
            reconciliation['payload']['unresolved'].append({'message':message})
            metadata['shipment_valuation'] = {'amount_rmb':None, 'quantity':row.get('actual_shipped_qty'),
                'uom':row.get('shipped_uom'), 'method':'SOURCE_UNAVAILABLE',
                'error':'SHIPMENT_VALUATION_SOURCE_UNAVAILABLE','error_detail':message}
        else:
            metadata['shipment_valuation'] = values[0]
            reconciliation['source_refs'].extend(values[0].get('source_refs') or [])
        row['extra_json'] = json.dumps(metadata,ensure_ascii=False,sort_keys=True,default=str)
