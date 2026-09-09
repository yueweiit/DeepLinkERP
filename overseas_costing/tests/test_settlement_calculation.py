"""最终物流结算的计算边界：来源优先、严格汇率与逐费用精确分摊。"""

from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from overseas_costing.services import calculate_service as service


def item(name='ITEM-1', **values):
    return {'name': name, 'quantity': 10, 'unit_price': 10, 'goods_value': 100,
            'gross_weight_kg': 1, **values}


def final_rule(amount=0, **values):
    return {'rule_code': 'settlement_freight_total', 'allocation_basis': 'gross_weight',
            'amount': amount, 'currency': 'RMB', 'is_final': 1,
            'source_binding_id': 'BINDING-1', 'source_snapshot': 'SNAPSHOT-1',
            'covered_scopes': 'freight', 'is_enabled': 1, 'is_active': 1, **values}


def calculate(items, rules, **kwargs):
    return service.calculate_item_rows(items, rules, fx_rmb_to_mxn=kwargs.pop('fx_rmb_to_mxn', 2.5), **kwargs)


def allocations(rows, currency='rmb'):
    return {row['name']: [Decimal(str(rule['allocated_' + currency]))
                         for rule in json.loads(row['derived_json'])['allocated_rules']]
            for row in rows}


def test_final_zero_suppresses_old_rule_and_item_estimates():
    old = {'rule_code': 'oa_logistics_freight', 'amount': 500, 'currency': 'RMB', 'is_enabled': 1}
    rows, summary = calculate([item(china_to_mexico_freight_rmb=900)], [old, final_rule()])
    assert rows[0]['total_cost_rmb'] == 100
    assert rows[0]['freight_alloc_rmb'] == 0
    assert summary['fee_pool_rmb'] == 0
    assert summary['rule_count'] == 1
    assert summary['calculation_review']['status'] == 'usable'


@pytest.mark.parametrize('flag', ['is_enabled', 'is_active'])
@pytest.mark.parametrize('disabled', [0, '0', False])
def test_disabled_final_blocks_instead_of_reviving_estimates(flag, disabled):
    with pytest.raises(ValueError, match='最终.*停用'):
        calculate([item(china_to_mexico_freight_rmb=900)], [final_rule(**{flag: disabled})])


@pytest.mark.parametrize('currency', [None, '', 'EUR', 'RMB/USD', 'not-USD', '???'])
def test_final_currency_is_explicit_and_supported(currency):
    with pytest.raises(ValueError, match='币种'):
        calculate([item()], [final_rule(100, currency=currency)])


@pytest.mark.parametrize('rate', [None, 0, -7, 'bad', float('nan'), float('inf')])
def test_final_usd_missing_or_invalid_fx_blocks(rate):
    with pytest.raises(ValueError, match='汇率'):
        calculate([item()], [final_rule(100, currency='USD')], fx_usd_to_rmb=rate)


@pytest.mark.parametrize('rate', [None, 0, -2, 'bad', float('nan'), float('inf')])
def test_final_mxn_missing_or_invalid_fx_blocks(rate):
    with pytest.raises(ValueError, match='汇率'):
        calculate([item()], [final_rule(100, currency='MXN')], fx_rmb_to_mxn=rate)


@pytest.mark.parametrize('currency', ['USD', 'EUR', None])
def test_legacy_rules_never_treat_unconverted_amount_as_rmb(currency):
    with pytest.raises(ValueError, match='币种|汇率'):
        calculate([item()], [{'rule_code': 'legacy_freight', 'amount': 100, 'currency': currency}])


def test_direct_usd_customs_requires_conversion_even_without_fee_rules():
    with pytest.raises(ValueError, match='汇率'):
        calculate([item(mexico_customs_usd=100)], [])


@pytest.mark.parametrize('amount', [None, '', 'bad', float('nan'), float('inf')])
def test_final_invalid_amount_blocks_instead_of_becoming_zero(amount):
    with pytest.raises(ValueError, match='金额'):
        calculate([item(china_to_mexico_freight_rmb=900)], [final_rule(amount)])


def test_ddp_final_replaces_customs_totals_components_tax_and_old_rules():
    rows, summary = calculate([item(china_to_mexico_freight_rmb=900, mexico_customs_mxn=200,
                                    mexico_customs_rmb=80, mexico_customs_usd=30,
                                    import_tax_total=70, igi_amount=20, iva_amount=50, service_aa=130)],
                              [final_rule(40, covered_scopes='freight,customs,tax'),
                               {'rule_code': 'mexico_customs', 'amount': 200, 'currency': 'MXN'},
                               {'rule_code': 'import_tax', 'amount': 70, 'currency': 'MXN'}])
    assert rows[0]['total_cost_rmb'] == 140
    assert rows[0]['total_logistics_mxn'] == 100
    assert summary['fee_pool_rmb'] == 40
    assert json.loads(rows[0]['derived_json'])['direct_customs']['amount_rmb'] == 0


def test_freight_final_keeps_uncovered_customs_and_misc_fallback():
    rows, _ = calculate([item(china_to_mexico_freight_rmb=900, mexico_misc_mxn=25,
                              import_tax_total=50, service_aa=25)], [final_rule()])
    assert rows[0]['freight_alloc_rmb'] == 0
    assert rows[0]['total_logistics_mxn'] == 100
    assert rows[0]['total_cost_rmb'] == 140


@pytest.mark.parametrize('scope,expected_mxn', [('customs', 50), ('tax', 25)])
def test_partial_final_scope_preserves_uncovered_components(scope, expected_mxn):
    rows, _ = calculate([item(import_tax_total=50, service_aa=25)],
                        [final_rule(0, covered_scopes=scope)])
    assert rows[0]['total_logistics_mxn'] == expected_mxn


def test_partial_scope_cannot_silently_split_combined_customs_total():
    with pytest.raises(ValueError, match='范围|覆盖'):
        calculate([item(mexico_customs_mxn=200)], [final_rule(10, covered_scopes='tax')])


def test_partial_legacy_bundle_overlap_blocks():
    with pytest.raises(ValueError, match='范围|覆盖'):
        calculate([item()], [final_rule(10), {'rule_code': 'bundle', 'covered_scopes': 'freight,customs',
                                            'amount': 300, 'currency': 'RMB'}])


@pytest.mark.parametrize('scopes', ['', 'freight,unknown'])
def test_final_requires_unambiguous_scope(scopes):
    with pytest.raises(ValueError, match='范围|覆盖'):
        calculate([item()], [final_rule(10, covered_scopes=scopes)])


@pytest.mark.parametrize('amount', ['1', '-1', '0.000001', '-0.000001', '0.100005'])
def test_each_pool_allocates_exact_six_decimal_total_with_stable_ties(amount):
    source_items = [item('C'), item('A'), item('B')]
    rule = final_rule(amount)
    rows, summary = calculate(source_items, [rule])
    rmb = allocations(rows)
    mxn = allocations(rows, 'mxn')
    assert sum(values[0] for values in rmb.values()) == Decimal(amount)
    assert sum(values[0] for values in mxn.values()) == Decimal(str(summary['fee_pool_mxn']))
    reverse_rows, _ = calculate(list(reversed(source_items)), [rule])
    assert allocations(reverse_rows) == rmb
    assert allocations(reverse_rows, 'mxn') == mxn
    assert abs(rmb['A'][0]) >= abs(rmb['B'][0])
    assert sum(Decimal(str(row['total_cost_rmb'])) for row in rows) == Decimal(str(summary['total_cost_rmb']))
    assert summary['calculation_review']['status'] == 'usable'


def test_detail_pools_each_balance_without_adding_source_total_or_legacy_amount():
    rules = [final_rule('1', rule_code='settlement_freight_a'),
             final_rule('-0.2', rule_code='settlement_freight_credit')]
    rows, summary = calculate([item('C', china_to_mexico_freight_rmb=100), item('A'), item('B')], rules)
    allocated = allocations(rows)
    assert sum(values[0] for values in allocated.values()) == Decimal('1')
    assert sum(values[1] for values in allocated.values()) == Decimal('-0.2')
    assert summary['fee_pool_rmb'] == 0.8
    assert summary['total_cost_rmb'] == 300.8


def test_quantity_change_recomputes_unit_totals_without_overwriting_purchase_price():
    rows, _ = calculate([item(quantity=4, unit_price=17, goods_value=100, total_unit_rmb=500,
                              alloc_price_mxn=999)], [final_rule(20)])
    assert rows[0]['unit_price'] == 17
    assert rows[0]['goods_value'] == 100
    assert rows[0]['total_unit_rmb'] == 30
    assert rows[0]['alloc_price_mxn'] == 12.5


def mock_formal_calculation(monkeypatch, rules, fx=None):
    from overseas_costing.services import cost_preview_service
    writes = []
    fake_db = SimpleNamespace(get_value=lambda *args, **kwargs: {'name': 'B', 'extra_json': '{}', 'modified': 'M1', 'current_version': 'V'},
                              set_value=lambda *args, **kwargs: writes.append((args, kwargs)), commit=lambda: None, rollback=lambda: None)
    fake_frappe = SimpleNamespace(db=fake_db, get_all=lambda *args, **kwargs: [], utils=SimpleNamespace(now=lambda: '2026-09-09 12:00:00'))
    monkeypatch.setattr(service, '_frappe', fake_frappe)
    monkeypatch.setattr(cost_preview_service, 'frappe', fake_frappe)
    monkeypatch.setattr(service, '_resolve_batch_name', lambda _: 'B')
    monkeypatch.setattr(service, '_resolve_version_name', lambda *_: 'V')
    monkeypatch.setattr(service, '_get_items', lambda *_: [item(china_to_mexico_freight_rmb=900)])
    monkeypatch.setattr(service, '_insert_audit_log', lambda **kwargs: None)

    class SnapshotRepository(cost_preview_service.FrappeCostRepository):
        # Replace database input loading only; use the actual production trial
        # calculation, snapshot construction and Frappe repository save methods.
        def lock_and_load(self, *args, **kwargs):
            context = {'batch': 'B', 'version': 'V', 'current_version': 'V', 'batch_modified': 'M1',
                       'version_status': 'Active', 'transport_mode': 'SEA'}
            items = [{'unit': '件', 'actual_shipped_qty': row['quantity'], **row} for row in service._get_items('B', 'V')]
            current_rules = [{'logical_fee_key': row['rule_code'], 'amount_status': 'ACTUAL', **row} for row in rules]
            return context, items, current_rules, fx if fx is not None else {'fx_rmb_to_mxn': 2.5}
    monkeypatch.setattr(cost_preview_service, 'FrappeCostRepository', SnapshotRepository)
    def no_ai(**kwargs):
        raise AssertionError('final pools must not be replaced by AI or legacy normalization')
    monkeypatch.setattr(service.allocation_service, 'suggest_allocation_rules_with_ai', no_ai)
    return writes


@pytest.mark.parametrize('rules,fx', [([final_rule(is_enabled=0)], None),
                                    ([final_rule(100, currency='USD')], None),
                                    ([final_rule(100, currency='MXN')], {'fx_rmb_to_mxn': 0})])
def test_formal_recalculation_blocks_invalid_final_before_any_writes(monkeypatch, rules, fx):
    writes = mock_formal_calculation(monkeypatch, rules, fx)
    with pytest.raises(ValueError):
        service.recalculate_batch('B')
    assert writes == []


def test_formal_zero_retains_final_metadata_and_never_calls_ai(monkeypatch):
    rules = [final_rule()]
    writes = mock_formal_calculation(monkeypatch, rules)
    result = service.recalculate_batch('B')
    assert result['ok'] is True
    assert Decimal(result['summary_snapshot']['total_cost_rmb']) == 100
    assert result['included_fees'][0]['source_binding_id'] == 'BINDING-1'
    assert writes


def test_rule_read_includes_final_source_and_coverage_metadata(monkeypatch):
    captured = {}
    def get_all(doctype, **kwargs):
        captured.update(kwargs)
        return []
    monkeypatch.setattr(service, '_frappe', SimpleNamespace(get_all=get_all))
    service._get_rules('B', 'V')
    assert {'is_final', 'source_binding_id', 'source_snapshot', 'covered_scopes'} <= set(captured['fields'])


def test_explicitly_missing_legacy_fx_is_not_replaced_with_assumed_rate():
    with pytest.raises(ValueError, match='汇率'):
        calculate([item()], [{'rule_code': 'legacy_freight', 'amount': 100, 'currency': 'MXN'}],
                  fx_rmb_to_mxn=None)


def test_final_missing_fx_argument_never_uses_legacy_default():
    with pytest.raises(ValueError, match='汇率'):
        service.calculate_item_rows([item()], [final_rule(100, currency='MXN')])


@pytest.mark.parametrize('provenance', [
    {'source_binding_id': ''}, {'source_snapshot': ''},
])
def test_final_rule_requires_traceable_source(provenance):
    with pytest.raises(ValueError, match='来源'):
        calculate([item()], [final_rule(100, **provenance)])


@pytest.mark.parametrize('provenance', [
    {'source_binding_id': 'BINDING-2'}, {'source_snapshot': 'SNAPSHOT-2'},
])
def test_overlapping_final_sources_or_snapshots_cannot_both_be_charged(provenance):
    with pytest.raises(ValueError, match='来源|快照'):
        calculate([item()], [final_rule(100), final_rule(200, rule_code='settlement_freight_other', **provenance)])


def test_rule_item_read_keeps_chargeable_weight_for_final_allocation(monkeypatch):
    source_rows = [item('A', gross_weight_kg=1, chargeable_weight_kg=3, volume_weight_kg=4),
                   item('B', gross_weight_kg=1, chargeable_weight_kg=1, volume_weight_kg=2)]
    def get_all(_doctype, **kwargs):
        return [{field: row[field] for field in kwargs['fields'] if field in row} for row in source_rows]
    monkeypatch.setattr(service, '_frappe', SimpleNamespace(get_all=get_all))
    rows, _ = calculate(service._get_items('B', 'V'), [final_rule(100, allocation_basis='chargeable_weight')])
    assert [row['freight_alloc_rmb'] for row in rows] == [75, 25]


def test_formal_legacy_missing_snapshot_fx_is_excluded_without_fake_conversion(monkeypatch):
    rules = [{'rule_code': 'legacy_freight', 'amount': 100, 'currency': 'MXN'}]
    writes = mock_formal_calculation(monkeypatch, rules, {'fx_rmb_to_mxn': None})
    result = service.recalculate_batch('B')
    assert result['ok'] and not result['summary']['is_complete']
    assert Decimal(result['summary']['total_cost_rmb']) == 100
    assert result['excluded_fees'][0]['reason_code'] == 'FX_RATE_MISSING'


def test_superseded_freight_rule_does_not_drop_uncovered_misc_fallback():
    items = [item(mexico_misc_mxn=25)]
    old = {'rule_code': 'oa_logistics_freight', 'amount': 500, 'currency': 'RMB', 'is_enabled': 1}
    rows_without_old, summary_without_old = calculate(items, [final_rule()])
    rows_with_old, summary_with_old = calculate(items, [old, final_rule()])
    assert rows_with_old[0]['total_logistics_mxn'] == rows_without_old[0]['total_logistics_mxn'] == 25
    assert summary_with_old['fee_pool_rmb'] == summary_without_old['fee_pool_rmb'] == 10


@pytest.mark.parametrize('old_rules,expected_mxn', [
    ([{'rule_code': 'mexico_misc_mxn', 'amount': 25, 'currency': 'MXN', 'is_enabled': 0}], 0),
    ([{'rule_code': 'oa_logistics_freight', 'amount': 500, 'currency': 'RMB', 'is_enabled': 1}], 25),
])
def test_formal_recalculation_uses_and_snapshots_exact_selected_fee_pools(monkeypatch, old_rules, expected_mxn):
    items = [item(mexico_misc_mxn=25)]
    rules = [final_rule(), *old_rules]
    preview_rows, preview_summary = calculate(items, rules)
    writes = mock_formal_calculation(monkeypatch, rules)
    monkeypatch.setattr(service, '_get_items', lambda *_: items)
    result = service.recalculate_batch('B')
    assert result['ok'] is True
    assert preview_summary['total_logistics_mxn'] == expected_mxn
    item_update = next(args[2] for args, _ in writes if args[0] == 'Overseas Cost Item')
    assert Decimal(item_update['total_logistics_mxn']) == Decimal(str(preview_rows[0]['total_logistics_mxn'])) == expected_mxn
    actual_rules = json.loads(item_update['derived_json'])['allocated_rules']
    reported_codes = [rule['fee_key'] for rule in result['included_fees']]
    assert [rule['rule_code'] for rule in actual_rules] == reported_codes
    assert result['summary_snapshot']['rule_count'] == len(reported_codes)
    version_update = next(args[2] for args, _ in writes if args[0] == 'Overseas Cost Version')
    assert json.loads(version_update['rule_snapshot_json']) == result['included_fees']


def test_explicit_disabled_rule_also_suppresses_legacy_item_fallback_without_final():
    rows, _ = calculate([item(mexico_misc_mxn=25)], [
        {'rule_code': 'mexico_misc_mxn', 'amount': 25, 'currency': 'MXN', 'is_enabled': 0},
    ])
    assert rows[0]['total_logistics_mxn'] == 0


@pytest.mark.parametrize('scope', ['freight', 'freight,customs,tax'])
def test_international_freight_or_ddp_does_not_imply_mexico_inland_coverage(scope):
    rows, _ = calculate([item(mexico_inland_mxn=25)], [final_rule(0, covered_scopes=scope)])
    assert rows[0]['total_logistics_mxn'] == 25


@pytest.mark.parametrize('field,currency', [('mexico_inland_mxn', 'MXN'), ('mexico_inland_misc_rmb', 'RMB')])
@pytest.mark.parametrize('explicit_old_rule', [False, True])
def test_explicit_mexico_inland_coverage_replaces_inland_field_or_rule_only(field, currency, explicit_old_rule):
    rules = [final_rule(0, covered_scopes='freight,customs,tax,mexico_inland')]
    if explicit_old_rule:
        rules.append({'rule_code': field, 'amount': 100, 'currency': currency, 'is_enabled': 1})
    rows, summary = calculate([item(**{field: 100, 'mexico_misc_mxn': 25})], rules)
    assert rows[0]['total_logistics_mxn'] == 25
    assert summary['fee_pool_rmb'] == 10
    assert 'mexico_inland' in summary['final_covered_scopes']


def test_uncovered_inland_fallback_is_preserved_alongside_explicit_misc_rule():
    rows, summary = calculate([item(mexico_inland_mxn=25, mexico_misc_mxn=70)], [
        final_rule(),
        {'rule_code': 'mexico_misc_mxn', 'amount': 50, 'currency': 'MXN', 'allocation_basis': 'gross_weight'},
    ])
    assert rows[0]['total_logistics_mxn'] == 75
    assert summary['fee_pool_rmb'] == 30
    actual_rules = json.loads(rows[0]['derived_json'])['allocated_rules']
    assert [rule['rule_code'] for rule in actual_rules].count('mexico_misc_mxn') == 1


@pytest.mark.parametrize('enabled,freight', [(1, 500), (0, 0)])
def test_uncovered_fallback_does_not_duplicate_explicit_freight_under_another_code(enabled, freight):
    rows, _ = calculate([item(china_to_mexico_freight_rmb=900, mexico_misc_mxn=25)], [
        final_rule(0, covered_scopes='customs'),
        {'rule_code': 'oa_logistics_freight', 'amount': 500, 'currency': 'RMB',
         'allocation_basis': 'gross_weight', 'is_enabled': enabled},
    ])
    assert rows[0]['total_logistics_mxn'] == freight * 2.5 + 25
    assert rows[0]['freight_alloc_rmb'] == freight
