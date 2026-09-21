import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime


TAX_USERS = ("System Manager", "Accounts Manager", "China Tax User")
FINANCE_MANAGERS = ("System Manager", "Accounts Manager", "China Finance Manager")
ACTIVE_REQUEST_STATUSES = ("Draft", "Pending Approval", "Approved", "Invoiced")
AMOUNT_TOLERANCE = 0.01


def _only_for(roles):
	frappe.only_for(roles)


def get_invoice_requirement(company, customer, posting_date, sales_invoice=None):
	"""Resolve single-document override, then customer rule, then company rule."""
	if sales_invoice:
		override = frappe.db.get_value("China Sales Invoice Control", sales_invoice, "requirement")
		if override:
			return {"requirement": override, "source": "Sales Invoice"}
	rules = frappe.get_all(
		"China Invoice Control Rule",
		filters={"company": company, "enabled": 1, "effective_from": ["<=", posting_date]},
		or_filters={"effective_to": [">=", posting_date], "effective_to": ["is", "not set"]},
		fields=["name", "customer", "requirement", "effective_from"],
		order_by="customer desc, effective_from desc, modified desc",
	)
	for rule in rules:
		if rule.customer == customer or not rule.customer:
			return {"requirement": rule.requirement, "source": rule.name}
	return {"requirement": "Manual", "source": None}


def _get_submitted_sales_invoice(name):
	doc = frappe.get_doc("Sales Invoice", name)
	if doc.docstatus != 1:
		frappe.throw(_("销售发票 {0} 必须已提交").format(name))
	return doc


def _invoice_tax_amount(doc):
	return flt(doc.total_taxes_and_charges, 2)


def _get_request_party_details(invoice):
	return {
		"seller_name": frappe.get_cached_value("Company", invoice.company, "company_name") or invoice.company,
		"seller_tax_id": invoice.company_tax_id
			or frappe.get_cached_value("Company", invoice.company, "tax_id"),
		"buyer_name": invoice.customer_name or invoice.customer,
		"buyer_tax_id": invoice.tax_id
			or frappe.get_cached_value("Customer", invoice.customer, "tax_id"),
	}


def _request_rows_from_invoice(doc):
	rows = []
	remaining_tax = _invoice_tax_amount(doc)
	for index, row in enumerate(doc.items):
		net_amount = flt(row.net_amount, 2)
		if index == len(doc.items) - 1:
			tax_amount = remaining_tax
		else:
			tax_amount = flt(_invoice_tax_amount(doc) * net_amount / flt(doc.net_total or 1), 2)
			remaining_tax -= tax_amount
		rows.append(
			{
				"sales_invoice": doc.name,
				"sales_invoice_item": row.name,
				"item_code": row.item_code,
				"item_name": row.item_name or row.description or row.item_code,
				"quantity": row.qty,
				"uom": row.uom,
				"net_amount": net_amount,
				"tax_rate": flt(tax_amount * 100 / net_amount, 4) if net_amount else 0,
				"tax_amount": tax_amount,
			}
		)
	return rows


def _validate_request_capacity(doc):
	"""Reserve source amount through active requests and prevent over-requesting."""
	for sales_invoice in {row.sales_invoice for row in doc.items}:
		invoice = _get_submitted_sales_invoice(sales_invoice)
		requested = sum(flt(row.gross_amount, 2) for row in doc.items if row.sales_invoice == sales_invoice)
		reserved = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(item.gross_amount), 0)
			FROM `tabChina Tax Invoice Request Item` item
			INNER JOIN `tabChina Tax Invoice Request` request ON request.name=item.parent
			WHERE item.sales_invoice=%s AND request.name!=%s
			AND request.status IN ('Draft', 'Pending Approval', 'Approved', 'Invoiced')
			""",
			(sales_invoice, doc.name or ""),
		)[0][0]
		available = flt(invoice.grand_total, 2) - flt(reserved, 2)
		if requested - available > AMOUNT_TOLERANCE:
			frappe.throw(_("销售发票 {0} 的累计开票申请金额不能超过原发票").format(sales_invoice))


def _validate_red_request(doc):
	if doc.request_type != "Red":
		return
	if not doc.original_invoice or not doc.credit_note:
		frappe.throw(_("红冲申请必须关联原蓝票和已提交销售退货或贷项发票"))
	blue = frappe.get_doc("China Tax Invoice", doc.original_invoice)
	credit_note = _get_submitted_sales_invoice(doc.credit_note)
	if blue.docstatus != 1 or blue.invoice_status != "蓝票":
		frappe.throw(_("原蓝票必须已提交且为蓝票"))
	if not credit_note.is_return:
		frappe.throw(_("红冲必须关联销售退货或贷项销售发票"))
	if any(flt(row.gross_amount) >= 0 for row in doc.items):
		frappe.throw(_("红冲申请的所有金额必须为负数"))
	already_red = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(ABS(gross_amount)), 0) FROM `tabChina Tax Invoice`
		WHERE original_invoice=%s AND invoice_status='红票' AND docstatus=1
		""",
		blue.name,
	)[0][0]
	if flt(already_red) + abs(flt(doc.gross_amount)) - flt(blue.gross_amount) > AMOUNT_TOLERANCE:
		frappe.throw(_("累计红冲金额不能超过原蓝票可红冲金额"))


@frappe.whitelist()
def create_request_from_sales_invoices(sales_invoices, company=None, remarks=None):
	_only_for(TAX_USERS)
	sales_invoices = frappe.parse_json(sales_invoices) if isinstance(sales_invoices, str) else sales_invoices
	if not isinstance(sales_invoices, list) or not sales_invoices:
		frappe.throw(_("至少选择一张销售发票"))
	invoices = [_get_submitted_sales_invoice(name) for name in sales_invoices]
	if len({doc.company for doc in invoices}) != 1 or (company and invoices[0].company != company):
		frappe.throw(_("合并开票申请必须属于同一公司"))
	if len({doc.customer for doc in invoices}) != 1:
		frappe.throw(_("合并开票申请必须属于同一客户"))
	if any(doc.is_return for doc in invoices):
		frappe.throw(_("销售退货或贷项发票必须通过红冲申请处理"))
	requirements = [get_invoice_requirement(doc.company, doc.customer, doc.posting_date, doc.name)["requirement"] for doc in invoices]
	party_details = _get_request_party_details(invoices[0])
	if not party_details["seller_tax_id"]:
		frappe.throw(_("公司 {0} 未维护税号，请先在公司资料中填写税号").format(invoices[0].company))
	doc = frappe.get_doc(
		{
			"doctype": "China Tax Invoice Request",
			"company": invoices[0].company,
			"customer": invoices[0].customer,
			**party_details,
			"requirement": "Required" if "Required" in requirements else "Manual",
			"remarks": remarks,
			"items": [row for invoice in invoices for row in _request_rows_from_invoice(invoice)],
		}
	)
	doc.insert()
	_validate_request_capacity(doc)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def set_sales_invoice_requirement(sales_invoice, requirement, reason):
	_only_for(FINANCE_MANAGERS)
	if requirement not in ("Required", "Not Required", "Manual") or not reason:
		frappe.throw(_("必须选择开票要求并填写覆盖原因"))
	sales = _get_submitted_sales_invoice(sales_invoice)
	name = frappe.db.get_value("China Sales Invoice Control", sales_invoice, "name")
	values = {"company": sales.company, "customer": sales.customer, "requirement": requirement, "reason": reason, "set_by": frappe.session.user, "set_on": now_datetime()}
	if name:
		doc = frappe.get_doc("China Sales Invoice Control", name)
		doc.update(values)
		doc.save()
	else:
		doc = frappe.get_doc({"doctype": "China Sales Invoice Control", "sales_invoice": sales_invoice, **values}).insert()
	return {"name": doc.name, "requirement": doc.requirement}


@frappe.whitelist()
def submit_request(name):
	_only_for(TAX_USERS)
	doc = frappe.get_doc("China Tax Invoice Request", name)
	if doc.status != "Draft":
		frappe.throw(_("只有草稿开票申请可以提交"))
	_validate_request_capacity(doc)
	_validate_red_request(doc)
	doc.db_set("status", "Pending Approval")
	return {"name": doc.name, "status": "Pending Approval"}


@frappe.whitelist()
def approve_request(name):
	_only_for(FINANCE_MANAGERS)
	doc = frappe.get_doc("China Tax Invoice Request", name)
	if doc.status != "Pending Approval":
		frappe.throw(_("只有待审批开票申请可以审批"))
	_validate_request_capacity(doc)
	_validate_red_request(doc)
	doc.db_set("status", "Approved")
	doc.db_set("approved_by", frappe.session.user)
	doc.db_set("approved_on", now_datetime())
	return {"name": doc.name, "status": "Approved"}


@frappe.whitelist()
def reject_request(name, reason):
	_only_for(FINANCE_MANAGERS)
	if not reason:
		frappe.throw(_("驳回必须填写原因"))
	doc = frappe.get_doc("China Tax Invoice Request", name)
	if doc.status != "Pending Approval":
		frappe.throw(_("只有待审批开票申请可以驳回"))
	doc.db_set("status", "Rejected")
	doc.db_set("rejection_reason", reason)
	return {"name": doc.name, "status": "Rejected"}


@frappe.whitelist()
def cancel_request(name, reason):
	_only_for(FINANCE_MANAGERS)
	if not reason:
		frappe.throw(_("取消必须填写原因"))
	doc = frappe.get_doc("China Tax Invoice Request", name)
	if doc.status in ("Invoiced", "Cancelled"):
		frappe.throw(_("已开票或已取消申请不能取消"))
	doc.db_set("status", "Cancelled")
	doc.db_set("rejection_reason", reason)
	return {"name": doc.name, "status": "Cancelled"}


def _invoice_payload(request):
	allocations = {}
	for row in request.items:
		bucket = allocations.setdefault(row.sales_invoice, {"reference_doctype": "Sales Invoice", "reference_name": row.sales_invoice, "allocated_net_amount": 0, "allocated_tax_amount": 0})
		bucket["allocated_net_amount"] += flt(row.net_amount, 2)
		bucket["allocated_tax_amount"] += flt(row.tax_amount, 2)
	return {
		"doctype": "China Tax Invoice",
		"company": request.company,
		"currency": request.currency,
		"direction": "销项",
		"invoice_type": "数电普通发票",
		"invoice_date": getdate(),
		"invoice_status": "红票" if request.request_type == "Red" else "蓝票",
		"seller_name": request.seller_name,
		"seller_tax_id": request.seller_tax_id,
		"buyer_name": request.buyer_name,
		"buyer_tax_id": request.buyer_tax_id,
		"original_invoice": request.original_invoice,
		"invoice_request": request.name,
		"credit_note": request.credit_note,
		"source_system": "China Tax Invoice Request",
		"source_id": request.name,
		"items": [{"item_name": row.item_name, "quantity": row.quantity, "unit": row.uom, "net_amount": row.net_amount, "tax_rate": row.tax_rate, "tax_amount": row.tax_amount} for row in request.items],
		"allocations": list(allocations.values()),
	}


@frappe.whitelist()
def create_tax_invoice_draft(name):
	_only_for(TAX_USERS)
	request = frappe.get_doc("China Tax Invoice Request", name)
	if request.status != "Approved":
		frappe.throw(_("只有已审批开票申请可以生成税务发票草稿"))
	if request.tax_invoice:
		return {"name": request.tax_invoice, "existing": True}
	doc = frappe.get_doc(_invoice_payload(request))
	# Invoice number is a required external fact; a temporary draft reference prevents accidental submission.
	doc.invoice_number = "DRAFT-" + request.name
	doc.insert()
	request.db_set("tax_invoice", doc.name)
	return {"name": doc.name, "existing": False}


@frappe.whitelist()
def feedback_tax_invoice(name, invoice_number, invoice_date, invoice_code=None, original_file=None, idempotency_key=None):
	"""Complete an approved request's draft with the returned tax-invoice identity and submit it."""
	_only_for(TAX_USERS)
	doc = frappe.get_doc("China Tax Invoice", name)
	idempotency_key = idempotency_key or f"manual-feedback:{doc.name}:{invoice_number}"
	if doc.docstatus == 1 and frappe.db.exists("China Tax Integration Call", {"idempotency_key": idempotency_key}):
		return {"name": doc.name, "status": "Submitted", "integration_call": frappe.db.get_value("China Tax Integration Call", {"idempotency_key": idempotency_key}, "name")}
	if doc.docstatus != 0 or not doc.invoice_request:
		frappe.throw(_("只能回填关联开票申请的税务发票草稿"))
	if not invoice_number or not invoice_date:
		frappe.throw(_("回填必须提供发票号码和开票日期"))
	request = frappe.get_doc("China Tax Invoice Request", doc.invoice_request)
	if request.status != "Approved":
		frappe.throw(_("关联开票申请必须为已审批状态"))
	doc.invoice_number = invoice_number
	doc.invoice_date = invoice_date
	doc.invoice_code = invoice_code
	if original_file:
		doc.original_file = original_file
	doc.source_system = "Manual Feedback"
	doc.save()
	doc.submit()
	call = create_integration_call(
		doc.company,
		"Manual",
		"Red" if doc.invoice_status == "红票" else "Issue",
		idempotency_key,
		request=request.name,
		tax_invoice=doc.name,
		request_summary={"invoice_number": invoice_number, "invoice_date": str(invoice_date)},
	)
	if call.status != "Succeeded":
		call.db_set("status", "Succeeded")
		call.db_set("completed_on", now_datetime())
		call.db_set("response_summary", json.dumps({"tax_invoice": doc.name}, ensure_ascii=False))
	return {"name": doc.name, "status": "Submitted", "integration_call": call.name}


def sync_request_from_tax_invoice(invoice):
	if not invoice.invoice_request:
		return
	request = frappe.get_doc("China Tax Invoice Request", invoice.invoice_request)
	if invoice.docstatus == 1:
		request.db_set("tax_invoice", invoice.name)
		request.db_set("status", "Invoiced")
	elif invoice.docstatus == 2 and request.status == "Invoiced":
		request.db_set("status", "Approved")


@frappe.whitelist()
def create_red_request(original_invoice, credit_note):
	_only_for(FINANCE_MANAGERS)
	blue = frappe.get_doc("China Tax Invoice", original_invoice)
	credit = _get_submitted_sales_invoice(credit_note)
	if blue.docstatus != 1 or blue.invoice_status != "蓝票" or not credit.is_return:
		frappe.throw(_("红冲需要已提交蓝票及已提交销售退货或贷项发票"))
	doc = frappe.get_doc(
		{
			"doctype": "China Tax Invoice Request", "company": credit.company, "customer": credit.customer,
			"request_type": "Red", "original_invoice": blue.name, "credit_note": credit.name,
			"seller_name": blue.seller_name, "seller_tax_id": blue.seller_tax_id, "buyer_name": blue.buyer_name, "buyer_tax_id": blue.buyer_tax_id,
			"requirement": "Required", "items": _request_rows_from_invoice(credit),
		}
	).insert()
	_validate_red_request(doc)
	return {"name": doc.name, "status": doc.status}


def create_integration_call(company, provider, operation, idempotency_key, request=None, tax_invoice=None, request_summary=None):
	if frappe.db.exists("China Tax Integration Call", {"idempotency_key": idempotency_key}):
		doc = frappe.get_doc("China Tax Integration Call", {"idempotency_key": idempotency_key})
		if doc.request != request or doc.tax_invoice != tax_invoice or doc.operation != operation:
			frappe.throw(_("幂等键已用于其他税务接口调用"))
		return doc
	return frappe.get_doc({"doctype": "China Tax Integration Call", "company": company, "provider": provider, "operation": operation, "idempotency_key": idempotency_key, "request": request, "tax_invoice": tax_invoice, "request_summary": json.dumps(request_summary or {}, ensure_ascii=False), "started_on": now_datetime()}).insert(ignore_permissions=True)
