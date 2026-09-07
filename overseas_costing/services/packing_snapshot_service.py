"""中文用途：预览可信装箱来源，并确认不可变、可追溯的当前装箱快照。"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover - 仅在读取本地 Excel Sheet 名时需要
    load_workbook = None

try:
    import frappe
except Exception:  # pragma: no cover
    frappe = None

from overseas_costing.services import packing_source_service


Resolver = Callable[..., dict[str, Any]]


def preview_packing_source_v2(
    batch_name: str,
    source_kind: str,
    source_id: str,
    *,
    sheet_name: str | None = None,
    browser_payload: dict[str, Any] | None = None,
    resolver: Resolver | None = None,
) -> dict[str, Any]:
    """浏览器只提交受控 ID；正文、路径、汇总和工作簿 URL 一律重新从服务器读取。"""

    del browser_payload
    kind = packing_source_service.normalize_packing_source_kind(source_kind)
    trusted = (resolver or packing_source_service.resolve_trusted_packing_source)(
        batch_name=str(batch_name),
        source_kind=kind,
        source_id=str(source_id),
        sheet_name=sheet_name,
    )
    source_hash = str(trusted.get("source_hash") or "")
    if len(source_hash) != 64:
        raise ValueError("可信装箱来源缺少 SHA-256。")
    preview = copy.deepcopy(trusted.get("preview") or {})
    source = _public_source(trusted.get("source") or {})
    revision = packing_source_service._encode_revision(
        kind,
        str(source.get("source_id") or source_id),
        source_hash,
        batch_name=str(batch_name),
    )
    return {
        **preview,
        "ok": True,
        "preview_ready": True,
        "source": source,
        "source_kind": kind,
        "source_id": source.get("source_id") or str(source_id),
        "source_hash": source_hash,
        "source_revision": revision,
    }


def confirm_packing_snapshot(
    batch_name: str,
    source_revision: str,
    resolutions_json: str | dict[str, Any] | None,
    *,
    repository: Any | None = None,
    resolver: Resolver | None = None,
) -> dict[str, Any]:
    claims = packing_source_service.get_source_revision_claims(source_revision)
    if not claims or str(claims.get("batch") or "") != str(batch_name):
        return {"ok": False, "source_changed": True, "message": "装箱预览不属于当前批次，请重新预览。"}
    kind = packing_source_service.normalize_packing_source_kind(str(claims.get("kind") or ""))
    source_id = str(claims.get("id") or "")
    expected_hash = str(claims.get("hash") or "")
    resolutions = _parse_resolutions(resolutions_json)
    repo = repository or FrappePackingSnapshotRepository()
    repo.lock_batch(str(batch_name))
    try:
        trusted = (resolver or packing_source_service.resolve_trusted_packing_source)(
            batch_name=str(batch_name),
            source_kind=kind,
            source_id=source_id,
            sheet_name=resolutions.get("sheet_name"),
        )
        actual_hash = str(trusted.get("source_hash") or "")
        if not actual_hash or actual_hash != expected_hash:
            repo.rollback()
            return {"ok": False, "source_changed": True, "message": "装箱来源已更新，请重新预览后确认。"}
        preview = _apply_resolutions(trusted.get("preview") or {}, resolutions)
        blocking = (preview.get("validation") or {}).get("blocking") or []
        if blocking:
            repo.rollback()
            return {
                "ok": False,
                "needs_group_confirmation": bool((preview.get("validation") or {}).get("needs_group_confirmation")),
                "validation": preview.get("validation"),
                "message": "装箱分组或汇总仍有待确认项目。",
            }
        gross = _positive_decimal(((preview.get("totals") or {}).get("gross_weight_kg") or {}).get("value"))
        volume = _positive_decimal(((preview.get("totals") or {}).get("volume_m3") or {}).get("value"))
        if gross is None or volume is None:
            repo.rollback()
            return {"ok": False, "message": "比较运费前必须确认整票毛重和总体积。"}
        idempotency_key = _idempotency_key(batch_name, source_revision, resolutions)
        existing = repo.get_by_idempotency_key(idempotency_key)
        if existing:
            repo.rollback()
            return {"ok": True, "idempotent": True, "snapshot": _public_snapshot(existing)}
        current = repo.get_current(str(batch_name))
        if current:
            repo.supersede(current)
        source = _public_source(trusted.get("source") or {})
        now = datetime.now(timezone.utc).isoformat()
        next_version = repo.next_version(str(batch_name)) if hasattr(repo, "next_version") else 1
        totals = preview.get("totals") or {}
        values = {
            "batch": str(batch_name),
            "version": next_version,
            "idempotency_key": idempotency_key,
            "source_kind": kind,
            "source_id": source_id,
            "source_revision": source_revision,
            "source_label": source.get("source_label") or source_id,
            "source_locator_json": _json(source),
            "source_read_at": now,
            "source_updated_at": source.get("source_updated_at") or None,
            "source_hash": actual_hash,
            "status": "Confirmed",
            "is_current": 1,
            "material_row_count": int(preview.get("material_row_count") or 0),
            "package_count": int(preview.get("package_count") or 0),
            "total_net_weight_kg": _decimal_text(
                _decimal((totals.get("net_weight_kg") or {}).get("value"))
            ),
            "net_total_kind": (totals.get("net_weight_kg") or {}).get("kind") or "",
            "total_gross_weight_kg": _decimal_text(gross),
            "total_volume_m3": _decimal_text(volume),
            "material_rows_json": _json(preview.get("material_rows") or []),
            "package_groups_json": _json(preview.get("groups") or []),
            "totals_json": _json(totals),
            "validation_json": _json(preview.get("validation") or {}),
            "resolutions_json": _json(resolutions),
            "confirmed_by": _session_user(),
            "confirmed_at": now,
        }
        snapshot = repo.insert_snapshot(values)
        repo.write_audit(
            {
                "batch": str(batch_name),
                "version": repo.current_version(str(batch_name)),
                "action_type": "PACKING_CONFIRM",
                "field_name": "packing_snapshot",
                "old_value": _record_value(current, "name") if current else "",
                "new_value": _record_value(snapshot, "name"),
                "operator_name": _session_user(),
                "action_remark": f"确认装箱来源：{values['source_label']}",
            }
        )
        repo.commit()
        return {"ok": True, "idempotent": False, "snapshot": _public_snapshot(snapshot)}
    except Exception:
        repo.rollback()
        raise


def _apply_resolutions(preview: dict[str, Any], resolutions: dict[str, Any]) -> dict[str, Any]:
    resolved = copy.deepcopy(preview)
    group_resolutions = resolutions.get("groups") if isinstance(resolutions.get("groups"), dict) else {}
    unresolved = []
    resolved_groups = []
    for group in resolved.get("groups") or []:
        if not group.get("needs_confirmation"):
            resolved_groups.append(group)
            continue
        decision = group_resolutions.get(str(group.get("group_id") or ""))
        action = str((decision or {}).get("action") or "") if isinstance(decision, dict) else str(decision or "")
        if action in {"confirm_shared", "link", "shared"}:
            group["needs_confirmation"] = False
            for field in ("net_weight_kg", "gross_weight_kg", "volume_m3", "package_count"):
                if isinstance(group.get(field), dict) and group[field].get("value") is not None:
                    group[field]["count_once"] = True
            group.setdefault("evidence", []).append({"kind": "user_confirmed_shared"})
            resolved_groups.append(group)
        elif action == "split":
            rows = list(group.get("row_numbers") or [])
            for index, row_number in enumerate(rows):
                singleton = copy.deepcopy(group)
                singleton["group_id"] = f"{group.get('group_id')}-row-{row_number}"
                singleton["row_numbers"] = [row_number]
                singleton["needs_confirmation"] = False
                singleton["suggestion_reason"] = None
                singleton.setdefault("evidence", []).append(
                    {"kind": "user_split", "source_group_id": group.get("group_id")}
                )
                if index:
                    for field in ("net_weight_kg", "gross_weight_kg", "volume_m3", "package_count"):
                        if isinstance(singleton.get(field), dict):
                            singleton[field]["value"] = None
                            singleton[field]["count_once"] = False
                    for metric in (singleton.get("dimensions") or {}).values():
                        if isinstance(metric, dict):
                            metric["value"] = None
                            metric["count_once"] = False
                resolved_groups.append(singleton)
        else:
            unresolved.append(group.get("group_id"))
            resolved_groups.append(group)
    resolved["groups"] = resolved_groups
    resolved["package_count"] = len(resolved_groups)
    validation = resolved.setdefault("validation", {})
    blocking = [
        item
        for item in (validation.get("blocking") or [])
        if item.get("code") not in {"group_confirmation_required"}
    ]
    if unresolved:
        blocking.append(
            {
                "code": "group_confirmation_required",
                "message": f"仍有 {len(unresolved)} 个共享包装候选未确认。",
            }
        )
    validation["blocking"] = blocking
    validation["needs_group_confirmation"] = bool(unresolved)
    return resolved


def _parse_resolutions(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        result = value
    else:
        try:
            result = json.loads(value or "{}")
        except (TypeError, ValueError) as error:
            raise ValueError("装箱确认内容不是有效 JSON。") from error
    if not isinstance(result, dict):
        raise ValueError("装箱确认内容必须是对象。")
    return result


def _idempotency_key(batch_name: str, source_revision: str, resolutions: dict[str, Any]) -> str:
    return hashlib.sha256(
        f"{batch_name}|{source_revision}|{_json(resolutions)}".encode("utf-8")
    ).hexdigest()


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_kind",
        "source_id",
        "source_label",
        "source_updated_at",
        "sheet_name",
        "workbook_id",
        "sheet_id",
        "instance_id",
        "comment_user",
    }
    return {key: value for key, value in source.items() if key in allowed}


def _public_snapshot(snapshot: Any) -> dict[str, Any]:
    allowed = {
        "name",
        "batch",
        "version",
        "idempotency_key",
        "source_kind",
        "source_id",
        "source_label",
        "source_hash",
        "status",
        "is_current",
        "material_row_count",
        "package_count",
        "total_net_weight_kg",
        "net_total_kind",
        "total_gross_weight_kg",
        "total_volume_m3",
        "confirmed_by",
        "confirmed_at",
    }
    if isinstance(snapshot, dict):
        return {key: snapshot.get(key) for key in allowed if key in snapshot}
    return {key: getattr(snapshot, key) for key in allowed if hasattr(snapshot, key)}


def _record_value(record: Any, fieldname: str) -> Any:
    return record.get(fieldname) if isinstance(record, dict) else getattr(record, fieldname, None)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _positive_decimal(value: Any) -> Decimal | None:
    result = _decimal(value)
    return result if result is not None and result > 0 else None


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _session_user() -> str:
    user = getattr(getattr(frappe, "session", None), "user", "") if frappe is not None else ""
    return str(user or "")


class FrappePackingSnapshotRepository:
    def __init__(self) -> None:
        if frappe is None:
            raise RuntimeError("当前环境未连接 Frappe。")

    def lock_batch(self, batch_name: str) -> None:
        rows = frappe.db.sql(
            "SELECT name FROM `tabOverseas Cost Batch` WHERE name=%s FOR UPDATE",
            (batch_name,),
        )
        if not rows:
            raise ValueError("未找到当前批次。")

    def current_version(self, batch_name: str) -> str:
        return str(frappe.db.get_value("Overseas Cost Batch", batch_name, "current_version") or "")

    def next_version(self, batch_name: str) -> int:
        rows = frappe.db.sql(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM `tabOverseas Packing Snapshot` WHERE batch=%s",
            (batch_name,),
        )
        return int(rows[0][0]) if rows else 1

    def get_by_idempotency_key(self, key: str) -> Any:
        name = frappe.db.get_value("Overseas Packing Snapshot", {"idempotency_key": key}, "name")
        return frappe.get_doc("Overseas Packing Snapshot", name) if name else None

    def get_current(self, batch_name: str) -> Any:
        name = frappe.db.get_value(
            "Overseas Packing Snapshot",
            {"batch": batch_name, "status": "Confirmed", "is_current": 1},
            "name",
        )
        return frappe.get_doc("Overseas Packing Snapshot", name) if name else None

    def supersede(self, snapshot: Any) -> None:
        snapshot.status = "Superseded"
        snapshot.is_current = 0
        snapshot.flags.allow_packing_supersede = True
        snapshot.save(ignore_permissions=True)

    def insert_snapshot(self, values: dict[str, Any]) -> Any:
        return frappe.get_doc({"doctype": "Overseas Packing Snapshot", **values}).insert(ignore_permissions=True)

    def write_audit(self, values: dict[str, Any]) -> None:
        frappe.get_doc({"doctype": "Overseas Cost Audit Log", **values}).insert(ignore_permissions=True)

    def commit(self) -> None:
        frappe.db.commit()

    def rollback(self) -> None:
        frappe.db.rollback()


def get_current_packing_snapshot(batch_name: str) -> dict[str, Any] | None:
    if frappe is None:
        raise RuntimeError("当前环境未连接 Frappe。")
    name = frappe.db.get_value(
        "Overseas Packing Snapshot",
        {"batch": str(batch_name), "status": "Confirmed", "is_current": 1},
        "name",
    )
    if not name:
        return None
    return _public_snapshot(frappe.get_doc("Overseas Packing Snapshot", name))


def list_packing_sources(batch_name: str) -> dict[str, Any]:
    """返回受控来源 ID；不返回服务器路径、对象键、原始审批 JSON 或任何凭据。"""

    if frappe is None:
        raise RuntimeError("当前环境未连接 Frappe。")
    attachment_rows = frappe.get_list(
        "Overseas Cost Attachment",
        filters={"batch": str(batch_name)},
        fields=["name", "source_type", "oa_attachment_origin", "attachment_type", "file_name", "file_url", "modified"],
        limit_page_length=1000,
    )
    manual = []
    approval = []
    for row in attachment_rows:
        sheets = _attachment_sheet_names(row)
        item = {
            "source_id": row.get("name"),
            "source_label": row.get("file_name") or row.get("name"),
            "source_updated_at": row.get("modified"),
            "available": bool(row.get("file_url")),
            "attachment_type": row.get("attachment_type") or "",
            "sheets": sheets,
        }
        if str(row.get("source_type") or "").upper() == "OA":
            approval.append(
                {
                    **item,
                    "source_kind": "approval_attachment",
                    "origin": row.get("oa_attachment_origin") or "Form",
                }
            )
        else:
            manual.append({**item, "source_kind": "manual_attachment"})

    detail = packing_source_service.dingtalk_approval_service.get_batch_dingtalk_approval_detail(str(batch_name))
    comments = []
    for approval_row in [detail.get("main_approval"), *(detail.get("linked_purchase_approvals") or [])]:
        if not isinstance(approval_row, dict) or approval_row.get("excluded"):
            continue
        for timeline in approval_row.get("timeline") or []:
            if not isinstance(timeline, dict) or not timeline.get("packing_candidate") or not timeline.get("source_id"):
                continue
            comments.append(
                {
                    "source_kind": "approval_comment",
                    "source_id": timeline.get("source_id"),
                    "source_label": f"评论 · {timeline.get('user_name') or timeline.get('user_id') or '未知人员'}",
                    "source_updated_at": timeline.get("operation_time"),
                    "instance_id": approval_row.get("instance_id") or "",
                    "available": True,
                    "remark_preview": str(timeline.get("remark") or "")[:160],
                }
            )

    wiki = []
    wiki_error = ""
    try:
        from overseas_costing.integrations.dingtalk_packing_source import get_packing_runtime_clients

        clients = get_packing_runtime_clients()
        for workbook in clients.catalog.list_workbooks():
            sheets = clients.catalog.list_sheets(str(workbook.get("workbook_id") or ""), limit=500)
            wiki.append(
                {
                    "workbook_id": workbook.get("workbook_id"),
                    "year": workbook.get("year"),
                    "label": workbook.get("label"),
                    "updated_at": workbook.get("updated_at"),
                    "sheets": [
                        {
                            "source_kind": "wiki_sheet",
                            "source_id": f"{sheet.get('workbook_id')}:{sheet.get('sheet_id')}",
                            "source_label": sheet.get("sheet_name"),
                            "source_updated_at": sheet.get("source_updated_at"),
                            "indexed_at": sheet.get("indexed_at"),
                            "available": True,
                        }
                        for sheet in sheets
                    ],
                }
            )
    except Exception:
        wiki_error = "知识库装箱表缓存暂不可用，请稍后重试。"
    return {
        "manual_attachments": manual,
        "approval_sources": [*approval, *comments],
        "wiki_workbooks": wiki,
        "wiki_error": wiki_error,
    }


def _attachment_sheet_names(row: dict[str, Any]) -> list[str]:
    """只返回工作表名，不向浏览器暴露站点路径。"""

    file_url = str(row.get("file_url") or "").strip()
    file_name = str(row.get("file_name") or file_url).lower()
    if not file_url or not file_name.endswith((".xlsx", ".xlsm")) or load_workbook is None:
        return []
    try:
        path = packing_source_service.import_service._resolve_excel_file_path(file_url=file_url)
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            return [str(name)[:200] for name in workbook.sheetnames]
        finally:
            workbook.close()
    except (FileNotFoundError, ValueError, OSError):
        return []
