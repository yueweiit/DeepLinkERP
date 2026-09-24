"""Purchase receipt to payable and three-way matching controls."""

import frappe
from frappe import _
from frappe.utils import flt


PAYMENT_STATUS_UNPAID = "未付款"
PAYMENT_STATUS_PARTIAL = "部分付款"
PAYMENT_STATUS_PAID = "全部付款"
PAYMENT_STATUS_NOT_APPLICABLE = "不适用"
PAYMENT_STATUS_CANCELLED = "已取消"
PAYMENT_STATUS_EXCEPTION = "异常"
DEFAULT_AMOUNT_TOLERANCE = 0.01


def get_purchase_payment_status(
	total_amount,
	paid_amount,
	outstanding_amount,
	docstatus=1,
	is_return=0,
	tolerance=DEFAULT_AMOUNT_TOLERANCE,
):
	"""Return a purchase payable payment status from current ledger amounts."""
	if docstatus == 2:
		return PAYMENT_STATUS_CANCELLED
	if is_return:
		return PAYMENT_STATUS_EXCEPTION

	total = flt(total_amount)
	paid = flt(paid_amount)
	outstanding = flt(outstanding_amount)
	if total < -tolerance or paid < -tolerance or outstanding < -tolerance:
		return PAYMENT_STATUS_EXCEPTION
	if total <= tolerance:
		return PAYMENT_STATUS_NOT_APPLICABLE
	if paid - total > tolerance or outstanding - total > tolerance:
		return PAYMENT_STATUS_EXCEPTION
	if outstanding <= tolerance:
		return PAYMENT_STATUS_PAID
	if paid > tolerance:
		return PAYMENT_STATUS_PARTIAL
	return PAYMENT_STATUS_UNPAID


def _source_rows(receipt_name):
	return frappe.get_all(
		"Purchase Invoice Item",
		filters={"purchase_receipt": receipt_name, "docstatus": ["!=", 2]},
		fields=["parent", "docstatus"],
		order_by="creation asc",
		limit_page_length=0,
	)


def get_purchase_invoices_for_receipt(receipt_name, outstanding_only=False):
	"""Return purchase invoices linked to a submitted purchase receipt."""
	receipt = frappe.get_doc("Purchase Receipt", receipt_name)
	receipt.check_permission("read")
	filters = {"name": ["in", list(dict.fromkeys(row.parent for row in _source_rows(receipt_name)))]}
	if outstanding_only:
		filters.update({"docstatus": 1, "outstanding_amount": [">", DEFAULT_AMOUNT_TOLERANCE]})
	return frappe.get_all(
		"Purchase Invoice",
		filters=filters,
		fields=[
			"name",
			"supplier",
			"company",
			"currency",
			"posting_date",
			"due_date",
			"grand_total",
			"outstanding_amount",
			"is_return",
			"docstatus",
		],
		order_by="posting_date asc, name asc",
		limit_page_length=0,
	)


def get_receipt_payment_summary(receipt_name):
	"""Summarize payable and payment state without storing stale receipt totals."""
	receipt = frappe.get_doc("Purchase Receipt", receipt_name)
	receipt.check_permission("read")
	invoices = get_purchase_invoices_for_receipt(receipt_name)
	valid = [invoice for invoice in invoices if invoice.docstatus == 1 and not flt(invoice.get("is_return"))]
	amount = sum(flt(invoice.grand_total) for invoice in valid)
	outstanding = sum(flt(invoice.outstanding_amount) for invoice in valid)
	if not valid:
		if not invoices:
			status = PAYMENT_STATUS_NOT_APPLICABLE
		elif all(invoice.docstatus == 2 for invoice in invoices):
			status = PAYMENT_STATUS_CANCELLED
		elif any(flt(invoice.get("is_return")) for invoice in invoices):
			status = PAYMENT_STATUS_EXCEPTION
		else:
			status = PAYMENT_STATUS_UNPAID
	else:
		status = get_purchase_payment_status(amount, amount - outstanding, outstanding)
	return {
		"purchase_receipt": receipt_name,
		"company": receipt.company,
		"supplier": receipt.supplier,
		"purchase_invoices": [invoice.name for invoice in invoices],
		"payable_purchase_invoices": [invoice.name for invoice in valid if invoice.outstanding_amount > DEFAULT_AMOUNT_TOLERANCE],
		"invoice_amount": amount,
		"outstanding_amount": outstanding,
		"payment_status": status,
	}


def _validate_purchase_order_link(invoice, row):
	if not row.purchase_order:
		return
	order = frappe.db.get_value(
		"Purchase Order",
		row.purchase_order,
		["docstatus", "company", "supplier"],
		as_dict=True,
	)
	if not order:
		frappe.throw(_("采购订单 {0} 不存在").format(row.purchase_order))
	if order.docstatus != 1:
		frappe.throw(_("采购订单 {0} 尚未审核，不能确认采购应付").format(row.purchase_order))
	if order.company != invoice.company or order.supplier != invoice.supplier:
		frappe.throw(_("采购订单 {0} 与采购应付单的公司或供应商不一致").format(row.purchase_order))


def _validate_purchase_receipt_link(invoice, row):
	if not row.purchase_receipt:
		return
	receipt = frappe.db.get_value(
		"Purchase Receipt",
		row.purchase_receipt,
		["docstatus", "company", "supplier", "is_return"],
		as_dict=True,
	)
	if not receipt:
		frappe.throw(_("采购收货单 {0} 不存在").format(row.purchase_receipt))
	if receipt.docstatus != 1:
		frappe.throw(_("采购收货单 {0} 尚未提交，不能确认采购应付").format(row.purchase_receipt))
	if receipt.is_return:
		frappe.throw(_("采购退货单 {0} 不能作为正常采购应付来源").format(row.purchase_receipt))
	if receipt.company != invoice.company or receipt.supplier != invoice.supplier:
		frappe.throw(_("采购收货单 {0} 与采购应付单的公司或供应商不一致").format(row.purchase_receipt))
	if not row.pr_detail:
		frappe.throw(_("采购应付明细 {0} 缺少采购收货明细关联").format(row.idx))

	pr_item = frappe.db.get_value(
		"Purchase Receipt Item",
		row.pr_detail,
		["parent", "qty", "item_code", "purchase_order", "purchase_order_item"],
		as_dict=True,
	)
	if not pr_item or pr_item.parent != row.purchase_receipt:
		frappe.throw(_("采购应付明细 {0} 的收货明细关联无效").format(row.idx))
	if flt(row.qty) - flt(pr_item.qty) > DEFAULT_AMOUNT_TOLERANCE:
		frappe.throw(_("采购应付明细 {0} 数量超过采购收货数量").format(row.idx))


def validate_purchase_invoice_submission(doc, method=None):
	"""Validate source links before a purchase invoice is submitted.

	Invoices without purchase-order/receipt links remain valid for service and
	direct expense purchases. Once a line claims a receipt source, every source
	link is checked so the normal inventory purchasing flow is three-way matched.
	"""
	if doc.doctype != "Purchase Invoice" or doc.get("is_return"):
		return
	if not any(row.get("purchase_order") or row.get("purchase_receipt") for row in doc.items):
		return
	for row in doc.items:
		_validate_purchase_order_link(doc, row)
		_validate_purchase_receipt_link(doc, row)


def _validate_payment_reference(payment_entry, reference, invoice):
	if not invoice:
		frappe.throw(_("采购应付单 {0} 不存在").format(reference.reference_name))
	if invoice.docstatus != 1:
		frappe.throw(_("采购应付单 {0} 尚未提交，不能付款").format(reference.reference_name))
	if invoice.company != payment_entry.company or invoice.supplier != payment_entry.party:
		frappe.throw(_("采购应付单 {0} 与付款单的公司或供应商不一致").format(reference.reference_name))
	if flt(reference.allocated_amount) <= 0:
		frappe.throw(_("采购应付单 {0} 的核销金额必须大于零").format(reference.reference_name))
	payment_currency = payment_entry.get("paid_to_account_currency")
	invoice_currency = invoice.get("party_account_currency") or invoice.get("currency")
	if payment_currency and invoice_currency and payment_currency != invoice_currency:
		frappe.throw(
			_("采购应付单 {0} 的币种 {1} 与付款单往来币种 {2} 不一致").format(
				reference.reference_name, invoice_currency, payment_currency
			)
		)
	if flt(reference.allocated_amount) - flt(invoice.outstanding_amount) > DEFAULT_AMOUNT_TOLERANCE:
		frappe.throw(_("采购应付单 {0} 的核销金额超过未付金额").format(reference.reference_name))
	if flt(invoice.is_return):
		frappe.throw(_("采购红字应付单 {0} 不能作为正常付款来源").format(reference.reference_name))


def validate_payment_entry(doc, method=None):
	"""Keep supplier payments anchored to submitted purchase payables."""
	if doc.doctype != "Payment Entry" or doc.get("payment_type") != "Pay":
		return
	seen_references = set()
	settlement_currencies = set()
	for reference in doc.get("references") or []:
		if reference.reference_doctype == "Purchase Receipt":
			frappe.throw(_("付款单不能直接核销采购收货单，请先确认采购应付单"))
		if reference.reference_doctype != "Purchase Invoice":
			continue
		key = (reference.reference_doctype, reference.reference_name)
		if key in seen_references:
			frappe.throw(_("付款单重复核销采购应付单 {0}").format(reference.reference_name))
		seen_references.add(key)
		if doc.get("party_type") != "Supplier" or not doc.get("party"):
			frappe.throw(_("采购付款必须指定供应商"))
		invoice = frappe.db.get_value(
			"Purchase Invoice",
			reference.reference_name,
			[
				"docstatus",
				"company",
				"supplier",
				"currency",
				"party_account_currency",
				"outstanding_amount",
				"is_return",
			],
			as_dict=True,
		)
		if invoice:
			currency = invoice.get("party_account_currency") or invoice.get("currency")
			if currency:
				settlement_currencies.add(currency)
		_validate_payment_reference(doc, reference, invoice)
	if len(settlement_currencies) > 1:
		frappe.throw(_("同一付款单不能核销不同往来币种的采购应付单"))


@frappe.whitelist(methods=["POST"])
def create_purchase_invoice_from_receipt(purchase_receipt, merge_taxes=False):
	"""Create an idempotent purchase invoice draft from a submitted receipt."""
	receipt = frappe.get_doc("Purchase Receipt", purchase_receipt)
	receipt.check_permission("read")
	if receipt.docstatus != 1:
		frappe.throw(_("只有已提交的采购收货单才能创建采购应付单"))
	if receipt.is_return:
		frappe.throw(_("采购退货单不能创建正常采购应付单"))

	existing = _source_rows(purchase_receipt)
	for row in existing:
		if row.docstatus == 1:
			return {"name": row.parent, "created": False, "docstatus": 1}
		if row.docstatus == 0:
			return {"name": row.parent, "created": False, "docstatus": 0}

	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	invoice = make_purchase_invoice(
		purchase_receipt,
		args={"merge_taxes": bool(merge_taxes)},
	)
	if not invoice or not invoice.get("items"):
		frappe.throw(_("采购收货单没有可确认的未开票明细"))
	invoice.check_permission("create")
	invoice.insert()
	return {"name": invoice.name, "created": True, "docstatus": invoice.docstatus}


@frappe.whitelist()
def get_receipt_payment_summary_for_user(purchase_receipt):
	return get_receipt_payment_summary(purchase_receipt)


@frappe.whitelist()
def get_purchase_payment_candidates(company, supplier=None, txt=None, limit=100):
	"""List payable invoices with their order and receipt links for payment selection."""
	if not company:
		frappe.throw(_("选择采购应付单时必须先指定公司"))
	try:
		limit = min(max(int(limit), 1), 200)
	except (TypeError, ValueError):
		limit = 100

	filters = {
		"company": company,
		"docstatus": 1,
		"outstanding_amount": [">", DEFAULT_AMOUNT_TOLERANCE],
		"is_return": 0,
	}
	if supplier:
		filters["supplier"] = supplier
	if txt:
		filters["name"] = ["like", f"%{txt.strip()}%"]

	invoices = frappe.get_list(
		"Purchase Invoice",
		filters=filters,
		fields=[
			"name",
			"supplier",
			"posting_date",
			"due_date",
			"currency",
			"grand_total",
			"outstanding_amount",
		],
		order_by="due_date asc, posting_date asc, name asc",
		limit_page_length=limit,
	)
	if not invoices:
		return []

	names = [invoice.name for invoice in invoices]
	items = frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ["in", names]},
		fields=["parent", "purchase_order", "purchase_receipt"],
		limit_page_length=0,
	)
	links = {name: {"purchase_orders": [], "purchase_receipts": []} for name in names}
	for item in items:
		link = links[item.parent]
		if item.purchase_order and item.purchase_order not in link["purchase_orders"]:
			link["purchase_orders"].append(item.purchase_order)
		if item.purchase_receipt and item.purchase_receipt not in link["purchase_receipts"]:
			link["purchase_receipts"].append(item.purchase_receipt)

	return [
		{
			**invoice,
			"purchase_orders": ", ".join(links[invoice.name]["purchase_orders"]),
			"purchase_receipts": ", ".join(links[invoice.name]["purchase_receipts"]),
		}
		for invoice in invoices
	]


@frappe.whitelist()
def get_purchase_invoice_status_for_user(purchase_invoice):
	"""Return live matching and payment status for a submitted payable."""
	invoice = frappe.get_doc("Purchase Invoice", purchase_invoice)
	invoice.check_permission("read")
	from china_finance.services.purchase_reconciliation import (
		evaluate_purchase_invoice,
		get_purchase_invoice_payment_summary,
	)

	payment_summary = get_purchase_invoice_payment_summary(invoice.name)
	evaluation = evaluate_purchase_invoice(invoice.name)
	return {
		"purchase_invoice": invoice.name,
		"purchase_orders": evaluation["purchase_orders"],
		"purchase_receipts": evaluation["purchase_receipts"],
		"tax_invoices": evaluation["tax_invoices"],
		"payment_entries": payment_summary["payment_entries"],
		"paid_amount": payment_summary["paid_amount"],
		"outstanding_amount": flt(invoice.outstanding_amount),
		"payment_status": get_purchase_payment_status(
			invoice.grand_total,
			payment_summary["paid_amount"],
			invoice.outstanding_amount,
			invoice.docstatus,
			invoice.is_return,
		),
		"reconciliation_status": evaluation["reconciliation_status"],
		"reconciliation_reason": evaluation["reconciliation_reason"],
	}


@frappe.whitelist()
def get_purchase_order_status_for_user(purchase_order):
	"""Return live receipt, payable, payment, and matching status for an order."""
	order = frappe.get_doc("Purchase Order", purchase_order)
	order.check_permission("read")
	from china_finance.services.purchase_reconciliation import get_purchase_order_reconciliation_rows

	rows = get_purchase_order_reconciliation_rows(
		order.company,
		order.transaction_date,
		order.transaction_date,
		purchase_order=order.name,
	)
	row = rows[0] if rows else frappe._dict()
	ordered_qty = flt(row.get("ordered_qty"))
	received_qty = flt(row.get("received_qty"))
	billed_qty = flt(row.get("billed_qty"))
	tolerance = 0.0001
	return {
		"purchase_order": order.name,
		"purchase_receipts": row.get("purchase_receipts") or "",
		"purchase_invoices": row.get("purchase_invoices") or "",
		"payment_entries": row.get("payment_entries") or "",
		"receive_status": (
			"未收货"
			if received_qty <= tolerance
			else "全部收货"
			if received_qty + tolerance >= ordered_qty
			else "部分收货"
		),
		"payable_status": (
			"未生成应付"
			if not row.get("purchase_invoices")
			else "全部应付"
			if flt(row.get("remaining_bill_qty")) <= tolerance
			else "部分应付"
		),
		"payment_status": row.get("payment_status") or PAYMENT_STATUS_NOT_APPLICABLE,
		"reconciliation_status": row.get("reconciliation_status") or "Ready",
		"reconciliation_reason": row.get("reconciliation_reason") or "",
		"ordered_qty": ordered_qty,
		"received_qty": received_qty,
		"billed_qty": billed_qty,
	}
