from __future__ import annotations

import json
import csv
import io
import os
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db
from .cleaning import normalize_model
from .dingtalk_sync import load_config as load_dingtalk_config
from .dingtalk_sync import log_step as log_dingtalk_step
from .dingtalk_sync import sync_one_row_to_dingtalk
from .news_service import collect_news_once
from .presentation import row_to_dict
from .ui import render_app_html
from .internal_api import handle as handle_internal_api

PENDING_MOLDING_STATUS = db.PARTIAL_MOLDING_STATUS
NO_TODAY_NEWS_ERROR = "latest_when_no_today"
NEWS_REFRESH_LOCK = threading.Lock()


def safe_print(message: str) -> None:
    try:
        print(message, flush=True)
    except (BrokenPipeError, OSError, ValueError):
        pass


def parse_optional_float(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return float(text)


def price_filter_args(query: dict[str, str]) -> dict[str, object]:
    return {
        "price_currency": query.get("price_currency") or None,
        "price_min": parse_optional_float(query.get("price_min")),
        "price_max": parse_optional_float(query.get("price_max")),
        "price_bucket": query.get("price_bucket") or "all",
    }


def rows_to_payload(conn, rows, *, table: str | None = None) -> list[dict]:
    materialized = list(rows)
    tipos = db.molding_tipos_for_models(conn, materialized)
    payload = []
    for row in materialized:
        item = row_to_dict(row, molding_tipos=tipos.get((row["brand"].upper(), row["normalized_model"]), []))
        if table is not None:
            item["_table"] = table
        payload.append(item)
    return payload


def news_rows_to_payload(rows) -> list[dict]:
    return [
        {
            "id": row["id"],
            "brand": row["brand"],
            "source_type": row["source_type"],
            "source_name": row["source_name"],
            "title": row["title"],
            "url": row["url"],
            "first_collected_at": row["first_collected_at"],
            "last_collected_at": row["last_collected_at"],
            "seen_date": row["seen_date"],
            "published_at": row["published_at"] if "published_at" in row.keys() else None,
            "collect_window_start": row["collect_window_start"] if "collect_window_start" in row.keys() else None,
            "collect_window_end": row["collect_window_end"] if "collect_window_end" in row.keys() else None,
            "last_error": row["last_error"],
        }
        for row in rows
    ]


def is_news_failure_marker(row) -> bool:
    title = str(row["title"] if "title" in row.keys() else "")
    error = row["last_error"] if "last_error" in row.keys() else None
    return bool(error) and title.endswith(("当日爬取失败", "褰撴棩鐖彇澶辫触"))


def merge_news_rows(*groups) -> list:
    merged = []
    seen = set()
    for rows in groups:
        for row in rows:
            key = (row["brand"], row["source_type"], row["title"], row["url"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def is_no_today_news_error(error: object) -> bool:
    return NO_TODAY_NEWS_ERROR in str(error or "")


def is_successful_news_fallback(error: object) -> bool:
    return "mobile_phone_keyword_filter" in str(error or "")


def classify_news_status(rows) -> dict[str, object]:
    errors = []
    no_today = False
    fallback_note = False
    visible_count = sum(1 for row in rows if not is_news_failure_marker(row))
    for row in rows:
        error = row["last_error"] if "last_error" in row.keys() else None
        if not error:
            continue
        marker = is_news_failure_marker(row)
        if is_no_today_news_error(error):
            no_today = visible_count == 0
            continue
        if is_successful_news_fallback(error):
            fallback_note = True
            if marker and visible_count == 0:
                errors.append(str(error))
            continue
        if marker or visible_count == 0:
            errors.append(str(error))
    crawl_error = errors[0] if errors else None
    empty_today = no_today and visible_count == 0 and not crawl_error
    return {
        "crawl_failed": bool(crawl_error),
        "crawl_error": crawl_error,
        "empty_today": empty_today,
        "empty_message": "今日暂无相关新闻" if empty_today else "",
        "fallback_note": fallback_note,
        "fallback_message": "部分品牌页未命中，已展示手机分区匹配到的新闻" if fallback_note else "",
    }


def news_payload(conn, query: dict[str, str]) -> dict[str, object]:
    fallback_limit = 3
    brand = (query.get("brand") or "").strip().upper() or None
    source_type = (query.get("source_type") or "").strip().lower() or None

    rows = db.list_recent_news_items(
        conn,
        brand=brand,
        source_type=source_type,
    )
    news_status = classify_news_status(rows)
    visible_rows = [row for row in rows if not is_news_failure_marker(row)]
    return {
        "status": "ok",
        "mode": "recent_retained",
        "date": query.get("date") or "today",
        "window_start": None,
        "window_end": None,
        "fallback_used": False,
        "fallback_limit": fallback_limit,
        "retention_days": 7,
        **news_status,
        "items": news_rows_to_payload(visible_rows),
    }


class PhoneWatchHandler(BaseHTTPRequestHandler):
    db_path: str = str(db.DEFAULT_DB)

    def log_message(self, format: str, *args) -> None:
        safe_print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/plain") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_csv(self, filename: str, rows: list[dict]) -> None:
        buffer = io.StringIO()
        fieldnames = [
            "brand",
            "country",
            "source_country",
            "missing_country",
            "model",
            "image_url",
            "price",
            "release_date",
            "launch_date",
            "badge",
            "sale_status",
            "source_name",
            "source_url",
            "reason",
            "sampling_status",
            "molding_tipos",
            "first_seen_at",
            "last_seen_at",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        body = "\ufeff".encode("utf-8") + buffer.getvalue().encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}

        if handle_internal_api(self, "GET", parsed.path, query, self.db_path):
            return

        if parsed.path == "/":
            if os.getenv("PHONE_WATCH_LEGACY_API_ENABLED", "true").lower() != "true":
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            else:
                self.send_text(render_app_html(api_mode=True), content_type="text/html")
            return

        if parsed.path.startswith("/api/") or parsed.path.startswith("/export/"):
            if os.getenv("PHONE_WATCH_LEGACY_API_ENABLED", "true").lower() != "true":
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

        try:
            with db.connect(self.db_path) as conn:
                if parsed.path == "/api/summary":
                    self.send_json(db.summary(conn))
                elif parsed.path == "/api/news":
                    self.send_json(news_payload(conn, query))
                elif parsed.path == "/api/phones":
                    rows = db.list_phones(
                        conn,
                        country=query.get("country") or None,
                        brand=query.get("brand") or None,
                        status=query.get("status") or None,
                        badge=query.get("badge") or None,
                        model_query=query.get("model_query") or None,
                        **price_filter_args(query),
                    )
                    self.send_json(rows_to_payload(conn, rows))
                elif parsed.path == "/api/candidates":
                    rows = db.list_candidates(
                        conn,
                        brand=query.get("brand") or None,
                        status=query.get("status") or None,
                        source_country=query.get("source_country") or None,
                        model_query=query.get("model_query") or None,
                        **price_filter_args(query),
                    )
                    self.send_json(rows_to_payload(conn, rows))
                elif parsed.path == "/api/today":
                    seen_date = query.get("date") or db.latest_collected_date(conn)
                    phones = []
                    candidates = []
                    if seen_date:
                        phones = rows_to_payload(
                            conn,
                            db.list_phones(
                                conn,
                                country=query.get("country") or None,
                                brand=query.get("brand") or None,
                                status=query.get("status") or None,
                                seen_date=seen_date,
                                badge=query.get("badge") or None,
                                **price_filter_args(query),
                            ),
                            table="phones",
                        )
                        candidates = rows_to_payload(
                            conn,
                            db.list_candidates(
                                conn,
                                brand=query.get("brand") or None,
                                status=query.get("status") or None,
                                source_country=None if query.get("country") == "MX" else (query.get("country") or None),
                                seen_date=seen_date,
                                model_query=query.get("model_query") or None,
                                **price_filter_args(query),
                            ),
                            table="candidates",
                        )
                    self.send_json({"date": seen_date, "phones": phones, "candidates": candidates})
                elif parsed.path == "/api/new-today":
                    seen_date = query.get("date") or db.latest_collected_date(conn)
                    previous_date = db.previous_collected_date(conn, seen_date) if seen_date else None
                    phones = []
                    candidates = []
                    if seen_date:
                        phones = rows_to_payload(
                            conn,
                            db.list_new_phones(
                                conn,
                                seen_date=seen_date,
                                country=query.get("country") or None,
                                brand=query.get("brand") or None,
                                status=query.get("status") or None,
                                badge=query.get("badge") or None,
                                **price_filter_args(query),
                            ),
                            table="phones",
                        )
                        candidates = rows_to_payload(
                            conn,
                            db.list_new_candidates(
                                conn,
                                seen_date=seen_date,
                                brand=query.get("brand") or None,
                                status=query.get("status") or None,
                                source_country=None if query.get("country") == "MX" else (query.get("country") or None),
                                **price_filter_args(query),
                            ),
                            table="candidates",
                        )
                    self.send_json(
                        {
                            "date": seen_date,
                            "previous_date": previous_date,
                            "phones": phones,
                            "candidates": candidates,
                        }
                    )
                elif parsed.path == "/api/custom-series":
                    self.send_json([dict(row) for row in db.custom_series_rules(conn)])
                elif parsed.path == "/api/field-options":
                    enabled_only = query.get("enabled_only") == "1"
                    field_names = query.get("field_names")
                    if field_names:
                        names = [name.strip() for name in field_names.split(",") if name.strip()]
                        options = db.field_options_map(conn, names, enabled_only=enabled_only)
                        self.send_json({
                            name: [dict(row) for row in rows]
                            for name, rows in options.items()
                        })
                    else:
                        field_name = query.get("field_name") or "brand"
                        self.send_json([dict(row) for row in db.field_options(conn, field_name, enabled_only=enabled_only)])
                elif parsed.path == "/api/tipo-options":
                    self.send_json([dict(row) for row in db.tipo_options(conn)])
                elif parsed.path == "/api/models/trash":
                    self.send_json({"ok": True, "items": db.trashed_models(conn)})
                elif parsed.path == "/export/phones.csv":
                    rows = db.list_phones(
                        conn,
                        country=query.get("country") or None,
                        brand=query.get("brand") or None,
                        status=query.get("status") or None,
                        badge=query.get("badge") or None,
                        model_query=query.get("model_query") or None,
                        **price_filter_args(query),
                    )
                    self.send_csv("phones.csv", rows_to_payload(conn, rows))
                elif parsed.path == "/export/candidates.csv":
                    rows = db.list_candidates(
                        conn,
                        brand=query.get("brand") or None,
                        status=query.get("status") or None,
                        source_country=query.get("source_country") or None,
                        model_query=query.get("model_query") or None,
                        **price_filter_args(query),
                    )
                    self.send_csv("candidates.csv", rows_to_payload(conn, rows))
                else:
                    self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": f"Invalid price filter: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        if handle_internal_api(self, "POST", parsed.path, query, self.db_path):
            return
        if os.getenv("PHONE_WATCH_LEGACY_API_ENABLED", "true").lower() != "true":
            self.send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path not in {
            "/api/status",
            "/api/status/bulk",
            "/api/labels",
            "/api/labels/bulk",
            "/api/custom-series",
            "/api/custom-series/enabled",
            "/api/dingtalk/sync-one",
            "/api/dingtalk/sync-selected",
            "/api/tipo-options",
            "/api/tipo-options/delete",
            "/api/manual-model",
            "/api/tipo-status",
            "/api/field-options",
            "/api/field-options/enabled",
            "/api/field-options/delete",
            "/api/models/trash",
            "/api/models/restore",
            "/api/models/purge",
            "/api/models/trash/cleanup",
            "/api/news/refresh",
        }:
            self.send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if parsed.path == "/api/news/refresh":
                if not NEWS_REFRESH_LOCK.acquire(blocking=False):
                    self.send_json(
                        {"ok": False, "error": "新闻采集中，请稍后再试"},
                        HTTPStatus.CONFLICT,
                    )
                    return
                try:
                    result = collect_news_once(self.db_path)
                finally:
                    NEWS_REFRESH_LOCK.release()
                self.send_json(result)
                return
            with db.connect(self.db_path) as conn:
                if parsed.path == "/api/models/trash":
                    updated = db.trash_models(
                        conn,
                        payload.get("items", []),
                        reason=str(payload.get("reason") or "manual_bulk_delete"),
                        deleted_by=str(payload.get("deleted_by") or "local_user"),
                        now=payload.get("now") or None,
                    )
                    self.send_json({"ok": True, "updated": updated})
                    return
                if parsed.path == "/api/models/restore":
                    restored = db.restore_models(conn, payload.get("items", []))
                    self.send_json({"ok": True, "restored": restored})
                    return
                if parsed.path == "/api/models/purge":
                    purged = db.purge_models(conn, payload.get("items", []))
                    self.send_json({"ok": True, "purged": purged})
                    return
                if parsed.path == "/api/models/trash/cleanup":
                    purged = db.cleanup_trashed_models(
                        conn,
                        now=payload.get("now") or None,
                    )
                    self.send_json({"ok": True, "purged": purged})
                    return
                if parsed.path == "/api/manual-model":
                    table = str(payload.get("type") or "candidates").strip()
                    if table not in db.VALID_TABLES:
                        raise ValueError("入库类型只能是 phones 或 candidates")

                    brand = str(payload.get("brand") or "").strip().upper()
                    model = str(payload.get("model") or "").strip()
                    source_url = str(payload.get("source_url") or "").strip()
                    if not brand:
                        raise ValueError("品牌不能为空")
                    if not model:
                        raise ValueError("型号不能为空")
                    if not source_url:
                        raise ValueError("来源链接不能为空")

                    sampling_status = db.normalize_sampling_status(payload.get("sampling_status"))
                    if sampling_status not in db.VALID_STATUSES:
                        raise ValueError("开模状态不合法")

                    badge = str(payload.get("badge") or "").strip()
                    if badge not in db.VALID_BADGES:
                        raise ValueError("标签不合法")

                    sale_status = str(payload.get("sale_status") or "").strip()
                    if sale_status not in db.VALID_SALE_STATUSES:
                        raise ValueError("销售状态不合法")

                    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    normalized_model = normalize_model(model, brand)

                    if table == "phones":
                        country = str(payload.get("country") or payload.get("source_country") or "MX").strip().upper()
                        db.upsert_phone(conn, {
                            "brand": brand,
                            "country": country,
                            "model": model,
                            "normalized_model": normalized_model,
                            "image_url": payload.get("image_url") or None,
                            "price": payload.get("price") or None,
                            "release_date": payload.get("release_date") or None,
                            "launch_date": payload.get("launch_date") or None,
                            "source_url": source_url,
                            "source_name": payload.get("source_name") or "Manual",
                            "badge": badge or None,
                            "first_seen_at": now,
                            "last_seen_at": now,
                            "sampling_status": sampling_status,
                            "clean_stage": "manual",
                        })
                        rows = db.list_phones(conn, brand=brand, country=country)
                    else:
                        source_country = str(payload.get("source_country") or "CN").strip().upper()
                        missing_country = str(payload.get("missing_country") or "MX").strip().upper()
                        db.upsert_candidate(conn, {
                            "brand": brand,
                            "source_country": source_country,
                            "missing_country": missing_country,
                            "model": model,
                            "normalized_model": normalized_model,
                            "image_url": payload.get("image_url") or None,
                            "price": payload.get("price") or None,
                            "release_date": payload.get("release_date") or None,
                            "launch_date": payload.get("launch_date") or None,
                            "source_url": source_url,
                            "source_name": payload.get("source_name") or "Manual",
                            "reason": payload.get("reason") or "人工添加",
                            "first_seen_at": now,
                            "last_seen_at": now,
                            "sampling_status": sampling_status,
                        })
                        rows = [
                            row for row in db.list_candidates(conn, brand=brand, source_country=source_country)
                            if row["missing_country"] == missing_country
                        ]

                    saved = next((row for row in rows if row["normalized_model"] == normalized_model), None)
                    if saved and (badge or sale_status):
                        db.set_display_labels(
                            conn,
                            table,
                            int(saved["id"]),
                            badge=badge or None,
                            sale_status=sale_status or None,
                        )

                    db.upsert_field_option(
                        conn,
                        field_name=db.MANAGED_FIELD_BRAND,
                        value=brand,
                        label=brand,
                        enabled=True,
                    )
                    self.send_json({
                        "ok": True,
                        "type": table,
                        "normalized_model": normalized_model,
                        "message": "已保存手动添加型号",
                    })
                    return
                if parsed.path == "/api/tipo-status":
                    table = str(payload["type"])
                    item_id = int(payload["id"])
                    tipo_name = str(payload["tipo_name"]).strip()
                    status = str(payload["status"]).strip()
                    if table not in db.VALID_TABLES:
                        raise ValueError("type 必须是 phones 或 candidates")
                    if not tipo_name:
                        raise ValueError("tipo_name 不能为空")
                    if status not in db.VALID_TIPO_STATUSES:
                        raise ValueError("status 必须是 待开模 或 已开模")
                    row = conn.execute(
                        f"SELECT * FROM {table} WHERE id = ?", (item_id,)
                    ).fetchone()
                    if not row:
                        raise ValueError(f"{table} id={item_id} 不存在")
                    db.upsert_molding_tipo(
                        conn,
                        brand=row["brand"],
                        normalized_model=row["normalized_model"],
                        source_table=table,
                        source_id=item_id,
                        tipo_name=tipo_name,
                        status=status,
                    )
                    aggregate = db.compute_molding_status(conn, row["brand"], row["normalized_model"])
                    current = conn.execute(
                        f"SELECT sampling_status FROM {table} WHERE id = ?", (item_id,)
                    ).fetchone()["sampling_status"]
                    if current != "忽略":
                        db.set_sampling_status(conn, table, item_id, aggregate)
                    else:
                        aggregate = "忽略"
                    self.send_json({"ok": True, "aggregate_status": aggregate})
                    return
                if parsed.path == "/api/field-options":
                    result = db.upsert_field_option(
                        conn,
                        field_name=str(payload.get("field_name") or "brand"),
                        value=str(payload["value"]),
                        label=payload.get("label"),
                        enabled=bool(payload.get("enabled", True)),
                        sort_order=int(payload.get("sort_order") or 0),
                        option_id=int(payload["id"]) if payload.get("id") else None,
                    )
                    self.send_json({"ok": True, "updated": result})
                    return
                if parsed.path == "/api/field-options/enabled":
                    updated = db.set_field_option_enabled(conn, int(payload["id"]), bool(payload["enabled"]))
                    self.send_json({"ok": True, "updated": updated})
                    return
                if parsed.path == "/api/field-options/delete":
                    deleted = db.delete_field_option(conn, int(payload["id"]))
                    self.send_json({"ok": True, "deleted": deleted})
                    return
                if parsed.path == "/api/tipo-options":
                    result = db.upsert_tipo_option(
                        conn,
                        str(payload["name"]),
                        bool(payload.get("enabled", True)),
                        int(payload["id"]) if payload.get("id") else None,
                    )
                    self.send_json({"ok": True, "updated": result})
                    return
                if parsed.path == "/api/tipo-options/delete":
                    deleted = db.delete_tipo_option(conn, int(payload["id"]))
                    self.send_json({"ok": True, "deleted": deleted})
                    return
                if parsed.path == "/api/dingtalk/sync-one":
                    table = str(payload["type"])
                    item_id = int(payload["id"])
                    dry_run = bool(payload.get("dry_run", False))
                    tipo_values = [str(value).strip() for value in payload.get("tipo_values", []) if str(value).strip()]
                    if not tipo_values:
                        raise ValueError("请选择至少一个 Tipo类型")
                    results = []
                    aggregate = None
                    log_dingtalk_step("web sync-one request", source_table=table, source_id=item_id, dry_run=dry_run)
                    for tipo_value in tipo_values:
                        results.append(sync_one_row_to_dingtalk(
                            conn,
                            config=load_dingtalk_config(),
                            source_table=table,
                            source_id=item_id,
                            dry_run=dry_run,
                            tipo_value=tipo_value,
                        ))
                    if all(result.get("ok") for result in results) and not dry_run:
                        row = conn.execute(
                            f"SELECT * FROM {table} WHERE id = ?", (item_id,)
                        ).fetchone()
                        if row:
                            for tipo_value in tipo_values:
                                db.upsert_molding_tipo(
                                    conn,
                                    brand=row["brand"],
                                    normalized_model=row["normalized_model"],
                                    source_table=table,
                                    source_id=item_id,
                                    tipo_name=tipo_value,
                                    status=db.TIPO_DONE_STATUS,
                                    synced_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                )
                            aggregate = db.compute_molding_status(
                                conn,
                                row["brand"],
                                row["normalized_model"],
                                all_required_tipos_done=True,
                            )
                            db.set_sampling_status(conn, table, item_id, aggregate)
                    self.send_json({"ok": all(result.get("ok") for result in results), "results": results, "sampling_status": aggregate if not dry_run else None})
                    return
                if parsed.path == "/api/dingtalk/sync-selected":
                    items = payload.get("items", [])
                    dry_run = bool(payload.get("dry_run", False))
                    results = []
                    log_dingtalk_step("web sync-selected request", count=len(items), dry_run=dry_run)
                    for item in items:
                        table = str(item["type"])
                        item_id = int(item["id"])
                        tipo_values = [str(value).strip() for value in item.get("tipo_values", payload.get("tipo_values", [])) if str(value).strip()]
                        if not tipo_values:
                            results.append({"ok": False, "source_table": table, "source_id": item_id, "error": "请选择至少一个 Tipo类型"})
                            continue
                        item_ok = True
                        for tipo_value in tipo_values:
                            try:
                                result = sync_one_row_to_dingtalk(
                                    conn,
                                    config=load_dingtalk_config(),
                                    source_table=table,
                                    source_id=item_id,
                                    dry_run=dry_run,
                                    tipo_value=tipo_value,
                                )
                                if result.get("ok") and not dry_run:
                                    result["sampling_status"] = db.TIPO_DONE_STATUS
                                else:
                                    item_ok = False
                                results.append(result)
                            except Exception as exc:
                                item_ok = False
                                log_dingtalk_step("web sync-selected item failed", source_table=table, source_id=item_id, tipo=tipo_value, error=exc)
                                results.append({"ok": False, "source_table": table, "source_id": item_id, "tipo": tipo_value, "error": str(exc)})
                        if item_ok and not dry_run:
                            row = conn.execute(
                                f"SELECT * FROM {table} WHERE id = ?", (item_id,)
                            ).fetchone()
                            if row:
                                for tipo_value in tipo_values:
                                    db.upsert_molding_tipo(
                                        conn,
                                        brand=row["brand"],
                                        normalized_model=row["normalized_model"],
                                        source_table=table,
                                        source_id=item_id,
                                        tipo_name=tipo_value,
                                        status=db.TIPO_DONE_STATUS,
                                        synced_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    )
                                aggregate = db.compute_molding_status(
                                    conn,
                                    row["brand"],
                                    row["normalized_model"],
                                    all_required_tipos_done=True,
                                )
                                db.set_sampling_status(conn, table, item_id, aggregate)
                    ok_count = sum(1 for result in results if result.get("ok"))
                    self.send_json({"ok": ok_count == len(results), "selected": len(results), "synced": ok_count, "failed": len(results) - ok_count, "results": results})
                    return
                if parsed.path == "/api/custom-series":
                    db.upsert_custom_series_rule(
                        conn,
                        str(payload["brand"]),
                        str(payload["series_name"]),
                        bool(payload.get("enabled", True)),
                    )
                    self.send_json({"ok": True})
                    return
                if parsed.path == "/api/custom-series/enabled":
                    updated = db.set_custom_series_rule_enabled(conn, int(payload["id"]), bool(payload["enabled"]))
                    self.send_json({"ok": True, "updated": updated})
                    return

                table = str(payload["type"])
                if parsed.path == "/api/labels":
                    db.set_display_labels(
                        conn,
                        table,
                        int(payload["id"]),
                        badge=payload.get("badge"),
                        sale_status=payload.get("sale_status"),
                    )
                    self.send_json({"ok": True, "updated": 1})
                    return
                if parsed.path == "/api/labels/bulk":
                    updated = db.set_display_labels_bulk(
                        conn,
                        table,
                        payload.get("ids", []),
                        badge=payload.get("badge"),
                        sale_status=payload.get("sale_status"),
                    )
                    self.send_json({"ok": True, "updated": updated})
                    return

                status = str(payload["status"])
                if parsed.path == "/api/status":
                    db.set_sampling_status(conn, table, int(payload["id"]), status)
                    updated = 1
                else:
                    updated = db.set_sampling_statuses(conn, table, payload.get("ids", []), status)
            self.send_json({"ok": True, "updated": updated})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        if not handle_internal_api(self, "PATCH", parsed.path, query, self.db_path):
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)


def run_server(db_path: str | Path, *, host: str = "127.0.0.1", port: int = 8000) -> None:
    PhoneWatchHandler.db_path = str(db_path)
    server = ThreadingHTTPServer((host, port), PhoneWatchHandler)
    safe_print(f"网页已启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        safe_print("网页已停止")
    finally:
        server.server_close()
