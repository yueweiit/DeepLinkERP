"""Frappe service for the audited LatinGo purchase-expense backfill."""

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP

try:  # Pure unit tests run outside a bench environment.
	import frappe
except ModuleNotFoundError:  # pragma: no cover - exercised by service tests through injection
	frappe = None

from oa_purchase_request.latingo_backfill_domain import (
	BACKFILL_END_DATE,
	BACKFILL_START_DATE,
	GENERIC_PURCHASE_PROCESS_CODE,
	LATINGO_COMPANY,
	LATINGO_COST_CENTER,
	LATINGO_INPUT_TAX_ACCOUNT,
	LATINGO_PURCHASE_PROCESS_CODE,
	LATINGO_WAREHOUSE,
	SERVICE_ITEM_GROUP,
	SERVICE_UOM,
	TEMP_SUPPLIER,
	TEMP_SUPPLIER_GROUP,
	build_approval_plan,
	build_preview_fingerprint,
	build_source_fingerprint,
	iter_archive_month_windows,
	is_generic_organization_in_scope,
	source_from_instance,
	submission_blockers,
)


def _whitelist(function=None, **options):
	if frappe is None:
		return function if function is not None else (lambda wrapped: wrapped)
	decorator = frappe.whitelist(**options)
	return decorator(function) if function is not None else decorator


def _validate_backfill_range(start_date, end_date) -> None:
	if str(start_date) != BACKFILL_START_DATE or str(end_date) != BACKFILL_END_DATE:
		raise ValueError(
			f"拉丁购历史回填固定范围为 {BACKFILL_START_DATE} 至 {BACKFILL_END_DATE}"
		)


def _merged_purchase_row(raw_row: dict, mapped_row: dict) -> dict:
	"""Retain source evidence while preferring the shared parser's canonical values."""

	return {
		**raw_row,
		"item_code": mapped_row.get("material_code") or mapped_row.get("item_code"),
		"item_name": mapped_row.get("product_name") or mapped_row.get("item_name"),
		"description": mapped_row.get("spec_model") or mapped_row.get("description"),
		"qty": mapped_row.get("quantity") if mapped_row.get("quantity") not in (None, "") else raw_row.get("数量"),
		"uom": mapped_row.get("unit") or mapped_row.get("uom") or raw_row.get("单位"),
		"amount": (
			mapped_row.get("goods_value")
			if mapped_row.get("goods_value") not in (None, "")
			else mapped_row.get("amount")
		),
		"rate": mapped_row.get("unit_price") or mapped_row.get("rate"),
	}


def collect_backfill_plans(
	start_date,
	end_date,
	*,
	source,
	extract_form_fields,
	extract_purchase_rows,
	map_purchase_row,
) -> dict:
	"""Read both approved source templates in monthly windows and build plans."""

	instances_by_id = {}
	duplicate_ids = set()
	updated_values = []
	lag_values = []
	for window_start, window_end in iter_archive_month_windows(start_date, end_date):
		for process_code in (LATINGO_PURCHASE_PROCESS_CODE, GENERIC_PURCHASE_PROCESS_CODE):
			result = source.list_instances(
				process_code=process_code,
				start=window_start,
				end=window_end,
				limit=10000,
			)
			if result.get("source_updated_at"):
				updated_values.append(str(result.get("source_updated_at")))
			if result.get("source_lag_seconds") is not None:
				lag_values.append(int(result.get("source_lag_seconds")))
			for instance in result.get("items") or []:
				instance_id = str(
					instance.get("processInstanceId") or instance.get("process_instance_id") or ""
				).strip()
				if not instance_id:
					continue
				if instance_id in instances_by_id:
					duplicate_ids.add(instance_id)
				instances_by_id[instance_id] = instance

	plans = []
	out_of_scope_count = 0
	out_of_date_count = 0
	for instance_id in sorted(instances_by_id):
		instance = instances_by_id[instance_id]
		fields = extract_form_fields(instance)
		raw_rows = extract_purchase_rows(instance)
		detail_rows = [
			_merged_purchase_row(row, map_purchase_row(row))
			for row in raw_rows
			if isinstance(row, dict)
		]
		source_record = source_from_instance(instance, fields=fields, detail_rows=detail_rows)
		if (
			source_record.get("process_code") == GENERIC_PURCHASE_PROCESS_CODE
			and not is_generic_organization_in_scope(source_record.get("organization"))
		):
			out_of_scope_count += 1
			continue
		plan = build_approval_plan(source_record, start_date, end_date)
		if plan.get("exclusion_reason") == "申请日期超出范围":
			out_of_date_count += 1
			continue
		plan["source_fingerprint"] = build_source_fingerprint(plan)
		plan["source_fields"] = fields
		plan["source_snapshot"] = instance
		plans.append(plan)

	return {
		"plans": plans,
		"duplicate_source_ids": sorted(duplicate_ids),
		"out_of_scope_count": out_of_scope_count,
		"out_of_date_count": out_of_date_count,
		"source_updated_at": max(updated_values) if updated_values else None,
		"source_lag_seconds": max(lag_values) if lag_values else None,
		"fingerprint": build_preview_fingerprint(plans),
	}


def analyze_backfill_state(plans, *, item_lookup, oa_by_process, oa_by_business) -> dict:
	"""Read-only idempotency and Item-ownership preflight."""

	conflicts = []
	existing = []
	for plan in plans:
		if not plan.get("included"):
			continue
		instance_id = plan.get("process_instance_id") or ""
		business_id = plan.get("business_id") or ""
		oa_row = oa_by_process(instance_id)
		if oa_row:
			if (oa_row.get("source_fingerprint") or "") != (plan.get("source_fingerprint") or ""):
				conflicts.append(f"来源实例 {instance_id} 已存在但来源指纹不同")
			elif not (
				oa_row.get("purchase_order_exists")
				if oa_row.get("purchase_order_exists") is not None
				else bool(oa_row.get("purchase_order"))
			):
				conflicts.append(f"来源实例 {instance_id} 已存在但未关联有效采购订单")
			else:
				existing.append(
					{
						"process_instance_id": instance_id,
						"oa_request": oa_row.get("name") or "",
						"purchase_order": oa_row.get("purchase_order") or "",
					}
				)
			continue
		business_row = oa_by_business(business_id)
		if business_row and (business_row.get("process_instance_id") or "") != instance_id:
			conflicts.append(f"审批编号 {business_id} 已被另一来源实例占用")

	item_specs = {}
	for plan in plans:
		if not plan.get("included"):
			continue
		for item in plan.get("items") or []:
			item_code = item.get("item_code") or ""
			if item_code:
				item_specs.setdefault(item_code, item)

	item_actions = []
	for item_code in sorted(item_specs):
		existing_item = item_lookup(item_code)
		if not existing_item:
			item_actions.append({"item_code": item_code, "action": "create"})
			continue
		owner = (existing_item.get("custom_overseas_business_entity") or "").strip()
		if not owner:
			item_actions.append({"item_code": item_code, "action": "update_ownership"})
		elif owner == "拉丁购国际电子商务（东莞）有限公司":
			item_actions.append({"item_code": item_code, "action": "reuse"})
		else:
			item_actions.append({"item_code": item_code, "action": "conflict", "existing_owner": owner})
			conflicts.append(f"物料 {item_code} 已属于其他子公司")

	return {
		"item_actions": item_actions,
		"existing": existing,
		"conflicts": sorted(set(conflicts)),
	}


def assert_apply_safe(preview: dict, expected_fingerprint: str) -> None:
	if not expected_fingerprint or preview.get("fingerprint") != expected_fingerprint:
		raise ValueError("预览指纹已变化，请重新预览并确认")
	if preview.get("conflicts"):
		raise ValueError("；".join(preview.get("conflicts") or []))


def _assert_system_manager() -> None:
	if frappe is None:
		raise RuntimeError("Frappe runtime is required")
	user = frappe.session.user
	if user != "Administrator" and "System Manager" not in frappe.get_roles(user):
		frappe.throw("仅 Administrator 或 System Manager 可以执行拉丁购历史回填")


def _collect_from_archive(start_date, end_date) -> dict:
	from overseas_costing.scripts.import_oa_logistics import (
		_get_postgres_approval_source,
		extract_form_fields,
		extract_purchase_expense_rows,
	)
	from overseas_costing.utils.field_mapper import map_purchase_expense_row_to_item

	return collect_backfill_plans(
		start_date,
		end_date,
		source=_get_postgres_approval_source(),
		extract_form_fields=extract_form_fields,
		extract_purchase_rows=extract_purchase_expense_rows,
		map_purchase_row=map_purchase_expense_row_to_item,
	)


def _get_item_for_preflight(item_code):
	return frappe.db.get_value(
		"Item",
		item_code,
		["name", "custom_overseas_business_entity"],
		as_dict=True,
	)


def _get_oa_for_preflight(filters):
	row = frappe.db.get_value(
		"OA Purchase Request",
		filters,
		["name", "process_instance_id", "source_fingerprint", "purchase_order"],
		as_dict=True,
	)
	if row:
		row["purchase_order_exists"] = bool(
			row.get("purchase_order") and frappe.db.exists("Purchase Order", row.get("purchase_order"))
		)
	return row


def _preview_counts(plans) -> dict:
	eligible = [plan for plan in plans if plan.get("included")]
	return {
		"scanned": len(plans),
		"eligible": len(eligible),
		"excluded": len(plans) - len(eligible),
		"completed": sum(not (plan.get("review_flags") or {}).get("source_pending") for plan in eligible),
		"running": sum(bool((plan.get("review_flags") or {}).get("source_pending")) for plan in eligible),
		"physical_orders": sum(plan.get("source_kind") == "physical" for plan in eligible),
		"service_orders": sum(plan.get("source_kind") == "service" for plan in eligible),
		"CNY": sum(plan.get("currency") == "CNY" for plan in eligible),
		"MXN": sum(plan.get("currency") == "MXN" for plan in eligible),
	}


def _master_data_preflight(plans) -> dict:
	actions = []
	for doctype, name in (
		("Supplier Group", TEMP_SUPPLIER_GROUP),
		("Item Group", SERVICE_ITEM_GROUP),
		("UOM", SERVICE_UOM),
		("Supplier", TEMP_SUPPLIER),
	):
		actions.append(
			{
				"doctype": doctype,
				"name": name,
				"action": "reuse" if frappe.db.exists(doctype, name) else "create",
			}
		)

	conflicts = []
	for doctype, name in (
		("Company", LATINGO_COMPANY),
		("Warehouse", LATINGO_WAREHOUSE),
		("Cost Center", LATINGO_COST_CENTER),
	):
		if not frappe.db.exists(doctype, name):
			conflicts.append(f"{doctype} 不存在：{name}")
	if any(plan.get("taxes") for plan in plans) and not frappe.db.exists("Account", LATINGO_INPUT_TAX_ACCOUNT):
		conflicts.append(f"税费科目不存在：{LATINGO_INPUT_TAX_ACCOUNT}")

	for item in _item_specs(plans).values():
		if item.get("item_group") != SERVICE_ITEM_GROUP and not frappe.db.exists("Item Group", item.get("item_group")):
			conflicts.append(f"物料组不存在：{item.get('item_group')}")
		if item.get("stock_uom") != SERVICE_UOM and not frappe.db.exists("UOM", item.get("stock_uom")):
			conflicts.append(f"单位不存在：{item.get('stock_uom')}")
	return {"actions": actions, "conflicts": sorted(set(conflicts))}


def _build_preview(start_date, end_date) -> dict:
	collection = _collect_from_archive(start_date, end_date)
	plans = collection.get("plans") or []
	state = analyze_backfill_state(
		plans,
		item_lookup=_get_item_for_preflight,
		oa_by_process=lambda instance_id: _get_oa_for_preflight({"process_instance_id": instance_id}),
		oa_by_business=lambda business_id: _get_oa_for_preflight({"oa_code": business_id}),
	)
	eligible = [plan for plan in plans if plan.get("included")]
	excluded = [plan for plan in plans if not plan.get("included")]
	master_state = _master_data_preflight(eligible)
	conflicts = sorted(set(state["conflicts"] + master_state["conflicts"]))
	warnings = [
		{
			"process_instance_id": plan.get("process_instance_id"),
			"business_id": plan.get("business_id"),
			"warnings": plan.get("warnings"),
		}
		for plan in eligible
		if plan.get("warnings")
	]
	return {
		"ok": not conflicts,
		"dry_run": True,
		"start_date": str(start_date),
		"end_date": str(end_date),
		"fingerprint": collection.get("fingerprint"),
		"source_updated_at": collection.get("source_updated_at"),
		"source_lag_seconds": collection.get("source_lag_seconds"),
		"counts": _preview_counts(plans),
		"eligible": eligible,
		"excluded": excluded,
		"item_actions": state["item_actions"],
		"master_data_actions": master_state["actions"],
		"existing": state["existing"],
		"conflicts": conflicts,
		"warnings": warnings,
		"duplicate_source_ids": collection.get("duplicate_source_ids") or [],
		"out_of_scope_count": collection.get("out_of_scope_count") or 0,
		"out_of_date_count": collection.get("out_of_date_count") or 0,
	}


@_whitelist(methods=["GET"])
def preview_latingo_purchase_backfill(start_date, end_date):
	"""Strictly read-only preview of the LatinGo approval backfill."""

	_assert_system_manager()
	_validate_backfill_range(start_date, end_date)
	return _without_raw_snapshots(_build_preview(start_date, end_date))


def _without_raw_snapshots(value):
	if isinstance(value, dict):
		return {
			key: _without_raw_snapshots(item)
			for key, item in value.items()
			if key not in {"source_snapshot", "source_fields"}
		}
	if isinstance(value, list):
		return [_without_raw_snapshots(item) for item in value]
	return value


def _root_group(doctype: str, parent_field: str):
	return frappe.db.get_value(doctype, {"is_group": 1, parent_field: ["is", "not set"]}, "name") or frappe.db.get_value(
		doctype,
		{"is_group": 1},
		"name",
	)


def _ensure_supplier_group():
	if frappe.db.exists("Supplier Group", TEMP_SUPPLIER_GROUP):
		return
	doc = frappe.new_doc("Supplier Group")
	doc.supplier_group_name = TEMP_SUPPLIER_GROUP
	doc.is_group = 0
	doc.parent_supplier_group = _root_group("Supplier Group", "parent_supplier_group")
	doc.insert(ignore_permissions=True)


def _ensure_service_item_group():
	if frappe.db.exists("Item Group", SERVICE_ITEM_GROUP):
		return
	doc = frappe.new_doc("Item Group")
	doc.item_group_name = SERVICE_ITEM_GROUP
	doc.is_group = 0
	doc.parent_item_group = _root_group("Item Group", "parent_item_group")
	doc.insert(ignore_permissions=True)


def _ensure_service_uom():
	if frappe.db.exists("UOM", SERVICE_UOM):
		return
	doc = frappe.new_doc("UOM")
	doc.uom_name = SERVICE_UOM
	doc.enabled = 1
	doc.insert(ignore_permissions=True)


def _ensure_temporary_supplier():
	if frappe.db.exists("Supplier", TEMP_SUPPLIER):
		return
	doc = frappe.new_doc("Supplier")
	doc.supplier_name = TEMP_SUPPLIER
	doc.supplier_type = "Company"
	doc.supplier_group = TEMP_SUPPLIER_GROUP
	doc.insert(ignore_permissions=True)


def _item_specs(plans):
	specs = {}
	for plan in plans:
		for item in plan.get("items") or []:
			if item.get("item_code"):
				specs.setdefault(item["item_code"], item)
	return specs


def _ensure_item(item: dict):
	item_code = item["item_code"]
	if frappe.db.exists("Item", item_code):
		owner = frappe.db.get_value("Item", item_code, "custom_overseas_business_entity") or ""
		if owner and owner != LATINGO_COMPANY:
			raise ValueError(f"物料 {item_code} 已属于其他子公司")
		if not owner:
			frappe.db.set_value(
				"Item",
				item_code,
				"custom_overseas_business_entity",
				LATINGO_COMPANY,
				update_modified=False,
			)
		return

	if not frappe.db.exists("Item Group", item["item_group"]):
		raise ValueError(f"物料组不存在：{item['item_group']}")
	if not frappe.db.exists("UOM", item["stock_uom"]):
		raise ValueError(f"单位不存在：{item['stock_uom']}")
	doc = frappe.new_doc("Item")
	doc.item_code = item_code
	doc.item_name = item.get("item_name") or item_code
	doc.description = item.get("description") or item.get("item_name") or item_code
	doc.item_group = item["item_group"]
	doc.stock_uom = item["stock_uom"]
	doc.is_stock_item = int(bool(item.get("is_stock_item")))
	doc.custom_overseas_business_entity = LATINGO_COMPANY
	doc.insert(ignore_permissions=True)


def _ensure_master_data(plans):
	for doctype, name in (
		("Company", LATINGO_COMPANY),
		("Warehouse", LATINGO_WAREHOUSE),
		("Cost Center", LATINGO_COST_CENTER),
	):
		if not frappe.db.exists(doctype, name):
			raise ValueError(f"{doctype} 不存在：{name}")
	if any(plan.get("taxes") for plan in plans) and not frappe.db.exists("Account", LATINGO_INPUT_TAX_ACCOUNT):
		raise ValueError(f"税费科目不存在：{LATINGO_INPUT_TAX_ACCOUNT}")

	_ensure_supplier_group()
	_ensure_service_item_group()
	_ensure_service_uom()
	_ensure_temporary_supplier()
	for item in _item_specs(plans).values():
		_ensure_item(item)


def _source_state(plan):
	flags = plan.get("review_flags") or {}
	if flags.get("source_invalid"):
		return "来源失效"
	if flags.get("source_stale"):
		return "来源已变化"
	if any(flags.values()):
		return "待复核"
	return "已建草稿"


def _create_oa_request(plan: dict):
	snapshot = plan.get("source_snapshot") or {}
	fields = plan.get("source_fields") or {}
	flags = plan.get("review_flags") or {}
	doc = frappe.new_doc("OA Purchase Request")
	doc.oa_code = plan["business_id"]
	doc.apply_date = plan["apply_date"]
	doc.department = plan.get("organization")
	doc.description = plan.get("description")
	doc.delivery_date = plan.get("schedule_date")
	doc.payee = plan.get("payee")
	doc.payment_amount = plan.get("header_amount")
	doc.currency = plan.get("currency")
	doc.approval_completed_at = snapshot.get("finishTime") or snapshot.get("finish_time") or ""
	doc.approval_status = plan.get("status")
	doc.creator = snapshot.get("originatorUserName") or snapshot.get("originator_user_name") or ""
	doc.created_time = snapshot.get("createTime") or snapshot.get("create_time") or ""
	doc.updated_time = snapshot.get("updatedAt") or snapshot.get("updated_at") or ""
	doc.process_instance_id = plan["process_instance_id"]
	doc.process_code = plan["process_code"]
	doc.form_name = snapshot.get("title") or ""
	doc.raw_payload = json.dumps(snapshot, ensure_ascii=False, default=str)
	doc.sync_status = "待复核"
	doc.source_fingerprint = plan.get("source_fingerprint")
	doc.latest_source_fingerprint = plan.get("source_fingerprint")
	doc.target_company = LATINGO_COMPANY
	doc.target_warehouse = LATINGO_WAREHOUSE if plan.get("source_kind") == "physical" else ""
	doc.temporary_supplier = TEMP_SUPPLIER
	doc.original_payee = plan.get("payee")
	doc.source_currency = plan.get("currency")
	doc.source_exchange_rate = plan.get("conversion_rate")
	doc.source_state = _source_state(plan)
	doc.source_pending = int(bool(flags.get("source_pending")))
	doc.source_stale = int(bool(flags.get("source_stale")))
	doc.source_invalid = int(bool(flags.get("source_invalid")))
	doc.exchange_rate_pending = int(bool(flags.get("exchange_rate_pending")))
	doc.price_pending = int(bool(flags.get("price_pending")))
	doc.temporary_supplier_pending = 1
	doc.backfill_imported = 1
	doc.error_message = "\n".join(plan.get("warnings") or [])
	for item in plan.get("items") or []:
		doc.append(
			"items",
			{
				"item_name": item.get("item_name") or item.get("item_code"),
				"item_code": item.get("item_code"),
				"specification": item.get("description"),
				"qty": item.get("qty"),
				"uom": item.get("stock_uom"),
				"amount": item.get("amount"),
			},
		)
	doc.insert(ignore_permissions=True)
	return doc


def _create_purchase_order(plan: dict, oa_doc):
	flags = plan.get("review_flags") or {}
	doc = frappe.new_doc("Purchase Order")
	doc.supplier = TEMP_SUPPLIER
	doc.company = LATINGO_COMPANY
	doc.transaction_date = plan["transaction_date"]
	doc.schedule_date = plan["schedule_date"]
	doc.currency = plan["currency"]
	doc.conversion_rate = plan["conversion_rate"]
	if plan.get("source_kind") == "physical":
		doc.set_warehouse = LATINGO_WAREHOUSE
	doc.custom_oa_purchase_expense = oa_doc.name
	doc.custom_latingo_backfill = 1
	doc.custom_latingo_source_instance_id = plan["process_instance_id"]
	doc.custom_latingo_source_fingerprint = plan.get("source_fingerprint")
	doc.custom_latingo_source_status = plan.get("status")
	doc.custom_latingo_source_result = plan.get("result")
	doc.custom_latingo_source_pending = int(bool(flags.get("source_pending")))
	doc.custom_latingo_source_stale = int(bool(flags.get("source_stale")))
	doc.custom_latingo_source_invalid = int(bool(flags.get("source_invalid")))
	doc.custom_latingo_exchange_rate_pending = int(bool(flags.get("exchange_rate_pending")))
	doc.custom_latingo_price_pending = int(bool(flags.get("price_pending")))
	doc.custom_latingo_temporary_supplier_pending = 1
	doc.custom_latingo_original_payee = plan.get("payee")
	for item in plan.get("items") or []:
		row = {
			"item_code": item["item_code"],
			"item_name": item.get("item_name") or item["item_code"],
			"description": item.get("description") or item["item_code"],
			"qty": item["qty"],
			"uom": item["stock_uom"],
			"stock_uom": item["stock_uom"],
			"conversion_factor": 1,
			"rate": item["rate"],
			"schedule_date": plan["schedule_date"],
			"cost_center": LATINGO_COST_CENTER,
		}
		if item.get("warehouse"):
			row["warehouse"] = item["warehouse"]
		doc.append("items", row)
	for tax in plan.get("taxes") or []:
		doc.append("taxes", {"category": "Total", "add_deduct_tax": "Add", **tax})
	_reconcile_purchase_order_total(doc, plan.get("grand_total"))
	doc.insert(ignore_permissions=True)
	return doc


def _reconcile_purchase_order_total(doc, expected_grand_total) -> None:
	"""Offset ERPNext's currency-precision line rounding at order level."""

	doc.run_method("calculate_taxes_and_totals")
	adjustment = (
		Decimal(str(doc.get("grand_total") or 0)) - Decimal(str(expected_grand_total or 0))
	).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	if adjustment:
		doc.apply_discount_on = "Grand Total"
		doc.discount_amount = float(adjustment)


def _create_backfill_pair(plan: dict) -> dict:
	oa_doc = _create_oa_request(plan)
	purchase_order = _create_purchase_order(plan, oa_doc)
	frappe.db.set_value(
		"OA Purchase Request",
		oa_doc.name,
		{"purchase_order": purchase_order.name, "sync_status": "已建草稿"},
		update_modified=False,
	)
	return {
		"process_instance_id": plan["process_instance_id"],
		"oa_request": oa_doc.name,
		"purchase_order": purchase_order.name,
	}


@_whitelist(methods=["POST"])
def apply_latingo_purchase_backfill(start_date, end_date, expected_fingerprint):
	"""Atomically create all missing OA requests and draft purchase orders."""

	_assert_system_manager()
	_validate_backfill_range(start_date, end_date)
	lock_name = "oa_purchase_request:latingo_purchase_backfill"
	lock_rows = frappe.db.sql("select get_lock(%s, 15)", (lock_name,))
	if not lock_rows or int(lock_rows[0][0] or 0) != 1:
		frappe.throw("另一个拉丁购历史回填任务正在执行，请稍后重试")
	try:
		preview = _build_preview(start_date, end_date)
		assert_apply_safe(preview, expected_fingerprint)
		existing_by_id = {row["process_instance_id"]: row for row in preview.get("existing") or []}
		missing = [
			plan
			for plan in preview.get("eligible") or []
			if plan.get("process_instance_id") not in existing_by_id
		]
		if not missing:
			return {
				"ok": True,
				"fingerprint": preview["fingerprint"],
				"created": [],
				"reused": list(existing_by_id.values()),
				"failed": [],
				"warnings": preview.get("warnings") or [],
			}

		frappe.db.savepoint("latingo_purchase_backfill")
		try:
			_ensure_master_data(missing)
			created = [_create_backfill_pair(plan) for plan in missing]
		except Exception as exc:
			frappe.db.rollback(save_point="latingo_purchase_backfill")
			if hasattr(frappe, "log_error"):
				frappe.log_error(title="LatinGo purchase backfill failed", message=frappe.get_traceback())
			return {
				"ok": False,
				"fingerprint": preview["fingerprint"],
				"created": [],
				"reused": list(existing_by_id.values()),
				"failed": [{"message": str(exc)}],
				"warnings": preview.get("warnings") or [],
			}
		return {
			"ok": True,
			"fingerprint": preview["fingerprint"],
			"created": created,
			"reused": list(existing_by_id.values()),
			"failed": [],
			"warnings": preview.get("warnings") or [],
		}
	finally:
		frappe.db.sql("select release_lock(%s)", (lock_name,))


def _current_source_plan(process_instance_id: str) -> dict | None:
	from overseas_costing.scripts.import_oa_logistics import (
		_get_postgres_approval_source,
		extract_form_fields,
		extract_purchase_expense_rows,
	)
	from overseas_costing.utils.field_mapper import map_purchase_expense_row_to_item

	instance = _get_postgres_approval_source().get_instances([process_instance_id]).get(process_instance_id)
	if not instance:
		return None
	fields = extract_form_fields(instance)
	detail_rows = [
		_merged_purchase_row(row, map_purchase_expense_row_to_item(row))
		for row in extract_purchase_expense_rows(instance)
		if isinstance(row, dict)
	]
	source_record = source_from_instance(instance, fields=fields, detail_rows=detail_rows)
	plan = build_approval_plan(source_record, BACKFILL_START_DATE, BACKFILL_END_DATE)
	plan["source_fingerprint"] = build_source_fingerprint(plan)
	return plan


def _refresh_oa_source_internal(docname: str) -> dict:
	oa_doc = frappe.get_doc("OA Purchase Request", docname)
	if not oa_doc.get("backfill_imported"):
		raise ValueError("refresh_oa_purchase_source 仅支持拉丁购历史回填记录")
	process_instance_id = (oa_doc.get("process_instance_id") or "").strip()
	if not process_instance_id:
		raise ValueError("OA Purchase Request 缺少 process_instance_id")
	plan = _current_source_plan(process_instance_id)
	if not plan:
		result = {
			"source_pending": False,
			"source_stale": True,
			"source_invalid": True,
			"latest_source_fingerprint": "",
			"source_state": "来源失效",
			"approval_status": "SOURCE_MISSING",
			"approval_result": "",
		}
	else:
		latest = plan.get("source_fingerprint") or ""
		original = oa_doc.get("source_fingerprint") or ""
		result = {
			"source_pending": bool((plan.get("review_flags") or {}).get("source_pending")),
			"source_stale": latest != original,
			"source_invalid": not bool(plan.get("included")),
			"latest_source_fingerprint": latest,
			"source_state": "来源失效" if not plan.get("included") else ("来源已变化" if latest != original else _source_state(plan)),
			"approval_status": plan.get("status") or "",
			"approval_result": plan.get("result") or "",
		}

	oa_values = {
		"approval_status": result["approval_status"],
		"latest_source_fingerprint": result["latest_source_fingerprint"],
		"source_state": result["source_state"],
		"source_pending": int(result["source_pending"]),
		"source_stale": int(result["source_stale"]),
		"source_invalid": int(result["source_invalid"]),
	}
	frappe.db.set_value("OA Purchase Request", oa_doc.name, oa_values, update_modified=False)
	purchase_order = oa_doc.get("purchase_order")
	if purchase_order and frappe.db.exists("Purchase Order", purchase_order):
		frappe.db.set_value(
			"Purchase Order",
			purchase_order,
			{
				"custom_latingo_source_status": result["approval_status"],
				"custom_latingo_source_result": result["approval_result"],
				"custom_latingo_source_pending": int(result["source_pending"]),
				"custom_latingo_source_stale": int(result["source_stale"]),
				"custom_latingo_source_invalid": int(result["source_invalid"]),
			},
			update_modified=False,
		)
	return result


@_whitelist(methods=["POST"])
def refresh_oa_purchase_source(docname):
	"""Refresh source status only; never overwrite manually edited business values."""

	_assert_system_manager()
	doc = frappe.get_doc("OA Purchase Request", docname)
	doc.check_permission("write")
	return _refresh_oa_source_internal(docname)


def sync_latingo_purchase_order_review_flags(doc, method=None):
	if not doc.get("custom_latingo_backfill"):
		return
	values = {
		"custom_latingo_temporary_supplier_pending": int(doc.get("supplier") == TEMP_SUPPLIER),
		"custom_latingo_price_pending": int(
			any(float(row.get("rate") or 0) <= 0 for row in doc.get("items") or [])
		),
	}
	for fieldname, value in values.items():
		setter = getattr(doc, "set", None)
		if callable(setter):
			setter(fieldname, value)
		else:
			doc[fieldname] = value


def validate_latingo_purchase_order_submission(doc, method=None):
	"""Block submission while any source or human review gate is unresolved."""

	if not doc.get("custom_latingo_backfill"):
		return
	oa_request = doc.get("custom_oa_purchase_expense")
	if not oa_request:
		frappe.throw("拉丁购历史回填采购订单缺少 OA Purchase Request 来源")
	try:
		fresh = _refresh_oa_source_internal(oa_request)
	except Exception as exc:
		frappe.throw(f"无法复核采购支出来源，禁止提交：{exc}")

	flags = {
		"source_pending": bool(fresh.get("source_pending")),
		"source_stale": bool(fresh.get("source_stale")),
		"source_invalid": bool(fresh.get("source_invalid")),
		"temporary_supplier": doc.get("supplier") == TEMP_SUPPLIER,
		"exchange_rate_pending": bool(doc.get("custom_latingo_exchange_rate_pending")),
		"price_pending": any(float(row.get("rate") or 0) <= 0 for row in doc.get("items") or []),
	}
	blockers = submission_blockers({"review_flags": flags})
	if blockers:
		frappe.throw("该采购订单仍有待复核事项，不能提交：" + "；".join(blockers))
