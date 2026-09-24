from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from china_finance.services import purchase_payables


class DocumentStub(SimpleNamespace):
	def get(self, fieldname, default=None):
		return getattr(self, fieldname, default)


class TestPurchasePayables(TestCase):
	def receipt(self, **values):
		defaults = dict(
			doctype="Purchase Receipt",
			docstatus=1,
			is_return=0,
			company="Test Company",
			supplier="Test Supplier",
			name="PR-0001",
			check_permission=Mock(),
		)
		defaults.update(values)
		return SimpleNamespace(**defaults)

	def invoice(self, **values):
		defaults = dict(
			doctype="Purchase Invoice",
			company="Test Company",
			supplier="Test Supplier",
			is_return=0,
			items=[],
		)
		defaults.update(values)
		return DocumentStub(**defaults)

	def test_unlinked_service_invoice_is_not_blocked(self):
		doc = self.invoice(items=[DocumentStub(purchase_order="", purchase_receipt="")])
		purchase_payables.validate_purchase_invoice_submission(doc)

	def test_unsubmitted_purchase_order_is_rejected(self):
		doc = self.invoice(items=[DocumentStub(purchase_order="PO-0001", purchase_receipt="")])
		with patch.object(
			frappe.db,
			"get_value",
			return_value=frappe._dict({"docstatus": 0, "company": "Test Company", "supplier": "Test Supplier"}),
		):
			with self.assertRaises(frappe.ValidationError):
				purchase_payables.validate_purchase_invoice_submission(doc)

	def test_receipt_line_requires_submitted_receipt_and_matching_quantity(self):
		row = DocumentStub(
			idx=1,
			purchase_order="PO-0001",
			purchase_receipt="PR-0001",
			pr_detail="PRI-0001",
			qty=11,
		)
		doc = self.invoice(items=[row])
		values = [
			frappe._dict({"docstatus": 1, "company": "Test Company", "supplier": "Test Supplier"}),
			frappe._dict({"docstatus": 1, "company": "Test Company", "supplier": "Test Supplier", "is_return": 0}),
			frappe._dict({"parent": "PR-0001", "qty": 10, "item_code": "ITEM-001", "purchase_order": "PO-0001", "purchase_order_item": "POI-0001"}),
		]
		with patch.object(frappe.db, "get_value", side_effect=values):
			with self.assertRaises(frappe.ValidationError):
				purchase_payables.validate_purchase_invoice_submission(doc)

	def test_return_receipt_cannot_create_payable(self):
		receipt = self.receipt(is_return=1)
		with patch.object(purchase_payables.frappe, "get_doc", return_value=receipt):
			with self.assertRaises(frappe.ValidationError):
				purchase_payables.create_purchase_invoice_from_receipt("PR-0001")

	def test_existing_draft_is_reused(self):
		receipt = self.receipt()
		with patch.object(purchase_payables.frappe, "get_doc", return_value=receipt), patch.object(
			purchase_payables, "_source_rows", return_value=[SimpleNamespace(parent="PINV-0001", docstatus=0)]
		), patch("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice") as mapper:
			result = purchase_payables.create_purchase_invoice_from_receipt("PR-0001")
		self.assertEqual(result, {"name": "PINV-0001", "created": False, "docstatus": 0})
		mapper.assert_not_called()

	def test_new_payable_uses_native_mapping_and_stays_draft(self):
		receipt = self.receipt()
		invoice = Mock()
		invoice.get.side_effect = lambda field: [{"item_code": "ITEM-001"}] if field == "items" else None
		invoice.name = "PINV-0001"
		invoice.docstatus = 0
		with patch.object(purchase_payables.frappe, "get_doc", return_value=receipt), patch.object(
			purchase_payables, "_source_rows", return_value=[]
		), patch(
			"erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
			return_value=invoice,
		) as mapper:
			result = purchase_payables.create_purchase_invoice_from_receipt("PR-0001")
		self.assertEqual(result, {"name": "PINV-0001", "created": True, "docstatus": 0})
		invoice.check_permission.assert_called_once_with("create")
		invoice.insert.assert_called_once_with()
		mapper.assert_called_once_with("PR-0001", args={"merge_taxes": False})
