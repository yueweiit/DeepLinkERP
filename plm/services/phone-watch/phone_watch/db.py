from __future__ import annotations

import json
import os
import re
import sqlite3
import ipaddress
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover - optional production dependency
    psycopg2 = None
    RealDictCursor = None

try:
    import pg8000.dbapi as pg8000
except ImportError:  # pragma: no cover - optional production dependency
    pg8000 = None


DEFAULT_DB = Path("data/phones.sqlite")
DEFAULT_STATUS = "未开模"
PARTIAL_MOLDING_STATUS = "部分开模"
LEGACY_PARTIAL_MOLDING_STATUS = "待开模"
VALID_STATUSES = {"未开模", PARTIAL_MOLDING_STATUS, "已开模", "忽略"}
VALID_TABLES = {"phones", "candidates"}
VALID_BADGES = {"", "新品", "新品预告", "官网当前机型", "Walmart MX 在售"}
VALID_SALE_STATUSES = {"", "已售", "未发售", "未发布", "未上市"}
STATUS_PRIORITY = {"未开模": 0, PARTIAL_MOLDING_STATUS: 1, "忽略": 2, "已开模": 3}
PRICE_FILTER_CURRENCIES = {"MXN", "CNY", "KRW", "USD"}
POSTGRES_INIT_ADVISORY_LOCK_ID = 2026070301

TIPO_PENDING_STATUS = "待开模"
TIPO_DONE_STATUS = "已开模"
VALID_TIPO_STATUSES = {TIPO_PENDING_STATUS, TIPO_DONE_STATUS}

MANAGED_FIELD_BRAND = "brand"
MANAGED_FIELD_SAMPLING_STATUS = "sampling_status"
MANAGED_FIELD_BADGE = "badge"
MANAGED_FIELD_SALE_STATUS = "sale_status"
MANAGED_FIELD_TIPO_STATUS = "tipo_status"
MANAGED_FIELD_COUNTRY = "country"
MANAGED_FIELD_PRICE_CURRENCY = "price_currency"
MANAGED_FIELD_PRICE_BUCKET = "price_bucket"
MANAGED_FIELD_MANUAL_MODEL_TYPE = "manual_model_type"
DEFAULT_BRANDS = ["MOTOROLA", "OPPO", "VIVO", "HONOR", "XIAOMI", "ZTE", "SAMSUNG"]
VALID_MANAGED_FIELDS = {
    MANAGED_FIELD_BRAND,
    MANAGED_FIELD_SAMPLING_STATUS,
    MANAGED_FIELD_BADGE,
    MANAGED_FIELD_SALE_STATUS,
    MANAGED_FIELD_TIPO_STATUS,
    MANAGED_FIELD_COUNTRY,
    MANAGED_FIELD_PRICE_CURRENCY,
    MANAGED_FIELD_PRICE_BUCKET,
    MANAGED_FIELD_MANUAL_MODEL_TYPE,
}
DEFAULT_MANAGED_FIELD_OPTIONS = {
    MANAGED_FIELD_BRAND: [(brand, brand) for brand in DEFAULT_BRANDS],
    MANAGED_FIELD_SAMPLING_STATUS: [
        (DEFAULT_STATUS, DEFAULT_STATUS),
        (PARTIAL_MOLDING_STATUS, PARTIAL_MOLDING_STATUS),
        ("已开模", "已开模"),
        ("忽略", "忽略"),
    ],
    MANAGED_FIELD_BADGE: [
        ("", "无标签"),
        ("新品", "新品"),
        ("新品预告", "新品预告"),
        ("官网当前机型", "官网当前机型"),
        ("Walmart MX 在售", "Walmart MX 在售"),
    ],
    MANAGED_FIELD_SALE_STATUS: [
        ("", "自动判断"),
        ("已售", "已售"),
        ("未发售", "未发售"),
        ("未发布", "未发布"),
        ("未上市", "未上市"),
    ],
    MANAGED_FIELD_TIPO_STATUS: [
        (TIPO_PENDING_STATUS, TIPO_PENDING_STATUS),
        (TIPO_DONE_STATUS, TIPO_DONE_STATUS),
    ],
    MANAGED_FIELD_COUNTRY: [
        ("MX", "墨西哥 MX"),
        ("CN", "中国 CN"),
        ("KR", "韩国 KR"),
        ("GLOBAL", "全球参考 GLOBAL"),
    ],
    MANAGED_FIELD_PRICE_CURRENCY: [
        ("MXN", "MXN"),
        ("CNY", "CNY"),
        ("KRW", "KRW"),
        ("USD", "USD"),
    ],
    MANAGED_FIELD_PRICE_BUCKET: [
        ("all", "全部"),
        ("priced", "有价格"),
        ("unpriced", "无价格/未识别"),
    ],
    MANAGED_FIELD_MANUAL_MODEL_TYPE: [
        ("candidates", "候选机型"),
        ("phones", "全部机型"),
    ],
}


def parse_price_for_filter(price: Any) -> tuple[str | None, float | None]:
    text = str(price or "").strip()
    if not text:
        return None, None

    upper = text.upper()
    currency: str | None = None
    if "US$" in upper or re.search(r"\bUSD\b", upper):
        currency = "USD"
    elif "MXN" in upper or re.search(r"\bMX\$", upper) or "$" in text:
        currency = "MXN"
    elif "CNY" in upper or "RMB" in upper or "¥" in text or "￥" in text or "元" in text:
        currency = "CNY"
    elif "KRW" in upper or "₩" in text or "원" in text:
        currency = "KRW"

    if currency is None:
        return None, None

    match = re.search(r"\d[\d,.\s]*", text)
    if not match:
        return currency, None

    raw_number = re.sub(r"[\s,]", "", match.group(0))
    try:
        amount = float(raw_number)
    except ValueError:
        return currency, None
    return currency, amount


def filter_rows_by_price(
    rows: list[Any],
    currency: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    price_bucket: str | None = None,
) -> list[Any]:
    selected_currency = str(currency or "").strip().upper() or None
    selected_bucket = str(price_bucket or "").strip() or "all"
    if selected_currency and selected_currency not in PRICE_FILTER_CURRENCIES:
        return []
    if selected_bucket not in {"all", "priced", "unpriced"}:
        return []
    if selected_bucket == "all" and selected_currency is None and min_price is None and max_price is None:
        return rows

    filtered: list[Any] = []
    for row in rows:
        row_currency, amount = parse_price_for_filter(row["price"] if "price" in row.keys() else "")
        has_price = bool(row_currency and amount is not None)
        if selected_bucket == "unpriced":
            if not has_price:
                filtered.append(row)
            continue
        if selected_bucket == "priced" and not has_price:
            continue
        if selected_currency and row_currency != selected_currency:
            continue
        if amount is None:
            continue
        if min_price is not None and amount < min_price:
            continue
        if max_price is not None and amount > max_price:
            continue
        filtered.append(row)
    return filtered


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def model_search_terms(model_query: str | None) -> tuple[str, str] | None:
    text = str(model_query or "").strip().lower()
    if not text:
        return None
    compact = re.sub(r"[\s\-]+", "", text)
    return f"%{escape_like(text)}%", f"%{escape_like(compact)}%"


def append_model_query_filter(filters: list[str], params: list[Any], model_query: str | None) -> None:
    terms = model_search_terms(model_query)
    if not terms:
        return
    model_term, normalized_term = terms
    filters.append(
        "(lower(model) LIKE ? ESCAPE '\\' OR lower(replace(replace(normalized_model, ' ', ''), '-', '')) LIKE ? ESCAPE '\\')"
    )
    params.extend([model_term, normalized_term])


def is_bad_image_url(value: Any) -> bool:
    url = str(value or "").strip().lower()
    if not url:
        return True
    bad_parts = (
        "placeholder",
        "lazyload",
        "spacer",
        "blank.",
        "logo",
        "logotipo",
        "favicon",
        "sprite",
        "icon-",
        "/icons/",
        "#primaryimage",
        "open-graph",
        "newsletter",
        "arrow",
        "audifonos",
        "cargadores",
        "smartwatch",
        "nome-produto",
        "nombre-producto",
        "product-name",
    )
    return any(part in url for part in bad_parts)


def normalize_sampling_status(status: str | None) -> str:
    value = str(status or "").strip()
    if not value:
        return DEFAULT_STATUS
    if value == LEGACY_PARTIAL_MOLDING_STATUS:
        return PARTIAL_MOLDING_STATUS
    return value


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS raw_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    page_url TEXT NOT NULL,
    raw_title TEXT,
    raw_badge TEXT,
    raw_image_url TEXT,
    raw_price TEXT,
    raw_release_date TEXT,
    raw_launch_date TEXT,
    raw_payload TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL,
    clean_stage TEXT NOT NULL DEFAULT 'raw',
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_raw_items_country_brand
    ON raw_items(country, brand);

CREATE INDEX IF NOT EXISTS idx_raw_items_page
    ON raw_items(page_url);

CREATE TABLE IF NOT EXISTS phones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    badge_override TEXT,
    sale_status_override TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL DEFAULT '未处理',
    clean_stage TEXT NOT NULL,
    deleted_at TEXT,
    delete_reason TEXT,
    deleted_by TEXT,
    purge_after TEXT,
    UNIQUE (brand, country, normalized_model)
);

CREATE INDEX IF NOT EXISTS idx_phones_country_brand
    ON phones(country, brand);

CREATE INDEX IF NOT EXISTS idx_phones_model
    ON phones(normalized_model);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    source_country TEXT NOT NULL,
    missing_country TEXT NOT NULL DEFAULT 'MX',
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    badge_override TEXT,
    sale_status_override TEXT,
    reason TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL DEFAULT '未处理',
    deleted_at TEXT,
    delete_reason TEXT,
    deleted_by TEXT,
    purge_after TEXT,
    UNIQUE (brand, source_country, missing_country, normalized_model)
);

CREATE INDEX IF NOT EXISTS idx_candidates_brand_status
    ON candidates(brand, sampling_status);

CREATE TABLE IF NOT EXISTS custom_series_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    series_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (brand, series_name)
);

CREATE TABLE IF NOT EXISTS molding_tipo_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    tipo_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '待开模',
    synced_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (brand, normalized_model, tipo_name)
);

CREATE INDEX IF NOT EXISTS idx_molding_tipo_model
    ON molding_tipo_records(brand, normalized_model);

CREATE TABLE IF NOT EXISTS managed_field_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_name TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (field_name, value)
);

CREATE TABLE IF NOT EXISTS dingtalk_tipo_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    first_collected_at TEXT NOT NULL,
    last_collected_at TEXT NOT NULL,
    seen_date TEXT NOT NULL,
    published_at TEXT,
    collect_run_id INTEGER,
    collect_window_start TEXT,
    collect_window_end TEXT,
    last_error TEXT,
    UNIQUE (brand, source_type, title, url)
);

CREATE INDEX IF NOT EXISTS idx_news_items_brand_seen
    ON news_items(brand, seen_date);

CREATE INDEX IF NOT EXISTS idx_news_items_source_seen
    ON news_items(source_type, seen_date);

CREATE INDEX IF NOT EXISTS idx_news_items_first_collected
    ON news_items(first_collected_at);
"""


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id SERIAL PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS raw_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES runs(id),
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    page_url TEXT NOT NULL,
    raw_title TEXT,
    raw_badge TEXT,
    raw_image_url TEXT,
    raw_price TEXT,
    raw_release_date TEXT,
    raw_launch_date TEXT,
    raw_payload TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL,
    clean_stage TEXT NOT NULL DEFAULT 'raw'
);

CREATE INDEX IF NOT EXISTS idx_raw_items_country_brand
    ON raw_items(country, brand);

CREATE INDEX IF NOT EXISTS idx_raw_items_page
    ON raw_items(page_url);

CREATE TABLE IF NOT EXISTS phones (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    badge_override TEXT,
    sale_status_override TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL DEFAULT '未处理',
    clean_stage TEXT NOT NULL,
    deleted_at TEXT,
    delete_reason TEXT,
    deleted_by TEXT,
    purge_after TEXT,
    UNIQUE (brand, country, normalized_model)
);

CREATE INDEX IF NOT EXISTS idx_phones_country_brand
    ON phones(country, brand);

CREATE INDEX IF NOT EXISTS idx_phones_model
    ON phones(normalized_model);

CREATE TABLE IF NOT EXISTS candidates (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL,
    source_country TEXT NOT NULL,
    missing_country TEXT NOT NULL DEFAULT 'MX',
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    badge_override TEXT,
    sale_status_override TEXT,
    reason TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL DEFAULT '未处理',
    deleted_at TEXT,
    delete_reason TEXT,
    deleted_by TEXT,
    purge_after TEXT,
    UNIQUE (brand, source_country, missing_country, normalized_model)
);

CREATE INDEX IF NOT EXISTS idx_candidates_brand_status
    ON candidates(brand, sampling_status);

CREATE TABLE IF NOT EXISTS custom_series_rules (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL,
    series_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (brand, series_name)
);

CREATE TABLE IF NOT EXISTS molding_tipo_records (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    tipo_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '待开模',
    synced_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (brand, normalized_model, tipo_name)
);

CREATE INDEX IF NOT EXISTS idx_molding_tipo_model
    ON molding_tipo_records(brand, normalized_model);

CREATE TABLE IF NOT EXISTS managed_field_options (
    id SERIAL PRIMARY KEY,
    field_name TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (field_name, value)
);

CREATE TABLE IF NOT EXISTS dingtalk_tipo_options (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_items (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    first_collected_at TEXT NOT NULL,
    last_collected_at TEXT NOT NULL,
    seen_date TEXT NOT NULL,
    published_at TEXT,
    collect_run_id INTEGER,
    collect_window_start TEXT,
    collect_window_end TEXT,
    last_error TEXT,
    UNIQUE (brand, source_type, title, url)
);

CREATE INDEX IF NOT EXISTS idx_news_items_brand_seen
    ON news_items(brand, seen_date);

CREATE INDEX IF NOT EXISTS idx_news_items_source_seen
    ON news_items(source_type, seen_date);

CREATE INDEX IF NOT EXISTS idx_news_items_first_collected
    ON news_items(first_collected_at);
"""

SOURCE_TABLE_NAMES = {
    "MX": "phones_mx",
    "CN": "phones_cn",
    "KR_SAMSUNG": "phones_kr_samsung",
    "GLOBAL": "phones_global",
}


SOURCE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS phones_mx (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL,
    UNIQUE (brand, country, normalized_model)
);

CREATE TABLE IF NOT EXISTS phones_cn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL,
    UNIQUE (brand, country, normalized_model)
);

CREATE TABLE IF NOT EXISTS phones_kr_samsung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL,
    UNIQUE (brand, country, normalized_model)
);

CREATE TABLE IF NOT EXISTS phones_global (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    image_url TEXT,
    price TEXT,
    release_date TEXT,
    launch_date TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT,
    badge TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sampling_status TEXT NOT NULL,
    UNIQUE (brand, country, normalized_model)
);

CREATE TABLE IF NOT EXISTS molding_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    normalized_model TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_country TEXT,
    missing_country TEXT,
    sampling_status TEXT NOT NULL,
    source_url TEXT,
    source_name TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (brand, normalized_model)
);
"""


POSTGRES_SOURCE_TABLE_SCHEMA = SOURCE_TABLE_SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")


def db_backend(db_path: str | Path = DEFAULT_DB) -> str:
    configured = os.getenv("PHONE_WATCH_DB_BACKEND")
    if configured is not None:
        return configured.strip().lower()
    if Path(db_path) != DEFAULT_DB:
        return "sqlite"
    return "postgres"


def pg_config() -> dict[str, Any]:
    config = {
        "host": os.getenv("PHONE_WATCH_PG_HOST", os.getenv("PGHOST", "127.0.0.1")),
        "database": os.getenv("PHONE_WATCH_PG_DATABASE", os.getenv("PGDATABASE", "phone_scraper")),
        "user": os.getenv("PHONE_WATCH_PG_USER", os.getenv("PGUSER", "postgres")),
        "password": os.getenv("PHONE_WATCH_PG_PASSWORD", os.getenv("PGPASSWORD", "")),
        "port": os.getenv("PHONE_WATCH_PG_PORT", os.getenv("PGPORT", "5432")),
        "options": os.getenv("PHONE_WATCH_PG_OPTIONS", "-c client_encoding=utf8"),
        "connect_timeout": int(os.getenv("PHONE_WATCH_PG_CONNECT_TIMEOUT", "10")),
    }
    if os.getenv("PHONE_WATCH_LOCAL_ONLY", "false").lower() == "true":
        host = str(config["host"]).strip().lower()
        allowed_names = {"localhost", "postgres", "phone-watch-db", "host.docker.internal"}
        local = host in allowed_names
        try:
            local = local or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if not local:
            raise RuntimeError("PHONE_WATCH_LOCAL_ONLY blocks non-local PostgreSQL hosts")
    return config


def pg_driver() -> str:
    requested = os.getenv("PHONE_WATCH_PG_DRIVER", "").strip().lower()
    if requested:
        return requested
    if pg8000 is not None:
        return "pg8000"
    return "psycopg2"


def pg_connect_config(driver: str) -> dict[str, Any]:
    config = pg_config()
    if driver == "pg8000":
        return {
            "host": config["host"],
            "database": config["database"],
            "user": config["user"],
            "password": config["password"],
            "port": int(config["port"]),
            "timeout": int(config["connect_timeout"]),
        }
    return config


def is_postgres_connection(conn: Any) -> bool:
    return isinstance(conn, PostgresConnection)


def lock_postgres_init(conn: Any) -> None:
    if is_postgres_connection(conn):
        conn.execute("SELECT pg_advisory_xact_lock(?)", (POSTGRES_INIT_ADVISORY_LOCK_ID,))


def convert_placeholders(sql: str) -> str:
    return sql.replace("?", "%s")


class CursorAdapter:
    def __init__(self, cursor: Any):
        self.cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self.cursor.rowcount or 0)

    @property
    def lastrowid(self) -> int | None:
        return getattr(self.cursor, "lastrowid", None)

    def _row_to_mapping(self, row: Any) -> Any:
        if row is None or hasattr(row, "keys"):
            return row
        description = getattr(self.cursor, "description", None) or []
        if not description:
            return row
        names = [str(column[0]) for column in description]
        return dict(zip(names, row))

    def fetchall(self) -> list[Any]:
        return [self._row_to_mapping(row) for row in self.cursor.fetchall()]

    def fetchone(self) -> Any:
        return self._row_to_mapping(self.cursor.fetchone())


class PostgresConnection:
    def __init__(self, raw_conn: Any, *, driver: str):
        self.raw_conn = raw_conn
        self.driver = driver

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> CursorAdapter:
        if self.driver == "psycopg2" and RealDictCursor is not None:
            cursor = self.raw_conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.raw_conn.cursor()
        cursor.execute(convert_placeholders(sql), params or [])
        return CursorAdapter(cursor)

    def executescript(self, script: str) -> None:
        statements = [statement.strip() for statement in script.split(";") if statement.strip()]
        for statement in statements:
            self.execute(statement)

    def commit(self) -> None:
        self.raw_conn.commit()

    def close(self) -> None:
        self.raw_conn.close()


@contextmanager
def connect(db_path: str | Path = DEFAULT_DB):
    if db_backend(db_path) == "postgres":
        driver = pg_driver()
        if driver == "pg8000":
            if pg8000 is None:
                raise RuntimeError("PostgreSQL backend requires pg8000. Install pg8000 or set PHONE_WATCH_PG_DRIVER=psycopg2.")
            raw_conn = pg8000.connect(**pg_connect_config(driver))
        elif driver == "psycopg2":
            if psycopg2 is None:
                raise RuntimeError("PostgreSQL backend requires psycopg2. Install psycopg2-binary or set PHONE_WATCH_PG_DRIVER=pg8000.")
            raw_conn = psycopg2.connect(**pg_connect_config(driver))
        else:
            raise RuntimeError("PHONE_WATCH_PG_DRIVER must be pg8000 or psycopg2")
        conn = PostgresConnection(raw_conn, driver=driver)
        if driver == "pg8000":
            conn.execute("SET client_encoding TO 'UTF8'")
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
    try:
        if not is_postgres_connection(conn):
            conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path = DEFAULT_DB) -> None:
    with connect(db_path) as conn:
        lock_postgres_init(conn)
        conn.executescript(POSTGRES_SCHEMA if is_postgres_connection(conn) else SCHEMA)
        conn.executescript(POSTGRES_SOURCE_TABLE_SCHEMA if is_postgres_connection(conn) else SOURCE_TABLE_SCHEMA)
        migrate_schema(conn)
        migrate_status_values(conn)


def clear_derived_tables(conn: Any) -> None:
    conn.execute("DELETE FROM candidates WHERE sampling_status != ?", ("已开模",))
    conn.execute("DELETE FROM phones WHERE sampling_status != ?", ("已开模",))


def snapshot_sampling_statuses(conn: Any) -> dict[str, str]:
    snapshot: dict[str, str] = {}

    def remember_model_status(brand: str, normalized_model: str, status: str) -> None:
        key = f"model|{brand}|{normalized_model}"
        old = snapshot.get(key)
        if old is None or STATUS_PRIORITY.get(status, 0) > STATUS_PRIORITY.get(old, 0):
            snapshot[key] = status

    for row in conn.execute(
        """
        SELECT brand, country, normalized_model, sampling_status
        FROM phones
        WHERE sampling_status IS NOT NULL
          AND sampling_status != ?
        """,
        (DEFAULT_STATUS,),
    ).fetchall():
        key = f"phones|{row['brand']}|{row['country']}|{row['normalized_model']}"
        snapshot[key] = row["sampling_status"]
        remember_model_status(row["brand"], row["normalized_model"], row["sampling_status"])

    for row in conn.execute(
        """
        SELECT brand, source_country, missing_country, normalized_model, sampling_status
        FROM candidates
        WHERE sampling_status IS NOT NULL
          AND sampling_status != ?
        """,
        (DEFAULT_STATUS,),
    ).fetchall():
        key = (
            f"candidates|{row['brand']}|{row['source_country']}|"
            f"{row['missing_country']}|{row['normalized_model']}"
        )
        snapshot[key] = row["sampling_status"]
        remember_model_status(row["brand"], row["normalized_model"], row["sampling_status"])
    return snapshot


def restore_sampling_statuses(conn: Any, snapshot: dict[str, str]) -> int:
    updated = 0
    for key, status in snapshot.items():
        parts = key.split("|")
        if parts[0] == "phones" and len(parts) == 4:
            cursor = conn.execute(
                """
                UPDATE phones
                SET sampling_status = ?
                WHERE brand = ?
                  AND country = ?
                  AND normalized_model = ?
                """,
                (status, parts[1], parts[2], parts[3]),
            )
            updated += int(cursor.rowcount or 0)
        elif parts[0] == "candidates" and len(parts) == 5:
            cursor = conn.execute(
                """
                UPDATE candidates
                SET sampling_status = ?
                WHERE brand = ?
                  AND source_country = ?
                  AND missing_country = ?
                  AND normalized_model = ?
                """,
                (status, parts[1], parts[2], parts[3], parts[4]),
            )
            updated += int(cursor.rowcount or 0)
    for key, status in snapshot.items():
        parts = key.split("|")
        if parts[0] != "model" or len(parts) != 3:
            continue
        brand, normalized_model = parts[1], parts[2]
        cursor = conn.execute(
            """
            UPDATE phones
            SET sampling_status = ?
            WHERE brand = ?
              AND normalized_model = ?
              AND sampling_status = ?
            """,
            (status, brand, normalized_model, DEFAULT_STATUS),
        )
        updated += int(cursor.rowcount or 0)
        cursor = conn.execute(
            """
            UPDATE candidates
            SET sampling_status = ?
            WHERE brand = ?
              AND normalized_model = ?
              AND sampling_status = ?
            """,
            (status, brand, normalized_model, DEFAULT_STATUS),
        )
        updated += int(cursor.rowcount or 0)
    return updated


def subtract_months(value: datetime, months: int) -> datetime:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(value.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return value.replace(year=year, month=month, day=day)


def cleanup_stale_unopened(conn: Any, *, months: int = 5, now: datetime | None = None) -> dict[str, int]:
    current = now or datetime.now(timezone.utc)
    cutoff = subtract_months(current, months).isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    for table in ("candidates", "phones"):
        cursor = conn.execute(
            f"""
            DELETE FROM {table}
            WHERE sampling_status != ?
              AND last_seen_at < ?
            """,
            ("已开模", cutoff),
        )
        counts[table] = int(cursor.rowcount or 0)

    cursor = conn.execute(
        """
        DELETE FROM raw_items
        WHERE fetched_at < ?
        """,
        (cutoff,),
    )
    counts["raw_items"] = int(cursor.rowcount or 0)
    counts["cutoff"] = cutoff
    return counts


def refresh_business_tables(conn: Any) -> dict[str, int]:
    for table in SOURCE_TABLE_NAMES.values():
        conn.execute(f"DELETE FROM {table}")
    counts = {table: 0 for table in SOURCE_TABLE_NAMES.values()}

    source_columns = """
        brand, country, model, normalized_model, image_url, price, release_date,
        launch_date, source_url, source_name, badge, first_seen_at, last_seen_at,
        sampling_status
    """
    source_filters = {
        SOURCE_TABLE_NAMES["MX"]: ("country = ?", ("MX",)),
        SOURCE_TABLE_NAMES["CN"]: ("country = ?", ("CN",)),
        SOURCE_TABLE_NAMES["KR_SAMSUNG"]: ("country = ? AND brand = ?", ("KR", "SAMSUNG")),
        SOURCE_TABLE_NAMES["GLOBAL"]: ("country = ?", ("GLOBAL",)),
    }
    for table, (where, params) in source_filters.items():
        conn.execute(
            f"""
            INSERT INTO {table} ({source_columns})
            SELECT {source_columns}
            FROM phones
            WHERE {where}
            """,
            params,
        )
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        counts[table] = int(row["count"] if row else 0)

    conn.execute("DELETE FROM molding_records")
    molding_count = 0
    for table in ("phones", "candidates"):
        for row in conn.execute(f"SELECT * FROM {table} WHERE sampling_status != ?", (DEFAULT_STATUS,)).fetchall():
            upsert_molding_record(conn, {key: row[key] for key in row.keys()}, source_table=table)
            molding_count += 1
    counts["molding_records"] = molding_count
    return counts


def column_names(conn: Any, table: str) -> set[str]:
    if is_postgres_connection(conn):
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ?
            """,
            (table,),
        ).fetchall()
        return {str(row["column_name"]) for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def add_column_if_missing(conn: Any, table: str, column: str, definition: str) -> None:
    if column in column_names(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_schema(conn: Any) -> None:
    add_column_if_missing(conn, "raw_items", "raw_price", "TEXT")
    add_column_if_missing(conn, "phones", "price", "TEXT")
    add_column_if_missing(conn, "candidates", "price", "TEXT")
    add_column_if_missing(conn, "candidates", "source_name", "TEXT")
    add_column_if_missing(conn, "candidates", "badge", "TEXT")
    add_column_if_missing(conn, "phones", "badge_override", "TEXT")
    add_column_if_missing(conn, "phones", "sale_status_override", "TEXT")
    add_column_if_missing(conn, "candidates", "badge_override", "TEXT")
    add_column_if_missing(conn, "candidates", "sale_status_override", "TEXT")
    for table in VALID_TABLES:
        add_column_if_missing(conn, table, "deleted_at", "TEXT")
        add_column_if_missing(conn, table, "delete_reason", "TEXT")
        add_column_if_missing(conn, table, "deleted_by", "TEXT")
        add_column_if_missing(conn, table, "purge_after", "TEXT")
    add_column_if_missing(conn, "news_items", "published_at", "TEXT")
    add_column_if_missing(conn, "news_items", "collect_run_id", "INTEGER")
    add_column_if_missing(conn, "news_items", "collect_window_start", "TEXT")
    add_column_if_missing(conn, "news_items", "collect_window_end", "TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_items_window
            ON news_items(collect_window_end, published_at)
        """
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dingtalk_tipo_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
        if not is_postgres_connection(conn)
        else """
        CREATE TABLE IF NOT EXISTS dingtalk_tipo_options (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS molding_tipo_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            normalized_model TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            tipo_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '待开模',
            synced_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (brand, normalized_model, tipo_name)
        );
        """
        if not is_postgres_connection(conn)
        else """
        CREATE TABLE IF NOT EXISTS molding_tipo_records (
            id SERIAL PRIMARY KEY,
            brand TEXT NOT NULL,
            normalized_model TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            tipo_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '待开模',
            synced_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (brand, normalized_model, tipo_name)
        );
        """
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS managed_field_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_name TEXT NOT NULL,
            value TEXT NOT NULL,
            label TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (field_name, value)
        );
        """
        if not is_postgres_connection(conn)
        else """
        CREATE TABLE IF NOT EXISTS managed_field_options (
            id SERIAL PRIMARY KEY,
            field_name TEXT NOT NULL,
            value TEXT NOT NULL,
            label TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (field_name, value)
        );
        """
    )
    seed_default_field_options(conn)


DEFAULT_TIPO_OPTIONS = [
    "清水套TPU Liso",
    "三合一UsoRudo",
    "Alterna幻甲",
    "幻影Fantasía Case",
    "超队Súper Capitán",
    "圣殿Case Blindaje",
    "亮甲Rainbow 2.0",
    "titanio 骑士2.0",
    "IML自研",
    "SUPER APITAN 2 GEN 超队2",
    "waves薇武士",
]


def seed_default_tipo_options(conn: Any) -> None:
    if conn.execute("SELECT COUNT(*) AS count FROM dingtalk_tipo_options").fetchone()["count"]:
        return
    for name in DEFAULT_TIPO_OPTIONS:
        upsert_tipo_option(conn, name, enabled=True)


def tipo_options(conn: Any, *, enabled_only: bool = False) -> list[Any]:
    seed_default_tipo_options(conn)
    where = "WHERE enabled = 1" if enabled_only else ""
    return conn.execute(
        f"""
        SELECT *
        FROM dingtalk_tipo_options
        {where}
        ORDER BY id
        """
    ).fetchall()


def upsert_tipo_option(conn: Any, name: str, enabled: bool = True, option_id: int | None = None) -> int:
    cleaned_name = re.sub(r"\s+", " ", str(name or "").strip())
    if not cleaned_name:
        raise ValueError("tipo name is required")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if option_id is not None:
        cursor = conn.execute(
            """
            UPDATE dingtalk_tipo_options
            SET name = ?, enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (cleaned_name, 1 if enabled else 0, now, int(option_id)),
        )
        return int(cursor.rowcount or 0)
    conn.execute(
        """
        INSERT INTO dingtalk_tipo_options (name, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            enabled = excluded.enabled,
            updated_at = excluded.updated_at
        """,
        (cleaned_name, 1 if enabled else 0, now, now),
    )
    return 1


def delete_tipo_option(conn: Any, option_id: int) -> int:
    cursor = conn.execute("DELETE FROM dingtalk_tipo_options WHERE id = ?", (int(option_id),))
    return int(cursor.rowcount or 0)


def normalize_news_row(row: dict[str, Any]) -> dict[str, str | None]:
    brand = str(row.get("brand") or "").strip().upper()
    source_type = str(row.get("source_type") or "").strip().lower()
    source_name = str(row.get("source_name") or "").strip()
    title = re.sub(r"\s+", " ", str(row.get("title") or "").strip())
    url = str(row.get("url") or "").strip()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    first_collected_at = str(row.get("first_collected_at") or row.get("collected_at") or now)
    last_collected_at = str(row.get("last_collected_at") or row.get("collected_at") or first_collected_at)
    seen_date = str(row.get("seen_date") or last_collected_at[:10])
    published_at = row.get("published_at")
    collect_run_id = row.get("collect_run_id")
    collect_window_start = row.get("collect_window_start")
    collect_window_end = row.get("collect_window_end")
    last_error = row.get("last_error")

    if not brand:
        raise ValueError("news brand is required")
    if not source_type:
        raise ValueError("news source_type is required")
    if not source_name:
        raise ValueError("news source_name is required")
    if not title:
        raise ValueError("news title is required")
    if not url:
        raise ValueError("news url is required")

    return {
        "brand": brand,
        "source_type": source_type,
        "source_name": source_name,
        "title": title,
        "url": url,
        "first_collected_at": first_collected_at,
        "last_collected_at": last_collected_at,
        "seen_date": seen_date,
        "published_at": None if published_at is None else str(published_at),
        "collect_run_id": None if collect_run_id is None else int(collect_run_id),
        "collect_window_start": None if collect_window_start is None else str(collect_window_start),
        "collect_window_end": None if collect_window_end is None else str(collect_window_end),
        "last_error": None if last_error is None else str(last_error),
    }


def upsert_news_item(conn: Any, row: dict[str, Any]) -> int | None:
    item = normalize_news_row(row)
    conn.execute(
        """
        INSERT INTO news_items (
            brand, source_type, source_name, title, url,
            first_collected_at, last_collected_at, seen_date,
            published_at, collect_run_id, collect_window_start, collect_window_end,
            last_error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand, source_type, title, url) DO UPDATE SET
            source_name = excluded.source_name,
            last_collected_at = excluded.last_collected_at,
            seen_date = excluded.seen_date,
            published_at = excluded.published_at,
            collect_run_id = excluded.collect_run_id,
            collect_window_start = excluded.collect_window_start,
            collect_window_end = excluded.collect_window_end,
            last_error = excluded.last_error
        """,
        (
            item["brand"],
            item["source_type"],
            item["source_name"],
            item["title"],
            item["url"],
            item["first_collected_at"],
            item["last_collected_at"],
            item["seen_date"],
            item["published_at"],
            item["collect_run_id"],
            item["collect_window_start"],
            item["collect_window_end"],
            item["last_error"],
        ),
    )
    existing = conn.execute(
        """
        SELECT id
        FROM news_items
        WHERE brand = ? AND source_type = ? AND title = ? AND url = ?
        """,
        (item["brand"], item["source_type"], item["title"], item["url"]),
    ).fetchone()
    return int(existing["id"]) if existing else None


def list_news_items(
    conn: Any,
    *,
    brand: str | None = None,
    source_type: str | None = None,
    seen_date: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    limit: int | None = None,
) -> list[Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if brand:
        clauses.append("brand = ?")
        params.append(str(brand).upper())
    if source_type:
        clauses.append("source_type = ?")
        params.append(str(source_type).lower())
    if seen_date:
        clauses.append("seen_date = ?")
        params.append(str(seen_date))
    if window_start and window_end:
        clauses.append(
            """
            (
                (published_at IS NOT NULL AND published_at > ? AND published_at <= ?)
                OR
                (published_at IS NULL AND last_collected_at > ? AND last_collected_at <= ?)
            )
            """
        )
        params.extend([str(window_start), str(window_end), str(window_start), str(window_end)])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(int(limit))
    return conn.execute(
        f"""
        SELECT *
        FROM news_items
        {where}
        ORDER BY COALESCE(published_at, last_collected_at) DESC, seen_date DESC, id DESC
        {limit_clause}
        """,
        params,
    ).fetchall()


def list_recent_news_items(
    conn: Any,
    *,
    brand: str | None = None,
    source_type: str | None = None,
    limit: int | None = None,
) -> list[Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if brand:
        clauses.append("brand = ?")
        params.append(str(brand).upper())
    if source_type:
        clauses.append("source_type = ?")
        params.append(str(source_type).lower())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(int(limit))
    return conn.execute(
        f"""
        SELECT *
        FROM news_items
        {where}
        ORDER BY COALESCE(published_at, last_collected_at, first_collected_at) DESC,
                 seen_date DESC,
                 id DESC
        {limit_clause}
        """,
        params,
    ).fetchall()


def list_news_for_brand_with_fallback(
    conn: Any,
    *,
    brand: str,
    seen_date: str | None = None,
    source_type: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    fallback_limit: int = 3,
) -> tuple[list[Any], bool]:
    primary_rows = list_news_items(
        conn,
        brand=brand,
        source_type=source_type,
        seen_date=seen_date,
        window_start=window_start,
        window_end=window_end,
    )
    if primary_rows:
        return primary_rows, False
    return list_news_items(conn, brand=brand, source_type=source_type, limit=fallback_limit), True


def find_news_item_by_brand_source_url(conn: Any, brand: str, source_type: str, url: str) -> Any | None:
    return conn.execute(
        """
        SELECT *
        FROM news_items
        WHERE brand = ? AND source_type = ? AND url = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(brand).upper(), str(source_type).lower(), str(url).split("#", 1)[0].rstrip("/")),
    ).fetchone()


def count_recent_news_for_brand(conn: Any, brand: str, source_type: str | None = None) -> int:
    clauses = ["brand = ?"]
    params: list[Any] = [str(brand).upper()]
    if source_type:
        clauses.append("source_type = ?")
        params.append(str(source_type).lower())
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM news_items
        WHERE {' AND '.join(clauses)}
        """,
        params,
    ).fetchone()
    return int(row["count"] if row else 0)


def latest_news_seen_date(conn: Any) -> str | None:
    row = conn.execute("SELECT MAX(seen_date) AS seen_date FROM news_items").fetchone()
    if not row:
        return None
    return row["seen_date"]


def latest_finished_run_time(conn: Any, mode: str) -> str | None:
    row = conn.execute(
        """
        SELECT finished_at
        FROM runs
        WHERE mode = ? AND finished_at IS NOT NULL
        ORDER BY finished_at DESC, id DESC
        LIMIT 1
        """,
        (mode,),
    ).fetchone()
    return str(row["finished_at"]) if row and row["finished_at"] is not None else None


def latest_successful_news_run(conn: Any) -> Any | None:
    return conn.execute(
        """
        SELECT
            r.id,
            r.mode,
            r.started_at,
            r.finished_at,
            MIN(n.collect_window_start) AS window_start,
            MAX(n.collect_window_end) AS window_end
        FROM runs r
        LEFT JOIN news_items n ON n.collect_run_id = r.id
        WHERE r.mode = 'collect-news' AND r.finished_at IS NOT NULL
        GROUP BY r.id, r.mode, r.started_at, r.finished_at
        ORDER BY r.finished_at DESC, r.id DESC
        LIMIT 1
        """
    ).fetchone()


def cleanup_old_news_items(conn: Any, *, retention_days: int = 7, now: str | None = None) -> int:
    current = datetime.fromisoformat(str(now).replace("Z", "+00:00")) if now else datetime.now(timezone.utc)
    cutoff = (current - timedelta(days=int(retention_days))).isoformat(timespec="seconds")
    cursor = conn.execute(
        "DELETE FROM news_items WHERE first_collected_at < ?",
        (cutoff,),
    )
    return int(cursor.rowcount or 0)


def custom_series_rules(conn: Any, *, enabled_only: bool = False) -> list[Any]:
    where = "WHERE enabled = 1" if enabled_only else ""
    return conn.execute(
        f"""
        SELECT *
        FROM custom_series_rules
        {where}
        ORDER BY brand, series_name
        """
    ).fetchall()


def custom_series_map(conn: Any) -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    for row in custom_series_rules(conn, enabled_only=True):
        rules.setdefault(str(row["brand"]).upper(), []).append(str(row["series_name"]))
    return rules


def upsert_custom_series_rule(conn: Any, brand: str, series_name: str, enabled: bool = True) -> None:
    cleaned_brand = brand.upper().strip()
    cleaned_series = re.sub(r"\s+", " ", str(series_name or "").strip())
    if not cleaned_brand or not cleaned_series:
        raise ValueError("brand and series_name are required")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO custom_series_rules (brand, series_name, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(brand, series_name) DO UPDATE SET
            enabled = excluded.enabled,
            updated_at = excluded.updated_at
        """,
        (cleaned_brand, cleaned_series, 1 if enabled else 0, now, now),
    )


def set_custom_series_rule_enabled(conn: Any, rule_id: int, enabled: bool) -> int:
    cursor = conn.execute(
        """
        UPDATE custom_series_rules
        SET enabled = ?, updated_at = ?
        WHERE id = ?
        """,
        (1 if enabled else 0, datetime.now(timezone.utc).isoformat(timespec="seconds"), int(rule_id)),
    )
    return int(cursor.rowcount or 0)


def migrate_status_values(conn: Any) -> None:
    replacements = {
        "未处理": DEFAULT_STATUS,
        "待打样": PARTIAL_MOLDING_STATUS,
        "已打样": "已开模",
        "待开模": PARTIAL_MOLDING_STATUS,
    }
    for table in ("phones", "candidates", "molding_records"):
        for old, new in replacements.items():
            conn.execute(f"UPDATE {table} SET sampling_status = ? WHERE sampling_status = ?", (new, old))
        conn.execute(
            f"""
            UPDATE {table}
            SET sampling_status = ?
            WHERE sampling_status IS NULL OR sampling_status = ''
            """,
            (DEFAULT_STATUS,),
        )


def start_run(conn: Any, mode: str, started_at: str, notes: str | None = None) -> int:
    if is_postgres_connection(conn):
        cursor = conn.execute(
            "INSERT INTO runs(mode, started_at, notes) VALUES (?, ?, ?) RETURNING id",
            (mode, started_at, notes),
        )
        return int(cursor.fetchone()["id"])
    cursor = conn.execute(
        "INSERT INTO runs(mode, started_at, notes) VALUES (?, ?, ?)",
        (mode, started_at, notes),
    )
    return int(cursor.lastrowid)


def finish_run(conn: Any, run_id: int, finished_at: str) -> None:
    conn.execute("UPDATE runs SET finished_at = ? WHERE id = ?", (finished_at, run_id))


def insert_raw_items(conn: Any, rows: Iterable[dict[str, Any]]) -> int:
    inserted = 0
    for row in rows:
        payload = row.get("raw_payload")
        if not isinstance(payload, str):
            payload = json.dumps(payload or {}, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO raw_items (
                run_id, brand, country, source_name, source_url, page_url,
                raw_title, raw_badge, raw_image_url, raw_price,
                raw_release_date, raw_launch_date, raw_payload, fetched_at, clean_stage
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("run_id"),
                row["brand"],
                row["country"],
                row["source_name"],
                row["source_url"],
                row["page_url"],
                row.get("raw_title"),
                row.get("raw_badge"),
                row.get("raw_image_url"),
                row.get("raw_price"),
                row.get("raw_release_date"),
                row.get("raw_launch_date"),
                payload,
                row["fetched_at"],
                row.get("clean_stage", "raw"),
            ),
        )
        inserted += 1
    return inserted


def raw_items_for_scope(conn: Any, countries: Iterable[str]) -> list[Any]:
    country_list = [country.upper() for country in countries]
    placeholders = ",".join("?" for _ in country_list)
    return conn.execute(
        f"""
        SELECT *
        FROM raw_items
        WHERE country IN ({placeholders})
        ORDER BY fetched_at DESC, id DESC
        """,
        country_list,
    ).fetchall()


def raw_items_today_for_scope(conn: Any, countries: Iterable[str], today: str) -> list[Any]:
    country_list = [country.upper() for country in countries]
    placeholders = ",".join("?" for _ in country_list)
    return conn.execute(
        f"""
        SELECT *
        FROM raw_items
        WHERE country IN ({placeholders})
          AND substr(fetched_at, 1, 10) = ?
        ORDER BY fetched_at DESC, id DESC
        """,
        [*country_list, today],
    ).fetchall()


def raw_items_for_run_scope(conn: Any, run_id: int, countries: Iterable[str]) -> list[Any]:
    country_list = [country.upper() for country in countries]
    placeholders = ",".join("?" for _ in country_list)
    return conn.execute(
        f"""
        SELECT *
        FROM raw_items
        WHERE run_id = ?
          AND country IN ({placeholders})
        ORDER BY fetched_at DESC, id DESC
        """,
        [run_id, *country_list],
    ).fetchall()


def latest_raw_date(conn: Any, countries: Iterable[str] | None = None) -> str | None:
    params: list[Any] = []
    where = ""
    if countries:
        country_list = [country.upper() for country in countries]
        placeholders = ",".join("?" for _ in country_list)
        where = f"WHERE country IN ({placeholders})"
        params.extend(country_list)
    row = conn.execute(
        f"""
        SELECT MAX(substr(fetched_at, 1, 10)) AS latest_date
        FROM raw_items
        {where}
        """,
        params,
    ).fetchone()
    if not row:
        return None
    return row["latest_date"]


def source_table_for_phone(row: dict[str, Any]) -> str | None:
    country = str(row.get("country") or "").upper()
    brand = str(row.get("brand") or "").upper()
    if country == "KR" and brand == "SAMSUNG":
        return SOURCE_TABLE_NAMES["KR_SAMSUNG"]
    return SOURCE_TABLE_NAMES.get(country)


def upsert_source_phone(conn: Any, row: dict[str, Any]) -> None:
    table = source_table_for_phone(row)
    if not table:
        return
    conn.execute(
        f"""
        INSERT INTO {table} (
            brand, country, model, normalized_model, image_url, price, release_date,
            launch_date, source_url, source_name, badge, first_seen_at,
            last_seen_at, sampling_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand, country, normalized_model) DO UPDATE SET
            model = excluded.model,
            image_url = COALESCE(excluded.image_url, {table}.image_url),
            price = COALESCE(excluded.price, {table}.price),
            release_date = COALESCE(excluded.release_date, {table}.release_date),
            launch_date = COALESCE(excluded.launch_date, {table}.launch_date),
            source_url = COALESCE(excluded.source_url, {table}.source_url),
            source_name = COALESCE(excluded.source_name, {table}.source_name),
            badge = COALESCE(excluded.badge, {table}.badge),
            last_seen_at = excluded.last_seen_at,
            sampling_status = excluded.sampling_status
        """,
        (
            row["brand"],
            row["country"],
            row["model"],
            row["normalized_model"],
            row.get("image_url"),
            row.get("price"),
            row.get("release_date"),
            row.get("launch_date"),
            row["source_url"],
            row.get("source_name"),
            row.get("badge"),
            row["first_seen_at"],
            row["last_seen_at"],
            row.get("sampling_status", DEFAULT_STATUS),
        ),
    )


def upsert_molding_record(conn: Any, row: dict[str, Any], *, source_table: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO molding_records (
            brand, model, normalized_model, source_table, source_country, missing_country,
            sampling_status, source_url, source_name, first_seen_at, last_seen_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand, normalized_model) DO UPDATE SET
            model = excluded.model,
            source_table = excluded.source_table,
            source_country = excluded.source_country,
            missing_country = excluded.missing_country,
            sampling_status = excluded.sampling_status,
            source_url = COALESCE(excluded.source_url, molding_records.source_url),
            source_name = COALESCE(excluded.source_name, molding_records.source_name),
            last_seen_at = excluded.last_seen_at,
            updated_at = excluded.updated_at
        """,
        (
            row["brand"],
            row["model"],
            row["normalized_model"],
            source_table,
            row.get("country") or row.get("source_country"),
            row.get("missing_country"),
            row.get("sampling_status", DEFAULT_STATUS),
            row.get("source_url"),
            row.get("source_name"),
            row.get("first_seen_at") or now,
            row.get("last_seen_at") or now,
            now,
        ),
    )


def validate_tipo_status(status: str) -> None:
    if status not in VALID_TIPO_STATUSES:
        raise ValueError(f"tipo status must be one of: {', '.join(sorted(VALID_TIPO_STATUSES))}")


def upsert_molding_tipo(
    conn: Any,
    *,
    brand: str,
    normalized_model: str,
    source_table: str,
    source_id: int,
    tipo_name: str,
    status: str = TIPO_PENDING_STATUS,
    synced_at: str | None = None,
) -> None:
    validate_tipo_status(status)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO molding_tipo_records (
            brand, normalized_model, source_table, source_id,
            tipo_name, status, synced_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand, normalized_model, tipo_name) DO UPDATE SET
            source_table = excluded.source_table,
            source_id = excluded.source_id,
            status = excluded.status,
            synced_at = COALESCE(excluded.synced_at, molding_tipo_records.synced_at),
            updated_at = excluded.updated_at
        """,
        (brand, normalized_model, source_table, int(source_id), tipo_name, status, synced_at, now),
    )


def molding_tipos_for_model(conn: Any, brand: str, normalized_model: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT tipo_name, status, synced_at, updated_at
        FROM molding_tipo_records
        WHERE brand = ? AND normalized_model = ?
        ORDER BY updated_at DESC, tipo_name
        """,
        (brand, normalized_model),
    ).fetchall()
    return [dict(row) for row in rows]


def molding_tipos_for_models(conn: Any, rows: Iterable[Any]) -> dict[tuple[str, str], list[dict[str, str]]]:
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        brand = str(row["brand"]).upper()
        normalized_model = str(row["normalized_model"])
        key = (brand, normalized_model)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    if not keys:
        return {}

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {key: [] for key in keys}
    models_by_brand: dict[str, list[str]] = {}
    for brand, normalized_model in keys:
        models_by_brand.setdefault(brand, []).append(normalized_model)

    for brand, models in models_by_brand.items():
        placeholders = ", ".join("?" for _ in models)
        # Grouping by brand keeps the SQL short and lets the existing
        # (brand, normalized_model) index serve large list payloads.
        result = conn.execute(
            f"""
            SELECT brand, normalized_model, tipo_name, status, synced_at, updated_at
            FROM molding_tipo_records
            WHERE brand = ? AND normalized_model IN ({placeholders})
            ORDER BY brand, normalized_model, tipo_name
            """,
            [brand, *models],
        ).fetchall()

        for row in result:
            key = (str(row["brand"]).upper(), str(row["normalized_model"]))
            grouped.setdefault(key, []).append({
                "tipo_name": row["tipo_name"],
                "status": row["status"],
                "synced_at": row["synced_at"],
                "updated_at": row["updated_at"],
            })
    return grouped


def compute_molding_status(
    conn: Any,
    brand: str,
    normalized_model: str,
    *,
    all_required_tipos_done: bool = False,
) -> str:
    rows = molding_tipos_for_model(conn, brand, normalized_model)
    if not rows:
        return DEFAULT_STATUS
    if all_required_tipos_done and all(row["status"] == TIPO_DONE_STATUS for row in rows):
        return "已开模"
    if any(row["status"] == TIPO_DONE_STATUS for row in rows):
        return PARTIAL_MOLDING_STATUS
    return PARTIAL_MOLDING_STATUS


def seed_default_field_options(conn: Any) -> None:
    for field_name, options in DEFAULT_MANAGED_FIELD_OPTIONS.items():
        existing = conn.execute(
            "SELECT COUNT(*) AS count FROM managed_field_options WHERE field_name = ?",
            (field_name,),
        ).fetchone()
        if existing and existing["count"]:
            continue
        for index, (value, label) in enumerate(options):
            upsert_field_option(
                conn,
                field_name=field_name,
                value=value,
                label=label,
                enabled=True,
                sort_order=index,
            )


def normalize_field_option_value(field_name: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if field_name in {MANAGED_FIELD_BADGE, MANAGED_FIELD_SALE_STATUS} and cleaned == "":
        return ""
    if not cleaned:
        raise ValueError("字段值不能为空")
    if field_name in {MANAGED_FIELD_BRAND, MANAGED_FIELD_COUNTRY, MANAGED_FIELD_PRICE_CURRENCY}:
        return cleaned.upper()
    if field_name == MANAGED_FIELD_SAMPLING_STATUS:
        return normalize_sampling_status(cleaned)
    return cleaned


def field_options(conn: Any, field_name: str, *, enabled_only: bool = False) -> list[Any]:
    if field_name not in VALID_MANAGED_FIELDS:
        raise ValueError("不支持的字段类型")
    filters = ["field_name = ?"]
    params: list[Any] = [field_name]
    if enabled_only:
        filters.append("enabled = 1")
    return conn.execute(
        f"""
        SELECT id, field_name, value, COALESCE(label, value) AS label, enabled, sort_order
        FROM managed_field_options
        WHERE {' AND '.join(filters)}
        ORDER BY sort_order, value
        """,
        params,
    ).fetchall()


def field_options_map(conn: Any, field_names: Sequence[str], *, enabled_only: bool = False) -> dict[str, list[Any]]:
    return {
        field_name: field_options(conn, field_name, enabled_only=enabled_only)
        for field_name in field_names
    }


def upsert_field_option(
    conn: Any,
    *,
    field_name: str,
    value: str,
    label: str | None = None,
    enabled: bool = True,
    sort_order: int = 0,
    option_id: int | None = None,
) -> int:
    if field_name not in VALID_MANAGED_FIELDS:
        raise ValueError("不支持的字段类型")
    normalized_value = normalize_field_option_value(field_name, value)
    display_label = str(label or normalized_value).strip() or normalized_value
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if option_id:
        cursor = conn.execute(
            """
            UPDATE managed_field_options
            SET value = ?, label = ?, enabled = ?, sort_order = ?, updated_at = ?
            WHERE id = ? AND field_name = ?
            """,
            (normalized_value, display_label, 1 if enabled else 0, int(sort_order), now, int(option_id), field_name),
        )
        return int(cursor.rowcount or 0)
    conn.execute(
        """
        INSERT INTO managed_field_options (field_name, value, label, enabled, sort_order, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(field_name, value) DO UPDATE SET
            label = excluded.label,
            enabled = excluded.enabled,
            sort_order = excluded.sort_order,
            updated_at = excluded.updated_at
        """,
        (field_name, normalized_value, display_label, 1 if enabled else 0, int(sort_order), now, now),
    )
    return 1


def set_field_option_enabled(conn: Any, option_id: int, enabled: bool) -> int:
    cursor = conn.execute(
        """
        UPDATE managed_field_options
        SET enabled = ?, updated_at = ?
        WHERE id = ?
        """,
        (1 if enabled else 0, datetime.now(timezone.utc).isoformat(timespec="seconds"), int(option_id)),
    )
    return int(cursor.rowcount or 0)


def delete_field_option(conn: Any, option_id: int) -> int:
    cursor = conn.execute(
        "DELETE FROM managed_field_options WHERE id = ?",
        (int(option_id),),
    )
    return int(cursor.rowcount or 0)


def upsert_phone(conn: Any, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO phones (
            brand, country, model, normalized_model, image_url, price, release_date,
            launch_date, source_url, source_name, badge, first_seen_at,
            last_seen_at, sampling_status, clean_stage
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand, country, normalized_model) DO UPDATE SET
            model = excluded.model,
            image_url = COALESCE(excluded.image_url, phones.image_url),
            price = COALESCE(excluded.price, phones.price),
            release_date = COALESCE(excluded.release_date, phones.release_date),
            launch_date = COALESCE(excluded.launch_date, phones.launch_date),
            source_url = COALESCE(excluded.source_url, phones.source_url),
            source_name = COALESCE(excluded.source_name, phones.source_name),
            badge = COALESCE(excluded.badge, phones.badge),
            last_seen_at = excluded.last_seen_at,
            clean_stage = excluded.clean_stage
        """,
        (
            row["brand"],
            row["country"],
            row["model"],
            row["normalized_model"],
            row.get("image_url"),
            row.get("price"),
            row.get("release_date"),
            row.get("launch_date"),
            row["source_url"],
            row.get("source_name"),
            row.get("badge"),
            row["first_seen_at"],
            row["last_seen_at"],
            row.get("sampling_status", DEFAULT_STATUS),
            row["clean_stage"],
        ),
    )
    upsert_source_phone(conn, row)
    if row.get("sampling_status") and row.get("sampling_status") != DEFAULT_STATUS:
        upsert_molding_record(conn, row, source_table="phones")


def list_phones(
    conn: Any,
    country: str | None = None,
    brand: str | None = None,
    status: str | None = None,
    seen_date: str | None = None,
    badge: str | None = None,
    model_query: str | None = None,
    price_currency: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    price_bucket: str | None = None,
) -> list[Any]:
    filters: list[str] = ["deleted_at IS NULL"]
    params: list[Any] = []
    if country:
        filters.append("country = ?")
        params.append(country.upper())
    if brand:
        filters.append("brand = ?")
        params.append(brand.upper())
    if status:
        filters.append("sampling_status = ?")
        params.append(status)
    if seen_date:
        filters.append("substr(last_seen_at, 1, 10) = ?")
        params.append(seen_date)
    if badge:
        filters.append("COALESCE(badge_override, badge) = ?")
        params.append(badge)
    append_model_query_filter(filters, params, model_query)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"""
        SELECT *
        FROM phones
        {where}
        ORDER BY last_seen_at DESC, brand, country, model
        """,
        params,
    ).fetchall()
    return filter_rows_by_price(rows, price_currency, price_min, price_max, price_bucket)


def normalized_models(conn: Any, country: str, brand: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT normalized_model
        FROM phones
        WHERE country = ? AND brand = ?
          AND deleted_at IS NULL
          AND sampling_status != '忽略'
        """,
        (country.upper(), brand.upper()),
    ).fetchall()
    return {str(row["normalized_model"]) for row in rows}


def origin_phones_for_compare(conn: Any) -> list[Any]:
    return conn.execute(
        """
        SELECT *
        FROM phones
        WHERE sampling_status != '忽略'
          AND deleted_at IS NULL
          AND (
            country = 'CN'
            OR (brand = 'SAMSUNG' AND country = 'KR')
            OR country = 'GLOBAL'
          )
        ORDER BY last_seen_at DESC
        """
    ).fetchall()


def upsert_candidate(conn: Any, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO candidates (
            brand, source_country, missing_country, model, normalized_model,
            image_url, price, release_date, launch_date, source_url, source_name, reason,
            first_seen_at, last_seen_at, sampling_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand, source_country, missing_country, normalized_model) DO UPDATE SET
            model = excluded.model,
            image_url = COALESCE(excluded.image_url, candidates.image_url),
            price = COALESCE(excluded.price, candidates.price),
            release_date = COALESCE(excluded.release_date, candidates.release_date),
            launch_date = COALESCE(excluded.launch_date, candidates.launch_date),
            source_url = COALESCE(excluded.source_url, candidates.source_url),
            source_name = COALESCE(excluded.source_name, candidates.source_name),
            reason = excluded.reason,
            last_seen_at = excluded.last_seen_at
        """,
        (
            row["brand"],
            row["source_country"],
            row.get("missing_country", "MX"),
            row["model"],
            row["normalized_model"],
            row.get("image_url"),
            row.get("price"),
            row.get("release_date"),
            row.get("launch_date"),
            row["source_url"],
            row.get("source_name"),
            row.get("reason"),
            row["first_seen_at"],
            row["last_seen_at"],
            row.get("sampling_status", DEFAULT_STATUS),
        ),
    )
    if row.get("sampling_status") and row.get("sampling_status") != DEFAULT_STATUS:
        upsert_molding_record(conn, row, source_table="candidates")


def delete_resolved_candidates(conn: Any) -> int:
    cursor = conn.execute(
        """
        DELETE FROM candidates
        WHERE sampling_status != ?
          AND deleted_at IS NULL
          AND EXISTS (
            SELECT 1
            FROM phones mx
            WHERE mx.country = candidates.missing_country
              AND mx.brand = candidates.brand
              AND mx.normalized_model = candidates.normalized_model
              AND mx.deleted_at IS NULL
              AND mx.sampling_status != '忽略'
        )
        """,
        ("已开模",),
    )
    return int(cursor.rowcount or 0)


def list_candidates(
    conn: Any,
    *,
    brand: str | None = None,
    status: str | None = None,
    source_country: str | None = None,
    seen_date: str | None = None,
    model_query: str | None = None,
    price_currency: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    price_bucket: str | None = None,
) -> list[Any]:
    filters: list[str] = ["deleted_at IS NULL"]
    params: list[Any] = []
    if brand:
        filters.append("brand = ?")
        params.append(brand.upper())
    if status:
        filters.append("sampling_status = ?")
        params.append(status)
    if source_country:
        filters.append("source_country = ?")
        params.append(source_country.upper())
    if seen_date:
        filters.append("substr(last_seen_at, 1, 10) = ?")
        params.append(seen_date)
    append_model_query_filter(filters, params, model_query)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"""
        SELECT *
        FROM candidates
        {where}
        ORDER BY
            CASE sampling_status
                WHEN '部分开模' THEN 0
                WHEN '未开模' THEN 1
                WHEN '已开模' THEN 2
                ELSE 3
            END,
            last_seen_at DESC,
            brand,
            model
        """,
        params,
    ).fetchall()
    return filter_rows_by_price(rows, price_currency, price_min, price_max, price_bucket)


def latest_collected_date(conn: Any) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(seen_date) AS seen_date
        FROM (
            SELECT substr(last_seen_at, 1, 10) AS seen_date FROM phones
            WHERE deleted_at IS NULL
            UNION ALL
            SELECT substr(last_seen_at, 1, 10) AS seen_date FROM candidates
            WHERE deleted_at IS NULL
        ) collected
        """
    ).fetchone()
    if not row:
        return None
    return row["seen_date"]


def previous_collected_date(conn: Any, latest_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(seen_date) AS seen_date
        FROM (
            SELECT substr(last_seen_at, 1, 10) AS seen_date FROM phones
            WHERE deleted_at IS NULL
            UNION ALL
            SELECT substr(last_seen_at, 1, 10) AS seen_date FROM candidates
            WHERE deleted_at IS NULL
        ) collected
        WHERE seen_date < ?
        """,
        (latest_date,),
    ).fetchone()
    if not row:
        return None
    return row["seen_date"]


def list_new_phones(
    conn: Any,
    *,
    seen_date: str,
    country: str | None = None,
    brand: str | None = None,
    status: str | None = None,
    badge: str | None = None,
    model_query: str | None = None,
    price_currency: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    price_bucket: str | None = None,
) -> list[Any]:
    filters = ["deleted_at IS NULL", "substr(first_seen_at, 1, 10) = ?"]
    params: list[Any] = [seen_date]
    if country:
        filters.append("country = ?")
        params.append(country.upper())
    if brand:
        filters.append("brand = ?")
        params.append(brand.upper())
    if status:
        filters.append("sampling_status = ?")
        params.append(status)
    if badge:
        filters.append("COALESCE(badge_override, badge) = ?")
        params.append(badge)
    append_model_query_filter(filters, params, model_query)
    rows = conn.execute(
        f"""
        SELECT *
        FROM phones
        WHERE {' AND '.join(filters)}
        ORDER BY first_seen_at DESC, brand, country, model
        """,
        params,
    ).fetchall()
    return filter_rows_by_price(rows, price_currency, price_min, price_max, price_bucket)


def list_new_candidates(
    conn: Any,
    *,
    seen_date: str,
    brand: str | None = None,
    status: str | None = None,
    source_country: str | None = None,
    model_query: str | None = None,
    price_currency: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    price_bucket: str | None = None,
) -> list[Any]:
    filters = ["deleted_at IS NULL", "substr(first_seen_at, 1, 10) = ?"]
    params: list[Any] = [seen_date]
    if brand:
        filters.append("brand = ?")
        params.append(brand.upper())
    if status:
        filters.append("sampling_status = ?")
        params.append(status)
    if source_country:
        filters.append("source_country = ?")
        params.append(source_country.upper())
    append_model_query_filter(filters, params, model_query)
    rows = conn.execute(
        f"""
        SELECT *
        FROM candidates
        WHERE {' AND '.join(filters)}
        ORDER BY first_seen_at DESC, brand, model
        """,
        params,
    ).fetchall()
    return filter_rows_by_price(rows, price_currency, price_min, price_max, price_bucket)


def validate_status_table(table: str, status: str) -> None:
    status = normalize_sampling_status(status)
    if table not in VALID_TABLES:
        raise ValueError("table must be phones or candidates")
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")


def validate_label_table(table: str) -> None:
    if table not in VALID_TABLES:
        raise ValueError("table must be phones or candidates")


def validate_badge_value(badge: str) -> None:
    if badge not in VALID_BADGES:
        raise ValueError(f"badge must be one of: {', '.join(sorted(VALID_BADGES))}")


def validate_sale_status_value(sale_status: str) -> None:
    if sale_status not in VALID_SALE_STATUSES:
        raise ValueError(f"sale_status must be one of: {', '.join(sorted(VALID_SALE_STATUSES))}")


def set_sampling_status(conn: Any, table: str, item_id: int, status: str) -> None:
    status = normalize_sampling_status(status)
    validate_status_table(table, status)
    conn.execute(f"UPDATE {table} SET sampling_status = ? WHERE id = ?", (status, item_id))
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row:
        upsert_molding_record(conn, {key: row[key] for key in row.keys()}, source_table=table)
        if status == "已开模":
            conn.execute(
                """
                UPDATE molding_tipo_records
                SET status = ?, updated_at = ?
                WHERE brand = ? AND normalized_model = ?
                """,
                (TIPO_DONE_STATUS,
                 datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 row["brand"].upper(), row["normalized_model"]),
            )


def set_display_labels(
    conn: Any,
    table: str,
    item_id: int,
    *,
    badge: str | None = None,
    sale_status: str | None = None,
) -> None:
    validate_label_table(table)
    assignments: list[str] = []
    params: list[Any] = []
    if badge is not None:
        validate_badge_value(badge)
        assignments.append("badge_override = ?")
        params.append(badge or None)
    if sale_status is not None:
        validate_sale_status_value(sale_status)
        assignments.append("sale_status_override = ?")
        params.append(sale_status or None)
    if not assignments:
        return
    params.append(int(item_id))
    conn.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?", params)


def set_display_labels_bulk(
    conn: Any,
    table: str,
    item_ids: Sequence[int],
    *,
    badge: str | None = None,
    sale_status: str | None = None,
) -> int:
    validate_label_table(table)
    ids = [int(item_id) for item_id in item_ids]
    if not ids:
        return 0
    assignments: list[str] = []
    params: list[Any] = []
    if badge is not None:
        validate_badge_value(badge)
        assignments.append("badge_override = ?")
        params.append(badge or None)
    if sale_status is not None:
        validate_sale_status_value(sale_status)
        assignments.append("sale_status_override = ?")
        params.append(sale_status or None)
    if not assignments:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id IN ({placeholders})", [*params, *ids])
    return getattr(cursor, "rowcount", 0) or len(ids)


def validate_model_table(table: str) -> str:
    if table not in VALID_TABLES:
        raise ValueError("type must be phones or candidates")
    return table


def normalize_trash_items(items: Sequence[dict[str, Any]]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {table: [] for table in VALID_TABLES}
    for item in items:
        table = validate_model_table(str(item.get("type") or item.get("table") or ""))
        item_id = int(item["id"])
        grouped[table].append(item_id)
    return {table: ids for table, ids in grouped.items() if ids}


def trash_deadline(now: str, retention_days: int = 7) -> str:
    base = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return (base + timedelta(days=retention_days)).isoformat(timespec="seconds")


def trash_models(
    conn: Any,
    items: Sequence[dict[str, Any]],
    *,
    reason: str = "manual_bulk_delete",
    deleted_by: str = "local_user",
    now: str | None = None,
    retention_days: int = 7,
) -> int:
    grouped = normalize_trash_items(items)
    if not grouped:
        return 0
    deleted_at = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    purge_after = trash_deadline(deleted_at, retention_days)
    updated = 0
    for table, ids in grouped.items():
        placeholders = ",".join("?" for _ in ids)
        cursor = conn.execute(
            f"""
            UPDATE {table}
            SET deleted_at = ?, delete_reason = ?, deleted_by = ?, purge_after = ?
            WHERE id IN ({placeholders}) AND deleted_at IS NULL
            """,
            [deleted_at, reason, deleted_by, purge_after, *ids],
        )
        updated += int(cursor.rowcount or 0)
    return updated


def trashed_models(conn: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in sorted(VALID_TABLES):
        source_country_expr = "country" if table == "phones" else "source_country"
        for row in conn.execute(
            f"""
            SELECT
                '{table}' AS type,
                id,
                brand,
                model,
                normalized_model,
                {source_country_expr} AS source_country,
                deleted_at,
                delete_reason,
                deleted_by,
                purge_after
            FROM {table}
            WHERE deleted_at IS NOT NULL
            ORDER BY deleted_at DESC, id DESC
            """
        ).fetchall():
            rows.append(dict(row))
    rows.sort(key=lambda row: (str(row.get("deleted_at") or ""), int(row.get("id") or 0)), reverse=True)
    return rows


def restore_models(conn: Any, items: Sequence[dict[str, Any]]) -> int:
    grouped = normalize_trash_items(items)
    restored = 0
    for table, ids in grouped.items():
        placeholders = ",".join("?" for _ in ids)
        cursor = conn.execute(
            f"""
            UPDATE {table}
            SET deleted_at = NULL, delete_reason = NULL, deleted_by = NULL, purge_after = NULL
            WHERE id IN ({placeholders}) AND deleted_at IS NOT NULL
            """,
            ids,
        )
        restored += int(cursor.rowcount or 0)
    return restored


def purge_models(conn: Any, items: Sequence[dict[str, Any]]) -> int:
    grouped = normalize_trash_items(items)
    purged = 0
    for table, ids in grouped.items():
        placeholders = ",".join("?" for _ in ids)
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE id IN ({placeholders}) AND deleted_at IS NOT NULL",
            ids,
        )
        purged += int(cursor.rowcount or 0)
    return purged


def cleanup_trashed_models(
    conn: Any,
    *,
    now: str | None = None,
    retention_days: int = 7,
) -> int:
    cutoff = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    purged = 0
    for table in VALID_TABLES:
        cursor = conn.execute(
            f"""
            DELETE FROM {table}
            WHERE deleted_at IS NOT NULL
              AND (
                purge_after <= ?
                OR (purge_after IS NULL AND deleted_at <= ?)
              )
            """,
            (cutoff, trash_deadline(cutoff, -retention_days)),
        )
        purged += int(cursor.rowcount or 0)
    return purged


def set_sampling_statuses(
    conn: Any,
    table: str,
    item_ids: Sequence[int],
    status: str,
) -> int:
    status = normalize_sampling_status(status)
    validate_status_table(table, status)
    ids = [int(item_id) for item_id in item_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(
        f"UPDATE {table} SET sampling_status = ? WHERE id IN ({placeholders})",
        [status, *ids],
    )
    for row in conn.execute(f"SELECT * FROM {table} WHERE id IN ({placeholders})", ids).fetchall():
        upsert_molding_record(conn, {key: row[key] for key in row.keys()}, source_table=table)
    return int(cursor.rowcount or 0)


def fill_missing_images(conn: Any) -> int:
    for table in VALID_TABLES:
        rows = conn.execute(f"SELECT id, image_url FROM {table} WHERE image_url IS NOT NULL AND image_url != ''").fetchall()
        for row in rows:
            if is_bad_image_url(row["image_url"]):
                conn.execute(f"UPDATE {table} SET image_url = NULL WHERE id = ?", (row["id"],))

    updated = 0
    for row in conn.execute(
        """
        SELECT id, brand, country, normalized_model
        FROM phones
        WHERE image_url IS NULL OR image_url = ''
        """
    ).fetchall():
        image_row = conn.execute(
            """
            SELECT raw_image_url
            FROM raw_items
            WHERE brand = ?
              AND country = ?
              AND raw_image_url IS NOT NULL
              AND raw_image_url != ''
              AND lower(raw_image_url) NOT LIKE '%placeholder%'
              AND lower(raw_image_url) NOT LIKE '%lazyload%'
              AND (
                lower(raw_title) LIKE ?
                OR replace(replace(replace(lower(raw_title), ' ', ''), '+', 'plus'), '-', '') LIKE ?
                OR lower(page_url) LIKE ?
                OR lower(raw_payload) LIKE ?
              )
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                row["brand"],
                row["country"],
                f"%{row['normalized_model'].lower()}%",
                f"%{row['normalized_model'].lower()}%",
                f"%{row['normalized_model'].lower()}%",
                f"%{row['normalized_model'].lower()}%",
            ),
        ).fetchone()
        if image_row and not is_bad_image_url(image_row["raw_image_url"]):
            conn.execute("UPDATE phones SET image_url = ? WHERE id = ?", (image_row["raw_image_url"], row["id"]))
            updated += 1

    for row in conn.execute(
        """
        SELECT id, brand, source_country, normalized_model
        FROM candidates
        WHERE image_url IS NULL OR image_url = ''
        """
    ).fetchall():
        phone_row = conn.execute(
            """
            SELECT image_url
            FROM phones
            WHERE brand = ?
              AND country = ?
              AND normalized_model = ?
              AND image_url IS NOT NULL
              AND image_url != ''
            LIMIT 1
            """,
            (row["brand"], row["source_country"], row["normalized_model"]),
        ).fetchone()
        if phone_row and not is_bad_image_url(phone_row["image_url"]):
            conn.execute("UPDATE candidates SET image_url = ? WHERE id = ?", (phone_row["image_url"], row["id"]))
            updated += 1
    return updated


def reset_pending_to_unreviewed(conn: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in VALID_TABLES:
        cursor = conn.execute(
            f"""
            UPDATE {table}
            SET sampling_status = ?
            WHERE sampling_status = ?
            """,
            (DEFAULT_STATUS, PARTIAL_MOLDING_STATUS),
        )
        counts[table] = int(cursor.rowcount or 0)
    return counts


def summary(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT 'phones' AS kind, COUNT(*) AS count FROM phones
        WHERE deleted_at IS NULL
        UNION ALL
        SELECT 'candidates' AS kind, COUNT(*) AS count FROM candidates
        WHERE deleted_at IS NULL
        UNION ALL
        SELECT 'pending_candidates' AS kind, COUNT(*) AS count
        FROM candidates
        WHERE sampling_status = '部分开模'
          AND deleted_at IS NULL
        UNION ALL
        SELECT 'unreviewed_candidates' AS kind, COUNT(*) AS count
        FROM candidates
        WHERE sampling_status = '未开模'
          AND deleted_at IS NULL
        UNION ALL
        SELECT 'ignored_phones' AS kind, COUNT(*) AS count
        FROM phones
        WHERE sampling_status = '忽略'
          AND deleted_at IS NULL
        """
    ).fetchall()
    counts: dict[str, Any] = {row["kind"]: row["count"] for row in rows}

    by_country = conn.execute(
        """
        SELECT country, COUNT(*) AS count
        FROM phones
        WHERE deleted_at IS NULL
        GROUP BY country
        ORDER BY country
        """
    ).fetchall()
    counts["by_country"] = {row["country"]: row["count"] for row in by_country}
    return counts


def check_connection(db_path: str | Path = DEFAULT_DB) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT 1 AS ok").fetchone()
        return {"backend": db_backend(db_path), "ok": int(row["ok"])}
