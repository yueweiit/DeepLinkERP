"""综合成本工作台的钉钉审批只读详情服务。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

try:
    import frappe
except Exception:  # pragma: no cover
    frappe = None

from overseas_costing.services.packing_comment_service import (
    build_comment_source_id,
    parse_packing_comment,
)


PACKING_NAME_KEYWORDS = ("装箱单", "装箱计划", "packing list", "packinglist", "发货清单", "装柜清单", "物品清单")


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        result = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return result if isinstance(result, list) else []


def _get_approval_source():
    from overseas_costing.services.import_service import _get_oa_postgres_source

    return _get_oa_postgres_source()


def _linked_instance_ids(extra_json) -> list[str]:
    from overseas_costing.services.import_service import _get_linked_purchase_approvals_from_extra

    return list(dict.fromkeys(
        str(row.get("source_instance_id") or "").strip()
        for row in _get_linked_purchase_approvals_from_extra(extra_json)
        if str(row.get("source_instance_id") or "").strip()
    ))


def _trusted_linked_instance_ids(payload: dict) -> list[str]:
    from overseas_costing.scripts.import_oa_logistics import extract_linked_purchase_approvals

    return list(dict.fromkeys(
        str(row.get("source_instance_id") or "").strip()
        for row in extract_linked_purchase_approvals(payload)
        if str(row.get("source_instance_id") or "").strip()
    ))


def _approval_matches_batch(batch: dict, payload: dict) -> bool:
    if str(batch.get("source_type") or "") != "oa_logistics":
        return False
    payload_instance = str(payload.get("processInstanceId") or payload.get("process_instance_id") or "").strip()
    payload_approval = str(payload.get("businessId") or payload.get("business_id") or "").strip()
    expected_instance = str(batch.get("source_instance_id") or "").strip()
    expected_approval = str(batch.get("source_approval_no") or "").strip()
    batch_no = str(batch.get("batch_no") or "").strip()
    return (
        bool(payload_instance and expected_instance and payload_instance == expected_instance)
        and bool(payload_approval and payload_approval in {expected_approval, batch_no})
    )


FORM_VALUE_PRIVATE_KEYS = {
    "authcode",
    "authmediaid",
    "mediaid",
    "fileid",
    "spaceid",
    "downloadurl",
    "previewurl",
    "url",
    "key",
    "rownumber",
}


def _safe_form_value(value):
    if isinstance(value, list):
        return [_safe_form_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("fileName") and (value.get("fileId") or value.get("spaceId")):
        return str(value.get("fileName") or "审批附件")
    return {
        str(key): _safe_form_value(item)
        for key, item in value.items()
        if str(key).replace("_", "").lower() not in FORM_VALUE_PRIVATE_KEYS
    }


def _display_value(value) -> str:
    if value is None:
        return ""
    decoded = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return value
    sanitized = _safe_form_value(decoded)
    if isinstance(sanitized, list):
        if all(isinstance(item, str) for item in sanitized):
            return "；".join(sanitized)
        table_rows = []
        for item in sanitized:
            cells = item.get("rowValue") if isinstance(item, dict) else None
            if not isinstance(cells, list):
                table_rows = []
                break
            pairs = []
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                label = str(cell.get("label") or "字段")
                cell_value = _display_value(cell.get("value"))
                pairs.append(f"{label}：{cell_value or '--'}")
            if pairs:
                table_rows.append("；".join(pairs))
        if table_rows:
            return "\n".join(table_rows)
    if isinstance(sanitized, (dict, list)):
        return json.dumps(sanitized, ensure_ascii=False)
    return str(sanitized)


def _form_fields(payload: dict) -> list[dict]:
    fields = _json_list(payload.get("formComponentValues") or payload.get("form_component_values"))
    return [
        {
            "label": str(row.get("name") or row.get("label") or row.get("componentName") or "未命名字段"),
            "value": _display_value(row.get("value")),
        }
        for row in fields
        if isinstance(row, dict)
    ]


def _actor_identity(
    *,
    corp_id: str,
    user_id: str,
    provided_name: str = "",
    actors: dict | None = None,
) -> dict:
    user_id = str(user_id or "").strip()
    provided_name = str(provided_name or "").strip()
    if provided_name and provided_name != user_id:
        return {
            "user_name": provided_name,
            "user_name_source": "payload",
            "user_name_unresolved": False,
        }
    if not user_id or user_id.lower() in {"bpms_system", "system", "dingtalk_system"}:
        return {
            "user_name": "系统",
            "user_name_source": "system",
            "user_name_unresolved": False,
        }
    actor = ((actors or {}).get(str(corp_id or ""), {}) or {}).get(user_id) or {}
    if isinstance(actor, str):
        actor = {"name": actor}
    actor_name = str(actor.get("name") or "").strip() if isinstance(actor, dict) else ""
    if actor_name and actor_name.lower() != "unknown" and actor_name != user_id:
        return {
            "user_name": actor_name,
            "user_name_source": "directory",
            "user_name_unresolved": False,
        }
    return {
        "user_name": "",
        "user_name_source": "unresolved",
        "user_name_unresolved": True,
    }


def _timeline(payload: dict, instance_id: str, actors: dict | None = None) -> list[dict]:
    operations = _json_list(payload.get("operationRecords") or payload.get("operation_records") or payload.get("comments"))
    corp_id = str(payload.get("corpId") or payload.get("corp_id") or "")
    result = []
    for row in operations:
        if not isinstance(row, dict):
            continue
        user_id = str(row.get("userId") or row.get("user_id") or row.get("operatorUserId") or "")
        operation_time = str(row.get("date") or row.get("createTime") or row.get("operationTime") or "")
        remark = str(row.get("remark") or row.get("comment") or row.get("content") or "").strip()
        packing = parse_packing_comment(remark)
        identity = _actor_identity(
            corp_id=corp_id,
            user_id=user_id,
            provided_name=str(row.get("userName") or row.get("user_name") or row.get("operatorName") or ""),
            actors=actors,
        )
        item = {
            "operation_type": str(row.get("type") or row.get("operationType") or "comment"),
            "result": str(row.get("result") or ""),
            "user_id": user_id,
            **identity,
            "operation_time": operation_time,
            "remark": remark,
            "packing_candidate": bool(packing.get("is_candidate")),
        }
        if remark:
            item["source_id"] = build_comment_source_id(instance_id, operation_time, user_id, remark)
            if packing.get("is_candidate"):
                item["packing_preview"] = {key: value for key, value in packing.items() if key != "source_text"}
        result.append(item)
    return result


def _local_attachment_map(batch_name: str) -> dict[tuple[str, str], dict]:
    if frappe is None or not hasattr(frappe, "get_list"):
        return {}
    rows = frappe.get_list(
        "Overseas Cost Attachment",
        filters={"batch": batch_name, "source_type": "OA"},
        fields=["name", "file_name", "file_url", "modified", "parse_result_json"],
        limit_page_length=1000,
    )
    result = {}
    for row in rows:
        snapshot = _json_dict(row.get("parse_result_json"))
        file_id = str(snapshot.get("file_id") or "").strip()
        instance_id = str(snapshot.get("process_instance_id") or "").strip()
        if file_id:
            result[(instance_id, file_id)] = row
    return result


def _attachment_item(row: dict, local: dict | None, actors: dict | None = None) -> dict:
    file_name = str(row.get("file_name") or row.get("file_id") or "")
    archive_status = str(row.get("archive_status") or "pending")
    file_url = str((local or {}).get("file_url") or "")
    normalized_name = file_name.lower()
    suffix = Path(file_name).suffix.lower()
    packing_candidate = any(keyword in normalized_name for keyword in PACKING_NAME_KEYWORDS)
    if suffix in {".xlsx", ".xlsm"}:
        packing_candidate = packing_candidate or "packing" in normalized_name or "清单" in normalized_name
    failure_code = str(row.get("failure_code") or "")
    failure_reason = str(row.get("last_error") or "")
    if failure_code == "userNotExist" or "userNotExist" in failure_reason:
        failure_reason = "钉钉下载授权返回 userNotExist，尚不能判断文件是否删除。"
    comment_user_id = str(row.get("comment_user_id") or "")
    comment_user_name = str(row.get("comment_user_name") or "")
    if comment_user_id or comment_user_name:
        comment_identity = _actor_identity(
            corp_id=str(row.get("corp_id") or ""),
            user_id=comment_user_id,
            provided_name=comment_user_name,
            actors=actors,
        )
    else:
        comment_identity = {
            "user_name": "",
            "user_name_source": "",
            "user_name_unresolved": False,
        }
    return {
        "attachment_name": (local or {}).get("name") or "",
        "file_id": str(row.get("file_id") or ""),
        "process_instance_id": str(row.get("process_instance_id") or ""),
        "space_id": str(row.get("space_id") or ""),
        "file_name": file_name,
        "declared_size": row.get("declared_size"),
        "actual_size": row.get("actual_size"),
        "origin": "Comment" if str(row.get("attachment_origin")) == "comment" else "Form",
        "comment_user_id": comment_user_id,
        "comment_user_name": comment_identity["user_name"],
        "comment_user_name_source": comment_identity["user_name_source"],
        "comment_user_name_unresolved": comment_identity["user_name_unresolved"],
        "comment_time": str(row.get("comment_time") or ""),
        "comment_remark": str(row.get("comment_remark") or ""),
        "archive_status": archive_status,
        "archive_method": str(row.get("archive_method") or ""),
        "content_quality": str(row.get("content_quality") or ""),
        "failure_code": failure_code,
        "failure_reason": failure_reason,
        "file_url": file_url,
        "previewable": bool(file_url) or archive_status == "archived",
        "downloadable": bool(file_url) or archive_status == "archived",
        "packing_candidate": packing_candidate,
    }


def _approval(payload: dict, attachments: list[dict], actors: dict | None = None) -> dict:
    from overseas_costing.scripts.import_oa_logistics import resolve_approval_decision

    instance_id = str(payload.get("processInstanceId") or payload.get("process_instance_id") or "")
    corp_id = str(payload.get("corpId") or payload.get("corp_id") or "")
    raw_status = str(payload.get("status") or "")
    raw_result = str(payload.get("result") or "")
    decision = resolve_approval_decision(raw_status, raw_result)
    status_upper = raw_status.strip().upper()
    rejection_tokens = ("REJECT", "REFUS", "DENY", "DISAGREE", "拒绝", "驳回", "不通过", "未通过")
    if decision.get("excluded"):
        if raw_result.strip() and decision.get("effective_status") == "REJECTED":
            exclusion_reason = "审批结果为拒绝"
        elif any(token in status_upper for token in rejection_tokens):
            exclusion_reason = "审批状态为拒绝"
        else:
            exclusion_reason = "审批已撤销、终止或作废"
    else:
        exclusion_reason = ""
    originator_user_id = str(payload.get("originatorUserId") or payload.get("originator_user_id") or "")
    originator_identity = _actor_identity(
        corp_id=corp_id,
        user_id=originator_user_id,
        provided_name=str(payload.get("originatorUserName") or payload.get("originator_user_name") or ""),
        actors=actors,
    )
    return {
        "corp_id": corp_id,
        "instance_id": instance_id,
        "business_id": str(payload.get("businessId") or payload.get("business_id") or ""),
        "process_code": str(payload.get("processCode") or payload.get("process_code") or ""),
        "title": str(payload.get("title") or ""),
        "status": raw_status,
        "result": raw_result,
        "raw_status": raw_status,
        "raw_result": raw_result,
        "process_status": decision.get("process_status") or "",
        "approval_result": decision.get("approval_result") or "",
        "effective_status": decision.get("effective_status") or "",
        "excluded": bool(decision.get("excluded")),
        "exclusion_reason": exclusion_reason,
        "originator_user_id": originator_user_id,
        "originator_user_name": originator_identity["user_name"],
        "originator_name_source": originator_identity["user_name_source"],
        "originator_name_unresolved": originator_identity["user_name_unresolved"],
        "originator_dept_name": str(payload.get("originatorDeptName") or payload.get("originator_dept_name") or ""),
        "create_time": str(payload.get("createTime") or payload.get("create_time") or ""),
        "finish_time": str(payload.get("finishTime") or payload.get("finish_time") or ""),
        "form_fields": _form_fields(payload),
        "timeline": _timeline(payload, instance_id, actors),
        "attachments": attachments,
    }


def get_batch_dingtalk_approval_detail(batch_name: str) -> dict:
    if frappe is None:
        return {"ok": False, "message": "当前未连接 Frappe。"}
    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_name,
        ["name", "batch_no", "source_type", "source_approval_no", "source_instance_id", "extra_json"],
        as_dict=True,
    ) or {}
    main_id = str(batch.get("source_instance_id") or "").strip()
    if not main_id:
        return {"ok": False, "message": "当前批次没有钉钉审批实例 ID。"}
    candidate_linked_ids = [value for value in _linked_instance_ids(batch.get("extra_json")) if value != main_id]
    instance_ids = [main_id, *candidate_linked_ids]
    bundle = _get_approval_source().get_instance_bundle(instance_ids)
    instances = bundle.get("instances") or {}
    actors = bundle.get("actors") or {}
    manifests_by_instance: dict[str, list[dict]] = defaultdict(list)
    local_by_file = _local_attachment_map(batch.get("name") or batch_name)
    for row in bundle.get("attachments") or []:
        if not isinstance(row, dict):
            continue
        instance_id = str(row.get("process_instance_id") or "")
        file_id = str(row.get("file_id") or "")
        manifests_by_instance[instance_id].append(
            _attachment_item(row, local_by_file.get((instance_id, file_id)), actors)
        )
    main_payload = instances.get(main_id)
    if not isinstance(main_payload, dict):
        return {"ok": False, "message": "成本系统数据库中未找到该物流审批。"}
    if not _approval_matches_batch(batch, main_payload):
        return {"ok": False, "message": "批次来源与钉钉物流审批不一致，已拒绝显示审批内容。"}
    trusted_linked = set(_trusted_linked_instance_ids(main_payload))
    linked_ids = [instance_id for instance_id in candidate_linked_ids if instance_id in trusted_linked]
    health = bundle.get("health") or {}
    archive_rows = [row for rows in manifests_by_instance.values() for row in rows]
    archive_health = {
        "total": len(archive_rows),
        "archived": sum(1 for row in archive_rows if row.get("archive_status") == "archived"),
        "pending": sum(1 for row in archive_rows if row.get("archive_status") in {"pending", "archiving", "retry"}),
        "manual_required": sum(1 for row in archive_rows if row.get("archive_status") == "manual_required"),
        "preview_only": sum(1 for row in archive_rows if row.get("content_quality") == "preview"),
    }
    main_approval = _approval(main_payload, manifests_by_instance.get(main_id, []), actors)
    linked_approvals = [
        _approval(instances[instance_id], manifests_by_instance.get(instance_id, []), actors)
        for instance_id in linked_ids
        if isinstance(instances.get(instance_id), dict)
    ]
    return {
        "ok": True,
        "batch_name": batch.get("name") or batch_name,
        "data_source": "postgres",
        "fallback_used": False,
        "source_updated_at": health.get("source_updated_at"),
        "source_lag_seconds": health.get("source_lag_seconds"),
        "archive_health": archive_health,
        "main_approval": main_approval,
        "linked_purchase_approvals": [row for row in linked_approvals if not row.get("excluded")],
        "excluded_linked_purchase_approvals": [row for row in linked_approvals if row.get("excluded")],
        "missing_linked_instance_ids": [instance_id for instance_id in linked_ids if instance_id not in instances],
    }


def materialize_batch_dingtalk_attachment(batch_name: str, process_instance_id: str, file_id: str) -> dict:
    """Create the local attachment record only after an authorized user requests the archived file."""

    detail = get_batch_dingtalk_approval_detail(batch_name)
    if not detail.get("ok"):
        return detail
    approvals = [
        detail.get("main_approval"),
        *(detail.get("linked_purchase_approvals") or []),
        *(detail.get("excluded_linked_purchase_approvals") or []),
    ]
    source_approval = next(
        (
            approval for approval in approvals
            if isinstance(approval, dict) and str(approval.get("instance_id") or "") == str(process_instance_id or "")
        ),
        None,
    )
    if not source_approval:
        return {"ok": False, "message": "该审批不属于当前批次。"}
    source = next(
        (
            item for item in source_approval.get("attachments") or []
            if str(item.get("file_id") or "") == str(file_id or "")
        ),
        None,
    )
    if not source:
        return {"ok": False, "message": "该附件不属于当前批次审批。"}
    if source.get("attachment_name"):
        return {"ok": True, "attachment_name": source["attachment_name"], "created": False}
    if str(source.get("archive_status") or "") != "archived":
        return {"ok": False, "message": source.get("failure_reason") or "附件尚未归档，暂不能下载。"}

    sql = getattr(getattr(frappe, "db", None), "sql", None)
    if callable(sql):
        sql(
            "SELECT name FROM `tabOverseas Cost Batch` WHERE name=%s FOR UPDATE",
            (batch_name,),
        )
    existing_rows = frappe.get_all(
        "Overseas Cost Attachment",
        filters={"batch": batch_name, "source_type": "OA"},
        fields=["name", "parse_result_json"],
        limit_page_length=1000,
    )
    for row in existing_rows:
        snapshot = _json_dict(row.get("parse_result_json"))
        if (
            str(snapshot.get("process_instance_id") or "") == str(process_instance_id or "")
            and str(snapshot.get("file_id") or "") == str(file_id or "")
        ):
            return {"ok": True, "attachment_name": row.get("name"), "created": False}

    batch = frappe.db.get_value("Overseas Cost Batch", batch_name, ["name", "current_version"], as_dict=True) or {}
    parse_snapshot = {
        "source": "dingtalk_postgres_archive",
        "approval_excluded": bool(source_approval.get("excluded")),
        "cost_source_allowed": not bool(source_approval.get("excluded")),
        "exclusion_reason": source_approval.get("exclusion_reason") or "",
        "process_instance_id": process_instance_id,
        "file_id": file_id,
        "space_id": source.get("space_id") or "",
        "attachment_origin": source.get("origin") or "Form",
        "comment_user_name": source.get("comment_user_name") or "",
        "comment_time": source.get("comment_time") or "",
        "comment_remark": source.get("comment_remark") or "",
        "archive": {
            "status": source.get("archive_status") or "archived",
            "archive_method": source.get("archive_method") or "",
            "content_quality": source.get("content_quality") or "",
        },
    }
    doc = frappe.get_doc({
        "doctype": "Overseas Cost Attachment",
        "batch": batch.get("name") or batch_name,
        "version": batch.get("current_version") or None,
        "source_type": "OA",
        "oa_attachment_origin": source.get("origin") or "Form",
        "attachment_type": (
            "Packing List"
            if source.get("packing_candidate") and not source_approval.get("excluded")
            else "Other"
        ),
        "source_doc_no": source_approval.get("business_id") or process_instance_id,
        "file_name": source.get("file_name") or file_id,
        "parse_status": "Queued",
        "parse_result_json": json.dumps(parse_snapshot, ensure_ascii=False),
        "remark": (
            "由已排除钉钉审批归档按需创建，仅供审计查看和下载，不可作为成本或装箱数据源。"
            if source_approval.get("excluded")
            else "由钉钉审批归档清单按需创建，文件内容将从 MinIO 下载。"
        ),
    }).insert(ignore_permissions=True)
    return {"ok": True, "attachment_name": doc.name, "created": True}
