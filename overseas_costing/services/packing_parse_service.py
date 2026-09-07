"""中文用途：从统一装箱网格识别物料行、共享包装组和可追溯整票汇总。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


HEADER_ALIASES = {
    "material_code": ("品目编码", "物料编码", "itemcode", "item code", "sku", "货号"),
    "product_name": ("中文品名", "产品名称", "物料名称", "品名", "productname"),
    "quantity": ("总个数", "总数量", "数量", "quantity", "qty"),
    "unit": ("申报单位", "单位", "unit"),
    "length_m": ("长m", "长度m", "lengthm"),
    "width_m": ("宽m", "宽度m", "widthm"),
    "height_m": ("高m", "高度m", "heightm"),
    "net_weight_kg": ("总净重", "净重nw", "netweight", "净重"),
    "gross_weight_kg": ("总毛重", "毛重gw", "grossweight", "毛重"),
    "volume_m3": ("总体积", "totalcapacity", "volumem3", "volume", "cbm", "体积"),
    "package_count": ("件数numberofpieces", "包装件数", "箱数", "件数"),
}

PHYSICAL_FIELDS = (
    "length_m",
    "width_m",
    "height_m",
    "net_weight_kg",
    "gross_weight_kg",
    "volume_m3",
    "package_count",
)
TOTAL_LABELS = ("合计", "总计", "total", "totals")


def parse_packing_grid(grid: dict[str, Any]) -> dict[str, Any]:
    cells = grid.get("cells") or []
    if not cells:
        return _empty_preview(grid, "empty_grid", "装箱表格没有可读取的单元格。")

    header_row, columns, original_headers = _find_header(cells)
    if not header_row or "material_code" not in columns:
        return _empty_preview(grid, "header_not_found", "未识别到物料编码表头。")

    total_row = None
    material_rows: list[dict[str, Any]] = []
    for row_number in range(header_row + 1, len(cells) + 1):
        if _is_total_row(cells[row_number - 1]):
            total_row = row_number
            break
        if _is_repeated_header(cells[row_number - 1], columns):
            break
        material_code = _string_value(_cell_raw(cells, row_number, columns.get("material_code")))
        product_name = _string_value(_cell_raw(cells, row_number, columns.get("product_name")))
        if not material_code and not product_name:
            continue
        material_rows.append(
            {
                "source_row": row_number,
                "material_code": material_code,
                "product_name": product_name,
                "quantity": _decimal_text(_decimal_cell(cells, row_number, columns.get("quantity"))),
                "unit": _string_value(_cell_raw(cells, row_number, columns.get("unit"))),
                "raw_fields": {
                    header: dict(cells[row_number - 1][column - 1])
                    for column, header in original_headers.items()
                    if header and column <= len(cells[row_number - 1])
                },
            }
        )

    row_numbers = [row["source_row"] for row in material_rows]
    merges = _physical_merges(grid, columns, set(row_numbers))
    groups = _build_groups(cells, row_numbers, columns, merges, bool(grid.get("merge_ranges_available")))
    blocking = _group_blockers(cells, groups, columns)
    warnings: list[dict[str, str]] = []

    for row in material_rows:
        code = row.get("material_code") or ""
        if code and not re.search(r"[A-Za-z]", code):
            warnings.append(
                {
                    "code": "nonstandard_material_code",
                    "message": f"第 {row['source_row']} 行物料编码为纯数字，保留为待匹配候选。",
                }
            )

    totals = _build_totals(cells, groups, columns, total_row)
    blocking.extend(_total_mismatch_blockers(totals))
    package_total = _build_package_total(cells, groups, columns, total_row)
    totals["package_count"] = package_total
    needs_confirmation = any(group["needs_confirmation"] for group in groups)
    if needs_confirmation and not any(item["code"] == "conflicting_merge_ranges" for item in blocking):
        blocking.append(
            {
                "code": "group_confirmation_required",
                "message": "来源未提供可靠合并范围，候选共享包装组需要人工确认。",
            }
        )

    return {
        "ok": not blocking,
        "source": {
            "source_kind": grid.get("source_kind"),
            "sheet_name": grid.get("sheet_name"),
            "range_address": grid.get("range_address"),
            "merge_ranges_available": bool(grid.get("merge_ranges_available")),
            "source_updated_at": grid.get("source_updated_at"),
        },
        "header_row": header_row,
        "material_row_count": len(material_rows),
        "package_group_count": len(groups),
        "package_count": int(Decimal(package_total["value"])) if package_total.get("value") is not None else len(groups),
        "material_rows": material_rows,
        "groups": groups,
        "totals": totals,
        "validation": {
            "blocking": blocking,
            "warnings": warnings,
            "needs_group_confirmation": needs_confirmation,
        },
    }


def _find_header(cells: list[list[dict[str, Any]]]) -> tuple[int, dict[str, int], dict[int, str]]:
    for row_number, row in enumerate(cells[:40], start=1):
        normalized = {index: _normalize_header(cell.get("raw_value") or cell.get("display_value")) for index, cell in enumerate(row, start=1)}
        columns: dict[str, int] = {}
        for field, aliases in HEADER_ALIASES.items():
            candidates = [
                (_header_match_score(field, header, aliases), -column, column)
                for column, header in normalized.items()
                if header
            ]
            score, _position, column = max(candidates, default=(0, 0, 0))
            if score > 0:
                columns[field] = column
        if "material_code" in columns and ("quantity" in columns or "product_name" in columns):
            originals = {
                index: str(cell.get("display_value") or cell.get("raw_value") or "").strip()
                for index, cell in enumerate(row, start=1)
            }
            return row_number, columns, originals
    return 0, {}, {}


def _physical_merges(
    grid: dict[str, Any], columns: dict[str, int], material_rows: set[int]
) -> list[dict[str, Any]]:
    physical_columns = {column: field for field, column in columns.items() if field in PHYSICAL_FIELDS}
    result = []
    for merge in grid.get("merge_ranges") or []:
        if merge.get("start_column") != merge.get("end_column"):
            continue
        column = int(merge.get("start_column") or 0)
        if column not in physical_columns:
            continue
        rows = tuple(
            row
            for row in range(int(merge["start_row"]), int(merge["end_row"]) + 1)
            if row in material_rows
        )
        if len(rows) < 2:
            continue
        result.append({**merge, "field": physical_columns[column], "rows": rows})
    return result


def _build_groups(
    cells: list[list[dict[str, Any]]],
    row_numbers: list[int],
    columns: dict[str, int],
    merges: list[dict[str, Any]],
    merge_ranges_available: bool,
) -> list[dict[str, Any]]:
    parent = {row: row for row in row_numbers}

    def find(row: int) -> int:
        while parent[row] != row:
            parent[row] = parent[parent[row]]
            row = parent[row]
        return row

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for merge in merges:
        for row in merge["rows"][1:]:
            union(merge["rows"][0], row)

    suggestions: list[tuple[int, int]] = []
    if not merge_ranges_available:
        for previous, current in zip(row_numbers, row_numbers[1:]):
            if current != previous + 1:
                continue
            if all(_cell_is_blank(cells, current, columns.get(field)) for field in PHYSICAL_FIELDS):
                union(previous, current)
                suggestions.append((previous, current))

    grouped: dict[int, list[int]] = {}
    for row in row_numbers:
        grouped.setdefault(find(row), []).append(row)

    result = []
    for index, rows in enumerate(sorted(grouped.values(), key=lambda item: item[0]), start=1):
        row_set = set(rows)
        evidence = [
            {
                "kind": merge.get("evidence_kind") or "xlsx_merge",
                "field": merge["field"],
                "rows": list(merge["rows"]),
            }
            for merge in merges
            if row_set.intersection(merge["rows"])
        ]
        suggested = [pair for pair in suggestions if pair[0] in row_set and pair[1] in row_set]
        evidence.extend(
            {
                "kind": "blank_continuation_suggestion",
                "field": "package_level_fields",
                "rows": list(pair),
            }
            for pair in suggested
        )
        merge_spans = {tuple(merge["rows"]) for merge in merges if row_set.intersection(merge["rows"])}
        incompatible = len(merge_spans) > 1
        needs_confirmation = incompatible or bool(suggested)
        result.append(
            {
                "group_id": f"package-{index}",
                "row_numbers": rows,
                "dimensions": {
                    field: _metric(cells, rows, columns.get(field), merges, field)
                    for field in ("length_m", "width_m", "height_m")
                },
                "net_weight_kg": _metric(cells, rows, columns.get("net_weight_kg"), merges, "net_weight_kg"),
                "gross_weight_kg": _metric(cells, rows, columns.get("gross_weight_kg"), merges, "gross_weight_kg"),
                "volume_m3": _metric(cells, rows, columns.get("volume_m3"), merges, "volume_m3"),
                "package_count": _metric(cells, rows, columns.get("package_count"), merges, "package_count"),
                "evidence": evidence,
                "needs_confirmation": needs_confirmation,
                "suggestion_reason": "箱级字段为空且与上一物料连续" if suggested else None,
                "merge_conflict": incompatible,
            }
        )
    return result


def _metric(
    cells: list[list[dict[str, Any]]],
    rows: list[int],
    column: int | None,
    merges: list[dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    value = next((_decimal_cell(cells, row, column) for row in rows if _decimal_cell(cells, row, column) is not None), None)
    explicit_merge = any(merge["field"] == field and set(merge["rows"]) == set(rows) for merge in merges)
    return {
        "value": _decimal_text(value),
        "count_once": len(rows) == 1 or explicit_merge,
        "source_row": next((row for row in rows if _decimal_cell(cells, row, column) is not None), None),
        "evidence": "xlsx_merge" if explicit_merge else "direct_value" if value is not None else "missing",
    }


def _group_blockers(
    cells: list[list[dict[str, Any]]], groups: list[dict[str, Any]], columns: dict[str, int]
) -> list[dict[str, str]]:
    blocking = []
    if any(group.get("merge_conflict") for group in groups):
        blocking.append(
            {
                "code": "conflicting_merge_ranges",
                "message": "毛重、体积或其他箱级字段的合并范围不一致，需要人工确认分组。",
            }
        )
    for group in groups:
        for field in ("gross_weight_kg", "volume_m3", "net_weight_kg"):
            column = columns.get(field)
            for row in group["row_numbers"]:
                cell = _cell(cells, row, column)
                if cell and cell.get("formula") and cell.get("raw_value") is None:
                    blocking.append(
                        {
                            "code": "unresolved_formula",
                            "message": f"第 {row} 行 {field} 是没有缓存结果的公式，不能在服务器端猜算。",
                        }
                    )
                    break
    return blocking


def _build_totals(
    cells: list[list[dict[str, Any]]],
    groups: list[dict[str, Any]],
    columns: dict[str, int],
    total_row: int | None,
) -> dict[str, dict[str, Any]]:
    result = {}
    for field, unit in (
        ("net_weight_kg", "kg"),
        ("gross_weight_kg", "kg"),
        ("volume_m3", "m3"),
    ):
        calculated_values = [
            _to_decimal(group[field].get("value"))
            for group in groups
            if group[field].get("value") is not None and group[field].get("count_once")
        ]
        calculated = sum((value for value in calculated_values if value is not None), Decimal("0")) if calculated_values else None
        declared = _decimal_cell(cells, total_row, columns.get(field)) if total_row else None
        value = calculated if field == "net_weight_kg" or declared is None else declared
        kind = "calculated_detail_sum" if field == "net_weight_kg" or declared is None else "source_total"
        result[field] = {
            "value": _decimal_text(value),
            "unit": unit,
            "kind": kind,
            "source_range": f"{field}:{total_row}" if declared is not None else None,
            "precision": _decimal_precision(value),
            "declared_value": _decimal_text(declared),
            "calculated_value": _decimal_text(calculated),
        }
    return result


def _total_mismatch_blockers(totals: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """表内合计和明细加总不一致时，不猜用哪个，交给用户确认。"""

    blockers = []
    labels = {"net_weight_kg": "净重", "gross_weight_kg": "毛重", "volume_m3": "体积"}
    for field, label in labels.items():
        total = totals.get(field) or {}
        declared = _to_decimal(total.get("declared_value"))
        calculated = _to_decimal(total.get("calculated_value"))
        if declared is None or calculated is None:
            continue
        tolerance = max(Decimal("0.01"), abs(declared) * Decimal("0.001"))
        if abs(declared - calculated) <= tolerance:
            continue
        blockers.append(
            {
                "code": "total_mismatch",
                "field": field,
                "declared_value": _decimal_text(declared),
                "calculated_value": _decimal_text(calculated),
                "message": f"表内{label}合计 {declared} 与明细加总 {calculated} 不一致，请选择比较口径。",
            }
        )
    return blockers


def _header_match_score(field: str, header: str, aliases: tuple[str, ...]) -> int:
    matches = [_normalize_header(alias) for alias in aliases if _normalize_header(alias) in header]
    if not matches:
        return 0
    score = max(100 if alias == header else 50 + len(alias) for alias in matches)
    if field in {"net_weight_kg", "gross_weight_kg", "volume_m3"}:
        if any(marker in header for marker in ("总", "total")):
            score += 100
        if any(marker in header for marker in ("每件", "单件", "perpiece", "perunit", "unit")):
            score -= 100
    return score


def _build_package_total(
    cells: list[list[dict[str, Any]]],
    groups: list[dict[str, Any]],
    columns: dict[str, int],
    total_row: int | None,
) -> dict[str, Any]:
    calculated_values = [
        _to_decimal(group["package_count"].get("value"))
        for group in groups
        if group.get("package_count")
        and group["package_count"].get("value") is not None
        and group["package_count"].get("count_once")
    ]
    calculated = sum((value for value in calculated_values if value is not None), Decimal("0")) if calculated_values else None
    declared = _decimal_cell(cells, total_row, columns.get("package_count")) if total_row else None
    value = declared if declared is not None else calculated
    if value is not None and (value < 0 or value != value.to_integral_value()):
        value = None
    return {
        "value": _decimal_text(value),
        "unit": "piece",
        "kind": "source_total" if declared is not None else "calculated_group_sum" if calculated is not None else "group_count_fallback",
        "source_range": f"package_count:{total_row}" if declared is not None else None,
        "precision": 0 if value is not None else None,
        "declared_value": _decimal_text(declared),
        "calculated_value": _decimal_text(calculated),
    }


def _empty_preview(grid: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "source": {"source_kind": grid.get("source_kind"), "sheet_name": grid.get("sheet_name")},
        "material_row_count": 0,
        "package_group_count": 0,
        "package_count": 0,
        "material_rows": [],
        "groups": [],
        "totals": {},
        "validation": {"blocking": [{"code": code, "message": message}], "warnings": [], "needs_group_confirmation": False},
    }


def _cell(cells: list[list[dict[str, Any]]], row: int | None, column: int | None) -> dict[str, Any] | None:
    if not row or not column or row < 1 or column < 1 or row > len(cells) or column > len(cells[row - 1]):
        return None
    return cells[row - 1][column - 1]


def _cell_raw(cells: list[list[dict[str, Any]]], row: int | None, column: int | None) -> Any:
    cell = _cell(cells, row, column)
    return cell.get("raw_value") if cell else None


def _cell_is_blank(cells: list[list[dict[str, Any]]], row: int, column: int | None) -> bool:
    cell = _cell(cells, row, column)
    return not cell or cell.get("raw_value") in (None, "") and not cell.get("formula")


def _decimal_cell(cells: list[list[dict[str, Any]]], row: int | None, column: int | None) -> Decimal | None:
    cell = _cell(cells, row, column)
    if not cell or cell.get("raw_value") in (None, ""):
        return None
    return _to_decimal(cell.get("raw_value"))


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _decimal_precision(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return max(0, -value.as_tuple().exponent)


def _string_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip() or None


def _normalize_header(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _is_total_row(row: list[dict[str, Any]]) -> bool:
    for cell in row[:12]:
        normalized = _normalize_header(cell.get("raw_value") or cell.get("display_value"))
        if normalized in TOTAL_LABELS:
            return True
    return False


def _is_repeated_header(row: list[dict[str, Any]], columns: dict[str, int]) -> bool:
    material_cell = _cell_raw([row], 1, columns.get("material_code"))
    normalized = _normalize_header(material_cell)
    return any(_normalize_header(alias) in normalized for alias in HEADER_ALIASES["material_code"])
