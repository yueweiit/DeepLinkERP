"""Preserve accounting-date order when the list view submits selected vouchers."""

import json

import frappe


def sort_voucher_names(doctype, names):
	if isinstance(names, str):
		names = frappe.parse_json(names)
	date_field = {
		"Journal Entry": "posting_date",
		"Payment Entry": "posting_date",
		"Period Closing Voucher": "period_end_date",
	}.get(doctype)
	if not date_field or not names or len(names) > 500:
		return names
	# Keep missing documents in the request so the native operation still
	# reports them. Submission/workflow permissions remain the native checks.
	ordered = frappe.get_all(
		doctype, filters={"name": ["in", names]}, pluck="name",
		order_by=f"{date_field} asc, creation asc, name asc",
	)
	position = {name: index for index, name in enumerate(ordered)}
	return sorted(names, key=lambda name: position.get(name, len(position)))


@frappe.whitelist()
def submit_cancel_or_update_docs(doctype, docnames, action="submit", data=None, task_id=None):
	from frappe.desk.doctype.bulk_update.bulk_update import submit_cancel_or_update_docs as native

	if action == "submit":
		docnames = sort_voucher_names(doctype, docnames)
	return native(doctype, docnames, action=action, data=data, task_id=task_id)


@frappe.whitelist()
def bulk_workflow_approval(docnames, doctype, action):
	from frappe.model.workflow import bulk_workflow_approval as native

	# The native method expects JSON even when invoked from another Python function.
	return native(json.dumps(sort_voucher_names(doctype, docnames)), doctype, action)
