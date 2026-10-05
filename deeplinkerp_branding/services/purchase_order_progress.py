"""Source-authorized order progress, never financial documents or bank/account data.

Private linked accounting reads are used only for this fixed summary projection.
The PO, company and PO fields must pass the caller's native read permissions first.
Financial document APIs and writes keep their own native permissions.
"""

import json
from decimal import Decimal

import frappe
from frappe.model import get_permitted_fields

from deeplinkerp_branding.services.purchase_payment_service import (
	_read,
	_record_reader,
	_RecordReader,
	amount,
	invoice_balance,
)

ITEM_FIELDS = {"idx", "item_code", "item_name", "description", "qty", "uom", "rate", "amount", "received_qty"}
NOTICE = "仅显示有权查看的订单进度；不包含银行账户、应付单或付款单明细。订单未付不是已到货应付余额。"
UNCERTAIN = "共享应付、退货或跨币种无法安全归入本订单，请由财务核对；不将整单金额冒充采购成本。"


def settlement(order, invoices, receipt_orders, advances):
	"""Reuse native maintained PI balance and current PO-reference advances.

	Reconciled advances move from PO to PI references and are counted once.
	Shared or mixed invoices deliberately have no invented per-order allocation.
	"""
	settled = sum((amount(row["amount"]) for row in advances), Decimal(0))
	exact = all(row["currency"] == order.currency for row in advances)
	for invoice in invoices:
		if invoice.docstatus != 1:
			continue
		sources = set()
		for item in invoice.items:
			sources.update(
				{item.purchase_order}
				if item.purchase_order
				else receipt_orders.get(item.purchase_receipt, {None})
			)
		if order.name not in sources:
			continue
		if (
			sources != {order.name}
			or invoice.company != order.company
			or invoice.supplier != order.supplier
			or invoice.is_return
			or (invoice.party_account_currency or invoice.currency) != order.currency
		):
			exact = False
			continue
		balance = invoice_balance(invoice)
		settled += amount(balance["settled"])
	return {
		"settled": float(settled) if exact else None,
		"order_unpaid": float(amount(order.grand_total) - settled) if exact else None,
		"settlement_exact": exact,
		"settlement_notice": "" if exact else UNCERTAIN,
	}


@frappe.whitelist()
def get_order_progress(purchase_orders, include_items=False):
	names = json.loads(purchase_orders) if isinstance(purchase_orders, str) else purchase_orders
	if (
		not isinstance(names, list)
		or not 1 <= len(names) <= 100
		or any(not isinstance(n, str) for n in names)
	):
		frappe.throw("每次仅支持 1 至 100 张采购订单")
	names = list(dict.fromkeys(names))
	reader = _RecordReader()
	token = _record_reader.set(reader)
	try:
		reader.preload("Purchase Order", names)
		orders = {}
		for name in names:
			# Requested unauthorized documents fail the whole call; no hidden names/totals.
			doc = _read(
				"Purchase Order",
				name,
				{"company", "supplier", "currency", "grand_total", "items", "per_received"},
			)
			orders[name] = doc
		receipt_items = frappe.get_all(
			"Purchase Receipt Item",
			filters={"purchase_order": ["in", names]},
			fields=["parent", "purchase_order"],
			limit_page_length=0,
		)
		receipt_names = list({row.parent for row in receipt_items})
		all_receipt_items = (
			frappe.get_all(
				"Purchase Receipt Item",
				filters={"parent": ["in", receipt_names]},
				fields=["parent", "purchase_order"],
				limit_page_length=0,
			)
			if receipt_names
			else []
		)
		receipt_orders = {}
		for row in all_receipt_items:
			receipt_orders.setdefault(row.parent, set()).add(row.purchase_order or None)
		invoice_items = frappe.get_all(
			"Purchase Invoice Item",
			or_filters=[["purchase_order", "in", names], ["purchase_receipt", "in", receipt_names]],
			fields=["parent", "purchase_order", "purchase_receipt"],
			limit_page_length=0,
		)
		reader.preload("Purchase Invoice", {row.parent for row in invoice_items})
		# Only current PO references: an advance already reconciled into PI is not added twice.
		references = frappe.get_all(
			"Payment Entry Reference",
			filters={"reference_doctype": "Purchase Order", "reference_name": ["in", names]},
			fields=["parent", "reference_name", "allocated_amount"],
			limit_page_length=0,
		)
		reader.preload("Payment Entry", {row.parent for row in references})
		item_fields = ITEM_FIELDS & set(
			get_permitted_fields("Purchase Order Item", parenttype="Purchase Order", permission_type="read")
		)
		result = {}
		for name, doc in orders.items():
			invoices = [
				invoice for (dt, _), invoice in reader.docs.items() if dt == "Purchase Invoice" and invoice
			]
			advances = []
			for ref in references:
				pe = reader.docs.get(("Payment Entry", ref.parent))
				if (
					ref.reference_name == name
					and pe
					and pe.docstatus == 1
					and pe.payment_type == "Pay"
					and pe.party_type == "Supplier"
					and pe.company == doc.company
					and pe.party == doc.supplier
				):
					advances.append({"amount": ref.allocated_amount, "currency": pe.paid_to_account_currency})
			row = {
				"name": name,
				"modified": str(doc.modified),
				"currency": doc.currency,
				"grand_total": doc.grand_total,
				"received_percent": doc.per_received,
				"docstatus": doc.docstatus,
				**settlement(doc, invoices, receipt_orders, advances),
				"notice": NOTICE,
			}
			if any(
				not reader.docs.get(("Purchase Invoice", item.parent))
				and name
				in (
					{item.purchase_order}
					if item.purchase_order
					else receipt_orders.get(item.purchase_receipt, set())
				)
				for item in invoice_items
			):
				row.update(
					settled=None, order_unpaid=None, settlement_exact=False, settlement_notice=UNCERTAIN
				)
			if doc.docstatus != 1:
				row.update(settled=None, order_unpaid=None, settlement_exact=False)
			if include_items in (True, 1, "1", "true"):
				row["item_fields"] = sorted(item_fields)
				row["items"] = [{field: item.get(field) for field in item_fields} for item in doc.items]
			result[name] = row
		return result
	finally:
		_record_reader.reset(token)
