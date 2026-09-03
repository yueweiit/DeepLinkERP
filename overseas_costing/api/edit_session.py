"""批次编辑租约 API。"""

import frappe

from overseas_costing.services import edit_session_service
from overseas_costing.services.access_control import require_doctype_permission


@frappe.whitelist()
def acquire(batch_name: str) -> dict:
    require_doctype_permission("Overseas Cost Batch", "write", doc=batch_name)
    return edit_session_service.acquire_edit_session(batch_name)


@frappe.whitelist()
def renew(batch_name: str, edit_token: str) -> dict:
    require_doctype_permission("Overseas Cost Batch", "write", doc=batch_name)
    return edit_session_service.renew_edit_session(batch_name, edit_token)


@frappe.whitelist()
def release(batch_name: str, edit_token: str) -> dict:
    require_doctype_permission("Overseas Cost Batch", "write", doc=batch_name)
    return edit_session_service.release_edit_session(batch_name, edit_token)
