"""中文用途：对装箱计划 Sheet 解析业务日期并生成可解释、稳定的推荐排序。"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


_FULL_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>20\d{2})\s*[./_-]\s*(?P<month>\d{1,2})\s*[./_-]\s*(?P<day>\d{1,2})(?!\d)"
)
_SHORT_DATE_PATTERN = re.compile(
    r"(?<![\d.])(?P<month>\d{1,2})\s*[./_-]\s*(?P<day>\d{1,2})(?:\s*日)?(?!\d)"
)
_CHINESE_DATE_PATTERN = re.compile(r"(?<!\d)(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日?")
_REFERENCE_HEADER_TOKENS = ("审批", "订单", "采购单", "orderno", "order no", "approval")


def parse_sheet_business_date(sheet_name: str, workbook_year: int | str | None) -> date | None:
    """从 Sheet 名提取日期；缺少年份时仅使用白名单工作簿年份。"""

    text = str(sheet_name or "")
    match = _FULL_DATE_PATTERN.search(text)
    if match:
        return _safe_date(match.group("year"), match.group("month"), match.group("day"))
    year = _safe_year(workbook_year)
    if year is None:
        return None
    for pattern in (_CHINESE_DATE_PATTERN, _SHORT_DATE_PATTERN):
        match = pattern.search(text)
        if match:
            return _safe_date(year, match.group("month"), match.group("day"))
    return None


def sort_packing_sheets(sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """推荐项置顶，随后按业务日期、源时间、快照时间及稳定标识排序。"""

    copied = [dict(item) for item in sheets]
    for item in copied:
        parsed = _coerce_date(item.get("business_date")) or parse_sheet_business_date(
            str(item.get("source_label") or item.get("sheet_name") or ""),
            item.get("workbook_year") or item.get("year"),
        )
        item["business_date"] = parsed.isoformat() if parsed else None

    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        business_date = _coerce_date(item.get("business_date"))
        return (
            0 if item.get("is_recommended") else 1,
            -(business_date.toordinal() if business_date else 0),
            -_timestamp(item.get("source_updated_at")),
            -_timestamp(item.get("snapshot_updated_at")),
            str(item.get("source_label") or item.get("sheet_name") or "").casefold(),
            str(item.get("source_id") or item.get("sheet_id") or ""),
        )

    return sorted(copied, key=key)


def summarize_packing_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """提取推荐需要的最小摘要，不保留原始工作表正文。"""

    item_codes: set[str] = set()
    references: set[str] = set()
    for row in preview.get("material_rows") or []:
        if not isinstance(row, dict):
            continue
        code = _normalize_code(row.get("material_code"))
        if code:
            item_codes.add(code)
        raw_fields = row.get("raw_fields") or {}
        if not isinstance(raw_fields, dict):
            continue
        for header, cell in raw_fields.items():
            normalized_header = _normalize_text(header)
            if not any(token.replace(" ", "") in normalized_header for token in _REFERENCE_HEADER_TOKENS):
                continue
            value = _cell_value(cell)
            if value:
                references.add(value)
    return {"item_codes": sorted(item_codes), "references": sorted(references)}


def recommend_packing_sheets(
    sheets: list[dict[str, Any]],
    *,
    batch_context: dict[str, Any],
    snapshot_summaries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """计算候选证据；只有最高且有正向证据的一项会被标记为推荐。"""

    batch_codes = {_normalize_code(value) for value in batch_context.get("item_codes") or []}
    batch_codes.discard("")
    batch_references = {_normalize_reference(value) for value in batch_context.get("references") or []}
    batch_references.discard("")
    keywords = {
        _normalize_text(value)
        for value in batch_context.get("keywords") or []
        if len(_normalize_text(value)) >= 2
    }
    reference_date = _coerce_date(batch_context.get("reference_date"))
    scored: list[dict[str, Any]] = []

    for original in sheets:
        item = dict(original)
        source_id = str(item.get("source_id") or "")
        summary = snapshot_summaries.get(source_id) or {}
        summary_codes = {_normalize_code(value) for value in summary.get("item_codes") or []}
        summary_codes.discard("")
        summary_references = {_normalize_reference(value) for value in summary.get("references") or []}
        summary_references.discard("")
        matched = sorted(batch_codes & summary_codes)
        missing = sorted(batch_codes - summary_codes)
        extra = sorted(summary_codes - batch_codes)
        label_reference_text = _normalize_reference(item.get("source_label") or item.get("sheet_name"))
        named_reference_matches = {
            value for value in batch_references if len(value) >= 4 and value in label_reference_text
        }
        reference_matches = sorted((batch_references & summary_references) | named_reference_matches)
        business_date = parse_sheet_business_date(
            str(item.get("source_label") or item.get("sheet_name") or ""),
            item.get("workbook_year") or item.get("year"),
        )
        label_text = _normalize_text(item.get("source_label") or item.get("sheet_name"))
        keyword_matches = sorted(keyword for keyword in keywords if keyword in label_text)

        score = 0
        reasons: list[str] = []
        coverage = (len(matched) / len(batch_codes)) if batch_codes else 0.0
        if matched:
            score += round(coverage * 60)
            reasons.append(f"匹配当前批次 {len(matched)}/{len(batch_codes)} 个 SKU")
        if reference_matches:
            score += 25
            reasons.append(f"匹配 {len(reference_matches)} 个审批或订单编号")
        if keyword_matches:
            score += 10
            reasons.append(f"名称匹配：{'、'.join(keyword_matches[:3])}")
        date_score = _date_proximity_score(business_date, reference_date)
        if date_score:
            score += date_score
            reasons.append("Sheet 日期接近当前批次")
        if extra:
            score -= min(10, len(extra) * 2)
            reasons.append(f"含 {len(extra)} 个批次外物料，预览时确认")

        has_snapshot = bool(summary)
        if has_snapshot and batch_codes and coverage == 1:
            confidence = "high"
        elif has_snapshot and ((coverage >= 0.7 and reference_matches) or reference_matches):
            confidence = "high" if coverage >= 0.7 else "medium"
        elif has_snapshot and matched:
            confidence = "medium"
        elif score > 0:
            confidence = "low"
        else:
            confidence = "none"

        item.update(
            {
                "display_source_name": "装箱计划表",
                "business_date": business_date.isoformat() if business_date else None,
                "snapshot_status": (
                    "ready" if has_snapshot else str(item.get("snapshot_status") or "not_cached")
                ),
                "recommendation_score": max(0, min(100, score)),
                "recommendation_confidence": confidence,
                "recommendation_reasons": reasons,
                "matched_item_codes": matched,
                "missing_item_codes": missing,
                "extra_item_codes": extra,
                "is_recommended": False,
                "auto_select_recommended": False,
                "_reference_match_count": len(reference_matches),
                "_coverage": coverage,
            }
        )
        scored.append(item)

    eligible = [item for item in scored if item["recommendation_score"] > 0]
    if eligible:
        winner = max(
            eligible,
            key=lambda item: (
                item["recommendation_score"],
                item["_reference_match_count"],
                item["_coverage"],
                _date_ordinal(item.get("business_date")),
                str(item.get("source_id") or ""),
            ),
        )
        winner["is_recommended"] = True
        winner["auto_select_recommended"] = bool(
            winner.get("recommendation_confidence") in {"high", "medium"}
            and winner.get("snapshot_status") == "ready"
        )

    for item in scored:
        item.pop("_reference_match_count", None)
        item.pop("_coverage", None)
    return sort_packing_sheets(scored)


def _safe_year(value: Any) -> int | None:
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if 2000 <= year <= 2100 else None


def _safe_date(year: Any, month: Any, day: Any) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    try:
        return parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return 0.0


def _date_ordinal(value: Any) -> int:
    parsed = _coerce_date(value)
    return parsed.toordinal() if parsed else 0


def _date_proximity_score(business_date: date | None, reference_date: date | None) -> int:
    if not business_date or not reference_date:
        return 0
    days = abs((business_date - reference_date).days)
    if days <= 7:
        return 5
    if days <= 30:
        return 3
    if days <= 90:
        return 1
    return 0


def _normalize_code(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _normalize_reference(value: Any) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "").strip()).upper()


def _normalize_text(value: Any) -> str:
    return re.sub(r"[\s_\-/]+", "", str(value or "").strip()).casefold()


def _cell_value(cell: Any) -> str:
    if isinstance(cell, dict):
        value = cell.get("raw_value")
        if value in (None, ""):
            value = cell.get("display_value")
    else:
        value = cell
    return str(value).strip() if value not in (None, "") else ""
