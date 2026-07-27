import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Delivery Note": [
				{
					"fieldname": "custom_delivery_readiness_status",
					"fieldtype": "Select",
					"insert_after": "status",
					"label": "发货放行状态",
					"options": "\nPending Release\nReady to Deliver\nDelivered",
					"read_only": 1,
					"no_copy": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
				},
			]
		},
		update=True,
	)

	frappe.clear_cache(doctype="Delivery Note")
	backfill_delivery_note_readiness_status()


def backfill_delivery_note_readiness_status():
	if not frappe.db.has_column("Delivery Note", "custom_delivery_readiness_status"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabDelivery Note` dn
		SET dn.custom_delivery_readiness_status = NULL
		WHERE dn.docstatus NOT IN (0, 1)
		"""
	)

	# CRM owns this field. During a fresh multi-app migrate, MES may run
	# before CRM has created it; the next migrate will complete this update.
	if not frappe.db.has_column("Sales Order", "custom_process_status"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabDelivery Note` dn
		SET dn.custom_delivery_readiness_status = 'Delivered'
		WHERE dn.docstatus = 1
			AND EXISTS (
				SELECT 1
				FROM `tabDelivery Note Item` dni
				WHERE dni.parent = dn.name
					AND IFNULL(dni.against_sales_order, '') != ''
			)
		"""
	)

	frappe.db.sql(
		"""
		UPDATE `tabDelivery Note` dn
		SET dn.custom_delivery_readiness_status = 'Pending Release'
		WHERE dn.docstatus = 0
			AND EXISTS (
				SELECT 1
				FROM `tabDelivery Note Item` dni
				WHERE dni.parent = dn.name
					AND IFNULL(dni.against_sales_order, '') != ''
			)
		"""
	)

	frappe.db.sql(
		"""
		UPDATE `tabDelivery Note` dn
		SET dn.custom_delivery_readiness_status = 'Ready to Deliver'
		WHERE dn.docstatus = 0
			AND EXISTS (
				SELECT 1
				FROM `tabDelivery Note Item` dni
				WHERE dni.parent = dn.name
					AND IFNULL(dni.against_sales_order, '') != ''
			)
			AND NOT EXISTS (
				SELECT 1
				FROM `tabDelivery Note Item` dni
				INNER JOIN `tabSales Order` so ON so.name = dni.against_sales_order
				WHERE dni.parent = dn.name
					AND IFNULL(dni.against_sales_order, '') != ''
					AND IFNULL(so.custom_process_status, '') != 'Deliverable'
			)
		"""
	)
