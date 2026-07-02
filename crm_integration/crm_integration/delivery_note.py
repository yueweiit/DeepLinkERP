import frappe
from frappe import _

from crm_integration.crm_integration.settings import is_crm_integration_enabled
from crm_integration.crm_integration.sales_order import (
	DELIVERABLE,
	PENDING_FINAL_PAYMENT,
	PENDING_PRODUCTION,
	set_process_status,
)


COMPLETED = "Completed"
DRAFT_ALLOWED_STATUSES = (PENDING_PRODUCTION, PENDING_FINAL_PAYMENT, DELIVERABLE)


def validate_sales_order_process_status(doc, method=None):
	if not is_crm_integration_enabled(doc.get("company")):
		return

	validate_linked_sales_orders_in_statuses(
		doc,
		DRAFT_ALLOWED_STATUSES,
		_("以下销售订单状态不允许创建或保存销售出库草稿：<br>{0}"),
	)


def validate_sales_order_deliverable_before_submit(doc, method=None):
	if not is_crm_integration_enabled(doc.get("company")):
		return

	validate_linked_sales_orders_in_statuses(
		doc,
		(DELIVERABLE,),
		_("以下销售订单未放行发货，不能提交销售出库：<br>{0}"),
	)


def set_pending_final_payment_before_insert(doc, method=None):
	if not is_crm_integration_enabled(doc.get("company")):
		return

	for sales_order in get_linked_sales_orders(doc):
		process_status = frappe.db.get_value("Sales Order", sales_order, "custom_process_status")
		if process_status == PENDING_PRODUCTION:
			set_process_status(frappe.get_doc("Sales Order", sales_order), PENDING_FINAL_PAYMENT)


def rollback_pending_final_payment_on_trash(doc, method=None):
	if not is_crm_integration_enabled(doc.get("company")):
		return

	if doc.docstatus != 0:
		return

	for sales_order in get_linked_sales_orders(doc):
		process_status = frappe.db.get_value("Sales Order", sales_order, "custom_process_status")
		if process_status != PENDING_FINAL_PAYMENT:
			continue

		if has_other_draft_delivery_note(sales_order, doc.name):
			continue

		set_process_status(frappe.get_doc("Sales Order", sales_order), PENDING_PRODUCTION)


def mark_sales_orders_completed_on_submit(doc, method=None):
	if not is_crm_integration_enabled(doc.get("company")):
		return

	sales_orders = get_linked_sales_orders(doc)
	if not sales_orders:
		return

	for sales_order in sales_orders:
		frappe.db.set_value(
			"Sales Order",
			sales_order,
			"custom_process_status",
			COMPLETED,
			update_modified=True,
		)

	frappe.logger().info(
		f"Delivery Note {doc.name} submitted; marked Sales Orders completed: {', '.join(sales_orders)}"
	)


def validate_linked_sales_orders_in_statuses(doc, allowed_statuses, message_template):
	sales_orders = get_linked_sales_orders(doc)
	if not sales_orders:
		return

	invalid_orders = frappe.get_all(
		"Sales Order",
		filters={
			"name": ["in", sales_orders],
			"custom_process_status": ["not in", allowed_statuses],
		},
		fields=["name", "custom_process_status"],
		order_by="name asc",
	)

	if invalid_orders:
		messages = [
			_("{0}: {1}").format(order.name, order.custom_process_status or "")
			for order in invalid_orders
		]
		frappe.throw(message_template.format("<br>".join(messages)))


def get_linked_sales_orders(doc):
	return sorted(
		{
			item.against_sales_order
			for item in doc.get("items", [])
			if item.get("against_sales_order")
		}
	)


def has_other_draft_delivery_note(sales_order, current_delivery_note):
	return frappe.db.sql(
		"""
		SELECT dni.name
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_sales_order = %s
			AND dn.name != %s
			AND dn.docstatus = 0
		LIMIT 1
		""",
		(sales_order, current_delivery_note),
	)
