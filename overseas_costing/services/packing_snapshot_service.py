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
from overseas_costing.services.packing_sheet_recommendation import (
    recommend_packing_sheets,
    summarize_packing_preview,
)


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
        idempotency_key = _idempotency_key(batch_name, source_revision)
        existing = repo.get_by_idempotency_key(idempotency_key)
        if existing:
            stored_resolutions = _parse_resolutions(_record_value(existing, "resolutions_json"))
            repo.rollback()
            if _json(stored_resolutions) != _json(resolutions):
                return {
                    "ok": False,
                    "source_changed": False,
                    "resolution_conflict": True,
                    "message": "该来源版本已经确认，不能用另一组决定覆盖。请刷新来源后重新预览。",
                }
            return {"ok": True, "idempotent": True, "snapshot": _public_snapshot(existing)}
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
        elif action in {"split", "partition"}:
            rows = list(group.get("row_numbers") or [])
            partitions = [[row] for row in rows] if action == "split" else (decision or {}).get("partitions")
            normalized = _validate_partitions(rows, partitions)
            if normalized:
                resolved_groups.extend(_partition_group(group, normalized, action))
            else:
                unresolved.append(group.get("group_id"))
                resolved_groups.append(group)
        else:
            unresolved.append(group.get("group_id"))
            resolved_groups.append(group)
    resolved["groups"] = resolved_groups
    resolved["package_group_count"] = len(resolved_groups)
    _recompute_resolved_totals(resolved)
    resolved_total_fields = _apply_total_resolutions(resolved, resolutions)
    validation = resolved.setdefault("validation", {})
    blocking = [
        item
        for item in (validation.get("blocking") or [])
        if item.get("code") != "group_confirmation_required"
        and not (item.get("code") == "conflicting_merge_ranges" and not unresolved)
        and not (item.get("code") == "total_mismatch" and item.get("field") in resolved_total_fields)
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


def _validate_partitions(rows: list[int], partitions: Any) -> list[list[int]] | None:
    if not isinstance(partitions, list) or not partitions:
        return None
    normalized = []
    for partition in partitions:
        if not isinstance(partition, list) or not partition:
            return None
        try:
            values = [int(row) for row in partition]
        except (TypeError, ValueError):
            return None
        if len(values) != len(set(values)):
            return None
        normalized.append(values)
    flattened = [row for partition in normalized for row in partition]
    return normalized if len(flattened) == len(set(flattened)) and sorted(flattened) == sorted(rows) else None


def _partition_group(group: dict[str, Any], partitions: list[list[int]], action: str) -> list[dict[str, Any]]:
    result = []
    for index, partition in enumerate(partitions, start=1):
        subgroup = copy.deepcopy(group)
        subgroup["group_id"] = f"{group.get('group_id')}-part-{index}"
        subgroup["row_numbers"] = partition
        subgroup["needs_confirmation"] = False
        subgroup["suggestion_reason"] = None
        subgroup["merge_conflict"] = False
        subgroup.setdefault("evidence", []).append(
            {"kind": f"user_{action}", "source_group_id": group.get("group_id"), "rows": partition}
        )
        metrics = [
            subgroup.get("net_weight_kg"),
            subgroup.get("gross_weight_kg"),
            subgroup.get("volume_m3"),
            subgroup.get("package_count"),
            *((subgroup.get("dimensions") or {}).values()),
        ]
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            source_row = metric.get("source_row")
            owns_value = source_row in partition if source_row is not None else index == 1
            if owns_value and metric.get("value") is not None:
                metric["count_once"] = True
            else:
                metric["value"] = None
                metric["count_once"] = False
                metric["source_row"] = None
        result.append(subgroup)
    return result


def _apply_total_resolutions(preview: dict[str, Any], resolutions: dict[str, Any]) -> set[str]:
    decisions = resolutions.get("totals") if isinstance(resolutions.get("totals"), dict) else {}
    resolved_fields: set[str] = set()
    for field, total in (preview.get("totals") or {}).items():
        declared = _decimal((total or {}).get("declared_value"))
        calculated = _decimal((total or {}).get("calculated_value"))
        if declared is None or calculated is None:
            continue
        tolerance = max(Decimal("0.01"), abs(declared) * Decimal("0.001"))
        if abs(declared - calculated) <= tolerance:
            resolved_fields.add(field)
    for field, decision in decisions.items():
        total = (preview.get("totals") or {}).get(field)
        if not isinstance(total, dict):
            continue
        action = str((decision or {}).get("action") or "") if isinstance(decision, dict) else str(decision or "")
        if action == "use_declared" and total.get("declared_value") is not None:
            total["value"] = total["declared_value"]
            total["kind"] = "user_selected_source_total"
            resolved_fields.add(field)
        elif action == "use_calculated" and total.get("calculated_value") is not None:
            total["value"] = total["calculated_value"]
            total["kind"] = "user_selected_calculated"
            resolved_fields.add(field)
    return resolved_fields


def _recompute_resolved_totals(preview: dict[str, Any]) -> None:
    """用用户已确认的 count_once 包装组重新汇总，但保留表内整票声明值。"""

    groups = preview.get("groups") or []
    totals = preview.setdefault("totals", {})
    for field in ("net_weight_kg", "gross_weight_kg", "volume_m3"):
        values = [
            _decimal((group.get(field) or {}).get("value"))
            for group in groups
            if (group.get(field) or {}).get("count_once")
        ]
        calculated = sum((value for value in values if value is not None), Decimal("0")) if any(value is not None for value in values) else None
        total = totals.setdefault(field, {})
        total["calculated_value"] = _decimal_text(calculated)
        if field == "net_weight_kg" or total.get("kind") != "source_total":
            total["value"] = _decimal_text(calculated)
            total["kind"] = "calculated_detail_sum"

    package_values = [
        _decimal((group.get("package_count") or {}).get("value"))
        for group in groups
        if (group.get("package_count") or {}).get("count_once")
    ]
    package_calculated = sum(
        (value for value in package_values if value is not None), Decimal("0")
    ) if any(value is not None for value in package_values) else None
    package_total = totals.setdefault("package_count", {})
    package_total["calculated_value"] = _decimal_text(package_calculated)
    if package_total.get("kind") != "source_total" and package_calculated is not None:
        package_total["value"] = _decimal_text(package_calculated)
        package_total["kind"] = "calculated_group_sum"
    resolved_package_count = _decimal(package_total.get("value"))
    if resolved_package_count is not None and resolved_package_count == resolved_package_count.to_integral_value():
        preview["package_count"] = int(resolved_package_count)


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


def _idempotency_key(batch_name: str, source_revision: str) -> str:
    return hashlib.sha256(f"{batch_name}|{source_revision}".encode("utf-8")).hexdigest()


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
        fields=["name", "batch", "source_type", "oa_attachment_origin", "attachment_type", "file_name", "file_url", "modified", "parse_result_json"],
        limit_page_length=1000,
    )
    manual = []
    approval = []
    approval_by_identity = {}
    approval_by_name = {}
    for row in attachment_rows:
        if not _is_excel_packing_attachment(row.get("file_name")):
            continue
        if str(row.get("source_type") or "").upper() == "OA" and packing_source_service._attachment_is_audit_only(row):
            continue
        snapshot = packing_source_service.import_service._json_loads_dict(row.get("parse_result_json"))
        archive = snapshot.get("archive") if isinstance(snapshot.get("archive"), dict) else {}
        sheets = _attachment_sheet_names(row)
        item = {
            "source_id": row.get("name"),
            "attachment_name": row.get("name"),
            "source_label": row.get("file_name") or row.get("name"),
            "source_updated_at": row.get("modified"),
            "available": bool(row.get("file_url")),
            "download_required": not bool(row.get("file_url")),
            "supported_for_material_import": str(row.get("file_name") or "").lower().endswith(".xlsx"),
            "attachment_type": row.get("attachment_type") or "",
            "sheets": sheets,
        }
        if str(row.get("source_type") or "").upper() == "OA":
            item.update({
                "source_kind": "approval_attachment",
                "origin": row.get("oa_attachment_origin") or snapshot.get("attachment_origin") or "Form",
                "process_instance_id": str(snapshot.get("process_instance_id") or snapshot.get("instance_id") or ""),
                "file_id": str(snapshot.get("file_id") or ""),
                "archive_status": archive.get("status") or ("archived" if item["available"] else "pending"),
                "can_download": not item["available"] and (archive.get("status") == "archived" or bool(snapshot.get("file_id"))),
            })
            approval.append(item)
            approval_by_name[str(row.get("name") or "")] = item
            if item["process_instance_id"] and item["file_id"]:
                approval_by_identity[(item["process_instance_id"], item["file_id"])] = item
        else:
            manual.append({**item, "source_kind": "manual_attachment"})

    detail = packing_source_service.dingtalk_approval_service.get_batch_dingtalk_approval_detail(str(batch_name))
    comments = []
    for approval_row in [detail.get("main_approval"), *(detail.get("linked_purchase_approvals") or [])]:
        if not isinstance(approval_row, dict) or approval_row.get("excluded"):
            continue
        for attachment in approval_row.get("attachments") or []:
            if not isinstance(attachment, dict) or not _is_excel_packing_attachment(attachment.get("file_name")):
                continue
            instance_id = str(approval_row.get("instance_id") or "")
            file_id = str(attachment.get("file_id") or "")
            if not instance_id or not file_id:
                continue
            identity = (instance_id, file_id)
            existing = approval_by_identity.get(identity) or approval_by_name.get(str(attachment.get("attachment_name") or ""))
            available = bool((existing or {}).get("available"))
            archive_status = str(attachment.get("archive_status") or "pending")
            metadata = {
                "process_instance_id": instance_id,
                "file_id": file_id,
                "origin": attachment.get("origin") or "Form",
                "archive_status": archive_status,
                "can_download": not available and archive_status == "archived",
                "download_required": not available,
            }
            if existing:
                existing.update(metadata)
                approval_by_identity[identity] = existing
                continue
            source_id = "oa:" + hashlib.sha256(_json(list(identity)).encode("utf-8")).hexdigest()
            item = {
                **metadata,
                "source_kind": "approval_attachment",
                "source_id": source_id,
                "attachment_name": "",
                "source_label": attachment.get("file_name") or file_id,
                "source_updated_at": attachment.get("source_updated_at") or attachment.get("comment_time") or detail.get("source_updated_at"),
                "available": False,
                "supported_for_material_import": str(attachment.get("file_name") or "").lower().endswith(".xlsx"),
                "attachment_type": "",
                "sheets": [],
            }
            approval.append(item)
            approval_by_identity[identity] = item
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
        batch_context = _packing_batch_context(str(batch_name), detail)
        workbook_rows: list[dict[str, Any]] = []
        all_sheet_rows: list[dict[str, Any]] = []
        all_snapshot_states: dict[str, dict[str, Any]] = {}
        for workbook in clients.catalog.list_workbooks():
            workbook_id = str(workbook.get("workbook_id") or "")
            sheets = clients.catalog.list_sheets(workbook_id, limit=500)
            snapshot_states = _packing_snapshot_summaries(clients, workbook_id)
            all_snapshot_states.update(snapshot_states)
            rendered_sheets = []
            for sheet in sheets:
                source_id = f"{sheet.get('workbook_id')}:{sheet.get('sheet_id')}"
                snapshot_state = snapshot_states.get(source_id) or {}
                rendered_sheets.append(
                    {
                        "source_kind": "wiki_sheet",
                        "source_id": source_id,
                        "source_label": sheet.get("sheet_name"),
                        "source_updated_at": sheet.get("source_updated_at"),
                        "indexed_at": sheet.get("indexed_at"),
                        "workbook_id": sheet.get("workbook_id"),
                        "workbook_year": sheet.get("year") or workbook.get("year"),
                        "snapshot_updated_at": snapshot_state.get("snapshot_updated_at"),
                        "snapshot_status": snapshot_state.get("snapshot_status") or "not_cached",
                        "available": True,
                    }
                )
            workbook_rows.append(
                {
                    "workbook_id": workbook.get("workbook_id"),
                    "year": workbook.get("year"),
                    "label": workbook.get("label"),
                    "updated_at": workbook.get("updated_at"),
                    "sheets": rendered_sheets,
                }
            )
            all_sheet_rows.extend(rendered_sheets)

        snapshot_summaries = {
            source_id: state.get("summary") or {}
            for source_id, state in all_snapshot_states.items()
            if state.get("summary")
        }
        recommended = recommend_packing_sheets(
            all_sheet_rows,
            batch_context=batch_context,
            snapshot_summaries=snapshot_summaries,
        )
        recommended_by_id = {str(row.get("source_id") or ""): row for row in recommended}
        for workbook in workbook_rows:
            workbook["sheets"] = [
                recommended_by_id[str(row.get("source_id") or "")]
                for row in workbook.get("sheets") or []
                if str(row.get("source_id") or "") in recommended_by_id
            ]
            workbook["sheets"].sort(
                key=lambda row: next(
                    index
                    for index, candidate in enumerate(recommended)
                    if candidate.get("source_id") == row.get("source_id")
                )
            )
        wiki = _pin_recommended_workbook(workbook_rows)
    except Exception:
        wiki_error = "装箱计划表缓存暂不可用，请稍后重试。"
    return {
        "manual_attachments": manual,
        "approval_sources": [*approval, *comments],
        "wiki_workbooks": wiki,
        "wiki_error": wiki_error,
    }


def _is_excel_packing_attachment(file_name: Any) -> bool:
    return str(file_name or "").strip().lower().endswith((".xlsx", ".xlsm"))


def _packing_batch_context(batch_name: str, detail: dict[str, Any]) -> dict[str, Any]:
    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_name,
        [
            "name",
            "batch_no",
            "waybill_no",
            "source_approval_no",
            "source_instance_id",
            "project_collection",
            "creation",
        ],
        as_dict=True,
    ) or {}
    items = frappe.get_list(
        "Overseas Cost Item",
        filters={"batch": str(batch.get("name") or batch_name)},
        fields=["material_code", "product_name", "source_doc_no"],
        limit_page_length=5000,
    )
    item_codes = {str(row.get("material_code") or "").strip() for row in items}
    references = {
        str(batch.get(field) or "").strip()
        for field in ("batch_no", "waybill_no", "source_approval_no", "source_instance_id")
    }
    keywords = {str(batch.get("project_collection") or "").strip()}
    for row in items:
        references.add(str(row.get("source_doc_no") or "").strip())
        keywords.add(str(row.get("product_name") or "").strip())
    approvals = [detail.get("main_approval"), *(detail.get("linked_purchase_approvals") or [])]
    for approval in approvals:
        if not isinstance(approval, dict) or approval.get("excluded"):
            continue
        references.update(
            str(approval.get(field) or "").strip()
            for field in ("business_id", "instance_id")
        )
        keywords.add(str(approval.get("title") or "").strip())
        for field in approval.get("form_fields") or []:
            if not isinstance(field, dict):
                continue
            value = str(field.get("value") or "").strip()
            label = str(field.get("label") or "").lower()
            if any(token in label for token in ("审批", "订单", "单号", "order", "物流")):
                references.add(value)
            elif 2 <= len(value) <= 80:
                keywords.add(value)
    creation = str(batch.get("creation") or "")
    return {
        "item_codes": sorted(value for value in item_codes if value),
        "references": sorted(value for value in references if value),
        "keywords": sorted(value for value in keywords if value),
        "reference_date": creation[:10] if len(creation) >= 10 else None,
    }


def _packing_snapshot_summaries(clients: Any, workbook_id: str) -> dict[str, dict[str, Any]]:
    """读取现有 MinIO 快照；任何单个对象失败都只影响对应 Sheet。"""

    from overseas_costing.services.packing_grid import build_grid_from_dingtalk_snapshot
    from overseas_costing.services.packing_parse_service import parse_packing_grid

    result: dict[str, dict[str, Any]] = {}
    for manifest in clients.catalog.list_latest_snapshots(workbook_id):
        sheet_id = str(manifest.get("sheet_id") or "")
        source_id = f"{workbook_id}:{sheet_id}"
        state = {
            "snapshot_status": "ready",
            "snapshot_updated_at": manifest.get("created_at"),
        }
        try:
            payload = clients.archive.download(manifest)
            preview = parse_packing_grid(build_grid_from_dingtalk_snapshot(payload))
            state["summary"] = summarize_packing_preview(preview)
        except Exception:
            state["snapshot_status"] = "unreadable"
        result[source_id] = state
    return result


def _pin_recommended_workbook(workbooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """多年度表时把包含全局推荐项的工作簿整体置顶。"""

    return sorted(
        workbooks,
        key=lambda workbook: (
            0 if any(sheet.get("is_recommended") for sheet in workbook.get("sheets") or []) else 1,
        ),
    )


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
