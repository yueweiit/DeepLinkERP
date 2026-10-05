"""One native PO advance/stock/invoice/tail chain, dedicated empty synthetic QA only."""

import json
import uuid

import frappe
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
from frappe.utils import add_days, nowdate

from deeplinkerp_branding.services import purchase_document_actions as actions
from deeplinkerp_branding.services import purchase_order_progress as progress
from deeplinkerp_branding.services import purchase_payment_service as payments

COMPANY = "QA Second Company"


def guard():
	assert frappe.local.site == "po-grid-qa.localhost"
	assert frappe.conf.db_name == "qa_po_flow_5" and frappe.conf.db_host == "db"
	assert not frappe.db.sql("select count(*) from `tabPurchase Order Item` where item_code not like 'QA-%'")[
		0
	][0]
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	frappe.flags.mute_emails = True


def order(submit=True):
	doc = frappe.get_doc(
		dict(
			doctype="Purchase Order",
			company=COMPANY,
			supplier="QA Test Supplier",
			currency="CNY",
			schedule_date=add_days(nowdate(), 1),
			items=[
				dict(
					item_code="QA-PO-ITEM",
					qty=10,
					rate=1000,
					warehouse="Stores - QAB",
					schedule_date=add_days(nowdate(), 1),
				)
			],
		)
	).insert()
	if submit:
		doc.submit()
	return doc


def ledgers(names):
	return {
		"gl": frappe.get_all(
			"GL Entry",
			filters={"voucher_no": ["in", names]},
			fields=[
				"voucher_type",
				"voucher_no",
				"account",
				"debit",
				"credit",
				"against_voucher_type",
				"against_voucher",
				"is_cancelled",
			],
			limit_page_length=0,
		),
		"ple": frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_no": ["in", names]},
			fields=[
				"voucher_type",
				"voucher_no",
				"account",
				"against_voucher_type",
				"against_voucher_no",
				"amount",
				"delinked",
			],
			limit_page_length=0,
		),
	}


def chain():
	guard()
	before_pi_count = frappe.db.count("Purchase Invoice")
	po = order()
	args = dict(
		source_doctype="Purchase Order",
		source_name=po.name,
		amount_to_pay=3000,
		bank_account="Cash - QAB",
		request_id=str(uuid.uuid4()),
	)
	result = actions.record_payment(**args)
	assert not result.get("failed"), result
	advance = result["document"]
	assert advance["docstatus"] == 1
	assert frappe.db.count("Purchase Invoice") == before_pi_count
	first = ledgers([advance["name"]])
	assert any(row.account == "QA Supplier Advances - QAB" and row.debit == 3000 for row in first["gl"]), (
		first
	)
	assert any(row.account == "Cash - QAB" and row.credit == 3000 for row in first["gl"]), first
	assert actions.record_payment(**args)["document"]["name"] == advance["name"]
	assert ledgers([advance["name"]]) == first
	pre = progress.get_order_progress([po.name])
	print("AFTER_ADVANCE", json.dumps(pre, default=str))
	drafts = frappe.get_all(
		"Purchase Receipt Item", filters={"purchase_order": po.name, "docstatus": 0}, pluck="parent"
	)
	preview = actions.preview_document(
		"Purchase Order", po.name, "Purchase Receipt", target_name=drafts[0] if drafts else None
	)
	key = preview["document"]["items"][0]["key"]
	receipt_args = dict(
		source_name=po.name,
		changes={"items": [{"key": key, "qty": 4}]},
		request_id=str(uuid.uuid4()),
		**(
			{"target_name": preview["document"]["name"], "expected_modified": preview["document"]["modified"]}
			if preview["document"]["name"]
			else {}
		),
	)
	received = actions.record_receipt(**receipt_args)
	assert not received.get("failed"), received
	pr = received["document"]
	assert pr["docstatus"] == 1
	assert actions.record_receipt(**receipt_args)["document"]["name"] == pr["name"]
	assert frappe.db.get_value("Purchase Order", po.name, "per_received") == 40
	qty = frappe.db.get_value("Bin", {"item_code": "QA-PO-ITEM", "warehouse": "Stores - QAB"}, "actual_qty")
	assert qty == 4, qty
	pi = make_purchase_invoice(pr["name"])
	pi.bill_no = "QA-COMMERCIAL-001"
	pi.bill_date = nowdate()
	pi.allocate_advances_automatically = 1
	pi.set_advances()
	pi.insert()
	pi.submit()
	assert sum(row.allocated_amount for row in pi.advances) == 3000
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 1000
	after_bill = ledgers([advance["name"], pr["name"], pi.name])
	assert (
		sum(
			row.debit - row.credit
			for row in after_bill["gl"]
			if row.account == "QA Supplier Advances - QAB" and not row.is_cancelled
		)
		== 0
	)
	cash = sum(
		row.credit - row.debit
		for row in after_bill["gl"]
		if row.account == "Cash - QAB" and not row.is_cancelled
	)
	assert cash == 3000, cash
	after = progress.get_order_progress([po.name])
	print("AFTER_BILL", json.dumps(after, default=str))
	assert after[po.name]["settled"] == 3000, after
	tail = actions.record_payment(
		source_doctype="Purchase Order",
		source_name=po.name,
		purchase_invoice=pi.name,
		amount_to_pay=1000,
		bank_account="Cash - QAB",
		request_id=str(uuid.uuid4()),
	)
	assert not tail.get("failed"), tail
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 0
	final = progress.get_order_progress([po.name])
	assert final[po.name]["settled"] == 4000, final
	assert final[po.name]["order_unpaid"] == 6000, final
	assert (
		frappe.db.get_value("Bin", {"item_code": "QA-PO-ITEM", "warehouse": "Stores - QAB"}, "actual_qty")
		== 4
	)
	return dict(
		order=po.name,
		advance=advance["name"],
		receipt=pr["name"],
		invoice=pi.name,
		tail=tail["document"]["name"],
		stock_qty=4,
		remaining_order=6000,
		invoice_outstanding=0,
		advance_ledger=first,
		invoice_ledger=after_bill,
		final_ledger=ledgers([advance["name"], pr["name"], pi.name, tail["document"]["name"]]),
		progress=final,
	)


def receipt(po, qty=4):
	drafts = frappe.get_all(
		"Purchase Receipt Item", filters={"purchase_order": po.name, "docstatus": 0}, pluck="parent"
	)
	preview = actions.preview_document(
		"Purchase Order", po.name, "Purchase Receipt", target_name=drafts[0] if drafts else None
	)["document"]
	return actions.record_receipt(
		source_name=po.name,
		changes={"items": [{"key": preview["items"][0]["key"], "qty": qty}]},
		request_id=str(uuid.uuid4()),
		**(
			{"target_name": preview["name"], "expected_modified": preview["modified"]}
			if preview["name"]
			else {}
		),
	)


def advance_args(po, amount=3000, **extra):
	return dict(
		source_doctype="Purchase Order",
		source_name=po.name,
		amount_to_pay=amount,
		bank_account="Cash - QAB",
		request_id=str(uuid.uuid4()),
		**extra,
	)


def reject_draft_order():
	po = order(False)
	result = actions.record_payment(**advance_args(po))
	assert result.get("failed") and "提交" in result["error"], result
	assert not frappe.db.count("Payment Entry")


def reject_missing_asset():
	po = order()
	frappe.db.set_value("Company", COMPANY, "book_advance_payments_in_separate_party_account", 0)
	frappe.clear_document_cache("Company", COMPANY)
	result = actions.record_payment(**advance_args(po))
	assert result.get("failed") and "资产" in result["error"], result
	assert not frappe.db.count("Payment Entry") and not frappe.db.count("GL Entry")


def reject_overpayment():
	po = order()
	result = actions.record_payment(**advance_args(po, 10001))
	assert result.get("failed") and "余额" in result["error"], result
	assert not frappe.db.count("Payment Entry")


def continue_advance_draft():
	po = order()
	args = advance_args(po, confirm=0)
	draft = actions.record_payment(**args)["document"]
	assert draft["docstatus"] == 0
	retry = actions.record_payment(**advance_args(po, 500))
	assert retry.get("needs_review") and retry["document"]["name"] == draft["name"]
	assert retry["document"]["amount"] == 3000 and not frappe.db.count("GL Entry")
	completed = actions.complete_payment(
		draft["name"], {"amount": 2000}, draft["modified"], str(uuid.uuid4())
	)
	assert not completed.get("failed"), completed
	assert completed["document"]["docstatus"] == 1 and completed["document"]["amount"] == 2000
	assert progress.get_order_progress([po.name])[po.name]["settled"] == 2000


def receipt_cancellation():
	po = order()
	received = receipt(po)
	assert not received.get("failed"), received
	assert (
		frappe.db.get_value("Bin", {"item_code": "QA-PO-ITEM", "warehouse": "Stores - QAB"}, "actual_qty")
		== 4
	)
	doc = frappe.get_doc("Purchase Receipt", received["document"]["name"])
	doc.cancel()
	assert frappe.db.get_value("Purchase Order", po.name, "per_received") == 0
	assert (
		frappe.db.get_value("Bin", {"item_code": "QA-PO-ITEM", "warehouse": "Stores - QAB"}, "actual_qty")
		== 0
	)


def advance_cancellation():
	po = order()
	result = actions.record_payment(**advance_args(po))
	assert not result.get("failed"), result
	doc = frappe.get_doc("Payment Entry", result["document"]["name"])
	doc.cancel()
	summary = progress.get_order_progress([po.name])[po.name]
	assert summary["settled"] == 0 and summary["order_unpaid"] == 10000
	assert frappe.db.get_value("Purchase Order", po.name, "advance_paid") == 0
	gl = ledgers([doc.name])["gl"]
	assert (
		sum(row.debit - row.credit for row in gl if row.account == "Cash - QAB" and not row.is_cancelled) == 0
	)


def permissions():
	po = order()
	user = "qa-po-buyer@example.invalid"
	frappe.get_doc(
		dict(
			doctype="User",
			email=user,
			first_name="QA Buyer",
			send_welcome_email=0,
			roles=[{"role": "Purchase User"}, {"role": "Purchase Manager"}],
		)
	).insert()
	frappe.set_user(user)
	summary = progress.get_order_progress([po.name])[po.name]
	assert summary["settled"] == 0
	assert not frappe.has_permission("Payment Entry", "create")
	result = actions.record_payment(**advance_args(po))
	assert result.get("failed") and "权限" in result["error"], result
	assert not frappe.db.count("Payment Entry")


def source_pending():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Purchase Order": [
				{
					"fieldname": "custom_oa_purchase_expense",
					"label": "QA OA Source",
					"fieldtype": "Link",
					"options": "OA Purchase Request",
				}
			]
		}
	)
	for field in ("source_pending", "source_invalid", "source_stale"):
		if not frappe.get_meta("OA Purchase Request").has_field(field):
			create_custom_fields(
				{"OA Purchase Request": [{"fieldname": field, "label": "QA " + field, "fieldtype": "Check"}]}
			)
	po = order()
	source = frappe.get_doc(
		{
			"doctype": "OA Purchase Request",
			"oa_code": "QA-PENDING-" + str(uuid.uuid4()),
			"approval_status": "RUNNING",
			"source_pending": 1,
		}
	)
	source.flags.ignore_mandatory = True
	source.insert()
	frappe.db.set_value("Purchase Order", po.name, "custom_oa_purchase_expense", source.name)
	result = actions.record_payment(**advance_args(po))
	assert result.get("failed") and "审批" in result["error"], result
	assert not frappe.db.count("Payment Entry")


def receipt_workflow():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	if not frappe.get_meta("Purchase Receipt").has_field("workflow_state"):
		create_custom_fields(
			{
				"Purchase Receipt": [
					{
						"fieldname": "workflow_state",
						"label": "Workflow State",
						"fieldtype": "Link",
						"options": "Workflow State",
					}
				]
			}
		)
	for name in ("QA PO Receipt Draft", "QA PO Receipt Approved"):
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": name}).insert()
	frappe.get_doc(
		{"doctype": "Workflow Action Master", "workflow_action_name": "QA Approve Receipt"}
	).insert()
	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": "QA PO Receipt Workflow",
			"document_type": "Purchase Receipt",
			"is_active": 1,
			"workflow_state_field": "workflow_state",
			"states": [
				{"state": "QA PO Receipt Draft", "doc_status": 0, "allow_edit": "System Manager"},
				{"state": "QA PO Receipt Approved", "doc_status": 1, "allow_edit": "System Manager"},
			],
			"transitions": [
				{
					"state": "QA PO Receipt Draft",
					"action": "QA Approve Receipt",
					"next_state": "QA PO Receipt Approved",
					"allowed": "System Manager",
					"allow_self_approval": 1,
				}
			],
		}
	).insert()
	frappe.clear_cache()
	po = order()
	saved = receipt(po)
	assert not saved.get("failed"), saved
	doc = saved["document"]
	assert doc["docstatus"] == 0 and saved["allowed_actions"] == ["QA Approve Receipt"], saved
	approved = actions.record_receipt(
		po.name,
		{},
		str(uuid.uuid4()),
		target_name=doc["name"],
		expected_modified=doc["modified"],
		workflow_action="QA Approve Receipt",
	)
	assert not approved.get("failed"), approved
	assert approved["document"]["docstatus"] == 1
	assert (
		frappe.db.get_value("Bin", {"item_code": "QA-PO-ITEM", "warehouse": "Stores - QAB"}, "actual_qty")
		== 4
	)


def execute():
	guard()
	results = []
	for case in (
		chain,
		reject_draft_order,
		reject_missing_asset,
		reject_overpayment,
		continue_advance_draft,
		receipt_cancellation,
		advance_cancellation,
		permissions,
		source_pending,
		receipt_workflow,
	):
		try:
			result = case()
			results.append(case.__name__)
			print("PASSED", case.__name__, flush=True)
			if case is chain:
				print("NATIVE_CHAIN_EVIDENCE", json.dumps(result, ensure_ascii=False, default=str))
		finally:
			frappe.db.rollback()
			frappe.set_user("Administrator")
			frappe.clear_cache()
	print(json.dumps({"independent_scenarios": results, "status": "passed"}, ensure_ascii=False))


def committed_response_retry():
	"""Backend committed, response absent: replay the same request on current DB state."""
	guard()
	po = order()
	args = advance_args(po)
	first = actions.record_payment(**args)
	assert not first.get("failed"), first
	name = first["document"]["name"]
	frappe.db.commit()
	before = ledgers([name])
	replayed = actions.record_payment(**args)
	assert replayed.get("reused") and replayed["document"]["name"] == name
	assert before == ledgers([name]) and len(before["gl"]) == 2
	assert progress.get_order_progress([po.name])[po.name]["settled"] == 3000
	receipt_result = receipt(po)
	assert not receipt_result.get("failed"), receipt_result
	pr = receipt_result["document"]
	frappe.db.commit()
	remaining = actions.preview_document("Purchase Order", po.name, "Purchase Receipt")["document"]
	assert remaining["items"][0]["max_qty"] == 6
	too_much = actions.record_receipt(
		po.name, {"items": [{"key": remaining["items"][0]["key"], "qty": 7}]}, str(uuid.uuid4())
	)
	assert too_much.get("failed") and "数量" in too_much["error"], too_much
	assert frappe.db.get_value("Purchase Order", po.name, "per_received") == 40
	assert (
		frappe.db.get_value("Bin", {"item_code": "QA-PO-ITEM", "warehouse": "Stores - QAB"}, "actual_qty")
		== 4
	)
	# Cancel committed QA documents so other UI samples start at zero physical stock.
	frappe.get_doc("Purchase Receipt", pr["name"]).cancel()
	frappe.get_doc("Payment Entry", name).cancel()
	frappe.db.commit()
	print(
		json.dumps(
			{
				"committed_response_retry": "passed",
				"unique_gl_rows": 2,
				"receipt_current_remaining": 6,
				"overflow_rejected": True,
				"order": po.name,
				"payment": name,
				"receipt": pr["name"],
			}
		)
	)
