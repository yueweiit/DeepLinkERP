"""One selected value basis must survive preview, save, and source refresh."""
from copy import deepcopy
from decimal import Decimal

import pytest

from overseas_costing.services import material_ai_row_selection as rows
from overseas_costing.services.effective_logistics_source import project_ai_items
from overseas_costing.services.material_ai_selection_writer import write_rows
from overseas_costing.services.material_input_service import present_material_row
from overseas_costing.services.shipment_cost_service import object_json, shipment_value
from overseas_costing.tests.test_freight_lines import setup_cost
from overseas_costing.tests.test_source_goods_value_adoption import evidence, review, project_defaults


def saved_context():
    store, ledger, batch, version, current, *_ = setup_cost()
    items, source = evidence((800,), (4,))
    items[0].update(name=current['name'], stable_line_key='LINE')
    return store, ledger, batch, version, items, source


def save(projection, context):
    store, ledger, batch, version, items, _ = context
    projection.update(batch=batch['name'], version=version['name'], id='P', revision='R',
                      run_id='R', source_context={}, sources=[])
    write_rows(store, ledger, projection, {})
    return ledger.get('item', items[0]['name'])


def price_proposal(item, *, amount='300', currency='RMB', source_id='PRICE', metadata=None):
    price = {'unit_price': amount, 'purchase_currency': currency,
             'purchase_uom': 'kg', 'unit_price_uom': 'kg'}
    fact = {**price, 'quantity': '4', 'material_code': item['material_code'],
            'spec_model': item.get('spec_model') or '', 'source_doc_no': source_id}
    meta = {**deepcopy(metadata or {}), 'logistics_row': {'purchase_fact': fact}}
    return {'proposal_id': source_id, 'proposal_type': 'logistics_reconcile',
            'confidence': 1, 'default_selected': True, 'source_refs': [{'source_id': source_id, 'row': 1}],
            'payload': {'rows': [{**item, **price, '_review_origin': 'source',
                                '_review_purchase_values': price, '_review_price_metadata': meta}]}}


def shipment_proposal(item, amount='800'):
    valuation = {'amount_rmb': amount, 'quantity': '4', 'uom': 'kg', 'currency': 'RMB',
                 'method': 'packing_row_total', 'source_refs': [{'source_id': 'SHIP', 'row': 2}]}
    return {'proposal_id': 'SHIP', 'proposal_type': 'logistics_reconcile',
            'confidence': 1, 'default_selected': True, 'source_refs': valuation['source_refs'],
            'payload': {'rows': [{**item, '_review_origin': 'source',
                                 'extra_json': {'shipment_valuation': valuation}}]}}


def payment_total(item):
    fact = {'original_amount': '900', 'amount_rmb': '900', 'currency': 'RMB',
            'quantity': '4', 'uom': 'kg', 'rate_to_rmb': '1', 'source_type': 'payment',
            'material_code': item['material_code'], 'spec_model': '',
            'source_refs': [{'source_id': 'PAY', 'row': 1}]}
    return {'proposal_id': 'PAY', 'proposal_type': 'item_update', 'target_item_name': item['name'],
            'confidence': 1, 'default_selected': True, 'source_refs': fact['source_refs'],
            '_purchase_value_fact': fact, 'payload': {'fields': {'goods_value': '900'}}}


SOURCES = [{'source_id': 'PAY', 'source_kind': 'approval_form', 'approval_role': 'payment'},
           {'source_id': 'SHIP', 'source_kind': 'approval_attachment', 'approval_role': 'international_logistics'},
           {'source_id': 'PRICE', 'source_kind': 'approval_form', 'approval_role': 'purchase'}]


@pytest.mark.parametrize('mode', ['field', 'row'])
def test_explicit_price_retires_prior_total_in_preview_save_and_reread(mode):
    context = saved_context()
    _, ledger, _, _, items, source = context
    existing = project_defaults(items, review(items, source))['rows'][0]
    ledger.put('item', items[0]['name'], existing)
    before = deepcopy(existing)
    proposal = price_proposal(existing, metadata=object_json(existing['extra_json']))
    catalog = rows.catalog([existing], [proposal], [], {}, run_id='R', sources=SOURCES)
    candidate = next(c for c in catalog['field_candidates'] if c['fieldname'] == 'unit_price')
    if mode == 'field':
        projection = rows.project([existing], catalog, [], [], 'update_selected',
            field_choices={existing['name'] + ':unit_price': candidate['candidate_id']})
    else:
        projection = rows.project([existing], catalog, [candidate['row_id']], [], 'update_selected')
    assert existing == before
    projected = projection['rows'][0]
    assert Decimal(shipment_value(projected)['amount_rmb']) == 1200
    assert present_material_row(projected)['adopted_price']['value'] == '300.00'
    saved = save(projection, context)
    assert Decimal(shipment_value(saved)['amount_rmb']) == 1200
    assert present_material_row(saved)['adopted_price']['value'] == '300.00'
    history = object_json(saved['extra_json'])['purchase_value_history']
    assert history[-1]['amount_rmb'] == '800'
    assert saved['unit_price'] == '300'


@pytest.mark.parametrize('changed', [dict(material_code='SKU-NEW'), dict(spec_model='NEW'),
                                    dict(unit='箱')])
def test_stable_line_cannot_carry_prior_fact_across_material_identity(changed):
    items, source = evidence((800,), (4,))
    items[0]['stable_line_key'] = 'LINE'
    existing = project_defaults(items, review(items, source))['rows'][0]
    before = deepcopy(existing)
    goods = {'material_code': 'SKU-1', 'spec_model': '', 'quantity': '4', 'unit': 'kg',
             'line_key': 'LINE', **changed}
    bundle = {'context': {'root_kind': 'expense', 'available': True, 'source_snapshot': 'S',
                          'binding_id': 'B', 'fingerprint': 'F'}, 'source': {'goods': [goods]}}
    projected = project_ai_items([existing], bundle)[0]
    assert existing == before
    assert not object_json(projected['extra_json']).get('adopted_purchase_value')
    assert object_json(projected['extra_json'])['purchase_value_history'][-1]['amount_rmb'] == '800'
    assert shipment_value(projected)['amount_rmb'] is None
    assert not present_material_row(projected).get('adopted_price', {}).get('value')


@pytest.mark.parametrize('changed', [dict(material_code='SKU-NEW'), dict(spec_model='NEW')])
def test_reread_rejects_mismatched_persisted_purchase_fact(changed):
    items, source = evidence((800,), (4,))
    adopted = project_defaults(items, review(items, source))['rows'][0]
    adopted.update(changed)
    assert shipment_value(adopted)['amount_rmb'] is None
    assert 'IDENTITY' in shipment_value(adopted)['error']
    assert not present_material_row(adopted).get('adopted_price', {}).get('value')


def test_default_total_price_and_shipment_value_use_one_highest_priority_basis():
    context = saved_context()
    _, ledger, _, _, items, _ = context
    ledger.put('item', items[0]['name'], items[0])
    proposals = [payment_total(items[0]), shipment_proposal(items[0]), price_proposal(items[0])]
    catalog = rows.catalog(items, proposals, [], {}, run_id='R', sources=SOURCES)
    value_fields = {'goods_value', 'unit_price', 'shipment_value_rmb'}
    candidates = [c for c in catalog['field_candidates'] if c['fieldname'] in value_fields]
    assert [c['suggested_value'] for c in candidates if c['default_selected']] == ['900']
    assert all(c['can_apply'] for c in candidates)
    projection = project_defaults(items, catalog)
    assert shipment_value(projection['rows'][0])['amount_rmb'] == '900'
    assert present_material_row(projection['rows'][0])['adopted_price']['value'] == '225.00'
    saved = save(projection, context)
    assert shipment_value(saved)['amount_rmb'] == '900'
    assert present_material_row(saved)['adopted_price']['value'] == '225.00'
    for field, expected in [('shipment_value_rmb', '800'), ('unit_price', '1200')]:
        refreshed = rows.catalog([saved], proposals, [], {}, run_id='R2', sources=SOURCES)
        lower = next(c for c in refreshed['field_candidates'] if c['fieldname'] == field)
        manual = rows.project([saved], refreshed, [], [], 'update_selected',
            field_choices={saved['name'] + ':' + field: lower['candidate_id']})
        assert Decimal(shipment_value(manual['rows'][0])['amount_rmb']) == Decimal(expected)
        reread = save(manual, context)
        assert Decimal(shipment_value(reread)['amount_rmb']) == Decimal(expected)
        assert object_json(reread['extra_json'])['purchase_value_history'][-1]['amount_rmb'] == '900'


def test_explicit_price_selects_its_currency_unit_tuple_with_version_fx():
    context = saved_context()
    _, ledger, _, _, items, source = context
    existing = project_defaults(items, review(items, source))['rows'][0]
    existing.update(purchase_currency='RMB', actual_shipped_qty='2', actual_shipped_qty_mode='MANUAL_CONFIRMED')
    ledger.put('item', items[0]['name'], existing)
    proposal = price_proposal(existing, currency='USD')
    catalog = rows.catalog([existing], [proposal], [], {}, run_id='R', sources=SOURCES, fx_rates={'USD': '7'})
    price = next(c for c in catalog['field_candidates'] if c['fieldname'] == 'unit_price')
    projected = rows.project([existing], catalog, [], [], 'update_selected',
        field_choices={existing['name'] + ':unit_price': price['candidate_id']})
    assert projected['rows'][0]['purchase_currency'] == 'USD'
    assert Decimal(shipment_value(projected['rows'][0])['amount_rmb']) == 4200
    display = present_material_row(projected['rows'][0])['adopted_price']
    assert (display['value'], display['currency']) == ('300.00', 'USD')
    reread = save(projected, context)
    assert Decimal(shipment_value(reread)['amount_rmb']) == 4200
    assert reread['purchase_currency'] == 'USD'


@pytest.mark.parametrize('missing_field', ['quantity', 'purchase_currency', 'unit', 'fx'])
def test_incomplete_price_basis_cannot_retire_valid_total(missing_field):
    items, source = evidence((800,), (4,))
    existing = project_defaults(items, review(items, source))['rows'][0]
    proposal = price_proposal(existing, currency='USD' if missing_field == 'fx' else 'RMB')
    fact = proposal['payload']['rows'][0]['_review_price_metadata']['logistics_row']['purchase_fact']
    if missing_field == 'unit':
        fact.pop('purchase_uom')
        fact.pop('unit_price_uom')
    else:
        fact.pop(missing_field, None)
    catalog = rows.catalog([existing], [proposal], [], {}, run_id='R', sources=SOURCES)
    candidate = next(c for c in catalog['field_candidates'] if c['fieldname'] == 'unit_price')
    assert not candidate['can_apply']
    assert not candidate['default_selected']
    assert shipment_value(existing)['amount_rmb'] == '800'


@pytest.mark.parametrize('protected', ['raw_price', 'manual'])
def test_default_value_basis_keeps_existing_price_and_manual_values(protected):
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation
    items, _ = evidence((800,), (4,))
    if protected == 'raw_price':
        items[0].update(unit_price='250', purchase_currency='RMB', purchase_uom='kg')
    else:
        items[0]['extra_json'] = {'manual_shipment_valuation':
            build_manual_shipment_valuation(items[0], '999', actor='reviewer')}
    proposals = [payment_total(items[0]), shipment_proposal(items[0]), price_proposal(items[0])]
    catalog = rows.catalog(items, proposals, [], {}, run_id='R', sources=SOURCES)
    assert not [c for c in catalog['field_candidates']
                if c['fieldname'] in {'goods_value', 'unit_price', 'shipment_value_rmb'} and c['default_selected']]


def test_explicit_lower_basis_overrides_still_checked_higher_default():
    items, _ = evidence((800,), (4,))
    proposals = [payment_total(items[0]), shipment_proposal(items[0])]
    catalog = rows.catalog(items, proposals, [], {}, run_id='R', sources=SOURCES)
    choices = {f"{c['item_name']}:{c['fieldname']}": c['candidate_id']
               for c in catalog['field_candidates'] if c.get('default_selected') or c['fieldname'] == 'shipment_value_rmb'}
    projected = rows.project(items, catalog, [], [], 'update_selected', field_choices=choices)
    assert shipment_value(projected['rows'][0])['amount_rmb'] == '800'
    assert not any(change['fieldname'] == 'goods_value' for change in projected['changes'])


def test_equivalent_total_and_price_compare_at_the_current_shipping_quantity():
    items, _ = evidence((800,), (4,))
    items[0].update(actual_shipped_qty='2', actual_shipped_qty_mode='MANUAL_CONFIRMED')
    price = price_proposal(items[0], amount='225')
    sources = [{**source, 'approval_role': 'payment'} for source in SOURCES]
    catalog = rows.catalog(items, [payment_total(items[0]), price], [], {}, run_id='R', sources=sources)
    defaults = [candidate for candidate in catalog['field_candidates']
                if candidate['fieldname'] in {'goods_value', 'unit_price'} and candidate['default_selected']]
    assert len(defaults) == 1
    projected = project_defaults(items, catalog)
    assert Decimal(shipment_value(projected['rows'][0])['amount_rmb']) == 450


def test_computed_price_evidence_stays_private_in_public_catalog():
    from overseas_costing.services.material_ai_selection_service import public_catalog
    items, _ = evidence((800,), (4,))
    catalog = rows.catalog(items, [price_proposal(items[0])], [], {}, run_id='R', sources=SOURCES)
    public = public_catalog(catalog)
    assert '_price_valuation' not in str(public)
    assert 'input_evidence' not in str(public)


@pytest.mark.parametrize('selection', ['field', 'row'])
@pytest.mark.parametrize('currency', ['RMB', None])
def test_fill_missing_skips_existing_price_and_its_whole_tuple(selection, currency):
    context = saved_context()
    _, ledger, _, _, items, _ = context
    items[0].update(unit_price='250', goods_value='1000', purchase_currency=currency,
                    purchase_uom='kg', gross_weight_kg=None)
    ledger.put('item', items[0]['name'], items[0])
    proposal = price_proposal(items[0])
    proposal['payload']['rows'][0]['gross_weight_kg'] = '7'
    catalog = rows.catalog(items, [proposal], [], {}, run_id='R', sources=SOURCES)
    selected = [candidate for candidate in catalog['field_candidates']
                if candidate['fieldname'] in {'unit_price', 'gross_weight_kg'}]
    before = deepcopy(items)
    if selection == 'field':
        choices = {f"{candidate['item_name']}:{candidate['fieldname']}": candidate['candidate_id']
                   for candidate in selected}
        projection = rows.project(items, catalog, [], [], 'fill_missing', field_choices=choices)
    else:
        projection = rows.project(items, catalog, [selected[0]['row_id']], [], 'fill_missing')
    assert items == before
    projected = projection['rows'][0]
    assert Decimal(shipment_value(projected)['amount_rmb']) == 1000
    assert projected['unit_price'] == '250'
    assert projected.get('purchase_currency') == currency
    assert projected.get('unit_price_uom') is None
    assert not projected.get('_price_metadata')
    assert {change['fieldname'] for change in projection['changes']} == {'gross_weight_kg'}
    saved = save(projection, context)
    assert Decimal(shipment_value(saved)['amount_rmb']) == 1000
    assert saved['unit_price'] == '250'
    assert saved.get('purchase_currency') == currency
    assert not object_json(saved.get('extra_json')).get('logistics_row')


def real_purchase_chain(items, logistics, *, prior=None):
    from overseas_costing.services.logistics_purchase_facts_service import enrich_logistics_purchase_facts
    from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
    purchase = {'source_id': 'PUR', 'approval_no': 'PUR-1', 'source_kind': 'approval_form',
        'approval_role': 'purchase', 'selected': True, 'available': True,
        'form_fields': {'币种Moneda': 'RMB', '采购明细': [{
            '物品编码Código': 'SKU-1', '规格型号': 'GRADE-A', '数量Cantidad': 4,
            '单位Unidad': 'kg', '单价Precio': 300, '总金额Monto Total': 1200}]}}
    enriched = enrich_logistics_purchase_facts(prior or items, [purchase])
    reconciliation = build_logistics_reconciliation(enriched['items'], logistics)
    return purchase, enriched, reconciliation


@pytest.mark.parametrize('historical', [False, True])
def test_real_purchase_enrichment_reconciliation_price_has_verified_identity_and_source(historical):
    context = saved_context()
    _, ledger, _, _, items, logistics = context
    items[0].update(source_type='OA_LOGISTICS_ROW', spec_model='GRADE-A')
    logistics['form_fields']['货物信息Bienes'][0]['规格型号'] = 'GRADE-A'
    purchase, enriched, reconciliation = real_purchase_chain(items, logistics)
    if historical:
        prior = deepcopy(enriched['items'])
        meta = object_json(prior[0]['extra_json'])
        for key in ('material_code', 'spec_model', 'source_refs'):
            meta['logistics_row']['purchase_fact'].pop(key, None)
        prior[0]['extra_json'] = meta
        purchase, enriched, reconciliation = real_purchase_chain(items, logistics, prior=prior)
    fact = object_json(enriched['items'][0]['extra_json'])['logistics_row']['purchase_fact']
    assert (fact.get('material_code'), fact.get('spec_model')) == ('SKU-1', 'GRADE-A')
    catalog = rows.catalog(items, [reconciliation], [], {}, run_id='R', sources=[logistics, purchase])
    price = next(c for c in catalog['field_candidates'] if c['fieldname'] == 'unit_price')
    assert price['can_apply'] and price['default_selected']
    assert price['workflow_stage'] == 'purchase'
    assert {ref['source_id'] for ref in price['source_refs']} == {'PUR'}
    assert price['source_refs'][0]['row'] == 1
    ledger.put('item', items[0]['name'], items[0])
    projected = project_defaults(items, catalog)
    assert Decimal(shipment_value(projected['rows'][0])['amount_rmb']) == 1200
    saved = save(projected, context)
    assert Decimal(shipment_value(saved)['amount_rmb']) == 1200
    assert present_material_row(saved)['adopted_price']['value'] == '300.00'
    assert {ref['source_id'] for ref in shipment_value(saved)['source_refs']} == {'PUR'}


@pytest.mark.parametrize('include_payment', [False, True])
def test_real_purchase_price_does_not_get_logistics_priority(include_payment):
    from overseas_costing.services.purchase_value_evidence import extract_row_fact
    items, logistics = evidence((800,), (4,))
    items[0].update(source_type='OA_LOGISTICS_ROW', spec_model='GRADE-A')
    raw = logistics['form_fields']['货物信息Bienes'][0]
    raw['规格型号'] = 'GRADE-A'
    purchase, _, reconciliation = real_purchase_chain(items, logistics)
    fact = extract_row_fact(raw, role='international_logistics', refs=[{'source_id': 'LOG', 'row': 1}])
    total = {'proposal_id': 'LOG-TOTAL', 'proposal_type': 'item_update', 'target_item_name': items[0]['name'],
        'confidence': 1, 'default_selected': True, '_purchase_value_fact': fact,
        'source_refs': fact['source_refs'], 'payload': {'fields': {'goods_value': '800'}}}
    proposals, sources = [reconciliation, total], [logistics, purchase]
    if include_payment:
        payment = payment_total(items[0])
        payment['_purchase_value_fact']['spec_model'] = 'GRADE-A'
        proposals.append(payment)
        sources.append(SOURCES[0])
    catalog = rows.catalog(items, proposals, [], {}, run_id='R', sources=sources)
    defaults = [c for c in catalog['field_candidates']
                if c['fieldname'] in {'goods_value', 'unit_price', 'shipment_value_rmb'} and c['default_selected']]
    assert [(c['workflow_stage'], c['suggested_value']) for c in defaults] == [
        ('payment', '900') if include_payment else ('international_logistics', '800')]
    price = next(c for c in catalog['field_candidates'] if c['fieldname'] == 'unit_price')
    assert price['can_apply'] and price['workflow_stage'] == 'purchase'
    assert {ref['source_id'] for ref in price['source_refs']} == {'PUR'}


def test_historical_price_identity_is_not_borrowed_from_current_row_without_source():
    from overseas_costing.services.logistics_purchase_facts_service import enrich_logistics_purchase_facts
    items, logistics = evidence((800,), (4,))
    items[0].update(source_type='OA_LOGISTICS_ROW', spec_model='GRADE-A')
    purchase, enriched, _ = real_purchase_chain(items, logistics)
    prior = enriched['items'][0]
    meta = object_json(prior['extra_json'])
    for key in ('material_code', 'spec_model'):
        meta['logistics_row']['purchase_fact'].pop(key, None)
    prior.update(material_code='SKU-NEW', extra_json=meta)
    for sources in ([], [purchase]):
        result = enrich_logistics_purchase_facts([prior], sources)['items'][0]
        fact = object_json(result['extra_json'])['logistics_row']['purchase_fact']
        assert not fact.get('material_code')
        from overseas_costing.services.purchase_value_evidence import price_valuation
        assert price_valuation(result, object_json(result['extra_json']), []) is None
