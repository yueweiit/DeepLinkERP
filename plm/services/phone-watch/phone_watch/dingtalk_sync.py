from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import db

LOGGER = logging.getLogger("phone_watch.dingtalk")


SYNC_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS dingtalk_process_sync (
    id SERIAL PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    process_instance_id TEXT,
    synced_at TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (source_table, source_id)
);
"""

SQLITE_SYNC_TABLE_SCHEMA = SYNC_TABLE_SCHEMA.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")

SYNCABLE_TABLES = {"phones", "candidates"}


def configure_logging() -> None:
    if LOGGER.handlers:
        return
    log_dir = os.getenv("PHONE_WATCH_LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(os.path.join(log_dir, "dingtalk_sync.log"), encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(stream_handler)
    LOGGER.addHandler(file_handler)
    LOGGER.propagate = False


def log_step(message: str, **extra: Any) -> None:
    configure_logging()
    suffix = " ".join(f"{key}={value}" for key, value in extra.items() if value is not None)
    LOGGER.info("%s%s", message, f" {suffix}" if suffix else "")


@dataclass(frozen=True)
class DingTalkConfig:
    app_key: str
    app_secret: str
    agent_id: str
    process_code: str
    originator_user_id: str
    approver_user_id: str
    dept_id: str
    token_url: str = "https://oapi.dingtalk.com/gettoken"


def env_value(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def load_config() -> DingTalkConfig:
    return DingTalkConfig(
        app_key=env_value("DINGTALK_TOKEN_APP_KEY", env_value("DINGTALK_APP_KEY")),
        app_secret=env_value("DINGTALK_TOKEN_APP_SECRET", env_value("DINGTALK_APP_SECRET")),
        agent_id=env_value("DINGTALK_AGENT_ID"),
        process_code=env_value("DINGTALK_PROCESS_CODE"),
        originator_user_id=env_value("DINGTALK_ORIGINATOR_USER_ID"),
        approver_user_id=env_value("DINGTALK_APPROVER_USER_ID"),
        dept_id=env_value("DINGTALK_DEPT_ID", "-1"),
        token_url=env_value("DINGTALK_TOKEN_URL", "https://oapi.dingtalk.com/gettoken"),
    )


def validate_config(config: DingTalkConfig) -> None:
    missing = [
        name
        for name, value in (
            ("DINGTALK_TOKEN_APP_KEY or DINGTALK_APP_KEY", config.app_key),
            ("DINGTALK_TOKEN_APP_SECRET or DINGTALK_APP_SECRET", config.app_secret),
            ("DINGTALK_AGENT_ID", config.agent_id),
            ("DINGTALK_PROCESS_CODE", config.process_code),
            ("DINGTALK_ORIGINATOR_USER_ID", config.originator_user_id),
            ("DINGTALK_DEPT_ID", config.dept_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing DingTalk configuration: " + ", ".join(missing))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_sync_table(conn: Any) -> None:
    log_step("ensure sync table")
    conn.executescript(SQLITE_SYNC_TABLE_SCHEMA if not db.is_postgres_connection(conn) else SYNC_TABLE_SCHEMA)


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DingTalk HTTP {exc.code}: {raw}") from exc
    return json.loads(raw)


def get_access_token(config: DingTalkConfig, *, timeout: int = 20) -> str:
    log_step("request dingtalk access token", token_url=config.token_url)
    query = urllib.parse.urlencode({"appkey": config.app_key, "appsecret": config.app_secret})
    url = f"{config.token_url}?{query}"
    result = http_json(url, timeout=timeout)
    if int(result.get("errcode", -1)) != 0:
        log_step("dingtalk access token failed", result=result)
        raise RuntimeError(f"DingTalk token failed: {result}")
    log_step("dingtalk access token ok")
    return str(result["access_token"])


def create_process_instance(
    token: str,
    config: DingTalkConfig,
    form_values: list[dict[str, str]],
    *,
    timeout: int = 20,
) -> str:
    log_step("create dingtalk process start", form_fields=[item["name"] for item in form_values])
    log_step("create dingtalk process form values", form_values=json.dumps(form_values, ensure_ascii=False))
    url = "https://oapi.dingtalk.com/topapi/processinstance/create"
    url = f"{url}?{urllib.parse.urlencode({'access_token': token})}"
    body = {
        "agent_id": int(config.agent_id),
        "process_code": config.process_code,
        "originator_user_id": config.originator_user_id,
        "dept_id": int(config.dept_id),
        "form_component_values": form_values,
    }
    if config.approver_user_id:
        body["approvers_v2"] = [
            {
                "task_action_type": "AND",
                "user_ids": [config.approver_user_id],
            }
        ]
    result = http_json(url, method="POST", body=body, timeout=timeout)
    if int(result.get("errcode", -1)) != 0:
        log_step("create dingtalk process failed", result=result)
        raise RuntimeError(f"DingTalk create process failed: {result}")
    log_step("create dingtalk process ok", process_instance_id=result.get("process_instance_id"))
    return str(result["process_instance_id"])


def select_rows(
    conn: Any,
    *,
    source_table: str,
    status: str | None,
    seen_date: str | None,
    limit: int,
) -> list[Any]:
    if source_table not in SYNCABLE_TABLES:
        raise ValueError(f"source_table must be one of: {', '.join(sorted(SYNCABLE_TABLES))}")

    filters = [
        "NOT EXISTS (SELECT 1 FROM dingtalk_process_sync d WHERE d.source_table = ? AND d.source_id = s.id AND d.status = 'synced')"
    ]
    params: list[Any] = [source_table]
    if status:
        filters.append("s.sampling_status = ?")
        params.append(status)
    if seen_date:
        filters.append("substr(s.first_seen_at, 1, 10) = ?")
        params.append(seen_date)
    params.append(limit)
    return conn.execute(
        f"""
        SELECT s.id, s.model, s.price, s.source_url, s.source_name, s.first_seen_at, s.last_seen_at
        FROM {source_table} s
        WHERE {' AND '.join(filters)}
        ORDER BY s.first_seen_at DESC, s.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()


def select_row_by_id(conn: Any, *, source_table: str, source_id: int) -> Any | None:
    if source_table not in SYNCABLE_TABLES:
        raise ValueError(f"source_table must be one of: {', '.join(sorted(SYNCABLE_TABLES))}")
    return conn.execute(
        f"""
        SELECT id, model, price, source_url, source_name, first_seen_at, last_seen_at
        FROM {source_table}
        WHERE id = ?
        """,
        (source_id,),
    ).fetchone()


def row_form_values(
    row: Any,
    *,
    model_field: str,
    price_field: str,
    page_field: str,
    sales_channel_field: str,
    tipo_value: str | None = None,
    tipo_field: str = "Tipo类型",
) -> list[dict[str, str]]:
    values = [
        {"name": model_field, "value": str(row["model"] or "")},
        {"name": page_field, "value": str(row["source_url"] or "")},
        {"name": sales_channel_field, "value": str(row["source_name"] or "")},
    ]
    price = str(row["price"] or "").strip()
    if price:
        values.insert(1, {"name": price_field, "value": normalize_form_price(price)})
    network_field = env_value("DINGTALK_NETWORK_FIELD")
    network_default = env_value("DINGTALK_NETWORK_DEFAULT")
    if network_field and network_default:
        values.append({"name": network_field, "value": network_default})
    mold_mark_field = env_value("DINGTALK_MOLD_MARK_FIELD") or "Selle en el molde模具印字"
    if mold_mark_field:
        values.append({"name": mold_mark_field, "value": str(row["model"] or "")})
    if tipo_value:
        values.append({"name": tipo_field, "value": str(tipo_value)})
    return values


def normalize_form_price(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = cleaned.replace(",", "").replace("，", "")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    return match.group(0) if match else cleaned


def upsert_sync_result(
    conn: Any,
    *,
    source_table: str,
    source_id: int,
    status: str,
    payload: dict[str, Any],
    process_instance_id: str | None = None,
    error: str | None = None,
) -> None:
    if db.is_postgres_connection(conn):
        conn.execute(
            """
            INSERT INTO dingtalk_process_sync (
                source_table, source_id, process_instance_id, synced_at, status, error, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_table, source_id) DO UPDATE SET
                process_instance_id = excluded.process_instance_id,
                synced_at = excluded.synced_at,
                status = excluded.status,
                error = excluded.error,
                payload = excluded.payload
            """,
            (source_table, source_id, process_instance_id, now_utc(), status, error, json.dumps(payload, ensure_ascii=False)),
        )
        return
    conn.execute(
        """
        INSERT INTO dingtalk_process_sync (
            source_table, source_id, process_instance_id, synced_at, status, error, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_table, source_id) DO UPDATE SET
            process_instance_id = excluded.process_instance_id,
            synced_at = excluded.synced_at,
            status = excluded.status,
            error = excluded.error,
            payload = excluded.payload
        """,
        (source_table, source_id, process_instance_id, now_utc(), status, error, json.dumps(payload, ensure_ascii=False)),
    )


def sync_rows_to_dingtalk(
    conn: Any,
    *,
    config: DingTalkConfig,
    source_table: str = "candidates",
    status: str | None = None,
    seen_date: str | None = None,
    limit: int = 50,
    dry_run: bool = False,
    timeout: int = 20,
    model_field: str = "Modelos型号",
    price_field: str = "价格Precio de Celular",
    page_field: str = "网站链接Pagina",
    sales_channel_field: str = "销售渠道 Canales venta",
    tipo_field: str = "Tipo类型",
) -> dict[str, int]:
    log_step("batch dingtalk sync start", source_table=source_table, status=status, seen_date=seen_date, limit=limit, dry_run=dry_run)
    ensure_sync_table(conn)
    if not dry_run:
        validate_config(config)
    rows = select_rows(conn, source_table=source_table, status=status, seen_date=seen_date, limit=limit)
    counts = {"selected": len(rows), "synced": 0, "failed": 0, "skipped": 0}
    log_step("batch dingtalk rows selected", selected=len(rows))
    token = "" if dry_run else get_access_token(config, timeout=timeout)

    for row in rows:
        log_step("batch dingtalk row start", source_table=source_table, source_id=row["id"], model=row["model"])
        form_values = row_form_values(
            row,
            model_field=model_field,
            price_field=price_field,
            page_field=page_field,
            sales_channel_field=sales_channel_field,
            tipo_value=None,
            tipo_field=tipo_field,
        )
        payload = {"form_component_values": form_values, "source_table": source_table, "source_id": row["id"]}
        if dry_run:
            upsert_sync_result(conn, source_table=source_table, source_id=row["id"], status="dry_run", payload=payload)
            counts["skipped"] += 1
            log_step("batch dingtalk row dry-run", source_table=source_table, source_id=row["id"], model=row["model"])
            continue
        try:
            instance_id = create_process_instance(token, config, form_values, timeout=timeout)
            upsert_sync_result(
                conn,
                source_table=source_table,
                source_id=row["id"],
                status="synced",
                process_instance_id=instance_id,
                payload=payload,
            )
            counts["synced"] += 1
            log_step("batch dingtalk row synced", source_table=source_table, source_id=row["id"], model=row["model"], process_instance_id=instance_id)
            time.sleep(0.2)
        except Exception as exc:  # keep batch moving and store the exact failed row
            upsert_sync_result(
                conn,
                source_table=source_table,
                source_id=row["id"],
                status="failed",
                error=str(exc),
                payload=payload,
            )
            counts["failed"] += 1
            log_step("batch dingtalk row failed", source_table=source_table, source_id=row["id"], model=row["model"], error=exc)
    log_step("batch dingtalk sync done", selected=counts["selected"], synced=counts["synced"], failed=counts["failed"], skipped=counts["skipped"])
    return counts


def sync_one_row_to_dingtalk(
    conn: Any,
    *,
    config: DingTalkConfig,
    source_table: str,
    source_id: int,
    dry_run: bool = False,
    timeout: int = 20,
    model_field: str = "Modelos型号",
    price_field: str = "价格Precio de Celular",
    page_field: str = "网站链接Pagina",
    sales_channel_field: str = "销售渠道 Canales venta",
    tipo_value: str | None = None,
    tipo_field: str = "Tipo类型",
) -> dict[str, Any]:
    log_step("single dingtalk sync start", source_table=source_table, source_id=source_id, dry_run=dry_run)
    ensure_sync_table(conn)
    if not dry_run:
        validate_config(config)

    row = select_row_by_id(conn, source_table=source_table, source_id=source_id)
    if row is None:
        log_step("single dingtalk row not found", source_table=source_table, source_id=source_id)
        raise ValueError(f"{source_table} id={source_id} not found")

    form_values = row_form_values(
        row,
        model_field=model_field,
        price_field=price_field,
        page_field=page_field,
        sales_channel_field=sales_channel_field,
        tipo_value=tipo_value,
        tipo_field=tipo_field,
    )
    payload = {"form_component_values": form_values, "source_table": source_table, "source_id": row["id"], "tipo": tipo_value}
    log_step("single dingtalk form built", source_table=source_table, source_id=row["id"], model=row["model"], tipo=tipo_value)

    if dry_run:
        upsert_sync_result(conn, source_table=source_table, source_id=row["id"], status="dry_run", payload=payload)
        log_step("single dingtalk dry-run done", source_table=source_table, source_id=row["id"], model=row["model"])
        return {
            "ok": True,
            "status": "dry_run",
            "source_table": source_table,
            "source_id": row["id"],
            "model": row["model"],
            "tipo": tipo_value,
            "form_component_values": form_values,
        }

    try:
        token = get_access_token(config, timeout=timeout)
        instance_id = create_process_instance(token, config, form_values, timeout=timeout)
        upsert_sync_result(
            conn,
            source_table=source_table,
            source_id=row["id"],
            status="synced",
            process_instance_id=instance_id,
            payload=payload,
        )
        log_step("single dingtalk synced", source_table=source_table, source_id=row["id"], model=row["model"], process_instance_id=instance_id)
        return {
            "ok": True,
            "status": "synced",
            "source_table": source_table,
            "source_id": row["id"],
            "model": row["model"],
            "tipo": tipo_value,
            "process_instance_id": instance_id,
        }
    except Exception as exc:
        upsert_sync_result(
            conn,
            source_table=source_table,
            source_id=row["id"],
            status="failed",
            error=str(exc),
            payload=payload,
        )
        log_step("single dingtalk failed", source_table=source_table, source_id=row["id"], model=row["model"], error=exc)
        raise
