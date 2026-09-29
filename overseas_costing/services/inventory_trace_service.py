"""原始库位与原始标识的幂等回填服务。"""

from __future__ import annotations

from typing import Any, Iterable

try:
    import frappe
except Exception:  # pragma: no cover - 本地单测环境不安装 Frappe
    frappe = None


TRACE_FIELDS = (
    "item_code",
    "warehouse",
    "original_location",
    "original_identifier_alias",
)


class FrappeInventoryTraceRepository:
    def get_bin(self, item_code: str, warehouse: str):
        return frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            ["name", "actual_qty", "custom_original_location"],
            as_dict=True,
        )

    def get_item_alias(self, item_code: str):
        if not frappe.db.exists("Item", item_code):
            return None
        return (
            frappe.db.get_value(
                "Item", item_code, "custom_original_identifier_alias"
            )
            or ""
        )

    def set_bin_location(self, bin_name: str, value: str) -> None:
        frappe.db.set_value(
            "Bin",
            bin_name,
            "custom_original_location",
            value,
            update_modified=False,
        )

    def set_item_alias(self, item_code: str, value: str) -> None:
        frappe.db.set_value(
            "Item",
            item_code,
            "custom_original_identifier_alias",
            value,
            update_modified=False,
        )


def normalize_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for index, raw_row in enumerate(rows or [], start=1):
        row = {fieldname: str(raw_row.get(fieldname) or "").strip() for fieldname in TRACE_FIELDS}
        missing_fields = [fieldname for fieldname, value in row.items() if not value]
        if missing_fields:
            raise ValueError(
                f"第 {index} 行缺少字段：{', '.join(missing_fields)}"
            )

        key = (row["item_code"], row["warehouse"])
        previous = seen.get(key)
        if previous and previous != row:
            raise ValueError(
                f"同一物料和仓库存在冲突的追溯数据：{row['item_code']} / {row['warehouse']}"
            )
        if previous:
            continue
        seen[key] = row
        normalized.append(row)
    return normalized


def apply_inventory_trace(rows, *, dry_run: bool = True, repository=None) -> dict[str, Any]:
    repository = repository or FrappeInventoryTraceRepository()
    normalized_rows = normalize_rows(rows)
    bin_updates: dict[str, str] = {}
    item_updates: dict[str, str] = {}
    missing: list[dict[str, str]] = []
    conflicts: list[dict[str, Any]] = []
    unchanged_rows = 0

    def add_unique(target: list[dict], value: dict) -> None:
        if value not in target:
            target.append(value)

    for row in normalized_rows:
        item_code = row["item_code"]
        warehouse = row["warehouse"]
        requested_location = row["original_location"]
        requested_alias = row["original_identifier_alias"]

        bin_row = repository.get_bin(item_code, warehouse)
        item_alias = repository.get_item_alias(item_code)
        if not bin_row:
            add_unique(
                missing,
                {"item_code": item_code, "warehouse": warehouse, "target": "Bin"},
            )
        if item_alias is None:
            add_unique(missing, {"item_code": item_code, "target": "Item"})
        if not bin_row or item_alias is None:
            continue

        actual_qty = float(bin_row.get("actual_qty") or 0)
        if abs(actual_qty) <= 1e-12:
            add_unique(
                conflicts,
                {
                    "item_code": item_code,
                    "warehouse": warehouse,
                    "field": "actual_qty",
                    "existing": bin_row.get("actual_qty") or 0,
                    "requested": "nonzero balance",
                },
            )
            continue

        current_location = str(bin_row.get("custom_original_location") or "").strip()
        current_alias = str(item_alias or "").strip()
        location_matches = current_location == requested_location
        alias_matches = current_alias == requested_alias

        if current_location and not location_matches:
            add_unique(
                conflicts,
                {
                    "item_code": item_code,
                    "warehouse": warehouse,
                    "field": "custom_original_location",
                    "existing": current_location,
                    "requested": requested_location,
                },
            )
        elif not current_location:
            bin_updates[bin_row["name"]] = requested_location

        if current_alias and not alias_matches:
            add_unique(
                conflicts,
                {
                    "item_code": item_code,
                    "field": "custom_original_identifier_alias",
                    "existing": current_alias,
                    "requested": requested_alias,
                },
            )
        elif not current_alias:
            item_updates[item_code] = requested_alias

        if location_matches and alias_matches:
            unchanged_rows += 1

    result = {
        "dry_run": bool(dry_run),
        "input_rows": len(normalized_rows),
        "pending_bin_updates": len(bin_updates),
        "pending_item_updates": len(item_updates),
        "updated_bins": 0,
        "updated_items": 0,
        "unchanged_rows": unchanged_rows,
        "missing": missing,
        "conflicts": conflicts,
        "applied": False,
    }
    if dry_run or missing or conflicts:
        return result

    for bin_name, value in bin_updates.items():
        repository.set_bin_location(bin_name, value)
    for item_code, value in item_updates.items():
        repository.set_item_alias(item_code, value)

    result["updated_bins"] = len(bin_updates)
    result["updated_items"] = len(item_updates)
    result["applied"] = True
    return result
