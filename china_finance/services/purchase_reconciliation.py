import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from china_finance.services.purchase_payables import (
	PAYMENT_STATUS_NOT_APPLICABLE,
	get_purchase_payment_status,
)


POLICY_DIRECT = "Direct"
POLICY_RECEIPT_AND_INVOICE = "Receipt and Invoice"
POLICY_RECEIPT_INVOICE_TAX = "Receipt, Invoice and Tax Invoice"
STATUS_READY = "Ready"
STATUS_BLOCKED = "Blocked"
STATUS_NOT_APPLICABLE = "Not Applicable"
STATUS_WAIVED = "Waived"


def get_reconciliation_policy(company, supplier, posting_date):
	"""Return the supplier rule first, then the company default, or direct reconciliation."""
	posting_date = getdate(posting_date)
	rules = frappe.get_all(
		"China Purchase Reconciliation Rule",
		filters={"company": company, "enabled": 1},
		fields=["name", "supplier", "policy", "amount_tolerance", "quantity_tolerance", "effective_from", "effective_to"],
	)
	applicable = [
		rule
		for rule in rules
		if rule.supplier in (None, "", supplier)
		and getdate(rule.effective_from) <= posting_date
		and (not rule.effective_to or getdate(rule.effective_to) >= posting_date)
	]
	if not applicable:
		return {
			"policy": POLICY_DIRECT,
			"amount_tolerance": 0.01,
			"quantity_tolerance": 0.0001,
			"rule": None,
		}
	applicable.sort(
		key=lambda rule: (bool(rule.supplier and rule.supplier == supplier), getdate(rule.effective_from), rule.name),
		reverse=True,
	)
	rule = applicable[0]
	return {
		"policy": rule.policy,
		"amount_tolerance": flt(rule.amount_tolerance),
		"quantity_tolerance": flt(rule.quantity_tolerance),
		"rule": rule.name,
	}


def evaluate_purchase_invoice(invoice_name):
	"""Evaluate one submitted purchase invoice without changing ERPNext source documents."""
	invoice = frappe.get_doc("Purchase Invoice", invoice_name)
	policy = get_reconciliation_policy(invoice.company, invoice.supplier, invoice.posting_date)
	result = {
		"purchase_invoice": invoice.name,
		"purchase_orders": "",
		"purchase_receipts": "",
		"tax_invoices": "",
		"reconciliation_policy": policy["policy"],
		"reconciliation_status": STATUS_READY,
		"reconciliation_reason": "",
		"ordered_qty": 0,
		"received_qty": 0,
		"billed_qty": 0,
		"remaining_receive_qty": 0,
		"remaining_bill_qty": 0,
		"po_variance_status": STATUS_NOT_APPLICABLE,
		"po_variance_reason": "",
	}
	if invoice.docstatus != 1:
		result.update({"reconciliation_status": STATUS_BLOCKED, "reconciliation_reason": _("采购发票未提交")})
		return result

	purchase_orders = sorted({row.purchase_order for row in invoice.items if row.purchase_order})
	purchase_receipts = sorted({row.purchase_receipt for row in invoice.items if row.purchase_receipt})
	result["purchase_orders"] = ", ".join(purchase_orders)
	result["purchase_receipts"] = ", ".join(purchase_receipts)
	result.update(_purchase_order_quantities(invoice, policy["quantity_tolerance"]))

	if policy["policy"] == POLICY_DIRECT:
		return result

	issues = _receipt_issues(invoice, policy["quantity_tolerance"])
	if policy["policy"] == POLICY_RECEIPT_INVOICE_TAX:
		tax_invoices, allocated_amount = _tax_invoice_allocation(invoice.name)
		result["tax_invoices"] = ", ".join(tax_invoices)
		if not tax_invoices:
			issues.append(_("未关联已提交的进项税务发票"))
		elif abs(flt(invoice.grand_total) - allocated_amount) > policy["amount_tolerance"]:
			issues.append(
				_("进项税务发票分摊金额 {0} 与采购发票金额 {1} 不一致").format(
					allocated_amount, flt(invoice.grand_total)
				)
			)
	if issues:
		result.update({"reconciliation_status": STATUS_BLOCKED, "reconciliation_reason": "；".join(issues)})
	return result


def _purchase_order_quantities(invoice, quantity_tolerance):
	po_items = sorted({row.po_detail for row in invoice.items if row.po_detail})
	if not po_items:
		return {
			"ordered_qty": 0, "received_qty": 0, "billed_qty": 0, "remaining_receive_qty": 0,
			"remaining_bill_qty": 0, "po_variance_status": STATUS_NOT_APPLICABLE, "po_variance_reason": "",
		}
	placeholders = ", ".join(["%s"] * len(po_items))
	rows = frappe.db.sql(
		f"""
		SELECT poi.name, poi.qty AS ordered_qty,
			COALESCE(receipts.received_qty, 0) AS received_qty,
			COALESCE(invoices.billed_qty, 0) AS billed_qty
		FROM `tabPurchase Order Item` poi
		LEFT JOIN (
			SELECT pri.purchase_order_item, SUM(pri.qty) AS received_qty
			FROM `tabPurchase Receipt Item` pri
			INNER JOIN `tabPurchase Receipt` pr ON pr.name=pri.parent AND pr.docstatus=1
			WHERE pri.purchase_order_item IN ({placeholders}) GROUP BY pri.purchase_order_item
		) receipts ON receipts.purchase_order_item=poi.name
		LEFT JOIN (
			SELECT pii.po_detail, SUM(pii.qty) AS billed_qty
			FROM `tabPurchase Invoice Item` pii
			INNER JOIN `tabPurchase Invoice` pi ON pi.name=pii.parent AND pi.docstatus=1
			WHERE pii.po_detail IN ({placeholders}) GROUP BY pii.po_detail
		) invoices ON invoices.po_detail=poi.name
		WHERE poi.name IN ({placeholders})
		""",
		[*po_items, *po_items, *po_items],
		as_dict=True,
	)
	ordered = sum(flt(row.ordered_qty) for row in rows)
	received = sum(flt(row.received_qty) for row in rows)
	billed = sum(flt(row.billed_qty) for row in rows)
	issues = []
	if received - ordered > quantity_tolerance:
		issues.append(_("采购订单累计收货数量超出订单"))
	if billed - ordered > quantity_tolerance:
		issues.append(_("采购订单累计开票数量超出订单"))
	return {
		"ordered_qty": ordered,
		"received_qty": received,
		"billed_qty": billed,
		"remaining_receive_qty": max(0, ordered - received),
		"remaining_bill_qty": max(0, ordered - billed),
		"po_variance_status": STATUS_BLOCKED if issues else STATUS_READY,
		"po_variance_reason": "；".join(issues),
	}


def apply_purchase_reconciliation_statuses(lines):
	"""Refresh generated supplier statement lines while preserving approved waivers."""
	for line in lines:
		if line.get("voucher_type") != "Purchase Invoice":
			line.update(
				{
					"reconciliation_policy": "",
					"reconciliation_status": STATUS_NOT_APPLICABLE,
					"reconciliation_reason": "",
				}
			)
			continue
		if line.get("reconciliation_status") == STATUS_WAIVED:
			continue
		evaluation = evaluate_purchase_invoice(line.get("voucher_no"))
		line.update(evaluation)


def waive_purchase_reconciliation_line(statement_name, line_name, reason):
	frappe.only_for(("System Manager", "Accounts Manager", "China Finance Manager"))
	if not reason:
		frappe.throw(_("豁免必须填写原因"))
	statement = frappe.get_doc("China Reconciliation Statement", statement_name)
	if statement.docstatus != 0 or statement.statement_type != "Supplier":
		frappe.throw(_("只能豁免草稿供应商对账单中的采购拦截明细"))
	line = next((row for row in statement.lines if row.name == line_name), None)
	if not line or line.reconciliation_status != STATUS_BLOCKED:
		frappe.throw(_("未找到可豁免的采购拦截明细"))
	line.reconciliation_status = STATUS_WAIVED
	line.waiver_reason = reason
	line.waived_by = frappe.session.user
	line.waived_on = now_datetime()
	statement.save()
	return {"statement": statement.name, "line": line.name, "status": line.reconciliation_status}


def get_blocked_purchase_invoices(company, from_date, to_date):
	blocked = []
	for name in frappe.get_all(
		"Purchase Invoice",
		filters={"company": company, "posting_date": ["between", [from_date, to_date]], "docstatus": 1},
		pluck="name",
	):
		result = evaluate_purchase_invoice(name)
		if result["reconciliation_status"] == STATUS_BLOCKED:
			blocked.append(result)
	return blocked


def get_purchase_invoice_payment_summary(purchase_invoice):
	row = frappe.db.sql(
		"""
		SELECT GROUP_CONCAT(DISTINCT pe.name ORDER BY pe.posting_date, pe.name SEPARATOR ', ') AS payment_entries,
			COALESCE(SUM(reference.allocated_amount), 0) AS paid_amount
		FROM `tabPayment Entry Reference` reference
		INNER JOIN `tabPayment Entry` pe ON pe.name=reference.parent AND pe.docstatus=1
		WHERE reference.reference_doctype='Purchase Invoice' AND reference.reference_name=%s
		""",
		purchase_invoice,
		as_dict=True,
	)[0]
	return {"payment_entries": row.payment_entries or "", "paid_amount": flt(row.paid_amount)}


def get_purchase_order_reconciliation_rows(company, from_date, to_date, supplier=None, purchase_order=None):
	conditions = [
		"po.company=%(company)s",
		"po.transaction_date BETWEEN %(from_date)s AND %(to_date)s",
		"po.docstatus=1",
	]
	values = {"company": company, "from_date": from_date, "to_date": to_date}
	if supplier:
		conditions.append("po.supplier=%(supplier)s")
		values["supplier"] = supplier
	if purchase_order:
		conditions.append("po.name=%(purchase_order)s")
		values["purchase_order"] = purchase_order
	rows = frappe.db.sql(
		f"""
		SELECT po.name AS purchase_order, po.transaction_date, po.supplier,
			COALESCE(invoices.currency, po.currency) AS currency,
			COALESCE(invoices.party_account_currency, po.currency) AS party_account_currency,
			COALESCE(po_qty.ordered_qty, 0) AS ordered_qty, receipts.purchase_receipts,
			COALESCE(receipts.received_qty, 0) AS received_qty, invoices.purchase_invoices,
			COALESCE(invoices.billed_qty, 0) AS billed_qty, tax.tax_invoices,
			payments.payment_entries, COALESCE(payments.paid_amount, 0) AS paid_amount,
			COALESCE(invoices.grand_total, 0) AS invoice_amount,
			COALESCE(invoices.outstanding_amount, 0) AS outstanding_amount
		FROM `tabPurchase Order` po
		LEFT JOIN (
			SELECT parent, SUM(qty) AS ordered_qty FROM `tabPurchase Order Item` GROUP BY parent
		) po_qty ON po_qty.parent=po.name
		LEFT JOIN (
			SELECT pri.purchase_order,
				GROUP_CONCAT(DISTINCT pri.parent ORDER BY pri.parent SEPARATOR ', ') AS purchase_receipts,
				SUM(pri.qty) AS received_qty
			FROM `tabPurchase Receipt Item` pri
			INNER JOIN `tabPurchase Receipt` pr ON pr.name=pri.parent AND pr.docstatus=1
			WHERE pri.purchase_order IS NOT NULL AND pri.purchase_order!=''
			GROUP BY pri.purchase_order
		) receipts ON receipts.purchase_order=po.name
		LEFT JOIN (
			SELECT source.purchase_order,
				GROUP_CONCAT(DISTINCT source.currency) AS currency,
				GROUP_CONCAT(DISTINCT source.party_account_currency) AS party_account_currency,
				GROUP_CONCAT(source.purchase_invoice ORDER BY source.purchase_invoice SEPARATOR ', ') AS purchase_invoices,
				SUM(source.billed_qty) AS billed_qty, SUM(source.allocated_invoice_amount) AS grand_total,
				SUM(source.allocated_outstanding_amount) AS outstanding_amount
			FROM (
				SELECT pii.purchase_order, pii.parent AS purchase_invoice, pi.currency, pi.party_account_currency, SUM(pii.qty) AS billed_qty,
					SUM(CASE WHEN pi.base_net_total > 0 THEN pi.grand_total * pii.base_amount / pi.base_net_total ELSE 0 END) AS allocated_invoice_amount,
					SUM(CASE WHEN pi.base_net_total > 0 THEN pi.outstanding_amount * pii.base_amount / pi.base_net_total ELSE 0 END) AS allocated_outstanding_amount
				FROM `tabPurchase Invoice Item` pii
				INNER JOIN `tabPurchase Invoice` pi ON pi.name=pii.parent AND pi.docstatus=1
				WHERE pii.purchase_order IS NOT NULL AND pii.purchase_order!=''
				GROUP BY pii.purchase_order, pii.parent, pi.currency, pi.party_account_currency
			) source GROUP BY source.purchase_order
		) invoices ON invoices.purchase_order=po.name
		LEFT JOIN (
			SELECT pii.purchase_order,
				GROUP_CONCAT(DISTINCT ti.name ORDER BY ti.invoice_date, ti.name SEPARATOR ', ') AS tax_invoices
			FROM `tabPurchase Invoice Item` pii
			INNER JOIN `tabChina Tax Invoice Allocation` allocation
				ON allocation.reference_doctype='Purchase Invoice' AND allocation.reference_name=pii.parent
			INNER JOIN `tabChina Tax Invoice` ti
				ON ti.name=allocation.parent AND ti.docstatus=1 AND ti.direction='进项'
			WHERE pii.purchase_order IS NOT NULL AND pii.purchase_order!=''
			GROUP BY pii.purchase_order
		) tax ON tax.purchase_order=po.name
		LEFT JOIN (
			SELECT source.purchase_order,
				GROUP_CONCAT(DISTINCT source.payment_entry ORDER BY source.payment_entry SEPARATOR ', ') AS payment_entries,
				SUM(source.allocated_amount) AS paid_amount
			FROM (
				SELECT pii.purchase_order, reference.parent AS payment_entry, reference.reference_name,
					SUM(CASE WHEN pi.base_net_total > 0 THEN reference.allocated_amount * pii.base_amount / pi.base_net_total ELSE 0 END) AS allocated_amount
				FROM `tabPurchase Invoice Item` pii
				INNER JOIN `tabPurchase Invoice` pi ON pi.name=pii.parent AND pi.docstatus=1
				INNER JOIN `tabPayment Entry Reference` reference
					ON reference.reference_doctype='Purchase Invoice' AND reference.reference_name=pii.parent
				INNER JOIN `tabPayment Entry` pe ON pe.name=reference.parent AND pe.docstatus=1
				WHERE pii.purchase_order IS NOT NULL AND pii.purchase_order!=''
				GROUP BY pii.purchase_order, pii.parent, reference.parent, reference.reference_name
			) source GROUP BY source.purchase_order
		) payments ON payments.purchase_order=po.name
		WHERE {' AND '.join(conditions)}
		ORDER BY po.transaction_date, po.name
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		policy = get_reconciliation_policy(company, row.supplier, row.transaction_date)
		tolerance = policy["quantity_tolerance"]
		issues = []
		if row.received_qty - row.ordered_qty > tolerance:
			issues.append(_("超收"))
		if row.billed_qty - row.ordered_qty > tolerance:
			issues.append(_("超票"))
		if policy["policy"] != POLICY_DIRECT and row.billed_qty > tolerance:
			if not row.purchase_receipts or row.received_qty + tolerance < row.billed_qty:
				issues.append(_("收货与发票未齐套"))
		if policy["policy"] == POLICY_RECEIPT_INVOICE_TAX and row.purchase_invoices and not row.tax_invoices:
			issues.append(_("未关联进项税票"))
		row.reconciliation_policy = policy["policy"]
		row.remaining_receive_qty = max(0, flt(row.ordered_qty) - flt(row.received_qty))
		row.remaining_bill_qty = max(0, flt(row.ordered_qty) - flt(row.billed_qty))
		row.reconciliation_status = STATUS_BLOCKED if issues else STATUS_READY
		row.reconciliation_reason = "；".join(issues)
		row.payment_status = (
			get_purchase_payment_status(row.invoice_amount, row.invoice_amount - row.paid_amount, row.outstanding_amount)
			if row.purchase_invoices
			else PAYMENT_STATUS_NOT_APPLICABLE
		)
	return rows


def _receipt_issues(invoice, quantity_tolerance):
	issues = []
	for row in invoice.items:
		if not row.purchase_receipt:
			issues.append(_("物料 {0} 未关联采购收货单").format(row.item_code or row.idx))
			continue
		if frappe.db.get_value("Purchase Receipt", row.purchase_receipt, "docstatus") != 1:
			issues.append(_("采购收货单 {0} 未提交").format(row.purchase_receipt))
			continue
		if not row.pr_detail:
			issues.append(_("物料 {0} 缺少收货明细关联").format(row.item_code or row.idx))
			continue
		received_qty = flt(frappe.db.get_value("Purchase Receipt Item", row.pr_detail, "received_qty"))
		if received_qty + quantity_tolerance < flt(row.qty):
			issues.append(_("物料 {0} 收货数量不足").format(row.item_code or row.idx))
	return list(dict.fromkeys(issues))


def _tax_invoice_allocation(purchase_invoice):
	rows = frappe.db.sql(
		"""
		SELECT ti.name, COALESCE(SUM(a.allocated_gross_amount), 0) AS allocated_amount
		FROM `tabChina Tax Invoice Allocation` a
		INNER JOIN `tabChina Tax Invoice` ti ON ti.name=a.parent
		WHERE a.reference_doctype='Purchase Invoice' AND a.reference_name=%s
			AND ti.docstatus=1 AND ti.direction='进项' AND ti.invoice_status='蓝票'
		GROUP BY ti.name
		ORDER BY ti.invoice_date, ti.name
		""",
		purchase_invoice,
		as_dict=True,
	)
	return [row.name for row in rows], sum(flt(row.allocated_amount) for row in rows)
