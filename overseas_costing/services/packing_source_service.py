"""统一处理钉钉附件和纯评论装箱来源。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

try:
    import frappe
except Exception:  # pragma: no cover
    frappe = None

from overseas_costing.services import dingtalk_approval_service, import_service
from overseas_costing.services.packing_comment_service import parse_packing_comment


def _revision_signing_key() -> bytes:
    if frappe is None:  # only used by pure unit tests
        return b"overseas-costing-test-key"
    candidates = [
        getattr(getattr(frappe, "local", None), "conf", None),
        getattr(frappe, "conf", None),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        value = candidate.get("encryption_key") if hasattr(candidate, "get") else getattr(candidate, "encryption_key", None)
        if value:
            return str(value).encode("utf-8")
    raise RuntimeError("站点缺少 encryption_key，无法签发装箱来源确认令牌。")


def _encode_revision(
    source_kind: str,
    source_id: str,
    source_hash: str,
    *,
    batch_name: str = "",
    version_name: str = "",
    batch_modified: str = "",
    version_modified: str = "",
) -> str:
    payload = json.dumps(
        {
            "kind": source_kind,
            "id": source_id,
            "hash": source_hash,
            "batch": batch_name,
            "version": version_name,
            "batch_modified": batch_modified,
            "version_modified": version_modified,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_revision_signing_key(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode_revision(value: str) -> dict:
    text = str(value or "").strip()
    try:
        encoded, signature = text.rsplit(".", 1)
        expected = hmac.new(_revision_signing_key(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return {}
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError, RuntimeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_source_revision_claims(value: str) -> dict:
    """Return authenticated claims for the API permission layer."""

    return _decode_revision(value)


def _attachment_hash(row: dict) -> str:
    digest = hashlib.sha256()
    digest.update("|".join(str(row.get(key) or "") for key in ("name", "modified", "file_url", "file_name")).encode("utf-8"))
    file_url = str(row.get("file_url") or "").strip()
    if file_url:
        try:
            path = import_service._resolve_excel_file_path(file_url=file_url)
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except (FileNotFoundError, ValueError, OSError):
            digest.update(b"|unresolved-local-file")
    return digest.hexdigest()


def _source_context(batch_name: str, version_name: str | None = None) -> dict:
    if frappe is None or not hasattr(frappe, "db"):
        return {
            "version_name": str(version_name or ""),
            "batch_modified": "",
            "version_modified": "",
        }
    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_name,
        ["current_version", "modified"],
        as_dict=True,
    ) or {}
    resolved_version = str(version_name or batch.get("current_version") or "")
    version_modified = frappe.db.get_value("Overseas Cost Version", resolved_version, "modified") if resolved_version else ""
    return {
        "version_name": resolved_version,
        "batch_modified": str(batch.get("modified") or ""),
        "version_modified": str(version_modified or ""),
    }


def _commit() -> None:
    commit = getattr(getattr(frappe, "db", None), "commit", None) if frappe is not None else None
    if callable(commit):
        commit()


def _rollback() -> None:
    rollback = getattr(getattr(frappe, "db", None), "rollback", None) if frappe is not None else None
    if callable(rollback):
        rollback()


def _attachment_source(batch_name: str, source_id: str) -> dict:
    if frappe is None:
        return {}
    return frappe.db.get_value(
        "Overseas Cost Attachment",
        {"name": source_id, "batch": batch_name, "source_type": "OA"},
        ["name", "batch", "file_name", "file_url", "modified"],
        as_dict=True,
    ) or {}


def _find_comment_source(batch_name: str, source_id: str) -> dict:
    detail = dingtalk_approval_service.get_batch_dingtalk_approval_detail(batch_name)
    approvals = [detail.get("main_approval"), *(detail.get("linked_purchase_approvals") or [])]
    for approval in approvals:
        if not isinstance(approval, dict):
            continue
        for item in approval.get("timeline") or []:
            if not isinstance(item, dict) or str(item.get("source_id") or "") != str(source_id):
                continue
            return {
                **item,
                "instance_id": approval.get("instance_id") or "",
            }
    return {}


def _comment_preview_kwargs(batch_name: str, source: dict, version_name: str | None = None) -> tuple[dict, dict]:
    parsed = parse_packing_comment(str(source.get("remark") or ""))
    source_id = str(source.get("source_id") or "")
    source_remark = (
        f"钉钉审批 {source.get('instance_id') or '--'}；"
        f"评论人 {source.get('user_name') or source.get('user_id') or '--'}"
        f"({source.get('user_id') or '--'})；"
        f"评论时间 {source.get('operation_time') or '--'}；"
        f"原文：{source.get('remark') or ''}"
    )
    rows = []
    for row in parsed.get("rows") or []:
        rows.append({
            **row,
            "source_remark": source_remark,
            "source_doc_no": f"DINGTALK-COMMENT:{source_id}",
        })
    kwargs = {
        "batch_name": batch_name,
        "attachment_name": f"DINGTALK-COMMENT:{source_id}",
        "version_name": version_name,
        "template_hint": "dingtalk_comment",
        "sheet_rows_json": json.dumps(rows, ensure_ascii=False),
    }
    return parsed, kwargs


def preview_packing_source(
    batch_name: str,
    source_kind: str,
    source_id: str,
    version_name: str | None = None,
) -> dict:
    kind = str(source_kind or "").strip().lower()
    resolved_source_id = str(source_id or "").strip()
    context = _source_context(batch_name, version_name)
    if kind == "attachment":
        source = _attachment_source(batch_name, resolved_source_id)
        if not source:
            return {"ok": False, "message": "未找到当前批次的钉钉附件。"}
        source_hash = _attachment_hash(source)
        if not str(source.get("file_url") or "").strip():
            return {
                "ok": False,
                "download_required": True,
                "attachment_name": source.get("name"),
                "source_kind": kind,
                "source_id": resolved_source_id,
                "message": "附件尚未保存到系统，请先下载后再生成装箱预览。",
            }
        result = import_service.preview_packing_list_attachment(
            batch_name=batch_name,
            attachment_name=source.get("name"),
            file_url=source.get("file_url"),
            version_name=context["version_name"] or version_name,
        )
    elif kind == "comment":
        source = _find_comment_source(batch_name, resolved_source_id)
        if not source:
            return {"ok": False, "source_changed": True, "message": "未找到该钉钉评论，可能已重新同步。"}
        source_hash = str(source.get("source_id") or "")
        parsed, kwargs = _comment_preview_kwargs(batch_name, source, context["version_name"] or version_name)
        if not parsed.get("is_candidate") or not parsed.get("rows"):
            return {"ok": False, "message": "该评论没有足够的装箱数量或物料信息，不能生成写入预览。"}
        result = import_service.preview_packing_list_attachment(**kwargs)
        result["comment_preview"] = {key: value for key, value in parsed.items() if key != "source_text"}
        result["source_snapshot"] = {
            "instance_id": source.get("instance_id") or "",
            "operation_time": source.get("operation_time") or "",
            "user_id": source.get("user_id") or "",
            "user_name": source.get("user_name") or "",
            "remark": source.get("remark") or "",
        }
    else:
        return {"ok": False, "message": "装箱来源类型必须是 attachment 或 comment。"}

    return {
        **result,
        "source_kind": kind,
        "source_id": resolved_source_id,
        "source_revision": _encode_revision(
            kind,
            resolved_source_id,
            source_hash,
            batch_name=batch_name,
            version_name=str(result.get("version_name") or context["version_name"] or ""),
            batch_modified=context["batch_modified"],
            version_modified=context["version_modified"],
        ),
    }


def apply_packing_source(
    batch_name: str,
    source_revision: str,
    resolutions_json: str | dict | None = None,
    version_name: str | None = None,
) -> dict:
    revision = _decode_revision(source_revision)
    kind = str(revision.get("kind") or "")
    source_id = str(revision.get("id") or "")
    expected_hash = str(revision.get("hash") or "")
    revision_batch = str(revision.get("batch") or "")
    revision_version = str(revision.get("version") or "")
    if revision_batch != str(batch_name) or (version_name and str(version_name) != revision_version):
        return {"ok": False, "source_changed": True, "message": "装箱预览不属于当前批次或版本，请重新预览。"}
    context = _source_context(batch_name, revision_version)
    if (
        context["version_name"] != revision_version
        or context["batch_modified"] != str(revision.get("batch_modified") or "")
        or context["version_modified"] != str(revision.get("version_modified") or "")
    ):
        return {"ok": False, "source_changed": True, "message": "批次数据已变化，请重新预览后确认。"}
    if kind == "attachment":
        source = _attachment_source(batch_name, source_id)
        actual_hash = _attachment_hash(source) if source else ""
        kwargs = {
            "batch_name": batch_name,
            "attachment_name": source.get("name") if source else None,
            "file_url": source.get("file_url") if source else None,
            "version_name": revision_version,
        }
    elif kind == "comment":
        source = _find_comment_source(batch_name, source_id)
        actual_hash = str(source.get("source_id") or "")
        _parsed, kwargs = _comment_preview_kwargs(batch_name, source, revision_version) if source else ({}, {})
    else:
        return {"ok": False, "source_changed": True, "message": "装箱来源版本无效，请重新预览。"}
    if not source or not expected_hash or expected_hash != actual_hash:
        return {"ok": False, "source_changed": True, "message": "钉钉装箱来源已变化，请重新预览后确认。"}

    if isinstance(resolutions_json, dict):
        resolutions = resolutions_json
    else:
        try:
            resolutions = json.loads(resolutions_json or "{}")
        except (TypeError, ValueError):
            resolutions = {}
    if not isinstance(resolutions, dict):
        resolutions = {}
    fresh_preview = import_service.preview_packing_list_attachment(**kwargs)
    if not fresh_preview.get("ok"):
        return {"ok": False, "source_changed": True, "message": fresh_preview.get("message") or "来源重新预览失败。"}
    try:
        apply_result = import_service.apply_packing_list_fillable_fields(
            **kwargs,
            preview_result=fresh_preview,
            recalculate_after_writeback=False,
            commit_after_writeback=False,
            auto_create_unmatched_items=bool(resolutions.get("create_unmatched_items")),
        )
        if not apply_result.get("ok"):
            _rollback()
            return apply_result
        conflict_results = []
        for conflict in resolutions.get("conflicts") or []:
            if not isinstance(conflict, dict):
                continue
            action = str(conflict.get("action") or "pending_review")
            if action not in {"use_attachment", "keep_system", "pending_review"}:
                continue
            result = import_service.resolve_packing_list_conflict_row(
                **kwargs,
                preview_result=fresh_preview,
                target_item_name=str(conflict.get("target_item_name") or ""),
                resolution_action=action,
                recalculate_after_writeback=False,
                commit_after_writeback=False,
            )
            if not result.get("ok"):
                _rollback()
                return {"ok": False, "message": result.get("message") or "装箱冲突处理失败，未保存任何更改。", "conflict_result": result}
            conflict_results.append(result)
        _commit()
    except Exception:
        _rollback()
        raise
    changed = bool(
        apply_result.get("updated_count")
        or apply_result.get("created_count")
        or any(result.get("changed_field_count") for result in conflict_results)
    )
    recalculate_result = import_service._recalculate_after_writeback(
        batch_doc_name=apply_result.get("batch_doc_name") or batch_name,
        version_name=apply_result.get("version_name") or revision_version,
        enabled=changed,
    )
    return {
        **apply_result,
        "source_kind": kind,
        "source_id": source_id,
        "source_revision": source_revision,
        "conflict_results": conflict_results,
        "recalculate_result": recalculate_result,
        "message": import_service._message_with_recalculate_result(
            str(apply_result.get("message") or "装箱来源已确认。"),
            recalculate_result,
        ),
    }
