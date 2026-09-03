"""海外成本模块的统一访问控制。"""

from __future__ import annotations

try:
    import frappe
except Exception:  # pragma: no cover - 纯函数测试时保持可导入
    frappe = None


OVERSEAS_COST_ROLES = ("System Manager", "海外成本核算用户")
PERMISSION_LABELS = {
    "read": "查看",
    "write": "修改",
    "create": "新建",
    "delete": "删除",
}


def require_overseas_cost_access() -> None:
    """只允许页面配置中的两类角色调用 RPC。"""

    if frappe is None:
        raise RuntimeError("当前未连接 Frappe。")
    frappe.only_for(OVERSEAS_COST_ROLES)


def require_doctype_permission(doctype: str, ptype: str = "read", *, doc=None) -> None:
    """在角色门槛之外，尊重 DocType 对具体操作的授权。"""

    require_overseas_cost_access()
    permission_doc = doc
    if isinstance(doc, str) and hasattr(frappe, "get_doc"):
        permission_doc = frappe.get_doc(doctype, doc)
    if frappe.has_permission(doctype, ptype=ptype, doc=permission_doc):
        return
    label = PERMISSION_LABELS.get(ptype, ptype)
    frappe.throw(f"当前账号没有{label}权限：{doctype}。", frappe.PermissionError)


def require_batch_permission(batch_reference: str, ptype: str = "read") -> str:
    """解析批次业务单号，并检查当前用户对实际批次文档的权限。"""

    require_overseas_cost_access()
    from overseas_costing.services import batch_service

    batch_name = batch_service._resolve_batch_name(str(batch_reference or "").strip())
    if not batch_name:
        frappe.throw("未找到目标批次。", frappe.DoesNotExistError)
    require_doctype_permission("Overseas Cost Batch", ptype, doc=batch_name)
    return batch_name


def require_attachment_permission(attachment_name: str, ptype: str = "read") -> str:
    """附件权限必须同时满足附件本身与其所属批次的权限。"""

    normalized_name = str(attachment_name or "").strip()
    require_doctype_permission("Overseas Cost Attachment", ptype, doc=normalized_name)
    batch_name = frappe.db.get_value("Overseas Cost Attachment", normalized_name, "batch")
    if batch_name:
        require_batch_permission(batch_name, "write" if ptype in {"write", "delete"} else "read")
    return normalized_name


def validate_api_access() -> None:
    """Frappe auth hook：覆盖整个 overseas_costing.api 命名空间。"""

    if frappe is None:
        return
    form_dict = getattr(getattr(frappe, "local", None), "form_dict", None) or {}
    command = str(form_dict.get("cmd") or "")
    if command.startswith("overseas_costing.api."):
        require_overseas_cost_access()
