"""ERP 供应商的唯一解析入口。

只有启用中的 Supplier 精确匹配才会返回可写入的规范名称；模糊结果
始终只是人工选择候选，不会自动创建或写入 ERP Supplier。
"""

from __future__ import annotations

import json
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

try:
    import frappe
except Exception:  # pragma: no cover - 纯单测可注入供应商列表
    frappe = None


MIN_CANDIDATE_SCORE = 0.72
HIGH_CONFIDENCE_SCORE = 0.90
HIGH_CONFIDENCE_MARGIN = 0.08
MAX_CANDIDATES = 5


def _value(record: Any, fieldname: str, default: Any = "") -> Any:
    if isinstance(record, dict):
        return record.get(fieldname, default)
    return getattr(record, fieldname, default)


def normalize_supplier_text(value: Any) -> str:
    """用于名称匹配的稳定规范化，不改写 ERP 中的原始名称。"""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(character for character in text if character.isalnum())


def _active_supplier_rows(suppliers: Iterable[Any]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for supplier in suppliers or []:
        if bool(int(_value(supplier, "disabled", 0) or 0)):
            continue
        name = str(_value(supplier, "name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(
            {
                "name": name,
                "supplier_name": str(_value(supplier, "supplier_name") or "").strip(),
            }
        )
    return rows


def load_active_suppliers() -> list[dict]:
    """从当前 ERP 读取启用 Supplier；无 Frappe 环境时返回空集。"""

    if frappe is None:
        return []
    return _active_supplier_rows(
        frappe.get_all(
            "Supplier",
            filters={"disabled": 0},
            fields=["name", "supplier_name", "disabled"],
            order_by="supplier_name asc, name asc",
            limit_page_length=0,
        )
    )


def _similarity(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    sequence_score = SequenceMatcher(None, query, candidate).ratio()
    if query in candidate or candidate in query:
        shorter, longer = min(len(query), len(candidate)), max(len(query), len(candidate))
        partial_score = MIN_CANDIDATE_SCORE + (1 - MIN_CANDIDATE_SCORE) * shorter / longer
        return max(sequence_score, partial_score)
    return sequence_score


def resolve_supplier_reference(raw_value: Any, *, suppliers: Iterable[Any] | None = None) -> dict:
    """解析原始供应商文本；只有 EXACT 会给出 ``canonical_supplier``。"""

    raw = str(raw_value or "").strip()
    result = {
        "raw_value": raw,
        "status": "EMPTY" if not raw else "UNRESOLVED",
        "canonical_supplier": "",
        "candidates": [],
    }
    if not raw:
        return result

    rows = _active_supplier_rows(load_active_suppliers() if suppliers is None else suppliers)
    normalized_raw = normalize_supplier_text(raw)
    name_matches = [
        supplier for supplier in rows
        if normalized_raw and normalize_supplier_text(supplier["name"]) == normalized_raw
    ]
    if len(name_matches) == 1:
        return {
            "raw_value": raw,
            "status": "EXACT",
            "canonical_supplier": name_matches[0]["name"],
            "candidates": [],
        }

    supplier_name_matches = [
        supplier for supplier in rows
        if normalized_raw
        and supplier["supplier_name"]
        and normalize_supplier_text(supplier["supplier_name"]) == normalized_raw
    ]
    exact_matches = name_matches or supplier_name_matches
    if len(exact_matches) == 1:
        return {
            "raw_value": raw,
            "status": "EXACT",
            "canonical_supplier": exact_matches[0]["name"],
            "candidates": [],
        }
    if len(exact_matches) > 1:
        return {
            "raw_value": raw,
            "status": "AMBIGUOUS",
            "canonical_supplier": "",
            "candidates": [
                {
                    "name": supplier["name"],
                    "supplier_name": supplier["supplier_name"],
                    "score": 1.0,
                    "high_confidence": False,
                }
                for supplier in sorted(exact_matches, key=lambda item: item["name"])
            ][:MAX_CANDIDATES],
        }

    scored: list[dict] = []
    for supplier in rows:
        score = max(
            (_similarity(normalized_raw, normalize_supplier_text(alias)) for alias in (
                supplier["name"], supplier["supplier_name"]
            ) if alias),
            default=0.0,
        )
        if score < MIN_CANDIDATE_SCORE:
            continue
        scored.append(
            {
                "name": supplier["name"],
                "supplier_name": supplier["supplier_name"],
                "score": round(score, 4),
                "high_confidence": False,
            }
        )
    scored.sort(key=lambda candidate: (-candidate["score"], candidate["supplier_name"], candidate["name"]))
    candidates = scored[:MAX_CANDIDATES]
    if candidates:
        runner_up_score = candidates[1]["score"] if len(candidates) > 1 else 0.0
        candidates[0]["high_confidence"] = bool(
            candidates[0]["score"] >= HIGH_CONFIDENCE_SCORE
            and candidates[0]["score"] - runner_up_score >= HIGH_CONFIDENCE_MARGIN
        )
        result["status"] = "SUGGESTED"
        result["candidates"] = candidates
    return result


def _metadata(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def supplier_provenance_state(item: dict) -> dict:
    """区分新模板缺供应商与旧模板默认供应商兼容场景。"""

    metadata = _metadata(item.get("extra_json"))
    supplier = str(item.get("supplier") or "").strip()
    field_present = metadata.get("supplier_field_present") is True
    legacy_without_supplier_column = not field_present
    missing_new_supplier = field_present and not supplier
    return {
        "supplier": supplier,
        "raw_value": str(metadata.get("supplier_raw_value") or "").strip(),
        "match_status": str(metadata.get("supplier_match_status") or "").strip(),
        "supplier_field_present": field_present,
        "requires_explicit_supplier": missing_new_supplier,
        "legacy_default_allowed": legacy_without_supplier_column and not supplier,
        "warning": "历史兼容默认供应商" if legacy_without_supplier_column and not supplier else "",
    }
