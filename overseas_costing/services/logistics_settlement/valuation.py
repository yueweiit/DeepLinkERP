"""Final shipment value from independent purchase evidence, without rewriting it."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from .application import row_meta
from .model import currency, digest, number
from overseas_costing.utils.field_mapper import normalize_unit


def value_final_cargo(item, cargo, fx_context):
    meta = row_meta(item)
    association = meta.get('logistics_row') or {}
    fact = association.get('purchase_fact') or {}
    if not isinstance(fact, dict):
        fact = {}
    purchase_source = fact.get('source_doc_no') or association.get('purchase_source_id')
    if not purchase_source:
        fact = item
        purchase_source = item.get('source_doc_no')
    purchase_identity = meta.get('settlement_original_values') or item
    if fact is not item and fact.get('material_code'):
        purchase_identity = fact
    final_price = cargo.get('merchandise_price') or {}
    using_expense = final_price.get('present') is True
    if using_expense:
        fact = {'unit_price':final_price.get('price'), 'purchase_currency':final_price.get('currency'),
                'unit_price_uom':final_price.get('price_uom')}
        purchase_source = cargo.get('source_snapshot')
        purchase_identity = cargo
    final_code = str(cargo.get('material_code') or '').strip().casefold()
    purchase_code = str(purchase_identity.get('material_code') or '').strip().casefold()
    price = number(fact.get('unit_price'))
    qty = number(cargo.get('quantity'))
    purchase_currency = currency(fact.get('purchase_currency'))
    uom = normalize_unit(cargo.get('unit'))
    price_uom = normalize_unit(fact.get('unit_price_uom') or fact.get('purchase_uom') or fact.get('unit'))
    result = {'method': 'settlement_expense_unit_price' if using_expense else 'settlement_purchase_unit_price', 'quantity': qty, 'uom': uom, 'currency': 'RMB',
              'amount_rmb': None, 'error': '', 'source_snapshot': cargo.get('source_snapshot'),
              'fx_context': dict(fx_context or {}), 'input_evidence': {
                  'purchase_source': purchase_source, 'price': price, 'price_uom': price_uom,
                  'original_currency': purchase_currency, 'cargo': cargo}}
    if using_expense:
        result['input_evidence']['price_evidence'] = final_price.get('evidence')
    rate = '1' if purchase_currency == 'RMB' else number((fx_context or {}).get('fx_usd_to_rmb')) if purchase_currency == 'USD' else None
    if purchase_currency == 'MXN':
        rate_mxn = number((fx_context or {}).get('fx_rmb_to_mxn'))
        rate = str(Decimal('1') / Decimal(rate_mxn)) if rate_mxn is not None and Decimal(rate_mxn) > 0 else None
    if using_expense and final_price.get('ambiguous'):
        result['error'] = 'SETTLEMENT_EXPENSE_PRICE_AMBIGUOUS'
    elif not purchase_source or price is None or Decimal(price) < 0:
        result['error'] = 'SETTLEMENT_PURCHASE_PRICE_EVIDENCE_REQUIRED'
    elif final_code and purchase_code and final_code != purchase_code:
        result['error'] = 'SETTLEMENT_PURCHASE_MATERIAL_MISMATCH'
    elif qty is None or Decimal(qty) <= 0 or not uom or price_uom != uom:
        result['error'] = 'SETTLEMENT_QUANTITY_OR_PRICE_UNIT_INVALID'
    elif purchase_currency not in {'RMB','USD','MXN'} or rate is None or Decimal(rate) <= 0:
        result['error'] = 'SETTLEMENT_PURCHASE_CURRENCY_OR_FX_REQUIRED'
    else:
        result['amount_rmb'] = format((Decimal(price)*Decimal(qty)*Decimal(rate)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP), '.6f')
    result['input_evidence']['rate'] = rate
    result['input_fingerprint'] = digest(result['input_evidence'])
    result['status'] = 'missing' if result['error'] else 'automatic'
    return result


def reconcile_replacement_value(item, cargo, fx_context, prior_item=None):
    """Compare a newly calculated shipment value with an exactly matched prior row."""
    calculated = value_final_cargo(item, cargo, fx_context)
    prior_amount = number((prior_item or {}).get('goods_value'))
    prior_valuation = row_meta(prior_item or {}).get('settlement_valuation') or {}
    if (prior_amount is None or Decimal(prior_amount) <= 0) and prior_valuation.get('status') == 'conflict':
        prior_amount = number(prior_valuation.get('prior_amount_rmb'))
    has_prior = prior_amount is not None and Decimal(prior_amount) > 0
    calculated_amount = number(calculated.get('amount_rmb'))
    agrees = (has_prior and not calculated.get('error') and calculated_amount is not None
              and Decimal(prior_amount) == Decimal(calculated_amount))
    if not has_prior or agrees:
        return calculated
    return {
        **calculated,
        'status': 'conflict',
        'amount_rmb': None,
        'error': 'SETTLEMENT_SHIPMENT_VALUE_CONFLICT',
        'prior_amount_rmb': prior_amount,
        'calculated_amount_rmb': calculated_amount,
        'prior_evidence': deepcopy(prior_valuation.get('prior_evidence') or prior_item),
        'calculated_evidence': deepcopy(calculated),
    }
