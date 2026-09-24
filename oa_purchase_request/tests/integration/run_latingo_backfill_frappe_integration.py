"""Rollback-only production-shape integration rehearsal for the LatinGo backfill.

Run with::

    bench --site <site> execute \
      oa_purchase_request.tests.integration.run_latingo_backfill_frappe_integration.run

The function always rolls back its savepoint and therefore never retains the
temporary OA requests, master data or purchase orders it creates.
"""

from __future__ import annotations

import frappe

from oa_purchase_request import latingo_backfill as service
from oa_purchase_request.latingo_backfill_domain import LATINGO_COMPANY


START_DATE = "2026-07-01"
END_DATE = "2026-09-24"


def _assert(condition, message):
	if not condition:
		raise AssertionError(message)


def _counts():
	return {
		"oa": frappe.db.count("OA Purchase Request"),
		"latingo_po": frappe.db.count("Purchase Order", {"company": LATINGO_COMPANY}),
		"other_po": frappe.db.count("Purchase Order", {"company": ["!=", LATINGO_COMPANY]}),
		"purchase_receipt": frappe.db.count("Purchase Receipt"),
	}


def _assert_preview(preview):
	expected = {
		"scanned": 46,
		"eligible": 37,
		"excluded": 9,
		"completed": 30,
		"running": 7,
		"physical_orders": 13,
		"service_orders": 24,
		"CNY": 16,
		"MXN": 21,
	}
	_assert(preview["counts"] == expected, f"preview counts differ: {preview['counts']}")
	_assert(not preview["conflicts"], f"preview conflicts: {preview['conflicts']}")
	_assert(sum(row["action"] == "create" for row in preview["item_actions"]) == 23, "expected 20 goods + 3 services")
	_assert(sum(row["action"] == "update_ownership" for row in preview["item_actions"]) == 9, "expected nine ownership updates")


def _assert_created_documents(created):
	_assert(len(created) == 37, "expected 37 created source pairs")
	oa_names = [row["oa_request"] for row in created]
	po_names = [row["purchase_order"] for row in created]
	_assert(len(set(oa_names)) == 37 and len(set(po_names)) == 37, "source pairs must be one-to-one")

	oas = frappe.get_all(
		"OA Purchase Request",
		filters={"name": ["in", oa_names]},
		fields=[
			"name",
			"purchase_order",
			"approval_status",
			"source_pending",
			"exchange_rate_pending",
			"price_pending",
			"target_company",
			"sync_status",
		],
		limit_page_length=100,
	)
	_assert(len(oas) == 37, "expected 37 OA Purchase Request documents")
	_assert(all(row.target_company == LATINGO_COMPANY for row in oas), "all OA requests must target LatinGo")
	_assert(all(row.sync_status == "已建草稿" for row in oas), "all OA requests must link a draft")
	_assert(sum(bool(row.source_pending) for row in oas) == 7, "expected seven running approvals")
	_assert(sum(bool(row.exchange_rate_pending) for row in oas) == 21, "expected 21 MXN reviews")
	_assert(sum(bool(row.price_pending) for row in oas) == 1, "expected one price review")

	pos = frappe.get_all(
		"Purchase Order",
		filters={"name": ["in", po_names]},
		fields=[
			"name",
			"docstatus",
			"company",
			"currency",
			"conversion_rate",
			"transaction_date",
			"schedule_date",
			"custom_latingo_source_pending",
			"custom_latingo_exchange_rate_pending",
			"custom_latingo_price_pending",
		],
		limit_page_length=100,
	)
	_assert(len(pos) == 37 and all(row.docstatus == 0 for row in pos), "all 37 purchase orders must be drafts")
	_assert(all(row.company == LATINGO_COMPANY for row in pos), "all purchase orders must target LatinGo")
	_assert(sum(row.currency == "CNY" for row in pos) == 16, "expected 16 CNY orders")
	_assert(sum(row.currency == "MXN" for row in pos) == 21, "expected 21 MXN orders")
	_assert(all(float(row.conversion_rate) == (0.39 if row.currency == "MXN" else 1.0) for row in pos), "exchange rates differ")
	_assert(all(row.schedule_date >= row.transaction_date for row in pos), "schedule date may not precede order date")

	tax_po = frappe.db.get_value(
		"OA Purchase Request",
		"202608241502000513674",
		"purchase_order",
	)
	tax_doc = frappe.get_doc("Purchase Order", tax_po)
	_assert(float(tax_doc.net_total) == 13200 and float(tax_doc.grand_total) == 13332, "tax order total does not reconcile")
	_assert(len(tax_doc.taxes) == 1 and tax_doc.taxes[0].charge_type == "Actual", "expected one Actual tax row")

	playo_po = frappe.db.get_value("OA Purchase Request", "202608180748000045053", "purchase_order")
	playo_doc = frappe.get_doc("Purchase Order", playo_po)
	_assert(len(playo_doc.items) == 1, "PLAYO order should have one line")
	_assert(playo_doc.items[0].item_code == "PLAYO", "PLAYO code changed")
	_assert(float(playo_doc.items[0].qty) == 32 and float(playo_doc.items[0].rate) == 0, "PLAYO quantity/rate changed")

	service_pos = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": ["in", po_names], "item_code": ["like", "LGO-SVC-%"]},
		fields=["parent", "warehouse"],
		limit_page_length=100,
	)
	_assert(len(service_pos) == 24 and all(not row.warehouse for row in service_pos), "service rows must not use a warehouse")


def run():
	"""Execute source drift, rollback, one-to-one and repeat-run checks."""

	frappe.set_user("Administrator")
	baseline = _counts()
	preview = service.preview_latingo_purchase_backfill(START_DATE, END_DATE)
	_assert_preview(preview)

	try:
		service.apply_latingo_purchase_backfill(START_DATE, END_DATE, "stale-fingerprint")
	except ValueError as exc:
		_assert("预览指纹已变化" in str(exc), "stale preview must be rejected")
	else:
		raise AssertionError("stale preview fingerprint was accepted")
	_assert(_counts() == baseline, "stale fingerprint attempt changed data")

	frappe.db.savepoint("latingo_integration_outer")
	original_create = service._create_backfill_pair
	created_calls = 0

	def fail_second(plan):
		nonlocal created_calls
		created_calls += 1
		if created_calls == 2:
			raise RuntimeError("intentional integration rollback")
		return original_create(plan)

	service._create_backfill_pair = fail_second
	try:
		failed = service.apply_latingo_purchase_backfill(START_DATE, END_DATE, preview["fingerprint"])
	finally:
		service._create_backfill_pair = original_create
	_assert(not failed["ok"] and failed["created"] == [], "failed batch must return zero created rows")
	_assert(_counts() == baseline, "failed batch did not roll back completely")

	try:
		result = service.apply_latingo_purchase_backfill(START_DATE, END_DATE, preview["fingerprint"])
		_assert(result["ok"] and not result["failed"], f"rehearsal failed: {result}")
		_assert_created_documents(result["created"])
		after_create = _counts()
		_assert(after_create["oa"] == baseline["oa"] + 37, "OA count changed by other than 37")
		_assert(after_create["latingo_po"] == baseline["latingo_po"] + 37, "LatinGo PO count changed by other than 37")
		_assert(after_create["other_po"] == baseline["other_po"], "other-company PO count changed")
		_assert(after_create["purchase_receipt"] == baseline["purchase_receipt"], "purchase receipt was created")

		repeat_preview = service.preview_latingo_purchase_backfill(START_DATE, END_DATE)
		repeat = service.apply_latingo_purchase_backfill(START_DATE, END_DATE, repeat_preview["fingerprint"])
		_assert(repeat["created"] == [] and len(repeat["reused"]) == 37, "repeat run was not idempotent")

		manual_po = result["created"][0]["purchase_order"]
		manual_item = frappe.db.get_value("Purchase Order Item", {"parent": manual_po}, ["name", "rate"], as_dict=True)
		manual_rate = float(manual_item.rate) + 1
		frappe.db.set_value("Purchase Order Item", manual_item.name, "rate", manual_rate, update_modified=False)
		service.refresh_oa_purchase_source(result["created"][0]["oa_request"])
		_assert(float(frappe.db.get_value("Purchase Order Item", manual_item.name, "rate")) == manual_rate, "refresh overwrote a manual rate")

		return {
			"ok": True,
			"preview_counts": preview["counts"],
			"created_count": len(result["created"]),
			"repeat_reused_count": len(repeat["reused"]),
			"rollback_verified": True,
			"manual_edit_preserved": True,
		}
	finally:
		frappe.db.rollback(save_point="latingo_integration_outer")
		_assert(_counts() == baseline, "outer rehearsal rollback did not restore baseline")
