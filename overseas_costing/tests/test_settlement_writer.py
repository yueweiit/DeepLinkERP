import json
import sqlite3
import uuid

import pytest

from overseas_costing.services.logistics_settlement.store import Store
from overseas_costing.services.logistics_settlement.model import dumps
from overseas_costing.tests.test_logistics_settlement import source, ingest, table_row
from overseas_costing.services.logistics_settlement.matching import match_source, confirm_candidate, replace_binding


class Ledger:
    def __init__(self, store):
        self.store = store
        store.sql('CREATE TABLE cost_docs (id TEXT PRIMARY KEY, kind TEXT, data TEXT)')
        self.fail_rules = False

    def get(self, kind, name, lock=False):
        rows = self.store.sql('SELECT data FROM cost_docs WHERE id=%s AND kind=%s', (name, kind))
        return json.loads(rows[0]['data']) if rows else None

    def rows(self, kind, **filters):
        docs = [json.loads(r['data']) for r in self.store.sql('SELECT data FROM cost_docs WHERE kind=%s', (kind,))]
        return [d for d in docs if all(d.get(k) == v for k, v in filters.items())]

    def create(self, kind, values):
        if self.fail_rules and kind == 'rule':
            raise RuntimeError('failed rule write')
        data = {**values, 'name': uuid.uuid4().hex}
        self.store.sql('INSERT INTO cost_docs VALUES (%s,%s,%s)', (data['name'], kind, dumps(data)))
        return data

    def put(self, kind, name, values):
        data = {**self.get(kind, name), **values}
        self.store.sql('UPDATE cost_docs SET data=%s WHERE id=%s', (dumps(data), name))
        return data

    def delete(self, kind, name):
        self.store.sql('DELETE FROM cost_docs WHERE id=%s AND kind=%s', (name, kind))


@pytest.fixture
def setup():
    store = Store.sqlite(sqlite3.connect(':memory:')); store.install()
    ledger = Ledger(store)
    batch = ledger.create('batch', {'batch_no': 'B', 'status': 'Calculated', 'confirm_status': 'Pending'})
    version = ledger.create('version', {'batch': batch['name'], 'status': 'Active', 'is_current': 1})
    ledger.put('batch', batch['name'], {'current_version': version['name']})
    item = ledger.create('item', {'batch': batch['name'], 'version': version['name'], 'material_code': 'A', 'unit': '件', 'quantity': 2, 'unit_price': 10, 'goods_value': 20, 'gross_weight_kg': 4, 'volume_m3': 3, 'extra_json': dumps({'goods_value_source': 'derived_quantity_unit_price'})})
    rule = ledger.create('rule', {'batch': batch['name'], 'version': version['name'], 'rule_code': 'oa_logistics_freight', 'amount': 200, 'currency': 'RMB', 'is_enabled': 1, 'is_active': 1})
    logistics = ingest(store, source('L', 'logistics'))
    row = source('E', amount='100')
    row['raw_payload']['formComponentValues'].append({'name': '货物明细', 'componentType': 'TableField', 'value': [table_row('a', quantity='4')]})
    expense = ingest(store, row)
    candidate = match_source(store, expense['id'])[0]
    binding = confirm_candidate(store, candidate['id'], candidate['revision'], 'u')
    store.insert('batch_map', {'id': logistics['id'], 'source_id': logistics['id'], 'batch': batch['name'], 'data': '{}'})
    return store, ledger, batch, version, item, rule, binding


def test_application_atomic_quantity_packing_and_repeated_sync(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    s, l, batch, version, item, rule, binding = setup
    applied = apply_binding(s, l, binding['id'], 'u')
    assert applied['application_status'] == 'applied_pending'
    changed = l.get('item', item['name'])
    assert str(changed['quantity']) == '4'
    assert str(changed['goods_value']) == '40'
    assert changed['gross_weight_kg'] == 4 and changed['volume_m3'] == 3
    assert json.loads(changed['extra_json'])['settlement_packing_review']
    assert l.get('rule', rule['name'])['is_enabled'] == 0
    assert len(l.rows('rule')) == 2
    apply_binding(s, l, binding['id'], 'u')
    assert len(l.rows('rule')) == 2 and s.count('application') == 1


def test_failed_application_rolls_back_items_and_version(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    s, l, batch, version, item, rule, binding = setup
    l.fail_rules = True
    with pytest.raises(RuntimeError):
        apply_binding(s, l, binding['id'], 'u')
    assert l.get('item', item['name'])['quantity'] == 2
    assert l.get('rule', rule['name'])['is_enabled'] == 1
    assert s.count('application') == 0
    assert s.get('binding', binding['id'])['application_status'] == 'pending'


def test_confirmed_version_freezes_and_source_noop_creates_no_second_draft(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    s, l, batch, version, item, rule, binding = setup
    l.put('version', version['name'], {'status': 'Confirmed'})
    l.put('batch', batch['name'], {'confirm_status': 'Confirmed', 'writeback_status': 'Success'})
    applied = apply_binding(s, l, binding['id'], 'u')
    assert applied['version'] != version['name']
    assert l.get('version', version['name'])['status'] == 'Confirmed'
    assert l.get('item', item['name'])['quantity'] == 2
    assert l.get('rule', rule['name'])['is_enabled'] == 1
    apply_binding(s, l, binding['id'], 'u')
    assert len(l.rows('version')) == 2


def test_manual_edit_lock_queues_application(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding
    s, l, batch, version, item, rule, binding = setup
    l.put('batch', batch['name'], {'edit_lock_expires_at': '2099-01-01 00:00:00', 'edit_lock_owner': 'other'})
    result = apply_binding(s, l, binding['id'], 'u')
    assert result['application_status'] == 'queued'
    assert s.count('application') == 0
    assert l.get('item', item['name'])['quantity'] == 2


def test_rebind_removes_old_final_rules_in_same_transaction(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding, reverse_binding
    s, l, batch, version, item, rule, binding = setup
    apply_binding(s, l, binding['id'], 'u')
    b = ingest(s, source('E2', amount='50'))
    c = match_source(s, b['id'])[0]
    updated = replace_binding(s, binding['id'], 1, c['id'], c['revision'], 'u', '错误关联', on_replace=lambda old,new: reverse_binding(s,l,old,new,'u'))
    apply_binding(s, l, updated['id'], 'u')
    final = [r for r in l.rows('rule') if r.get('is_final') and r.get('is_enabled')]
    assert len(final) == 1 and str(final[0]['amount']) == '50'
    assert l.get('item', item['name'])['gross_weight_kg'] == 4
    assert s.count('audit', action='replace') == 1


def test_rebind_restores_retired_original_row_with_packing(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding, reverse_binding
    s,l,batch,version,item,rule,binding = setup
    retired = l.create('item', {'batch':batch['name'], 'version':version['name'], 'material_code':'B','unit':'件','quantity':7,'gross_weight_kg':9,'volume_m3':2})
    apply_binding(s,l,binding['id'],'u')
    assert l.get('item',retired['name']) is None
    b=ingest(s,source('E2',amount='50')); c=match_source(s,b['id'])[0]
    replace_binding(s,binding['id'],1,c['id'],c['revision'],'u','错误关联',on_replace=lambda old,new:reverse_binding(s,l,old,new,'u'))
    restored=[i for i in l.rows('item') if i['material_code']=='B']
    assert len(restored)==1 and restored[0]['gross_weight_kg']==9 and restored[0]['quantity']==7


def test_resolve_checks_refreshes_status_without_duplicate_application(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding, resolve_item_checks, item_review
    s,l,batch,version,item,rule,binding=setup
    apply_binding(s,l,binding['id'],'u')
    l.put('version',version['name'], {'fx_rmb_to_mxn':2.6})
    current=l.get('item',item['name'])
    resolve_item_checks(s,l,binding['id'],1,[{'item_name':item['name'],'expected_item_hash':item_review(current)['revision'],'packing_confirmed':True}], '已逐项核对装箱重量体积','u')
    result=apply_binding(s,l,binding['id'],'u')
    assert result['application_status']=='applied' and not result['issues']
    assert s.count('application')==1 and len(l.rows('rule'))==2


def test_item_check_rejects_stale_evidence(setup):
    from overseas_costing.services.logistics_settlement.writer import apply_binding, resolve_item_checks, item_review
    s,l,batch,version,item,rule,binding=setup
    apply_binding(s,l,binding['id'],'u')
    token=item_review(l.get('item',item['name']))['revision']
    l.put('item',item['name'],{'gross_weight_kg':100})
    with pytest.raises(ValueError, match='变化'):
        resolve_item_checks(s,l,binding['id'],1,[{'item_name':item['name'],'expected_item_hash':token,'packing_confirmed':True}], '核对','u')
    assert json.loads(l.get('item',item['name'])['extra_json'])['settlement_packing_review']


def test_scope_and_negative_acknowledgment_cannot_apply_to_new_unseen_source(setup):
    from overseas_costing.services.logistics_settlement.writer import validate_application_preview,apply_binding
    from overseas_costing.services.logistics_settlement.matching import configure_binding
    s,l,b,v,i,r,binding=setup
    old=s.get('source',binding['expense_id'])
    row=source('E',amount='-10',text='双清 MXT500174');row['updated_at']='2026-09-09T01:00:00+00:00';old=ingest(s,row)
    binding=configure_binding(s,binding,coverage=['freight','customs'],negative_confirmed=True,actor='u')
    apply_binding(s,l,binding['id'],'u')
    row['raw_payload']['formComponentValues'][3]['value']='-1000';row['updated_at']='2026-09-09T02:00:00+00:00';ingest(s,row)
    with pytest.raises(ValueError,match='支出已变化'):
        validate_application_preview(s,l,binding,old['snapshot'],v['name'])
    result=apply_binding(s,l,binding['id'],'sync')
    assert result['application_status']=='pending'
    assert not any(str(rule.get('amount'))=='-1000' for rule in l.rows('rule'))
