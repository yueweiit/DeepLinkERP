"""Final shipment value from independent purchase evidence, without rewriting it."""
from decimal import Decimal, ROUND_HALF_UP

from .application import row_meta
from .model import digest, number
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
    price = number(fact.get('unit_price'))
    qty = number(cargo.get('quantity'))
    currency = str(fact.get('purchase_currency') or '').strip().upper()
    currency = 'RMB' if currency == 'CNY' else currency
    uom = normalize_unit(cargo.get('unit'))
    price_uom = normalize_unit(fact.get('unit_price_uom') or fact.get('purchase_uom') or fact.get('unit'))
    result = {'method': 'settlement_purchase_unit_price', 'quantity': qty, 'uom': uom, 'currency': 'RMB',
              'amount_rmb': None, 'error': '', 'source_snapshot': cargo.get('source_snapshot'),
              'fx_context': dict(fx_context or {}), 'input_evidence': {
                  'purchase_source': purchase_source, 'price': price, 'price_uom': price_uom,
                  'original_currency': currency, 'cargo': cargo}}
    rate = '1' if currency == 'RMB' else number((fx_context or {}).get('fx_usd_to_rmb')) if currency == 'USD' else None
    if currency == 'MXN':
        rate_mxn = number((fx_context or {}).get('fx_rmb_to_mxn'))
        rate = str(Decimal('1') / Decimal(rate_mxn)) if rate_mxn is not None and Decimal(rate_mxn) > 0 else None
    if not purchase_source or price is None or Decimal(price) < 0:
        result['error'] = 'SETTLEMENT_PURCHASE_PRICE_EVIDENCE_REQUIRED'
    elif qty is None or Decimal(qty) <= 0 or not uom or price_uom != uom:
        result['error'] = 'SETTLEMENT_QUANTITY_OR_PRICE_UNIT_INVALID'
    elif currency not in {'RMB','USD','MXN'} or rate is None or Decimal(rate) <= 0:
        result['error'] = 'SETTLEMENT_PURCHASE_CURRENCY_OR_FX_REQUIRED'
    else:
        result['amount_rmb'] = format((Decimal(price)*Decimal(qty)*Decimal(rate)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP), '.6f')
    result['input_evidence']['rate'] = rate
    result['input_fingerprint'] = digest(result['input_evidence'])
    return result
