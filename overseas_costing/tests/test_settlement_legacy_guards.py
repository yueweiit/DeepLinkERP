from overseas_costing.scripts import import_oa_logistics as oa
from overseas_costing.services.logistics_settlement import runtime
from overseas_costing.tests.test_logistics_settlement import source, table_row


def test_logistics_service_unit_price_never_becomes_commodity_price():
    raw = source('E')['raw_payload']
    raw['formComponentValues'].append({'name': '明细', 'componentType': 'TableField', 'value': [table_row('a')]})
    assert oa.build_purchase_expense_item_values_from_approval(raw) == []


def test_legacy_fee_and_goods_paths_cannot_restore_estimates(monkeypatch):
    monkeypatch.setattr(runtime, 'has_final_binding', lambda name: True)
    monkeypatch.setattr(oa, 'frappe', object())
    result = oa._sync_oa_logistics_allocation_rule(batch_name='B', version_name='V', approval_item={'logistics_fee': {'amount': 500, 'currency': 'RMB'}})
    assert result['action'] == 'skipped'
    result = oa._replace_items_with_purchase_expense_rows(batch_name='B', version_name='V', approval_item={}, purchase_rows=[{'material_code': 'A'}])
    assert result['action'] == 'skipped'
    result = oa._sync_oa_goods_items(batch_name='B', version_name='V', approval_item={})
    assert result['action'] == 'skipped'
