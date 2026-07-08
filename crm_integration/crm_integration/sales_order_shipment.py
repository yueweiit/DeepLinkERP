from io import BytesIO

import frappe
import xlsxwriter
from frappe import _
from frappe.utils import flt
from frappe.utils.xlsxutils import make_xlsx


@frappe.whitelist()
def get_sales_order_shipment_details(sales_order):
	validate_sales_order_read_permission(sales_order)

	summary = get_sales_order_shipment_summary(sales_order)
	delivery_notes = get_sales_order_delivery_note_details(sales_order)
	return {"summary": summary, "delivery_notes": delivery_notes}


@frappe.whitelist()
def export_sales_order_shipment_details(sales_order):
	data = get_sales_order_shipment_details(sales_order)

	summary_data = [
		[
			_("物料编码"),
			_("物料名称"),
			_("订单数量"),
			_("已出货数量"),
			_("未出货数量"),
			_("单位"),
		]
	]
	for row in data["summary"]:
		summary_data.append(
			[
				row.get("item_code"),
				row.get("item_name"),
				row.get("ordered_qty"),
				row.get("delivered_qty"),
				row.get("remaining_qty"),
				row.get("uom"),
			]
		)

	detail_data = [
		[
			_("销售出库单"),
			_("过账日期"),
			_("物料编码"),
			_("物料名称"),
			_("出库数量"),
			_("单位"),
		]
	]
	for row in data["delivery_notes"]:
		detail_data.append(
			[
				row.get("delivery_note"),
				row.get("posting_date"),
				row.get("item_code"),
				row.get("item_name"),
				row.get("qty"),
				row.get("uom"),
			]
		)

	xlsx_file = BytesIO()
	workbook = xlsxwriter.Workbook(xlsx_file, {"constant_memory": True})
	make_xlsx(summary_data, _("汇总"), wb=workbook, column_widths=[18, 28, 14, 14, 14, 12])
	make_xlsx(detail_data, _("明细"), wb=workbook, column_widths=[22, 14, 18, 28, 14, 12])
	workbook.close()
	xlsx_file.seek(0)

	frappe.local.response.filename = f"shipment_details_{sales_order}.xlsx"
	frappe.local.response.filecontent = xlsx_file.getvalue()
	frappe.local.response.type = "download"


def validate_sales_order_read_permission(sales_order):
	if not sales_order or not frappe.db.exists("Sales Order", sales_order):
		frappe.throw(_("未找到销售订单 {0}").format(sales_order or ""))

	if not frappe.has_permission("Sales Order", "read", doc=sales_order):
		frappe.throw(_("缺少 Sales Order 读取权限"), frappe.PermissionError)


def get_sales_order_shipment_summary(sales_order):
	so_items = get_sales_order_items(sales_order)
	delivered_by_so_detail = get_delivered_qty_by_so_detail(sales_order)
	summary = []

	for item in so_items:
		ordered_qty = flt(item.stock_qty or item.qty)
		delivered_qty = max(flt(delivered_by_so_detail.get(item.name, 0)), 0)
		remaining_qty = max(ordered_qty - delivered_qty, 0)
		summary.append(
			{
				"so_detail": item.name,
				"item_code": item.item_code,
				"item_name": item.item_name,
				"ordered_qty": ordered_qty,
				"delivered_qty": delivered_qty,
				"remaining_qty": remaining_qty,
				"uom": item.stock_uom if flt(item.stock_qty) else item.uom,
			}
		)

	return summary


def get_sales_order_items(sales_order):
	return frappe.get_all(
		"Sales Order Item",
		filters={"parent": sales_order},
		fields=["name", "item_code", "item_name", "qty", "stock_qty", "uom", "stock_uom"],
		order_by="idx asc",
	)


def get_delivered_qty_by_so_detail(sales_order):
	rows = frappe.db.sql(
		"""
		SELECT
			dni.so_detail,
			SUM(
				CASE
					WHEN dn.is_return = 1 THEN -ABS(COALESCE(NULLIF(dni.stock_qty, 0), dni.qty, 0))
					ELSE COALESCE(NULLIF(dni.stock_qty, 0), dni.qty, 0)
				END
			) AS delivered_qty
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_sales_order = %s
			AND dn.docstatus = 1
			AND IFNULL(dni.so_detail, '') != ''
		GROUP BY dni.so_detail
		""",
		(sales_order,),
		as_dict=True,
	)
	return {row.so_detail: flt(row.delivered_qty) for row in rows}


def get_sales_order_delivery_note_details(sales_order):
	rows = frappe.db.sql(
		"""
		SELECT
			dn.name AS delivery_note,
			dn.posting_date,
			dn.creation,
			dn.is_return,
			dni.item_code,
			dni.item_name,
			dni.so_detail,
			CASE
				WHEN dn.is_return = 1 THEN -ABS(COALESCE(NULLIF(dni.stock_qty, 0), dni.qty, 0))
				ELSE COALESCE(NULLIF(dni.stock_qty, 0), dni.qty, 0)
			END AS qty,
			CASE
				WHEN COALESCE(dni.stock_qty, 0) != 0 THEN dni.stock_uom
				ELSE dni.uom
			END AS uom
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_sales_order = %s
			AND dn.docstatus = 1
		ORDER BY dn.posting_date DESC, dn.creation DESC, dni.idx ASC
		""",
		(sales_order,),
		as_dict=True,
	)

	return [row for row in rows if frappe.has_permission("Delivery Note", "read", doc=row.delivery_note)]
