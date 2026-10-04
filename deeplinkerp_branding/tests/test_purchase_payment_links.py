"""Optional link privacy and availability contracts, without a database."""
import unittest
from datetime import date, datetime
from io import BytesIO
from unittest.mock import patch
from types import SimpleNamespace

from openpyxl import load_workbook

import frappe
import frappe.permissions
from deeplinkerp_branding.services import purchase_payment_service as service


class PurchaseLinkTests(unittest.TestCase):
    def setUp(self):
        self.flags_patch = patch.object(frappe, 'flags', frappe._dict())
        self.flags_patch.start()
        self.addCleanup(self.flags_patch.stop)
        query = patch.object(service, '_query_fields', return_value=set(service.RECEIPT_FIELDS) | {'owner', 'creation', 'modified'})
        query.start()
        self.addCleanup(query.stop)
        normalize = patch.object(service, '_normalize_filter', side_effect=lambda dt, field, operator, value: [dt, field, operator, value])
        normalize.start()
        self.addCleanup(normalize.stop)

    def test_caught_framework_throw_does_not_queue_private_messages(self):
        frappe.local.message_log = []
        frappe.flags.mute_messages = False
        def private_error(*args):
            frappe.throw('private-target does not exist', frappe.DoesNotExistError)
        with patch.object(service, '_read', side_effect=private_error):
            warnings = []
            self.assertIsNone(service._related('Purchase Order', 'private-target', warnings))
        self.assertFalse(frappe.local.message_log)
        self.assertFalse(frappe.flags.mute_messages)
        self.assertEqual(warnings, [service.LINK_WARNING])

    def test_message_flag_is_restored_after_unexpected_error(self):
        frappe.flags.mute_messages = False
        with patch.object(service, '_read', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                service._related('Purchase Order', 'target', [])
        self.assertFalse(frappe.flags.mute_messages)

    def test_missing_and_denied_targets_have_the_same_public_result(self):
        for error in (frappe.DoesNotExistError, frappe.PermissionError):
            with self.subTest(error=error), patch.object(service, '_read', side_effect=error):
                warnings = []
                self.assertIsNone(service._related('Purchase Order', 'private-target', warnings))
                self.assertEqual(warnings, [service.LINK_WARNING])
                self.assertNotIn('private-target', str(warnings))

    def test_cross_company_and_supplier_links_are_not_returned(self):
        for doc in (frappe._dict(company='Other', supplier='S'), frappe._dict(company='C', supplier='Other')):
            with self.subTest(doc=doc), patch.object(service, '_read', return_value=doc):
                warnings = []
                self.assertIsNone(service._related('Purchase Order', 'private-target', warnings, company='C', supplier='S'))
                self.assertEqual(warnings, [service.LINK_WARNING])

    def test_available_link_retains_the_existing_document(self):
        doc = frappe._dict(company='C', supplier='S')
        with patch.object(service, '_read', return_value=doc):
            warnings = []
            self.assertIs(service._related('Purchase Order', 'valid', warnings, company='C', supplier='S'), doc)
            self.assertFalse(warnings)

    def test_programming_and_amount_errors_are_not_swallowed_as_missing_links(self):
        with patch.object(service, '_read', side_effect=ValueError('invalid amount')):
            with self.assertRaises(ValueError):
                service._related('Purchase Order', 'target', [])

    def test_mixed_links_keep_readable_targets_and_one_generic_warning(self):
        source = SimpleNamespace(company='C', supplier='S', items=[
            frappe._dict(purchase_order=n) for n in ('valid', 'missing', 'denied', 'valid')])
        def read(doctype, name, fields):
            if name == 'missing':
                raise frappe.DoesNotExistError
            if name == 'denied':
                raise frappe.PermissionError
            return frappe._dict(company='C', supplier='S')
        with patch.object(service, '_read', side_effect=read):
            warnings = []
            self.assertEqual(service._source_links(source, 'Purchase Order', 'purchase_order', warnings), ['valid'])
            self.assertEqual(warnings, [service.LINK_WARNING])

    def test_unreadable_receipt_row_does_not_break_other_rows_or_show_balance(self):
        rows = [frappe._dict(name=name, company='C', currency='CNY', grand_total=10) for name in ('unreadable', 'visible')]
        def chain(doctype, name, include_payments):
            if name == 'unreadable':
                raise frappe.PermissionError
            return {'orders': [], 'balances': [{'outstanding': 10, 'settled': 2}],
                    'can_create': True, 'can_create_invoice': False, 'draft_invoices': [], 'draft_orders': [], 'reason': '', 'warnings': [], 'incomplete_links': False, 'invoices': []}
        with patch.object(service, '_require_fields'), patch.object(service._RecordReader, 'preload'), patch.object(service, '_read'), patch.object(frappe, 'get_list', return_value=rows), patch.object(service, 'get_purchase_chain', side_effect=chain):
            result = service.get_receipt_list(page_length=2)
        self.assertEqual(result['total_count'], 2)
        self.assertFalse(result['rows'][0]['can_create'])
        self.assertEqual(result['rows'][0]['balances'], [])
        self.assertTrue(result['rows'][1]['can_create'])

    def test_denied_receipt_source_is_excluded_from_count_totals_and_rows(self):
        rows = [frappe._dict(name='private', company='C', currency='CNY', grand_total=100)]
        with patch.object(service, '_require_fields'), patch.object(service._RecordReader, 'preload'), patch.object(service, '_read', side_effect=frappe.PermissionError), patch.object(frappe, 'get_list', return_value=rows):
            result = service.get_receipt_list()
        self.assertEqual(result, {'rows': [], 'total_count': 0, 'totals': []})


class PaymentRecordReaderTests(unittest.TestCase):
    def setUp(self):
        flags = patch.object(frappe, 'flags', frappe._dict())
        flags.start()
        self.addCleanup(flags.stop)
        query = patch.object(service, '_query_fields', return_value={'name', 'party', 'party_type', 'payment_type', 'posting_date', 'creation', 'modified'})
        query.start()
        self.addCleanup(query.stop)
        normalize = patch.object(service, '_normalize_filter', side_effect=lambda dt, field, operator, value: [dt, field, operator, value])
        normalize.start()
        self.addCleanup(normalize.stop)

    def test_bulk_hydration_preserves_children_and_masks_parent(self):
        reader = service._RecordReader()
        rows = [frappe._dict(name='PE-1', company='C')]
        children = [frappe._dict(name='REF-1', parent='PE-1', idx=1)]
        doc = SimpleNamespace(mask_fields=unittest.mock.Mock())
        meta = SimpleNamespace(get_table_fields=lambda: [frappe._dict(fieldname='references', options='Payment Entry Reference')])
        values = unittest.mock.Mock(side_effect=[rows, children])
        with patch.object(frappe, 'db', SimpleNamespace(get_values=values)), patch.object(frappe, 'get_meta', return_value=meta), patch.object(frappe, 'get_doc', return_value=doc) as get_doc:
            reader.preload('Payment Entry', ['PE-1', 'missing', 'PE-1'])
            reader.preload('Payment Entry', ['PE-1', 'missing'])
        self.assertEqual(values.call_count, 2)
        self.assertEqual(values.call_args_list[1].args[1], {'parent': ['in', ['PE-1']], 'parenttype': 'Payment Entry', 'parentfield': 'references'})
        self.assertEqual(get_doc.call_args.args[0]['references'], children)
        doc.mask_fields.assert_called_once()
        self.assertIs(reader.doc('Payment Entry', 'PE-1'), doc)
        with self.assertRaises(frappe.DoesNotExistError):
            reader.doc('Payment Entry', 'missing')

    def test_denied_permission_is_never_cached_as_success(self):
        reader = service._RecordReader()
        doc = SimpleNamespace(doctype='Payment Entry', name='PE-1', check_permission=unittest.mock.Mock(side_effect=frappe.PermissionError))
        for _ in range(2):
            with self.assertRaises(frappe.PermissionError): reader.check(doc)
        self.assertEqual(doc.check_permission.call_count, 2)
        self.assertFalse(reader.checked)

    def test_context_is_restored_after_unexpected_error(self):
        outer = service._RecordReader()
        token = service._record_reader.set(outer)
        try:
            with patch.object(service, '_payment_records', side_effect=RuntimeError):
                with self.assertRaises(RuntimeError): service.get_payment_records()
            self.assertIs(service._record_reader.get(), outer)
        finally:
            service._record_reader.reset(token)

    def test_empty_page_does_not_read_vouchers(self):
        with patch.object(service, '_require_fields'), patch.object(frappe, 'get_list', return_value=[]), patch.object(service, '_vouchers') as vouchers:
            result = service.get_payment_records(search='no match')
        self.assertEqual(result['total_count'], 0)
        self.assertEqual(result['rows'], [])
        vouchers.assert_not_called()


class ProcurementExportTests(unittest.TestCase):
    """Read native XLSX files; isolate document access and the site-only default format."""

    def export(self, doctype, rows, columns=None, can_export=True, check_read=None,
               generic_export=True, owner_export=False, owner='buyer@example.test'):
        response = {}
        doc = SimpleNamespace(check_permission=check_read or (lambda permission: None),
                              get=lambda field: owner if field == 'owner' else None)
        allowed = service.RECEIPT_COLUMNS if doctype == 'Purchase Receipt' else service.PAYMENT_COLUMNS
        from frappe.utils.xlsxutils import XLSXStyleBuilder
        capability = lambda doctype, is_owner=False: owner_export if is_owner else can_export
        def throw_without_site(message, exception):
            raise exception(message)
        with patch.object(frappe, 'response', response), patch.object(frappe, 'has_permission', return_value=generic_export), patch.object(frappe.permissions, 'can_export', side_effect=capability), patch.object(frappe, 'session', SimpleNamespace(user='buyer@example.test')), patch.object(frappe, 'throw', side_effect=throw_without_site), patch.object(service, '_read_doc', return_value=doc), patch.object(XLSXStyleBuilder, 'get_datetime_format', return_value='yyyy-mm-dd hh:mm:ss'):
            service._export(doctype, rows, columns, allowed)
        return load_workbook(BytesIO(response['filecontent']))

    def test_native_capability_allows_export_when_generic_and_document_export_are_false(self):
        def readable(permission):
            if permission == 'export':
                raise frappe.PermissionError
        for doctype in ('Purchase Receipt', 'Payment Entry'):
            with self.subTest(doctype=doctype):
                workbook = self.export(doctype, [{'name': 'DOC-1', 'references': []}], ['name'],
                                       generic_export=False, check_read=readable)
                self.assertEqual(workbook.active.cell(2, 1).value, 'DOC-1')

    def test_owner_only_export_allows_exact_user_and_rejects_other_or_missing_owners(self):
        for doctype in ('Purchase Receipt', 'Payment Entry'):
            for owner in ('buyer@example.test', 'other@example.test', None):
                with self.subTest(doctype=doctype, owner=owner):
                    def export():
                        return self.export(doctype, [{'name': 'DOC-1', 'references': []}], ['name'],
                                           can_export=False, owner_export=True, owner=owner)
                    if owner == 'buyer@example.test':
                        self.assertEqual(export().active.cell(2, 1).value, 'DOC-1')
                    else:
                        with self.assertRaises(frappe.PermissionError):
                            export()

    def test_selected_amount_columns_keep_order_and_append_distinct_currencies(self):
        cases = (
            ('Purchase Receipt', 'grand_total', ['入库日期', '入库金额', '采购入库单号', '入库币种'], ['USD']),
            ('Payment Entry', 'amount', ['付款日期', '金额', '付款单', '付款币种', '核销币种'], ['USD', 'CNY']),
        )
        for doctype, amount_field, headers, currencies in cases:
            with self.subTest(doctype=doctype):
                row = {'name': 'DOC-1', 'posting_date': '2026-10-04', amount_field: 4000.123456,
                       'currency': 'USD', 'references': [{'currency': 'CNY'}]}
                selected = ['posting_date', amount_field, 'name']
                workbook = self.export(doctype, [row], selected)
                self.assertEqual([cell.value for cell in workbook.active[1]], headers)
                self.assertEqual([cell.value for cell in workbook.active[2]][3:], currencies)
                self.assertEqual(selected, ['posting_date', amount_field, 'name'])
                self.assertEqual(workbook.active.cell(2, 2).value, 4000.123456)
                self.assertEqual(workbook.active.cell(2, 2).number_format, '#,##0.00')

    def test_dates_are_typed_and_formatted_without_filling_missing_dates(self):
        for doctype in ('Purchase Receipt', 'Payment Entry'):
            for source_date in (date(2026, 10, 4), datetime(2026, 10, 4, 12, 30), '2026-10-04', None):
                with self.subTest(doctype=doctype, source_date=source_date):
                    row = {'name': 'DOC-1', 'posting_date': source_date, 'references': []}
                    workbook = self.export(doctype, [row], ['name', 'posting_date'])
                    cell = workbook.active.cell(2, 2)
                    self.assertEqual(cell.value, datetime(2026, 10, 4) if source_date else None)
                    if source_date:
                        self.assertEqual(cell.number_format, 'yyyy-mm-dd')
                        self.assertTrue(cell.is_date)
                    else:
                        # Native XLSXWriter omits empty cells; Excel inherits the column format.
                        self.assertEqual(workbook.active.column_dimensions['B'].number_format, 'yyyy-mm-dd')

    def test_default_and_explicit_currency_columns_are_not_duplicated(self):
        expected_receipt_labels = {
            'name': '采购入库单号', 'supplier_name': '供应商名称', 'supplier': '供应商编码',
            'posting_date': '入库日期', 'status': '入库状态', 'company': '公司',
            'currency': '入库币种', 'grand_total': '入库金额', 'docstatus': '单据状态', 'is_return': '是否退货',
        }
        for doctype, amount_field in (('Purchase Receipt', 'grand_total'), ('Payment Entry', 'amount')):
            allowed = service.RECEIPT_COLUMNS if doctype == 'Purchase Receipt' else service.PAYMENT_COLUMNS
            row = {'name': 'DOC-1', amount_field: 0, 'currency': 'CNY', 'references': []}
            for selected in (None, ['currency', amount_field, 'name']):
                with self.subTest(doctype=doctype, selected=selected):
                    workbook = self.export(doctype, [row], selected)
                    labels = [cell.value for cell in workbook.active[1]]
                    self.assertEqual(labels.count(allowed['currency']), 1)
                    if selected:
                        self.assertEqual(labels[:3], [allowed[column] for column in selected])
                    elif doctype == 'Purchase Receipt':
                        self.assertEqual(labels[:len(service.RECEIPT_FIELDS)],
                                         [expected_receipt_labels[column] for column in service.RECEIPT_FIELDS])
                    if doctype == 'Payment Entry':
                        self.assertEqual(labels.count('核销币种'), 1)

    def test_export_permissions_and_formula_protection_remain_native(self):
        for prefix in ('=', '+', '-', '@'):
            with self.subTest(prefix=prefix):
                row = {'name': 'DOC-1', 'supplier_name': '<span>' + prefix + 'unsafe</span>'}
                workbook = self.export('Purchase Receipt', [row], ['supplier_name'])
                cell = workbook.active.cell(2, 1)
                self.assertEqual(cell.value, "'" + prefix + 'unsafe')
                self.assertEqual(cell.data_type, 's')
        # Pure CI has no site-bound message flags; the native QA script tests real throws.
        def throw_without_site(message, exception):
            raise exception(message)
        with patch.object(frappe, 'throw', side_effect=throw_without_site), self.assertRaises(frappe.PermissionError):
            self.export('Purchase Receipt', [], ['name'], can_export=False)

    def test_each_exported_document_still_requires_read_permission(self):
        checked = []
        def denied(permission):
            checked.append(permission)
            if permission == 'read':
                raise frappe.PermissionError
        for doctype in ('Purchase Receipt', 'Payment Entry'):
            with self.subTest(doctype=doctype), self.assertRaises(frappe.PermissionError):
                self.export(doctype, [{'name': 'PRIVATE', 'references': []}], ['name'], check_read=denied)
        self.assertEqual(checked, ['read', 'read'])


if __name__ == '__main__':
    unittest.main()
