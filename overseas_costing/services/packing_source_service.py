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
from overseas_costing.services import effective_logistics_source as effective_source


SOURCE_KIND_ALIASES = {
    "manual_attachment": "manual_attachment",
    "attachment": "approval_attachment",
    "approval_attachment": "approval_attachment",
    "comment": "approval_comment",
    "approval_comment": "approval_comment",
    "wiki_sheet": "wiki_sheet",
}


def normalize_packing_source_kind(value: str) -> str:
    kind = str(value or "").strip().lower()
    if kind not in SOURCE_KIND_ALIASES:
        raise ValueError("不支持的装箱来源类型。")
    return SOURCE_KIND_ALIASES[kind]


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
    source_context: dict | None = None,
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
            "source_context": source_context or {},
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
    effective = (effective_source.current_source_bundle(batch_name, version_name) or {}).get('context') or {}
    if frappe is None or not hasattr(frappe, "db"):
        return {
            "version_name": str(version_name or ""),
            "batch_modified": "",
            "version_modified": "",
            "valid": True,
            "source_context": effective,
        }
    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_name,
        ["name", "current_version", "modified"],
        as_dict=True,
    ) or {}
    resolved_version = str(version_name or batch.get("current_version") or "")
    version = (
        frappe.db.get_value(
            "Overseas Cost Version",
            resolved_version,
            ["name", "batch", "modified"],
            as_dict=True,
        )
        if resolved_version
        else {}
    ) or {}
    batch_doc_name = str(batch.get("name") or "")
    current_version = str(batch.get("current_version") or "")
    return {
        "version_name": resolved_version,
        "batch_modified": str(batch.get("modified") or ""),
        "version_modified": str(version.get("modified") or ""),
        "source_context": effective,
        "valid": bool(
            batch_doc_name
            and resolved_version
            and resolved_version == current_version
            and str(version.get("name") or resolved_version) == resolved_version
            and str(version.get("batch") or "") == batch_doc_name
        ),
    }


def _lock_packing_scope(batch_name: str, version_name: str, source_kind: str, source_id: str) -> None:
    """Serialize preview validation and writeback for one batch/version."""

    effective_source.current_source_bundle(batch_name, version_name, lock=True)
    sql = getattr(getattr(frappe, "db", None), "sql", None) if frappe is not None else None
    if not callable(sql):
        return
    sql(
        "SELECT name FROM `tabOverseas Cost Batch` WHERE name=%s FOR UPDATE",
        (batch_name,),
    )
    sql(
        "SELECT name FROM `tabOverseas Cost Version` WHERE name=%s AND batch=%s FOR UPDATE",
        (version_name, batch_name),
    )
    sql(
        "SELECT name FROM `tabOverseas Cost Item` WHERE batch=%s AND version=%s ORDER BY name FOR UPDATE",
        (batch_name, version_name),
    )
    if source_kind == "attachment":
        sql(
            "SELECT name FROM `tabOverseas Cost Attachment` WHERE name=%s AND batch=%s FOR UPDATE",
            (source_id, batch_name),
        )


COMMENT_RESOLUTION_KEY = "dingtalk_packing_comment_resolutions"


def _comment_resolutions(batch_name: str, source_id: str) -> list[dict]:
    if frappe is None:
        return []
    raw = frappe.db.get_value("Overseas Cost Batch", batch_name, "extra_json") or ""
    try:
        payload = json.loads(raw) if isinstance(raw, str) and raw else (raw if isinstance(raw, dict) else {})
    except (TypeError, ValueError):
        payload = {}
    grouped = payload.get(COMMENT_RESOLUTION_KEY) if isinstance(payload, dict) else {}
    history = grouped.get(source_id) if isinstance(grouped, dict) else []
    return [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []


def _save_comment_resolutions(batch_name: str, source_id: str, resolutions: list[dict]) -> bool:
    if frappe is None or not resolutions:
        return False
    raw = frappe.db.get_value("Overseas Cost Batch", batch_name, "extra_json") or ""
    try:
        payload = json.loads(raw) if isinstance(raw, str) and raw else (raw if isinstance(raw, dict) else {})
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    grouped = payload.get(COMMENT_RESOLUTION_KEY)
    if not isinstance(grouped, dict):
        grouped = {}
    history = grouped.get(source_id)
    if not isinstance(history, list):
        history = []
    grouped[source_id] = [*history, *resolutions][-50:]
    payload[COMMENT_RESOLUTION_KEY] = grouped
    frappe.db.set_value(
        "Overseas Cost Batch",
        batch_name,
        "extra_json",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        update_modified=True,
    )
    return True


def _decorate_comment_resolutions(result: dict, history: list[dict]) -> None:
    if not history:
        result["conflict_resolutions"] = []
        return
    latest = {}
    for item in history:
        target = str(item.get("target_item_name") or "")
        if target:
            latest[target] = item
    for row in (result.get("writeback_preview") or {}).get("matched_rows") or []:
        resolution = latest.get(str(row.get("target_item_name") or ""))
        if resolution:
            row["conflict_resolution"] = resolution
    result["conflict_resolutions"] = history


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
        ["name", "batch", "version", "source_type", "file_name", "file_url", "modified", "parse_result_json"],
        as_dict=True,
    ) or {}


def _attachment_source_v2(batch_name: str, source_id: str) -> dict:
    if frappe is None:
        return {}
    return frappe.db.get_value(
        "Overseas Cost Attachment",
        {"name": source_id, "batch": batch_name},
        [
            "name",
            "batch",
            "version",
            "source_type",
            "file_name",
            "file_url",
            "modified",
            "parse_result_json",
        ],
        as_dict=True,
    ) or {}


def _attachment_is_audit_only(source: dict) -> bool:
    try:
        snapshot = json.loads(source.get("parse_result_json") or "{}")
    except (TypeError, ValueError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        return False
    return bool(
        snapshot.get("approval_excluded")
        or snapshot.get("cost_source_allowed") is False
        or import_service._approval_reference_is_excluded(str(source.get("batch") or ""), snapshot)
    )


def _find_comment_source(batch_name: str, source_id: str) -> dict:
    bundle = effective_source.current_source_bundle(batch_name)
    detail = (effective_source.approval_detail_for_bundle(bundle) if bundle and bundle['context']['root_kind'] == 'expense'
              else dingtalk_approval_service.get_batch_dingtalk_approval_detail(batch_name))
    approvals = [detail.get("main_approval"), *(detail.get("linked_purchase_approvals") or [])]
    for approval in approvals:
        if not isinstance(approval, dict) or approval.get("excluded"):
            continue
        for item in approval.get("timeline") or []:
            if not isinstance(item, dict) or str(item.get("source_id") or "") != str(source_id):
                continue
            return {
                **item,
                "instance_id": approval.get("instance_id") or "",
            }
    return {}


def resolve_trusted_packing_source(
    *, batch_name: str, source_kind: str, source_id: str, sheet_name: str | None = None,
    strict_material_xlsx: bool = False,
) -> dict:
    bundle = effective_source.current_source_bundle(batch_name)
    context = (bundle or {}).get('context') or {}
    effective_source.require_readable(context)
    trusted = _resolve_trusted_packing_source(batch_name=batch_name, source_kind=source_kind,
        source_id=source_id, sheet_name=sheet_name, strict_material_xlsx=strict_material_xlsx)
    latest = effective_source.current_source_bundle(batch_name)
    if context != ((latest or {}).get('context') or {}):
        raise ValueError('当前关联来源已变化，请重新预览。')
    if context:
        trusted['source_context'] = context
        trusted['source_hash'] = hashlib.sha256(f"{trusted['source_hash']}|{context['fingerprint']}".encode()).hexdigest()
    return trusted


def resolve_packing_attachment_path(source,bundle=None):
    """Keep bound XLS support inside the already-authorized attachment scope."""
    if bundle and bundle['context']['root_kind']=='expense':
        if not effective_source.attachment_allowed(source,bundle,for_analysis=True):
            raise ValueError('附件不属于当前采购支出资料。')
        if str(source.get('file_name') or '').lower().endswith('.xls'):
            from .attachment_parse_service import _resolve_source_file_path
            return _resolve_source_file_path(file_url=str(source.get('file_url') or ''))
    return import_service._resolve_excel_file_path(file_url=str(source.get('file_url') or ''))


def _read_archived_xls_grid(path, sheet_name, *, max_rows=1000,max_columns=120):
    """Read a current locally archived binary workbook without converting/uploading."""
    import xlrd
    from .packing_grid import Cell, MergeRange, dataclass_dict
    if path.stat().st_size > 20*1024*1024:
        raise ValueError('归档工作簿超过 20 MB 限制。')
    book=xlrd.open_workbook(str(path),formatting_info=True)
    try:
        if not sheet_name or sheet_name not in book.sheet_names():
            raise ValueError('请选择归档工作簿中的准确工作表。')
        sheet=book.sheet_by_name(sheet_name)
        if sheet.nrows > max_rows or sheet.ncols > max_columns:
            raise ValueError('归档工作表超过行列限制，请核对完整资料。')
        cells=[]
        for r in range(sheet.nrows):
            row=[]
            for c in range(sheet.ncols):
                if sheet.cell_type(r,c)==xlrd.XL_CELL_ERROR:
                    raise ValueError('归档工作表包含错误单元格，不能采用。')
                row.append(dataclass_dict(Cell(raw_value=sheet.cell_value(r,c),display_value=None,formula=None,row=r+1,column=c+1)))
            cells.append(row)
        return {'schema_version':1,'source_kind':'approval_attachment','sheet_name':sheet_name,
                'cells':cells,'merge_ranges_available':True,
                'merge_ranges':[dataclass_dict(MergeRange(start_row=r1+1,end_row=r2,start_column=c1+1,end_column=c2,evidence_kind='xls_merge'))
                                for r1,r2,c1,c2 in sheet.merged_cells], 'available_sheets':book.sheet_names()}
    finally:
        book.release_resources()


def _bound_wiki_cache_key(context, source_id):
    from .logistics_settlement.model import digest
    return digest('bound_wiki_snapshot',context.get('policy_version'),context['root_source_id'],context['source_snapshot'],source_id)


def load_bound_wiki_snapshot(context, source_id, *, store=None):
    from .logistics_settlement.store import Store
    from copy import deepcopy
    cache=(store or Store.frappe()).get('state',_bound_wiki_cache_key(context,source_id)) or {}
    saved=cache.get('source_context') or {}
    if any(saved.get(key)!=context.get(key) for key in ('policy_version','root_source_id','source_snapshot','corp_id','instance_id')):
        return None
    return deepcopy(cache.get('trusted'))


def wiki_refresh_status(context, source_id, *, store=None):
    """Local-only refresh health; operational timestamps are not content identity."""
    from .logistics_settlement.store import Store
    from .logistics_settlement.model import digest
    store=store or Store.frappe()
    cache=store.get('state',_bound_wiki_cache_key(context,source_id)) or {}
    saved=cache.get('source_context') or {}
    if any(saved.get(key)!=context.get(key) for key in ('policy_version','root_source_id','source_snapshot','corp_id','instance_id')):
        cache={}
    health=store.get('state',digest('bound_wiki_refresh_health',context.get('binding_id'),source_id)) or {}
    if any(health.get(key)!=context.get(key) for key in ('root_source_id','source_snapshot')):
        health={}
    return {'cache_refreshed_at':cache.get('updated_at') or '',
            'refresh_last_checked_at':health.get('last_checked_at') or '',
            'refresh_last_success_at':health.get('last_success_at') or cache.get('updated_at') or '',
            'refresh_error':health.get('last_error') or ''}


def refresh_bound_wiki_snapshot(batch_name, source_id, *, store=None, ledger=None, clients=None,actor='wiki-refresh'):
    """Explicit refresh/background only. Queries/AI read the persisted local copy."""
    from .logistics_settlement.store import Store
    from .logistics_settlement.model import dumps
    from .logistics_settlement.jobs import utcnow
    from .packing_grid import build_grid_from_dingtalk_snapshot
    from .packing_parse_service import parse_packing_grid
    from overseas_costing.integrations.dingtalk_packing_source import get_packing_runtime_clients
    from .logistics_settlement.ledger import FrappeLedger
    store=store or Store.frappe()
    ledger=ledger or FrappeLedger()
    bundle=effective_source.load_source_bundle(batch_name,store=store,ledger=ledger)
    context=bundle['context']
    effective_source.require_readable(context)
    if context['root_kind']!='expense' or source_id not in effective_source.explicit_wiki_sources(bundle['source']):
        raise ValueError('装箱计划表不是当前采购支出明确关联的工作表。')
    workbook, separator, sheet=source_id.partition(':')
    if not separator or not workbook or not sheet:
        raise ValueError('装箱计划表标识不完整。')
    cache_key=_bound_wiki_cache_key(context,source_id)
    observed=store.get('state',cache_key) or {}
    observed_generation=int(observed.get('refresh_generation') or 0)
    clients=clients or get_packing_runtime_clients()
    manifest=clients.catalog.get_latest_snapshot(workbook,sheet) or {}
    if not manifest.get('content_sha256') or str(manifest.get('corp_id') or '')!=context['corp_id']:
        raise ValueError('当前工作表缺少本企业可验证归档，请先完成归档刷新。')
    payload=clients.archive.download(manifest)
    if str(payload.get('workbookId') or '')!=workbook or str(payload.get('sheetId') or '')!=sheet:
        raise ValueError('归档内容不属于所选工作表。')
    grid=build_grid_from_dingtalk_snapshot(payload)
    trusted={'source_hash':str(manifest['content_sha256']), 'grid':grid,'preview':parse_packing_grid(grid),
             'source':{'source_kind':'wiki_sheet','source_id':source_id,'workbook_id':workbook,'sheet_id':sheet,
                       'source_label':str(payload.get('sheetName') or sheet),'sheet_name':str(payload.get('sheetName') or ''),
                       'source_updated_at':payload.get('captureFinishedAt') or manifest.get('capture_finished_at')}}
    with store.atomic():
        current=effective_source.load_source_bundle(batch_name,store=store,ledger=ledger,lock=True)
        cache=store.get('state',cache_key,lock=True) or {}
        if int(cache.get('refresh_generation') or 0)!=observed_generation:
            raise ValueError('已有更新的工作表刷新结果，请重新读取本地资料。')
        if current['context']!=context or source_id not in effective_source.explicit_wiki_sources(current['source']):
            raise ValueError('获取期间采购支出关联已变化，请重新获取。')
        old_sha=(cache.get('trusted') or {}).get('source_hash')
        changed=bool(old_sha and old_sha!=trusted['source_hash'])
        store.put('state',{'id':cache_key,'updated_at':utcnow(),
            'data':dumps({'source_context':context,'trusted':trusted,'archive_snapshot_id':manifest.get('id'),
                          'refresh_generation':observed_generation+1})})
        from .logistics_settlement.bound_wiki_service import record_refresh_health
        record_refresh_health(store,current['binding'],current['source'],source_id)
        if changed:
            from .logistics_settlement.bound_wiki_service import mark_wiki_changed
            binding=mark_wiki_changed(store,ledger,current,source_id,old_sha,trusted['source_hash'],actor)
            context=effective_source.context_for_source(current['source'],binding,context['cost_version'],batch_name)
    return {'ok':True,'source_id':source_id,'source_context':context,'source_hash':trusted['source_hash'],'changed':changed}


def _resolve_trusted_packing_source(
    *,
    batch_name: str,
    source_kind: str,
    source_id: str,
    sheet_name: str | None = None,
    strict_material_xlsx: bool = False,
) -> dict:
    """重新从服务器可信存储解析来源，浏览器不能提供正文、路径、总数或工作簿 URL。"""

    from overseas_costing.services.packing_grid import build_grid_from_dingtalk_snapshot
    from overseas_costing.services.packing_parse_service import parse_packing_grid
    from overseas_costing.utils.excel_workbook import read_packing_grid

    kind = normalize_packing_source_kind(source_kind)
    resolved_source_id = str(source_id or "").strip()
    if kind in {"manual_attachment", "approval_attachment"}:
        source = _attachment_source_v2(batch_name, resolved_source_id)
        effective_source.validate_packing_source(batch_name, kind, resolved_source_id, attachment=source)
        if not source:
            raise ValueError("未找到当前批次的装箱附件。")
        if kind == "approval_attachment" and str(source.get("source_type") or "").upper() != "OA":
            raise ValueError("所选附件不是当前批次的钉钉审批附件。")
        bundle = effective_source.current_source_bundle(batch_name)
        if _attachment_is_audit_only(source) and not (bundle and bundle['context']['root_kind'] == 'expense'):
            raise ValueError("该附件来自已排除审批，只能审计查看，不能作为装箱来源。")
        file_url = str(source.get("file_url") or "").strip()
        if not file_url:
            raise ValueError("装箱附件尚未保存到系统。")
        selected_sheet = str(sheet_name or "").strip()
        path = resolve_packing_attachment_path(source,bundle)
        bound_xls = bool(bundle and bundle['context']['root_kind']=='expense' and path.suffix.lower()=='.xls')
        if strict_material_xlsx and not bound_xls:
            from overseas_costing.services.material_import_service import validate_material_workbook_metadata

            validate_material_workbook_metadata(
                str(source.get("file_name") or path.name),
                path.stat().st_size,
            )
        grid = _read_archived_xls_grid(path,selected_sheet) if bound_xls else read_packing_grid(
            str(path),
            sheet_name=selected_sheet,
            require_exact_sheet=True,
            max_rows=1000 if strict_material_xlsx else None,
            max_columns=120 if strict_material_xlsx else None,
        )
        source_hash = hashlib.sha256(
            f"{_attachment_hash(source)}|{selected_sheet}".encode("utf-8")
        ).hexdigest()
        return {
            "source_hash": source_hash,
            "source": {
                "source_kind": kind,
                "source_id": resolved_source_id,
                "source_label": str(source.get("file_name") or resolved_source_id),
                "sheet_name": selected_sheet,
                "source_updated_at": str(source.get("modified") or ""),
            },
            "grid": grid,
            "preview": parse_packing_grid(grid),
        }

    if kind == "approval_comment":
        effective_source.validate_packing_source(batch_name, kind, resolved_source_id)
        source = _find_comment_source(batch_name, resolved_source_id)
        if not source:
            raise ValueError("未找到该钉钉评论，可能已重新同步。")
        parsed = parse_packing_comment(str(source.get("remark") or ""))
        if not parsed.get("is_candidate"):
            raise ValueError("该评论没有可识别的装箱信息。")
        source_hash = hashlib.sha256(
            json.dumps(
                {
                    "instance_id": source.get("instance_id"),
                    "operation_time": source.get("operation_time"),
                    "user_id": source.get("user_id"),
                    "remark": source.get("remark"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "source_hash": source_hash,
            "source": {
                "source_kind": kind,
                "source_id": resolved_source_id,
                "source_label": "钉钉审批评论",
                "instance_id": source.get("instance_id") or "",
                "source_updated_at": source.get("operation_time") or "",
                "comment_user": source.get("user_name") or source.get("user_id") or "",
            },
            "preview": _comment_snapshot_preview(parsed),
        }

    effective_source.validate_packing_source(batch_name, kind, resolved_source_id)
    bundle=effective_source.current_source_bundle(batch_name)
    if bundle and bundle['context']['root_kind']=='expense':
        cached=load_bound_wiki_snapshot(bundle['context'],resolved_source_id)
        if not cached:
            raise ValueError('当前采购支出工作表尚未获取到本地，请先点击刷新或获取资料。')
        return cached
    workbook_id, separator, sheet_id = resolved_source_id.partition(":")
    if not separator or not workbook_id or not sheet_id:
        raise ValueError("装箱计划表 Sheet 来源 ID 不合法。")
    from overseas_costing.integrations.dingtalk_packing_source import get_packing_runtime_clients

    clients = get_packing_runtime_clients()
    manifest = clients.catalog.get_latest_snapshot(workbook_id, sheet_id)
    if not manifest:
        raise ValueError("装箱计划表 Sheet 尚无可用缓存，请先刷新资料。")
    payload = clients.archive.download(manifest)
    if str(payload.get("workbookId") or "") != workbook_id or str(payload.get("sheetId") or "") != sheet_id:
        raise ValueError("装箱计划表快照与所选 Sheet 不一致。")
    grid = build_grid_from_dingtalk_snapshot(payload)
    source_hash = str(manifest.get("content_sha256") or "").strip().lower()
    if not source_hash:
        source_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return {
        "source_hash": source_hash,
        "source": {
            "source_kind": kind,
            "source_id": resolved_source_id,
            "source_label": str(payload.get("sheetName") or sheet_id),
            "workbook_id": workbook_id,
            "sheet_id": sheet_id,
            "sheet_name": payload.get("sheetName") or "",
            "source_updated_at": payload.get("captureFinishedAt") or manifest.get("capture_finished_at"),
        },
        "grid": grid,
        "preview": parse_packing_grid(grid),
    }


def _comment_snapshot_preview(parsed: dict) -> dict:
    rows = []
    for index, row in enumerate(parsed.get("rows") or [], start=1):
        rows.append(
            {
                "source_row": index,
                "material_code": row.get("material_code"),
                "product_name": row.get("product_name"),
                "quantity": str(row.get("actual_shipped_qty")) if row.get("actual_shipped_qty") is not None else None,
                "unit": row.get("unit"),
                "raw_fields": dict(row),
            }
        )
    gross = parsed.get("gross_weight_kg")
    volume = parsed.get("volume_m3")
    group = {
        "group_id": "comment-package-1",
        "row_numbers": list(range(1, len(rows) + 1)),
        "dimensions": {"value": parsed.get("dimensions_cm"), "unit": "cm"},
        "net_weight_kg": {"value": None, "count_once": True},
        "gross_weight_kg": {"value": str(gross) if gross is not None else None, "count_once": True},
        "volume_m3": {"value": str(volume) if volume is not None else None, "count_once": True},
        "package_count": {"value": "1", "count_once": True},
        "evidence": [{"kind": "trusted_comment_text", "confidence": parsed.get("confidence")}],
        "needs_confirmation": True,
    }
    blocking = [{"code": "group_confirmation_required", "message": "评论中的包装范围需要人工确认。"}]
    return {
        "ok": False,
        "source": {"source_kind": "approval_comment"},
        "material_row_count": len(rows),
        "package_group_count": 1,
        "package_count": 1,
        "material_rows": rows,
        "groups": [group],
        "totals": {
            "net_weight_kg": {"value": None, "kind": "missing"},
            "gross_weight_kg": {"value": str(gross) if gross is not None else None, "kind": "comment_value"},
            "volume_m3": {"value": str(volume) if volume is not None else None, "kind": "comment_calculated_dimensions"},
        },
        "validation": {
            "blocking": blocking,
            "warnings": [],
            "needs_group_confirmation": True,
        },
    }


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
            "source_attachment_id": f"DINGTALK-COMMENT:{source_id}",
            "source_file_name": "钉钉审批评论",
        })
    kwargs = {
        "batch_name": batch_name,
        # 评论不是 Overseas Cost Attachment 单据，不要传虚拟附件名称触发 Frappe 的不存在提示。
        "attachment_name": None,
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
    if not context.get("valid"):
        return {"ok": False, "source_changed": True, "message": "当前版本不属于该批次或已不是当前版本，请刷新后重试。"}
    if kind == "attachment":
        source = _attachment_source(batch_name, resolved_source_id)
        effective_source.validate_packing_source(batch_name, 'approval_attachment', resolved_source_id, attachment=source)
        if not source:
            return {"ok": False, "message": "未找到当前批次的钉钉附件。"}
        if _attachment_is_audit_only(source):
            return {
                "ok": False,
                "audit_only": True,
                "message": "该附件来自已排除审批，仅供审计查看和下载，不能作为装箱或成本数据源。",
            }
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
            trusted_server_payload=True,
        )
    elif kind == "comment":
        source = _find_comment_source(batch_name, resolved_source_id)
        if not source:
            return {"ok": False, "source_changed": True, "message": "未找到该钉钉评论，可能已重新同步。"}
        source_hash = str(source.get("source_id") or "")
        parsed, kwargs = _comment_preview_kwargs(batch_name, source, context["version_name"] or version_name)
        if not parsed.get("is_candidate") or not parsed.get("rows"):
            return {"ok": False, "message": "该评论没有足够的装箱数量或物料信息，不能生成写入预览。"}
        result = import_service.preview_packing_list_attachment(**kwargs, trusted_server_payload=True)
        _decorate_comment_resolutions(result, _comment_resolutions(batch_name, resolved_source_id))
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
            source_context=context.get('source_context') or {},
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
    _lock_packing_scope(batch_name, revision_version, kind, source_id)
    context = _source_context(batch_name, revision_version)
    if (
        not context.get("valid")
        or
        context["version_name"] != revision_version
        or context["batch_modified"] != str(revision.get("batch_modified") or "")
        or context["version_modified"] != str(revision.get("version_modified") or "")
        or (context.get('source_context') or {}) != (revision.get('source_context') or {})
    ):
        return {"ok": False, "source_changed": True, "message": "批次数据已变化，请重新预览后确认。"}
    if kind == "attachment":
        source = _attachment_source(batch_name, source_id)
        if source and _attachment_is_audit_only(source):
            return {
                "ok": False,
                "audit_only": True,
                "source_changed": True,
                "message": "该附件来自已排除审批，不能写入装箱或成本数据。",
            }
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
    fresh_preview = import_service.preview_packing_list_attachment(**kwargs, trusted_server_payload=True)
    if not fresh_preview.get("ok"):
        return {"ok": False, "source_changed": True, "message": fresh_preview.get("message") or "来源重新预览失败。"}
    try:
        apply_result = import_service.apply_packing_list_fillable_fields(
            **kwargs,
            preview_result=fresh_preview,
            recalculate_after_writeback=False,
            commit_after_writeback=False,
            auto_create_unmatched_items=bool(resolutions.get("create_unmatched_items")),
            trusted_server_payload=True,
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
                trusted_server_payload=True,
            )
            if not result.get("ok"):
                _rollback()
                return {"ok": False, "message": result.get("message") or "装箱冲突处理失败，未保存任何更改。", "conflict_result": result}
            conflict_results.append(result)
        if kind == "comment" and conflict_results:
            saved = _save_comment_resolutions(
                batch_name,
                source_id,
                [result.get("resolution") for result in conflict_results if isinstance(result.get("resolution"), dict)],
            )
            for result in conflict_results:
                result["resolution_saved"] = saved
        changed = bool(
            apply_result.get("updated_count")
            or apply_result.get("created_count")
            or any(result.get("changed_field_count") for result in conflict_results)
        )
        recalculate_result = import_service._recalculate_after_writeback(
            batch_doc_name=apply_result.get("batch_doc_name") or batch_name,
            version_name=apply_result.get("version_name") or revision_version,
            enabled=changed,
            commit_after_recalculate=False,
        )
        if recalculate_result.get("action") == "failed" or recalculate_result.get("ok") is False:
            _rollback()
            return {
                "ok": False,
                "message": recalculate_result.get("message") or "装箱字段重算失败，全部更改已回滚。",
                "recalculate_result": recalculate_result,
            }
        _commit()
    except Exception:
        _rollback()
        raise
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
