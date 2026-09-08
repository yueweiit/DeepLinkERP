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
    "net_weight_kg",
    "gross_weight_kg",
    "volume_m3",
    "volume_weight_kg",
    "chargeable_weight_kg",
    "project_collection",
)
MATERIAL_SOURCE_FIELDS = MATERIAL_PURCHASE_FACT_FIELDS + MATERIAL_IMPORT_FIELDS
POSITIVE_SUPPLEMENT_FIELDS = frozenset(
    {
        "actual_shipped_qty",
        "net_weight_kg",
        "gross_weight_kg",
        "volume_m3",
        "volume_weight_kg",
        "chargeable_weight_kg",
    }
)

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
        if fieldname in POSITIVE_SUPPLEMENT_FIELDS:
            try:
                if Decimal(str(new_value)) <= 0:
                    continue
            except (InvalidOperation, TypeError, ValueError):
                continue
        old_value = existing.get(fieldname)
        if _equal(old_value, new_value):
            continue
        changes.append(
            {
                "field": fieldname,
                "old": old_value,
                "new": new_value,
                "conflict": (
                    old_value not in (None, "")
                    and not (
                        fieldname in POSITIVE_SUPPLEMENT_FIELDS
                        and _equal(old_value, 0)
                    )
                ),
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
    source_doc_no = _normalized(incoming.get("source_doc_no"))
    source_line_no = _normalized(
        incoming.get("source_line_no")
        or incoming.get("purchase_source_row")
        or incoming.get("source_excel_row_no")
    )
    if not source_doc_no or not source_line_no:
        return []
    candidates = [
        item for item in existing
        if _normalized(item.get("material_code")) == material_code
    ]
    source_matches = [
        item for item in candidates
        if _normalized(item.get("source_doc_no")) == source_doc_no
    ]
    if not source_matches:
        return []
    line_matches = [
        item
        for item in source_matches
        if _normalized(item.get("excel_row_no") or item.get("source_line_no")) == source_line_no
    ]
    return line_matches


def _match_wiki_candidates(existing: list, incoming: dict) -> list:
    """Match a knowledge-base row without inventing missing purchase-line identity."""

    trusted_target_key = str(incoming.get("_target_stable_line_key") or "").strip()
    if trusted_target_key:
        return [
            item for item in existing
            if _stable_item_key(item) == trusted_target_key
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
        candidates = [
            item for item in candidates
            if _normalized(item.get("source_doc_no")) == source_doc_no
        ]
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
        candidates = (
            _match_wiki_candidates(existing or [], normalized_row)
            if str((source or {}).get("kind") or "") == "wiki_sheet"
            else _match_candidates(existing or [], normalized_row)
        )
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


def _positive_decimal(value: object) -> Optional[Decimal]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _decimal_precision(value: object) -> int:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return 0
    return max(0, -number.as_tuple().exponent)


def _wiki_group_metrics(group: dict, *, allow_uncertain: bool = False) -> dict:
    metrics = {}
    for fieldname in ("net_weight_kg", "gross_weight_kg", "volume_m3"):
        raw = group.get(fieldname) if isinstance(group.get(fieldname), dict) else {}
        value = raw.get("value")
        if _positive_decimal(value) is None or (raw.get("count_once") is not True and not allow_uncertain):
            continue
        metrics[fieldname] = {
            "value": _decimal_text(Decimal(str(value))),
            "precision": _decimal_precision(value),
        }
    return metrics


def _wiki_source_key(row: dict) -> str:
    return f"{_normalized(row.get('source_doc_no'))}|{_normalized(row.get('material_code'))}"


def build_wiki_material_projection(existing: list, parsed_preview: dict) -> dict:
    """Aggregate trusted Sheet rows into batch-scoped material candidates."""

    source_rows = [dict(row or {}) for row in (parsed_preview or {}).get("material_rows") or []]
    row_by_number = {
        int(row["source_row"]): row
        for row in source_rows
        if str(row.get("source_row") or "").isdigit()
    }
    in_batch_rows = []
    out_of_batch = []
    for row in source_rows:
        candidates = _match_wiki_candidates(existing or [], row)
        if candidates:
            in_batch_rows.append(row)
        else:
            out_of_batch.append(
                {
                    "source_row": row.get("source_row"),
                    "material_code": str(row.get("material_code") or ""),
                    "source_doc_no": str(row.get("source_doc_no") or ""),
                    "quantity": row.get("quantity"),
                }
            )

    def aggregate_key(row: dict) -> tuple[str, str]:
        material_code = _normalized(row.get("material_code"))
        source_doc_no = _normalized(row.get("source_doc_no"))
        if not source_doc_no:
            candidates = _match_wiki_candidates(existing or [], row)
            if len(candidates) == 1:
                source_doc_no = _normalized(candidates[0].get("source_doc_no"))
        return (source_doc_no, material_code)

    grouped_rows: dict[tuple[str, str], list[dict]] = {}
    for row in in_batch_rows:
        grouped_rows.setdefault(aggregate_key(row), []).append(row)

    groups = [dict(group or {}) for group in (parsed_preview or {}).get("groups") or []]
    groups_by_row: dict[int, list[dict]] = {}
    for group in groups:
        for row_number in group.get("row_numbers") or []:
            groups_by_row.setdefault(int(row_number), []).append(group)

    out_of_batch_groups = []
    for group in groups:
        if not bool(group.get("needs_confirmation")):
            continue
        group_rows = [
            row_by_number.get(int(row_number))
            for row_number in group.get("row_numbers") or []
        ]
        group_rows = [row for row in group_rows if row]
        if not group_rows or any(_match_wiki_candidates(existing or [], row) for row in group_rows):
            continue
        group_id = str(group.get("group_id") or "")
        out_of_batch_groups.append(
            {
                "group_id": group_id,
                "row_numbers": list(group.get("row_numbers") or []),
                "material_codes": sorted(
                    {
                        str(row.get("material_code") or "")
                        for row in group_rows
                        if str(row.get("material_code") or "")
                    }
                ),
                "metrics": _wiki_group_metrics(group, allow_uncertain=True),
                "reason": str(
                    group.get("suggestion_reason")
                    or "相邻行的箱级字段为空，疑似共享上方包装数据。"
                ),
            }
        )

    candidate_group_by_row: dict[int, list[dict]] = {}
    for group in out_of_batch_groups:
        for row_number in group.get("row_numbers") or []:
            candidate_group_by_row.setdefault(int(row_number), []).append(group)
    for row in out_of_batch:
        source_row = row.get("source_row")
        row_groups = (
            candidate_group_by_row.get(int(source_row), [])
            if str(source_row or "").isdigit()
            else []
        )
        if row_groups:
            row["source_group_ids"] = [group["group_id"] for group in row_groups]
            row["candidate_merge"] = True

    shared_groups = []
    shared_group_ids = set()
    confirmation_groups = []
    confirmation_group_ids = set()
    group_metrics_by_id: dict[str, dict] = {}
    for group in groups:
        participants = []
        seen_keys = set()
        for row_number in group.get("row_numbers") or []:
            source_row = row_by_number.get(int(row_number))
            if not source_row:
                continue
            key = aggregate_key(source_row)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            participants.append(
                {
                    "source_key": f"{key[0]}|{key[1]}",
                    "source_doc_no": str(source_row.get("source_doc_no") or ""),
                    "material_code": str(source_row.get("material_code") or ""),
                    "in_batch": bool(_match_wiki_candidates(existing or [], source_row)),
                }
            )
        candidate_metrics = _wiki_group_metrics(group, allow_uncertain=True)
        if (
            participants
            and any(participant["in_batch"] for participant in participants)
            and bool(group.get("needs_confirmation"))
        ):
            group_id = str(group.get("group_id") or "")
            confirmation_group_ids.add(group_id)
            group_metrics_by_id[group_id] = candidate_metrics
            confirmation_groups.append(
                {
                    "group_id": group_id,
                    "row_numbers": list(group.get("row_numbers") or []),
                    "material_codes": [
                        participant["material_code"] for participant in participants
                    ],
                    "metrics": candidate_metrics,
                    "reason": str(
                        group.get("suggestion_reason")
                        or "相邻行的箱级字段为空，疑似共享上方包装数据。"
                    ),
                }
            )
        if len(participants) <= 1:
            continue
        if not any(row["in_batch"] for row in participants):
            continue
        group_id = str(group.get("group_id") or "")
        metrics = _wiki_group_metrics(
            group,
            allow_uncertain=bool(group.get("needs_confirmation")),
        )
        group_metrics_by_id[group_id] = metrics
        shared_group_ids.add(group_id)
        shared_groups.append(
            {
                "group_id": group_id,
                "row_numbers": list(group.get("row_numbers") or []),
                "participants": participants,
                "metrics": metrics,
                "needs_confirmation": bool(group.get("needs_confirmation")),
                "reason": str(group.get("suggestion_reason") or ""),
                "allocation_required": len(metrics) == 3,
            }
        )

    incoming = []
    for key, rows in grouped_rows.items():
        rows = sorted(rows, key=lambda row: int(row.get("source_row") or 0))
        row_numbers = [int(row.get("source_row") or 0) for row in rows]
        source_groups = []
        seen_group_ids = set()
        for row_number in row_numbers:
            for group in groups_by_row.get(row_number, []):
                group_id = str(group.get("group_id") or "")
                if group_id not in seen_group_ids:
                    source_groups.append(group)
                    seen_group_ids.add(group_id)

        result = {
            "source_row": ",".join(str(value) for value in row_numbers),
            "source_rows": row_numbers,
            "source_group_ids": [str(group.get("group_id") or "") for group in source_groups],
            "source_doc_no": str(
                next(
                    (
                        row.get("source_doc_no")
                        for row in rows
                        if str(row.get("source_doc_no") or "").strip()
                    ),
                    "",
                )
                or next(
                    (
                        item.get("source_doc_no")
                        for item in _match_wiki_candidates(existing or [], rows[0])
                        if _normalized(item.get("source_doc_no")) == key[0]
                    ),
                    "",
                )
                or ""
            ),
            "material_code": str(rows[0].get("material_code") or ""),
        }
        quantities = [_positive_decimal(row.get("quantity")) for row in rows]
        if quantities and all(value is not None for value in quantities):
            result["actual_shipped_qty"] = _decimal_text(sum(quantities, Decimal("0")))
        units = [str(row.get("unit") or "").strip() for row in rows if str(row.get("unit") or "").strip()]
        normalized_units = {_normalized(value) for value in units}
        if len(normalized_units) == 1:
            result["shipped_uom"] = units[0]
        elif len(normalized_units) > 1:
            result.setdefault("source_conflicts", []).append(
                {"field": "shipped_uom", "options": sorted(set(units))}
            )
        projects = [
            str(row.get("project_collection") or "").strip()
            for row in rows
            if str(row.get("project_collection") or "").strip()
        ]
        normalized_projects = {_normalized(value) for value in projects}
        if len(normalized_projects) == 1:
            result["project_collection"] = projects[0]
        elif len(normalized_projects) > 1:
            result.setdefault("source_conflicts", []).append(
                {"field": "project_collection", "options": sorted(set(projects))}
            )
        chargeable_values = [_positive_decimal(row.get("chargeable_weight_kg")) for row in rows]
        if chargeable_values and all(value is not None for value in chargeable_values):
            result["chargeable_weight_kg"] = _decimal_text(sum(chargeable_values, Decimal("0")))

        incomplete_rows = []
        allocation_required = False
        group_confirmation_required = False
        totals = {fieldname: Decimal("0") for fieldname in ("net_weight_kg", "gross_weight_kg", "volume_m3")}
        for row_number in row_numbers:
            if not groups_by_row.get(row_number):
                incomplete_rows.append(row_number)
        for group in source_groups:
            group_id = str(group.get("group_id") or "")
            metrics = group_metrics_by_id.get(group_id)
            if metrics is None:
                metrics = _wiki_group_metrics(group)
            relevant_rows = sorted(set(row_numbers).intersection(group.get("row_numbers") or []))
            if len(metrics) != 3:
                incomplete_rows.extend(relevant_rows)
                continue
            if group_id in shared_group_ids:
                allocation_required = True
                continue
            if group_id in confirmation_group_ids:
                group_confirmation_required = True
            for fieldname in totals:
                totals[fieldname] += Decimal(metrics[fieldname]["value"])
        if incomplete_rows:
            result["physical_status"] = "incomplete"
        elif allocation_required:
            result["base_physical_values"] = {
                fieldname: _decimal_text(value) for fieldname, value in totals.items()
            }
            result["physical_status"] = "allocation_required"
        elif group_confirmation_required:
            result["base_physical_values"] = {
                fieldname: _decimal_text(value) for fieldname, value in totals.items()
            }
            result["physical_status"] = "group_confirmation_required"
        else:
            result.update({fieldname: _decimal_text(value) for fieldname, value in totals.items()})
            result["physical_status"] = "complete"
        result["physical_missing_rows"] = sorted(set(incomplete_rows))
        incoming.append(result)

    return {
        "incoming": incoming,
        "shared_groups": shared_groups,
        "confirmation_groups": confirmation_groups,
        "out_of_batch": out_of_batch,
        "out_of_batch_groups": out_of_batch_groups,
    }


def _allocation_decimal(value: object) -> Optional[Decimal]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def apply_wiki_group_allocations(projection: dict, choices: dict) -> tuple[list, Optional[dict]]:
    """Validate exact shared-package totals and add allocations to projected SKU rows."""

    group_confirmations = (
        choices.get("group_confirmations")
        if isinstance(choices.get("group_confirmations"), dict)
        else {}
    )
    required_confirmation_ids = {
        str(group.get("group_id") or "")
        for group in projection.get("confirmation_groups") or []
    }
    missing_confirmations = sorted(
        group_id
        for group_id in required_confirmation_ids
        if group_confirmations.get(group_id) is not True
    )
    if missing_confirmations:
        return [], {
            "ok": False,
            "code": "GROUP_CONFIRMATION_REQUIRED",
            "group_id": missing_confirmations[0],
        }

    allocations = choices.get("allocations") if isinstance(choices.get("allocations"), dict) else {}
    allocated_by_source: dict[str, dict[str, Decimal]] = {}
    groups_by_source: dict[str, set[str]] = {}
    for group in projection.get("shared_groups") or []:
        if group.get("allocation_required") is False:
            continue
        group_id = str(group.get("group_id") or "")
        group_values = allocations.get(group_id) if isinstance(allocations.get(group_id), dict) else {}
        participants = list(group.get("participants") or [])
        for fieldname, metric in (group.get("metrics") or {}).items():
            source_value = _allocation_decimal(metric.get("value"))
            if source_value is None:
                continue
            participant_values = []
            for participant in participants:
                source_key = str(participant.get("source_key") or "")
                values = group_values.get(source_key) if isinstance(group_values.get(source_key), dict) else {}
                allocated = _allocation_decimal(values.get(fieldname))
                if allocated is None:
                    return [], {
                        "ok": False,
                        "code": "ALLOCATION_REQUIRED",
                        "group_id": group_id,
                        "field": fieldname,
                        "source_key": source_key,
                    }
                participant_values.append(allocated)
                if participant.get("in_batch"):
                    allocated_by_source.setdefault(source_key, {}).setdefault(fieldname, Decimal("0"))
                    allocated_by_source[source_key][fieldname] += allocated
                    groups_by_source.setdefault(source_key, set()).add(group_id)
            precision = max(0, int(metric.get("precision") or 0))
            quantum = Decimal("1").scaleb(-precision)
            if sum(participant_values, Decimal("0")).quantize(quantum) != source_value.quantize(quantum):
                return [], {
                    "ok": False,
                    "code": "ALLOCATION_TOTAL_MISMATCH",
                    "group_id": group_id,
                    "field": fieldname,
                    "expected": _decimal_text(source_value),
                    "actual": _decimal_text(sum(participant_values, Decimal("0"))),
                }

    resolved_rows = []
    source_field_choices = (
        choices.get("source_fields")
        if isinstance(choices.get("source_fields"), dict)
        else {}
    )
    for original in projection.get("incoming") or []:
        row = dict(original)
        if row.get("physical_status") == "allocation_required":
            source_key = _wiki_source_key(row)
            assigned = allocated_by_source.get(source_key) or {}
            base = row.get("base_physical_values") if isinstance(row.get("base_physical_values"), dict) else {}
            for fieldname in ("net_weight_kg", "gross_weight_kg", "volume_m3"):
                row[fieldname] = _decimal_text(
                    Decimal(str(base.get(fieldname) or 0)) + assigned.get(fieldname, Decimal("0"))
                )
            row["physical_status"] = "complete"
            row["allocated_group_ids"] = sorted(groups_by_source.get(source_key) or [])
        elif row.get("physical_status") == "group_confirmation_required":
            row_group_ids = set(row.get("source_group_ids") or []).intersection(required_confirmation_ids)
            missing = sorted(group_id for group_id in row_group_ids if group_confirmations.get(group_id) is not True)
            if missing:
                return [], {
                    "ok": False,
                    "code": "GROUP_CONFIRMATION_REQUIRED",
                    "group_id": missing[0],
                }
            base = row.get("base_physical_values") if isinstance(row.get("base_physical_values"), dict) else {}
            for fieldname in ("net_weight_kg", "gross_weight_kg", "volume_m3"):
                row[fieldname] = str(base.get(fieldname) or "")
            row["physical_status"] = "complete"
            row["confirmed_group_ids"] = sorted(row_group_ids)
        row_choices = (
            source_field_choices.get(str(row.get("source_row")))
            if isinstance(source_field_choices.get(str(row.get("source_row"))), dict)
            else {}
        )
        for conflict in row.get("source_conflicts") or []:
            fieldname = str(conflict.get("field") or "")
            options = [str(value) for value in conflict.get("options") or []]
            selected = str(row_choices.get(fieldname) or "").strip()
            canonical = next((value for value in options if _normalized(value) == _normalized(selected)), "")
            if not canonical:
                return [], {
                    "ok": False,
                    "code": "SOURCE_FIELD_CHOICE_REQUIRED",
                    "source_row": row.get("source_row"),
                    "field": fieldname,
                    "options": options,
                }
            row[fieldname] = canonical
        if row.get("source_conflicts"):
            row.pop("source_conflicts", None)
        resolved_rows.append(row)
    return resolved_rows, None


def merge_wiki_rows_for_selected_targets(
    existing: list,
    rows: list,
    choices: dict,
) -> tuple[list, Optional[dict]]:
    """Merge projected Sheet rows that the user maps to the same purchase line."""

    grouped: dict[str, list[dict]] = {}
    target_by_key: dict[str, dict] = {}
    for original in rows or []:
        row = dict(original or {})
        candidates = _match_wiki_candidates(existing or [], row)
        if not candidates:
            continue
        selected_by_choice = False
        if len(candidates) == 1:
            target = candidates[0]
        else:
            selected_by_choice = True
            selected_key = _selected_key(choices, row.get("source_row"))
            target = next(
                (
                    candidate
                    for candidate in candidates
                    if _stable_item_key(candidate) == selected_key
                ),
                None,
            )
            if target is None:
                return [], {
                    "ok": False,
                    "code": "LINE_CHOICE_REQUIRED",
                    "source_row": row.get("source_row"),
                }
        row["_target_selected_by_choice"] = selected_by_choice
        target_key = _stable_item_key(target)
        if not target_key:
            return [], {"ok": False, "source_changed": True, "code": "TARGET_LINE_CHANGED"}
        grouped.setdefault(target_key, []).append(row)
        target_by_key[target_key] = target

    merged_rows = []
    for target_key, target_rows in grouped.items():
        target = target_by_key[target_key]
        if len(target_rows) == 1:
            merged = dict(target_rows[0])
            merged["_target_stable_line_key"] = target_key
            merged["choice_source_rows"] = [str(merged.get("source_row"))]
            merged["_merged_from_multiple_rows"] = False
            merged_rows.append(merged)
            continue

        source_numbers = sorted(
            {
                int(value)
                for row in target_rows
                for value in (row.get("source_rows") or [])
                if str(value).isdigit()
            }
        )
        choice_source_rows = [str(row.get("source_row")) for row in target_rows]
        merged = {
            "_target_stable_line_key": target_key,
            "_merged_from_multiple_rows": True,
            "_target_selected_by_choice": any(
                bool(row.get("_target_selected_by_choice")) for row in target_rows
            ),
            "choice_source_rows": choice_source_rows,
            "source_row": ",".join(str(value) for value in source_numbers)
            or ",".join(choice_source_rows),
            "source_rows": source_numbers,
            "source_doc_no": str(target.get("source_doc_no") or ""),
            "material_code": str(target.get("material_code") or target_rows[0].get("material_code") or ""),
            "source_group_ids": sorted(
                {
                    str(value)
                    for row in target_rows
                    for value in (row.get("source_group_ids") or [])
                    if str(value)
                }
            ),
            "allocated_group_ids": sorted(
                {
                    str(value)
                    for row in target_rows
                    for value in (row.get("allocated_group_ids") or [])
                    if str(value)
                }
            ),
            "confirmed_group_ids": sorted(
                {
                    str(value)
                    for row in target_rows
                    for value in (row.get("confirmed_group_ids") or [])
                    if str(value)
                }
            ),
            "physical_missing_rows": sorted(
                {
                    int(value)
                    for row in target_rows
                    for value in (row.get("physical_missing_rows") or [])
                    if str(value).isdigit()
                }
            ),
        }

        quantities = [_positive_decimal(row.get("actual_shipped_qty")) for row in target_rows]
        if quantities and all(value is not None for value in quantities):
            merged["actual_shipped_qty"] = _decimal_text(sum(quantities, Decimal("0")))

        for fieldname in ("shipped_uom", "project_collection"):
            values = [
                str(row.get(fieldname) or "").strip()
                for row in target_rows
                if str(row.get(fieldname) or "").strip()
            ]
            canonical = {_normalized(value) for value in values}
            if len(canonical) > 1:
                merged.setdefault("source_conflicts", []).append(
                    {
                        "field": fieldname,
                        "options": sorted(set(values)),
                        "current": target.get(fieldname),
                    }
                )
            if values:
                if len(canonical) == 1:
                    merged[fieldname] = values[0]

        chargeable_values = [
            _positive_decimal(row.get("chargeable_weight_kg")) for row in target_rows
        ]
        if chargeable_values and all(value is not None for value in chargeable_values):
            merged["chargeable_weight_kg"] = _decimal_text(
                sum(chargeable_values, Decimal("0"))
            )

        physical_fields = ("net_weight_kg", "gross_weight_kg", "volume_m3")
        physical_values = {
            fieldname: [_positive_decimal(row.get(fieldname)) for row in target_rows]
            for fieldname in physical_fields
        }
        physical_complete = all(
            row.get("physical_status") == "complete" for row in target_rows
        ) and all(
            values and all(value is not None for value in values)
            for values in physical_values.values()
        )
        if physical_complete:
            for fieldname, values in physical_values.items():
                merged[fieldname] = _decimal_text(sum(values, Decimal("0")))
            merged["physical_status"] = "complete"
        else:
            merged["physical_status"] = "incomplete"
        merged_rows.append(merged)

    return merged_rows, None


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


SOURCE_VALIDATION_HANDLED_BY_ROW_RULES = frozenset(
    {
        "conflicting_merge_ranges",
        "group_confirmation_required",
        "unresolved_formula",
    }
)


def _source_validation(preview: dict) -> dict:
    validation = preview.get("validation") if isinstance(preview.get("validation"), dict) else {}

    def public_issue(item: object, *, blocking: bool) -> dict:
        source = item if isinstance(item, dict) else {}
        code = str(source.get("code") or ("source_blocker" if blocking else "source_warning"))[:100]
        fieldname = str(source.get("field") or "")[:100]
        key = f"{code}:{fieldname}" if fieldname else code
        return {
            "code": code,
            "field": fieldname,
            "message": str(source.get("message") or "装箱计划表存在需要核对的数据。")[:1000],
            "declared_value": source.get("declared_value"),
            "calculated_value": source.get("calculated_value"),
            "confirmation_key": key,
            "confirmation_required": bool(
                blocking and code not in SOURCE_VALIDATION_HANDLED_BY_ROW_RULES
            ),
        }

    return {
        "blocking": [public_issue(item, blocking=True) for item in validation.get("blocking") or []],
        "warnings": [public_issue(item, blocking=False) for item in validation.get("warnings") or []],
    }


def _source_validation_error(validation: dict, choices: dict) -> Optional[dict]:
    confirmations = (
        choices.get("source_validation")
        if isinstance(choices.get("source_validation"), dict)
        else {}
    )
    for issue in validation.get("blocking") or []:
        if not issue.get("confirmation_required"):
            continue
        key = str(issue.get("confirmation_key") or "")
        if confirmations.get(key) is not True:
            return {
                "ok": False,
                "code": "SOURCE_VALIDATION_CONFIRMATION_REQUIRED",
                "confirmation_key": key,
                "failure_code": issue.get("code"),
                "field": issue.get("field"),
                "message": issue.get("message"),
            }
    return None


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

    def record_import_audit(self, payload: dict) -> None:
        from overseas_costing.services import usage_service

        result = usage_service.record_usage(
            action_type="EXCEL_IMPORT",
            batch_name=str(payload.get("batch") or ""),
            version_name=str(payload.get("version") or ""),
            remark=(
                f"确认写入{'装箱计划表' if payload.get('source_kind') == 'wiki_sheet' else '物料 Excel'}"
                f"：{payload.get('sheet') or payload.get('source_id') or '--'}"
            ),
            extra=payload,
        )
        if not result.get("ok"):
            raise RuntimeError(
                str(result.get("message") or "物料来源审计记录写入失败。")
            )

    def commit(self) -> None:
        frappe.db.commit()

    def rollback(self) -> None:
        frappe.db.rollback()


def _build_trusted_comparison(existing: list, kind: str, trusted: dict, source: dict) -> dict:
    parsed_preview = trusted.get("preview") or {}
    projection = None
    if kind == "wiki_sheet":
        projection = build_wiki_material_projection(existing, parsed_preview)
        incoming = projection["incoming"]
    else:
        incoming = _incoming_material_rows(parsed_preview)

    comparison = build_material_import_preview(existing, incoming, source)
    if projection is not None:
        projected_by_row = {str(row.get("source_row")): row for row in projection["incoming"]}
        for row in comparison["rows"]:
            projected = projected_by_row.get(str(row.get("source_row"))) or {}
            row["source_rows"] = list(projected.get("source_rows") or [])
            row["source_group_ids"] = list(projected.get("source_group_ids") or [])
            row["physical_status"] = str(projected.get("physical_status") or "")
            row["physical_missing_rows"] = list(projected.get("physical_missing_rows") or [])
            row["base_physical_values"] = dict(projected.get("base_physical_values") or {})
            row["source_conflicts"] = list(projected.get("source_conflicts") or [])
        comparison["shared_groups"] = projection["shared_groups"]
        comparison["confirmation_groups"] = projection["confirmation_groups"]
        comparison["out_of_batch"] = projection["out_of_batch"]
        comparison["out_of_batch_groups"] = projection["out_of_batch_groups"]
        comparison["summary"]["shared_groups"] = len(projection["shared_groups"])
        comparison["summary"]["group_confirmation_required"] = len(projection["confirmation_groups"])
        comparison["summary"]["allocation_required"] = sum(
            row.get("physical_status") == "allocation_required" for row in projection["incoming"]
        )
        comparison["summary"]["physical_incomplete"] = sum(
            row.get("physical_status") == "incomplete" for row in projection["incoming"]
        )
        comparison["summary"]["out_of_batch"] = len(projection["out_of_batch"])
    comparison["source_validation"] = _source_validation(parsed_preview)
    if projection is not None and not (
        projection["confirmation_groups"] or projection["shared_groups"]
    ):
        comparison["source_validation"]["blocking"] = [
            issue
            for issue in comparison["source_validation"]["blocking"]
            if issue.get("code") != "group_confirmation_required"
        ]
    comparison["summary"]["source_blockers"] = len(comparison["source_validation"]["blocking"])
    comparison["summary"]["source_warnings"] = len(comparison["source_validation"]["warnings"])
    comparison["preview_hash"] = _canonical_hash(
        {key: value for key, value in comparison.items() if key != "preview_hash"}
    )
    return comparison


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
    source_descriptor = {
        "kind": kind,
        "id": str(source.get("source_id") or source_id),
        "label": str(source.get("source_label") or source_id),
        "source_hash": source_hash,
        "sheet": selected_sheet,
        "source_updated_at": source.get("source_updated_at"),
    }
    comparison = _build_trusted_comparison(
        repo.get_items(context["batch"], context["version"]),
        kind,
        trusted,
        source_descriptor,
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
        comparison = _build_trusted_comparison(
            existing,
            str(claims.get("kind") or ""),
            trusted,
            {
                "kind": claims.get("kind"),
                "id": str(source.get("source_id") or claims.get("id") or ""),
                "label": str(source.get("source_label") or claims.get("id") or ""),
                "source_hash": claims.get("source_hash"),
                "sheet": str(source.get("sheet_name") or claims.get("sheet") or ""),
                "source_updated_at": source.get("source_updated_at"),
            },
        )
        if comparison["preview_hash"] != str(claims.get("preview_hash") or ""):
            repo.rollback()
            return {"ok": False, "source_changed": True, "code": "PREVIEW_CHANGED"}
        source_validation_error = (
            _source_validation_error(
                comparison.get("source_validation") or {},
                choices,
            )
            if str(claims.get("kind") or "") == "wiki_sheet"
            else None
        )
        if source_validation_error:
            repo.rollback()
            return source_validation_error

        if str(claims.get("kind") or "") == "wiki_sheet":
            out_of_batch = list(comparison.get("out_of_batch") or [])
            projection = build_wiki_material_projection(existing, trusted.get("preview") or {})
            resolved_rows, allocation_error = apply_wiki_group_allocations(projection, choices)
            if allocation_error:
                repo.rollback()
                return allocation_error
            resolved_rows, merge_error = merge_wiki_rows_for_selected_targets(
                existing,
                resolved_rows,
                choices,
            )
            if merge_error:
                repo.rollback()
                return merge_error
            comparison = build_material_import_preview(
                existing,
                resolved_rows,
                {
                    "kind": claims.get("kind"),
                    "id": str(source.get("source_id") or claims.get("id") or ""),
                    "label": str(source.get("source_label") or claims.get("id") or ""),
                    "source_hash": claims.get("source_hash"),
                    "sheet": str(source.get("sheet_name") or claims.get("sheet") or ""),
                    "source_updated_at": source.get("source_updated_at"),
                },
            )
            resolved_by_row = {str(row.get("source_row")): row for row in resolved_rows}
            for row in comparison["rows"]:
                resolved = resolved_by_row.get(str(row.get("source_row"))) or {}
                row["source_rows"] = list(resolved.get("source_rows") or [])
                row["source_group_ids"] = list(resolved.get("source_group_ids") or [])
                row["allocated_group_ids"] = list(resolved.get("allocated_group_ids") or [])
                row["confirmed_group_ids"] = list(resolved.get("confirmed_group_ids") or [])
                row["choice_source_rows"] = list(resolved.get("choice_source_rows") or [])
                row["physical_status"] = str(resolved.get("physical_status") or "")
                row["physical_missing_rows"] = list(resolved.get("physical_missing_rows") or [])
                row["source_conflicts"] = list(resolved.get("source_conflicts") or [])
                row["merged_from_multiple_rows"] = bool(
                    resolved.get("_merged_from_multiple_rows")
                )
                row["target_selected_by_choice"] = bool(
                    resolved.get("_target_selected_by_choice")
                )
                if row["source_conflicts"]:
                    row["classification"] = "conflict"
            comparison["summary"]["conflict"] = sum(
                row.get("classification") == "conflict" for row in comparison["rows"]
            )
            comparison["summary"]["physical_incomplete"] = sum(
                row.get("physical_status") == "incomplete" for row in comparison["rows"]
            )
            comparison["out_of_batch"] = out_of_batch
            comparison["summary"]["out_of_batch"] = len(out_of_batch)
            comparison["is_merged_preview"] = True
            comparison["preview_hash"] = _canonical_hash(
                {key: value for key, value in comparison.items() if key != "preview_hash"}
            )
            requires_merged_confirmation = any(
                row.get("merged_from_multiple_rows")
                or row.get("target_selected_by_choice")
                for row in comparison["rows"]
            )
            if (
                requires_merged_confirmation
                and str(choices.get("merged_preview_hash") or "")
                != comparison["preview_hash"]
            ):
                repo.rollback()
                return {
                    "ok": False,
                    "code": "MERGED_PREVIEW_CONFIRMATION_REQUIRED",
                    "merged_preview_hash": comparison["preview_hash"],
                    "merged_preview": comparison,
                }

        by_key = {_stable_item_key(item): item for item in existing}
        pending_updates = []
        selected_targets: dict[str, object] = {}
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
            if target_key in selected_targets:
                repo.rollback()
                return {
                    "ok": False,
                    "code": "DUPLICATE_TARGET_SELECTION",
                    "source_row": source_row,
                    "previous_source_row": selected_targets[target_key],
                }
            selected_targets[target_key] = source_row
            incoming = dict(row["incoming"])
            merged_source_fields = (
                choices.get("merged_source_fields")
                if isinstance(choices.get("merged_source_fields"), dict)
                else {}
            )
            row_source_choices = (
                merged_source_fields.get(str(source_row))
                if isinstance(merged_source_fields.get(str(source_row)), dict)
                else {}
            )
            explicitly_selected_source_fields = set()
            for conflict in row.get("source_conflicts") or []:
                fieldname = str(conflict.get("field") or "")
                options = [str(value) for value in conflict.get("options") or []]
                selected = str(row_source_choices.get(fieldname) or "").strip()
                canonical = next(
                    (value for value in options if _normalized(value) == _normalized(selected)),
                    "",
                )
                if not canonical:
                    repo.rollback()
                    return {
                        "ok": False,
                        "code": "SOURCE_FIELD_CHOICE_REQUIRED",
                        "source_row": source_row,
                        "field": fieldname,
                        "options": options,
                    }
                incoming[fieldname] = canonical
                explicitly_selected_source_fields.add(fieldname)
            updates = {}
            for change in build_field_changes(target, incoming):
                if change["conflict"]:
                    decision = (
                        "use_source"
                        if change["field"] in explicitly_selected_source_fields
                        else _decision(choices, source_row, change["field"])
                    )
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
            preview_row = next(
                (row for row in comparison["rows"] if str(row.get("source_row")) == str(source_row)),
                {},
            )
            source_rows = ",".join(str(value) for value in preview_row.get("source_rows") or [source_row])
            source_groups = ",".join(
                str(value)
                for value in (preview_row.get("allocated_group_ids") or preview_row.get("source_group_ids") or [])
            )
            group_remark = f"；装箱组 {source_groups}" if source_groups else ""
            repo.update_item(
                str(target.get("name") or ""),
                updates,
                {
                    "batch": context["batch"],
                    "version": context["version"],
                    "row_no": target.get("row_no"),
                    "remark": f"确认采用物料来源 {claims.get('id')} 第 {source_rows} 行{group_remark}",
                },
            )
        if pending_updates:
            resolved_source_id = str(source.get("source_id") or claims.get("id") or "")
            workbook_id, separator, sheet_id = resolved_source_id.partition(":")
            audit_rows = sorted(
                {
                    int(value)
                    for row in comparison["rows"]
                    for value in (row.get("source_rows") or [])
                    if str(value).isdigit()
                }
            )
            audit_groups = sorted(
                {
                    str(value)
                    for row in comparison["rows"]
                    for value in (row.get("allocated_group_ids") or row.get("source_group_ids") or [])
                    if str(value)
                }
            )
            record_audit = getattr(repo, "record_import_audit", None)
            if callable(record_audit):
                record_audit(
                    {
                        "batch": context["batch"],
                        "version": context["version"],
                        "source_kind": str(claims.get("kind") or ""),
                        "source_id": resolved_source_id,
                        "workbook_id": workbook_id if separator else "",
                        "sheet_id": sheet_id if separator else "",
                        "sheet": str(source.get("sheet_name") or claims.get("sheet") or ""),
                        "source_hash": str(claims.get("source_hash") or ""),
                        "source_rows": audit_rows,
                        "source_groups": audit_groups,
                        "manual_choices": {
                            key: dict(choices.get(key) or {})
                            if isinstance(choices.get(key), dict)
                            else {}
                            for key in (
                                "matches",
                                "fields",
                                "source_fields",
                                "merged_source_fields",
                                "group_confirmations",
                                "allocations",
                                "source_validation",
                            )
                        },
                        "writes": [
                            {
                                "item_name": str(target.get("name") or ""),
                                "fields": sorted(updates),
                            }
                            for target, updates, _source_row in pending_updates
                        ],
                    }
                )
            repo.mark_dirty(context["batch"])
            repo.commit()
        else:
            repo.rollback()
        refreshed_context = repo.get_context(context["batch"])
        return {
            "ok": True,
            "updated_count": len(pending_updates),
            "changed_field_count": sum(len(updates) for _target, updates, _row in pending_updates),
            "batch_name": context["batch"],
            "version_name": context["version"],
            "batch_modified": refreshed_context.get("batch_modified") or context.get("batch_modified"),
        }
    except Exception:
        repo.rollback()
        raise
