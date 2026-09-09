"""Disposable local Frappe/MariaDB integration checks; refuses every non-test site.
Run inside bench/sites with PYTHONPATH=/tmp/settlement-code and the bench Python.
No credentials are read or printed; frappe reads the isolated site's config itself.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import frappe

SITE = 'settlement-test.local'


def connect():
    frappe.init(site=SITE)
    assert frappe.conf.db_host == 'oc-settlement-test-db', 'Refuse non-test database'
    frappe.connect()
    frappe.set_user('Administrator')


def report(case, **details):
    print(json.dumps({'case': case, **details}, ensure_ascii=False, default=str), flush=True)


def worker():
    connect()
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.services.logistics_settlement.matching import confirm_candidate
    candidate_id, revision, barrier, ready = sys.argv[2:]
    Path(ready).touch()
    deadline = time.monotonic() + 15
    while not Path(barrier).exists():
        assert time.monotonic() < deadline, 'Barrier timed out'
        time.sleep(.03)
    try:
        result = confirm_candidate(Store.frappe(), candidate_id, revision, 'local-test', resolve=True, reason='本地并发唯一性验证')
        frappe.db.commit()
        report('worker', ok=True, binding=result['id'])
    except Exception as exc:
        frappe.db.rollback()
        report('worker', ok=False, error=type(exc).__name__, message=str(exc))
    finally:
        frappe.destroy()


def main():
    connect()
    from overseas_costing.services.logistics_settlement.schema import install
    from overseas_costing.services.logistics_settlement.store import Store, TABLES
    from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
    from overseas_costing.services.logistics_settlement.model import parse_source, dumps
    from overseas_costing.services.logistics_settlement.matching import match_source, confirm_candidate, replace_binding
    from overseas_costing.services.logistics_settlement.writer import apply_binding, reverse_binding, resolve_item_checks, item_review
    from overseas_costing.services.logistics_settlement.runtime import calculation_blockers
    from overseas_costing.services.calculate_service import recalculate_batch

    run = uuid.uuid4().hex[:10]
    db, ledger = Store.frappe(), FrappeLedger()
    install(); install()
    assert all(frappe.db.sql('SHOW TABLES LIKE %s', ('oc_ls_' + table,)) for table in TABLES)
    assert all(frappe.db.has_column('Overseas Cost Allocation Rule', field) for field in ('source_binding_id', 'source_snapshot', 'covered_scopes', 'is_final'))
    indexes = frappe.db.sql('SHOW INDEX FROM oc_ls_binding', as_dict=True)
    assert {'logistics_id', 'expense_id'} <= {row['Column_name'] for row in indexes if not row['Non_unique']}
    report('schema_idempotent', ok=True, tables=len(TABLES))

    def source(instance, kind='expense', corp=None, amount='0', quantity=None, hour='00'):
        fields = [{'name': '运输说明', 'value': '海运 MXT500174'}]
        if kind == 'expense':
            fields += [{'name': '采购支出', 'value': '服务类采购Compra De Servicios'},
                       {'name': '服务类采购', 'value': '物流及运输服务Servicios de logística y transporte'},
                       {'name': '总金额Monto Total', 'value': amount}, {'name': '币种Moneda', 'value': 'RMB'}]
        if quantity is not None:
            fields.append({'name': '货物明细', 'componentType': 'TableField', 'value': [
                {'rowId': 'a', 'rowValue': [{'name': '物料编码', 'value': 'A'},
                                          {'name': '数量', 'value': str(quantity)}, {'name': '单位', 'value': '件'}]}]})
        return {'corp_id': corp, 'process_instance_id': instance, 'process_code': kind,
                'updated_at': '2026-09-09T' + hour + ':00:00+00:00', 'status': 'COMPLETED', 'result': 'agree',
                'raw_payload': {'formComponentValues': fields}}

    def ingest(row):
        return db.ingest(parse_source(row, logistics_codes={'logistics'}))

    def fixture(tag, amount='0', quantity=2):
        corp = 'LOCAL-' + run + '-' + tag
        batch = ledger.create('batch', {'batch_no': corp, 'status': 'Draft', 'confirm_status': 'Pending', 'source_corp_id': corp})
        version = ledger.create('version', {'batch': batch['name'], 'version_code': 'LOCAL-INITIAL', 'status': 'Active', 'is_current': 1, 'fx_rmb_to_mxn': 2.5})
        ledger.put('batch', batch['name'], {'current_version': version['name']})
        item = ledger.create('item', {'batch': batch['name'], 'version': version['name'], 'row_no': 1,
                                     'material_code': 'A', 'product_name': '本地结算测试物料', 'unit': '件',
                                     'quantity': 2, 'actual_shipped_qty': 2, 'unit_price': 10, 'goods_value': 20,
                                     'gross_weight_kg': 4, 'volume_m3': 3, 'china_to_mexico_freight_rmb': 200,
                                     'extra_json': dumps({'goods_value_source': 'derived_quantity_unit_price'})})
        rule = ledger.create('rule', {'batch': batch['name'], 'version': version['name'], 'rule_code': 'oa_logistics_freight',
                                     'amount': 200, 'currency': 'RMB', 'allocation_basis': 'gross_weight', 'is_enabled': 1, 'is_active': 1})
        logistics = ingest(source(corp + '-L', 'logistics', corp=corp))
        expense = ingest(source(corp + '-E', corp=corp, amount=amount, quantity=quantity))
        candidate = match_source(db, expense['id'])[0]
        binding = confirm_candidate(db, candidate['id'], candidate['revision'], 'local-test')
        db.insert('batch_map', {'id': logistics['id'], 'source_id': logistics['id'], 'batch': batch['name'], 'data': '{}'})
        db.commit()
        return corp, batch, version, item, rule, binding

    corp, batch, version, item, rule, binding = fixture('zero')
    applied = apply_binding(db, ledger, binding['id'], 'local-test')
    assert applied['application_status'] == 'applied', applied.get('issues')
    assert ledger.get('rule', rule['name'])['is_enabled'] == 0
    final = [r for r in ledger.rows('rule', batch=batch['name'], version=version['name']) if r.get('is_final')]
    assert len(final) == 1 and float(final[0]['amount']) == 0
    calc = recalculate_batch(batch['name'])
    assert calc['ok'] and calc['summary_snapshot']['total_cost_rmb'] == 20, calc
    again = apply_binding(db, ledger, binding['id'], 'local-test')
    assert again['last_application'] == applied['last_application']
    assert db.count('application', binding_id=binding['id']) == 1
    db.commit()
    report('zero_apply_recalculate_idempotent', ok=True, batch=batch['name'])

    corp, batch, version, item, rule, binding = fixture('quantity', '100', 4)
    applied = apply_binding(db, ledger, binding['id'], 'local-test')
    assert applied['application_status'] == 'applied_pending'
    updated = ledger.get('item', item['name'])
    assert float(updated['quantity']) == 4 and float(updated['goods_value']) == 40 and float(updated['unit_price']) == 10
    assert float(updated['gross_weight_kg']) == 4 and float(updated['volume_m3']) == 3
    assert calculation_blockers(batch['name'], version['name'])
    blocked = recalculate_batch(batch['name'])
    assert blocked['ok'] is False
    resolved = resolve_item_checks(db, ledger, binding['id'], 1, [{'item_name': item['name'],
             'expected_item_hash': item_review(updated)['revision'], 'packing_confirmed': True}], '本地核对保留装箱资料', 'local-test')
    assert resolved['application_status'] == 'applied'
    calc = recalculate_batch(batch['name'])
    assert calc['ok'] and calc['summary_snapshot']['total_cost_rmb'] == 140, calc
    ledger.put('version', version['name'], {'status': 'Confirmed'})
    ledger.put('batch', batch['name'], {'confirm_status': 'Confirmed'})
    ingest(source(corp + '-E', corp=corp, amount='120', quantity=4, hour='01'))
    adjusted = apply_binding(db, ledger, binding['id'], 'local-test')
    assert adjusted['version'] != version['name']
    assert ledger.get('version', version['name'])['status'] == 'Confirmed'
    assert float(ledger.get('item', item['name'])['total_cost_rmb']) == 140
    assert len(ledger.rows('version', batch=batch['name'])) == 2
    apply_binding(db, ledger, binding['id'], 'local-test')
    assert len(ledger.rows('version', batch=batch['name'])) == 2
    frozen = recalculate_batch(batch['name'], version_name=version['name'])
    assert frozen['ok'] is False
    db.commit()
    report('quantity_packing_resolution_and_confirmed_freeze', ok=True, batch=batch['name'], adjustment=adjusted['version'])

    corp, batch, version, item, rule, binding = fixture('rollback', '100', 4)
    class FailingLedger(FrappeLedger):
        def create(self, kind, values):
            if kind == 'rule':
                raise RuntimeError('injected local rule failure')
            return super().create(kind, values)
    try:
        apply_binding(db, FailingLedger(), binding['id'], 'local-test')
        raise AssertionError('Expected application failure')
    except RuntimeError as exc:
        assert str(exc) == 'injected local rule failure'
    assert float(ledger.get('item', item['name'])['quantity']) == 2
    assert ledger.get('rule', rule['name'])['is_enabled'] == 1
    assert db.count('application', binding_id=binding['id']) == 0
    apply_binding(db, ledger, binding['id'], 'local-test')
    replacement = ingest(source(corp + '-E2', corp=corp, amount='50', quantity=2))
    candidate = match_source(db, replacement['id'])[0]
    before_item = ledger.get('item', item['name'])
    before_rules = ledger.rows('rule', batch=batch['name'], version=version['name'])
    before_audit = db.count('audit', binding_id=binding['id'])
    def fail_after_reverse(old, new):
        reverse_binding(db, ledger, old, new, 'local-test')
        raise RuntimeError('injected local reverse failure')
    try:
        replace_binding(db, binding['id'], 1, candidate['id'], candidate['revision'], 'local-test', '本地回滚验证', on_replace=fail_after_reverse)
        raise AssertionError('Expected replacement failure')
    except RuntimeError as exc:
        assert str(exc) == 'injected local reverse failure'
    assert db.get('binding', binding['id'])['expense_id'] == binding['expense_id']
    assert ledger.get('item', item['name']) == before_item
    assert ledger.rows('rule', batch=batch['name'], version=version['name']) == before_rules
    assert db.count('audit', binding_id=binding['id']) == before_audit
    replaced = replace_binding(db, binding['id'], 1, candidate['id'], candidate['revision'], 'local-test', '本地更正验证',
                               on_replace=lambda old, new: reverse_binding(db, ledger, old, new, 'local-test'))
    applied = apply_binding(db, ledger, replaced['id'], 'local-test')
    final = [r for r in ledger.rows('rule', batch=batch['name'], version=version['name']) if r.get('is_final')]
    assert len(final) == 1 and float(final[0]['amount']) == 50
    db.commit()
    report('application_and_rebind_atomic_rollback', ok=True, batch=batch['name'])

    for axis in ('logistics', 'expense'):
        corp = 'LOCAL-' + run + '-race-' + axis
        logistics = [ingest(source(corp + '-L' + str(i), 'logistics', corp=corp)) for i in range(1 if axis == 'logistics' else 2)]
        expenses = [ingest(source(corp + '-E' + str(i), corp=corp)) for i in range(2 if axis == 'logistics' else 1)]
        candidates = [candidate for expense in expenses for candidate in match_source(db, expense['id'])]
        assert len(candidates) == 2
        db.commit()
        barrier = '/tmp/settlement-race-' + run + '-' + axis
        processes = []
        for i, candidate in enumerate(candidates):
            ready = barrier + '.ready' + str(i)
            process = subprocess.Popen([sys.executable, __file__, '--worker', candidate['id'], candidate['revision'], barrier, ready], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append((process, ready))
        deadline = time.monotonic() + 15
        while not all(Path(ready).exists() for _, ready in processes):
            assert time.monotonic() < deadline, 'Worker startup timed out'
            time.sleep(.03)
        Path(barrier).touch()
        results = []
        for process, _ in processes:
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip().splitlines()[-1]))
        assert sorted(result['ok'] for result in results) == [False, True], results
        frappe.db.rollback()  # refresh read snapshot after worker commits
        assert sum(db.count('binding', logistics_id=logistic['id']) for logistic in logistics) == 1
        report('concurrent_' + axis + '_uniqueness', ok=True, outcomes=results)
    report('integration_complete', ok=True, run=run, site=SITE)
    frappe.destroy()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker()
    else:
        main()
