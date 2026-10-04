"""Permission-aware, read-only purchase orders and optional OA requests view."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

try:
	import frappe
	import frappe.permissions
	from frappe.model import get_permitted_fields
except ImportError:  # Local pure tests do not require a Frappe installation.
	frappe = None
	get_permitted_fields = None


PURCHASE_ORDER = "Purchase Order"
OA_REQUEST = "OA Purchase Request"
DEFAULT_PAGE_LENGTH = 100
MAX_PAGE_LENGTH = 2500
PO_FIELDS = (
	"name", "transaction_date", "supplier", "supplier_name", "status", "company", "currency",
	"grand_total", "advance_paid", "party_account_currency", "advance_payment_status",
	"per_received", "per_billed", "schedule_date", "project", "owner", "docstatus",
)
PO_QUERY_FIELDS = (*PO_FIELDS, "custom_oa_purchase_expense")
OA_QUERY_FIELDS = (
	"name", "oa_code", "apply_date", "creation", "target_company", "currency",
	"detail_total_amount", "processor_total_amount", "payment_amount", "purchase_order",
	"approval_status", "sync_status", "process_instance_id", "owner", "order_no",
)
AMOUNT_FIELDS = (
	("detail_total_amount", "采购明细合计"),
	("processor_total_amount", "加工合计"),
	("payment_amount", "付款申请金额"),
)
CURRENCY_ALIASES = {"人民币RMB": "CNY", "比索Peso": "MXN"}
RECOGNIZED_CURRENCIES = frozenset({
	"CNY", "MXN", "USD", "EUR", "GBP", "HKD", "JPY", "CAD", "AUD", "NZD", "CHF",
	"SGD", "TWD", "KRW", "INR", "BRL", "ZAR", "AED", "SAR", "THB", "VND", "IDR",
	"MYR", "PHP", "RUB", "SEK", "NOK", "DKK", "PLN", "CZK", "TRY", "CLP", "COP", "PEN",
})
EXPORT_LABELS = {
	"name": "单号", "transaction_date": "日期", "supplier": "供应商编码",
	"supplier_name": "供应商", "status": "订单状态", "company": "公司", "currency": "订单币种",
	"grand_total": "订单金额", "advance_paid": "已预付", "party_account_currency": "预付款币种",
	"advance_payment_status": "预付款状态", "per_received": "已收货%", "per_billed": "已开票%",
	"schedule_date": "需求日期", "project": "项目", "owner": "创建人", "docstatus": "单据状态",
	"source": "来源", "oa_name": "OA 记录", "oa_number": "OA 审批号", "approval_status": "审批状态",
	"oa_amount": "OA 申请金额", "oa_currency": "OA 币种", "oa_amount_basis": "OA 金额口径",
	"oa_warning": "OA 提示", "oa_references": "OA 来源明细", "row_type": "类型",
}
DEFAULT_EXPORT_COLUMNS = (
	"transaction_date", "name", "supplier_name", "status", "company", "source", "oa_number",
	"approval_status", "currency", "grand_total", "oa_currency", "oa_amount", "oa_amount_basis",
	"advance_paid", "party_account_currency", "advance_payment_status", "per_received", "per_billed",
	"schedule_date", "project", "owner", "oa_warning", "oa_references",
)
SORT_FIELDS = (frozenset(EXPORT_LABELS) - {"oa_references"}) | {"row_key"}
NUMERIC_FIELDS = frozenset({"grand_total", "oa_amount", "advance_paid", "per_received", "per_billed", "docstatus"})


def _whitelist(function):
	return frappe.whitelist()(function) if frappe is not None else function


def _text(value: Any) -> str:
	return "" if value is None else str(value).strip()


def _date(value: Any) -> str:
	return _text(value.isoformat() if hasattr(value, "isoformat") else value)[:10]


def _integer(value: Any, *, minimum: int, maximum: int | None = None) -> int:
	if isinstance(value, bool) or not re.fullmatch(r"\+?\d+", str(value).strip()):
		raise ValueError("分页参数必须是整数。")
	parsed = int(value)
	if parsed < minimum or (maximum is not None and parsed > maximum):
		raise ValueError(f"分页参数必须在 {minimum} 到 {maximum or '无限制'} 之间。")
	return parsed


def _filters(value: Any) -> dict[str, Any]:
	if isinstance(value, str):
		value = json.loads(value or "{}")
	if value is not None and not isinstance(value, dict):
		raise ValueError("筛选条件必须是对象。")
	parsed = dict(value or {})
	parsed["scope"] = _text(parsed.get("scope")) or "all"
	parsed["source"] = _text(parsed.get("source")).lower()
	if parsed["scope"] not in {"all", "orders", "oa"}:
		raise ValueError("不支持的采购查看范围。")
	if parsed["source"] not in {"", "oa", "non_oa"}:
		raise ValueError("不支持的采购来源。")
	for key in ("from_date", "to_date"):
		if parsed.get(key) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", _text(parsed[key])):
			raise ValueError("采购日期必须使用 YYYY-MM-DD。")
	return parsed


def _sort_spec(order_by: str) -> tuple[str, bool]:
	parts = _text(order_by).split()
	if len(parts) != 2 or parts[0] not in SORT_FIELDS or parts[1].lower() not in {"asc", "desc"}:
		raise ValueError("不支持的采购排序。")
	return parts[0], parts[1].lower() == "desc"


def _number(value: Any) -> Decimal | None:
	if value is None or value == "" or isinstance(value, bool):
		return None
	try:
		number = Decimal(str(value))
	except (InvalidOperation, ValueError):
		return None
	return number if number.is_finite() else None


def _oa_amount(request: dict) -> tuple[Any, str | None, str | None]:
	available = []
	for fieldname, basis in AMOUNT_FIELDS:
		if fieldname not in request:
			return None, None, "无权查看完整 OA 金额，待核实"
		value = request.get(fieldname)
		number = _number(value)
		if value is not None and value != "" and number is None:
			return None, None, "原始 OA 金额无效，待核实"
		if number is not None:
			available.append((value, basis))
			if number != 0:
				return value, basis, None
	if available:
		value, basis = available[-1]
		return value, basis, "原始金额为0，待核实"
	return None, None, None


def _currency(value: Any, currency_codes: set[str]) -> str | None:
	text = _text(value)
	alias = CURRENCY_ALIASES.get(text)
	if alias:
		return alias
	code = text.upper()
	return code if code in RECOGNIZED_CURRENCIES or code in currency_codes else None


def _oa_metadata(request: dict, currency_codes: set[str]) -> dict:
	amount, basis, amount_warning = _oa_amount(request)
	currency = _currency(request.get("currency"), currency_codes)
	warnings = [amount_warning] if amount_warning else []
	if not currency:
		warnings.append("OA 币种未知，未计入合计")
	return {
		"oa_name": request["name"],
		"oa_number": request.get("oa_code") or request.get("order_no") or request["name"],
		"approval_status": request.get("approval_status"),
		"oa_amount": amount, "oa_currency": currency, "oa_amount_basis": basis,
		"oa_warning": "；".join(warnings) or None,
	}


def _combine_warnings(*values) -> str | None:
	parts = [part for value in values if value for part in value.split("；") if part]
	return "；".join(dict.fromkeys(parts)) or None


def _oa_reference(request: dict, currency_codes: set[str], *, order=None, association_warning=None) -> dict:
	metadata = _oa_metadata(request, currency_codes)
	company_warning = None
	if order and _text(order.get("company")) and _text(request.get("target_company")):
		if _text(order["company"]) != _text(request["target_company"]):
			company_warning = "OA 公司与订单公司不一致"
	return {
		"name": metadata["oa_name"], "number": metadata["oa_number"],
		"approval_status": metadata["approval_status"], "amount": metadata["oa_amount"],
		"currency": metadata["oa_currency"], "amount_basis": metadata["oa_amount_basis"],
		"company": request.get("target_company") or None,
		"warning": _combine_warnings(metadata["oa_warning"], association_warning, company_warning),
	}


def _base_row(record: dict, doctype: str) -> dict:
	return {
		**{field: record.get(field) if doctype == PURCHASE_ORDER else None for field in PO_FIELDS},
		"name": record["name"], "row_key": f"{doctype}::{record['name']}",
		"row_type": "purchase_order" if doctype == PURCHASE_ORDER else "oa_request",
		"source": None, "oa_name": None, "oa_number": None, "approval_status": None,
		"oa_amount": None, "oa_currency": None, "oa_amount_basis": None, "oa_warning": None,
		"oa_references": [],
	}


def _canonical_rows(purchase_orders, oa_requests, currency_codes: set[str], oa_reverse_link_readable: bool) -> list[dict]:
	orders = {_text(row.get("name")): dict(row) for row in purchase_orders if _text(row.get("name"))}
	requests = {_text(row.get("name")): dict(row) for row in oa_requests if _text(row.get("name"))}
	associations, targets = defaultdict(set), defaultdict(set)
	for name, order in orders.items():
		linked = _text(order.get("custom_oa_purchase_expense"))
		if linked:
			targets[linked].add(name)
			if linked in requests:
				associations[name].add(linked)
	for name, request in requests.items():
		linked = _text(request.get("purchase_order"))
		if linked:
			targets[name].add(linked)
			if linked in orders:
				associations[linked].add(name)
	rows, suppressed = [], set()
	for name, order in orders.items():
		row = _base_row(order, PURCHASE_ORDER)
		row["_company_readable"] = "company" in order
		linked_names = sorted(associations[name])
		row["_search_values"] = []
		row["_approval_statuses"] = []
		if linked_names:
			suppressed.update(linked_names)
			row["source"] = "OA"
			row["_approval_statuses"] = [requests[key].get("approval_status") for key in linked_names]
			row["_search_values"] = [requests[key].get(field) for key in linked_names for field in ("name", "oa_code", "order_no")]
			conflict = any(len(targets[key]) > 1 for key in linked_names)
			if len(linked_names) == 1 and not conflict:
				row.update(_oa_metadata(requests[linked_names[0]], currency_codes))
			else:
				row["oa_number"] = "、".join(_text(requests[key].get("oa_code") or key) for key in linked_names)
				row["oa_warning"] = "OA 关联冲突，金额待核实" if conflict else "关联多个 OA，金额待核实"
			association_warning = row["oa_warning"] if conflict or len(linked_names) > 1 else None
			row["oa_references"] = [
				_oa_reference(requests[key], currency_codes, order=order, association_warning=association_warning)
				for key in linked_names
			]
			row["oa_warning"] = _combine_warnings(*(reference["warning"] for reference in row["oa_references"]))
		elif "custom_oa_purchase_expense" in order:
			if order.get("custom_oa_purchase_expense"):
				row["source"] = "OA"
				row["oa_warning"] = "OA 关联记录不可见或不存在"
			elif oa_reverse_link_readable:
				row["source"] = "未关联 OA"
		rows.append(row)
	for name, request in requests.items():
		if name in suppressed:
			continue
		row = _base_row(request, OA_REQUEST)
		row.update(_oa_metadata(request, currency_codes))
		status = "已生成订单（无权查看）" if request.get("purchase_order") else "未生成订单"
		if "purchase_order" not in request:
			status = "订单关联不可见"
			row["oa_warning"] = _combine_warnings(row["oa_warning"], status)
		row.update({
			"source": "OA", "transaction_date": _date(request.get("apply_date") or request.get("creation")) or None,
			"company": request.get("target_company") or None, "owner": request.get("owner"),
			"_company_readable": "target_company" in request,
			"status": status,
			"oa_references": [_oa_reference(request, currency_codes, association_warning="订单关联不可见" if "purchase_order" not in request else None)],
			"_approval_statuses": [request.get("approval_status")],
			"_search_values": [request.get("oa_code"), request.get("order_no")],
		})
		rows.append(row)
	return rows


def _matches(row: dict, filters: dict) -> bool:
	if filters["scope"] == "orders" and row["row_type"] != "purchase_order":
		return False
	if filters["scope"] == "oa" and row["source"] != "OA":
		return False
	source = {"oa": "OA", "non_oa": "未关联 OA"}.get(filters["source"])
	if source and row["source"] != source:
		return False
	company = _text(filters.get("company"))
	if company == "__unconfirmed__":
		if not row.get("_company_readable") or _text(row.get("company")):
			return False
	elif company and _text(row.get("company")) != company:
		return False
	date = _date(row.get("transaction_date"))
	if filters.get("from_date") and (not date or date < filters["from_date"]):
		return False
	if filters.get("to_date") and (not date or date > filters["to_date"]):
		return False
	approval = _text(filters.get("approval_status"))
	if approval and approval not in [_text(value) for value in row.get("_approval_statuses", [])]:
		return False
	search = _text(filters.get("search")).casefold()
	values = [row.get(field) for field in ("name", "supplier", "supplier_name", "oa_name", "oa_number", "project", "owner")]
	return not search or any(search in _text(value).casefold() for value in values + row.get("_search_values", []))


def _pipeline(purchase_orders, oa_requests, *, filters=None, order_by="transaction_date desc", currency_codes=(),
	oa_reverse_link_readable=True):
	parsed = _filters(filters)
	field, descending = _sort_spec(order_by)
	rows = [row for row in _canonical_rows(purchase_orders, oa_requests, set(currency_codes), oa_reverse_link_readable) if _matches(row, parsed)]
	rows.sort(key=lambda row: row["row_key"])
	nonempty, empty = [], []
	for row in rows:
		(empty if row.get(field) is None else nonempty).append(row)
	nonempty.sort(key=lambda row: (_number(row[field]) or Decimal(0)) if field in NUMERIC_FIELDS else _text(row[field]).casefold(), reverse=descending)
	rows = nonempty + empty
	totals = {"orders": defaultdict(Decimal), "oa": defaultdict(Decimal)}
	unknown_names = set()
	for row in rows:
		for kind, currency_field, amount_field in (("orders", "currency", "grand_total"), ("oa", "oa_currency", "oa_amount")):
			amount, currency = _number(row.get(amount_field)), _text(row.get(currency_field))
			if currency and amount is not None:
				totals[kind][currency] += amount
		unknown_names.update(reference["name"] for reference in row["oa_references"] if not reference["currency"])
	totals = {kind: [{"currency": code, "amount": float(value)} for code, value in sorted(group.items())] for kind, group in totals.items()}
	totals["oa_unknown_currency_count"] = len(unknown_names)
	return rows, totals


def _public_rows(rows: list[dict]) -> list[dict]:
	return [{
		**{key: value for key, value in row.items() if not key.startswith("_")},
		"company_visibility": "hidden" if not row["_company_readable"]
			else ("known" if _text(row.get("company")) else "pending"),
	} for row in rows]


def build_unified_purchase_payload(purchase_orders, oa_requests, *, filters=None, start=0,
	page_length=DEFAULT_PAGE_LENGTH, order_by="transaction_date desc", currency_codes=(),
	capabilities=None, warnings=(), oa_reverse_link_readable=True) -> dict:
	start = _integer(start, minimum=0)
	page_length = _integer(page_length, minimum=1, maximum=MAX_PAGE_LENGTH)
	rows, totals = _pipeline(purchase_orders, oa_requests, filters=filters, order_by=order_by,
		currency_codes=currency_codes, oa_reverse_link_readable=oa_reverse_link_readable)
	return {
		"rows": _public_rows(rows[start:start + page_length]), "total_count": len(rows),
		"start": start, "page_length": page_length, "has_previous": start > 0,
		"has_next": start + page_length < len(rows), "totals": totals,
		"capabilities": capabilities or {"purchase_order": True, "oa_request": True}, "warnings": list(warnings),
	}


def _columns(columns: Any) -> list[str]:
	if isinstance(columns, str):
		columns = json.loads(columns)
	if columns is None:
		return list(DEFAULT_EXPORT_COLUMNS)
	if not isinstance(columns, list) or not columns or any(not isinstance(key, str) or key not in EXPORT_LABELS for key in columns):
		raise ValueError("不支持的采购导出列。")
	if len(set(columns)) != len(columns):
		raise ValueError("采购导出列不能重复。")
	return columns


def _export_data(rows: list[dict], columns: Any) -> list[list]:
	fields = _columns(columns)
	return [
		[EXPORT_LABELS[field] for field in fields],
		*[[json.dumps(row.get(field) or [], ensure_ascii=False, default=str) if field == "oa_references"
			else row.get(field) for field in fields] for row in rows],
	]


def build_unified_purchase_export(purchase_orders, oa_requests, *, filters=None, columns=None,
	order_by="transaction_date desc", currency_codes=(), oa_reverse_link_readable=True) -> list[list]:
	rows, _ = _pipeline(purchase_orders, oa_requests, filters=filters, order_by=order_by,
		currency_codes=currency_codes, oa_reverse_link_readable=oa_reverse_link_readable)
	return _export_data(rows, columns)


def _require_export_permission(doctype: str, records) -> None:
	"""Match native report export authority, including its exact-owner fallback."""
	if frappe.permissions.can_export(doctype):
		return
	if not frappe.permissions.can_export(doctype, is_owner=True):
		frappe.throw(f"没有权限导出{doctype}。", frappe.PermissionError)
	for record in records:
		if "owner" in record:
			owner = record.get("owner")
		else:
			# Authority-only read: never restore a denied owner field to the projection.
			doc = frappe.get_doc(doctype, record["name"])
			doc.check_permission("read")
			owner = doc.get("owner")
		if not owner or owner != frappe.session.user:
			frappe.throw(f"没有权限导出{doctype}。", frappe.PermissionError)


def _read_records() -> tuple[list, list, dict, list, set, bool]:
	if frappe is None:
		raise RuntimeError("统一采购查询需要 Frappe 站点。")
	capabilities, warnings, records = {}, [], {}
	oa_reverse_link_readable = False
	for doctype, key, requested in ((PURCHASE_ORDER, "purchase_order", PO_QUERY_FIELDS), (OA_REQUEST, "oa_request", OA_QUERY_FIELDS)):
		exists = bool(frappe.db.exists("DocType", doctype))
		if doctype == OA_REQUEST and not exists:
			# No OA DocType means there can be no reverse links to hide.
			oa_reverse_link_readable = True
		readable = exists and bool(frappe.has_permission(doctype, "read"))
		capabilities[key] = readable
		if not readable:
			warnings.append(f"{doctype} 未安装。" if not exists else f"无权查看 {doctype}。")
			records[doctype] = []
			continue
		permitted = set(get_permitted_fields(doctype, permission_type="read", ignore_virtual=True))
		if doctype == OA_REQUEST:
			oa_reverse_link_readable = "purchase_order" in permitted
		fields = [field for field in requested if field in permitted]
		if "name" not in fields:
			frappe.throw(f"没有权限查看 {doctype} 单号。", frappe.PermissionError)
		result = frappe.get_list(doctype, fields=fields, limit_page_length=0)
		# Keep projection explicit even if a boundary returns surplus values.
		records[doctype] = [{field: row.get(field) for field in fields} for row in result]
	if not any(capabilities.values()):
		frappe.throw("没有权限查看采购订单或 OA 采购申请。", frappe.PermissionError)
	codes = {_text(row.get("currency")).upper() for row in records[OA_REQUEST] if _text(row.get("currency"))}
	currency_codes = {code for code in codes if code not in RECOGNIZED_CURRENCIES and frappe.db.exists("Currency", code)}
	return records[PURCHASE_ORDER], records[OA_REQUEST], capabilities, warnings, currency_codes, oa_reverse_link_readable


@_whitelist
def get_unified_purchase_list(filters=None, start=0, page_length=DEFAULT_PAGE_LENGTH,
	order_by="transaction_date desc") -> dict:
	orders, requests, capabilities, warnings, currencies, reverse_readable = _read_records()
	return build_unified_purchase_payload(orders, requests, filters=filters, start=start, page_length=page_length,
		order_by=order_by, currency_codes=currencies, capabilities=capabilities, warnings=warnings,
		oa_reverse_link_readable=reverse_readable)


@_whitelist
def export_unified_purchase_list(filters=None, columns=None, order_by="transaction_date desc") -> None:
	orders, requests, capabilities, _, currencies, reverse_readable = _read_records()
	rows, _ = _pipeline(orders, requests, filters=filters, order_by=order_by,
		currency_codes=currencies, oa_reverse_link_readable=reverse_readable)
	records = {PURCHASE_ORDER: {row["name"]: row for row in orders}, OA_REQUEST: {row["name"]: row for row in requests}}
	used = defaultdict(set)
	for row in rows:
		used[PURCHASE_ORDER if row["row_type"] == "purchase_order" else OA_REQUEST].add(row["name"])
		if row["oa_references"]:
			used[OA_REQUEST].update(reference["name"] for reference in row["oa_references"])
	if not rows:
		scope = _filters(filters)["scope"]
		for doctype, key in ((PURCHASE_ORDER, "purchase_order"), (OA_REQUEST, "oa_request")):
			if capabilities[key] and (scope != "orders" or doctype == PURCHASE_ORDER):
				used[doctype] = set()
	for doctype, names in sorted(used.items()):
		_require_export_permission(doctype, (records[doctype][name] for name in sorted(names)))
	from frappe.utils.xlsxutils import make_xlsx
	from xlsxwriter import Workbook
	output = BytesIO()
	# Source text remains unchanged; prevent ws.write from interpreting it as a formula or link.
	with Workbook(output, {
		"constant_memory": True, "strings_to_formulas": False, "strings_to_urls": False,
		"default_date_format": "yyyy-mm-dd hh:mm:ss",
	}) as workbook:
		# Native Data Export mode also preserves literal HTML-looking source text.
		make_xlsx(_export_data(rows, columns), "Data Export", wb=workbook)
	frappe.response["filename"] = "unified-purchase.xlsx"
	frappe.response["filecontent"] = output.getvalue()
	frappe.response["type"] = "binary"
