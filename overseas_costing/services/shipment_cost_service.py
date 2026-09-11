"""Effective shipment values, without rewriting read-only purchase facts."""
import json
from decimal import Decimal, InvalidOperation
from overseas_costing.utils.field_mapper import normalize_unit
from overseas_costing.services.logistics_settlement.model import currency, digest


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


def _decimal_text(value):
    amount = number(value)
    if amount is None:
        return None
    return format(amount.normalize(), 'f')


def shipment_input(row):
    shipping = row.get('effective_shipping') or {}
    quantity = row.get('actual_shipped_qty')
    if quantity in (None, ''):
        quantity = shipping.get('quantity', row.get('quantity'))
    uom = row.get('shipped_uom') or shipping.get('uom') or row.get('unit')
    return {'quantity': _decimal_text(quantity), 'uom': normalize_unit(uom)}


def shipment_input_fingerprint(row):
    return digest(shipment_input(row))


def build_manual_shipment_valuation(row, amount_rmb, *, actor, reason='', confirmed_at=''):
    amount = number(amount_rmb)
    if amount is None or amount < 0:
        raise ValueError('本次发货货值必须是有限非负数字。')
    inputs = shipment_input(row)
    return {
        'amount_rmb': _decimal_text(amount),
        'currency': 'RMB',
        'quantity': inputs['quantity'],
        'uom': inputs['uom'],
        'input_fingerprint': digest(inputs),
        'confirmed': True,
        'manual': True,
        'actor': str(actor or ''),
        'confirmed_at': str(confirmed_at or ''),
        'reason': str(reason or ''),
        'method': 'manual_shipment_valuation',
        'status': 'manual',
        'error': '',
    }


def _manual_value(row, manual):
    if not isinstance(manual, dict) or not manual.get('confirmed') or not manual.get('manual'):
        return None
    amount = number(manual.get('amount_rmb'))
    valid = amount is not None and amount >= 0 and currency(manual.get('currency')) == 'RMB'
    stale = manual.get('input_fingerprint') != shipment_input_fingerprint(row)
    if stale:
        return {**manual, 'amount_rmb': None, 'prior_amount_rmb': _decimal_text(manual.get('amount_rmb')),
                'status': 'stale', 'error': 'MANUAL_SHIPMENT_VALUATION_STALE'}
    if not valid:
        return {**manual, 'amount_rmb': None, 'status': 'missing', 'error': 'MANUAL_SHIPMENT_VALUATION_INVALID'}
    return {**manual, 'amount_rmb': _decimal_text(amount), 'status': 'manual', 'error': ''}


def _status(error, value, default='automatic'):
    if 'STALE' in str(error or ''):
        return 'stale'
    if 'CONFLICT' in str(error or ''):
        return 'conflict'
    if error:
        return 'missing'
    if value.get('status') in {'automatic', 'manual', 'conflict', 'missing', 'stale'}:
        return value['status']
    return default


def shipment_value(row):
    metadata = object_json(row.get('extra_json'))
    manual = _manual_value(row, metadata.get('manual_shipment_valuation'))
    if manual is not None:
        return manual
    if 'settlement_cargo' in metadata:
        cargo = metadata.get('settlement_cargo')
        valuation = metadata.get('settlement_valuation')
        if not isinstance(cargo, dict) or not isinstance(valuation, dict):
            return {'amount_rmb':None, 'method':'SETTLEMENT_FINAL', 'status':'missing',
                    'error':'SETTLEMENT_SHIPMENT_VALUE_REQUIRED'}
        from overseas_costing.services.logistics_settlement.valuation import value_final_cargo
        expected = value_final_cargo(row, cargo, valuation.get('fx_context') or {})
        if expected['input_fingerprint'] != valuation.get('input_fingerprint'):
            error = 'SETTLEMENT_SHIPMENT_VALUE_STALE'
        elif valuation.get('status') == 'conflict':
            error = valuation.get('error') or 'SETTLEMENT_SHIPMENT_VALUE_CONFLICT'
        else:
            error = expected['error']
        status = _status(error, valuation)
        return {**valuation, 'amount_rmb':None if error else valuation.get('amount_rmb'),
                'status':status, 'error':error}
    valuation = metadata.get('shipment_valuation')
    if valuation is None:
        amount = number(row.get('goods_value'))
        valid = amount is not None and amount >= 0
        return {'amount_rmb': row.get('goods_value') if valid else None, 'method': 'LEGACY_PURCHASE',
                'status': 'automatic' if valid else 'missing', 'error': ''}
    if not isinstance(valuation, dict):
        return {'amount_rmb': None, 'method': 'INVALID', 'status':'missing', 'error': 'SHIPMENT_VALUATION_INVALID'}
    legacy_manual = _manual_value(row, {
        **valuation,
        'manual': valuation.get('manual') or valuation.get('manual_override') or valuation.get('manual_override_flag'),
        'input_fingerprint': valuation.get('input_fingerprint') or shipment_input_fingerprint({
            **row, 'actual_shipped_qty': valuation.get('quantity'), 'shipped_uom': valuation.get('uom')}),
    })
    if legacy_manual is not None:
        return legacy_manual
    shipping = row.get('effective_shipping') or {}
    qty = shipping.get('quantity', row.get('actual_shipped_qty'))
    uom = shipping.get('uom') or row.get('shipped_uom') or row.get('unit')
    error = valuation.get('error') or ''
    if not error and (number(qty) != number(valuation.get('quantity')) or normalize_unit(uom) != normalize_unit(valuation.get('uom'))):
        error = 'SHIPMENT_VALUATION_STALE'
    if not error and (number(valuation.get('amount_rmb')) is None or number(valuation.get('amount_rmb')) < 0
                      or str(valuation.get('currency') or '').upper() not in {'RMB', 'CNY'}):
        error = 'SHIPMENT_VALUATION_INVALID'
    return {**valuation, 'amount_rmb': None if error else valuation.get('amount_rmb'),
            'status': _status(error, valuation), 'error': error}


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
