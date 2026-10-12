#!/usr/bin/env python3
"""Import PLM seed product/SKU color and process relationships.

The importer is intentionally idempotent and conservative:
* existing product lines, SKUs, processes, BOMs and decisions are reused;
* no existing row is deleted or overwritten;
* seed BOMs are created as draft reference BOMs without material lines;
* --dry-run is the default; --execute is required for writes.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json


PRODUCT_CODES = (
    "NBA4030",
    "NBD4030",
    "NDN4030",
    "NFA4020",
    "NFB4020",
    "NHA4030",
    "NWV4030",
)
IMPORT_TAG = "seed-color-process-20260803"
SOURCE_SYSTEM = "PLM_SEED"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=Path("PLM/seeds"),
        help="directory containing deployment_master_data_seed.json and master_route_seed.json",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="plm")
    parser.add_argument("--user", default="plm")
    parser.add_argument("--password", default="plm123")
    parser.add_argument("--schema", default="plm")
    parser.add_argument("--execute", action="store_true", help="commit changes")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("outputs/plm-seed-db-import/2026-08-03-import-report.json"),
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def product_code_from_bom(bom_code: str) -> str:
    for code in PRODUCT_CODES:
        if bom_code.startswith(f"BOM-{code}"):
            return code
    raise ValueError(f"Cannot resolve product code from BOM code: {bom_code}")


def color_code_from_bom(bom_code: str) -> str:
    match = re.search(r"(\d{2})-001$", bom_code)
    if not match:
        raise ValueError(f"Cannot resolve color code from BOM code: {bom_code}")
    return match.group(1)


def route_for_bom(product_code: str, color_code: str, routes_by_product: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    routes = routes_by_product[product_code]
    if product_code == "NBA4030":
        wanted = (
            "ROUTE-RAINBOW-INJECTION-CLEAR-V1"
            if color_code == "31"
            else "ROUTE-RAINBOW-DYE-NO-UV-V1"
        )
        for route in routes:
            if route["route_code"] == wanted:
                return route
    return sorted(
        routes,
        key=lambda route: (not route.get("is_default", False), route.get("priority", 9999)),
    )[0]


def json_route(route: dict[str, Any], operation_ids: dict[str, int]) -> dict[str, Any]:
    nodes = []
    for node in route.get("nodes", []):
        config = node.get("config_json") or {}
        output_base = text(config.get("outputBaseCode") or config.get("output_base_code"))
        nodes.append(
            {
                "nodeCode": node.get("node_code"),
                "stepNo": node.get("step_no"),
                "sourceOperationCode": node.get("operation_code"),
                "stepName": node.get("step_name"),
                "operationProcessId": operation_ids.get(output_base),
                "outputBaseCode": output_base,
                "outputType": config.get("outputType"),
                "outputColorMode": config.get("outputColorMode") or config.get("output_color_mode"),
                "outputColorCode": config.get("outputColorCode") or config.get("output_color_code"),
                "inputDimensions": config.get("inputDimensions") or config.get("input_dimensions"),
                "outputDimensions": config.get("outputDimensions") or config.get("output_dimensions"),
                "materialDimensions": config.get("materialDimensions") or config.get("material_dimensions"),
                "planningDimensions": config.get("planningDimensions") or config.get("planning_dimensions"),
            }
        )
    return {
        "source": "master_route_seed.json",
        "routeCode": route["route_code"],
        "routeName": route["route_name"],
        "productCode": route["product_code"],
        "version": route.get("version"),
        "scenario": route.get("scenario"),
        "status": route.get("status"),
        "edges": route.get("edges", []),
        "nodes": nodes,
    }


def count_source_duplicates(rows: list[dict[str, Any]], key: str) -> list[tuple[str, int]]:
    counts = Counter(text(row.get(key)) for row in rows)
    return sorted((value or "<blank>", count) for value, count in counts.items() if value and count > 1)


def ensure_required_tables(cur) -> None:
    required = {
        "plm_product",
        "plm_process",
        "plm_product_bom",
        "plm_product_bom_route",
        "plm_product_bom_route_color",
        "plm_product_production_color_decision",
        "plm_code_item",
    }
    cur.execute(
        """
        select table_name
        from information_schema.tables
        where table_schema = current_schema()
          and table_name = any(%s)
        """,
        (list(required),),
    )
    actual = {row[0] for row in cur.fetchall()}
    missing = sorted(required - actual)
    if missing:
        raise RuntimeError(f"Required PLM tables are missing: {', '.join(missing)}")


def fetch_products(cur) -> dict[str, dict[str, Any]]:
    cur.execute(
        """
        select product_id, product_code, product_name, product_type, product_specific_code,
               version_no, status, deleted_flag
        from plm_product
        where product_code = any(%s)
          and deleted_flag = 0
        """,
        (list(PRODUCT_CODES),),
    )
    return {
        row[1]: {
            "product_id": row[0],
            "product_code": row[1],
            "product_name": row[2],
            "product_type": row[3],
            "product_specific_code": row[4],
            "version_no": row[5],
            "status": row[6],
            "deleted_flag": row[7],
        }
        for row in cur.fetchall()
    }


def resolve_color_items(cur, color_rows: list[dict[str, Any]], execute: bool, stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in color_rows:
        code = text(row.get("color_code"))
        if not code:
            continue
        cur.execute(
            """
            select code_item_id, code_value, code_name, status
            from plm_code_item
            where code_type = 'color'
              and code_value = %s
              and deleted_flag = 0
            order by code_item_id
            limit 1
            """,
            (code,),
        )
        found = cur.fetchone()
        if found:
            result[code] = {
                "code_item_id": found[0],
                "code_value": found[1],
                "code_name": found[2],
                "status": found[3],
            }
            continue
        if not execute:
            result[code] = {
                "code_item_id": None,
                "code_value": code,
                "code_name": text(row.get("color_name")) or code,
                "status": "enabled",
            }
            stats["colors"]["would_insert"] += 1
            continue
        cur.execute(
            """
            insert into plm_code_item (
                code_type, code_value, code_name, status, sort_order,
                created_by, updated_by, deleted_flag
            )
            values ('color', %s, %s, 'enabled', %s, %s, %s, 0)
            returning code_item_id
            """,
            (
                code,
                text(row.get("color_name")) or code,
                int(code) if code.isdigit() else 0,
                IMPORT_TAG,
                IMPORT_TAG,
            ),
        )
        result[code] = {
            "code_item_id": cur.fetchone()[0],
            "code_value": code,
            "code_name": text(row.get("color_name")) or code,
            "status": "enabled",
        }
        stats["colors"]["inserted"] += 1
    return result


def upsert_sku(
    cur,
    row: dict[str, Any],
    parent: dict[str, Any],
    execute: bool,
    stats: dict[str, Any],
) -> int | None:
    article_code = text(row.get("article_code"))
    if not article_code:
        stats["skus"]["skipped"] += 1
        stats["skus"]["skipped_rows"].append({"reason": "missing article_code", "row": row})
        return None
    cur.execute(
        """
        select product_id, parent_product_id, product_type, finished_product_code,
               phone_model_code, color_code, import_short_code
        from plm_product
        where product_code = %s or finished_product_code = %s
        order by product_id
        limit 1
        """,
        (article_code, article_code),
    )
    found = cur.fetchone()
    expected = {
        "parent_product_id": parent["product_id"],
        "product_type": "model_variant",
        "finished_product_code": article_code,
        "phone_model_code": text(row.get("model_code")),
        "color_code": text(row.get("color_short_code")) or text(row.get("color_code")),
        "import_short_code": text(row.get("sku_code")) or article_code,
    }
    if found:
        if (
            found[1] != expected["parent_product_id"]
            or found[2] != expected["product_type"]
            or found[3] != expected["finished_product_code"]
        ):
            stats["skus"]["conflicts"] += 1
            stats["skus"]["conflict_rows"].append(
                {"article_code": article_code, "existing": found, "expected": expected}
            )
            return found[0]
        stats["skus"]["existing"] += 1
        return found[0]
    if not execute:
        stats["skus"]["would_insert"] += 1
        return None
    cur.execute(
        """
        insert into plm_product (
            parent_product_id, product_code, product_name, product_type,
            series_name, model, color, version_no, status, remark,
            created_by, updated_by, deleted_flag,
            source_system, source_instance_id,
            product_specific_code, phone_model_code, color_code,
            finished_product_code, import_short_code
        )
        values (
            %s, %s, %s, 'model_variant',
            %s, %s, %s, 'V1', 'archived', %s,
            %s, %s, 0,
            %s, %s, %s, %s, %s, %s, %s
        )
        returning product_id
        """,
        (
            parent["product_id"],
            article_code,
            text(row.get("product_name")) or article_code,
            parent["product_name"],
            text(row.get("phone_model")),
            text(row.get("color_name_zh")) or text(row.get("color")),
            f"seed mes_sku_master; bom_code={text(row.get('bom_code')) or ''}",
            IMPORT_TAG,
            IMPORT_TAG,
            SOURCE_SYSTEM,
            article_code,
            parent["product_specific_code"],
            text(row.get("model_code")),
            text(row.get("color_short_code")) or text(row.get("color_code")),
            article_code,
            text(row.get("sku_code")) or article_code,
        ),
    )
    stats["skus"]["inserted"] += 1
    return cur.fetchone()[0]


def upsert_operation(
    cur,
    product: dict[str, Any],
    base_code: str,
    source_nodes: list[tuple[dict[str, Any], dict[str, Any]]],
    execute: bool,
    stats: dict[str, Any],
) -> int | None:
    process_code = f"PROC-{base_code}"
    first_node, first_route = source_nodes[0]
    config = first_node.get("config_json") or {}
    process_name = text(first_node.get("step_name")) or base_code
    craft_code = base_code[-4:] if len(base_code) >= 4 else base_code
    fixed_color = text(config.get("outputColorCode") or config.get("output_color_code"))
    finished = (config.get("outputType") or "").lower() == "finished"
    param = {
        "source": "master_route_seed.json",
        "sourceOperationCode": first_node.get("operation_code"),
        "outputBaseCode": base_code,
        "outputType": config.get("outputType"),
        "outputColorMode": config.get("outputColorMode") or config.get("output_color_mode"),
        "outputColorCode": fixed_color,
        "sourceRoutes": [route["route_code"] for _, route in source_nodes],
    }
    cur.execute(
        """
        select process_id, process_code, product_id, business_operation_code
        from plm_process
        where process_code = %s
           or (process_type = 'operation' and business_operation_code = %s and deleted_flag = 0)
        order by case when business_operation_code = %s then 0 else 1 end,
                 case when process_code = %s then 0 else 1 end,
                 process_id
        limit 1
        """,
        (process_code, base_code, base_code, process_code),
    )
    found = cur.fetchone()
    if found:
        process_id = found[0]
        if found[1] == process_code and execute:
            cur.execute(
                """
                update plm_process
                set material_status_code = coalesce(material_status_code, %s),
                    finished_product_flag = coalesce(finished_product_flag, %s),
                    business_operation_code = coalesce(business_operation_code, %s),
                    product_specific_code = coalesce(product_specific_code, %s),
                    process_param_json = coalesce(process_param_json, %s::jsonb),
                    updated_at = current_timestamp,
                    updated_by = %s
                where process_id = %s
                """,
                (
                    base_code,
                    finished,
                    base_code,
                    product["product_specific_code"],
                    json.dumps(param, ensure_ascii=False),
                    IMPORT_TAG,
                    process_id,
                ),
            )
        stats["operations"]["existing"] += 1
        return process_id
    if not execute:
        stats["operations"]["would_insert"] += 1
        return None
    cur.execute(
        """
        insert into plm_process (
            product_id, process_code, process_name, process_type,
            sequence_no, operation_craft_code, material_status_code,
            finished_product_flag, business_operation_code,
            product_specific_code, version_no, process_param_json,
            status, remark, created_by, updated_by, deleted_flag
        )
        values (
            %s, %s, %s, 'operation',
            %s, %s, %s, %s, %s,
            %s, %s, %s::jsonb,
            'confirmed', %s, %s, %s, 0
        )
        returning process_id
        """,
        (
            product["product_id"],
            process_code,
            process_name,
            int(first_node.get("step_no") or 1) * 10,
            craft_code,
            base_code,
            finished,
            base_code,
            product["product_specific_code"],
            first_route.get("version") or "V1",
            json.dumps(param, ensure_ascii=False),
            f"seed operation base code; source={first_node.get('operation_code')}",
            IMPORT_TAG,
            IMPORT_TAG,
        ),
    )
    stats["operations"]["inserted"] += 1
    return cur.fetchone()[0]


def upsert_route(
    cur,
    route: dict[str, Any],
    product: dict[str, Any],
    operation_ids: dict[str, int | None],
    execute: bool,
    stats: dict[str, Any],
) -> int | None:
    route_code = route["route_code"]
    route_json = json_route(route, operation_ids)
    cur.execute(
        """
        select process_id
        from plm_process
        where process_code = %s
          and process_type = 'routing'
          and deleted_flag = 0
        limit 1
        """,
        (route_code,),
    )
    found = cur.fetchone()
    if found:
        stats["routes"]["existing"] += 1
        return found[0]
    if not execute:
        stats["routes"]["would_insert"] += 1
        return None
    cur.execute(
        """
        insert into plm_process (
            product_id, process_code, process_name, process_type,
            version_no, process_param_json, status, remark,
            created_by, updated_by, deleted_flag
        )
        values (
            %s, %s, %s, 'routing',
            %s, %s::jsonb, 'confirmed', %s,
            %s, %s, 0
        )
        returning process_id
        """,
        (
            product["product_id"],
            route_code,
            route["route_name"],
            route.get("version") or "V1",
            json.dumps(route_json, ensure_ascii=False),
            "seed route template; color/process relationship reference only",
            IMPORT_TAG,
            IMPORT_TAG,
        ),
    )
    stats["routes"]["inserted"] += 1
    return cur.fetchone()[0]


def upsert_bom(
    cur,
    bom: dict[str, Any],
    product: dict[str, Any],
    route: dict[str, Any],
    route_process_id: int | None,
    color_item: dict[str, Any],
    sku_by_bom_color: dict[tuple[str, str], int | None],
    execute: bool,
    stats: dict[str, Any],
) -> tuple[int | None, int | None]:
    bom_code = bom["bom_code"]
    bom_version = f"{bom.get('version') or 'V1'}-{color_item['code_value']}"
    cur.execute(
        "select product_bom_id, product_id, bom_scope, source_type from plm_product_bom where bom_code = %s",
        (bom_code,),
    )
    found = cur.fetchone()
    if found:
        if found[1] != product["product_id"]:
            stats["boms"]["conflicts"] += 1
            stats["boms"]["conflict_rows"].append(
                {"bom_code": bom_code, "existing_product_id": found[1], "expected_product_id": product["product_id"]}
            )
            return found[0], None
        bom_id = found[0]
        stats["boms"]["existing"] += 1
    elif not execute:
        stats["boms"]["would_insert"] += 1
        return None, None
    else:
        cur.execute(
            """
            insert into plm_product_bom (
                product_id, bom_code, bom_name, bom_type, quantity, uom_code,
                is_active, is_default, with_operations, currency_code,
                version_no, status, bom_scope, source_type, source_product_id,
                remark, created_by, updated_by, deleted_flag
            )
            values (
                %s, %s, %s, 'mbom', %s, 'pcs',
                %s, 0, 1, 'CNY',
                %s, 'draft', 'candidate', 'seed_reference', %s,
                %s, %s, %s, 0
            )
            returning product_bom_id
            """,
            (
                product["product_id"],
                bom_code,
                f"{product['product_name']} seed color reference",
                bom.get("output_qty") or 1,
                1 if bom.get("is_active", True) else 0,
                bom_version,
                product["product_id"],
                (
                    f"source specification={bom.get('custom_bom_specification') or ''}; "
                    "seed reference BOM; color/process relationship only; material lines not imported"
                ),
                IMPORT_TAG,
                IMPORT_TAG,
            ),
        )
        bom_id = cur.fetchone()[0]
        stats["boms"]["inserted"] += 1

    route_id = None
    if route_process_id is None:
        stats["bom_routes"]["skipped"] += 1
        return bom_id, None
    cur.execute(
        """
        select product_bom_route_id
        from plm_product_bom_route
        where product_bom_id = %s
          and process_id = %s
          and route_variant_no = 'BASE'
          and deleted_flag = 0
        limit 1
        """,
        (bom_id, route_process_id),
    )
    found_route = cur.fetchone()
    if found_route:
        route_id = found_route[0]
        stats["bom_routes"]["existing"] += 1
    elif not execute:
        stats["bom_routes"]["would_insert"] += 1
        return bom_id, None
    else:
        cur.execute(
            """
            insert into plm_product_bom_route (
                product_bom_id, product_id, process_id, route_code, route_name,
                status, shared_bom_group_code, route_variant_no, variant_name,
                variant_source_type, created_by, updated_by, deleted_flag
            )
            values (
                %s, %s, %s, %s, %s,
                'active', %s, 'BASE', %s,
                'seed_reference', %s, %s, 0
            )
            returning product_bom_route_id
            """,
            (
                bom_id,
                product["product_id"],
                route_process_id,
                route["route_code"],
                route["route_name"],
                f"SEED-{bom_code}",
                "seed color reference route",
                IMPORT_TAG,
                IMPORT_TAG,
            ),
        )
        route_id = cur.fetchone()[0]
        stats["bom_routes"]["inserted"] += 1

    color_code = color_item["code_value"]
    cur.execute(
        """
        select product_bom_route_color_id
        from plm_product_bom_route_color
        where product_bom_id = %s
          and color_code = %s
          and deleted_flag = 0
        limit 1
        """,
        (bom_id, color_code),
    )
    color_found = cur.fetchone()
    if color_found:
        stats["bom_route_colors"]["existing"] += 1
    elif not execute:
        stats["bom_route_colors"]["would_insert"] += 1
    else:
        cur.execute(
            """
            insert into plm_product_bom_route_color (
                product_bom_id, product_bom_route_id, code_item_id,
                color_code, color_name, status,
                created_by, updated_by, deleted_flag
            )
            values (%s, %s, %s, %s, %s, 'active', %s, %s, 0)
            """,
            (
                bom_id,
                route_id,
                color_item["code_item_id"],
                color_code,
                color_item["code_name"],
                IMPORT_TAG,
                IMPORT_TAG,
            ),
        )
        stats["bom_route_colors"]["inserted"] += 1

    created_sku_product_id = sku_by_bom_color.get((bom_code, color_item["code_value"]))
    cur.execute(
        """
        select product_production_color_decision_id, created_by
        from plm_product_production_color_decision
        where product_id = %s
          and color_code = %s
          and deleted_flag = 0
          and status = 'confirmed'
        limit 1
        """,
        (product["product_id"], color_code),
    )
    decision_found = cur.fetchone()
    if decision_found:
        if execute and decision_found[1] == IMPORT_TAG:
            cur.execute(
                """
                update plm_product_production_color_decision
                set product_bom_id = %s,
                    product_bom_route_id = %s,
                    code_item_id = %s,
                    color_name = %s,
                    created_sku_product_id = %s,
                    updated_at = current_timestamp,
                    updated_by = %s
                where product_production_color_decision_id = %s
                """,
                (
                    bom_id,
                    route_id,
                    color_item["code_item_id"],
                    color_item["code_name"],
                    created_sku_product_id,
                    IMPORT_TAG,
                    decision_found[0],
                ),
            )
        stats["decisions"]["existing"] += 1
    elif not execute:
        stats["decisions"]["would_insert"] += 1
    else:
        cur.execute(
            """
            insert into plm_product_production_color_decision (
                product_id, color_name, product_bom_id, product_bom_route_id,
                code_item_id, color_code, decision_batch_no, selected_flag,
                status, created_sku_product_id, confirmed_at, confirmed_by,
                created_by, updated_by, deleted_flag
            )
            values (
                %s, %s, %s, %s,
                %s, %s, %s, 1,
                'confirmed', %s, current_timestamp, %s,
                %s, %s, 0
            )
            """,
            (
                product["product_id"],
                color_item["code_name"],
                bom_id,
                route_id,
                color_item["code_item_id"],
                color_code,
                f"{IMPORT_TAG}-{product['product_code']}",
                created_sku_product_id,
                IMPORT_TAG,
                IMPORT_TAG,
                IMPORT_TAG,
            ),
        )
        stats["decisions"]["inserted"] += 1
    return bom_id, route_id


def make_stats() -> dict[str, Any]:
    def bucket() -> dict[str, Any]:
        return {"inserted": 0, "existing": 0, "would_insert": 0, "skipped": 0}

    return {
        "products": {"existing": 0, "conflicts": 0},
        "colors": bucket(),
        "skus": {**bucket(), "conflicts": 0, "conflict_rows": [], "skipped_rows": []},
        "operations": bucket(),
        "routes": bucket(),
        "boms": {**bucket(), "conflicts": 0, "conflict_rows": []},
        "bom_routes": bucket(),
        "bom_route_colors": bucket(),
        "decisions": bucket(),
        "source": {},
        "errors": [],
    }


def main() -> int:
    args = parse_args()
    deployment = load_json(args.seed_dir / "deployment_master_data_seed.json")
    route_seed = load_json(args.seed_dir / "master_route_seed.json")
    tables = deployment["tables"]
    stats = make_stats()
    stats["source"] = {
        "deployment_seed": str(args.seed_dir / "deployment_master_data_seed.json"),
        "route_seed": str(args.seed_dir / "master_route_seed.json"),
        "sku_rows": len(tables["mes_sku_master"]),
        "bom_rows": len(tables["bom_main"]),
        "route_rows": len(route_seed["process_routes"]),
        "execute": args.execute,
    }
    for key in ("article_code", "sku_code"):
        duplicate_rows = count_source_duplicates(tables["mes_sku_master"], key)
        if duplicate_rows:
            raise RuntimeError(f"Source SKU {key} duplicates: {duplicate_rows[:5]}")

    routes_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in route_seed["process_routes"]:
        routes_by_product[route["product_code"]].append(route)

    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.database,
        user=args.user,
        password=args.password,
        options=f"-c search_path={args.schema}",
    )
    connection.autocommit = False
    try:
        cur = connection.cursor()
        ensure_required_tables(cur)
        products = fetch_products(cur)
        missing_products = sorted(set(PRODUCT_CODES) - set(products))
        if missing_products:
            raise RuntimeError(f"Expected product lines are missing: {', '.join(missing_products)}")
        for code, product in products.items():
            if product["product_type"] != "product_line":
                raise RuntimeError(f"Product {code} is not a product_line: {product['product_type']}")
            stats["products"]["existing"] += 1

        color_rows_by_code: dict[str, dict[str, Any]] = {}
        for row in tables["mes_color_code"]:
            code = text(row.get("color_code"))
            if code:
                color_rows_by_code.setdefault(code, row)
        for row in tables["mes_product_item_color"]:
            code = text(row.get("color_code"))
            if code and code not in color_rows_by_code:
                color_rows_by_code[code] = {
                    "color_code": code,
                    "color_name": text(row.get("color_name")) or code,
                }
        color_items = resolve_color_items(cur, list(color_rows_by_code.values()), args.execute, stats)

        sku_by_bom_color: dict[tuple[str, str], int | None] = {}
        for row in tables["mes_sku_master"]:
            product_code = text(row.get("product_code"))
            if product_code not in products:
                stats["skus"]["skipped"] += 1
                continue
            sku_id = upsert_sku(cur, row, products[product_code], args.execute, stats)
            bom_code = text(row.get("bom_code"))
            sku_color_code = text(row.get("color_short_code")) or text(row.get("color_code"))
            if bom_code and sku_color_code and (bom_code, sku_color_code) not in sku_by_bom_color and sku_id is not None:
                sku_by_bom_color[(bom_code, sku_color_code)] = sku_id

        nodes_by_base: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for route in route_seed["process_routes"]:
            for node in route.get("nodes", []):
                config = node.get("config_json") or {}
                base_code = text(config.get("outputBaseCode") or config.get("output_base_code"))
                if base_code:
                    nodes_by_base[base_code].append((node, route))

        operation_ids: dict[str, int | None] = {}
        for base_code, source_nodes in sorted(nodes_by_base.items()):
            product_code = source_nodes[0][1]["product_code"]
            operation_ids[base_code] = upsert_operation(
                cur,
                products[product_code],
                base_code,
                source_nodes,
                args.execute,
                stats,
            )

        route_ids: dict[str, int | None] = {}
        for route in route_seed["process_routes"]:
            product = products[route["product_code"]]
            route_ids[route["route_code"]] = upsert_route(
                cur,
                route,
                product,
                operation_ids,
                args.execute,
                stats,
            )

        for bom in tables["bom_main"]:
            product_code = product_code_from_bom(bom["bom_code"])
            color_code = color_code_from_bom(bom["bom_code"])
            product = products[product_code]
            color_item = color_items.get(color_code)
            if not color_item:
                stats["boms"]["conflicts"] += 1
                stats["boms"]["conflict_rows"].append(
                    {"bom_code": bom["bom_code"], "reason": f"missing color dictionary {color_code}"}
                )
                continue
            route = route_for_bom(product_code, color_code, routes_by_product)
            route_process_id = route_ids[route["route_code"]]
            upsert_bom(
                cur,
                bom,
                product,
                route,
                route_process_id,
                color_item,
                sku_by_bom_color,
                args.execute,
                stats,
            )

        if stats["skus"]["conflicts"] or stats["boms"]["conflicts"]:
            raise RuntimeError(
                f"Import conflicts found: sku={stats['skus']['conflicts']}, bom={stats['boms']['conflicts']}"
            )
        if args.execute:
            connection.commit()
        else:
            connection.rollback()
    except Exception as exc:
        connection.rollback()
        stats["errors"].append(str(exc))
        raise
    finally:
        connection.close()

    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
