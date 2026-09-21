"""Coherent row purchase totals, independent of source priority and shipping quantity.

Only server-resolved evidence may create these facts. Amount, currency and the
quantity/unit they price are one bundle; changing shipment quantity cannot change
the purchase denominator. See docs/source-field-priority.md.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from overseas_costing.utils.field_mapper import map_oa_row_to_item, normalize_unit

META_KEY = 'adopted_purchase_value'
CURRENCY_FIELDS = ('币种', '币种Moneda', 'Moneda', '采购币种', 'purchase_currency', 'currency')


def number(value):
    try:
        from .logistics_settlement.model import number as parse_number
        parsed = parse_number(value)
        result = Decimal(parsed) if parsed is not None else None
        if result is None:
            return None
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def text(value):
    return format(value, 'f')


def key(value):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', ''.join(
        c for c in unicodedata.normalize('NFKD', str(value)).casefold()
        if not unicodedata.combining(c)))


def uom(value):
    from .source_review_extract_service import normalize_weight_uom
    return normalize_unit(normalize_weight_uom(value))


def row_context(raw, document):
    """Unwrap parser cells, inheriting only the same document's explicit currency."""
    result = {k: (v.get('raw_value') if isinstance(v, dict) and 'raw_value' in v else v)
              for k, v in raw.items()}
    aliases = {key(v) for v in CURRENCY_FIELDS}
    if not any(key(k) in aliases and v not in (None, '') for k, v in result.items()):
        for k, v in (document.get('form_fields') or {}).items():
            if key(k) in aliases and v not in (None, ''):
                result['currency'] = v
                break
    return result


def extract_row_fact(raw, *, role, refs=(), fx_rates=None):
    """Read a dedicated row-total column; never reinterpret freight/whole-order totals."""
    aliases = {key(v) for v in ('货值', '采购货值', '总货值', '货值Valor de mercancía',
        'Valor de mercancía', 'goods_value', '总金额Monto Total', 'Monto Total', '总价')}
    fields = [(k, v) for k, v in raw.items() if key(k) in aliases]
    if len(fields) != 1:
        return None
    label, raw_amount = fields[0]
    currency_aliases = {key(v) for v in CURRENCY_FIELDS}
    raw_currency = next((v for k, v in raw.items() if key(k) in currency_aliases and v not in (None, '')), '')
    from .logistics_settlement.model import currency
    cur = currency(raw_currency) if raw_currency else ''
    embedded = re.findall(r'(?i)\b(?:RMB|CNY|USD|MXN)\b|人民币|美元|比索', str(raw_amount))
    currencies = {currency(value) for value in embedded}
    if len(currencies) > 1 or (cur and currencies and cur not in currencies):
        return None
    if not cur and currencies:
        cur = next(iter(currencies))
    reason = 'explicit'
    dedicated = key(label) in {key(v) for v in ('货值', '采购货值', '总货值', '货值Valor de mercancía', 'Valor de mercancía')}
    if not cur and not raw_currency and role == 'international_logistics' and dedicated:
        cur, reason = 'RMB', '国际物流专用货值列未标币种，按人民币采购货值采用。'
    if cur not in {'RMB', 'USD', 'MXN'}:
        return None
    amount = number(re.sub(r'(?i)\b(?:RMB|CNY|USD|MXN)\b|人民币|美元|比索|[¥￥]', '', str(raw_amount)))
    mapped = mapped_row(raw)
    quantity, unit = number(mapped.get('quantity')), uom(mapped.get('unit'))
    if amount is None or amount < 0 or quantity is None or quantity <= 0 or not unit:
        return None
    rate = Decimal(1) if cur == 'RMB' else number((fx_rates or {}).get(cur))
    if rate is None or rate <= 0:
        return None
    return {'original_amount': text(amount), 'currency': cur, 'amount_rmb': text(amount * rate),
            'quantity': text(quantity), 'uom': unit, 'rate_to_rmb': text(rate),
            'currency_basis': reason, 'source_type': role, 'source_refs': deepcopy(list(refs)),
            'amount_field': str(label), 'explicit_zero': amount == 0,
            'material_code': str(mapped.get('material_code') or ''),
            'spec_model': str(mapped.get('spec_model') or ''),
            'default_reason': '按逐字段来源优先级采用；货值、数量、单位和币种来自同一资料行。'}


def mapped_row(raw):
    from overseas_costing.utils.field_mapper import map_purchase_expense_row_to_item
    result = map_oa_row_to_item(raw)
    purchase = map_purchase_expense_row_to_item(raw)
    return {k: (v if v not in (None, '') else purchase.get(k)) for k, v in result.items()}


def document_rows(document, ref):
    from .source_review_extract_service import _approval_goods_rows
    from .logistics_purchase_facts_service import parse_labelled_approval_rows
    if document.get('form_fields'):
        return [(i, row_context(raw, document)) for i, raw in enumerate(_approval_goods_rows(document), 1)]
    if document.get('structured_rows'):
        result = []
        for row in document['structured_rows']:
            if not isinstance(row, dict):
                continue
            if row.get('missing_formula_cache') or row.get('formula_errors'):
                continue
            if any((e or {}).get('cache_status') == 'missing'
                   for f, e in (row.get('field_evidence') or {}).items()
                   if f in {'total_amount', 'quantity', 'unit', 'currency'}):
                continue
            region = (row.get('field_ranges') or {}).get('total_amount') or {}
            if region.get('start_row') != region.get('end_row'):
                continue  # a merged total is not a per-row purchase amount
            raw = row.get('raw_fields') or row
            result.append((row.get('source_row') or (row.get('evidence') or {}).get('row'), row_context(raw, document)))
        return result
    if document.get('semantic_rows'):
        result = []
        for row in document['semantic_rows']:
            if str(row.get('sheet') or '') != str(ref.get('sheet') or ''):
                continue
            raw = {str(cell['header']): cell.get('value') for cell in row.get('cells') or []
                   if isinstance(cell, dict) and cell.get('header')}
            if raw:
                result.append((row.get('source_row'), raw))
        return result
    labelled = parse_labelled_approval_rows(document.get('text'))
    for observation in document.get('vision_observations') or []:
        anchor = observation.get('anchor') or {}
        if any(ref.get(k) and anchor.get(k) and str(ref[k]) != str(anchor[k]) for k in ('page', 'sheet')):
            continue
        labelled.extend(parse_labelled_approval_rows(observation.get('description')))
    return list(enumerate(labelled, 1))


def from_documents(fields, target, refs, documents, *, fx_rates=None):
    """Bind a model/deterministic total to the matching server-owned source row."""
    if 'goods_value' not in fields:
        return None
    facts = []
    for ref in refs:
        document = documents.get(str(ref.get('document_id') or ''), {})
        role = document.get('approval_role') or (document.get('source_ref') or {}).get('approval_role') or ''
        for index, raw in document_rows(document, ref):
            if ref.get('row') and int(ref['row']) != index:
                continue
            mapped = mapped_row(raw)
            if str(mapped.get('material_code') or '').strip().casefold() != str(target.get('material_code') or '').strip().casefold():
                continue
            if (mapped.get('spec_model') and target.get('spec_model')
                    and str(mapped['spec_model']).strip().casefold() != str(target['spec_model']).strip().casefold()):
                continue
            fact = extract_row_fact(raw, role=role, refs=[{**ref, 'row': index}], fx_rates=fx_rates)
            if fact and number(fields['goods_value']) in {number(fact['original_amount']), number(fact['amount_rmb'])}:
                facts.append(fact)
    # A duplicated SKU without a specific source row is not an unambiguous price.
    # Multiple locators for the same source row are not multiple purchase rows.
    import json
    distinct = {json.dumps({k: v for k, v in fact.items() if k != 'source_refs'}, sort_keys=True): fact for fact in facts}
    identities = {(ref.get('document_id'), ref.get('sheet'), ref.get('row'))
                  for fact in facts for ref in fact['source_refs']}
    return next(iter(distinct.values())) if len(distinct) == 1 and len(identities) == 1 else None


def identity_matches(row, fact, *, check_uom=True):
    """Stable row keys are not evidence that the material itself is unchanged."""
    identity = lambda value: str(value or '').strip().casefold()
    if (not identity(fact.get('material_code'))
            or any(identity(row.get(field)) != identity(fact.get(field))
                   for field in ('material_code', 'spec_model'))):
        return False
    return not check_uom or uom(row.get('shipped_uom') or row.get('unit') or row.get('purchase_uom')) == uom(fact.get('uom'))


def retire_purchase_value(meta):
    previous = meta.pop(META_KEY, None)
    if previous:
        meta.setdefault('purchase_value_history', []).append(deepcopy(previous))


def shipment_valuation(row, fact):
    from .shipment_cost_service import shipment_input
    inputs = shipment_input(row)
    quantity, shipped = number(fact.get('quantity')), number(inputs.get('quantity'))
    total = number(fact.get('amount_rmb'))
    error = ''
    if not identity_matches(row, fact, check_uom=False):
        error = 'PURCHASE_VALUE_IDENTITY_MISMATCH'
    elif total is None or total < 0 or quantity is None or quantity <= 0 or shipped is None or shipped < 0:
        error = 'PURCHASE_VALUE_QUANTITY_REQUIRED'
    elif not uom(inputs.get('uom')) or uom(inputs.get('uom')) != uom(fact.get('uom')):
        error = 'PURCHASE_VALUE_UOM_MISMATCH'
    return {'amount_rmb': None if error else text(total * shipped / quantity),
            'currency': 'RMB', 'quantity': inputs['quantity'], 'uom': inputs['uom'],
            'method': 'source_purchase_total_proration', 'status': 'missing' if error else 'automatic',
            'error': error, 'source_refs': deepcopy(fact.get('source_refs') or []),
            'input_evidence': deepcopy(fact)}


def adopted_price(fact, row=None):
    if row is not None and not identity_matches(row, fact):
        return None
    total, quantity = number(fact.get('amount_rmb')), number(fact.get('quantity'))
    if total is None or total < 0 or quantity is None or quantity <= 0:
        return None
    from decimal import ROUND_HALF_UP
    calculation_value = total / quantity
    return {'value': format(calculation_value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f'),
            'calculation_value': format(calculation_value, 'f'),
            'currency': 'RMB', 'unit': fact.get('uom'), 'source_type': 'purchase_total_derived',
            'source': fact.get('source_type'), 'error': '', 'evidence': deepcopy(fact)}


def price_valuation(row, metadata, refs, *, fx_rates=None):
    """Value a complete trusted purchase-price tuple using its own denomination."""
    from .shipment_cost_service import shipment_input
    from .logistics_settlement.valuation import value_final_cargo
    fact = (metadata.get('logistics_row') or {}).get('purchase_fact') or {}
    if not isinstance(fact, dict):
        return None
    quantity = number(fact.get('quantity'))
    if (quantity is None or quantity <= 0 or not fact.get('purchase_currency')
            or not fact.get('unit_price_uom') and not fact.get('purchase_uom')
            or not fact.get('source_doc_no')):
        return None
    identity_fact = {**fact, 'uom': fact.get('unit_price_uom') or fact.get('purchase_uom')}
    if not identity_matches(row, identity_fact):
        return None
    inputs = shipment_input(row)
    cargo = {**{field: row.get(field) for field in ('material_code', 'spec_model')},
             'quantity': inputs['quantity'], 'unit': inputs['uom']}
    rates = dict((metadata.get('settlement_valuation') or {}).get('fx_context') or {})
    for currency, rate in (fx_rates or {}).items():
        if currency == 'USD':
            rates['fx_usd_to_rmb'] = rate
        elif currency == 'MXN' and number(rate) is not None and number(rate) > 0:
            rates['fx_rmb_to_mxn'] = text(Decimal(1) / number(rate))
        elif currency.startswith('fx_'):
            rates[currency] = rate
    valuation = value_final_cargo({**row, 'extra_json': metadata}, cargo, rates)
    valuation['source_refs'] = deepcopy(refs)
    return valuation if not valuation.get('error') else None
