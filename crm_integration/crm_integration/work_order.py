import frappe
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def query_sales_order(doctype, txt, searchfield, start, page_len, filters):
	"""Return submitted Sales Orders available for Work Order creation."""
	filters = frappe._dict(filters or {})
	production_item = filters.get("production_item")
	company = filters.get("company")

	if not production_item:
		return []

	base_filters = [["Sales Order", "docstatus", "=", 1]]
	if company:
		base_filters.append(["Sales Order", "company", "=", company])
	base_filters.append(["Sales Order", "status", "not in", ["Closed", "On Hold"]])

	return frappe.get_list(
		"Sales Order",
		fields=["name"],
		filters=base_filters,
		or_filters=[
			["Sales Order Item", "item_code", "=", production_item],
			["Packed Item", "item_code", "=", production_item],
		],
		as_list=True,
		distinct=True,
	)

