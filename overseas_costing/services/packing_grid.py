"""中文用途：定义来源无关的装箱表格网格，并保留原值、显示值、公式和合并证据。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class PackingSheetNotFound(ValueError):
    """用户明确选择的工作表不存在。"""


@dataclass(frozen=True)
class Cell:
    raw_value: Any
    display_value: str | None
    formula: str | None
    row: int
    column: int


@dataclass(frozen=True)
class MergeRange:
    start_row: int
    end_row: int
    start_column: int
    end_column: int
    evidence_kind: str


@dataclass(frozen=True)
class MaterialLine:
    source_row: int
    material_code: str | None
    quantity: str | None
    unit: str | None
    raw_fields: dict[str, Any]


@dataclass(frozen=True)
class PackageGroup:
    group_id: str
    row_numbers: tuple[int, ...]
    dimensions: dict[str, Any]
    net_weight: dict[str, Any]
    gross_weight: dict[str, Any]
    volume: dict[str, Any]
    package_count: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    needs_confirmation: bool


@dataclass(frozen=True)
class PackingTotals:
    value: str | None
    unit: str
    kind: str
    source_range: str | None
    precision: int | None


def dataclass_dict(value: Any) -> dict[str, Any]:
    return asdict(value)


def build_grid_from_dingtalk_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """把阿里云缓存的 schema v1 JSON 转为统一网格，不猜测不存在的合并范围。"""

    if snapshot.get("schemaVersion", snapshot.get("schema_version")) != 1:
        raise ValueError("仅支持 schema version 1 的钉钉表格快照。")

    values = snapshot.get("values") or []
    display_values = snapshot.get("displayValues", snapshot.get("display_values")) or []
    formulas = snapshot.get("formulas") or []
    if not values and snapshot.get("chunks"):
        chunks = sorted(snapshot.get("chunks") or [], key=_chunk_start_row)
        values = [row for chunk in chunks for row in (chunk.get("values") or [])]
        display_values = [
            row for chunk in chunks for row in (chunk.get("displayValues", chunk.get("display_values")) or [])
        ]
        formulas = [row for chunk in chunks for row in (chunk.get("formulas") or [])]
    row_count = max(len(values), len(display_values), len(formulas))
    column_count = max(
        [len(row) for matrix in (values, display_values, formulas) for row in matrix] or [0]
    )

    cells: list[list[dict[str, Any]]] = []
    for row_index in range(row_count):
        row: list[dict[str, Any]] = []
        for column_index in range(column_count):
            raw_value = _matrix_value(values, row_index, column_index)
            display_value = _matrix_value(display_values, row_index, column_index)
            formula = _matrix_value(formulas, row_index, column_index)
            row.append(
                dataclass_dict(
                    Cell(
                        raw_value=raw_value,
                        display_value=None if display_value in (None, "") else str(display_value),
                        formula=None if formula in (None, "") else str(formula),
                        row=row_index + 1,
                        column=column_index + 1,
                    )
                )
            )
        cells.append(row)

    merge_ranges = snapshot.get("mergeRanges", snapshot.get("merge_ranges")) or []
    normalized_merges = [_normalize_merge_range(item, "dingtalk_merge") for item in merge_ranges]
    merge_ranges_available = bool(
        snapshot.get("mergeRangesAvailable", snapshot.get("merge_ranges_available", False))
    )

    return {
        "schema_version": 1,
        "source_kind": "wiki_sheet",
        "sheet_name": str(snapshot.get("sheetName", snapshot.get("sheet_name")) or ""),
        "range_address": snapshot.get("rangeAddress", snapshot.get("range_address")),
        "cells": cells,
        "merge_ranges_available": merge_ranges_available,
        "merge_ranges": normalized_merges if merge_ranges_available else [],
        "source_updated_at": snapshot.get("sourceUpdatedAt", snapshot.get("source_updated_at")),
    }


def _chunk_start_row(chunk: Any) -> int:
    if not isinstance(chunk, dict):
        return 0
    address = str(chunk.get("rangeAddress", chunk.get("range_address")) or "")
    match = __import__("re").search(r"[A-Za-z]+(\d+)", address)
    return int(match.group(1)) if match else 0


def _matrix_value(matrix: list[list[Any]], row: int, column: int) -> Any:
    if row >= len(matrix) or column >= len(matrix[row]):
        return None
    return matrix[row][column]


def _normalize_merge_range(item: Any, default_evidence: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("非法的合并单元格范围。")
    return dataclass_dict(
        MergeRange(
            start_row=int(item.get("start_row", item.get("startRow"))),
            end_row=int(item.get("end_row", item.get("endRow"))),
            start_column=int(item.get("start_column", item.get("startColumn"))),
            end_column=int(item.get("end_column", item.get("endColumn"))),
            evidence_kind=str(item.get("evidence_kind", item.get("evidenceKind")) or default_evidence),
        )
    )
