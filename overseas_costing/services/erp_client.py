"""中文用途：DeepLinkERP 推送客户端。

配置读取顺序：环境变量优先，其次 Frappe site_config。
不要把接口地址、token、目标 DocType 写死在代码里。
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    import frappe
except Exception:  # pragma: no cover - 本地单测无 Frappe 时保持可导入
    frappe = None


DEFAULT_TIMEOUT = 20
SETTINGS_DOCTYPE = "Overseas Cost ERP Settings"


def push_overseas_cost_payload(payload: dict) -> dict:
    """把已确认的海外成本报文推送到 DeepLinkERP。

    目标 DocType 和字段映射尚未最终确认，所以这里做成配置化：
    - OVERSEAS_COSTING_ERP_BASE_URL / DEEPLINKERP_BASE_URL
    - OVERSEAS_COSTING_ERP_AUTHORIZATION / DEEPLINKERP_AUTHORIZATION
    - OVERSEAS_COSTING_ERP_TARGET_DOCTYPE / DEEPLINKERP_TARGET_DOCTYPE
    - OVERSEAS_COSTING_ERP_FIELD_MAP 可选，JSON 对象：ERP字段 -> 本地报文路径
    """

    config = get_erp_push_config()
    missing = _missing_config_reasons(config)
    if missing:
        return {
            "ok": False,
            "status": "Failed",
            "message": "；".join(missing),
            "config_ready": False,
            "request": _redact_request_config(config),
        }

    body = _build_resource_body(payload, config)
    url = _build_resource_url(config)
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
        headers={
            "Authorization": config["authorization"],
            "Content-Type": "application/json",
        },
        method=config["method"],
    )

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
    return {
        "base_url": _clean(base_url),
        "authorization": _clean(authorization),
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


def _missing_config_reasons(config: dict) -> list[str]:
    reasons = []
    if not config.get("base_url"):
        reasons.append("缺少 DeepLinkERP 接口地址配置")
    if not config.get("authorization"):
        reasons.append("缺少 DeepLinkERP 鉴权配置")
    if not config.get("target_doctype"):
        reasons.append("缺少 DeepLinkERP 目标 DocType 配置")
    if config.get("enabled") is False:
        reasons.append("ERP 推送设置当前未启用")
    if config.get("method") not in {"POST", "PUT", "PATCH"}:
        reasons.append("DeepLinkERP HTTP 方法只支持 POST/PUT/PATCH")
    return reasons


def _build_resource_url(config: dict) -> str:
    base_url = str(config.get("base_url") or "").rstrip("/")
    doctype = quote(str(config.get("target_doctype") or "").strip(), safe="")
    return f"{base_url}/{doctype}"


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
        "target_doctype": config.get("target_doctype") or "",
        "method": config.get("method") or "",
        "timeout": config.get("timeout") or DEFAULT_TIMEOUT,
        "authorization_configured": bool(config.get("authorization")),
        "field_map_configured": bool(config.get("field_map")),
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
        "target_doctype",
        "http_method",
        "timeout",
        "payload_field",
        "field_map_json",
    ):
        try:
            settings[fieldname] = values.get(fieldname)
        except Exception:
            settings[fieldname] = getattr(values, fieldname, None)
    return settings


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
