import frappe
from frappe import _

from crm_integration.crm_integration.integration_log import create_crm_log, update_crm_log
from crm_integration.crm_integration.sales_order import PENDING_DEPOSIT_CONFIRMATION
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
