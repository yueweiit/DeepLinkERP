"""Opt-in document/runtime checks on the guarded disposable Frappe test site.

Upstream parsing is represented by explicit parsed fixtures; File insertion,
permissions, SQL persistence, document/binding writers and calculation are real.
The scheduled retry inventory is scoped to this run to protect concurrent QA.
"""
from copy import deepcopy
from decimal import Decimal
import json
import uuid
from unittest.mock import patch

import frappe

from overseas_costing.tests.integration.run_settlement_frappe_integration import connect, report, SITE


def main():
    connect()
    from frappe.utils.file_manager import save_file
    from overseas_costing.services.logistics_settlement import runtime
    from overseas_costing.services.logistics_settlement.schema import install
    from overseas_costing.services.logistics_settlement.store import Store, TABLES
    from overseas_costing.services.logistics_settlement.ledger import FrappeLedger
    from overseas_costing.services.logistics_settlement.model import parse_source, dumps, digest
    from overseas_costing.services.logistics_settlement.matching import match_source, confirm_candidate
    from overseas_costing.services.logistics_settlement.writer import apply_binding, resolve_item_checks, item_review
    from overseas_costing.services.logistics_settlement.document_writer import sync_logistics_documents
    from overseas_costing.services.calculate_service import recalculate_batch

    run = uuid.uuid4().hex[:10]
    db, ledger = Store.frappe(), FrappeLedger()
    install(); install()
    assert all(frappe.db.sql('SHOW TABLES LIKE %s', ('oc_ls_' + table,)) for table in TABLES)
    report('document_schema_idempotent', ok=True, tables=len(TABLES))
    reader = frappe.get_doc({'doctype': 'User', 'email': 'local-settlement-' + run + '@example.invalid',
        'first_name': 'Local settlement reader', 'enabled': 1, 'send_welcome_email': 0,
        'roles': [{'role': '海外成本核算用户'}]}).insert(ignore_permissions=True)

    def raw_source(corp, kind, amount='0', documents=None, hour='00'):
        fields = [{'name': '运输说明', 'value': '海运 MXT500174'}]
        if kind == 'expense':
            fields += [{'name': '采购支出', 'value': '服务类采购Compra De Servicios'},
                       {'name': '服务类采购', 'value': '物流及运输服务Servicios de logística y transporte'},
                       {'name': '总金额Monto Total', 'value': amount}, {'name': '币种Moneda', 'value': 'RMB'},
                       {'name': '货物明细', 'componentType': 'TableField', 'value': [
                           {'rowId': 'a', 'rowValue': [{'name': '物料编码', 'value': 'A'},
                            {'name': '数量', 'value': '2'}, {'name': '单位', 'value': '件'}]}]}]
        return {'corp_id': corp, 'process_instance_id': corp + '-' + kind, 'process_code': kind,
                'updated_at': '2026-09-09T' + hour + ':00:00+00:00', 'status': 'COMPLETED', 'result': 'agree',
                'raw_payload': {'formComponentValues': fields}, 'settlement_documents': documents or [],
                'attachments': [d['manifest'] for d in documents or []]}

    def ingest(raw):
        return db.ingest(parse_source(raw, logistics_codes={'logistics'}))

    def fixture(tag, amount='0', **physical):
        corp = 'LOCAL-DOC-' + run + '-' + tag
        batch = ledger.create('batch', {'batch_no': corp, 'status': 'Draft', 'confirm_status': 'Pending', 'source_corp_id': corp})
        version = ledger.create('version', {'batch': batch['name'], 'version_code': 'LOCAL-INITIAL', 'status': 'Active',
                                          'is_current': 1, 'fx_rmb_to_mxn': 2.5})
        ledger.put('batch', batch['name'], {'current_version': version['name']})
        item = ledger.create('item', {'batch': batch['name'], 'version': version['name'], 'row_no': 1,
             'material_code': 'A', 'product_name': '本地装箱集成验证', 'unit': '件', 'quantity': 2,
             'actual_shipped_qty': 0, 'unit_price': 10, 'goods_value': 20, 'gross_weight_kg': 0, 'volume_m3': 0,
             'extra_json': dumps({'goods_value_source': 'purchase_approval'}), **physical})
        logistics = ingest(raw_source(corp, 'logistics'))
        expense = ingest(raw_source(corp, 'expense', amount=amount))
        candidate = match_source(db, expense['id'])[0]
        binding = confirm_candidate(db, candidate['id'], candidate['revision'], 'local-document-test')
        db.insert('batch_map', {'id': logistics['id'], 'source_id': logistics['id'], 'batch': batch['name'], 'data': '{}'})
        db.commit()
        return corp, batch, version, item, binding

    def document(tag, *, url=None, **values):
        identity = digest(run, tag, values)
        if url is None:
            # Synthetic bytes intentionally bypass the upstream parser; this tests File registration.
            cached = save_file('local-packing-' + identity[:10] + '.xlsx',
                              ('Synthetic local packing bytes ' + identity).encode(), None, None, is_private=1)
            url = cached.file_url
        fields = {'物料编码': 'A', '规格': '', '单位': '件', '装箱数量': '4', '毛重(kg)': '8',
                  '体积(m³)': '2', '单价': '999', '货值': '99999', **values}
        return {'id': identity, 'file_name': '装箱单.xlsx', 'file_url': url, 'status': 'parsed',
                'manifest': {'file_id': run + '-' + tag, 'archive_status': 'archived', 'archive_quality': 'original',
                             'source_kind': 'comment', 'sha256': identity, 'object_key': identity},
                'tables': [{'kind': 'packing', 'title': '装箱单', 'complete': False,
                           'rows': [{'position': 2, 'rowValue': [{'name': k, 'value': v} for k, v in fields.items()]}]}]}

    def sync(corp, batch, docs, hour='01'):
        source = ingest(raw_source(corp, 'logistics', documents=docs, hour=hour))
        return source, sync_logistics_documents(db, ledger, source, batch['name'], 'local-document-test')

    def file_links(url):
        return frappe.get_all('File', filters={'file_url': url},
                              fields=['name', 'is_private', 'attached_to_doctype', 'attached_to_name'], limit_page_length=0)

    def acknowledge(binding, item_name):
        current = db.get('binding', binding['id'])
        return resolve_item_checks(db, ledger, binding['id'], current['revision'], [
            {'item_name': item_name, 'expected_item_hash': item_review(ledger.get('item', item_name))['revision'],
             'packing_confirmed': True}], '本地已核对装箱与采购数量差异，保留独立采购价格', 'local-document-test')

    corp, batch, version, item, binding = fixture('packing')
    doc = document('packing')
    cache_before = file_links(doc['file_url'])
    source, state = sync(corp, batch, [doc])
    row = ledger.get('item', item['name'])
    assert [Decimal(str(row[k])) for k in ('quantity', 'unit_price', 'goods_value')] == [Decimal(2), Decimal(10), Decimal(20)]
    assert [Decimal(str(row[k])) for k in ('actual_shipped_qty', 'gross_weight_kg', 'volume_m3')] == [Decimal(4), Decimal(8), Decimal(2)]
    meta = json.loads(row['extra_json'])
    assert meta['goods_value_source'] == 'purchase_approval' and meta['settlement_packing_review']
    assert meta['settlement_packing_provenance']['gross_weight_kg']['source_snapshot'] == source['snapshot']
    attachments = ledger.rows('attachment', batch=batch['name'], version=version['name'])
    assert len(attachments) == 1
    parsed = json.loads(attachments[0]['parse_result_json'])
    assert parsed['manual_document']['slot_code'] == 'sea_packing_list' and parsed['cost_source_allowed'] is True
    assert attachments[0]['oa_attachment_origin'] == 'Comment'
    links = file_links(doc['file_url'])
    # Frappe's Attach-field hook may adopt a previously unattached cached File.
    # Once owned by an attachment, every original link must stay unchanged.
    assert len(links) in {len(cache_before), len(cache_before) + 1} and all(link['is_private'] for link in links)
    assert {link['name'] for link in cache_before} <= {link['name'] for link in links}
    assert all(link in links for link in cache_before if link['attached_to_name'])
    assert any(link['attached_to_doctype'] == 'Overseas Cost Attachment' and link['attached_to_name'] == attachments[0]['name'] for link in links)
    linked_file = next(link for link in links if link['attached_to_name'] == attachments[0]['name'])
    assert frappe.get_doc('File', linked_file['name']).has_permission('read', user=reader.name)
    assert not frappe.get_doc('File', linked_file['name']).has_permission('read', user='Guest')
    apply_binding(db, ledger, binding['id'], 'local-document-test')
    assert runtime.calculation_blockers(batch['name'], version['name'])
    assert recalculate_batch(batch['name'])['ok'] is False
    assert acknowledge(binding, item['name'])['application_status'] == 'applied'
    assert not db.get('document_sync', state['id'])['blocking']
    assert not runtime.calculation_blockers(batch['name'], version['name'])
    acknowledged_row = ledger.get('item', item['name'])
    assert recalculate_batch(batch['name'])['ok'] is True
    calculated_row = ledger.get('item', item['name'])
    retry = sync_logistics_documents(db, ledger, source, batch['name'], 'local-document-test')
    assert retry['changed'] is False and not retry['blocking'], {'retry': retry,
        'calculation_changes': {k: [acknowledged_row.get(k), value] for k, value in calculated_row.items()
                                if acknowledged_row.get(k) != value}}
    assert file_links(doc['file_url']) == links
    db.commit()
    report('private_file_packing_precedence_and_review_ack', ok=True, batch=batch['name'])

    # Same physical data URL must be permission-linked to both historical and adjustment cards.
    frozen_item = deepcopy(ledger.get('item', item['name']))
    frozen_attachment = deepcopy(ledger.get('attachment', attachments[0]['name']))
    ledger.put('version', version['name'], {'status': 'Confirmed'})
    ledger.put('batch', batch['name'], {'confirm_status': 'Confirmed'})
    changed_doc = document('packing-corrected', url=doc['file_url'], **{'毛重(kg)': '9'})
    changed_source, changed_state = sync(corp, batch, [changed_doc], hour='02')
    assert changed_state['version'] != version['name'] and len(ledger.rows('version', batch=batch['name'])) == 2
    assert ledger.get('item', item['name']) == frozen_item
    assert ledger.get('attachment', attachments[0]['name']) == frozen_attachment
    current_item = ledger.rows('item', batch=batch['name'], version=changed_state['version'])[0]
    assert Decimal(str(current_item['gross_weight_kg'])) == 8, 'Preserve conflicting physical value'
    assert json.loads(current_item['extra_json'])['settlement_packing_review']
    current_attachments = ledger.rows('attachment', batch=batch['name'], version=changed_state['version'])
    assert len(current_attachments) == 1
    shared_links = file_links(doc['file_url'])
    assert {attachments[0]['name'], current_attachments[0]['name']} <= {link['attached_to_name'] for link in shared_links}
    assert all(link in shared_links for link in links)
    for link in shared_links:
        if link['attached_to_name']:
            assert frappe.get_doc('File', link['name']).has_permission('read', user=reader.name)
        assert not frappe.get_doc('File', link['name']).has_permission('read', user='Guest')
    repeat = sync_logistics_documents(db, ledger, changed_source, batch['name'], 'local-document-test')
    assert repeat['changed'] is False and len(ledger.rows('version', batch=batch['name'])) == 2
    assert file_links(doc['file_url']) == shared_links
    apply_binding(db, ledger, binding['id'], 'local-document-test')
    acknowledge(binding, current_item['name'])
    assert not db.get('document_sync', changed_state['id'])['blocking']
    db.commit()
    report('frozen_document_adjustment_shared_file_and_retry', ok=True, batch=batch['name'], adjustment=changed_state['version'])

    corp, batch, version, item, binding = fixture('retirement')
    doc = document('retired', **{'装箱数量': '2'})
    source, state = sync(corp, batch, [doc])
    assert not state['blocking']
    apply_binding(db, ledger, binding['id'], 'local-document-test')
    frozen_item = deepcopy(ledger.get('item', item['name']))
    frozen_attachment = deepcopy(ledger.rows('attachment', batch=batch['name'])[0])
    old_links = file_links(doc['file_url'])
    ledger.put('version', version['name'], {'status': 'Confirmed'})
    ledger.put('batch', batch['name'], {'confirm_status': 'Confirmed'})
    retired_raw = raw_source(corp, 'logistics', hour='02')
    retired_raw['attachments'] = [{**doc['manifest'], 'retired_at': '2026-09-09T02:00:00+00:00'}]
    retired_source = ingest(retired_raw)
    runtime.apply_source(retired_source['id'])
    retired_state = db.get('document_sync', state['id'])
    assert retired_state['blocking'] and retired_state['version'] != version['name']
    assert ledger.get('item', item['name']) == frozen_item
    assert ledger.get('attachment', frozen_attachment['name']) == frozen_attachment
    current_item = ledger.rows('item', batch=batch['name'], version=retired_state['version'])[0]
    assert Decimal(str(current_item['gross_weight_kg'])) == 8
    assert json.loads(current_item['extra_json'])['settlement_packing_review']
    current_attachment = ledger.rows('attachment', batch=batch['name'], version=retired_state['version'])[0]
    parsed = json.loads(current_attachment['parse_result_json'])
    assert parsed['settlement_document']['retired'] and not parsed['cost_source_allowed']
    assert all(link in file_links(doc['file_url']) for link in old_links)
    assert runtime.calculation_blockers(batch['name'], retired_state['version'])
    acknowledge(binding, current_item['name'])
    assert not db.get('document_sync', state['id'])['blocking']
    assert not runtime.calculation_blockers(batch['name'], retired_state['version'])
    runtime.apply_source(retired_source['id'])
    assert len(ledger.rows('version', batch=batch['name'])) == 2
    assert not db.get('document_sync', state['id'])['blocking']
    db.commit()
    report('retired_packing_frozen_history_and_review_ack', ok=True, batch=batch['name'])

    corp, batch, version, item, binding = fixture('new-cargo')
    ledger.put('item', item['name'], {'material_code': 'OTHER'})
    doc = document('new-cargo', **{'装箱数量': '2'})
    source, state = sync(corp, batch, [doc])
    assert state['blocking'] and Decimal(str(ledger.get('item', item['name'])['gross_weight_kg'])) == 0
    apply_binding(db, ledger, binding['id'], 'local-document-test')
    current_items = ledger.rows('item', batch=batch['name'], version=version['name'])
    assert len(current_items) == 1 and current_items[0]['material_code'] == 'A'
    assert Decimal(str(current_items[0]['gross_weight_kg'])) == 8
    assert Decimal(str(current_items[0]['actual_shipped_qty'])) == 2
    assert Decimal(str(current_items[0].get('unit_price') or 0)) == 0, 'Packing price must not become purchase price'
    assert not db.get('document_sync', state['id'])['blocking']
    db.commit()
    report('final_goods_creation_replans_previously_unmatched_packing', ok=True, batch=batch['name'])

    corp, batch, version, item, binding = fixture('queue')
    ledger.put('batch', batch['name'], {'edit_lock_owner': 'local-test-editor', 'edit_lock_expires_at': '2099-01-01 00:00:00'})
    doc = document('queued', **{'装箱数量': '2'})
    source, state = sync(corp, batch, [doc])
    assert state['status'] == 'queued' and not ledger.rows('attachment', batch=batch['name'])
    assert Decimal(str(ledger.get('item', item['name'])['gross_weight_kg'])) == 0
    assert apply_binding(db, ledger, binding['id'], 'local-document-test')['application_status'] == 'queued'
    ledger.put('batch', batch['name'], {'edit_lock_owner': '', 'edit_lock_expires_at': None})

    class RunScopedStore(Store):
        """Constrain only job inventory and cursor state, leaving all target SQL real."""
        def find(self, table, **kwargs):
            if table == 'document_sync':
                kwargs['source_id'] = source['id']
            if table == 'binding':
                kwargs['id'] = binding['id']
            return super().find(table, **kwargs)

        def get(self, table, identity, lock=False):
            if table == 'state' and identity in {'document_cursor', 'application_cursor', 'control'}:
                identity = run + '-' + identity
            return super().get(table, identity, lock)

        def put(self, table, values):
            if table == 'state' and values['id'] in {'document_cursor', 'application_cursor', 'control'}:
                values = {**values, 'id': run + '-' + values['id']}
            return super().put(table, values)

    scoped_store = RunScopedStore(frappe.db)
    scoped_store.put('state', {'id': 'control', 'updated_at': '', 'data': dumps({'enabled': True})})
    with patch.object(runtime, 'enabled', return_value=True), patch.object(runtime, 'store', return_value=scoped_store):
        runtime.resume_pending()
    assert db.get('document_sync', state['id'])['status'] == 'applied'
    assert db.get('binding', binding['id'])['application_status'] == 'applied'
    assert len(ledger.rows('attachment', batch=batch['name'])) == 1
    assert Decimal(str(ledger.get('item', item['name'])['gross_weight_kg'])) == 8
    assert not runtime.calculation_blockers(batch['name'], version['name'])
    db.commit()
    report('locked_document_and_binding_resume_pending', ok=True, batch=batch['name'], inventory_scope='new fixture only')

    corp, batch, version, item, binding = fixture('microfee', amount='0.0000005', actual_shipped_qty=2, gross_weight_kg=1)
    result = apply_binding(db, ledger, binding['id'], 'local-document-test')
    assert result['application_status'] == 'applied', result
    actual = [r for r in ledger.rows('rule', batch=batch['name'], version=version['name']) if r['is_final']]
    assert len(actual) == 1 and Decimal(str(actual[0]['amount'])) == Decimal('0.000001')
    application = db.get('application', result['last_application'])
    planned = application['plan']['rules'][0]
    assert Decimal(planned['amount']) == Decimal(str(actual[0]['amount']))
    assert Decimal(planned['original_amount']) == Decimal('0.0000005')
    assert Decimal(planned['rounding_adjustment']) == Decimal('0.0000005')
    expense = db.get('source', binding['expense_id'])
    assert Decimal(expense['amount']) == Decimal('0.0000005')
    assert not runtime.calculation_blockers(batch['name'], version['name'])
    calculated = recalculate_batch(batch['name'])
    assert calculated['ok'] is True, calculated
    assert Decimal(str(ledger.get('item', item['name'])['freight_alloc_rmb'])) == Decimal('0.000001')
    db.commit()
    report('microfee_database_plan_precision_and_original_audit', ok=True, batch=batch['name'])

    corp, batch, version, item, binding = fixture('tailfee', actual_shipped_qty=2, gross_weight_kg=1)
    raw = raw_source(corp, 'expense', amount='0.999999999', hour='01')
    raw['raw_payload']['formComponentValues'].append({'name': '费用明细', 'componentType': 'TableField', 'value': [
        {'rowId': key, 'rowValue': [{'name': '费用名称', 'value': '运费'}, {'name': '金额', 'value': '0.333333333'}]}
        for key in ('a', 'b', 'c')]})
    source = ingest(raw)
    result = apply_binding(db, ledger, binding['id'], 'local-document-test')
    assert result['application_status'] == 'applied', result
    rules = [r for r in ledger.rows('rule', batch=batch['name'], version=version['name']) if r['is_final']]
    amounts = {r['rule_code']: Decimal(str(r['amount'])) for r in rules}
    assert len(amounts) == 3 and sum(amounts.values()) == Decimal(1), amounts
    assert not runtime.calculation_blockers(batch['name'], version['name'])
    raw['raw_payload']['formComponentValues'][-1]['value'].reverse()
    raw['updated_at'] = '2026-09-09T02:00:00+00:00'
    reordered = ingest(raw)
    apply_binding(db, ledger, binding['id'], 'local-document-test')
    again = [r for r in ledger.rows('rule', batch=batch['name'], version=version['name']) if r['is_final']]
    assert {r['rule_code']: Decimal(str(r['amount'])) for r in again} == amounts
    assert not runtime.calculation_blockers(batch['name'], version['name'])
    assert recalculate_batch(batch['name'])['ok'] is True
    db.commit()
    report('fee_detail_stable_tail_reordering_no_total_double_count', ok=True, batch=batch['name'])
    report('document_integration_complete', ok=True, run=run, site=SITE)
    frappe.destroy()


if __name__ == '__main__':
    main()
