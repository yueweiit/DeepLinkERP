"""Settlement acceptance against the production preview/saved-trial engine."""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from overseas_costing.services import cost_preview_service as service, fee_service
from overseas_costing.tests.test_source_metadata_security import controllers


def item(name='A', **values):
    return dict(name=name, stable_line_key=name, quantity=10, actual_shipped_qty=4,
                actual_shipped_qty_mode='EXPLICIT_SOURCE', unit='件', shipped_uom='件',
                unit_price=10, goods_value=100, gross_weight_kg=1, **values)


def final(amount='0', **values):
    return {'name': 'FINAL', 'rule_code': 'settlement_freight_total',
            'logical_fee_key': 'settlement_freight_total', 'amount_status': 'ACTUAL',
            'amount': amount, 'currency': 'RMB', 'scope_type': 'ALL_ITEMS',
            'allocation_basis': 'gross_weight', 'is_final': 1, 'is_enabled': 1, 'is_active': 1,
            'source_binding_id': 'B', 'source_snapshot': 'S', 'covered_scopes': 'freight', **values}


def old(key, amount='100', **values):
    return {'name': key, 'rule_code': key, 'logical_fee_key': key, 'amount_status': 'ACTUAL',
            'amount': amount, 'currency': 'RMB', 'allocation_basis': 'goods_value', **values}


def save_data(fees, items=None, fx=None, components=None):
    return service.build_saved_cost_data(items or [item()], fees,
        {'fx_rmb_to_mxn': 2.5} if fx is None else fx, 'SEA', fee_components=components)


def test_final_zero_suppresses_covered_pools_and_defaults_but_preserves_independent_fees():
    fees = fee_service.compose_fee_worklist_rows([
        old('international_sea_freight'), old('international_express_fee'),
        old('customs_clearance_fee', '20'), old('import_tax', '30'),
        old('destination_delivery', '7'), old('misc', '3'),
        final(covered_scopes='freight,customs,tax')], 'SEA')
    result = save_data(fees)
    assert Decimal(result['summary']['total_cost_rmb']) == Decimal('110')
    assert {f['fee_key'] for f in result['included_fees']} == {'settlement_freight_total', 'destination_delivery', 'misc'}
    assert not result['excluded_fees']
    assert result['summary_snapshot']['calculation_schema'] == 2


@pytest.mark.parametrize('changes', [
    {'is_enabled': 0}, {'is_active': 0}, {'currency': ''}, {'currency': 'EUR'},
    {'source_binding_id': ''}, {'source_snapshot': ''}, {'covered_scopes': ''},
    {'covered_scopes': 'freight,invalid'}, {'amount': 'NaN'}, {'amount': None},
    {'amount_status': 'MISSING'},
])
def test_invalid_final_blocks_current_trial_even_when_zero(changes):
    with pytest.raises(ValueError):
        fees = fee_service.compose_fee_worklist_rows([old('international_sea_freight'), final(**changes)], 'SEA')
        save_data(fees)


@pytest.mark.parametrize('currency,fx', [('RMB', {}), ('MXN', {}), ('USD', {'fx_rmb_to_mxn': 2.5}),
    ('USD', {'fx_usd_to_rmb': 'NaN', 'fx_rmb_to_mxn': 2.5}), ('MXN', {'fx_rmb_to_mxn': -1})])
def test_final_zero_does_not_skip_necessary_fx(currency, fx):
    with pytest.raises(ValueError, match='汇率'):
        save_data([final(currency=currency)], fx=fx)


@pytest.mark.parametrize('amount', ['1', '-1', '0.000001', '-0.000001', '0.100005'])
def test_final_pool_and_saved_schema2_totals_conserve_six_places(amount):
    items = [item('C'), item('A'), item('B')]
    original = deepcopy(items)
    result = save_data([final(amount)], items)
    fee = result['included_fees'][0]
    assert sum(map(Decimal, fee['allocations'].values())) == Decimal(amount)
    assert sum(Decimal(r['total_cost_rmb']) for r in result['item_updates']) == Decimal(result['summary']['total_cost_rmb'])
    assert sum(Decimal(r['freight_alloc_rmb']) for r in result['item_updates']) == Decimal(amount)
    assert result['summary']['is_complete']
    assert result['included_fees'] == save_data([final(amount)], list(reversed(items)))['included_fees']
    assert items == original
    assert all(Decimal(row['total_unit_rmb']) == (Decimal(row['total_cost_rmb']) / 4).quantize(Decimal('0.000001')) for row in result['item_updates'])


def test_final_details_have_distinct_identities_and_no_old_components_or_total():
    fees = [old('import_tax', '50'), final('0.4', covered_scopes='freight,tax'),
            final('-0.1', name='CREDIT', logical_fee_key='settlement_freight_credit', rule_code='settlement_freight_credit', covered_scopes='freight,tax')]
    components = [{'fee_rule': 'FINAL', 'logical_fee_key': 'settlement_freight_total', 'item': 'A',
                   'stable_line_key': 'A', 'amount_rmb': 99, 'is_active': 1, 'status': 'CONFIRMED', 'cost_effect': 'COST'}]
    result = save_data(fees, components=components)
    assert Decimal(result['summary']['total_cost_rmb']) == Decimal('100.3')
    assert len(result['included_fees']) == 2 and not result['excluded_fees']


def test_explicit_inland_scope_suppresses_only_inland_and_keeps_freight():
    result = save_data([old('destination_delivery', '20'), old('international_sea_freight', '30'), final(covered_scopes='mexico_inland')])
    assert Decimal(result['summary']['total_cost_rmb']) == 130


def test_partial_old_bundle_and_conflicting_final_source_block():
    with pytest.raises(ValueError, match='范围|覆盖'):
        save_data([final(), old('bundle', covered_scopes='freight,customs')])
    with pytest.raises(ValueError, match='来源|重叠'):
        save_data([final(), final(name='OTHER', source_binding_id='OTHER')])


def test_final_project_policy_retains_two_stage_allocation_at_six_places():
    policy = {'project_allocation': {'method': 'PROJECT_GROSS_WEIGHT', 'projects': ['P', 'Q'], 'source_refs': [{'id': 'policy'}]}}
    result = save_data([final('-0.000003', scope_value_json=json.dumps(policy))],
                       [item('A', project_collection='P'), item('B', project_collection='Q')])
    fee = result['included_fees'][0]
    assert sum(map(Decimal, fee['project_allocations'].values())) == Decimal('-0.000003')
    assert sum(map(Decimal, fee['allocations'].values())) == Decimal('-0.000003')
    assert sum(Decimal(row['total_cost_rmb']) for row in result['project_summary']) == Decimal('199.999997')


def test_settlement_metadata_survives_fee_reads_and_exact_saved_rule_evidence():
    fields = fee_service._rule_fields()
    assert {'is_final', 'source_binding_id', 'source_snapshot', 'covered_scopes'} <= set(fields)
    result = save_data([final('1')])
    assert result['included_fees'][0]['source_snapshot'] == 'S'
    assert json.loads(result['item_updates'][0]['derived_json'])['allocated_rules'][0]['source_binding_id'] == 'B'


def test_source_owned_fee_and_covered_estimate_edits_block_without_hiding_other_fees():
    from overseas_costing.services.logistics_settlement.fee_policy import assert_fee_edit_allowed
    fees = [final(), old('international_sea_freight', is_enabled=0)]
    for payload in [final('99'), old('international_sea_freight'), old('international_express_fee')]:
        with pytest.raises(ValueError):
            assert_fee_edit_allowed(fees, payload)
    assert_fee_edit_allowed(fees, old('destination_delivery'))


def test_current_repository_checks_binding_before_acquiring_batch_lock(monkeypatch):
    from overseas_costing.services import batch_service, edit_session_service
    from overseas_costing.services.logistics_settlement import runtime
    events = []
    monkeypatch.setattr(batch_service, '_resolve_batch_name', lambda value: 'B')
    def blocker(*args, **kwargs):
        assert kwargs == {'for_calculation': True, 'lock': True}
        events.append('binding-and-source-locks')
        return ['来源待核对']
    monkeypatch.setattr(runtime, 'calculation_blockers', blocker)
    monkeypatch.setattr(edit_session_service, '_lock_row', lambda name: events.append('batch-lock'))
    with pytest.raises(ValueError, match='来源待核对'):
        service.FrappeCostRepository().lock_and_load('B', 'V', edit_token=None, expected_modified=None, trusted=True)
    assert events == ['binding-and-source-locks']


def test_ai_fee_split_cannot_mutate_final_or_reactivate_covered_pool(monkeypatch):
    from overseas_costing.services import fee_evidence_review_service as review
    monkeypatch.setattr(fee_service, '_query_rules', lambda *args: [final()])
    repo = review.FrappeFeeEvidenceReviewRepository()
    monkeypatch.setattr(repo, 'materialize_fee_rule', lambda *args: pytest.fail('guard must precede writes'))
    for row in [final('9'), old('international_sea_freight')]:
        with pytest.raises(ValueError, match='最终|覆盖'):
            repo.save_fee_split(context={'batch': 'B', 'version': 'V'}, fee_row=row,
                evidence_values={}, attachment={}, draft={}, run_id='RUN')


def test_final_mxn_allocations_conserve_independently_of_rmb_rounding():
    result = save_data([final('1')], [item('A'), item('B'), item('C')])
    assert sum(Decimal(r['freight_alloc_mxn']) for r in result['item_updates']) == Decimal('2.5')
    assert sum(Decimal(r['total_logistics_mxn']) for r in result['item_updates']) == Decimal('2.5')


@pytest.mark.parametrize('explicit,expected', [(None, '10'), (0, '0'), (1, '20')])
def test_uncovered_item_pool_respects_explicit_disabled_and_current_fee_identity(explicit, expected):
    fees = [final()]
    if explicit is not None:
        fees.append(old('mexico_misc_mxn', '50', currency='MXN', is_enabled=explicit))
    result = save_data(fee_service.compose_fee_worklist_rows(fees, 'SEA'), [item(mexico_misc_mxn=25)])
    assert Decimal(result['summary']['allocated_fees_rmb']) == Decimal(expected)


def test_ambiguous_legacy_combined_amount_cannot_be_silently_hidden():
    with pytest.raises(ValueError, match='范围'):
        save_data([final(covered_scopes='freight,mexico_inland')], [item(mexico_inland_misc_rmb=99)])


def test_fee_controller_rejects_direct_source_fact_change_and_deletion(controllers):
    _, Controller = controllers
    payload = {**final(), 'batch': 'B', 'version': 'V'}
    with pytest.raises(ValueError, match='最终'):
        Controller(payload).save()
    doc = Controller(payload)
    with pytest.raises(ValueError, match='最终'):
        doc.on_trash()
    Controller(payload).save(ignore_permissions=True)  # Trusted settlement writer.


def test_fee_evidence_candidates_preserve_local_document_context_and_version_scope():
    descriptor = {'document_id': 'D', 'audit_only': True, 'retired': True}
    attachments = [{'name': 'current', 'version': 'V', 'parse_result_json': json.dumps({'settlement_document': descriptor, 'amount': 99})},
        {'name': 'other', 'version': 'OLD', 'parse_result_json': json.dumps({'settlement_document': descriptor})},
        {'name': 'legacy', 'version': 'OLD', 'parse_result_json': '{}'}]
    rows = fee_service.build_evidence_candidates(attachments, version_name='V')
    assert {r['attachment'] for r in rows} == {'current', 'legacy'}
    row = next(row for row in rows if row['attachment'] == 'current')
    assert row['version'] == 'V' and row['settlement_document'] == descriptor and row['audit_only'] is True
    assert row['amount_candidates'] == []


def test_normal_trial_keeps_production_aggregate_mxn_rounding():
    result = service.build_saved_cost_data([item()], [old('misc1', '0.01'), old('misc2', '0.01')], {'fx_rmb_to_mxn': '.5'}, 'SEA')
    assert result['item_updates'][0]['total_logistics_mxn'] == '0.01'


def test_real_trial_projection_retains_independent_purchase_valuation_evidence():
    assert {'unit_price', 'purchase_currency', 'source_doc_no', 'purchase_uom', 'unit_price_uom', 'extra_json'} <= set(service.COST_INPUT_FIELDS)


@pytest.mark.parametrize('currency,amount,fx,expected_rmb,expected_mxn', [
    ('MXN', '1', {'fx_rmb_to_mxn': 3}, '0.333333', '1'),
    ('MXN', '10', {'fx_rmb_to_mxn': 7}, '1.428571', '10'),
    ('MXN', '-1', {'fx_rmb_to_mxn': 3}, '-0.333333', '-1'),
    ('USD', '0.000001', {'fx_rmb_to_mxn': 3, 'fx_usd_to_rmb': '.4'}, '0', '0.000001'),
    ('USD', '-0.000001', {'fx_rmb_to_mxn': 3, 'fx_usd_to_rmb': '.4'}, '0', '-0.000001'),
])
@pytest.mark.parametrize('project_policy', [False, True])
def test_each_currency_pool_converts_directly_from_original_fee(currency, amount, fx, expected_rmb, expected_mxn, project_policy):
    rows = [item(name, project_collection=name) for name in ('A', 'B', 'C')]
    policy = {'project_allocation': {'method': 'PROJECT_GROSS_WEIGHT', 'projects': ['A', 'B', 'C'], 'source_refs': [{'id': 'policy'}]}} if project_policy else {}
    fee = final(amount, currency=currency, scope_value_json=json.dumps(policy))
    result = save_data([fee], rows, fx)
    included = result['included_fees'][0]
    assert Decimal(included['amount_rmb']) == Decimal(expected_rmb)
    assert Decimal(included['amount_mxn']) == Decimal(expected_mxn)
    assert sum(Decimal(row['freight_alloc_mxn']) for row in result['item_updates']) == Decimal(expected_mxn)
    assert sum(Decimal(row['freight_alloc_rmb']) for row in result['item_updates']) == Decimal(expected_rmb)
    reordered = save_data([fee], rows[::-1], fx)
    assert reordered['included_fees'][0]['allocations_mxn'] == included['allocations_mxn']
