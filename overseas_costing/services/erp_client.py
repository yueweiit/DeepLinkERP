"""中文用途：DeepLinkERP 推送客户端。

配置读取顺序：环境变量优先，其次 Frappe site_config。
不要把接口地址、token、目标 DocType 写死在代码里。
"""

from __future__ import annotations

import json
import os
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    import frappe
except Exception:  # pragma: no cover - 本地单测无 Frappe 时保持可导入
    frappe = None


DEFAULT_TIMEOUT = 20
SETTINGS_DOCTYPE = "Overseas Cost ERP Settings"
PUSH_MODE_STANDARD = "standard_purchase"
PUSH_MODE_GENERIC = "generic_resource"


class AmbiguousRemoteBusinessKey(RuntimeError):
    """Raised when one stable business key resolves to multiple remote documents."""


if frappe is not None:
    whitelist = frappe.whitelist
else:  # pragma: no cover - 本地单测无 Frappe 时保持可导入
    def whitelist(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator


@whitelist()
def check_erp_connection() -> dict:
    """检查 ERP 对接设置是否能连通目标模块。

    这里只发 GET 检查请求，不创建、不修改 ERP 单据。
    """

    config = get_erp_push_config()
    missing = _missing_config_reasons(config)
    if missing:
        return {
            "ok": False,
            "config_ready": False,
            "message": "；".join(missing),
            "request": _redact_request_config(config),
        }

    urls = _connection_check_urls(config)
    try:
        responses = []
        for url in urls:
            request = _build_request(config, url=url, method="GET")
            with urlopen(request, timeout=config["timeout"]) as response:
                response_text = response.read().decode("utf-8", errors="ignore")
                responses.append(
                    {
                        "url": url,
                        "http_status": getattr(response, "status", 200),
                        "response": _load_json_response(response_text),
                    }
                )
        return {
            "ok": True,
            "config_ready": True,
            "http_status": responses[-1]["http_status"] if responses else 200,
            "message": _connection_success_message(config),
            "request": _redact_request_config(config),
            "response": {"checks": responses},
        }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return {
            "ok": False,
            "config_ready": True,
            "http_status": exc.code,
            "message": f"ERP 连接检查失败：HTTP {exc.code} {_compact_text(detail)}",
            "request": _redact_request_config(config),
            "response": _load_json_response(detail),
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "config_ready": True,
            "message": f"ERP 连接检查失败：{exc}",
            "request": _redact_request_config(config),
            "response": {},
        }


def push_overseas_cost_payload(payload: dict) -> dict:
    """把已确认的海外成本报文推送到 DeepLinkERP。

    默认走 ERPNext 标准模块：
    - Item：物料档案
    - Purchase Order：采购订单草稿

    通用 DocType 推送保留为兜底模式，避免影响既有测试入口。
    """

    validation = validate_payload_for_push(payload)
    if not validation.get("ok"):
        return {
            "status": "Failed",
            **validation,
        }

    config = get_erp_push_config()
    if config.get("push_mode") == PUSH_MODE_STANDARD:
        return _push_standard_purchase_flow(payload, config)

    return _push_generic_resource(payload, config)


def validate_payload_for_push(payload: dict | None = None) -> dict:
    config = get_erp_push_config()
    missing = _missing_config_reasons(config, payload=payload or {})
    return {
        "ok": not missing,
        "ready": not missing,
        "config_ready": not missing,
        "blocking_reasons": missing,
        "request": _redact_request_config(config),
        "message": "ERP 推送配置已完成。" if not missing else "ERP 推送配置未完成：" + "；".join(missing),
    }


def _push_generic_resource(payload: dict, config: dict) -> dict:
    body = _build_resource_body(payload, config)
    url = _build_resource_url(config)
    request = _build_request(config, url=url, method=config["method"], body=body)

    try:
        with urlopen(request, timeout=config["timeout"]) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
            response_body = _load_json_response(response_text)
            target_doc = _extract_target_doc(response_body)
            return {
                "ok": True,
                "status": "Success",
                "config_ready": True,
                "http_status": getattr(response, "status", 200),
                "erp_target_doc": target_doc,
                "message": f"DeepLinkERP 返回成功{f'，目标单据 {target_doc}' if target_doc else ''}。",
                "request": _redact_request_config(config),
                "response": response_body,
            }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        response_body = _load_json_response(detail)
        return {
            "ok": False,
            "status": "Failed",
            "config_ready": True,
            "http_status": exc.code,
            "message": f"DeepLinkERP 接口返回失败：HTTP {exc.code} {_compact_text(detail)}",
            "request": _redact_request_config(config),
            "response": response_body,
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status": "Failed",
            "config_ready": True,
            "message": f"DeepLinkERP 接口调用失败：{exc}",
            "request": _redact_request_config(config),
            "response": {},
        }


def _push_standard_purchase_flow(payload: dict, config: dict) -> dict:
    try:
        stable_payload = dict(payload or {})
        if not stable_payload.get("business_key"):
            batch_key = stable_payload.get("batch_no") or stable_payload.get("batch_name") or ""
            stable_payload["business_key"] = f"legacy:{batch_key}"
        result = create_purchase(stable_payload, config)
        target_doc = result.get("erp_target_doc") or ""
        return {
            **result,
            "status": "Success",
            "config_ready": True,
            "message": (
                f"DeepLinkERP 已存在采购订单 {target_doc}，本次未重复创建。"
                if result.get("status") == "EXISTS"
                else f"已推送到 DeepLinkERP：采购订单 {target_doc or '已创建'}。"
            ),
            "request": _redact_request_config(config),
        }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        response_body = _load_json_response(detail)
        return {
            "ok": False,
            "status": "Failed",
            "config_ready": True,
            "http_status": exc.code,
            "message": f"DeepLinkERP 标准模块推送失败：HTTP {exc.code} {_compact_text(detail)}",
            "request": _redact_request_config(config),
            "response": response_body,
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status": "Failed",
            "config_ready": True,
            "message": f"DeepLinkERP 标准模块调用失败：{exc}",
            "request": _redact_request_config(config),
            "response": {},
        }


def get_erp_push_config() -> dict:
    settings = _load_erp_settings()
    base_url = _conf_value(
        "OVERSEAS_COSTING_ERP_BASE_URL",
        "DEEPLINKERP_BASE_URL",
        "DEEPLINK_ERP_BASE_URL",
        "overseas_costing_erp_base_url",
        settings=settings,
        settings_field="base_url",
    )
    authorization = _conf_value(
        "OVERSEAS_COSTING_ERP_AUTHORIZATION",
        "DEEPLINKERP_AUTHORIZATION",
        "DEEPLINK_ERP_AUTHORIZATION",
        "overseas_costing_erp_authorization",
        settings=settings,
        settings_field="authorization",
    )
    if not authorization:
        api_key = _conf_value("OVERSEAS_COSTING_ERP_API_KEY", "DEEPLINKERP_API_KEY", "overseas_costing_erp_api_key")
        api_secret = _conf_value(
            "OVERSEAS_COSTING_ERP_API_SECRET",
            "DEEPLINKERP_API_SECRET",
            "overseas_costing_erp_api_secret",
        )
        if api_key and api_secret:
            authorization = f"token {api_key}:{api_secret}"

    timeout = _conf_int(
        "OVERSEAS_COSTING_ERP_TIMEOUT",
        "DEEPLINKERP_TIMEOUT",
        default=DEFAULT_TIMEOUT,
        settings=settings,
        settings_field="timeout",
    )
    field_map = _conf_json(
        "OVERSEAS_COSTING_ERP_FIELD_MAP",
        "DEEPLINKERP_FIELD_MAP",
        settings=settings,
        settings_field="field_map_json",
    )
    push_mode = _clean(
        _conf_value(
            "OVERSEAS_COSTING_ERP_PUSH_MODE",
            "DEEPLINKERP_PUSH_MODE",
            settings=settings,
            settings_field="push_mode",
        )
    )
    if push_mode in ("标准模块（物料+采购订单）", "standard", "standard_purchase_order"):
        push_mode = PUSH_MODE_STANDARD
    elif push_mode in ("通用单据", "generic"):
        push_mode = PUSH_MODE_GENERIC
    push_mode = push_mode or PUSH_MODE_STANDARD
    return {
        "base_url": _clean(base_url),
        "authorization": _clean(authorization),
        "push_mode": push_mode,
        "company": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_COMPANY",
                "DEEPLINKERP_COMPANY",
                settings=settings,
                settings_field="company",
            )
        ),
        "supplier": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_SUPPLIER",
                "DEEPLINKERP_SUPPLIER",
                settings=settings,
                settings_field="supplier",
            )
        ),
        "cost_center": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_COST_CENTER",
                "DEEPLINKERP_COST_CENTER",
                settings=settings,
                settings_field="cost_center",
            )
        ),
        "item_group": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_ITEM_GROUP",
                "DEEPLINKERP_ITEM_GROUP",
                default="All Item Groups",
                settings=settings,
                settings_field="item_group",
            )
        ),
        "stock_uom": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_STOCK_UOM",
                "DEEPLINKERP_STOCK_UOM",
                default="Nos",
                settings=settings,
                settings_field="stock_uom",
            )
        ),
        "default_currency": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_DEFAULT_CURRENCY",
                "DEEPLINKERP_DEFAULT_CURRENCY",
                default="CNY",
                settings=settings,
                settings_field="default_currency",
            )
        ),
        "schedule_date": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_SCHEDULE_DATE",
                "DEEPLINKERP_SCHEDULE_DATE",
                settings=settings,
                settings_field="schedule_date",
            )
        ),
        "target_doctype": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_TARGET_DOCTYPE",
                "DEEPLINKERP_TARGET_DOCTYPE",
                "DEEPLINK_ERP_TARGET_DOCTYPE",
                "overseas_costing_erp_target_doctype",
                settings=settings,
                settings_field="target_doctype",
            )
        ),
        "method": (
            _clean(
                _conf_value(
                    "OVERSEAS_COSTING_ERP_HTTP_METHOD",
                    "DEEPLINKERP_HTTP_METHOD",
                    settings=settings,
                    settings_field="http_method",
                )
            )
            or "POST"
        ).upper(),
        "timeout": timeout,
        "field_map": field_map if isinstance(field_map, dict) else {},
        "payload_field": _clean(
            _conf_value(
                "OVERSEAS_COSTING_ERP_PAYLOAD_FIELD",
                "DEEPLINKERP_PAYLOAD_FIELD",
                settings=settings,
                settings_field="payload_field",
            )
        )
        or "payload_json",
        "enabled": bool(settings.get("enabled", 1)),
    }


def _missing_config_reasons(config: dict, payload: dict | None = None) -> list[str]:
    reasons = []
    payload = payload or {}
    if not config.get("base_url"):
        reasons.append("缺少 DeepLinkERP 接口地址配置")
    if not config.get("authorization"):
        reasons.append("缺少 DeepLinkERP 鉴权配置")
    if config.get("push_mode") == PUSH_MODE_GENERIC and not config.get("target_doctype"):
        reasons.append("缺少 DeepLinkERP 目标 DocType 配置")
    if config.get("push_mode") == PUSH_MODE_STANDARD:
        if not config.get("supplier") and not _payload_has_supplier(payload):
            reasons.append("缺少默认供应商配置")
        if not config.get("item_group"):
            reasons.append("缺少默认物料组配置")
        if not config.get("stock_uom"):
            reasons.append("缺少默认计量单位配置")
    if config.get("enabled") is False:
        reasons.append("ERP 推送设置当前未启用")
    if config.get("push_mode") == PUSH_MODE_GENERIC and config.get("method") not in {"POST", "PUT", "PATCH"}:
        reasons.append("DeepLinkERP HTTP 方法只支持 POST/PUT/PATCH")
    return reasons


def _payload_has_supplier(payload: dict) -> bool:
    if str(payload.get("supplier") or "").strip():
        return True
    return bool(_unique_item_value(payload.get("items") or [], "supplier"))


def _build_resource_url(config: dict) -> str:
    return _build_doctype_url(config, str(config.get("target_doctype") or "").strip())


def _build_doctype_url(config: dict, doctype: str, docname: str | None = None) -> str:
    base_url = str(config.get("base_url") or "").rstrip("/")
    doctype = quote(str(doctype or "").strip(), safe="")
    if docname:
        return f"{base_url}/{doctype}/{quote(str(docname), safe='')}"
    return f"{base_url}/{doctype}"


def _build_request(config: dict, url: str, method: str, body: dict | None = None) -> Request:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
    return Request(
        url,
        data=data,
        headers={
            "Authorization": config["authorization"],
            "Content-Type": "application/json",
        },
        method=method,
    )


def _request_json(config: dict, *, method: str, url: str, body: dict | None = None) -> dict:
    request = _build_request(config, url=url, method=method, body=body)
    with urlopen(request, timeout=config.get("timeout") or DEFAULT_TIMEOUT) as response:
        return _load_json_response(response.read().decode("utf-8", errors="ignore"))


def _connection_check_urls(config: dict) -> list[str]:
    if config.get("push_mode") == PUSH_MODE_STANDARD:
        return [
            f"{_build_doctype_url(config, 'Item')}?limit_page_length=1",
            f"{_build_doctype_url(config, 'Purchase Order')}?limit_page_length=1",
        ]
    return [f"{_build_resource_url(config)}?limit_page_length=1"]


def _connection_success_message(config: dict) -> str:
    if config.get("push_mode") == PUSH_MODE_STANDARD:
        return "ERP 连接检查通过，Item 和 Purchase Order 标准模块可访问。"
    return "ERP 连接检查通过，接口地址、鉴权和目标 DocType 可访问。"


def _build_resource_body(payload: dict, config: dict) -> dict:
    field_map = config.get("field_map") or {}
    if field_map:
        body = {}
        for erp_field, source_path in field_map.items():
            body[str(erp_field)] = _get_path_value(payload, str(source_path))
        return body

    return {
        "batch_no": payload.get("batch_no") or payload.get("batch_name") or "",
        "batch_name": payload.get("batch_name") or "",
        "version_name": payload.get("version_name") or "",
        "version_code": payload.get("version_code") or "",
        "subsidiary_code": payload.get("subsidiary_code") or "",
        "item_count": payload.get("item_count") or 0,
        "total_cost_rmb": payload.get("total_cost_rmb") or 0,
        str(config.get("payload_field") or "payload_json"): json.dumps(payload, ensure_ascii=False, default=str),
    }


def _get_path_value(payload: dict, path: str):
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _extract_target_doc(response_body) -> str:
    if isinstance(response_body, dict):
        data = response_body.get("data")
        if isinstance(data, dict):
            return str(data.get("name") or data.get("docname") or data.get("id") or "")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return str(data[0].get("name") or data[0].get("docname") or data[0].get("id") or "")
        return str(response_body.get("name") or response_body.get("docname") or response_body.get("id") or "")
    return ""


def _find_existing_purchase_order(payload: dict, config: dict) -> str:
    batch_no = payload.get("batch_no") or payload.get("batch_name") or ""
    version_code = payload.get("version_code") or payload.get("version_name") or ""
    if not batch_no:
        return ""

    filters = [["custom_overseas_batch_no", "=", batch_no]]
    if version_code:
        filters.append(["custom_overseas_cost_version", "=", version_code])
    url = (
        f"{_build_doctype_url(config, 'Purchase Order')}"
        f"?fields={quote(json.dumps(['name'], ensure_ascii=False), safe='')}"
        f"&filters={quote(json.dumps(filters, ensure_ascii=False), safe='')}"
        "&limit_page_length=1"
    )
    request = _build_request(config, url=url, method="GET")
    try:
        with urlopen(request, timeout=config["timeout"]) as response:
            response_body = _load_json_response(response.read().decode("utf-8", errors="ignore"))
    except HTTPError as exc:
        if exc.code == 417:
            return ""
        raise
    data = response_body.get("data") if isinstance(response_body, dict) else None
    if isinstance(data, list) and data:
        return str((data[0] or {}).get("name") or "")
    return ""


def _find_existing_purchase_order_by_business_key(payload: dict, config: dict) -> str:
    business_key = str(payload.get("business_key") or "").strip()
    if not business_key:
        raise ValueError("business_key is required")
    filters = [["custom_overseas_business_key", "=", business_key]]
    url = (
        f"{_build_doctype_url(config, 'Purchase Order')}"
        f"?fields={quote(json.dumps(['name'], ensure_ascii=False), safe='')}"
        f"&filters={quote(json.dumps(filters, ensure_ascii=False), safe='')}"
        "&limit_page_length=2"
    )
    try:
        data = (_request_json(config, method="GET", url=url).get("data") or [])
    except HTTPError as exc:
        if exc.code == 417:
            return ""
        raise
    if len(data) > 1:
        raise AmbiguousRemoteBusinessKey(business_key)
    return str((data[0] if data else {}).get("name") or "")


def lookup_purchase_by_business_key(payload: dict, config: dict) -> dict:
    name = _find_existing_purchase_order_by_business_key(payload, config)
    return {"found": bool(name), "name": name}


def lookup_legacy_purchase_candidates(payload: dict, config: dict) -> list[dict]:
    """Read at most three old purchase documents by batch number; never mutate ERP."""

    batch_no = str(payload.get("batch_no") or payload.get("batch_name") or "").strip()
    if not batch_no:
        return []
    filters = [["custom_overseas_batch_no", "=", batch_no]]
    list_url = (
        f"{_build_doctype_url(config, 'Purchase Order')}"
        f"?fields={quote(json.dumps(['name'], ensure_ascii=False), safe='')}"
        f"&filters={quote(json.dumps(filters, ensure_ascii=False), safe='')}"
        "&limit_page_length=3"
    )
    rows = (_request_json(config, method="GET", url=list_url).get("data") or [])
    candidates = []
    for row in rows[:3]:
        name = str((row or {}).get("name") or "")
        if not name:
            continue
        document = (_request_json(
            config,
            method="GET",
            url=_build_doctype_url(config, "Purchase Order", name),
        ).get("data") or {})
        candidates.append(
            {
                "name": str(document.get("name") or name),
                "docstatus": int(document.get("docstatus") or 0),
                "business_key": str(document.get("custom_overseas_business_key") or ""),
                "cost_result_hash": str(document.get("custom_overseas_cost_result_hash") or ""),
                "items": [
                    {
                        "stable_line_key": str(item.get("custom_overseas_stable_line_key") or ""),
                        "quantity": item.get("qty") or 0,
                        "remote_row": str(item.get("name") or ""),
                        "goods_value": item.get("custom_overseas_original_amount") or 0,
                        "total_cost_rmb": item.get("custom_overseas_comprehensive_amount") or 0,
                        "total_unit_rmb": item.get("custom_overseas_comprehensive_unit_price") or 0,
                        "freight_alloc_rmb": item.get("custom_overseas_freight_alloc_amount") or 0,
                        "clearance_alloc_rmb": item.get("custom_overseas_clearance_alloc_amount") or 0,
                        "tax_alloc_rmb": item.get("custom_overseas_tax_alloc_amount") or 0,
                        "amount_status": str(item.get("custom_overseas_amount_status") or document.get("custom_overseas_amount_status") or ""),
                    }
                    for item in document.get("items") or []
                ],
            }
        )
    return candidates


def create_purchase(payload: dict, config: dict) -> dict:
    """Create a draft purchase in one explicitly selected ERP site."""

    existing = lookup_purchase_by_business_key(payload, config)
    if existing.get("found"):
        return {
            "ok": True,
            "status": "EXISTS",
            "erp_target_doc": str(existing.get("name") or ""),
            "response": {"purchase_order": {"name": existing.get("name"), "deduplicated": True}, "items": []},
        }
    item_results = [_ensure_item(item, payload, config) for item in payload.get("items") or []]
    response = _request_json(
        config,
        method="POST",
        url=_build_doctype_url(config, "Purchase Order"),
        body=_build_purchase_order_body(payload, config),
    )
    return {
        "ok": True,
        "status": "CREATED",
        "erp_target_doc": _extract_target_doc(response),
        "response": {"purchase_order": response, "items": item_results},
    }


def read_purchase_state(link: dict, config: dict) -> dict:
    return _request_json(
        config,
        method="GET",
        url=_build_doctype_url(config, link["remote_doctype"], link["remote_document"]),
    )


def build_draft_purchase_cost_update(old_link: dict, new_cost: dict) -> dict:
    try:
        old_quantity = float(old_link.get("quantity") or 0)
        new_quantity = float(new_cost.get("effective_shipped_qty") or new_cost.get("quantity") or 0)
    except (TypeError, ValueError):
        raise ValueError("BUSINESS_CHANGE_REQUIRED")
    if old_quantity != new_quantity:
        raise ValueError("BUSINESS_CHANGE_REQUIRED")
    return {
        "custom_overseas_original_amount": new_cost.get("goods_value") or 0,
        "custom_overseas_comprehensive_amount": new_cost.get("total_cost_rmb") or 0,
        "custom_overseas_comprehensive_unit_price": new_cost.get("total_unit_rmb") or 0,
        "custom_overseas_freight_alloc_amount": new_cost.get("freight_alloc_rmb") or 0,
        "custom_overseas_clearance_alloc_amount": new_cost.get("clearance_alloc_rmb") or 0,
        "custom_overseas_tax_alloc_amount": new_cost.get("tax_alloc_rmb") or 0,
        "custom_overseas_cost_result_hash": new_cost.get("cost_result_hash") or "",
        "custom_overseas_amount_status": new_cost.get("amount_status") or "",
    }


def update_purchase_cost(payload: dict, link: dict, config: dict) -> dict:
    mode = str(config.get("cost_update_mode") or "DISABLED").upper()
    if mode == "DISABLED":
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "UPDATE_MODE_UNAVAILABLE"}
    if mode != "DRAFT_PURCHASE_ORDER":
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "MANUAL_COST_UPDATE_REQUIRED"}
    current = read_purchase_state(link, config).get("data") or {}
    if int(current.get("docstatus") or 0) != 0:
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "DOCUMENT_NOT_DRAFT"}
    if float(current.get("per_received") or 0) > 0:
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "DOCUMENT_HAS_RECEIPTS"}
    stable_key = str(link.get("stable_line_key") or "")
    new_cost = next(
        (row for row in payload.get("items") or [] if str(row.get("stable_line_key") or "") == stable_key),
        None,
    )
    if not new_cost:
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "UPDATE_ITEM_NOT_FOUND"}
    remote_matches = [
        row
        for row in current.get("items") or []
        if str(row.get("custom_overseas_stable_line_key") or "") == stable_key
        or (link.get("remote_row") and str(row.get("name") or "") == str(link.get("remote_row")))
    ]
    if len(remote_matches) != 1:
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "REMOTE_LINE_NOT_UNIQUE"}
    remote_row = remote_matches[0]
    item_body = build_draft_purchase_cost_update(
        {**link, "quantity": remote_row.get("qty")},
        new_cost,
    )
    item_response = _request_json(
        config,
        method="PUT",
        url=_build_doctype_url(config, "Purchase Order Item", remote_row.get("name") or link.get("remote_row")),
        body=item_body,
    )
    amount_status = payload.get("amount_status") or new_cost.get("amount_status") or ""
    header_body = {
        "custom_overseas_cost_version": payload.get("version_code") or payload.get("version_name") or "",
        "custom_overseas_cost_result_hash": payload.get("cost_result_hash") or new_cost.get("cost_result_hash") or "",
        "custom_overseas_total_cost_rmb": payload.get("document_total_cost_rmb") or payload.get("total_cost_rmb") or 0,
        "custom_overseas_amount_status": amount_status,
    }
    header_response = _request_json(
        config,
        method="PUT",
        url=_build_doctype_url(config, link["remote_doctype"], link["remote_document"]),
        body=header_body,
    )
    return {"ok": True, "status": "UPDATED", "item": item_response, "header": header_response}


def _ensure_item(item: dict, payload: dict, config: dict) -> dict:
    item_code = str(item.get("material_code") or "").strip()
    if not item_code:
        return {"ok": False, "message": "物料编码为空，已跳过。"}

    body = _build_item_body(item, payload, config)
    exists = _resource_exists(config, "Item", item_code)
    if exists:
        return {"ok": True, "item_code": item_code, "action": "existing", "response": {}}
    response_body = _request_json(
        config,
        method="POST",
        url=_build_doctype_url(config, "Item"),
        body=body,
    )
    return {
        "ok": True,
        "item_code": item_code,
        "action": "created",
        "response": response_body,
    }


def _resource_exists(config: dict, doctype: str, docname: str) -> bool:
    request = _build_request(config, url=_build_doctype_url(config, doctype, docname), method="GET")
    try:
        with urlopen(request, timeout=config["timeout"]):
            return True
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def _build_item_body(item: dict, payload: dict, config: dict) -> dict:
    formula = item.get("cost_formula") or {}
    item_code = str(item.get("material_code") or "").strip()
    item_name = str(item.get("material_name") or item.get("product_name") or item_code).strip()
    return {
        "item_code": item_code,
        "item_name": item_name or item_code,
        "item_group": config.get("item_group") or "All Item Groups",
        "stock_uom": config.get("stock_uom") or "Nos",
        "is_stock_item": 1,
        "custom_overseas_batch_no": payload.get("batch_no") or payload.get("batch_name") or "",
        "custom_overseas_cost_version": payload.get("version_code") or payload.get("version_name") or "",
        "custom_overseas_business_entity": payload.get("subsidiary_code") or "",
        "custom_overseas_supplier": item.get("supplier") or payload.get("supplier") or "",
        "custom_overseas_original_unit_price": item.get("original_unit_price") or formula.get("original_unit_price") or 0,
        "custom_overseas_comprehensive_unit_price": item.get("comprehensive_unit_price")
        or formula.get("comprehensive_unit_price")
        or 0,
    }


def _build_purchase_order_body(payload: dict, config: dict) -> dict:
    items = payload.get("items") or []
    schedule_date = config.get("schedule_date") or date.today().isoformat()
    company = config.get("company") or payload.get("subsidiary_code") or ""
    currency = _normalize_currency(_first_item_value(items, "purchase_currency") or config.get("default_currency") or "CNY")
    supplier, supplier_source = _resolve_supplier(payload, config, items)
    return {
        "company": company,
        "supplier": supplier,
        "transaction_date": date.today().isoformat(),
        "schedule_date": schedule_date,
        "currency": currency,
        "custom_overseas_batch_no": payload.get("batch_no") or payload.get("batch_name") or "",
        "custom_overseas_cost_version": payload.get("version_code") or payload.get("version_name") or "",
        "custom_overseas_business_key": payload.get("business_key") or "",
        "custom_overseas_cost_result_hash": payload.get("cost_result_hash") or "",
        "custom_overseas_amount_status": payload.get("amount_status") or (
            "ESTIMATED" if payload.get("estimated_fee_keys") else "ACTUAL"
        ),
        "custom_overseas_business_entity": payload.get("subsidiary_code") or "",
        "custom_overseas_total_cost_rmb": payload.get("total_cost_rmb") or 0,
        "custom_overseas_supplier_source": supplier_source,
        "custom_overseas_cost_payload_json": json.dumps(payload, ensure_ascii=False, default=str),
        "items": [_build_purchase_order_item(row, payload, config, schedule_date) for row in items],
    }


def _build_purchase_order_item(item: dict, payload: dict, config: dict, schedule_date: str) -> dict:
    formula = item.get("cost_formula") or {}
    expense_detail = item.get("expense_detail") or {}
    logistics = expense_detail.get("logistics") or {}
    clearance_tax = expense_detail.get("clearance_and_tax") or {}
    qty = item.get("source_quantity") or item.get("outbound_quantity") or formula.get("quantity") or 0
    original_unit_price = item.get("original_unit_price") or formula.get("original_unit_price") or 0
    comprehensive_unit_price = item.get("comprehensive_unit_price") or formula.get("comprehensive_unit_price") or 0
    original_amount = item.get("goods_value") or formula.get("goods_value") or _multiply(original_unit_price, qty)
    comprehensive_amount = formula.get("total_cost") or _multiply(comprehensive_unit_price, qty)
    freight_amount = logistics.get("freight_alloc_rmb") or formula.get("allocated_logistics_cost") or 0
    clearance_amount = clearance_tax.get("clearance_alloc_rmb")
    if clearance_amount is None:
        clearance_amount = clearance_tax.get("mexico_customs_rmb") or clearance_tax.get("mexico_customs_mxn") or 0
    tax_amount = clearance_tax.get("tax_alloc_rmb")
    if tax_amount is None:
        tax_amount = (
            clearance_tax.get("import_tax_total")
            or _multiply(1, clearance_tax.get("igi_amount") or 0) + _multiply(1, clearance_tax.get("iva_amount") or 0)
        )
    original_amount = _round_currency(original_amount)
    freight_amount = _round_currency(freight_amount)
    clearance_amount = _round_currency(clearance_amount)
    tax_amount = _round_currency(tax_amount)
    comprehensive_amount = _round_currency(comprehensive_amount)
    clearance_amount = _round_currency(
        clearance_amount
        + comprehensive_amount
        - original_amount
        - freight_amount
        - clearance_amount
        - tax_amount
    )
    row = {
        "item_code": item.get("material_code") or "",
        "item_name": item.get("material_name") or "",
        "qty": qty,
        "uom": config.get("stock_uom") or "Nos",
        "stock_uom": config.get("stock_uom") or "Nos",
        "conversion_factor": 1,
        "schedule_date": schedule_date,
        "rate": original_unit_price,
        "custom_overseas_original_unit_price": original_unit_price,
        "custom_overseas_comprehensive_unit_price": comprehensive_unit_price,
        "custom_overseas_original_amount": original_amount,
        "custom_overseas_comprehensive_amount": comprehensive_amount,
        "custom_overseas_freight_alloc_amount": freight_amount,
        "custom_overseas_clearance_alloc_amount": clearance_amount,
        "custom_overseas_tax_alloc_amount": tax_amount,
        "custom_overseas_batch_no": payload.get("batch_no") or payload.get("batch_name") or "",
        "custom_overseas_cost_version": payload.get("version_code") or payload.get("version_name") or "",
        "custom_overseas_stable_line_key": item.get("stable_line_key") or "",
        "custom_overseas_business_entity": payload.get("subsidiary_code") or "",
        "custom_overseas_cost_center": config.get("cost_center") or payload.get("cost_center") or "",
    }
    if config.get("cost_center"):
        row["cost_center"] = config.get("cost_center")
    return row


def _resolve_supplier(payload: dict, config: dict, items: list[dict]) -> tuple[str, str]:
    for source, value in (
        ("batch", payload.get("supplier")),
        ("item", _unique_item_value(items, "supplier")),
        ("config", config.get("supplier")),
    ):
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned, source
    return "", "missing"


def _unique_item_value(items: list[dict], fieldname: str):
    values = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = str(item.get(fieldname) or "").strip()
        if value and value not in values:
            values.append(value)
    return values[0] if len(values) == 1 else None


def _first_item_value(items: list[dict], fieldname: str):
    for item in items:
        value = item.get(fieldname)
        if value not in (None, ""):
            return value
    return None


def _normalize_currency(value) -> str:
    currency = str(value or "").strip().upper().replace(" ", "")
    currency_aliases = {
        "RMB": "CNY",
        "人民币": "CNY",
        "人民币RMB": "CNY",
        "CNY人民币": "CNY",
        "美元": "USD",
        "美元USD": "USD",
        "USD美元": "USD",
        "墨西哥比索": "MXN",
        "墨西哥比索MXN": "MXN",
        "MXN墨西哥比索": "MXN",
    }
    if currency in currency_aliases:
        return currency_aliases[currency]
    return currency or "CNY"


def _multiply(left, right) -> float:
    try:
        return round(float(left or 0) * float(right or 0), 6)
    except (TypeError, ValueError):
        return 0


def _round_currency(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0


def _load_json_response(text: str):
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": _compact_text(text, limit=1000)}


def _compact_text(text: str, limit: int = 300) -> str:
    compact = " ".join(str(text or "").split())
    return compact[:limit]


def _redact_request_config(config: dict) -> dict:
    return {
        "base_url": config.get("base_url") or "",
        "push_mode": config.get("push_mode") or "",
        "target_doctype": config.get("target_doctype") or "",
        "method": config.get("method") or "",
        "timeout": config.get("timeout") or DEFAULT_TIMEOUT,
        "authorization_configured": bool(config.get("authorization")),
        "field_map_configured": bool(config.get("field_map")),
        "company_configured": bool(config.get("company")),
        "supplier_configured": bool(config.get("supplier")),
        "cost_center_configured": bool(config.get("cost_center")),
        "item_group": config.get("item_group") or "",
        "stock_uom": config.get("stock_uom") or "",
    }


def _load_erp_settings() -> dict:
    if frappe is None:
        return {}
    try:
        if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
            return {}
        values = frappe.get_single(SETTINGS_DOCTYPE)
    except Exception:
        return {}

    settings = {}
    for fieldname in (
        "enabled",
        "base_url",
        "authorization",
        "push_mode",
        "company",
        "supplier",
        "cost_center",
        "item_group",
        "stock_uom",
        "default_currency",
        "schedule_date",
        "target_doctype",
        "http_method",
        "timeout",
        "payload_field",
        "field_map_json",
    ):
        settings[fieldname] = _get_doc_field_value(values, fieldname)
    return settings


def _get_doc_field_value(doc, fieldname: str):
    if fieldname == "authorization" and hasattr(doc, "get_password"):
        try:
            value = doc.get_password(fieldname, raise_exception=False)
            if _has_value(value):
                return value
        except TypeError:
            try:
                value = doc.get_password(fieldname)
                if _has_value(value):
                    return value
            except Exception:
                pass
        except Exception:
            pass
    try:
        return doc.get(fieldname)
    except Exception:
        return getattr(doc, fieldname, None)


def _conf_value(*keys: str, default: str = "", settings: dict | None = None, settings_field: str = "") -> str:
    for key in keys:
        value = os.environ.get(key)
        if _has_value(value):
            return _clean(value)

    if settings and settings_field:
        value = settings.get(settings_field)
        if _has_value(value):
            return _clean(value)

    conf = getattr(frappe, "conf", None) if frappe is not None else None
    if conf:
        for key in keys:
            for candidate in (key, key.lower()):
                try:
                    value = conf.get(candidate) if hasattr(conf, "get") else getattr(conf, candidate, None)
                except Exception:
                    value = None
                if _has_value(value):
                    return _clean(value)
    return default


def _conf_int(*keys: str, default: int = 0, settings: dict | None = None, settings_field: str = "") -> int:
    value = _conf_value(*keys, settings=settings, settings_field=settings_field)
    if not _has_value(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _conf_json(*keys: str, settings: dict | None = None, settings_field: str = ""):
    value = _conf_value(*keys, settings=settings, settings_field=settings_field)
    if not _has_value(value):
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _has_value(value) -> bool:
    return value not in (None, "")


def _clean(value) -> str:
    return str(value or "").strip()
