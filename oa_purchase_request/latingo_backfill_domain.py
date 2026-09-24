"""Pure business rules for the LatinGo purchase-expense backfill.

This module intentionally has no Frappe dependency.  The source adapter and
document writer live in :mod:`oa_purchase_request.latingo_backfill` while this
file owns the deterministic scope, mapping, fingerprint and submit rules.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


LATINGO_COMPANY = "拉丁购国际电子商务（东莞）有限公司"
LATINGO_PURCHASE_PROCESS_CODE = "PROC-6E11B527-2F82-439C-817D-C868DE086C97"
GENERIC_PURCHASE_PROCESS_CODE = "PROC-BFDF6F09-4551-43B3-8C55-537AA74A241B"
LATINGO_WAREHOUSE = "仓库 - 拉丁购"
LATINGO_COST_CENTER = "主 - 拉丁购"
TEMP_SUPPLIER = "拉丁购采购支出（待确认供应商）"
TEMP_SUPPLIER_GROUP = "拉丁购待确认供应商"
SERVICE_ITEM_GROUP = "LGO 服务采购"
SERVICE_UOM = "项：servicio"
LATINGO_INPUT_TAX_ACCOUNT = "22210101 - 应交税费－应交增值税－进项税额 - 拉丁购"
KNOWN_TAX_APPROVAL = "202608241502000513674"
BACKFILL_START_DATE = "2026-07-01"
BACKFILL_END_DATE = "2026-09-24"

ALLOWED_GENERIC_ORGANIZATIONS = {
	"obg线上业务组grupodenegociosenlinea",
	"obg1线上业务部grupodenegociosenlinea",
}

UOM_MAP = {
	"个": "个：pieza",
	"只": "个：pieza",
	"套": "套：conjunto",
	"根": "根：raíz",
}


def _date(value) -> date | None:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	text = str(value or "").strip()
	if not text:
		return None
	try:
		return date.fromisoformat(text[:10])
	except ValueError:
		return None


def _decimal(value, default="0") -> Decimal:
	if value in (None, ""):
		return Decimal(default)
	try:
		return Decimal(str(value).replace(",", "").strip())
	except (InvalidOperation, ValueError):
		return Decimal(default)


def _money(value) -> float:
	return float(_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _rate(value) -> float:
	return float(_decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _text(value) -> str:
	return str(value or "").strip()


def _normalized(value) -> str:
	decomposed = unicodedata.normalize("NFKD", _text(value).lower())
	plain = "".join(char for char in decomposed if not unicodedata.combining(char))
	return "".join(plain.split())


def _truthy(value) -> bool:
	if isinstance(value, bool):
		return value
	return _normalized(value) in {"1", "true", "yes", "y", "deleted", "已删除"}


def _first(row: dict, *keys: str):
	for key in keys:
		if row.get(key) not in (None, ""):
			return row.get(key)
	return None


def _scalar(value):
	if isinstance(value, dict):
		for key in ("name", "label", "text", "value", "title"):
			if value.get(key) not in (None, ""):
				return _scalar(value.get(key))
		return ""
	if isinstance(value, list):
		parts = [_text(_scalar(item)) for item in value]
		return ", ".join(part for part in parts if part)
	return value


def _field_value(fields: dict, *aliases: str):
	for alias in aliases:
		if fields.get(alias) not in (None, ""):
			return _scalar(fields.get(alias))
	normalized = {_normalized(key): value for key, value in fields.items()}
	for alias in aliases:
		value = normalized.get(_normalized(alias))
		if value not in (None, ""):
			return _scalar(value)
	return ""


def source_from_instance(instance: dict, *, fields: dict, detail_rows: list[dict]) -> dict:
	"""Build the stable source shape from the existing parser outputs."""

	deleted = any(
		_truthy(instance.get(key))
		for key in ("is_deleted", "isDeleted", "deleted")
	) or bool(instance.get("deleted_at") or instance.get("deletedAt"))
	return {
		"process_instance_id": _text(
			instance.get("processInstanceId") or instance.get("process_instance_id")
		),
		"business_id": _text(
			instance.get("businessId") or instance.get("business_id") or instance.get("bizId")
		),
		"process_code": _text(instance.get("processCode") or instance.get("process_code")),
		"status": _text(instance.get("status") or instance.get("approvalStatus")),
		"result": _text(instance.get("result") or instance.get("approvalResult")),
		"is_deleted": deleted,
		"apply_date": _field_value(fields, "申请日期Fecha de solicitud", "申请日期", "Fecha de solicitud"),
		"organization": _field_value(
			fields,
			"申请部门/组织 Departamento Solicitante",
			"申请部门/组织",
			"Departamento Solicitante",
			"组织",
		),
		"currency": _field_value(fields, "币种Moneda", "币种", "Moneda"),
		"amount": _field_value(fields, "金额importe", "金额", "importe", "Monto Total"),
		"payee": _field_value(fields, "收款人beneficiario", "收款人", "beneficiario"),
		"description": _field_value(
			fields,
			"规格明细需求说明Descripcion de las necesidades de detalles",
			"规格明细需求说明",
			"Descripcion de las necesidades de detalles",
			"采购支出说明",
			"说明",
		),
		"delivery_date": _field_value(fields, "交付日期Fecha de entrega", "交付日期", "Fecha de entrega"),
		"service_purchase_type": _field_value(
			fields,
			"服务类采购 Adquisiciones de servicios",
			"服务类采购",
			"Adquisiciones de servicios",
		),
		"pds_category": _field_value(fields, "PDS分类Clasificacion PDS", "PDS分类", "Clasificacion PDS"),
		"expense_category": _field_value(
			fields,
			"费用分类 Clasificacion de gastos",
			"费用分类",
			"Clasificacion de gastos",
		),
		"detail_rows": detail_rows,
	}


def iter_month_windows(start_date, end_date) -> list[tuple[date, date]]:
	"""Split an inclusive date range into calendar-month windows."""

	start = _date(start_date)
	end = _date(end_date)
	if not start or not end or end < start:
		raise ValueError("开始日期和结束日期必须是有效的正向日期范围")
	windows = []
	cursor = start
	while cursor <= end:
		month_end = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
		window_end = min(month_end, end)
		windows.append((cursor, window_end))
		if cursor.month == 12:
			cursor = date(cursor.year + 1, 1, 1)
		else:
			cursor = date(cursor.year, cursor.month + 1, 1)
	return windows


def iter_archive_month_windows(start_date, end_date) -> list[tuple[date, date]]:
	"""Pad adjacent months because the archive indexes creation, not application, date."""

	requested = iter_month_windows(start_date, end_date)
	start = requested[0][0]
	end = requested[-1][1]
	if start.month == 1:
		query_start = date(start.year - 1, 12, 1)
	else:
		query_start = date(start.year, start.month - 1, 1)
	if end.month == 12:
		next_year, next_month = end.year + 1, 1
	else:
		next_year, next_month = end.year, end.month + 1
	query_end = date(next_year, next_month, monthrange(next_year, next_month)[1])
	return iter_month_windows(query_start, query_end)


def is_generic_organization_in_scope(value) -> bool:
	return _normalized(value) in ALLOWED_GENERIC_ORGANIZATIONS


def duplicate_process_instance_ids(values) -> list[str]:
	"""Return normalized, nonblank process IDs that cannot receive a unique index."""

	counts = {}
	for value in values:
		instance_id = _text(value)
		if instance_id:
			counts[instance_id] = counts.get(instance_id, 0) + 1
	return sorted(instance_id for instance_id, count in counts.items() if count > 1)


def _exclusion_reason(source: dict, start_date, end_date) -> str:
	if _truthy(source.get("is_deleted")):
		return "来源已删除"

	status = _normalized(source.get("status"))
	result = _normalized(source.get("result"))
	if any(marker in result for marker in ("refuse", "reject", "rejected", "拒绝", "驳回", "不同意")):
		return "审批已拒绝"
	if any(marker in status for marker in ("terminated", "revoked", "cancel", "撤销", "终止", "取消")):
		return "审批已终止或撤销"

	process_code = _text(source.get("process_code"))
	if process_code not in {LATINGO_PURCHASE_PROCESS_CODE, GENERIC_PURCHASE_PROCESS_CODE}:
		return "流程不在回填范围"
	if process_code == GENERIC_PURCHASE_PROCESS_CODE:
		if not is_generic_organization_in_scope(source.get("organization")):
			return "组织不属于 OBG/OBG1 电商"

	apply_date = _date(source.get("apply_date"))
	start = _date(start_date)
	end = _date(end_date)
	if not apply_date:
		return "缺少有效申请日期"
	if apply_date < start or apply_date > end:
		return "申请日期超出范围"
	return ""


def _currency(value) -> str:
	normalized = _normalized(value)
	if normalized in {"peso", "pesos", "mxn", "墨西哥比索"} or "peso" in normalized:
		return "MXN"
	if normalized in {"rmb", "cny", "人民币", "人民币rmb"}:
		return "CNY"
	return _text(value).upper()


def _service_item_code(source: dict) -> str:
	text = " ".join(
		_text(source.get(key)).lower()
		for key in ("service_purchase_type", "pds_category", "expense_category", "description")
	)
	if "pds" in text or "拍摄" in text or "主播" in text or "contenido" in text or "presentador" in text:
		return "LGO-SVC-PDS"
	if any(marker in text for marker in ("物流", "运输", "logística", "logistica", "transporte")):
		return "LGO-SVC-LOGISTICS"
	return "LGO-SVC-OTHER"


def _physical_item(row: dict) -> dict:
	item_code = _text(_first(row, "item_code", "material_code", "物品编码", "物料编码", "编码"))
	item_name = _text(_first(row, "item_name", "product_name", "物品名称", "物料名称", "名称"))
	if item_code == "0":
		item_code = "LGO-PPE-GLASSES-CLEAR"
		item_name = item_name or "透明安全眼镜"
	item_code = item_code.strip().upper()
	if item_code.startswith("CW"):
		item_group = "CW 宠物用品"
	elif item_code == "PLAYO":
		item_group = "FL Suministros Auxiliares辅料"
	elif item_code == "LGO-PPE-GLASSES-CLEAR":
		item_group = "GJ Herramienta工具"
	else:
		item_group = _text(row.get("item_group")) or "CW 宠物用品"

	qty = _decimal(_first(row, "qty", "quantity", "数量"), default="1")
	if qty == 0:
		qty = Decimal("1")
	amount_value = _first(row, "amount", "goods_value", "总金额", "金额")
	rate_value = _first(row, "rate", "unit_price", "单价")
	if amount_value not in (None, ""):
		amount = _decimal(amount_value)
		rate = amount / qty
	else:
		rate = _decimal(rate_value)
		amount = rate * qty
	uom = _text(_first(row, "uom", "unit", "单位"))
	return {
		"item_code": item_code,
		"item_name": item_name or item_code,
		"item_group": item_group,
		"stock_uom": UOM_MAP.get(uom, uom or "个：pieza"),
		"is_stock_item": 1,
		"qty": float(qty),
		"rate": _rate(rate),
		"amount": _money(amount),
		"warehouse": LATINGO_WAREHOUSE,
		"description": _text(_first(row, "description", "specification", "规格")) or item_name or item_code,
	}


def _service_item(source: dict) -> dict:
	amount = _money(source.get("amount"))
	return {
		"item_code": _service_item_code(source),
		"item_group": SERVICE_ITEM_GROUP,
		"stock_uom": SERVICE_UOM,
		"is_stock_item": 0,
		"qty": 1.0,
		"rate": amount,
		"amount": amount,
		"warehouse": "",
		"description": _text(source.get("description")) or "采购支出服务",
	}


def build_approval_plan(source: dict, start_date, end_date) -> dict:
	"""Turn one pre-parsed approval into a deterministic write plan."""

	reason = _exclusion_reason(source, start_date, end_date)
	apply_date = _date(source.get("apply_date"))
	currency = _currency(source.get("currency"))
	status = _text(source.get("status"))
	result = _text(source.get("result"))
	plan = {
		"process_instance_id": _text(source.get("process_instance_id")),
		"business_id": _text(source.get("business_id")),
		"process_code": _text(source.get("process_code")),
		"status": status,
		"result": result,
		"included": not reason,
		"exclusion_reason": reason,
		"apply_date": apply_date.isoformat() if apply_date else "",
		"organization": _text(source.get("organization")),
		"currency": currency,
		"conversion_rate": 0.39 if currency == "MXN" else 1.0,
		"header_amount": _money(source.get("amount")),
		"payee": _text(source.get("payee")),
		"description": _text(source.get("description")),
		"target_company": LATINGO_COMPANY,
		"warehouse": LATINGO_WAREHOUSE,
		"cost_center": LATINGO_COST_CENTER,
		"temporary_supplier": TEMP_SUPPLIER,
		"transaction_date": apply_date.isoformat() if apply_date else "",
		"schedule_date": "",
		"source_kind": "physical" if source.get("detail_rows") else "service",
		"items": [],
		"taxes": [],
		"net_total": 0.0,
		"grand_total": 0.0,
		"amount_difference": 0.0,
		"warnings": [],
		"review_flags": {
			"source_pending": _normalized(status) not in {"completed", "agree", "同意", "已完成"},
			"exchange_rate_pending": currency == "MXN",
			"price_pending": False,
			"temporary_supplier": True,
			"source_stale": False,
			"source_invalid": False,
		},
	}
	if not plan["included"]:
		return plan

	delivery_date = _date(source.get("delivery_date"))
	plan["schedule_date"] = max(apply_date, delivery_date or apply_date).isoformat()
	if source.get("detail_rows"):
		plan["items"] = [_physical_item(row) for row in source.get("detail_rows") if isinstance(row, dict)]
	else:
		plan["items"] = [_service_item(source)]
	plan["review_flags"]["price_pending"] = any(_decimal(row.get("rate")) == 0 for row in plan["items"])

	plan["net_total"] = _money(sum(_decimal(row.get("amount")) for row in plan["items"]))
	if plan["business_id"] == KNOWN_TAX_APPROVAL and _money(plan["header_amount"] - plan["net_total"]) == 132.0:
		plan["taxes"] = [
			{
				"charge_type": "Actual",
				"account_head": LATINGO_INPUT_TAX_ACCOUNT,
				"tax_amount": 132.0,
				"description": "来源审批明确的 1% 进项税",
			}
		]
	tax_total = sum(_decimal(row.get("tax_amount")) for row in plan["taxes"])
	plan["grand_total"] = _money(_decimal(plan["net_total"]) + tax_total)
	plan["amount_difference"] = _money(_decimal(plan["header_amount"]) - _decimal(plan["grand_total"]))
	if plan["amount_difference"]:
		plan["warnings"].append(
			f"审批金额与明细/税费合计相差 {plan['amount_difference']:.2f} {currency or '未知币种'}"
		)
	return plan


def submission_blockers(plan: dict) -> list[str]:
	flags = plan.get("review_flags") or {}
	blockers = []
	if flags.get("source_invalid"):
		blockers.append("来源审批后来已拒绝、撤销或删除")
	if flags.get("source_pending"):
		blockers.append("来源审批尚未完成")
	if flags.get("source_stale"):
		blockers.append("来源指纹已过期")
	if flags.get("temporary_supplier"):
		blockers.append("临时供应商尚未替换")
	if flags.get("exchange_rate_pending"):
		blockers.append("MXN 汇率尚未确认")
	if flags.get("price_pending"):
		blockers.append("存在零价格物料")
	return blockers


def _json_safe(value):
	if isinstance(value, dict):
		return {
			key: _json_safe(item)
			for key, item in sorted(value.items())
			if key not in {"source_fingerprint", "source_snapshot", "source_fields"}
		}
	if isinstance(value, (list, tuple)):
		return [_json_safe(item) for item in value]
	if isinstance(value, (date, datetime)):
		return value.isoformat()
	if isinstance(value, Decimal):
		return str(value)
	return value


def build_preview_fingerprint(plans: list[dict]) -> str:
	ordered = sorted(
		(_json_safe(plan) for plan in plans),
		key=lambda plan: (plan.get("process_instance_id") or "", plan.get("business_id") or ""),
	)
	payload = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_source_fingerprint(plan: dict) -> str:
	return build_preview_fingerprint([plan])
