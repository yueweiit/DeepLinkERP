from typing import Any

import frappe
from frappe import _

from crm_integration.crm_integration.integration_log import create_crm_log, update_crm_log
from crm_integration.crm_integration.sales_order import PENDING_DEPOSIT_CONFIRMATION
from crm_integration.crm_integration.sales_order import PENDING_CONFIRMATION, PENDING_PRODUCTION
from crm_integration.crm_integration.settings import is_crm_integration_enabled, throw_crm_integration_disabled


@frappe.whitelist(methods=["POST"])
def create_and_submit_sales_order(sales_order=None):
	"""Create a Sales Order from an external system and submit it immediately."""
	payload = get_request_payload(sales_order)
	validate_sales_order_payload(payload)
	if not is_crm_integration_enabled(payload.get("company")):
		throw_crm_integration_disabled(payload.get("company"))
	ensure_sales_persons_exist(payload)

	crm_log = create_crm_log(
		direction="Inbound",
		event="Sales Order Create And Submit",
		status="Pending",
		source="CRM",
		request_url=get_request_url(),
		request_payload=payload,
	)

	try:
		doc = frappe.get_doc(payload)
		doc.insert(ignore_permissions=True)
		doc.submit()

		if doc.get("custom_process_status") != PENDING_DEPOSIT_CONFIRMATION:
			doc.db_set("custom_process_status", PENDING_DEPOSIT_CONFIRMATION, update_modified=True)
			doc.custom_process_status = PENDING_DEPOSIT_CONFIRMATION

		response = {
			"status": "success",
			"message": _("销售订单已创建并提交。"),
			"name": doc.name,
			"docstatus": doc.docstatus,
			"process_status": doc.get("custom_process_status"),
		}

		update_crm_log(
			crm_log,
			status="Success",
			reference_doctype="Sales Order",
			reference_name=doc.name,
			response_payload=response,
			http_status_code=200,
		)
		return response
	except Exception:
		update_crm_log(
			crm_log,
			status="Failed",
			error_message=frappe.get_traceback(),
			http_status_code=500,
		)
		raise


@frappe.whitelist(methods=["POST"])
def update_sales_order_by_crm_order_no(sales_order: Any = None):
	"""Update an existing Sales Order using its CRM order number."""
	payload = get_request_payload(sales_order)
	validate_sales_order_update_payload(payload)

	crm_order_no = payload["custom_crm_order_no"]
	sales_order_names = frappe.get_all(
		"Sales Order",
		filters={"custom_crm_order_no": crm_order_no},
		pluck="name",
		limit_page_length=2,
	)
	if not sales_order_names:
		frappe.throw(_("未找到 CRM 销售订单号 {0} 对应的销售订单。").format(crm_order_no))
	if len(sales_order_names) > 1:
		frappe.throw(_("CRM 销售订单号 {0} 对应多笔销售订单，无法安全修改。").format(crm_order_no))

	doc = frappe.get_doc("Sales Order", sales_order_names[0])
	validate_sales_order_update_status(doc)
	update_sales_order_items(doc, payload.get("items"))
	for field, value in payload.items():
		if field not in {"doctype", "name", "docstatus", "items"}:
			doc.set(field, value)

	if payload.get("items"):
		doc.calculate_taxes_and_totals()
	if doc.docstatus == 1:
		doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)
	return {
		"status": "success",
		"message": _("销售订单已更新。"),
		"name": doc.name,
		"crm_order_no": doc.custom_crm_order_no,
		"docstatus": doc.docstatus,
	}


def update_sales_order_items(doc, items):
	if not items:
		return
	if isinstance(items, str):
		items = frappe.parse_json(items)
	if not isinstance(items, list):
		frappe.throw(_("items 必须是数组。"))

	rows_by_name = {row.name: row for row in doc.items}
	rows_by_item_code = {row.item_code: row for row in doc.items if row.item_code}
	allowed_fields = {"qty", "rate"}

	for item in items:
		if not isinstance(item, dict):
			frappe.throw(_("items 中的每一项必须是对象。"))

		row = rows_by_name.get(item.get("name")) or rows_by_item_code.get(item.get("item_code"))
		if not row:
			identifier = item.get("name") or item.get("item_code") or _("未提供")
			frappe.throw(_("销售订单中未找到明细 {0}。").format(identifier))

		fields = set(item) - {"name", "item_code"}
		unsupported_fields = fields - allowed_fields
		if unsupported_fields:
			frappe.throw(_("不支持修改销售订单明细字段：{0}。").format(", ".join(sorted(unsupported_fields))))
		if not fields:
			frappe.throw(_("明细 {0} 未提供需要修改的字段。").format(row.item_code or row.name))

		for field in fields:
			row.set(field, item[field])


def validate_sales_order_update_status(doc):
	allowed_statuses = {
		PENDING_CONFIRMATION,
		PENDING_DEPOSIT_CONFIRMATION,
		PENDING_PRODUCTION,
	}
	process_status = doc.get("custom_process_status")
	if process_status and process_status not in allowed_statuses:
		frappe.throw(
			_("销售订单 {0} 当前状态为 {1}，只有生产中及之前的状态允许修改。").format(
				doc.name, process_status
			)
		)


def get_request_payload(sales_order=None):
	if isinstance(sales_order, str):
		return frappe.parse_json(sales_order)

	if isinstance(sales_order, dict):
		return sales_order

	if frappe.request and frappe.request.is_json:
		request_json = frappe.request.get_json(silent=True) or {}
		if request_json.get("sales_order"):
			return request_json.get("sales_order")
		return request_json

	return dict(frappe.form_dict.get("sales_order") or frappe.form_dict)


def validate_sales_order_payload(payload):
	if not isinstance(payload, dict):
		frappe.throw(_("请求体必须是 JSON 对象。"))

	payload.setdefault("doctype", "Sales Order")
	if payload.get("doctype") != "Sales Order":
		frappe.throw(_("该接口只支持创建 Sales Order。"))

	if payload.get("docstatus"):
		frappe.throw(_("请求体不能直接传 docstatus，请由接口自动提交销售订单。"))

	if not payload.get("customer"):
		frappe.throw(_("缺少必填字段：customer"))

	if not payload.get("items"):
		frappe.throw(_("缺少销售订单明细：items"))


def validate_sales_order_update_payload(payload: Any):
	if not isinstance(payload, dict):
		frappe.throw(_("请求体必须是 JSON 对象。"))

	if payload.get("doctype") and payload["doctype"] != "Sales Order":
		frappe.throw(_("该接口只支持修改 Sales Order。"))
	if payload.get("name"):
		frappe.throw(_("请使用 custom_crm_order_no 定位销售订单，不要传 name。"))
	if payload.get("docstatus") is not None:
		frappe.throw(_("不允许通过该接口修改 docstatus。"))
	if not payload.get("custom_crm_order_no"):
		frappe.throw(_("缺少必填字段：custom_crm_order_no"))


def ensure_sales_persons_exist(payload):
	"""Ensure every Sales Person referenced in sales_team exists in ERP.

	If a Sales Person does not exist, create it automatically as a leaf node.
	"""
	sales_team = payload.get("sales_team")
	if not sales_team:
		return

	for row in sales_team:
		person_name = row.get("sales_person")
		if not person_name:
			continue

		if not frappe.db.exists("Sales Person", {"sales_person_name": person_name}):
			frappe.get_doc(
				{
					"doctype": "Sales Person",
					"sales_person_name": person_name,
					"is_group": 0,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)


def get_request_url():
	if not getattr(frappe.local, "request", None):
		return None

	return getattr(frappe.request, "url", None)
