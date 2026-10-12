#!/usr/bin/env python3
"""Replace the 2026-08-04 ERP BOM placeholders with seed BOM child details."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

from sync_20260804_bom_routes_to_db import find_file, parse_bom_rows


IMPORT_TAG = "erp-sync-20260804"
DETAIL_TAG = "seed-bom-detail"
PLACEHOLDER = "--"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads-dir", type=Path, default=Path(r"D:\Users\46733\Downloads"))
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=Path(r"D:\work\资料\PLM\seeds\deployment_master_data_seed.json"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="plm")
    parser.add_argument("--user", default="plm")
    parser.add_argument("--password", default="plm123")
    parser.add_argument("--schema", default="plm")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("outputs/erp-sync-20260804/seed-bom-detail-report.json"),
    )
    return parser.parse_args()


def connect(args: argparse.Namespace):
    return psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.database,
        user=args.user,
        password=args.password,
        options=f"-c search_path={args.schema}",
    )


def fetch_one(cur, query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
    cur.execute(query, params)
    return cur.fetchone()


def normalized_seed_code(bom_code: str) -> str:
    return re.sub(r"-\d{3}$", "-001", bom_code.strip())


def clean_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    result = str(value).strip()
    return result or default


def seed_tables(seed_file: Path) -> dict[str, Any]:
    data = json.loads(seed_file.read_text(encoding="utf-8"))
    return data["tables"]


def build_seed_index(tables: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    main_by_code = {row["bom_code"]: row for row in tables["bom_main"]}
    children_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tables["bom_child"]:
        children_by_code[row["bom_code"]].append(row)
    for rows in children_by_code.values():
        rows.sort(key=lambda row: (row.get("line_no") is None, row.get("line_no") or 0))
    return main_by_code, children_by_code


def find_route_for_seed_bom(
    cur,
    seed_bom_code: str,
    child_rows: list[dict[str, Any]],
) -> tuple[str, str, int] | None:
    route = fetch_one(
        cur,
        """
        select r.route_code, r.route_name, r.process_id
        from plm_product_bom b
        join plm_product_bom_route r on r.product_bom_id = b.product_bom_id
        where b.bom_code = %s
          and b.deleted_flag = 0
          and r.deleted_flag = 0
          and r.status = 'active'
          and r.variant_source_type = 'seed_reference'
          and r.route_code <> %s
        order by r.product_bom_route_id
        limit 1
        """,
        (seed_bom_code, PLACEHOLDER),
    )
    if route:
        return route[0], route[1], route[2]

    route_code = next(
        (clean_text(row.get("target_route_code")) for row in child_rows if clean_text(row.get("target_route_code"))),
        None,
    )
    if not route_code:
        return None
    process = fetch_one(
        cur,
        """
        select process_code, process_name, process_id
        from plm_process
        where process_code = %s and process_type = 'routing' and deleted_flag = 0
        order by process_id
        limit 1
        """,
        (route_code,),
    )
    return (process[0], process[1], process[2]) if process else None


def current_bom_route(
    cur,
    bom_id: int,
    route_code: str,
    route_name: str,
    process_id: int,
    product_id: int,
    bom_code: str,
    now: datetime,
) -> int:
    route = fetch_one(
        cur,
        """
        select product_bom_route_id
        from plm_product_bom_route
        where product_bom_id = %s and deleted_flag = 0
        order by case when variant_source_type = 'erp_archive_placeholder' then 0 else 1 end,
                 product_bom_route_id
        limit 1
        """,
        (bom_id,),
    )
    if route:
        cur.execute(
            """
            update plm_product_bom_route
            set product_id = %s,
                process_id = %s,
                route_code = %s,
                route_name = %s,
                shared_bom_group_code = %s,
                variant_name = 'Seed BOM 明细路线',
                variant_source_type = %s,
                updated_at = %s,
                updated_by = %s
            where product_bom_route_id = %s
            """,
            (
                product_id,
                process_id,
                route_code,
                route_name,
                "SEED-" + bom_code,
                DETAIL_TAG,
                now,
                DETAIL_TAG,
                route[0],
            ),
        )
        return route[0]

    cur.execute(
        """
        insert into plm_product_bom_route (
            product_bom_id, product_id, process_id, route_code, route_name,
            shared_bom_group_code, route_variant_no, variant_name, variant_source_type,
            status, created_at, created_by, updated_at, updated_by, deleted_flag
        )
        values (%s, %s, %s, %s, %s, %s, 'SEED-DETAIL', 'Seed BOM 明细路线',
                %s, 'active', %s, %s, %s, %s, 0)
        returning product_bom_route_id
        """,
        (
            bom_id,
            product_id,
            process_id,
            route_code,
            route_name,
            "SEED-" + bom_code,
            DETAIL_TAG,
            now,
            DETAIL_TAG,
            now,
            DETAIL_TAG,
        ),
    )
    return cur.fetchone()[0]


def inventory_index(cur, child_rows: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    codes = sorted(
        {
            clean_text(row.get("child_code_normalized") or row.get("child_code"))
            for row in child_rows
            if clean_text(row.get("child_code_normalized") or row.get("child_code"))
        }
    )
    cur.execute(
        """
        select inventory_id, inventory_code, inventory_name, specification,
               coalesce(stock_uom, purchase_uom, sales_uom) as unit,
               supplier_name, unit_cost, currency_code
        from plm_inventory
        where deleted_flag = 0 and inventory_code = any(%s)
        """,
        (codes,),
    )
    return {row[1]: row for row in cur.fetchall()}


def soft_delete_managed_items(cur, bom_id: int, now: datetime) -> tuple[int, int]:
    unmanaged = fetch_one(
        cur,
        """
        select count(*)
        from plm_product_bom_item
        where product_bom_id = %s
          and deleted_flag = 0
          and created_by not in (%s, %s)
        """,
        (bom_id, IMPORT_TAG, DETAIL_TAG),
    )[0]
    cur.execute(
        """
        update plm_product_bom_item
        set deleted_flag = 1, updated_at = %s, updated_by = %s
        where product_bom_id = %s
          and deleted_flag = 0
          and created_by in (%s, %s)
        """,
        (now, DETAIL_TAG, bom_id, IMPORT_TAG, DETAIL_TAG),
    )
    return unmanaged, cur.rowcount


def insert_items(
    cur,
    bom_id: int,
    route_id: int,
    product_id: int,
    bom_code: str,
    rows: list[dict[str, Any]],
    inventories: dict[str, tuple[Any, ...]],
    now: datetime,
) -> tuple[int, int]:
    missing_inventory = 0
    for index, row in enumerate(rows, start=1):
        item_code = clean_text(row.get("child_code_normalized") or row.get("child_code"), PLACEHOLDER)
        inventory = inventories.get(item_code)
        if inventory is None:
            missing_inventory += 1
        inventory_id = inventory[0] if inventory else None
        item_name = clean_text(row.get("child_name"), PLACEHOLDER)
        specification = inventory[3] if inventory else None
        unit = clean_text(row.get("unit")) or (inventory[4] if inventory else None) or "pcs"
        quantity = Decimal(str(row.get("quantity") or 1))
        remark = {
            "source": "deployment_master_data_seed.json",
            "importTag": DETAIL_TAG,
            "componentRowId": row.get("component_row_id"),
            "mappingStatus": row.get("mapping_status"),
            "targetProcessCode": row.get("target_process_code"),
            "targetProcessName": row.get("target_process_name"),
            "targetRouteCode": row.get("target_route_code"),
            "mappingSource": row.get("mapping_source"),
        }
        cur.execute(
            """
            insert into plm_product_bom_item (
                product_bom_id, product_bom_route_id, product_id, shared_bom_group_code,
                inventory_id, item_code, item_name, specification, line_no, quantity,
                uom_code, loss_rate, unit_cost_snapshot, supplier_name_snapshot,
                line_cost_snapshot, currency_code, material_source, unmatched_flag,
                substitute_flag, remark, version_no, status,
                created_at, created_by, updated_at, updated_by, deleted_flag
            )
            values (
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, 0, 0, %s,
                0, %s, 'seed_bom_child', %s,
                0, %s, %s, 'draft',
                %s, %s, %s, %s, 0
            )
            """,
            (
                bom_id,
                route_id,
                product_id,
                "SEED-" + bom_code,
                inventory_id,
                item_code,
                item_name,
                specification,
                index,
                quantity,
                unit,
                inventory[5] if inventory else None,
                inventory[7] if inventory and inventory[7] else "CNY",
                0 if inventory else 1,
                Json(remark),
                bom_code,
                now,
                DETAIL_TAG,
                now,
                DETAIL_TAG,
            ),
        )
    return len(rows), missing_inventory


def main() -> None:
    args = parse_args()
    bom_file = find_file(args.downloads_dir, "*BOM*2026-08-04.xlsx")
    source_rows = parse_bom_rows(bom_file)
    tables = seed_tables(args.seed_file)
    main_by_code, children_by_code = build_seed_index(tables)
    all_children = [row for rows in children_by_code.values() for row in rows]

    report: dict[str, Any] = {
        "executed": args.execute,
        "import_tag": DETAIL_TAG,
        "source_seed_file": str(args.seed_file),
        "bom_file": str(bom_file),
        "source_bom_count": len(source_rows),
        "seed_bom_count": len(main_by_code),
        "seed_child_count": len(all_children),
        "matched_boms": 0,
        "inserted_items": 0,
        "placeholder_items_soft_deleted": 0,
        "unmanaged_active_items": 0,
        "missing_inventory": [],
        "route_updates": [],
        "component_count_mismatches": [],
        "skipped": [],
    }

    conn = connect(args)
    try:
        cur = conn.cursor()
        inventories = inventory_index(cur, all_children)
        for source in source_rows:
            current_bom = fetch_one(
                cur,
                """
                select product_bom_id, product_id
                from plm_product_bom
                where bom_code = %s and deleted_flag = 0
                """,
                (source["bom_code"],),
            )
            seed_code = normalized_seed_code(source["bom_code"])
            seed_main = main_by_code.get(seed_code)
            child_rows = children_by_code.get(seed_code, [])
            if current_bom is None or seed_main is None or not child_rows:
                report["skipped"].append(
                    {
                        "bom_code": source["bom_code"],
                        "seed_bom_code": seed_code,
                        "reason": "current_bom_or_seed_detail_missing",
                    }
                )
                continue

            report["matched_boms"] += 1
            if source["component_count"] is not None and source["component_count"] != len(child_rows):
                report["component_count_mismatches"].append(
                    {
                        "bom_code": source["bom_code"],
                        "source_component_count": source["component_count"],
                        "seed_child_count": len(child_rows),
                    }
                )

            route_info = find_route_for_seed_bom(cur, seed_code, child_rows)
            if route_info is None:
                report["skipped"].append(
                    {"bom_code": source["bom_code"], "seed_bom_code": seed_code, "reason": "route_not_found"}
                )
                continue
            route_code, route_name, process_id = route_info
            now = datetime.now()
            if args.execute:
                route_id = current_bom_route(
                    cur,
                    current_bom[0],
                    route_code,
                    route_name,
                    process_id,
                    current_bom[1],
                    source["bom_code"],
                    now,
                )
                unmanaged, soft_deleted = soft_delete_managed_items(cur, current_bom[0], now)
                report["unmanaged_active_items"] += unmanaged
                report["placeholder_items_soft_deleted"] += soft_deleted
                inserted, missing = insert_items(
                    cur,
                    current_bom[0],
                    route_id,
                    current_bom[1],
                    source["bom_code"],
                    child_rows,
                    inventories,
                    now,
                )
                report["inserted_items"] += inserted
                if missing:
                    report["missing_inventory"].append(
                        {"bom_code": source["bom_code"], "missing_rows": missing}
                    )
                report["route_updates"].append(
                    {
                        "bom_code": source["bom_code"],
                        "route_code": route_code,
                        "route_name": route_name,
                        "item_count": inserted,
                    }
                )
            else:
                report["inserted_items"] += len(child_rows)

        if args.execute:
            conn.commit()
        else:
            conn.rollback()
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))


if __name__ == "__main__":
    main()
