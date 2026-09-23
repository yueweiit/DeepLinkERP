import hashlib
from contextlib import contextmanager

import frappe
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
from frappe import _
from frappe.utils import cint, flt, getdate, now

from crm_integration.crm_integration.integration_log import create_crm_log, update_crm_log
from crm_integration.crm_integration.sales_order import (
	CRM_STATUS_SHIPMENT_CANCELLED,
	CRM_STATUS_SHIPMENT_CREATED,
	DELIVERABLE,
	PENDING_FINAL_PAYMENT,
	PENDING_PRODUCTION,
	enqueue_sales_order_status_to_crm,
	is_missing_mes_integration_error,
	set_process_status,
)
from crm_integration.crm_integration.settings import is_crm_integration_enabled

COMPLETED = "Completed"
PARTIALLY_DELIVERED = "Partially Delivered"
DRAFT_ALLOWED_STATUSES = (PENDING_PRODUCTION, PENDING_FINAL_PAYMENT, DELIVERABLE, PARTIALLY_DELIVERED)
CRM_SHIPMENT_FIELD = "custom_crm_shipment_no"
CRM_SHIPMENT_LOCK_TIMEOUT = 15


class CRMShipmentIdentityConflict(frappe.ValidationError):
	http_status_code = 409


def create_and_submit_delivery_note_from_crm(payload):
	payload = normalize_crm_shipment_payload(payload)
	validate_crm_shipment_payload(payload)
	sales_order = get_crm_shipment_sales_order(payload)

	if not is_crm_integration_enabled(sales_order.get("company")):
		frappe.throw(_("公司 {0} 未启用 CRM 集成。").format(sales_order.get("company") or ""))

	crm_log = create_crm_log(
		direction="Inbound",
		event="CRM Shipment Create And Submit",
		status="Pending",
		reference_doctype="Sales Order",
		reference_name=sales_order.name,
		source="CRM",
		request_payload=payload,
	)

	try:
		with crm_shipment_lock(payload[CRM_SHIPMENT_FIELD]):
			lock_sales_order_for_crm_shipment(sales_order.name)
			sales_order = frappe.get_doc("Sales Order", sales_order.name)
			credit_delivery_note = get_crm_delivery_note_for_allocation_credit(payload)
			allocations = allocate_crm_shipment_items(
				sales_order,
				payload["items"],
				credit_delivery_note=credit_delivery_note,
			)
			delivery_note, idempotent_replay = get_or_create_crm_delivery_note(
				sales_order, payload, allocations
			)

			if delivery_note.docstatus == 0:
				release_sales_order_for_crm_shipment(sales_order)
				prepare_crm_delivery_note_for_submit(delivery_note, sales_order, payload)
				delivery_note.flags.ignore_permissions = True
				delivery_note.submit()
				idempotent_replay = False

		response = get_crm_shipment_response(
			delivery_note,
			payload[CRM_SHIPMENT_FIELD],
			idempotent_replay=idempotent_replay,
		)
		update_crm_log(
			crm_log,
			status="Success",
			reference_doctype="Delivery Note",
			reference_name=delivery_note.name,
			response_payload=response,
			http_status_code=200,
		)
		return response
	except Exception:
		update_crm_log(
			crm_log,
			status="Failed",
			error_message=frappe.get_traceback(),
			http_status_code=getattr(frappe.local.response, "http_status_code", None),
		)
		raise


def normalize_crm_shipment_payload(payload):
	if not isinstance(payload, dict):
		return payload

	payload = dict(payload)
	payload[CRM_SHIPMENT_FIELD] = (
		payload.get(CRM_SHIPMENT_FIELD) or payload.get("shipment_no") or payload.get("externalShipmentId")
	)
	return payload


def validate_crm_shipment_payload(payload):
	if not isinstance(payload, dict):
		frappe.throw(_("请求体必须是 JSON 对象。"))

	shipment_no = str(payload.get(CRM_SHIPMENT_FIELD) or "").strip()
	if not shipment_no:
		frappe.throw(_("缺少必填字段：custom_crm_shipment_no"))
	if len(shipment_no) > 140:
		frappe.throw(_("custom_crm_shipment_no 不能超过 140 个字符。"))
	payload[CRM_SHIPMENT_FIELD] = shipment_no

	if not payload.get("sales_order") and not payload.get("custom_crm_order_no"):
		frappe.throw(_("sales_order 和 custom_crm_order_no 至少需要提供一个。"))
	if "delivery_note" in payload:
		frappe.throw(
			_("delivery_note 参数已停用，请由 CRM 提供发货明细，ERP 将直接创建并提交销售出库。")
		)

	items = payload.get("items")
	if not isinstance(items, list) or not items:
		frappe.throw(_("缺少销售出库明细：items"))

	for index, item in enumerate(items, start=1):
		if not isinstance(item, dict):
			frappe.throw(_("items 中第 {0} 项必须是对象。").format(index))
		if not item.get("item_code") and not (item.get("sales_order_item") or item.get("name")):
			frappe.throw(_("销售出库第 {0} 行缺少 item_code 或 sales_order_item。").format(index))
		if flt(item.get("qty")) <= 0:
			frappe.throw(_("销售出库第 {0} 行 qty 必须大于 0。").format(index))
		version = item.get("custom_version")
		if version is not None and not isinstance(version, str):
			frappe.throw(_("销售出库第 {0} 行 custom_version 必须是字符串。").format(index))
		if version is not None and len(version) > 64:
			frappe.throw(_("销售出库第 {0} 行 custom_version 不能超过 64 个字符。").format(index))


def get_crm_shipment_sales_order(payload):
	sales_order_name = payload.get("sales_order")
	crm_order_no = payload.get("custom_crm_order_no")

	if sales_order_name:
		if not frappe.db.exists("Sales Order", sales_order_name):
			frappe.throw(_("未找到销售订单 {0}。").format(sales_order_name))
		sales_order = frappe.get_doc("Sales Order", sales_order_name)
		if crm_order_no and sales_order.get("custom_crm_order_no") != crm_order_no:
			throw_crm_shipment_identity_conflict(
				_("ERP 销售订单 {0} 与 CRM 订单号 {1} 不匹配。").format(sales_order_name, crm_order_no)
			)
		return sales_order

	names = frappe.get_all(
		"Sales Order",
		filters={"custom_crm_order_no": crm_order_no},
		pluck="name",
		limit_page_length=2,
	)
	if not names:
		frappe.throw(_("未找到 CRM 销售订单号 {0} 对应的销售订单。").format(crm_order_no))
	if len(names) > 1:
		throw_crm_shipment_identity_conflict(_("CRM 销售订单号 {0} 对应多笔销售订单。").format(crm_order_no))
	return frappe.get_doc("Sales Order", names[0])


def get_crm_delivery_note_for_allocation_credit(payload):
	return get_delivery_note_by_crm_shipment_no(payload[CRM_SHIPMENT_FIELD])


def allocate_crm_shipment_items(sales_order, requested_items, credit_delivery_note=None):
	if sales_order.docstatus != 1:
		frappe.throw(_("销售订单 {0} 必须已提交。").format(sales_order.name))

	credited_qty = get_delivery_note_qty_credit(credit_delivery_note, sales_order.name)
	available_rows = []
	for row in sales_order.get("items", []):
		if row.get("delivered_by_supplier"):
			continue
		remaining_qty = flt(row.get("qty")) - flt(row.get("delivered_qty")) + flt(credited_qty.get(row.name))
		if remaining_qty > 0:
			available_rows.append(frappe._dict(doc=row, remaining_qty=remaining_qty))

	allocations = []
	for index, request_item in enumerate(requested_items, start=1):
		request_row = frappe._dict(request_item)
		item_code = request_row.get("item_code")
		row_name = request_row.get("sales_order_item") or request_row.get("name")
		version_supplied = "custom_version" in request_item
		version = request_row.get("custom_version") or ""

		candidates = [row for row in available_rows if row.remaining_qty > 0]
		if row_name:
			candidates = [row for row in candidates if row.doc.name == row_name]
		else:
			candidates = [row for row in candidates if row.doc.item_code == item_code]
			if version_supplied:
				candidates = [row for row in candidates if (row.doc.get("custom_version") or "") == version]
			else:
				candidate_versions = {row.doc.get("custom_version") or "" for row in candidates}
				if len(candidate_versions) > 1:
					frappe.throw(
						_(
							"销售出库第 {0} 行物料 {1} 对应多个版本，请传 custom_version 或 sales_order_item。"
						).format(index, item_code)
					)

		if not candidates:
			frappe.throw(_("销售出库第 {0} 行未找到可出库的销售订单明细。").format(index))

		if row_name:
			source_row = candidates[0].doc
			if item_code and source_row.item_code != item_code:
				throw_crm_shipment_identity_conflict(
					_("销售出库第 {0} 行 item_code 与 sales_order_item 不匹配。").format(index)
				)
			if version_supplied and (source_row.get("custom_version") or "") != version:
				throw_crm_shipment_identity_conflict(
					_("销售出库第 {0} 行 custom_version 与销售订单明细不匹配。").format(index)
				)

		qty_to_allocate = flt(request_row.get("qty"))
		for candidate in candidates:
			if qty_to_allocate <= 0:
				break
			allocated_qty = min(qty_to_allocate, flt(candidate.remaining_qty))
			allocations.append(
				frappe._dict(
					sales_order_item=candidate.doc,
					request_row=request_row,
					qty=allocated_qty,
				)
			)
			candidate.remaining_qty = flt(candidate.remaining_qty) - allocated_qty
			qty_to_allocate -= allocated_qty

		if qty_to_allocate > 0.000001:
			frappe.throw(_("销售出库第 {0} 行数量超过销售订单剩余可出库数量。").format(index))

	return allocations


def get_delivery_note_qty_credit(delivery_note, sales_order_name):
	if not delivery_note or delivery_note.docstatus != 1:
		return {}

	quantities = {}
	for row in delivery_note.get("items", []):
		if row.get("against_sales_order") != sales_order_name or not row.get("so_detail"):
			continue
		quantities[row.so_detail] = flt(quantities.get(row.so_detail)) + flt(row.get("qty"))
	return quantities


def get_or_create_crm_delivery_note(sales_order, payload, allocations):
	shipment_no = payload[CRM_SHIPMENT_FIELD]
	existing = get_delivery_note_by_crm_shipment_no(shipment_no)

	if existing:
		validate_crm_delivery_note_identity(existing, sales_order, allocations)
		if existing.docstatus == 2:
			throw_crm_shipment_identity_conflict(
				_("CRM 发货单号 {0} 对应的 ERP 销售出库已取消。").format(shipment_no)
			)
		return existing, existing.docstatus == 1

	return make_crm_delivery_note(sales_order, payload, allocations), False


def get_delivery_note_by_crm_shipment_no(shipment_no):
	if not frappe.db.has_column("Delivery Note", CRM_SHIPMENT_FIELD):
		frappe.throw(_("缺少 CRM 发货单号字段，请先执行 bench migrate。"))

	names = frappe.get_all(
		"Delivery Note",
		filters={CRM_SHIPMENT_FIELD: shipment_no},
		pluck="name",
		limit_page_length=2,
	)
	if len(names) > 1:
		throw_crm_shipment_identity_conflict(
			_("CRM 发货单号 {0} 已对应多张 ERP 销售出库。").format(shipment_no)
		)
	return frappe.get_doc("Delivery Note", names[0]) if names else None


def validate_crm_delivery_note_identity(delivery_note, sales_order, allocations):
	error = get_crm_delivery_note_identity_error(delivery_note, sales_order, allocations)
	if error:
		throw_crm_shipment_identity_conflict(error)


def get_crm_delivery_note_identity_error(delivery_note, sales_order, allocations):
	linked_sales_orders = get_linked_sales_orders(delivery_note)
	if linked_sales_orders != [sales_order.name]:
		return _("ERP 销售出库 {0} 关联的销售订单与本次请求不一致。").format(
			delivery_note.name
		)

	expected_qty = get_allocation_qty_by_sales_order_item(allocations)
	actual_qty = {}
	for row in delivery_note.get("items", []):
		if row.get("against_sales_order") != sales_order.name or not row.get("so_detail"):
			continue
		actual_qty[row.so_detail] = flt(actual_qty.get(row.so_detail)) + flt(row.get("qty"))
	actual_qty = {key: flt(value, 9) for key, value in actual_qty.items()}
	if actual_qty != expected_qty:
		return _("ERP 销售出库 {0} 的明细与本次 CRM 发货数量不一致。").format(
			delivery_note.name
		)

	if not delivery_note_dimensions_match(delivery_note, allocations):
		return _("ERP 销售出库 {0} 的仓库、批次或序列号与本次 CRM 发货不一致。").format(
			delivery_note.name
		)

	return None


def delivery_note_dimensions_match(delivery_note, allocations):
	constraints = {}
	for allocation in allocations:
		warehouse = allocation.request_row.get("warehouse") or None
		batch_no = allocation.request_row.get("batch_no") or None
		serial_no = allocation.request_row.get("serial_no") or None
		serial_and_batch_bundle = allocation.request_row.get("serial_and_batch_bundle") or None
		if not any((warehouse, batch_no, serial_no, serial_and_batch_bundle)):
			continue
		key = (
			allocation.sales_order_item.name,
			warehouse,
			batch_no,
			serial_no,
			serial_and_batch_bundle,
		)
		constraints[key] = flt(constraints.get(key)) + flt(allocation.qty)

	actual_by_so_detail = {}
	for row in delivery_note.get("items", []):
		if not row.get("so_detail"):
			continue
		actual_by_so_detail.setdefault(row.so_detail, []).append(
			frappe._dict(
				warehouse=row.get("warehouse") or None,
				batch_no=row.get("batch_no") or None,
				serial_no=row.get("serial_no") or None,
				serial_and_batch_bundle=row.get("serial_and_batch_bundle") or None,
				remaining_qty=flt(row.get("qty")),
			)
		)

	ordered_constraints = sorted(
		constraints.items(),
		key=lambda entry: sum(value is not None for value in entry[0][1:]),
		reverse=True,
	)
	for (
		so_detail,
		warehouse,
		batch_no,
		serial_no,
		serial_and_batch_bundle,
	), expected_qty in ordered_constraints:
		matching_rows = [
			row
			for row in actual_by_so_detail.get(so_detail, [])
			if row.remaining_qty > 0
			and (not warehouse or row.warehouse == warehouse)
			and (not batch_no or row.batch_no == batch_no)
			and (not serial_no or row.serial_no == serial_no)
			and (
				not serial_and_batch_bundle
				or row.serial_and_batch_bundle == serial_and_batch_bundle
			)
		]
		if flt(sum(row.remaining_qty for row in matching_rows), 9) + 0.000001 < flt(expected_qty, 9):
			return False

		qty_to_consume = flt(expected_qty)
		for row in matching_rows:
			consumed_qty = min(qty_to_consume, row.remaining_qty)
			row.remaining_qty -= consumed_qty
			qty_to_consume -= consumed_qty
			if qty_to_consume <= 0.000001:
				break

	return True


def get_allocation_qty_by_sales_order_item(allocations):
	quantities = {}
	for allocation in allocations:
		row_name = allocation.sales_order_item.name
		quantities[row_name] = flt(quantities.get(row_name)) + flt(allocation.qty)
	return {key: flt(value, 9) for key, value in quantities.items()}


def make_crm_delivery_note(sales_order, payload, allocations):
	delivery_note = make_delivery_note(
		sales_order.name,
		kwargs={"skip_item_mapping": True, "for_reserved_stock": False},
	)
	delivery_note.set("items", [])
	delivery_note.set(CRM_SHIPMENT_FIELD, payload[CRM_SHIPMENT_FIELD])

	for allocation in allocations:
		append_crm_delivery_note_item(delivery_note, sales_order, allocation)

	apply_crm_shipment_header_fields(delivery_note, payload)
	delivery_note.run_method("set_missing_values")
	delivery_note.run_method("set_po_nos")
	delivery_note.run_method("calculate_taxes_and_totals")
	delivery_note.run_method("set_use_serial_batch_fields")
	delivery_note.flags.ignore_permissions = True
	delivery_note.insert(ignore_permissions=True)
	return delivery_note


def append_crm_delivery_note_item(delivery_note, sales_order, allocation):
	source = allocation.sales_order_item
	request_row = allocation.request_row
	qty = flt(allocation.qty)
	conversion_factor = flt(source.get("conversion_factor")) or 1
	warehouse = request_row.get("warehouse") or source.get("warehouse") or sales_order.get("set_warehouse")

	row = delivery_note.append(
		"items",
		{
			"item_code": source.item_code,
			"item_name": source.item_name,
			"description": source.description,
			"qty": qty,
			"stock_qty": qty * conversion_factor,
			"uom": source.uom,
			"stock_uom": source.stock_uom,
			"conversion_factor": conversion_factor,
			"warehouse": warehouse,
			"rate": source.rate,
			"base_rate": source.base_rate,
			"amount": qty * flt(source.rate),
			"base_amount": qty * flt(source.base_rate),
			"against_sales_order": sales_order.name,
			"so_detail": source.name,
			"delivery_date": source.get("delivery_date") or sales_order.get("delivery_date"),
			"custom_version": source.get("custom_version"),
		},
	)

	for fieldname in ("batch_no", "serial_no", "serial_and_batch_bundle"):
		if request_row.get(fieldname):
			row.set(fieldname, request_row.get(fieldname))


def prepare_crm_delivery_note_for_submit(delivery_note, sales_order, payload):
	set_crm_shipment_no(delivery_note, payload[CRM_SHIPMENT_FIELD])
	apply_crm_shipment_header_fields(delivery_note, payload)
	versions = {row.name: row.get("custom_version") for row in sales_order.get("items", [])}
	for row in delivery_note.get("items", []):
		if row.get("so_detail") in versions:
			row.set("custom_version", versions[row.so_detail])

	delivery_note.flags.ignore_permissions = True
	delivery_note.save(ignore_permissions=True)


def apply_crm_shipment_header_fields(delivery_note, payload):
	if payload.get("posting_date"):
		delivery_note.posting_date = getdate(payload["posting_date"])
	if payload.get("posting_time"):
		delivery_note.posting_time = payload["posting_time"]
		delivery_note.set_posting_time = 1


def set_crm_shipment_no(delivery_note, shipment_no):
	current = delivery_note.get(CRM_SHIPMENT_FIELD)
	if current and current != shipment_no:
		throw_crm_shipment_identity_conflict(
			_("ERP 销售出库 {0} 已绑定其他 CRM 发货单号。").format(delivery_note.name)
		)
	if delivery_note.docstatus == 1:
		delivery_note.db_set(CRM_SHIPMENT_FIELD, shipment_no, update_modified=False)
	else:
		delivery_note.set(CRM_SHIPMENT_FIELD, shipment_no)


def release_sales_order_for_crm_shipment(sales_order):
	process_status = sales_order.get("custom_process_status")
	if process_status in (PENDING_PRODUCTION, PENDING_FINAL_PAYMENT):
		set_process_status(sales_order, DELIVERABLE)
		return
	if process_status not in (DELIVERABLE, PARTIALLY_DELIVERED):
		frappe.throw(
			_("销售订单 {0} 当前流程状态为 {1}，不允许执行 CRM 发货。").format(
				sales_order.name, process_status or ""
			)
		)


def get_crm_shipment_response(delivery_note, shipment_no, idempotent_replay=False):
	response = {
		"status": "success",
		"message": _("销售出库已在 ERP 提交并完成库存扣减。"),
		"name": delivery_note.name,
		"crm_shipment_no": shipment_no,
		"docstatus": delivery_note.docstatus,
		"stock_updated": delivery_note.docstatus == 1,
		"timestamp": now(),
	}
	if idempotent_replay:
		response["message"] = _("CRM 发货单已处理，本次请求按幂等方式返回原销售出库。")
		response["idempotent_replay"] = True
	return response


def throw_crm_shipment_identity_conflict(message):
	frappe.response["error_code"] = "ERP_CRM_SHIPMENT_IDENTITY_CONFLICT"
	frappe.throw(
		f"ERP_CRM_SHIPMENT_IDENTITY_CONFLICT: {message}",
		exc=CRMShipmentIdentityConflict,
		title=_("CRM 发货单幂等编号冲突"),
	)


@contextmanager
def crm_shipment_lock(shipment_no):
	if getattr(frappe.db, "db_type", None) != "mariadb":
		yield
		return

	digest = hashlib.sha256(str(shipment_no).encode()).hexdigest()
	lock_name = f"crm-shipment-{digest}"[:64]
	result = frappe.db.sql(
		"SELECT GET_LOCK(%s, %s)",
		(lock_name, CRM_SHIPMENT_LOCK_TIMEOUT),
	)
	if not result or cint(result[0][0]) != 1:
		frappe.throw(_("CRM 发货单号 {0} 正在处理中，请稍后重试。").format(shipment_no))

	def release_lock():
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))

	try:
		yield
	except Exception:
		release_lock()
		raise
	else:
		frappe.db.after_commit.add(release_lock)
		frappe.db.after_rollback.add(release_lock)


def lock_sales_order_for_crm_shipment(sales_order_name):
	frappe.db.sql(
		"SELECT name FROM `tabSales Order` WHERE name = %s FOR UPDATE",
		(sales_order_name,),
	)


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
		if doc.docstatus == 1 and not doc.get(CRM_SHIPMENT_FIELD):
			enqueue_crm_delivery_note_shipment_event(
				doc, sales_order_name, process_status
			)
		elif doc.docstatus == 2:
			enqueue_crm_delivery_note_cancellation_event(
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


def enqueue_crm_delivery_note_cancellation_event(doc, sales_order_name, process_status):
	items = get_delivery_note_shipment_items(doc, sales_order_name)
	if not items:
		return

	try:
		enqueue_sales_order_status_to_crm(
			sales_order_name=sales_order_name,
			external_status=CRM_STATUS_SHIPMENT_CANCELLED,
			triggered_status=process_status,
			trigger_event="delivery_note_cancelled",
			delivery_note_name=doc.name,
			items=items,
			remark=_("销售出库 {0} 已取消，ERP流程状态：{1}").format(
				doc.name, process_status
			),
		)
	except Exception:
		frappe.log_error(
			title="Failed to enqueue CRM Delivery Note cancellation event",
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
	except ModuleNotFoundError as exc:
		if is_missing_mes_integration_error(exc):
			return
		raise
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
