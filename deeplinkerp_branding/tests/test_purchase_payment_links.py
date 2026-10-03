"""Optional link privacy and availability contracts, without a database."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import frappe
from deeplinkerp_branding.services import purchase_payment_service as service


class PurchaseLinkTests(unittest.TestCase):
    def setUp(self):
        self.flags_patch = patch.object(frappe, 'flags', frappe._dict())
        self.flags_patch.start()
        self.addCleanup(self.flags_patch.stop)

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
        rows = [frappe._dict(name='unreadable'), frappe._dict(name='visible')]
        def chain(doctype, name, include_payments):
            if name == 'unreadable':
                raise frappe.PermissionError
            return {'orders': [], 'balances': [{'outstanding': 10, 'settled': 2}],
                    'can_create': True, 'reason': '', 'warnings': [], 'incomplete_links': False, 'invoices': []}
        with patch.object(service, '_require_fields'), patch.object(frappe, 'get_list', return_value=rows), patch.object(service, 'get_purchase_chain', side_effect=chain):
            result = service.get_receipt_list(page_length=2)
        self.assertEqual(result['total_count'], 2)
        self.assertFalse(result['rows'][0]['can_create'])
        self.assertEqual(result['rows'][0]['balances'], [])
        self.assertTrue(result['rows'][1]['can_create'])


if __name__ == '__main__':
    unittest.main()
