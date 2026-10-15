"""Shared calculation layer for the Operations KPI dashboard and its drill-down reports."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, get_first_day, getdate, nowdate


KPI_ROLES = {
	"System Manager",
	"Accounts Manager",
	"Accounts User",
	"Sales Manager",
	"Sales User",
	"Purchase Manager",
	"Purchase User",
	"Stock Manager",
	"Stock User",
	"Manufacturing Manager",
	"Manufacturing User",
}
DEFAULT_AGING_RULES = [
	{"label": "30天内到期", "from_days": 0, "to_days": 30, "risk_level": "低风险"},
	{"label": "31-60天逾期", "from_days": 31, "to_days": 60, "risk_level": "低风险"},
	{"label": "61-90天逾期", "from_days": 61, "to_days": 90, "risk_level": "中风险"},
	{"label": "91-180天逾期", "from_days": 91, "to_days": 180, "risk_level": "高风险"},
	{"label": "180天以上逾期", "from_days": 181, "to_days": None, "risk_level": "高风险"},
]
DEFAULT_PURCHASE_DELAY_RISK_RULES = [
	{"label": "0-30 Days", "from_days": 0, "to_days": 30, "risk_level": "Low Risk"},
	{"label": "31-90 Days", "from_days": 31, "to_days": 90, "risk_level": "Medium Risk"},
	{"label": "91+ Days", "from_days": 91, "to_days": None, "risk_level": "High Risk"},
]
DRILLDOWN_REPORTS = {
	"sales_order_list": "Sales Order List",
	"receivable_aging_analysis": "Receivable Aging Analysis",
	"purchase_delay_analysis": "Purchase Delay Analysis",
}
OPERATION_DRILLDOWNS = {
	"production_completion_rate": {"route": ["List", "Work Order"], "doctype": "Work Order", "date_field": "planned_start_date"},
	"purchase_on_time_rate": {"route": ["query-report", "Purchase Delay Analysis"], "report": "Purchase Delay Analysis"},
	"realtime_inventory_amount": {"route": ["query-report", "Realtime Inventory"], "report": "Realtime Inventory"},
	"safety_stock_warning_count": {"route": ["query-report", "Safety Stock Status"], "report": "Safety Stock Status"},
	"purchase_in_transit_amount": {"route": ["query-report", "Purchase Order Analysis"], "report": "Purchase Order Analysis"},
	"material_over_consumption_rate": {"route": ["List", "Work Order"], "doctype": "Work Order", "date_field": "planned_start_date"},
}


def normalise_filters(filters=None):
	filters = frappe._dict(frappe.parse_json(filters) if isinstance(filters, str) else (filters or {}))
	filters.company = filters.get("company") or frappe.defaults.get_user_default("Company")
	if not filters.company:
		filters.company = frappe.db.get_value("Company", {}, "name")
	if not filters.company:
		frappe.throw(_("请先选择公司。"))
	filters.from_date = getdate(filters.get("from_date") or get_first_day(nowdate()))
	filters.to_date = getdate(filters.get("to_date") or nowdate())
	if filters.from_date > filters.to_date:
		frappe.throw(_("开始日期不能晚于截止日期。"))
	return filters


def check_dashboard_access():
	if not (set(frappe.get_roles()) & KPI_ROLES):
		frappe.throw(_("您没有查看运营指标看板的权限。"), frappe.PermissionError)


@frappe.whitelist()
def get_kpi_dashboard_data(filters=None):
	check_dashboard_access()
	filters = normalise_filters(filters)
	aging_rows = get_receivable_aging_rows(filters)
	purchase_delay_rows = get_purchase_delay_rows(filters)
	return {
		"filters": {"company": filters.company, "from_date": str(filters.from_date), "to_date": str(filters.to_date)},
		"drilldown_permissions": get_drilldown_permissions(),
		"operations_drilldowns": get_operations_drilldowns(filters),
		"sales": get_sales_kpis(filters),
		"delivery": get_delivery_kpis(filters),
		"receivable": get_receivable_kpis(filters, aging_rows),
		"salesperson": get_salesperson_kpis(filters),
		"year_over_year": get_year_over_year_kpis(filters),
		"reconciliation": get_reconciliation_kpis(filters),
		"aging": {"distribution": get_aging_distribution(aging_rows), "top_customers": get_overdue_customers(aging_rows)},
		"operations": get_operations_kpis(filters, purchase_delay_rows),
		"production_trend": get_production_trend(filters),
		"delayed_suppliers": [row for row in purchase_delay_rows if row.delayed_order_count][:10],
		"high_tech": get_high_tech_kpis(filters),
		"high_tech_trend": get_high_tech_trend(filters),
		"high_tech_projects": get_high_tech_project_rows(filters)[:10],
	}


def _workspace_card(metric_data, route, filters):
	"""Adapt one KPI metric to Frappe's native Number Card response format."""
	return {
		"value": metric_data.get("value"),
		"fieldtype": metric_data.get("datatype", "Float"),
		"route": route,
		"route_options": {"company": filters.company, "from_date": str(filters.from_date), "to_date": str(filters.to_date)},
	}


def _get_workspace_metric(section, key, route, filters=None):
	check_dashboard_access()
	filters = normalise_filters(filters)
	aging_rows = get_receivable_aging_rows(filters) if section == "receivable" else None
	data = {
		"sales": get_sales_kpis(filters),
		"delivery": get_delivery_kpis(filters),
		"receivable": get_receivable_kpis(filters, aging_rows),
		"operations": get_operations_kpis(filters),
		"high_tech": get_high_tech_kpis(filters),
	}[section]
	return _workspace_card(data[key], route, filters)


@frappe.whitelist()
def workspace_sales_amount(filters=None):
	return _get_workspace_metric("sales", "total_sales_amount", ["query-report", "Sales Order List"], filters)


@frappe.whitelist()
def workspace_sales_orders(filters=None):
	return _get_workspace_metric("sales", "total_orders", ["query-report", "Sales Order List"], filters)


@frappe.whitelist()
def workspace_delivery_completed(filters=None):
	return _get_workspace_metric("delivery", "completed_orders", ["query-report", "Delivery List"], filters)


@frappe.whitelist()
def workspace_received_amount(filters=None):
	return _get_workspace_metric("receivable", "received_amount", ["query-report", "Receivable Aging Analysis"], filters)


@frappe.whitelist()
def workspace_receivable_amount(filters=None):
	return _get_workspace_metric("receivable", "receivable_amount", ["query-report", "Receivable Aging Analysis"], filters)


@frappe.whitelist()
def workspace_production_completion(filters=None):
	return _get_workspace_metric("operations", "production_completion_rate", ["List", "Work Order"], filters)


@frappe.whitelist()
def workspace_inventory_value(filters=None):
	return _get_workspace_metric("operations", "realtime_inventory_amount", ["query-report", "Realtime Inventory"], filters)


@frappe.whitelist()
def workspace_high_tech_revenue(filters=None):
	return _get_workspace_metric("high_tech", "high_tech_revenue", ["query-report", "High Tech Revenue Analysis"], filters)


def get_sales_kpis(filters):
	row = frappe.db.sql(
		"""
		SELECT COUNT(*) AS total_orders, COALESCE(SUM(grand_total), 0) AS total_sales_amount,
			COALESCE(SUM(CASE WHEN custom_is_high_tech_revenue = 1 THEN grand_total ELSE 0 END), 0) AS high_tech_revenue
		FROM `tabSales Order`
		WHERE docstatus = 1 AND company = %(company)s
			AND transaction_date BETWEEN %(from_date)s AND %(to_date)s
		""",
		filters,
		as_dict=True,
	)[0]
	total = flt(row.total_sales_amount)
	return {
		"total_orders": metric(row.total_orders, "Int"),
		"total_sales_amount": metric(total, "Currency"),
		"high_tech_revenue": metric(row.high_tech_revenue, "Currency"),
		"high_tech_ratio": metric(percent(row.high_tech_revenue, total), "Percent"),
	}


def get_delivery_kpis(filters):
	rows = frappe.db.sql(
		"""
		SELECT so.name, MIN(CASE WHEN soi.delivered_qty >= soi.qty THEN 1 ELSE 0 END) AS fully_delivered,
			MAX(CASE WHEN soi.delivered_qty > 0 THEN 1 ELSE 0 END) AS any_delivered
		FROM `tabSales Order` so
		INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
		WHERE so.docstatus = 1 AND so.company = %(company)s
			AND so.transaction_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY so.name
		""",
		filters,
		as_dict=True,
	)
	completed = sum(flt(row.fully_delivered) == 1 for row in rows)
	in_progress = sum(flt(row.fully_delivered) != 1 and flt(row.any_delivered) == 1 for row in rows)
	undelivered = len(rows) - completed - in_progress
	return {
		"completed_orders": metric(completed, "Int"),
		"pending_orders": metric(len(rows) - completed, "Int"),
		"delivered_orders": metric(completed, "Int"),
		"delivering_orders": metric(in_progress, "Int"),
		"undelivered_orders": metric(undelivered, "Int"),
	}


def get_receivable_aging_rows(filters):
	rows = frappe.db.sql(
		"""
		SELECT si.name AS sales_invoice, si.customer, si.customer_name, si.posting_date,
			si.due_date, si.grand_total, si.outstanding_amount
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1 AND si.company = %(company)s
			AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		""",
		filters,
		as_dict=True,
	)
	rules = get_aging_rules()
	for row in rows:
		row.outstanding_amount = flt(row.outstanding_amount)
		row.receivable_days = max(0, date_diff(filters.to_date, row.due_date)) if row.due_date else 0
		row.aging_label, row.risk_level = resolve_aging_rule(row.receivable_days, rules)
		row.status = "已结清" if not row.outstanding_amount else "未结清"
	return rows


def get_receivable_kpis(filters, aging_rows):
	collections = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(per.allocated_amount), 0) AS received_amount
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive'
			AND per.reference_doctype = 'Sales Invoice' AND pe.company = %(company)s
			AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
		""",
		filters,
		as_dict=True,
	)[0]
	open_rows = [row for row in aging_rows if row.outstanding_amount]
	open_balance = sum(row.outstanding_amount for row in open_rows)
	overdue_90 = sum(row.outstanding_amount for row in open_rows if row.receivable_days > 90)
	weighted_days = sum(row.outstanding_amount * row.receivable_days for row in open_rows)
	month_filters = frappe._dict(filters.copy())
	month_filters.from_date = get_first_day(filters.to_date)
	target = get_target("collection_amount_monthly", month_filters)
	month_received = frappe.db.sql(
		"""SELECT COALESCE(SUM(per.allocated_amount), 0)
		FROM `tabPayment Entry` pe INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND per.reference_doctype = 'Sales Invoice'
			AND pe.company = %(company)s AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s""",
		month_filters,
	)[0][0]
	return {
		"received_amount": metric(collections.received_amount, "Currency"),
		"receivable_amount": metric(open_balance, "Currency"),
		"settled_documents": metric(sum(row.status == "已结清" for row in aging_rows), "Int"),
		"unsettled_documents": metric(len(open_rows), "Int"),
		"average_receivable_days": metric(percent(weighted_days, open_balance), "Float"),
		"overdue_over_90": metric(overdue_90, "Currency"),
		"receivable_turnover_days": metric(percent(weighted_days, open_balance), "Float"),
		"total_receivable_balance": metric(open_balance, "Currency"),
		"aging_0_30": metric(sum(r.outstanding_amount for r in open_rows if r.receivable_days <= 30), "Currency"),
		"aging_31_90": metric(sum(r.outstanding_amount for r in open_rows if 31 <= r.receivable_days <= 90), "Currency"),
		"aging_over_90": metric(overdue_90, "Currency"),
		"monthly_collection_completion": get_monthly_collection_completion(month_received, target),
	}


def get_monthly_collection_completion(month_received, target):
	"""Calculate the monthly collection completion from the configured target."""
	return metric(percent(month_received, target["target_value"]) if target else None, "Percent", target)


def get_drilldown_permissions():
	"""Expose report access flags without duplicating role rules in the browser."""
	return {
		key: bool(frappe.db.exists("Report", report_name) and frappe.get_cached_doc("Report", report_name).is_permitted())
		for key, report_name in DRILLDOWN_REPORTS.items()
	}


def get_operations_drilldowns(filters):
	"""Return only permitted, source-aligned routes for operations metrics."""
	result = {}
	for metric_key, definition in OPERATION_DRILLDOWNS.items():
		if definition.get("report"):
			permitted = frappe.db.exists("Report", definition["report"]) and frappe.get_cached_doc(
				"Report", definition["report"]
			).is_permitted()
		else:
			permitted = frappe.has_permission(definition["doctype"], "read")
		if not permitted:
			continue

		route_options = {"company": filters.company}
		if definition["route"][0] == "query-report":
			route_options.update({"from_date": str(filters.from_date), "to_date": str(filters.to_date)})
		elif definition.get("date_field"):
			route_options[definition["date_field"]] = ["between", [str(filters.from_date), str(filters.to_date)]]
		result[metric_key] = {"route": definition["route"], "route_options": route_options}
	return result


def get_salesperson_kpis(filters):
	delivery_rows = frappe.db.sql(
		"""
		SELECT st.sales_person, COUNT(DISTINCT dn.name) AS delivery_count,
			COALESCE(SUM(dni.amount * COALESCE(st.allocated_percentage, 0) / 100), 0) AS delivery_amount
		FROM `tabDelivery Note` dn
		INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		LEFT JOIN `tabSales Team` st ON st.parent = dni.against_sales_order
		WHERE dn.docstatus = 1 AND dn.company = %(company)s
			AND dn.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY st.sales_person ORDER BY delivery_amount DESC
		""",
		filters,
		as_dict=True,
	)
	data = {
		row.sales_person: frappe._dict(
			{"sales_person": row.sales_person, "delivery_count": flt(row.delivery_count), "delivery_amount": flt(row.delivery_amount), "personal_received": 0, "personal_receivable": 0, "order_amount": 0}
		)
		for row in delivery_rows
		if row.sales_person
	}
	order_rows = frappe.db.sql(
		"""SELECT st.sales_person,
			COALESCE(SUM(so.grand_total * COALESCE(st.allocated_percentage, 0) / 100), 0) AS order_amount
		FROM `tabSales Order` so INNER JOIN `tabSales Team` st ON st.parent = so.name
		WHERE so.docstatus = 1 AND so.company = %(company)s AND so.transaction_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY st.sales_person""",
		filters,
		as_dict=True,
	)
	financial_rows = frappe.db.sql(
		"""SELECT st.sales_person,
			COALESCE(SUM(si.outstanding_amount * COALESCE(st.allocated_percentage, 0) / 100), 0) AS personal_receivable,
			COALESCE(SUM(COALESCE(receipts.received_amount, 0) * COALESCE(st.allocated_percentage, 0) / 100), 0) AS personal_received
		FROM `tabSales Invoice` si INNER JOIN `tabSales Team` st ON st.parent = si.name
		LEFT JOIN (
			SELECT per.reference_name AS sales_invoice, SUM(per.allocated_amount) AS received_amount
			FROM `tabPayment Entry` pe INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
			WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND per.reference_doctype = 'Sales Invoice'
				AND pe.company = %(company)s AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
			GROUP BY per.reference_name
		) receipts ON receipts.sales_invoice = si.name
		WHERE si.docstatus = 1 AND si.company = %(company)s AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY st.sales_person""",
		filters,
		as_dict=True,
	)
	for row in order_rows + financial_rows:
		if not row.sales_person:
			continue
		entry = data.setdefault(row.sales_person, frappe._dict({"sales_person": row.sales_person, "delivery_count": 0, "delivery_amount": 0, "personal_received": 0, "personal_receivable": 0, "order_amount": 0}))
		for field in ("order_amount", "personal_received", "personal_receivable"):
			if field in row:
				entry[field] = flt(row[field])
	for row in data.values():
		row.delivery_rate = percent(row.delivery_amount, row.order_amount)
		row.collection_rate = percent(row.personal_received, row.personal_received + row.personal_receivable)
	return sorted(data.values(), key=lambda row: row.delivery_amount, reverse=True)[:10]


def get_year_over_year_kpis(filters):
	previous = frappe._dict(filters.copy())
	previous.from_date = add_days(filters.from_date, -365)
	previous.to_date = add_days(filters.to_date, -365)
	current_sales = get_sales_kpis(filters)["total_sales_amount"]["value"]
	previous_sales = get_sales_kpis(previous)["total_sales_amount"]["value"]
	current_ar = sum(row.outstanding_amount for row in get_receivable_aging_rows(filters))
	previous_ar = sum(row.outstanding_amount for row in get_receivable_aging_rows(previous))
	return {
		"prior_sales_amount": metric(previous_sales, "Currency"),
		"sales_growth_rate": metric(percent(current_sales - previous_sales, previous_sales), "Percent"),
		"receivable_growth_rate": metric(percent(current_ar - previous_ar, previous_ar), "Percent"),
	}


def get_reconciliation_kpis(filters):
	delivery = get_delivery_kpis(filters)
	mismatches = frappe.db.sql(
		"""SELECT COUNT(*) FROM (
			SELECT so.name FROM `tabSales Order` so INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
			WHERE so.docstatus = 1 AND so.company = %(company)s AND so.transaction_date BETWEEN %(from_date)s AND %(to_date)s
			GROUP BY so.name, so.status
			HAVING (so.status = 'Completed' AND MIN(CASE WHEN soi.delivered_qty >= soi.qty THEN 1 ELSE 0 END) = 0)
		) AS mismatched_orders""",
		filters,
	)[0][0]
	return {"unfinished_orders": delivery["pending_orders"], "status_mismatch_count": metric(mismatches, "Int")}


def get_aging_distribution(rows):
	result = []
	for rule in get_aging_rules():
		amount = sum(row.outstanding_amount for row in rows if row.outstanding_amount and row.aging_label == rule.label)
		result.append({"label": rule.label, "amount": amount})
	total = sum(row["amount"] for row in result)
	for row in result:
		row["ratio"] = percent(row["amount"], total)
	return result


def get_overdue_customers(rows):
	customers = defaultdict(lambda: {"overdue_amount": 0, "overdue_days": 0})
	for row in rows:
		if row.outstanding_amount and row.receivable_days > 30:
			customers[row.customer].update({"customer": row.customer, "customer_name": row.customer_name})
			customers[row.customer]["overdue_amount"] += row.outstanding_amount
			customers[row.customer]["overdue_days"] = max(customers[row.customer]["overdue_days"], row.receivable_days)
	result = list(customers.values())
	for row in result:
		_, row["risk_level"] = resolve_aging_rule(row["overdue_days"], get_aging_rules())
	return sorted(result, key=lambda row: (row["overdue_amount"], row["overdue_days"]), reverse=True)[:10]


def get_operations_kpis(filters, po_rows=None):
	work_orders = frappe.db.sql(
		"""SELECT COALESCE(SUM(qty), 0) AS planned, COALESCE(SUM(produced_qty), 0) AS produced
		FROM `tabWork Order` WHERE docstatus = 1 AND company = %(company)s
			AND planned_start_date BETWEEN %(from_date)s AND %(to_date)s""",
		filters,
		as_dict=True,
	)[0]
	po_rows = po_rows if po_rows is not None else get_purchase_delay_rows(filters)
	# Only orders whose final receipt or due date has reached the report cutoff
	# belong to the delivery-timeliness denominator. Future commitments are not
	# late and must not dilute the on-time rate.
	total_po = sum(row["evaluated_order_count"] for row in po_rows)
	on_time = sum(row["on_time_order_count"] for row in po_rows)
	in_transit = frappe.db.sql(
		"""SELECT COALESCE(SUM(GREATEST(poi.qty - COALESCE(poi.received_qty, 0), 0) * poi.rate), 0)
		FROM `tabPurchase Order` po INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
		WHERE po.docstatus = 1 AND po.company = %(company)s AND po.transaction_date BETWEEN %(from_date)s AND %(to_date)s
			AND IFNULL(poi.qty, 0) > IFNULL(poi.received_qty, 0)
			AND COALESCE(po.status, '') NOT IN ('Closed', 'Cancelled')""",
		filters,
	)[0][0]
	excluded_warehouses = get_inventory_excluded_warehouses()
	warehouse_clause = ""
	if excluded_warehouses:
		filters.inventory_excluded_warehouses = tuple(excluded_warehouses)
		warehouse_clause = " AND w.name NOT IN %(inventory_excluded_warehouses)s"
	inventory_value = frappe.db.sql(
		f"""SELECT COALESCE(SUM(b.actual_qty * b.valuation_rate), 0)
		FROM `tabBin` b INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
		WHERE w.company = %(company)s AND w.is_group = 0 AND w.disabled = 0{warehouse_clause}""",
		filters,
	)[0][0]
	warnings = frappe.db.sql(
		"""SELECT COUNT(DISTINCT CONCAT(i.name, '|', ir.warehouse)) FROM `tabItem` i INNER JOIN `tabItem Reorder` ir ON ir.parent = i.name
		LEFT JOIN `tabBin` b ON b.item_code = i.name AND b.warehouse = ir.warehouse
		INNER JOIN `tabWarehouse` w ON w.name = ir.warehouse
		WHERE i.disabled = 0 AND i.is_stock_item = 1 AND w.company = %(company)s AND w.is_group = 0 AND w.disabled = 0
			AND ((i.safety_stock > 0 AND COALESCE(b.projected_qty, 0) <= i.safety_stock)
			 OR (ir.warehouse_reorder_level > 0 AND COALESCE(b.projected_qty, 0) <= ir.warehouse_reorder_level))""",
		filters,
	)[0][0]
	consumption = frappe.db.sql(
		"""SELECT COALESCE(SUM(required_qty), 0) AS required_qty, COALESCE(SUM(GREATEST(consumed_qty - required_qty, 0)), 0) AS excess_qty
		FROM `tabWork Order Item` woi INNER JOIN `tabWork Order` wo ON wo.name = woi.parent
		WHERE wo.docstatus = 1 AND wo.company = %(company)s AND wo.planned_start_date BETWEEN %(from_date)s AND %(to_date)s""",
		filters,
		as_dict=True,
	)[0]
	return {
		"production_completion_rate": metric(percent(work_orders.produced, work_orders.planned), "Percent", get_target("production_completion_rate", filters)),
		"purchase_on_time_rate": metric(percent(on_time, total_po), "Percent", get_target("purchase_on_time_rate", filters)),
		"realtime_inventory_amount": metric(inventory_value, "Currency", get_target("realtime_inventory_amount", filters)),
		"safety_stock_warning_count": metric(warnings, "Int", get_target("safety_stock_warning_count", filters)),
		"purchase_in_transit_amount": metric(in_transit, "Currency", get_target("purchase_in_transit_amount", filters)),
		"material_over_consumption_rate": metric(percent(consumption.excess_qty, consumption.required_qty), "Percent", get_target("material_over_consumption_rate", filters)),
	}


def get_inventory_excluded_warehouses():
	"""Return configured business warehouses excluded from sellable inventory KPIs.

	The fields are app extensions and may not exist during an intermediate
	migration, so missing fields/sites must degrade to an empty exclusion list.
	"""
	if not frappe.db.exists("DocType", "Stock Settings"):
		return []
	result = []
	# 样品仓仍属于企业持有库存，应计入库存金额；客户借出仓则不属于
	# 当前可用经营库存，因此继续排除。
	for fieldname in ("custom_customer_loan_warehouse",):
		try:
			value = frappe.db.get_single_value("Stock Settings", fieldname)
		except Exception:
			# A partially migrated site may have the DocType metadata but not its
			# table yet. KPI rendering must remain available in that state.
			continue
		if value and value not in result:
			result.append(value)
	return result


def get_production_trend(filters):
	rows = frappe.db.sql(
		"""SELECT DATE_FORMAT(planned_start_date, '%%Y-%%m') AS period, COALESCE(SUM(qty), 0) AS planned_qty,
			COALESCE(SUM(produced_qty), 0) AS actual_qty FROM `tabWork Order`
		WHERE docstatus = 1 AND company = %(company)s AND planned_start_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY DATE_FORMAT(planned_start_date, '%%Y-%%m') ORDER BY period""",
		filters,
		as_dict=True,
	)
	for row in rows:
		row.completion_rate = percent(row.actual_qty, row.planned_qty)
	return rows


def get_purchase_delay_item_rows(filters):
	"""Raw PO item rows with receipt aggregates, shared by delay reports and the rating engine."""
	return frappe.db.sql(
		"""
		SELECT po.supplier, po.supplier_name, po.name AS purchase_order,
			po.transaction_date AS order_date,
			poi.name AS purchase_order_item, poi.qty, poi.schedule_date AS expected_date,
			COALESCE(SUM(CASE WHEN pr.name IS NOT NULL THEN pri.qty ELSE 0 END), 0) AS received_qty,
			MAX(pr.posting_date) AS receipt_date
		FROM `tabPurchase Order` po
		INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
		LEFT JOIN `tabPurchase Receipt Item` pri ON pri.purchase_order_item = poi.name
		LEFT JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
			AND pr.docstatus = 1 AND pr.posting_date <= %(to_date)s
		WHERE po.docstatus = 1 AND po.company = %(company)s AND po.transaction_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY po.supplier, po.supplier_name, po.name, po.transaction_date, poi.name, poi.qty, poi.schedule_date
		""",
		filters,
		as_dict=True,
	)


def get_purchase_delay_rows(filters):
	rows = get_purchase_delay_item_rows(filters)
	orders = get_purchase_order_delay_status(rows, filters.to_date)
	suppliers = defaultdict(
		lambda: {
			"order_count": 0,
			"evaluated_order_count": 0,
			"on_time_order_count": 0,
			"delayed_order_count": 0,
			"pending_order_count": 0,
			"unevaluable_order_count": 0,
			"total_delay_days": 0,
			"total_delivered_delay_days": 0,
			"open_overdue_days": [],
			"open_overdue_order_count": 0,
			"max_open_overdue_days": 0,
			"completed_order_count": 0,
			"total_lead_time_days": 0,
			"open_overdue_lead_days": 0,
			"max_lead_time_days": 0,
		}
	)
	for row in orders:
		entry = suppliers[row.supplier]
		entry.update({"supplier": row.supplier, "supplier_name": row.supplier_name})
		entry["order_count"] += 1
		if row.status == "on_time":
			entry["on_time_order_count"] += 1
		elif row.status == "delayed":
			entry["delayed_order_count"] += 1
			entry["total_delay_days"] += row.delay_days
			entry["total_delivered_delay_days"] += row.delivered_delay_days
			if row.open_overdue_days > 0:
				entry["open_overdue_days"].append(row.open_overdue_days)
				entry["open_overdue_order_count"] += 1
				entry["max_open_overdue_days"] = max(entry["max_open_overdue_days"], row.open_overdue_days)
		elif row.status == "unevaluable":
			entry["unevaluable_order_count"] += 1
		else:
			entry["pending_order_count"] += 1
		entry["evaluated_order_count"] = entry["on_time_order_count"] + entry["delayed_order_count"]
		if row.lead_time_days is not None:
			entry["max_lead_time_days"] = max(entry["max_lead_time_days"], row.lead_time_days)
			if row.open_overdue_days > 0:
				entry["open_overdue_lead_days"] += row.lead_time_days
			else:
				entry["completed_order_count"] += 1
				entry["total_lead_time_days"] += row.lead_time_days
	result = []
	risk_rules = get_purchase_delay_risk_rules()
	for row in suppliers.values():
		row["average_delay_days"] = percent(row["total_delay_days"], row["delayed_order_count"])
		row["average_lead_time_days"] = percent(
			row["total_lead_time_days"] + row["open_overdue_lead_days"],
			row["completed_order_count"] + row["open_overdue_order_count"],
		)
		row["risk_level"] = resolve_purchase_delay_risk_rule(row["average_delay_days"], risk_rules)
		result.append(frappe._dict(row))
	return sorted(result, key=lambda row: (row.delayed_order_count, row.average_delay_days), reverse=True)


def get_purchase_order_delay_status(item_rows, cutoff_date):
	"""Determine purchase delivery performance at order level as of a cutoff.

	An incomplete item is late only after its planned receipt date. Future or
	unscheduled items stay pending evaluation; this prevents a zero-day delay
	from being displayed as an overdue order. A delayed order uses the greatest
	delay among its delayed items.

	Orders whose items are all fully received also expose the actual lead time
	(last receipt date minus order date), independent of the schedule date.
	"""
	orders = defaultdict(list)
	for row in item_rows:
		if flt(row.get("qty")) > 0:
			orders[row.purchase_order].append(row)

	result = []
	# Overdue days for unreceived items only accrue up to today: a future
	# cutoff must not count time that has not elapsed yet.
	cutoff_date = min(getdate(cutoff_date), getdate(nowdate()))
	for purchase_order, rows in orders.items():
		# Establish the order-level reference row before evaluating open-delay
		# lead time.  The previous implementation assigned this after the loop,
		# which raised UnboundLocalError for overdue open orders.
		first = rows[0]
		delivered_delay = 0
		open_overdue = 0
		all_on_time = True
		fully_delivered = True
		all_qty_received = True
		has_due_item = False
		any_overdue = False
		last_receipt_date = None
		open_overdue_lead_days = None
		for row in rows:
			expected_date = getdate(row.expected_date) if row.expected_date else None
			fully_received = flt(row.received_qty) >= flt(row.qty)
			if not fully_received:
				all_qty_received = False
			if fully_received and row.receipt_date:
				receipt_date = getdate(row.receipt_date)
				last_receipt_date = max(last_receipt_date, receipt_date) if last_receipt_date else receipt_date
			else:
				fully_delivered = False
			if not expected_date:
				# 无承诺交期的行无法判定准时：已收齐则不影响整单评估，
				# 未收齐则整单不能算作按时。
				if not fully_received:
					all_on_time = False
				continue
			has_due_item = True
			if fully_received and row.receipt_date:
				delivered_delay = max(delivered_delay, max(0, date_diff(row.receipt_date, expected_date)))
			elif fully_received:
				# Receipt quantities without a submitted receipt date cannot be
				# evaluated reliably as on-time.
				all_on_time = False
			elif expected_date < cutoff_date:
				open_overdue = max(open_overdue, date_diff(cutoff_date, expected_date))
				any_overdue = True
				if first.get("order_date"):
					open_overdue_lead_days = max(
						open_overdue_lead_days or 0,
						max(0, date_diff(cutoff_date, first.order_date)),
					)
			else:
				all_on_time = False

		max_delay = max(delivered_delay, open_overdue)
		# 到期订单总数 = 按期交付 + 逾期补交 + 截止日仍未交但已逾期；
		# 未到承诺交期的未交订单为待评估，无承诺交期的订单无法评估，两者均不计入及时率。
		if any_overdue or delivered_delay > 0:
			status = "delayed"
		elif has_due_item and all_on_time:
			status = "on_time"
		elif not has_due_item and all_qty_received:
			status = "unevaluable"
		else:
			status = "pending"
		lead_time_days = None
		if fully_delivered and last_receipt_date and first.get("order_date"):
			lead_time_days = max(0, date_diff(last_receipt_date, first.order_date))
		elif open_overdue_lead_days is not None:
			# 逾期未交订单按“下单日到截止日”的已耗时计入实际交期，避免美化交付表现。
			lead_time_days = open_overdue_lead_days
		result.append(
			frappe._dict(
				{
					"purchase_order": purchase_order,
					"supplier": first.supplier,
					"supplier_name": first.supplier_name,
					"status": status,
					"delay_days": max_delay,
					# 已交付迟到是事实值，不再变化；在途逾期随时间持续累积。
					"delivered_delay_days": delivered_delay,
					"open_overdue_days": open_overdue,
					"lead_time_days": lead_time_days,
				}
			)
		)
	return result


def get_high_tech_kpis(filters):
	sales = get_sales_kpis(filters)
	projects = frappe.db.count("Project", {"company": filters.company, "status": ["not in", ["Completed", "Cancelled"]]})
	rd_cost = frappe.db.sql(
		"""SELECT COALESCE(SUM(grand_total), 0) FROM `tabPurchase Invoice`
		WHERE docstatus = 1 AND company = %(company)s AND project IS NOT NULL AND project != ''
			AND posting_date BETWEEN %(from_date)s AND %(to_date)s""",
		filters,
	)[0][0]
	return {
		"high_tech_revenue": high_tech_compliance_metric(sales["high_tech_revenue"]["value"], "Currency", "high_tech_revenue", filters),
		"total_revenue": high_tech_compliance_metric(sales["total_sales_amount"]["value"], "Currency", "total_revenue", filters),
		"high_tech_ratio": high_tech_compliance_metric(sales["high_tech_ratio"]["value"], "Percent", "high_tech_ratio", filters),
		"rd_project_count": high_tech_compliance_metric(projects, "Int", "rd_project_count", filters),
		"rd_expense_amount": high_tech_compliance_metric(rd_cost, "Currency", "rd_expense_amount", filters),
		"rd_expense_ratio": high_tech_compliance_metric(percent(rd_cost, sales["total_sales_amount"]["value"]), "Percent", "rd_expense_ratio", filters),
	}


def high_tech_compliance_metric(value, datatype, kpi_code, filters):
	"""Apply one consistent compliance vocabulary to the high-tech module."""
	is_ratio = datatype == "Percent"
	return compliance_metric(
		value,
		datatype,
		get_target(kpi_code, filters),
		passed_status="合规" if is_ratio else "达标",
		failed_status="不合规" if is_ratio else "未达标",
	)


def get_high_tech_trend(filters):
	rows = frappe.db.sql(
		"""SELECT YEAR(transaction_date) AS year, COALESCE(SUM(grand_total), 0) AS total_revenue,
			COALESCE(SUM(CASE WHEN custom_is_high_tech_revenue = 1 THEN grand_total ELSE 0 END), 0) AS high_tech_revenue
		FROM `tabSales Order` WHERE docstatus = 1 AND company = %(company)s
			AND transaction_date BETWEEN DATE_SUB(DATE_FORMAT(%(to_date)s, '%%Y-01-01'), INTERVAL 2 YEAR) AND %(to_date)s
		GROUP BY YEAR(transaction_date) ORDER BY year""",
		filters,
		as_dict=True,
	)
	for row in rows:
		row.high_tech_ratio = percent(row.high_tech_revenue, row.total_revenue)
	return rows


def get_high_tech_project_rows(filters):
	return frappe.db.sql(
		"""SELECT so.project, COALESCE(p.project_name, so.project) AS project_name,
			COALESCE(SUM(so.grand_total), 0) AS high_tech_revenue
		FROM `tabSales Order` so LEFT JOIN `tabProject` p ON p.name = so.project
		WHERE so.docstatus = 1 AND so.company = %(company)s AND so.custom_is_high_tech_revenue = 1
			AND so.project IS NOT NULL AND so.project != '' AND so.transaction_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY so.project, p.project_name ORDER BY high_tech_revenue DESC""",
		filters,
		as_dict=True,
	)


def get_aging_rules():
	if not frappe.db.exists("DocType", "Aging Period Rule"):
		return [frappe._dict(row) for row in DEFAULT_AGING_RULES]
	rules = frappe.get_all("Aging Period Rule", filters={"enabled": 1}, fields=["label", "from_days", "to_days", "risk_level"], order_by="from_days")
	return rules or [frappe._dict(row) for row in DEFAULT_AGING_RULES]


def get_purchase_delay_risk_rules():
	if not frappe.db.exists("DocType", "Purchase Delay Risk Rule"):
		return [frappe._dict(row) for row in DEFAULT_PURCHASE_DELAY_RISK_RULES]
	rules = frappe.get_all(
		"Purchase Delay Risk Rule",
		filters={"enabled": 1},
		fields=["label", "from_days", "to_days", "risk_level"],
		order_by="from_days",
	)
	return rules or [frappe._dict(row) for row in DEFAULT_PURCHASE_DELAY_RISK_RULES]


def resolve_purchase_delay_risk_rule(days, rules):
	for rule in rules:
		if days >= flt(rule.from_days) and (not rule.to_days or days <= flt(rule.to_days)):
			return rule.risk_level
	return "Low Risk"


def resolve_aging_rule(days, rules):
	for rule in rules:
		if days >= flt(rule.from_days) and (not rule.to_days or days <= flt(rule.to_days)):
			return rule.label, rule.risk_level
	return "未分类", "低风险"


def get_target(kpi_code, filters):
	if not frappe.db.exists("DocType", "KPI Target"):
		return None
	date = getdate(filters.to_date)
	periods = (
		("Monthly", date.strftime("%Y-%m")),
		("Quarterly", f"{date.year}-Q{((date.month - 1) // 3) + 1}"),
		("Yearly", str(date.year)),
	)
	for period_type, period_value in periods:
		target = frappe.db.get_value(
			"KPI Target",
			{"company": filters.company, "kpi_code": kpi_code, "period_type": period_type, "period_value": period_value},
			["target_value", "warning_threshold", "danger_threshold", "evaluation_direction"],
			as_dict=True,
		)
		if target:
			return target
	return None


def metric(value, datatype, target=None):
	value = None if value is None else flt(value) if datatype != "Int" else int(value or 0)
	target_direction = target.get("evaluation_direction") if target else None
	result = {
		"value": value,
		"datatype": datatype,
		"target": target.get("target_value") if target else None,
		"target_direction": target_direction,
		"target_progress": None,
		"status": "未设置",
	}
	if target and value is not None:
		result["achievement"] = get_target_achievement(value, target.target_value, target_direction)
		result["target_progress"] = get_target_progress(value, target.target_value, target_direction)
		result["status"] = "正常"
		if target.evaluation_direction == "Lower Is Better":
			if target.danger_threshold is not None and value >= flt(target.danger_threshold):
				result["status"] = "危险"
			elif target.warning_threshold is not None and value >= flt(target.warning_threshold):
				result["status"] = "预警"
		else:
			if target.danger_threshold is not None and value <= flt(target.danger_threshold):
				result["status"] = "危险"
			elif target.warning_threshold is not None and value <= flt(target.warning_threshold):
				result["status"] = "预警"
	return result


def get_target_achievement(value, target_value, evaluation_direction):
	"""Return a capped, direction-aware target achievement ratio.

	For a lower-is-better KPI, exceeding the target is a lower achievement;
	for example 1,810 against a 1,000 cap is 55.2%, not 181.0%. Values that
	are already better than target are capped at 100% instead of reporting an
	unbounded percentage.
	"""
	value = flt(value)
	target_value = flt(target_value)
	if target_value == 0:
		return 1 if value == 0 else 0

	if evaluation_direction == "Lower Is Better":
		achievement = target_value / value if value else 1
	else:
		achievement = value / target_value
	return max(0, min(1, flt(achievement)))


def get_target_progress(value, target_value, evaluation_direction):
	"""Return the direction-aware achievement as a percentage for progress UI."""
	return get_target_achievement(value, target_value, evaluation_direction) * 100


def compliance_metric(value, datatype, target, passed_status, failed_status):
	"""Return a target-based KPI with compliance-oriented status wording.

	High-tech revenue and ratio are statutory/business compliance indicators.
	They must communicate whether the configured annual target is met, instead of
	appearing as merely 'normal' when no warning thresholds are configured.
	"""
	result = metric(value, datatype, target)
	if not target or result["value"] is None:
		return result

	target_value = flt(target.target_value)
	if not target_value:
		return result

	if target.evaluation_direction == "Lower Is Better":
		is_compliant = flt(result["value"]) <= target_value
	else:
		is_compliant = flt(result["value"]) >= target_value
	result["status"] = passed_status if is_compliant else failed_status
	return result


def percent(numerator, denominator):
	return flt(numerator) / flt(denominator) if flt(denominator) else 0
