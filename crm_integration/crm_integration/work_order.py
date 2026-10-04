import frappe
from crm_integration.crm_integration.finance_release import is_production_released
from crm_integration.crm_integration.settings import is_crm_integration_enabled


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def query_sales_order(doctype, txt, searchfield, start, page_len, filters):
	"""Reuse the native permission-aware item query, then apply the common release gate."""
	filters = frappe._dict(filters or {})
	if not filters.get("production_item"):
		return []
	base_filters = [["Sales Order", "docstatus", "=", 1], ["Sales Order", "status", "not in", ["Closed", "On Hold", "Stopped"]]]
	if filters.get("company"):
		base_filters.append(["Sales Order", "company", "=", filters.company])
	if txt:
		base_filters.append(["Sales Order", "name", "like", f"%{txt}%"])
	candidates = frappe.get_list("Sales Order", fields=["name", "company", "custom_process_status", "status", "docstatus"],
		filters=base_filters, or_filters=[["Sales Order Item", "item_code", "=", filters.production_item], ["Packed Item", "item_code", "=", filters.production_item]],
		distinct=True, limit_page_length=0, order_by="name asc")
	available = [(row.name,) for row in candidates if not is_crm_integration_enabled(row.company) or is_production_released(row)]
	return available[int(start or 0):int(start or 0) + int(page_len or 20)]
