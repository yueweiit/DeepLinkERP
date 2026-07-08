import frappe
from frappe import _
from frappe.utils import flt

from crm_integration.crm_integration.settings import is_crm_integration_enabled
from crm_integration.crm_integration.sales_order import (
	CRM_STATUS_SHIPMENT_CREATED,
	DELIVERABLE,
	PENDING_FINAL_PAYMENT,
	PENDING_PRODUCTION,
	enqueue_sales_order_status_to_crm,
	set_process_status,
)


COMPLETED = "Completed"
PARTIALLY_DELIVERED = "Partially Delivered"
DRAFT_ALLOWED_STATUSES = (PENDING_PRODUCTION, PENDING_FINAL_PAYMENT, DELIVERABLE, PARTIALLY_DELIVERED)


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

	if is_delivery_note_marked_ready_to_deliver(doc):
		return

	validate_linked_sales_orders_in_statuses(
		doc,
		(DELIVERABLE, PARTIALLY_DELIVERED),
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
	update_sales_orders_delivery_process_status(doc)


def update_sales_orders_delivery_process_status_on_cancel(doc, method=None):
	update_sales_orders_delivery_process_status(doc)


def update_sales_orders_delivery_process_status(doc):
	if not is_crm_integration_enabled(doc.get("company")):
		return

	sales_orders = get_linked_sales_orders(doc)
	if not sales_orders:
		return

	updated_statuses = []
	for sales_order_name in sales_orders:
		sales_order = frappe.get_doc("Sales Order", sales_order_name)
		process_status = get_sales_order_delivery_process_status(sales_order_name)
		set_process_status(sales_order, process_status)
		updated_statuses.append(f"{sales_order_name}: {process_status}")
		if doc.docstatus == 1:
			enqueue_crm_delivery_note_shipment_event(
				doc, sales_order_name, process_status
			)

	frappe.logger().info(
		f"Delivery Note {doc.name} updated Sales Order delivery process statuses: {', '.join(updated_statuses)}"
	)
	if doc.docstatus in (1, 2):
		enqueue_mes_delivery_note_status_callback(doc.name)


def enqueue_crm_delivery_note_shipment_event(doc, sales_order_name, process_status):
	items = get_delivery_note_shipment_items(doc, sales_order_name)
	if not items:
		return

	try:
		enqueue_sales_order_status_to_crm(
			sales_order_name=sales_order_name,
			external_status=CRM_STATUS_SHIPMENT_CREATED,
			triggered_status=process_status,
			trigger_event="delivery_note_submitted",
			delivery_note_name=doc.name,
			items=items,
			remark=get_delivery_note_shipment_remark(
				doc.name, sales_order_name, process_status
			),
		)
	except Exception:
		frappe.log_error(
			title="Failed to enqueue CRM Delivery Note shipment event",
			message=frappe.get_traceback(),
		)


def get_delivery_note_shipment_remark(delivery_note_name, sales_order_name, process_status):
	if process_status == COMPLETED:
		return "全部发货"

	shipment_count = get_submitted_delivery_note_count(sales_order_name, delivery_note_name)
	return f"第{shipment_count}次部分发货"


def get_submitted_delivery_note_count(sales_order_name, current_delivery_note):
	rows = frappe.db.sql(
		"""
		SELECT COUNT(DISTINCT dn.name) AS delivery_note_count
		FROM `tabDelivery Note` dn
		INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		INNER JOIN `tabDelivery Note` current_dn ON current_dn.name = %s
		WHERE dn.docstatus = 1
			AND dni.against_sales_order = %s
			AND dn.creation <= current_dn.creation
		""",
		(current_delivery_note, sales_order_name),
		as_dict=True,
	)
	return max(int(rows[0].delivery_note_count if rows else 0), 1)


def get_delivery_note_shipment_items(doc, sales_order_name):
	qty_by_item = {}
	for row in doc.get("items", []):
		if row.get("against_sales_order") != sales_order_name:
			continue

		item_code = row.get("item_code")
		quantity = flt(row.get("stock_qty") or row.get("qty"))
		if not item_code or quantity <= 0:
			continue

		qty_by_item[item_code] = flt(qty_by_item.get(item_code)) + quantity

	return [
		{"externalItemId": item_code, "quantity": quantity}
		for item_code, quantity in sorted(qty_by_item.items())
	]


def enqueue_mes_delivery_note_status_callback(delivery_note_name):
	try:
		from mes_integration.mes_integration.delivery_note import (
			enqueue_delivery_note_status_callback,
		)

		enqueue_delivery_note_status_callback(delivery_note_name)
	except Exception:
		frappe.log_error(
			title="Failed to enqueue MES Delivery Note status callback",
			message=frappe.get_traceback(),
		)


def get_sales_order_delivery_process_status(sales_order_name):
	items = get_sales_order_item_quantities(sales_order_name)
	if not items:
		return DELIVERABLE

	delivered_qty_by_so_detail = get_delivered_qty_by_sales_order_item(sales_order_name)
	has_delivered_qty = False
	all_items_delivered = True
	for item in items:
		ordered_qty = item.stock_qty or item.qty or 0
		delivered_qty = delivered_qty_by_so_detail.get(item.name, 0)
		if delivered_qty > 0:
			has_delivered_qty = True
		if delivered_qty + 0.000001 < ordered_qty:
			all_items_delivered = False

	if all_items_delivered:
		return COMPLETED

	return PARTIALLY_DELIVERED if has_delivered_qty else DELIVERABLE


def get_sales_order_item_quantities(sales_order_name):
	return frappe.get_all(
		"Sales Order Item",
		filters={"parent": sales_order_name},
		fields=["name", "qty", "stock_qty"],
		order_by="idx asc",
	)


def get_delivered_qty_by_sales_order_item(sales_order_name):
	rows = frappe.db.sql(
		"""
		SELECT
			dni.so_detail,
			SUM(
				CASE
					WHEN dn.is_return = 1 THEN -ABS(COALESCE(dni.stock_qty, dni.qty, 0))
					ELSE COALESCE(dni.stock_qty, dni.qty, 0)
				END
			) AS delivered_qty
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_sales_order = %s
			AND dn.docstatus = 1
			AND IFNULL(dni.so_detail, '') != ''
		GROUP BY dni.so_detail
		""",
		(sales_order_name,),
		as_dict=True,
	)
	return {row.so_detail: max(row.delivered_qty or 0, 0) for row in rows}


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


def is_delivery_note_marked_ready_to_deliver(doc):
	if not frappe.db.has_column("Delivery Note", "custom_delivery_readiness_status"):
		return False

	return doc.get("custom_delivery_readiness_status") == "Ready to Deliver"


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
