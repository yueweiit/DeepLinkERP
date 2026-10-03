"""Idempotent metadata-only patch; never backfills or submits business documents."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from mes_integration.mes_integration.request_category import CATEGORIES, FIELDNAME


def execute():
	create_custom_fields({"Material Request": [{
		"fieldname": FIELDNAME,
		"fieldtype": "Select",
		"insert_after": "custom_odt",
		"label": "MES申请类别",
		"options": "\n" + "\n".join(CATEGORIES),
		"read_only": 1,
		"no_copy": 1,
		"allow_on_submit": 1,
		"in_list_view": 1,
		"in_standard_filter": 1,
	}],}, update=True)
	frappe.clear_cache(doctype="Material Request")
