"""海外成本工作台的轻量查询与任务分类。"""

from __future__ import annotations

import json
import re

try:
    import frappe
except Exception:  # pragma: no cover - 本地纯函数测试时保持可导入
    frappe = None

from overseas_costing.services import batch_service


ISSUE_ORDER = ("purchase", "logistics", "calculation", "erp_failed")
FIELD_GROUPS = {
    "basic": ("A", "H"),
    "purchase": ("I", "P"),
    "logistics": ("Q", "Z"),
    "tax": ("AA", "AJ"),
    "total": ("AK", "BE"),
}
FIXED_ITEM_FIELDS = ("material_code", "product_name")
SAFE_SORT_FIELDS = {
    "row_no",
    "material_code",
    "product_name",
    "quantity",
    "goods_value",
    "total_cost_rmb",
    "total_unit_rmb",
}
RESULT_PREVIEW_ITEM_FIELDS = [
    "name",
    "row_no",
    "material_code",
    "product_name",
    "spec_model",
    "unit_price",
    "purchase_currency",
    "quantity",
    "goods_value",
    "freight_alloc_rmb",
    "mexico_customs_mxn",
    "mexico_customs_rmb",
    "mexico_customs_usd",
    "import_tax_total",
    *batch_service.TAX_COMPONENT_FIELDS,
    "total_cost_rmb",
    "total_unit_rmb",
    "derived_json",
]
RESULT_PREVIEW_OUTPUT_FIELDS = (
    "material_code",
    "product_name",
    "spec_model",
    "unit_price",
    "purchase_currency",
    "quantity",
    "freight_alloc_rmb",
    "tax_alloc_rmb",
    "clearance_alloc_rmb",
    "total_unit_rmb",
)
RESULT_PREVIEW_FREIGHT_KEYWORDS = (
    "freight",
    "ocean",
    "shipping",
    "transport",
    "logistics",
    "运费",
    "运输",
    "物流",
    "海运",
)
RESULT_PREVIEW_TAX_KEYWORDS = ("tax", "tariff", "duty", "igi", "iva", "关税", "税费")
RESULT_PREVIEW_CLEARANCE_KEYWORDS = (
    "clearance",
    "customs",
    "broker",
    "清关",
    "报关",
)


def _item_count_fields_for_frappe() -> list:
    """Use the aggregate field syntax supported by the active Frappe major version."""

    version = str(getattr(frappe, "__version__", "") or "")
    match = re.search(r"\d+", version)
    if match and int(match.group()) < 16:
        return ["count(name) as total"]
    return [{"COUNT": "name", "as": "total"}]


def operation_error(stage: str, scope: str, reason: str, next_action: str) -> dict:
    """Return the stable error shape consumed by workbench actions."""
    return {
        "ok": False,
        "error": {
            "stage": str(stage or "操作"),
            "scope": str(scope or "当前范围"),
            "reason": str(reason or "操作失败"),
            "next_action": str(next_action or "刷新后重试或查看操作记录"),
        },
    }


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_page(page, page_length, *, default_length: int = 30) -> tuple[int, int]:
    try:
        normalized_page = max(1, int(page or 1))
    except (TypeError, ValueError):
        normalized_page = 1
    try:
        normalized_length = min(100, max(10, int(page_length or default_length)))
    except (TypeError, ValueError):
        normalized_length = default_length
    return normalized_page, normalized_length


def classify_batch(batch: dict, stats: dict) -> dict:
    approval_state = str(
        (batch.get("source_status") or {}).get("purchase_approval_sync_state") or ""
    ).lower()
    status = str(batch.get("status") or "").lower()
    writeback = str(batch.get("writeback_status") or "").lower()
    issues = []
    if (
        approval_state in {"missing", "pending", "invalid"}
        or not batch.get("subsidiary_code")
        or stats.get("missing_purchase_count", 0)
        or not stats.get("item_count", 0)
    ):
        issues.append("purchase")
    if stats.get("missing_logistics_count", 0):
        issues.append("logistics")
    if status in {"draft", "dirty", "writeback failed"} or _as_float(
        batch.get("actual_total_cost_rmb") or batch.get("estimated_total_cost_rmb")
    ) <= 0:
        issues.append("calculation")
    if "fail" in writeback:
        issues.append("erp_failed")
    primary = next((code for code in ISSUE_ORDER if code in issues), "ready")
    action = {
        "purchase": "supplement",
        "logistics": "supplement",
        "calculation": "recalculate",
        "erp_failed": "erp_retry",
        "ready": "view",
    }[primary]
    return {"issue_codes": issues, "primary_issue": primary, "primary_action": action}


def filter_batches_for_task(rows: list[dict], task: str) -> list[dict]:
    if task == "pending":
        return [row for row in rows if row.get("primary_issue") != "ready"]
    if task == "cost":
        return [
            row
            for row in rows
            if _as_float(row.get("actual_total_cost_rmb") or row.get("estimated_total_cost_rmb")) > 0
        ]
    if task == "erp":
        return [
            row
            for row in rows
            if str(row.get("writeback_status") or "").lower() in {"pending", "failed"}
            or (
                str(row.get("confirm_status") or "").lower() == "confirmed"
                and str(row.get("writeback_status") or "").lower() != "success"
            )
        ]
    return list(rows)


def select_item_columns(columns: list[dict], group: str) -> list[dict]:
    if group == "all":
        return list(columns)
    start, end = FIELD_GROUPS.get(group, FIELD_GROUPS["basic"])
    start_index = next(index for index, column in enumerate(columns) if column["excel_col"] == start)
    end_index = next(index for index, column in enumerate(columns) if column["excel_col"] == end)
    return [
        column
        for index, column in enumerate(columns)
        if column["fieldname"] in FIXED_ITEM_FIELDS or start_index <= index <= end_index
    ]


def normalize_item_query(page, page_length, group, sort_by, sort_order) -> dict:
    page, page_length = normalize_page(page, page_length, default_length=50)
    group = group if group in {*FIELD_GROUPS, "all"} else "basic"
    sort_by = sort_by if sort_by in SAFE_SORT_FIELDS else "row_no"
    sort_order = "desc" if str(sort_order).lower() == "desc" else "asc"
    return {
        "page": page,
        "page_length": page_length,
        "group": group,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }


def _load_result_preview_json(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _round_result_amount(value):
    return round(_as_float(value), 6)


def _rule_bucket(rule: dict) -> str:
    text = " ".join(
        str(rule.get(fieldname) or "")
        for fieldname in ("rule_code", "expense_category")
    ).lower()
    if any(keyword in text for keyword in RESULT_PREVIEW_TAX_KEYWORDS):
        return "tax"
    if any(keyword in text for keyword in RESULT_PREVIEW_CLEARANCE_KEYWORDS):
        return "clearance"
    if any(keyword in text for keyword in RESULT_PREVIEW_FREIGHT_KEYWORDS):
        return "freight"
    return "other"


def build_batch_result_preview_item(item: dict, *, calculated: bool) -> dict:
    """将一行明细收敛为快捷结果口径，不把普通杂费冒充清关费。"""

    result = {
        "name": item.get("name") or "",
        "row_no": item.get("row_no"),
        "material_code": item.get("material_code") or "",
        "product_name": item.get("product_name") or "",
        "spec_model": item.get("spec_model") or "",
        "unit_price": item.get("unit_price"),
        "purchase_currency": item.get("purchase_currency") or "",
        "quantity": item.get("quantity"),
        "freight_alloc_rmb": None,
        "tax_alloc_rmb": None,
        "clearance_alloc_rmb": None,
        "unlisted_other_cost_rmb": None,
        "total_unit_rmb": None,
    }
    if not calculated:
        return result

    metadata = _load_result_preview_json(item.get("derived_json"))
    direct_customs = metadata.get("direct_customs")
    if not isinstance(direct_customs, dict):
        direct_customs = {}
    allocated_rules = metadata.get("allocated_rules")
    if not isinstance(allocated_rules, list):
        allocated_rules = []

    fx_rmb_to_mxn = _as_float(metadata.get("fx_rmb_to_mxn"))
    fx_usd_to_rmb = _as_float(metadata.get("fx_usd_to_rmb"))
    tax_mxn = _as_float(item.get("import_tax_total"))
    if not tax_mxn:
        tax_mxn = sum(_as_float(item.get(fieldname)) for fieldname in batch_service.TAX_COMPONENT_FIELDS)
    if not tax_mxn:
        tax_mxn = _as_float(direct_customs.get("tax_mxn"))

    customs_source_type = str(direct_customs.get("source_type") or "").strip().lower()
    direct_customs_rmb = _as_float(direct_customs.get("amount_rmb"))
    if not direct_customs_rmb:
        direct_customs_rmb = _as_float(item.get("mexico_customs_rmb"))
    if not direct_customs_rmb and _as_float(item.get("mexico_customs_mxn")) and fx_rmb_to_mxn:
        direct_customs_rmb = _as_float(item.get("mexico_customs_mxn")) / fx_rmb_to_mxn
    if not direct_customs_rmb and _as_float(item.get("mexico_customs_usd")) and fx_usd_to_rmb:
        direct_customs_rmb = _as_float(item.get("mexico_customs_usd")) * fx_usd_to_rmb

    has_component_breakdown = customs_source_type == "customs_components"
    customs_total_cannot_be_split = bool(direct_customs_rmb and not has_component_breakdown and not tax_mxn)
    tax_from_customs = (
        None
        if customs_total_cannot_be_split or (tax_mxn and not fx_rmb_to_mxn)
        else _as_float(tax_mxn) / fx_rmb_to_mxn
        if tax_mxn
        else 0.0
    )
    direct_clearance_rmb = None
    service_mxn = _as_float(direct_customs.get("service_mxn"))
    if service_mxn:
        direct_clearance_rmb = service_mxn / fx_rmb_to_mxn if fx_rmb_to_mxn else None
    elif has_component_breakdown:
        direct_clearance_rmb = 0.0
    elif direct_customs_rmb and tax_from_customs is not None:
        direct_clearance_rmb = max(direct_customs_rmb - tax_from_customs, 0.0)
    elif not direct_customs_rmb:
        direct_clearance_rmb = 0.0

    buckets = {"freight": 0.0, "tax": 0.0, "clearance": 0.0, "other": 0.0}
    rule_buckets = []
    for rule in allocated_rules:
        if not isinstance(rule, dict):
            continue
        bucket = _rule_bucket(rule)
        rule_buckets.append(bucket)
        buckets[bucket] += _as_float(rule.get("allocated_rmb"))

    freight_value_is_missing = item.get("freight_alloc_rmb") in (None, "")
    freight_rmb = (
        None
        if freight_value_is_missing and "freight" not in rule_buckets
        else buckets["freight"]
        if allocated_rules
        else _as_float(item.get("freight_alloc_rmb"))
    )
    if allocated_rules and not freight_rmb and not freight_value_is_missing:
        freight_rmb = _as_float(item.get("freight_alloc_rmb"))
    tax_rmb = None if tax_from_customs is None else tax_from_customs + buckets["tax"]
    clearance_rmb = None if direct_clearance_rmb is None else direct_clearance_rmb + buckets["clearance"]
    other_rmb = buckets["other"] + (direct_customs_rmb if customs_total_cannot_be_split else 0.0)

    if freight_rmb is not None and tax_rmb is not None and clearance_rmb is not None:
        expected_extra = max(_as_float(item.get("total_cost_rmb")) - _as_float(item.get("goods_value")), 0.0)
        known_extra = freight_rmb + tax_rmb + clearance_rmb + other_rmb
        if expected_extra - known_extra > 0.000001:
            other_rmb += expected_extra - known_extra

    result.update(
        {
            "freight_alloc_rmb": None if freight_rmb is None else _round_result_amount(freight_rmb),
            "tax_alloc_rmb": None if tax_rmb is None else _round_result_amount(tax_rmb),
            "clearance_alloc_rmb": None if clearance_rmb is None else _round_result_amount(clearance_rmb),
            "unlisted_other_cost_rmb": _round_result_amount(other_rmb),
            "total_unit_rmb": (
                None
                if item.get("total_unit_rmb") in (None, "")
                else _round_result_amount(item.get("total_unit_rmb"))
            ),
        }
    )
    return result


def build_batch_result_preview_payload(
    *,
    batch: dict,
    version: dict,
    items: list[dict],
    page=1,
    page_length=20,
) -> dict:
    page, page_length = normalize_page(page, page_length, default_length=20)
    calculated = bool(version.get("calculated_at"))
    ordered_items = sorted(items, key=lambda item: (_as_float(item.get("row_no")), str(item.get("name") or "")))
    result_items = [build_batch_result_preview_item(item, calculated=calculated) for item in ordered_items]

    purchase_totals_by_currency: dict[str, float] = {}
    for item in ordered_items:
        currency = str(item.get("purchase_currency") or "").strip().upper()
        purchase_totals_by_currency[currency] = purchase_totals_by_currency.get(currency, 0.0) + _as_float(
            item.get("goods_value")
        )
    purchase_totals = [
        {"currency": currency, "amount": _round_result_amount(amount)}
        for currency, amount in purchase_totals_by_currency.items()
    ]
    total_quantity = sum(_as_float(item.get("quantity")) for item in ordered_items)
    weighted_total_unit_rmb = None
    has_all_total_costs = all(item.get("total_cost_rmb") not in (None, "") for item in ordered_items)
    if calculated and total_quantity and has_all_total_costs:
        weighted_total_unit_rmb = _round_result_amount(
            sum(_as_float(item.get("total_cost_rmb")) for item in ordered_items) / total_quantity
        )

    def result_total(fieldname: str):
        values = [item.get(fieldname) for item in result_items]
        if not calculated or any(value is None for value in values):
            return None
        return _round_result_amount(sum(_as_float(value) for value in values))

    tax_total = result_total("tax_alloc_rmb")
    clearance_total = result_total("clearance_alloc_rmb")
    result_totals = {
        "freight": result_total("freight_alloc_rmb"),
        "tax": tax_total,
        "clearance": clearance_total,
    }
    calculation_status = (
        "pending"
        if not calculated
        else "partial"
        if weighted_total_unit_rmb is None or any(value is None for value in result_totals.values())
        else "ready"
    )
    total = len(result_items)
    offset = (page - 1) * page_length
    return {
        "ok": True,
        "batch_name": batch.get("name") or "",
        "version_name": version.get("name") or "",
        "summary": {
            "batch_no": batch.get("batch_no") or batch.get("name") or "",
            "logistics_no": batch.get("waybill_no") or batch.get("customs_no") or "",
            "purchase_totals": purchase_totals,
            "total_freight_rmb": result_totals["freight"],
            "total_tax_rmb": tax_total,
            "total_clearance_rmb": clearance_total,
            "total_quantity": _round_result_amount(total_quantity),
            "weighted_total_unit_rmb": weighted_total_unit_rmb,
            "unlisted_other_cost_rmb": result_total("unlisted_other_cost_rmb"),
            "calculation_status": calculation_status,
        },
        "items": [
            {fieldname: item.get(fieldname) for fieldname in RESULT_PREVIEW_OUTPUT_FIELDS}
            for item in result_items[offset : offset + page_length]
        ],
        "total": total,
        "page": page,
        "page_length": page_length,
        "page_count": (total + page_length - 1) // page_length,
    }


def get_batch_result_preview(batch_name: str, page=1, page_length=20) -> dict:
    page, page_length = normalize_page(page, page_length, default_length=20)
    if frappe is None:
        return build_batch_result_preview_payload(
            batch={"name": batch_name, "batch_no": batch_name},
            version={},
            items=[],
            page=page,
            page_length=page_length,
        ) | {"dry_run": True}

    batch_doc_name = batch_service._resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}
    version_name = batch_service._resolve_version_name(batch_doc_name, None)
    if not version_name:
        return {"ok": False, "batch_name": batch_doc_name, "message": "当前批次没有版本。"}

    batch_rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"name": batch_doc_name},
        fields=["name", "batch_no", "waybill_no", "customs_no", "current_version", "status"],
        limit_page_length=1,
    )
    version_rows = frappe.get_all(
        "Overseas Cost Version",
        filters={"name": version_name, "batch": batch_doc_name},
        fields=["name", "calculated_at"],
        limit_page_length=1,
    )
    if not batch_rows or not version_rows:
        return {"ok": False, "batch_name": batch_doc_name, "message": "当前批次或版本已不存在。"}

    items = frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_doc_name, "version": version_name},
        fields=RESULT_PREVIEW_ITEM_FIELDS,
        order_by="row_no asc, name asc",
        limit_page_length=0,
    )
    return build_batch_result_preview_payload(
        batch=batch_rows[0],
        version=version_rows[0],
        items=items,
        page=page,
        page_length=page_length,
    )


def _load_current_item_stats(batch_names: list[str]) -> dict[str, dict]:
    if frappe is None or not batch_names:
        return {}
    rows = frappe.db.sql(
        """
        select item.batch,
               count(*) as item_count,
               sum(case when coalesce(item.unit_price, 0) <= 0
                              or coalesce(item.purchase_currency, '') = ''
                              or coalesce(item.goods_value, 0) <= 0
                        then 1 else 0 end) as missing_purchase_count,
               sum(case when coalesce(item.actual_shipped_qty, 0) <= 0
                              or coalesce(item.gross_weight_kg, 0) <= 0
                        then 1 else 0 end) as missing_logistics_count
          from `tabOverseas Cost Item` item
          inner join `tabOverseas Cost Batch` batch
                  on batch.name = item.batch and batch.current_version = item.version
         where item.batch in %(batch_names)s
         group by item.batch
        """,
        {"batch_names": tuple(batch_names)},
        as_dict=True,
    )
    return {row["batch"]: row for row in rows}


def _matches_workbench_filters(row: dict, filters: dict) -> bool:
    issue = str(filters.get("issue") or "")
    if issue and issue not in row.get("issue_codes", []):
        return False
    subsidiary = str(filters.get("subsidiary_code") or "")
    if subsidiary and str(row.get("subsidiary_code") or "") != subsidiary:
        return False
    calculation_status = str(filters.get("calculation_status") or "").lower()
    if calculation_status and str(row.get("status") or "").lower() != calculation_status:
        return False
    erp_status = str(filters.get("erp_status") or "").lower()
    if erp_status and str(row.get("writeback_status") or "").lower() != erp_status:
        return False
    return True


def _classified_batches(filters: dict | None = None) -> list[dict]:
    filters = dict(filters or {})
    query = dict(filters)
    # 分类和异常统计必须基于完整结果集，不能在 2000 条时静默截断。
    query["candidate_limit"] = 0
    batches = batch_service.get_batch_list(query).get("items") or []
    stats = _load_current_item_stats([row["name"] for row in batches])
    classified = [
        {**row, **classify_batch(row, stats.get(row["name"], {}))}
        for row in batches
    ]
    return [row for row in classified if _matches_workbench_filters(row, filters)]


def get_workbench_batches(
    filters: dict | None = None,
    task: str = "pending",
    page=1,
    page_length=30,
) -> dict:
    classified = filter_batches_for_task(_classified_batches(filters), task)
    page, page_length = normalize_page(page, page_length)
    offset = (page - 1) * page_length
    return {
        "ok": True,
        "items": classified[offset : offset + page_length],
        "total": len(classified),
        "page": page,
        "page_length": page_length,
    }


def get_workbench_summary(filters: dict | None = None) -> dict:
    counts = {"purchase": 0, "logistics": 0, "calculation": 0, "erp_failed": 0}
    for row in _classified_batches(filters):
        for code in row["issue_codes"]:
            counts[code] += 1
    return {"ok": True, "counts": counts}


def get_batch_items_page(
    batch_name: str,
    version_name: str | None = None,
    keyword: str = "",
    page=1,
    page_length=50,
    field_group: str = "basic",
    sort_by: str = "row_no",
    sort_order: str = "asc",
) -> dict:
    query = normalize_item_query(page, page_length, field_group, sort_by, sort_order)
    columns = select_item_columns(batch_service.EXCEL_COLUMNS, query["group"])
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "batch_name": batch_name,
            "version_name": version_name,
            "columns": columns,
            "items": [],
            "total": 0,
            "page": query["page"],
            "page_length": query["page_length"],
            "page_count": 0,
            "field_group": query["group"],
        }

    batch_doc_name = batch_service._resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}
    resolved_version = batch_service._resolve_version_name(batch_doc_name, version_name)
    if not resolved_version:
        return {"ok": False, "batch_name": batch_doc_name, "message": "当前批次没有版本。"}

    db_filters, or_filters = batch_service._build_item_query_args(
        batch_doc_name,
        resolved_version,
        keyword=keyword,
    )
    fieldnames = list(
        dict.fromkeys(
            ["name", "row_no", "excel_row_no", "modified"]
            + [column["fieldname"] for column in columns]
        )
    )
    count_rows = frappe.get_all(
        "Overseas Cost Item",
        filters=db_filters,
        or_filters=or_filters,
        fields=_item_count_fields_for_frappe(),
        limit_page_length=1,
    )
    total = int((count_rows[0] if count_rows else {}).get("total") or 0)
    items = frappe.get_all(
        "Overseas Cost Item",
        filters=db_filters,
        or_filters=or_filters,
        fields=fieldnames,
        order_by=f"{query['sort_by']} {query['sort_order']}",
        limit_start=(query["page"] - 1) * query["page_length"],
        limit_page_length=query["page_length"],
    )
    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "version_name": resolved_version,
        "columns": columns,
        "items": items,
        "total": total,
        "page": query["page"],
        "page_length": query["page_length"],
        "page_count": (total + query["page_length"] - 1) // query["page_length"],
        "field_group": query["group"],
    }


def locate_batch_item(
    batch_name: str,
    item_name: str,
    version_name: str | None = None,
    page_length=50,
) -> dict:
    """定位 SKU 在无筛选、按原始行号排序的详情页码。"""

    _page, page_length = normalize_page(1, page_length, default_length=50)
    if frappe is None:
        return {"ok": False, "dry_run": True, "message": "当前未连接 Frappe。"}
    batch_doc_name = batch_service._resolve_batch_name(batch_name)
    if not batch_doc_name:
        return {"ok": False, "message": f"未找到批次：{batch_name}"}
    resolved_version = batch_service._resolve_version_name(batch_doc_name, version_name)
    if not resolved_version:
        return {"ok": False, "message": "当前批次没有版本。"}

    fields = list(dict.fromkeys(["name", "row_no", "excel_row_no"] + batch_service.EXCEL_FIELDNAMES))
    items = frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_doc_name, "version": resolved_version},
        fields=fields,
        order_by="row_no asc, name asc",
        limit_page_length=0,
    )
    normalized_item_name = str(item_name or "").strip()
    index = next((index for index, item in enumerate(items) if item.get("name") == normalized_item_name), -1)
    if index < 0:
        return {"ok": False, "message": "当前批次中没有找到该 SKU。"}
    return {
        "ok": True,
        "batch_name": batch_doc_name,
        "version_name": resolved_version,
        "item": items[index],
        "page": index // page_length + 1,
        "page_length": page_length,
        "total": len(items),
    }
