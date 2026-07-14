import frappe


def execute():
	for fieldname in ("custom_shipment_details_tab", "custom_shipment_details_html"):
		field_name = frappe.db.get_value(
			"Custom Field",
			{"dt": "Sales Order", "fieldname": fieldname},
		)
		if field_name:
			frappe.delete_doc("Custom Field", field_name, ignore_permissions=True)

	frappe.clear_cache(doctype="Sales Order")
