# PostgreSQL Init Deadlock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent concurrent PostgreSQL `init_db()` calls from deadlocking during startup schema migration.

**Architecture:** Serialize PostgreSQL initialization with a transaction-scoped advisory lock before any schema or data migration statements run. Keep the status migration table order deterministic so all callers acquire table locks in the same order.

**Tech Stack:** Python 3.11, `unittest`, project-local `phone_watch.db`, optional PostgreSQL drivers via existing `PostgresConnection` abstraction.

## Global Constraints

- Do not change SQLite initialization behavior.
- Do not change business status values or migration semantics.
- Keep edits limited to `phone_watch/db.py` and focused tests.
- Use TDD: write and run failing tests before production code.

---

### Task 1: PostgreSQL Init Advisory Lock And Deterministic Status Migration

**Files:**
- Modify: `tests/test_news_db.py`
- Modify: `phone_watch/db.py`

**Interfaces:**
- Consumes: existing `db.init_db(db_path=DEFAULT_DB)`, `db.migrate_status_values(conn)`, `db.is_postgres_connection(conn)`
- Produces: `db.POSTGRES_INIT_ADVISORY_LOCK_ID: int`, `db.lock_postgres_init(conn: Any) -> None`

- [x] **Step 1: Write failing regression tests**

Add these imports near the top of `tests/test_news_db.py`:

```python
from contextlib import contextmanager
from unittest import mock
```

Add these helper classes and tests after the existing imports and before `class NewsDatabaseTests`:

```python
class FakePostgresCursor:
    rowcount = 0
    lastrowid = None

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class FakePostgresConnection:
    driver = "pg8000"

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, tuple(params or ())))
        return FakePostgresCursor()

    def executescript(self, script):
        self.statements.append(("SCRIPT", ()))

    def commit(self):
        self.statements.append(("COMMIT", ()))

    def close(self):
        self.statements.append(("CLOSE", ()))


class PostgresInitMigrationTests(unittest.TestCase):
    def test_postgres_init_takes_advisory_lock_before_schema_migrations(self) -> None:
        fake_conn = FakePostgresConnection()

        @contextmanager
        def fake_connect(db_path=db.DEFAULT_DB):
            yield fake_conn

        with (
            mock.patch.object(db, "connect", fake_connect),
            mock.patch.object(db, "is_postgres_connection", return_value=True),
        ):
            db.init_db()

        lock_index = next(
            index
            for index, (sql, _params) in enumerate(fake_conn.statements)
            if "pg_advisory_xact_lock" in sql
        )
        script_index = next(
            index
            for index, (sql, _params) in enumerate(fake_conn.statements)
            if sql == "SCRIPT"
        )
        self.assertLess(lock_index, script_index)

    def test_status_value_migration_uses_stable_table_order(self) -> None:
        fake_conn = FakePostgresConnection()

        db.migrate_status_values(fake_conn)

        updated_tables = []
        for sql, _params in fake_conn.statements:
            normalized_sql = " ".join(sql.split())
            if normalized_sql.startswith("UPDATE "):
                updated_tables.append(normalized_sql.split()[1])

        first_seen_tables = list(dict.fromkeys(updated_tables))
        self.assertEqual(first_seen_tables, ["phones", "candidates", "molding_records"])
```

- [x] **Step 2: Run tests to verify they fail**

Run: `py -m unittest tests.test_news_db.PostgresInitMigrationTests -v`

Expected: FAIL because `pg_advisory_xact_lock` is not executed yet.

- [x] **Step 3: Add minimal production implementation**

In `phone_watch/db.py`, add a module-level constant after `PRICE_FILTER_CURRENCIES`:

```python
POSTGRES_INIT_ADVISORY_LOCK_ID = 2026070301
```

Add this helper after `is_postgres_connection`:

```python
def lock_postgres_init(conn: Any) -> None:
    if is_postgres_connection(conn):
        conn.execute("SELECT pg_advisory_xact_lock(?)", (POSTGRES_INIT_ADVISORY_LOCK_ID,))
```

Update `init_db` so the lock is taken before schema scripts:

```python
def init_db(db_path: str | Path = DEFAULT_DB) -> None:
    with connect(db_path) as conn:
        lock_postgres_init(conn)
        conn.executescript(POSTGRES_SCHEMA if is_postgres_connection(conn) else SCHEMA)
        conn.executescript(POSTGRES_SOURCE_TABLE_SCHEMA if is_postgres_connection(conn) else SOURCE_TABLE_SCHEMA)
        migrate_schema(conn)
        migrate_status_values(conn)
```

Update `migrate_status_values` table iteration:

```python
    for table in ("phones", "candidates", "molding_records"):
```

- [x] **Step 4: Run focused tests to verify they pass**

Run: `py -m unittest tests.test_news_db.PostgresInitMigrationTests -v`

Expected: OK.

- [x] **Step 5: Run related database tests**

Run: `py -m unittest tests.test_news_db tests.test_tipo_molding_status -v`

Expected: OK.

- [x] **Step 6: Inspect diff**

Run: `git diff -- phone_watch/db.py tests/test_news_db.py docs/superpowers/plans/2026-07-03-postgres-init-deadlock.md`

Expected: Diff only contains the advisory lock, stable table order, tests, and this plan.
