"""中文用途：ERP 站点能力合同与只读核验规则。"""

from __future__ import annotations


def build_erpnext_standard_field_spec() -> dict[str, list[dict]]:
    """返回分站点同步额外依赖的 ERPNext 自定义字段定义。"""

    return {
        "Purchase Order": [
            {
                "fieldname": "custom_overseas_business_key",
                "label": "海外成本稳定业务键",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_cost_payload_json",
            },
            {
                "fieldname": "custom_overseas_cost_result_hash",
                "label": "海外成本结果哈希",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_business_key",
            },
            {
                "fieldname": "custom_overseas_amount_status",
                "label": "海外成本金额性质",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_cost_result_hash",
            },
        ],
        "Purchase Order Item": [
            {
                "fieldname": "custom_overseas_stable_line_key",
                "label": "海外成本稳定物料行键",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_cost_center",
            },
        ],
    }


def build_safe_site_summary(site: dict) -> dict:
    """输出供普通业务页面展示的站点摘要，永不包含凭据或接口地址。"""

    return {
        "site_code": _text(site.get("site_code")),
        "label": _text(site.get("label")),
        "subsidiary_code": _text(site.get("subsidiary_code")),
        "enabled": site.get("enabled", 1) not in (0, False, "0"),
        "push_mode": _text(site.get("push_mode")),
        "cost_update_mode": _text(site.get("cost_update_mode")) or "DISABLED",
        "capability_status": _text(site.get("capability_status")) or "UNVERIFIED",
        "capability_checked_at": site.get("capability_checked_at"),
    }


def evaluate_erpnext_metadata(metadata: dict) -> dict:
    """根据已读取的远端 DocType 元数据判断是否满足分站点同步字段合同。"""

    required = build_erpnext_standard_field_spec()
    missing: dict[str, list[str]] = {}
    for doctype, fields in required.items():
        available = _fieldnames(metadata.get(doctype))
        absent = [field["fieldname"] for field in fields if field["fieldname"] not in available]
        if absent:
            missing[doctype] = absent

    return {
        "ok": not missing,
        "capability_status": "VERIFIED" if not missing else "FAILED",
        "missing_fields": missing,
        "message": "ERP 站点字段能力核验通过。" if not missing else "ERP 站点缺少海外成本同步字段。",
    }


def verify_erpnext_site(site_config: dict, metadata_reader=None) -> dict:
    """只读核验目标 ERPNext 站点是否具备海外成本同步所需字段。"""

    doctypes = list(build_erpnext_standard_field_spec())
    if metadata_reader is None:
        from overseas_costing.services.erp_client import read_erpnext_doctype_metadata

        metadata_reader = read_erpnext_doctype_metadata

    read_result = metadata_reader(site_config, doctypes)
    if not read_result.get("ok"):
        return {
            "ok": False,
            "capability_status": "FAILED",
            "missing_fields": {},
            "metadata_read": read_result,
            "message": read_result.get("message") or "ERP 站点元数据读取失败。",
        }

    evaluation = evaluate_erpnext_metadata(read_result.get("metadata") or {})
    return {**evaluation, "metadata_read": read_result}


def _fieldnames(value) -> set[str]:
    if isinstance(value, dict):
        value = value.get("fields") or value.get("data") or []
    names = set()
    for field in value or []:
        if isinstance(field, dict):
            name = _text(field.get("fieldname"))
        else:
            name = _text(field)
        if name:
            names.add(name)
    return names


def _text(value) -> str:
    return str(value or "").strip()
