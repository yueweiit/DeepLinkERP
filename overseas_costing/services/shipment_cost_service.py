"""Effective shipment values, without rewriting read-only purchase facts."""
import json
from decimal import Decimal, InvalidOperation
from overseas_costing.utils.field_mapper import normalize_unit


def object_json(value):
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def shipment_value(row):
    metadata = object_json(row.get('extra_json'))
    if 'settlement_cargo' in metadata:
        cargo = metadata.get('settlement_cargo')
        valuation = metadata.get('settlement_valuation')
        if not isinstance(cargo, dict) or not isinstance(valuation, dict):
            return {'amount_rmb':None, 'method':'SETTLEMENT_FINAL', 'error':'SETTLEMENT_SHIPMENT_VALUE_REQUIRED'}
        from overseas_costing.services.logistics_settlement.valuation import value_final_cargo
        expected = value_final_cargo(row, cargo, valuation.get('fx_context') or {})
        error = expected['error'] or ('SETTLEMENT_SHIPMENT_VALUE_STALE' if expected['input_fingerprint'] != valuation.get('input_fingerprint') else '')
        return {**valuation, 'amount_rmb':None if error else valuation.get('amount_rmb'), 'error':error}
    valuation = metadata.get('shipment_valuation')
    if valuation is None:
        return {'amount_rmb': row.get('goods_value'), 'method': 'LEGACY_PURCHASE', 'error': ''}
    if not isinstance(valuation, dict):
        return {'amount_rmb': None, 'method': 'INVALID', 'error': 'SHIPMENT_VALUATION_INVALID'}
    shipping = row.get('effective_shipping') or {}
    qty = shipping.get('quantity', row.get('actual_shipped_qty'))
    uom = shipping.get('uom') or row.get('shipped_uom') or row.get('unit')
    error = valuation.get('error') or ''
    if not error and (number(qty) != number(valuation.get('quantity')) or normalize_unit(uom) != normalize_unit(valuation.get('uom'))):
        error = 'SHIPMENT_VALUATION_STALE'
    if not error and (number(valuation.get('amount_rmb')) is None or number(valuation.get('amount_rmb')) < 0
                      or str(valuation.get('currency') or '').upper() not in {'RMB', 'CNY'}):
        error = 'SHIPMENT_VALUATION_INVALID'
    return {**valuation, 'amount_rmb': None if error else valuation.get('amount_rmb'), 'error': error}


def project_summaries(rows, precision=2):
    groups = {}
    for row in rows:
        project = str(row.get('project_collection') or '').strip() or '未归属项目'
        group = groups.setdefault(project, {'project_collection': project, 'item_keys': [],
            **{f: Decimal('0') for f in ('goods_value_rmb','gross_weight_kg','allocated_fees_rmb','direct_fees_rmb','total_cost_rmb')}})
        group['item_keys'].append(row.get('stable_line_key') or row.get('name'))
        for field in ('goods_value_rmb','gross_weight_kg','allocated_fees_rmb','direct_fees_rmb','total_cost_rmb'):
            group[field] += number(row.get(field)) or Decimal('0')
    return [{k: (format(v, 'f') if k == 'gross_weight_kg' else format(v, f'.{precision}f')) if isinstance(v, Decimal) else v
             for k,v in group.items()} for group in groups.values()]
