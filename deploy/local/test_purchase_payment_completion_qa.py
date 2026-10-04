"""Native completion scenarios on the dedicated synthetic QA database, always rollback."""

import hashlib
import json
import uuid
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
from frappe.utils import add_days, nowdate

from deeplinkerp_branding.services import purchase_document_actions as actions
from deeplinkerp_branding.services import purchase_payment_service as service

SITE = "po-grid-qa.localhost"
HOST = "dlp-payment-ux-db-20261005"
COMPANY = "QA Second Company"
TYPES = (
	"Purchase Order",
	"Purchase Receipt",
	"Purchase Invoice",
	"Payment Entry",
	"GL Entry",
	"Payment Ledger Entry",
	"China Accounting Voucher",
	"Workflow",
	"Workflow State",
	"Workflow Action Master",
	"Custom DocPerm",
	"Role",
	"User",
)


def seed():
	po = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"company": COMPANY,
			"supplier": "QA Test Supplier",
			"currency": "CNY",
			"schedule_date": add_days(nowdate(), 1),
			"items": [
				{"item_code": "QA-PO-ITEM", "qty": 10, "rate": 1000, "schedule_date": add_days(nowdate(), 1)}
			],
		}
	).insert()
	po.submit()
	pr = make_purchase_receipt(po.name)
	pr.items[0].qty = 4
	pr.insert()
	pr.submit()
	pi = make_purchase_invoice(pr.name)
	pi.insert()
	pi.submit()
	args = dict(
		source_doctype="Purchase Receipt",
		source_name=pr.name,
		purchase_invoice=pi.name,
		amount_to_pay=3000,
		bank_account="Cash - QAB",
		request_id=str(uuid.uuid4()),
	)
	return po, pr, pi, args


def direct():
	_, pr, pi, args = seed()
	result = actions.record_payment(**args)
	name = result["document"]["name"]
	assert result["document"]["docstatus"] == 1
	assert actions.record_payment(**args)["document"]["name"] == name
	assert frappe.db.count("Payment Entry", {"name": name}) == 1
	assert frappe.db.count("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": name}) == 2
	assert service.get_purchase_chain("Purchase Receipt", pr.name)["balances"][0]["outstanding"] == 1000
	second = actions.record_payment(**dict(args, amount_to_pay=1000, request_id=str(uuid.uuid4())))
	assert second["document"]["docstatus"] == 1
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 0
	rows = service.get_payment_records(purchase_receipt=pr.name)["rows"]
	assert {row["name"] for row in rows} == {name, second["document"]["name"]}
	assert all(row["docstatus"] == 1 and row["references"][0]["name"] == pi.name for row in rows)
	assert actions.record_payment(**dict(args, amount_to_pay=1, request_id=str(uuid.uuid4())))["failed"]


def existing():
	_, _, pi, args = seed()
	draft = actions.record_payment(**dict(args, confirm=0))["document"]
	assert draft["docstatus"] == 0
	assert not frappe.db.count("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": draft["name"]})
	review = actions.record_payment(**dict(args, amount_to_pay=500, request_id=str(uuid.uuid4())))
	assert review["needs_review"] and review["document"]["name"] == draft["name"]
	assert review["document"]["amount"] == 3000, "Different input must not overwrite the business draft"
	complete = dict(
		name=draft["name"],
		changes={"amount": 1200, "remarks": "QA completion"},
		expected_modified=draft["modified"],
		request_id=str(uuid.uuid4()),
	)
	result = actions.complete_payment(**complete)
	assert result["document"]["docstatus"] == 1 and result["document"]["amount"] == 1200
	assert actions.complete_payment(**complete)["document"]["name"] == draft["name"]
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 2800
	try:
		actions.complete_payment(**dict(complete, changes={"amount": 1500}))
	except frappe.ValidationError:
		pass
	else:
		raise AssertionError("Changed retry payload accepted")


def failure():
	_, _, _, args = seed()
	original = PaymentEntry.on_submit

	def failed(doc):
		original(doc)
		raise frappe.ValidationError("QA native submit failure after posting")

	with patch.object(PaymentEntry, "on_submit", failed):
		result = actions.record_payment(**args)
		assert result["failed"] and "QA native submit failure" in result["error"]
	return args


def workflow():
	_, _, pi, args = seed()
	assert frappe.get_meta("Payment Entry").has_field("status")
	for state in ("Draft", "Submitted"):
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert()
	if not frappe.db.exists("Workflow Action Master", "Submit"):
		frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": "Submit"}).insert()
	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": "QA UX Payment Approval",
			"document_type": "Payment Entry",
			"is_active": 1,
			"workflow_state_field": "status",
			"states": [
				{"state": "Draft", "doc_status": 0, "allow_edit": "System Manager"},
				{"state": "Submitted", "doc_status": 1, "allow_edit": "System Manager"},
			],
			"transitions": [
				{
					"state": "Draft",
					"action": "Submit",
					"next_state": "Submitted",
					"allowed": "System Manager",
					"allow_self_approval": 1,
				}
			],
		}
	).insert()
	frappe.cache.hdel("workflow", "Payment Entry")
	pending = actions.record_payment(**args)
	doc = pending["document"]
	assert doc["docstatus"] == 0 and pending["allowed_actions"] == ["Submit"]
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 4000
	done = actions.complete_payment(
		name=doc["name"],
		changes={},
		expected_modified=doc["modified"],
		request_id=str(uuid.uuid4()),
		workflow_action="Submit",
	)
	assert done["document"]["docstatus"] == 1


def no_submit():
	_, _, _, args = seed()
	draft = actions.record_payment(**dict(args, confirm=0))["document"]
	role = "QA UX Payment Drafter"
	frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
	for doctype in (
		"Payment Entry",
		"Purchase Invoice",
		"Purchase Order",
		"Purchase Receipt",
		"Company",
		"Account",
		"Supplier",
	):
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": doctype,
				"role": role,
				"permlevel": 0,
				"read": 1,
				"write": int(doctype == "Payment Entry"),
				"create": int(doctype == "Payment Entry"),
				"submit": 0,
			}
		).insert()
		frappe.clear_cache(doctype=doctype)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": "qa-ux-drafter@example.invalid",
			"first_name": "QA UX",
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	).insert()
	frappe.set_user(user.name)
	preview = actions.preview_payment(draft["name"])
	assert preview["allowed_actions"] == [] and preview["document"]["docstatus"] == 0
	result = actions.complete_payment(
		name=draft["name"], changes={}, expected_modified=draft["modified"], request_id=str(uuid.uuid4())
	)
	assert result["document"]["docstatus"] == 0, "No-submit user must not post a native payment"


def multiple_drafts():
	_, _, _, args = seed()
	first = service.create_payment_draft(**args)
	second = service.create_payment_draft(**dict(args, amount_to_pay=500, request_id=str(uuid.uuid4())))
	before = {
		name: frappe.get_doc("Payment Entry", name).as_dict() for name in (first["name"], second["name"])
	}
	result = actions.record_payment(**dict(args, request_id=str(uuid.uuid4())))
	assert result["needs_review"] and result["document"]["docstatus"] == 0
	assert all(frappe.get_doc("Payment Entry", name).as_dict() == doc for name, doc in before.items())


def execute():
	if frappe.local.site != SITE or frappe.conf.db_host != HOST:
		raise RuntimeError("Dedicated synthetic QA database only")
	frappe.flags.in_test = True
	frappe.flags.mute_emails = True
	before = {doctype: frappe.db.count(doctype) for doctype in TYPES}
	results = []
	for case in (direct, existing, failure, workflow, no_submit, multiple_drafts):
		frappe.set_user("Administrator")
		try:
			args = case()
			results.append(case.__name__)
		finally:
			frappe.db.rollback()
			frappe.set_user("Administrator")
			frappe.clear_cache()
		assert {doctype: frappe.db.count(doctype) for doctype in TYPES} == before, (
			"QA transaction did not roll back"
		)
		if case is failure:
			key = (
				"dlp-purchase-draft:"
				+ hashlib.sha256((frappe.session.user + ":" + args["request_id"]).encode()).hexdigest()
			)
			assert not frappe.cache.get_value(key), "Rolled-back draft request was left cached"
	print(
		json.dumps(
			{
				"scenarios": results,
				"before": before,
				"after": {doctype: frappe.db.count(doctype) for doctype in TYPES},
			},
			ensure_ascii=False,
		)
	)


def execute_concurrency():
	"""Committed fixtures only on the disposable DB; restore its baseline after browser QA."""
	from concurrent.futures import ThreadPoolExecutor
	from threading import Barrier

	if frappe.local.site != SITE or frappe.conf.db_host != HOST:
		raise RuntimeError("Dedicated synthetic QA database only")
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	frappe.flags.mute_emails = True
	_, pr, pi, args = seed()
	frappe.db.commit()
	barrier = Barrier(4)

	def worker(request_id):
		frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		frappe.set_user("Administrator")
		frappe.flags.in_test = True
		frappe.flags.mute_emails = True
		try:
			barrier.wait(timeout=20)
			result = actions.record_payment(**dict(args, request_id=request_id))
			frappe.db.commit()
			return result
		except Exception as error:
			frappe.db.rollback()
			return {"failed": True, "error": type(error).__name__}
		finally:
			frappe.destroy()

	requests = [args["request_id"], args["request_id"], str(uuid.uuid4()), str(uuid.uuid4())]
	with ThreadPoolExecutor(max_workers=4) as pool:
		results = list(pool.map(worker, requests))
	frappe.db.rollback()
	refs = frappe.get_all(
		"Payment Entry Reference",
		filters={"reference_doctype": "Purchase Invoice", "reference_name": pi.name},
		pluck="parent",
	)
	payments = frappe.get_all(
		"Payment Entry", filters={"name": ["in", refs]}, fields=["name", "docstatus", "paid_amount"]
	)
	assert len(payments) == 1 and payments[0].docstatus == 1 and payments[0].paid_amount == 3000
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 1000
	assert frappe.db.count("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": payments[0].name}) == 2
	retry = actions.record_payment(**args)
	assert retry["document"]["name"] == payments[0].name
	print(
		json.dumps(
			{
				"concurrent_requests": 4,
				"unique_payments": 1,
				"native_gl_rows": 2,
				"outstanding": 1000,
				"results": results,
				"source": pr.name,
			},
			default=str,
			ensure_ascii=False,
		)
	)
