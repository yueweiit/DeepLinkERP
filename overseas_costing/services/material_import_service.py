"""物料字段级导入预览、签名修订和原子采用。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

try:
    import frappe
except Exception:  # pragma: no cover - pure tests do not require Frappe
    frappe = None

from overseas_costing.services import material_input_service, packing_source_service


MATERIAL_PURCHASE_FACT_FIELDS = (
    "material_code",
    "product_name",
    "product_name_es",
    "spec_model",
    "purchase_uom",
    "unit_price",
    "unit_price_uom",
    "purchase_currency",
    "quantity",
    "goods_value",
)

MATERIAL_IMPORT_FIELDS = (
    "actual_shipped_qty",
    "shipped_uom",
    "gross_weight_kg",
    "volume_m3",
    "volume_weight_kg",
    "chargeable_weight_kg",
    "project_collection",
)
MATERIAL_SOURCE_FIELDS = MATERIAL_PURCHASE_FACT_FIELDS + MATERIAL_IMPORT_FIELDS

SOURCE_KIND_ALIASES = {
    "manual_xlsx": "manual_attachment",
    "manual_attachment": "manual_attachment",
    "approval_attachment": "approval_attachment",
    "attachment": "approval_attachment",
    "approval_comment": "approval_comment",
    "comment": "approval_comment",
    "wiki_sheet": "wiki_sheet",
}

MAX_MATERIAL_WORKBOOK_BYTES = 20 * 1024 * 1024


def validate_material_workbook_metadata(file_name: str, file_size: object) -> None:
    """Reject non-xlsx and oversized material workbooks before parsing."""

    if not str(file_name or "").strip().lower().endswith(".xlsx"):
        raise ValueError("物料 Excel 导入仅支持 .xlsx 文件。")
    try:
        normalized_size = int(file_size or 0)
    except (TypeError, ValueError):
        normalized_size = 0
    if normalized_size > MAX_MATERIAL_WORKBOOK_BYTES:
        raise ValueError("物料 Excel 文件不能超过 20 MB。")


def _normalized(value: object) -> str:
    return str(value or "").strip().casefold()


def _equal(old_value: object, new_value: object) -> bool:
    if old_value in (None, "") and new_value in (None, ""):
        return True
    try:
        return Decimal(str(old_value)) == Decimal(str(new_value))
    except (InvalidOperation, TypeError, ValueError):
        return str(old_value or "").strip() == str(new_value or "").strip()


def build_field_changes(existing: dict, incoming: dict) -> list:
    """Return only nonblank, allow-listed field changes."""

    changes = []
    for fieldname in MATERIAL_IMPORT_FIELDS:
        new_value = incoming.get(fieldname)
        if new_value in (None, ""):
            continue
        old_value = existing.get(fieldname)
        if _equal(old_value, new_value):
            continue
        changes.append(
            {
                "field": fieldname,
                "old": old_value,
                "new": new_value,
                "conflict": old_value not in (None, ""),
            }
        )
    return changes


def _stable_item_key(item: dict) -> str:
    stored = str(item.get("stable_line_key") or "").strip()
    item_name = str(item.get("name") or "").strip()
    return stored or (f"legacy:{item_name}" if item_name else "")


def _candidate_view(item: dict) -> dict:
    return {
        "name": item.get("name") or "",
        "stable_line_key": _stable_item_key(item),
        "row_no": item.get("row_no"),
        "excel_row_no": item.get("excel_row_no"),
        "material_code": item.get("material_code") or "",
        "source_doc_no": item.get("source_doc_no") or "",
    }


def _match_candidates(existing: list, incoming: dict) -> list:
    stable_line_key = _normalized(incoming.get("stable_line_key"))
    if stable_line_key:
        return [
            item for item in existing
            if _normalized(item.get("stable_line_key")) == stable_line_key
        ]

    material_code = _normalized(incoming.get("material_code"))
    if not material_code:
        return []
    candidates = [
        item for item in existing
        if _normalized(item.get("material_code")) == material_code
    ]
    source_doc_no = _normalized(incoming.get("source_doc_no"))
    if source_doc_no:
        source_matches = [
            item for item in candidates
            if _normalized(item.get("source_doc_no")) == source_doc_no
        ]
        if source_matches:
            candidates = source_matches
    source_line_no = _normalized(
        incoming.get("source_line_no")
        or incoming.get("purchase_source_row")
        or incoming.get("source_excel_row_no")
    )
    if source_line_no:
        line_matches = [
            item
            for item in candidates
            if _normalized(item.get("excel_row_no") or item.get("source_line_no")) == source_line_no
        ]
        if line_matches:
            return line_matches
    return candidates


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_material_import_preview(existing: list, incoming: list, source: dict) -> dict:
    """Compare trusted source rows to current item rows without guessing duplicates."""

    preview_rows = []
    for index, source_row in enumerate(incoming or [], start=1):
        normalized_row = dict(source_row or {})
        normalized_row.setdefault("source_row", index)
        candidates = _match_candidates(existing or [], normalized_row)
        if len(candidates) == 1:
            target = candidates[0]
            status = "matched"
            target_key = _stable_item_key(target)
            changes = build_field_changes(target, normalized_row)
        elif len(candidates) > 1:
            target = {}
            status = "choice_required"
            target_key = ""
            changes = []
        else:
            target = {}
            status = "unmatched"
            target_key = ""
            changes = []
        if status == "unmatched":
            classification = "unmatched"
        elif status == "choice_required" or any(change["conflict"] for change in changes):
            classification = "conflict"
        elif changes:
            classification = "supplement"
        else:
            classification = "no_change"
        preview_rows.append(
            {
                "source_row": normalized_row.get("source_row"),
                "match_status": status,
                "classification": classification,
                "target_stable_line_key": target_key,
                "candidates": [_candidate_view(item) for item in candidates],
                "changes": changes,
                "incoming": {
                    fieldname: normalized_row.get(fieldname)
                    for fieldname in MATERIAL_SOURCE_FIELDS
                    if normalized_row.get(fieldname) not in (None, "")
                },
            }
        )

    result = {
        "source": dict(source or {}),
        "rows": preview_rows,
        "summary": {
            "matched": sum(row["match_status"] == "matched" for row in preview_rows),
            "choice_required": sum(row["match_status"] == "choice_required" for row in preview_rows),
            "unmatched": sum(row["match_status"] == "unmatched" for row in preview_rows),
            "changed_fields": sum(len(row["changes"]) for row in preview_rows),
            "supplement": sum(row["classification"] == "supplement" for row in preview_rows),
            "conflict": sum(row["classification"] == "conflict" for row in preview_rows),
            "no_change": sum(row["classification"] == "no_change" for row in preview_rows),
        },
    }
    result["preview_hash"] = _canonical_hash(result)
    return result


def _signing_key() -> bytes:
    return packing_source_service._revision_signing_key()


def encode_material_preview_revision(claims: dict, *, signing_key: Optional[bytes] = None) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(signing_key or _signing_key(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def decode_material_preview_revision(value: str, *, signing_key: Optional[bytes] = None) -> dict:
    try:
        encoded, signature = str(value or "").rsplit(".", 1)
        expected = hmac.new(signing_key or _signing_key(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return {}
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        claims = json.loads(payload.decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _source_kind(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in SOURCE_KIND_ALIASES:
        raise ValueError("不支持的物料导入来源类型。")
    return SOURCE_KIND_ALIASES[normalized]


def _first_value(*values: object) -> object:
    return next((value for value in values if value not in (None, "")), "")


def _incoming_material_rows(preview: dict) -> list:
    rows = []
    for index, source_row in enumerate(preview.get("material_rows") or [], start=1):
        raw_fields = source_row.get("raw_fields") if isinstance(source_row.get("raw_fields"), dict) else {}
        combined = {**raw_fields, **source_row}
        row = {
            fieldname: combined.get(fieldname)
            for fieldname in MATERIAL_SOURCE_FIELDS
            if combined.get(fieldname) not in (None, "")
        }
        row.update(
            {
                "source_row": combined.get("source_row") or index,
                "source_line_no": _first_value(
                    combined.get("source_line_no"),
                    combined.get("purchase_source_row"),
                ),
                "source_doc_no": combined.get("source_doc_no") or "",
                "actual_shipped_qty": _first_value(
                    combined.get("actual_shipped_qty"),
                    combined.get("shipped_quantity"),
                    combined.get("quantity"),
                ),
                "shipped_uom": _first_value(combined.get("shipped_uom"), combined.get("unit")),
            }
        )
        if combined.get("purchase_quantity") not in (None, ""):
            row["quantity"] = combined.get("purchase_quantity")
        else:
            row.pop("quantity", None)
        rows.append({key: value for key, value in row.items() if value not in (None, "")})
    return rows


def _source_totals(preview: dict) -> dict:
    totals = preview.get("totals") if isinstance(preview.get("totals"), dict) else {}
    result = {}
    for fieldname in ("gross_weight_kg", "volume_m3", "net_weight_kg", "package_count"):
        value = totals.get(fieldname)
        if isinstance(value, dict):
            value = value.get("value")
        if value not in (None, ""):
            result[fieldname] = value
    return result


def _resolve_trusted_material_source(
    resolver: Optional[Callable[..., dict]],
    **kwargs,
) -> dict:
    if resolver is not None:
        return resolver(**kwargs)
    return packing_source_service.resolve_trusted_packing_source(
        **kwargs,
        strict_material_xlsx=True,
    )


class FrappeMaterialImportRepository:
    """Small persistence adapter; pure comparison logic stays outside Frappe."""

    def get_context(self, batch_name: str) -> dict:
        if frappe is None:
            raise RuntimeError("当前未连接 Frappe。")
        from overseas_costing.services import batch_service

        resolved_batch = batch_service._resolve_batch_name(batch_name)
        if not resolved_batch:
            raise ValueError(f"未找到批次：{batch_name}")
        batch = frappe.db.get_value(
            "Overseas Cost Batch",
            resolved_batch,
            ["name", "current_version", "modified"],
            as_dict=True,
        ) or {}
        version_name = str(batch.get("current_version") or "")
        version = frappe.db.get_value(
            "Overseas Cost Version",
            version_name,
            ["name", "batch", "modified"],
            as_dict=True,
        ) or {}
        if not version_name or str(version.get("batch") or "") != str(batch.get("name") or ""):
            raise ValueError("当前批次没有有效的当前版本。")
        return {
            "batch": str(batch.get("name") or ""),
            "version": version_name,
            "batch_modified": str(batch.get("modified") or ""),
            "version_modified": str(version.get("modified") or ""),
        }

    def get_items(self, batch_name: str, version_name: str) -> list:
        fields = list(
            dict.fromkeys(
                ["name", "row_no", "excel_row_no", "stable_line_key", "source_doc_no"]
                + list(MATERIAL_SOURCE_FIELDS)
                + ["actual_shipped_qty_mode", "actual_shipped_qty_source_revision"]
            )
        )
        return frappe.get_all(
            "Overseas Cost Item",
            filters={"batch": batch_name, "version": version_name},
            fields=fields,
            order_by="row_no asc, name asc",
            limit_page_length=10000,
        )

    def assert_write(self, batch_name: str, edit_token: str, expected_modified: str) -> None:
        from overseas_costing.services import edit_session_service

        edit_session_service.assert_batch_write(
            batch_name,
            edit_token=edit_token,
            expected_modified=expected_modified,
        )

    def lock(self, batch_name: str, version_name: str) -> None:
        sql = getattr(getattr(frappe, "db", None), "sql", None)
        if not callable(sql):
            return
        sql(
            "SELECT name FROM `tabOverseas Cost Version` WHERE name=%s AND batch=%s FOR UPDATE",
            (version_name, batch_name),
        )
        sql(
            "SELECT name FROM `tabOverseas Cost Item` WHERE batch=%s AND version=%s ORDER BY name FOR UPDATE",
            (batch_name, version_name),
        )

    def update_item(self, item_name: str, updates: dict, audit_context: dict) -> None:
        from overseas_costing.services import import_service

        import_service._update_item_fields(
            item_name=item_name,
            batch_doc_name=audit_context["batch"],
            version_name=audit_context["version"],
            row_no=audit_context.get("row_no"),
            field_updates=updates,
            action_remark=audit_context["remark"],
        )

    def mark_dirty(self, batch_name: str) -> None:
        frappe.db.set_value("Overseas Cost Batch", batch_name, "status", "Dirty", update_modified=True)

    def commit(self) -> None:
        frappe.db.commit()

    def rollback(self) -> None:
        frappe.db.rollback()


def preview_material_import(
    batch_name: str,
    source_kind: str,
    source_id: str,
    sheet_name: Optional[str] = None,
    *,
    repository=None,
    resolver: Optional[Callable[..., dict]] = None,
    signing_key: Optional[bytes] = None,
) -> dict:
    repo = repository or FrappeMaterialImportRepository()
    context = repo.get_context(str(batch_name))
    kind = _source_kind(source_kind)
    trusted = _resolve_trusted_material_source(
        resolver,
        batch_name=context["batch"],
        source_kind=kind,
        source_id=str(source_id),
        sheet_name=sheet_name,
    )
    source_hash = str(trusted.get("source_hash") or "")
    if len(source_hash) != 64:
        raise ValueError("可信物料来源缺少 SHA-256。")
    source = dict(trusted.get("source") or {})
    selected_sheet = str(source.get("sheet_name") or sheet_name or "")
    comparison = build_material_import_preview(
        repo.get_items(context["batch"], context["version"]),
        _incoming_material_rows(trusted.get("preview") or {}),
        {
            "kind": kind,
            "id": str(source.get("source_id") or source_id),
            "label": str(source.get("source_label") or source_id),
            "source_hash": source_hash,
            "sheet": selected_sheet,
        },
    )
    claims = {
        "batch": context["batch"],
        "version": context["version"],
        "batch_modified": context["batch_modified"],
        "version_modified": context["version_modified"],
        "kind": kind,
        "id": str(source.get("source_id") or source_id),
        "source_hash": source_hash,
        "sheet": selected_sheet,
        "preview_hash": comparison["preview_hash"],
    }
    comparison.update(
        {
            "ok": True,
            "batch_name": context["batch"],
            "version_name": context["version"],
            "preview_revision": encode_material_preview_revision(claims, signing_key=signing_key),
            "sheet": {
                "selected": selected_sheet,
                "available": list(source.get("available_sheets") or []),
            },
            "mapping": [
                {"source": fieldname, "target": fieldname, "confidence": "parser"}
                for fieldname in MATERIAL_IMPORT_FIELDS
                if any(fieldname in row.get("incoming", {}) for row in comparison["rows"])
            ],
            "source_totals": _source_totals(trusted.get("preview") or {}),
        }
    )
    return comparison


def _choices(value: object) -> dict:
    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            raise ValueError("物料导入选择不是有效 JSON。")
    if not isinstance(payload, dict):
        raise ValueError("物料导入选择必须是对象。")
    return payload


def _decision(choices: dict, source_row: object, fieldname: str) -> str:
    fields = choices.get("fields") if isinstance(choices.get("fields"), dict) else {}
    row_choices = fields.get(str(source_row)) if isinstance(fields.get(str(source_row)), dict) else {}
    return str(row_choices.get(fieldname) or "")


def _selected_key(choices: dict, source_row: object) -> str:
    matches = choices.get("matches") if isinstance(choices.get("matches"), dict) else {}
    return str(matches.get(str(source_row)) or "").strip()


def apply_material_import(
    batch_name: str,
    preview_revision: str,
    choices_json: object,
    edit_token: str,
    expected_modified: str,
    *,
    repository=None,
    resolver: Optional[Callable[..., dict]] = None,
    signing_key: Optional[bytes] = None,
) -> dict:
    repo = repository or FrappeMaterialImportRepository()
    claims = decode_material_preview_revision(preview_revision, signing_key=signing_key)
    if not claims or str(claims.get("batch") or "") != str(batch_name):
        return {"ok": False, "source_changed": True, "code": "INVALID_PREVIEW_REVISION"}
    choices = _choices(choices_json)
    repo.assert_write(str(batch_name), str(edit_token or ""), str(expected_modified or ""))
    repo.lock(str(batch_name), str(claims.get("version") or ""))
    try:
        context = repo.get_context(str(batch_name))
        if any(
            str(context.get(key) or "") != str(claims.get(key) or "")
            for key in ("batch", "version", "batch_modified", "version_modified")
        ):
            repo.rollback()
            return {"ok": False, "source_changed": True, "code": "BATCH_VERSION_CHANGED"}
        trusted = _resolve_trusted_material_source(
            resolver,
            batch_name=context["batch"],
            source_kind=str(claims.get("kind") or ""),
            source_id=str(claims.get("id") or ""),
            sheet_name=str(claims.get("sheet") or "") or None,
        )
        if str(trusted.get("source_hash") or "") != str(claims.get("source_hash") or ""):
            repo.rollback()
            return {"ok": False, "source_changed": True, "code": "SOURCE_CHANGED"}

        existing = repo.get_items(context["batch"], context["version"])
        source = dict(trusted.get("source") or {})
        comparison = build_material_import_preview(
            existing,
            _incoming_material_rows(trusted.get("preview") or {}),
            {
                "kind": claims.get("kind"),
                "id": str(source.get("source_id") or claims.get("id") or ""),
                "label": str(source.get("source_label") or claims.get("id") or ""),
                "source_hash": claims.get("source_hash"),
                "sheet": str(source.get("sheet_name") or claims.get("sheet") or ""),
            },
        )
        if comparison["preview_hash"] != str(claims.get("preview_hash") or ""):
            repo.rollback()
            return {"ok": False, "source_changed": True, "code": "PREVIEW_CHANGED"}

        by_key = {_stable_item_key(item): item for item in existing}
        pending_updates = []
        for row in comparison["rows"]:
            source_row = row["source_row"]
            target_key = str(row.get("target_stable_line_key") or "")
            if row["match_status"] == "choice_required":
                target_key = _selected_key(choices, source_row)
                candidate_keys = {str(candidate.get("stable_line_key") or "") for candidate in row["candidates"]}
                if not target_key or target_key not in candidate_keys:
                    repo.rollback()
                    return {"ok": False, "code": "LINE_CHOICE_REQUIRED", "source_row": source_row}
            if row["match_status"] == "unmatched":
                continue
            target = by_key.get(target_key)
            if not target:
                repo.rollback()
                return {"ok": False, "source_changed": True, "code": "TARGET_LINE_CHANGED"}
            updates = {}
            for change in build_field_changes(target, row["incoming"]):
                if change["conflict"]:
                    decision = _decision(choices, source_row, change["field"])
                    if decision not in {"use_source", "keep_current"}:
                        repo.rollback()
                        return {
                            "ok": False,
                            "code": "CONFLICT_DECISION_REQUIRED",
                            "source_row": source_row,
                            "field": change["field"],
                        }
                    if decision == "keep_current":
                        continue
                updates[change["field"]] = change["new"]
            if "actual_shipped_qty" in updates:
                updates["actual_shipped_qty_mode"] = "EXPLICIT_SOURCE"
                updates["actual_shipped_qty_source_revision"] = str(claims["source_hash"])
            if updates:
                pending_updates.append((target, updates, source_row))

        for target, updates, source_row in pending_updates:
            repo.update_item(
                str(target.get("name") or ""),
                updates,
                {
                    "batch": context["batch"],
                    "version": context["version"],
                    "row_no": target.get("row_no"),
                    "remark": f"确认采用物料来源 {claims.get('id')} 第 {source_row} 行",
                },
            )
        if pending_updates:
            repo.mark_dirty(context["batch"])
            repo.commit()
        else:
            repo.rollback()
        return {
            "ok": True,
            "updated_count": len(pending_updates),
            "changed_field_count": sum(len(updates) for _target, updates, _row in pending_updates),
            "batch_name": context["batch"],
            "version_name": context["version"],
        }
    except Exception:
        repo.rollback()
        raise
