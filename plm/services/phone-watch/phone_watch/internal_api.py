from __future__ import annotations

import csv
import hmac
import io
import json
import os
import re
from http import HTTPStatus
from typing import Any

from . import db
from .presentation import row_to_dict


INTERNAL_PREFIX = "/internal/v1"
KIND_TO_TABLE = {"phone": "phones", "candidate": "candidates"}
TABLE_TO_KIND = {value: key for key, value in KIND_TO_TABLE.items()}


def _configured_token() -> str:
    return os.getenv("PHONE_WATCH_INTERNAL_TOKEN", "").strip()


def _authorized(headers: Any) -> tuple[bool, HTTPStatus, str]:
    expected = _configured_token()
    if not expected:
        return False, HTTPStatus.SERVICE_UNAVAILABLE, "internal service token is not configured"
    supplied = str(headers.get("Authorization") or "")
    if not supplied.startswith("Bearer "):
        return False, HTTPStatus.UNAUTHORIZED, "unauthorized"
    actual = supplied[7:].strip()
    if not hmac.compare_digest(actual, expected):
        return False, HTTPStatus.UNAUTHORIZED, "unauthorized"
    return True, HTTPStatus.OK, ""


def _kind(value: str | None) -> tuple[str, str]:
    kind = str(value or "phone").strip().lower()
    table = KIND_TO_TABLE.get(kind)
    if table is None:
        raise ValueError("kind must be phone or candidate")
    return kind, table


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    number = int(value or default)
    if number < 1 or number > maximum:
        raise ValueError(f"value must be between 1 and {maximum}")
    return number


def _read_json(handler: Any) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _payload_rows(conn: Any, rows: list[Any], kind: str) -> list[dict[str, Any]]:
    tipos = db.molding_tipos_for_models(conn, rows)
    result: list[dict[str, Any]] = []
    for row in rows:
        item = row_to_dict(
            row,
            molding_tipos=tipos.get((str(row["brand"]).upper(), row["normalized_model"]), []),
        )
        item["kind"] = kind
        price_currency, price_amount = db.parse_price_for_filter(item.get("price"))
        item["priceCurrency"] = price_currency
        item["priceAmount"] = price_amount
        result.append(item)
    return result


def _filters(kind: str, query: dict[str, str]) -> tuple[list[str], list[Any]]:
    filters = ["deleted_at IS NULL"]
    params: list[Any] = []
    keyword = str(query.get("keyword") or "").strip().lower()
    if keyword:
        escaped = db.escape_like(keyword)
        filters.append(
            "(lower(model) LIKE ? ESCAPE '\\' OR lower(normalized_model) LIKE ? ESCAPE '\\' "
            "OR lower(brand) LIKE ? ESCAPE '\\' OR lower(COALESCE(source_name,'')) LIKE ? ESCAPE '\\')"
        )
        pattern = f"%{escaped}%"
        params.extend([pattern, pattern, pattern, pattern])
    brand = str(query.get("brand") or "").strip().upper()
    if brand:
        filters.append("brand = ?")
        params.append(brand)
    country = str(query.get("country") or "").strip().upper()
    if country:
        if kind == "phone":
            filters.append("country = ?")
            params.append(country)
        else:
            filters.append("(source_country = ? OR missing_country = ?)")
            params.extend([country, country])
    source = str(query.get("source") or "").strip().lower()
    if source:
        filters.append("lower(COALESCE(source_name,'')) LIKE ? ESCAPE '\\'")
        params.append(f"%{db.escape_like(source)}%")
    status = str(query.get("status") or "").strip()
    if status:
        db.validate_status_table(KIND_TO_TABLE[kind], status)
        filters.append("sampling_status = ?")
        params.append(db.normalize_sampling_status(status))
    date_from = str(query.get("dateFrom") or "").strip()
    if date_from:
        filters.append("substr(last_seen_at,1,10) >= ?")
        params.append(date_from)
    date_to = str(query.get("dateTo") or "").strip()
    if date_to:
        filters.append("substr(last_seen_at,1,10) <= ?")
        params.append(date_to)
    return filters, params


def list_items(conn: Any, query: dict[str, str], *, paged: bool = True) -> dict[str, Any] | list[dict[str, Any]]:
    kind, table = _kind(query.get("kind"))
    filters, params = _filters(kind, query)
    where = " AND ".join(filters)
    if not paged:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY last_seen_at DESC, id DESC",
            params,
        ).fetchall()
        return _payload_rows(conn, rows, kind)

    page = _positive_int(query.get("page"), 1, 1_000_000)
    size = _positive_int(query.get("size"), 20, 100)
    total_row = conn.execute(f"SELECT COUNT(*) AS total FROM {table} WHERE {where}", params).fetchone()
    total = int(total_row["total"] if total_row else 0)
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {where} ORDER BY last_seen_at DESC, id DESC LIMIT ? OFFSET ?",
        [*params, size, (page - 1) * size],
    ).fetchall()
    return {
        "content": _payload_rows(conn, rows, kind),
        "page": page,
        "size": size,
        "totalElements": total,
        "totalPages": (total + size - 1) // size,
    }


def _item(conn: Any, kind: str, item_id: int) -> dict[str, Any] | None:
    _, table = _kind(kind)
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ? AND deleted_at IS NULL",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    return _payload_rows(conn, [row], kind)[0]


def _update_one(conn: Any, kind: str, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _, table = _kind(kind)
    if "status" in payload:
        db.set_sampling_status(conn, table, item_id, str(payload["status"]))
    if "badge" in payload or "saleStatus" in payload:
        db.set_display_labels(
            conn,
            table,
            item_id,
            badge=payload.get("badge"),
            sale_status=payload.get("saleStatus"),
        )
    updated = _item(conn, kind, item_id)
    if updated is None:
        raise LookupError("item not found")
    return updated


def _update_bulk(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    kind, table = _kind(str(payload.get("kind") or ""))
    ids = [int(value) for value in payload.get("ids", [])]
    if not ids or len(ids) > 500:
        raise ValueError("ids must contain between 1 and 500 items")
    updated = 0
    if "status" in payload:
        updated = max(updated, db.set_sampling_statuses(conn, table, ids, str(payload["status"])))
    if "badge" in payload or "saleStatus" in payload:
        updated = max(
            updated,
            db.set_display_labels_bulk(
                conn,
                table,
                ids,
                badge=payload.get("badge"),
                sale_status=payload.get("saleStatus"),
            ),
        )
    return {"kind": kind, "updated": updated}


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    fields = [
        "id", "kind", "brand", "country", "source_country", "missing_country", "model",
        "price", "badge", "sale_status", "sampling_status", "source_name", "source_url",
        "first_seen_at", "last_seen_at",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _send_csv(handler: Any, filename: str, rows: list[dict[str, Any]]) -> None:
    body = _csv_bytes(rows)
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _item_path(path: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"/internal/v1/items/(phone|candidate)/(\d+)", path)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def handle(handler: Any, method: str, path: str, query: dict[str, str], db_path: str) -> bool:
    if not path.startswith(INTERNAL_PREFIX):
        return False
    allowed, status, error = _authorized(handler.headers)
    if not allowed:
        handler.send_json({"error": error}, status)
        return True
    try:
        if method == "GET" and path == f"{INTERNAL_PREFIX}/health":
            handler.send_json({"status": "ok", **db.check_connection(db_path)})
            return True
        with db.connect(db_path) as conn:
            if method == "GET" and path == f"{INTERNAL_PREFIX}/summary":
                handler.send_json(db.summary(conn))
                return True
            if method == "GET" and path == f"{INTERNAL_PREFIX}/items":
                handler.send_json(list_items(conn, query))
                return True
            if method == "GET" and path == f"{INTERNAL_PREFIX}/export.csv":
                kind, _ = _kind(query.get("kind"))
                _send_csv(handler, f"phone-watch-{kind}.csv", list_items(conn, query, paged=False))
                return True
            item_path = _item_path(path)
            if method == "GET" and item_path:
                item = _item(conn, *item_path)
                if item is None:
                    handler.send_json({"error": "item not found"}, HTTPStatus.NOT_FOUND)
                else:
                    handler.send_json(item)
                return True
            if method == "PATCH" and item_path:
                handler.send_json(_update_one(conn, *item_path, _read_json(handler)))
                return True
            if method == "POST" and path == f"{INTERNAL_PREFIX}/items/bulk":
                handler.send_json(_update_bulk(conn, _read_json(handler)))
                return True
        handler.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
    except LookupError as exc:
        handler.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        handler.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
    except Exception:
        # Do not return database, driver, credential, or crawler details to callers.
        handler.send_json({"error": "internal service failure"}, HTTPStatus.INTERNAL_SERVER_ERROR)
    return True
