"""Move the legacy Mexico inventory from the China company to YUEWEI MX.

Warehouse and Company are part of ERPNext's historical stock ledger identity, so
this migration must not rewrite either field in place.  It creates the matching
warehouse tree in the target company and posts paired Stock Reconciliations.
The pure planning helpers live in this module as well so the exact scope can be
tested without importing Frappe.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Iterable

try:
    import frappe
except ImportError:  # pragma: no cover - the unit-test environment has no Frappe
    frappe = None


SOURCE_COMPANY = "YW 中国共享中心"
TARGET_COMPANY = "YUEWEI MX"
SOURCE_ROOT_WAREHOUSE = "墨西哥仓库 - YC"
SOURCE_SUFFIX = " - YC"
TARGET_SUFFIX = " - YWFM"
MIGRATION_ID = "YWC-YMX-20261002"
RECONCILIATION_PREFIX = f"MAT-RECO-{MIGRATION_ID}"
# ERPNext queues Stock Reconciliations with more than 100 rows.  A release
# migration must finish and audit each pair before workers are re-enabled.
DEFAULT_CHUNK_SIZE = 100
MAX_CHUNK_SIZE = 100
QUANTITY_TOLERANCE = Decimal("0.000001")
VALUE_TOLERANCE = Decimal("0.01")


class CompanyInventoryTransferError(RuntimeError):
    """Raised before commit when the inventory transfer cannot be proven safe."""


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def target_warehouse_name(source_name: str) -> str:
    """Map only the approved legacy company suffix to the YUEWEI MX suffix."""

    source_name = str(source_name or "")
    if not source_name.endswith(SOURCE_SUFFIX):
        raise CompanyInventoryTransferError(
            f"Warehouse {source_name!r} does not use the approved source suffix"
        )
    return source_name[: -len(SOURCE_SUFFIX)] + TARGET_SUFFIX


def build_transfer_snapshot(
    *,
    warehouses: Iterable[dict],
    balances: Iterable[dict],
    existing_warehouse_names: Iterable[str],
    allowed_existing_target_names: Iterable[str] = (),
) -> dict:
    """Build and hash an immutable transfer plan, rejecting unsafe stock."""

    warehouse_rows = [dict(row) for row in warehouses]
    balance_rows = [dict(row) for row in balances]
    existing = {str(name) for name in existing_warehouse_names}
    allowed_existing = {str(name) for name in allowed_existing_target_names}
    source_names = {str(row.get("name") or "") for row in warehouse_rows}

    planned_warehouses = []
    target_names = set()
    for row in sorted(warehouse_rows, key=lambda item: (item.get("lft") or 0, item.get("name") or "")):
        source_name = str(row.get("name") or "")
        target_name = target_warehouse_name(source_name)
        if target_name in target_names:
            raise CompanyInventoryTransferError(
                f"Multiple source warehouses map to {target_name!r}"
            )
        target_names.add(target_name)
        if target_name in existing and target_name not in allowed_existing:
            raise CompanyInventoryTransferError(
                f"Target warehouse {target_name!r} already exists"
            )

        source_parent = row.get("parent_warehouse")
        target_parent = (
            target_warehouse_name(str(source_parent)) if source_parent else None
        )
        planned_warehouses.append(
            {
                **row,
                "source_name": source_name,
                "target_name": target_name,
                "target_parent_warehouse": target_parent,
            }
        )

    planned_balances = []
    for row in sorted(
        balance_rows,
        key=lambda item: (item.get("warehouse") or "", item.get("item_code") or ""),
    ):
        source_warehouse = str(row.get("warehouse") or "")
        if source_warehouse not in source_names:
            raise CompanyInventoryTransferError(
                f"Balance warehouse {source_warehouse!r} is outside the approved tree"
            )
        quantity = _decimal(row.get("actual_qty"))
        if quantity < 0:
            raise CompanyInventoryTransferError(
                f"Cannot transfer negative stock for {row.get('item_code')}"
            )
        if int(row.get("has_serial_no") or 0):
            raise CompanyInventoryTransferError(
                f"Cannot transfer serial-controlled stock for {row.get('item_code')}"
            )
        if int(row.get("has_batch_no") or 0):
            raise CompanyInventoryTransferError(
                f"Cannot transfer batch-controlled stock for {row.get('item_code')}"
            )
        planned_balances.append(
            {
                **row,
                "actual_qty": quantity,
                "valuation_rate": _decimal(row.get("valuation_rate")),
                "stock_value": _decimal(row.get("stock_value")),
                "target_warehouse": target_warehouse_name(source_warehouse),
            }
        )

    total_qty = sum(
        (row["actual_qty"] for row in planned_balances), Decimal("0")
    )
    total_stock_value = sum(
        (row["stock_value"] for row in planned_balances), Decimal("0")
    )
    canonical = {
        "migration_id": MIGRATION_ID,
        "source_company": SOURCE_COMPANY,
        "target_company": TARGET_COMPANY,
        "warehouses": [
            {
                "source": row["source_name"],
                "target": row["target_name"],
                "parent": row["target_parent_warehouse"],
                "is_group": int(row.get("is_group") or 0),
            }
            for row in planned_warehouses
        ],
        "balances": [
            {
                "item_code": row.get("item_code"),
                "source_warehouse": row.get("warehouse"),
                "target_warehouse": row.get("target_warehouse"),
                "actual_qty": str(row["actual_qty"]),
                "valuation_rate": str(row["valuation_rate"]),
                "stock_value": str(row["stock_value"]),
            }
            for row in planned_balances
        ],
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()

    return {
        "ok": True,
        "migration_id": MIGRATION_ID,
        "source_company": SOURCE_COMPANY,
        "target_company": TARGET_COMPANY,
        "warehouse_count": len(planned_warehouses),
        "balance_count": len(planned_balances),
        "total_qty": float(total_qty),
        "total_stock_value": float(total_stock_value),
        "warehouses": planned_warehouses,
        "balances": planned_balances,
        "snapshot_hash": snapshot_hash,
    }


def build_reconciliation_batches(rows: Iterable[dict], *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[dict]:
    """Split a plan into stable target/source Stock Reconciliation pairs."""

    if not 1 <= int(chunk_size) <= MAX_CHUNK_SIZE:
        raise CompanyInventoryTransferError(
            f"chunk_size must be between 1 and {MAX_CHUNK_SIZE}"
        )
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda item: (item.get("warehouse") or "", item.get("item_code") or ""),
    )
    batches = []
    for offset in range(0, len(ordered), int(chunk_size)):
        index = len(batches) + 1
        batches.append(
            {
                "index": index,
                "rows": ordered[offset : offset + int(chunk_size)],
                "target_name": f"{RECONCILIATION_PREFIX}-T-{index:03d}",
                "source_name": f"{RECONCILIATION_PREFIX}-S-{index:03d}",
            }
        )
    return batches


def preflight_company_inventory_transfer() -> dict:
    """Read production state and return the exact migration snapshot without writes."""

    _require_frappe()
    _require_company(SOURCE_COMPANY)
    _require_company(TARGET_COMPANY)
    warehouses = _source_warehouse_tree()
    if not warehouses:
        raise CompanyInventoryTransferError(
            f"Source warehouse tree {SOURCE_ROOT_WAREHOUSE!r} does not exist"
        )
    balances = _source_balances(warehouses)
    existing_names = set(
        frappe.get_all("Warehouse", pluck="name", limit_page_length=0)
    )
    allowed_existing = _validate_existing_target_warehouses(warehouses)
    return build_transfer_snapshot(
        warehouses=warehouses,
        balances=balances,
        existing_warehouse_names=existing_names,
        allowed_existing_target_names=allowed_existing,
    )


def execute_company_inventory_transfer(chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    """Create warehouses and paired adjustments, submit, disable source, and audit.

    This entry point is intentionally deployment-only.  It refuses to run once
    the source has no inventory unless all deterministic reconciliation pairs
    already exist and the final audit proves the migration completed.
    """

    _require_frappe()
    chunk_size = int(chunk_size)
    existing_docs = _existing_reconciliation_names()
    if existing_docs and not _source_has_stock():
        audit = verify_company_inventory_transfer_complete()
        return {"ok": True, "already_completed": True, "audit": audit}
    if existing_docs:
        raise CompanyInventoryTransferError(
            "Migration reconciliation documents already exist while source stock remains; "
            "restore the release backup or complete the reviewed plan manually"
        )

    snapshot = preflight_company_inventory_transfer()
    if not snapshot["balances"]:
        raise CompanyInventoryTransferError("No source inventory was found to transfer")

    batches = build_reconciliation_batches(snapshot["balances"], chunk_size=chunk_size)
    _create_target_warehouse_tree(snapshot["warehouses"])
    posting_date, posting_time = _posting_timestamp()

    # Every draft is inserted before the first stock mutation.  The deterministic
    # names and snapshot hash make the reviewed plan recoverable and auditable.
    for batch in batches:
        _create_reconciliation_draft(
            name=batch["target_name"],
            company=TARGET_COMPANY,
            rows=batch["rows"],
            target=True,
            posting_date=posting_date,
            posting_time=posting_time,
            snapshot_hash=snapshot["snapshot_hash"],
        )
        _create_reconciliation_draft(
            name=batch["source_name"],
            company=SOURCE_COMPANY,
            rows=batch["rows"],
            target=False,
            posting_date=posting_date,
            posting_time=posting_time,
            snapshot_hash=snapshot["snapshot_hash"],
        )
    frappe.db.commit()

    submitted_pairs = []
    for batch in batches:
        _submit_reconciliation_pair(batch)
        submitted_pairs.append(
            {"target": batch["target_name"], "source": batch["source_name"]}
        )

    audit = _audit_snapshot(snapshot)
    _disable_migrated_source_warehouses(snapshot["warehouses"])
    frappe.db.commit()
    return {
        "ok": True,
        "already_completed": False,
        "migration_id": MIGRATION_ID,
        "snapshot_hash": snapshot["snapshot_hash"],
        "warehouse_count": snapshot["warehouse_count"],
        "balance_count": snapshot["balance_count"],
        "total_qty": float(snapshot["total_qty"]),
        "total_stock_value": float(snapshot["total_stock_value"]),
        "reconciliation_pairs": submitted_pairs,
        "audit": audit,
    }


def _submit_reconciliation_pair(batch: dict) -> None:
    """Commit only a synchronous, fully posted, balanced transfer pair."""

    try:
        target_doc = frappe.get_doc("Stock Reconciliation", batch["target_name"])
        source_doc = frappe.get_doc("Stock Reconciliation", batch["source_name"])
        target_doc.submit()
        if int(target_doc.docstatus) != 1:
            raise CompanyInventoryTransferError(
                f"Stock Reconciliation {batch['target_name']!r} is not submitted"
            )
        source_doc.submit()
        if int(source_doc.docstatus) != 1:
            raise CompanyInventoryTransferError(
                f"Stock Reconciliation {batch['source_name']!r} is not submitted"
            )
        _audit_snapshot({"balances": batch["rows"]})
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise


def verify_company_inventory_transfer_complete() -> dict:
    """Deployment/acceptance gate for source depletion and target ownership."""

    _require_frappe()
    source_rows = _source_balance_totals()
    remaining_qty = sum((_decimal(row.get("actual_qty")) for row in source_rows), Decimal("0"))
    target_docs = _reconciliation_docs("T")
    source_docs = _reconciliation_docs("S")
    if remaining_qty.copy_abs() > QUANTITY_TOLERANCE:
        raise CompanyInventoryTransferError(
            f"Source Mexico warehouses still contain {remaining_qty} units"
        )
    if not target_docs or len(target_docs) != len(source_docs):
        raise CompanyInventoryTransferError(
            "Migration Stock Reconciliation pairs are missing or incomplete"
        )
    unfinished = [
        row["name"]
        for row in target_docs + source_docs
        if int(row.get("docstatus") or 0) != 1
    ]
    if unfinished:
        raise CompanyInventoryTransferError(
            "Migration Stock Reconciliations are not submitted: " + ", ".join(unfinished)
        )
    target_qty = _migration_target_quantity(target_docs)
    return {
        "ok": True,
        "migration_id": MIGRATION_ID,
        "source_remaining_qty": float(remaining_qty),
        "target_migrated_qty": float(target_qty),
        "target_reconciliations": len(target_docs),
        "source_reconciliations": len(source_docs),
    }


def _require_frappe() -> None:
    if frappe is None:
        raise CompanyInventoryTransferError("Frappe runtime is required")


def _require_company(name: str) -> None:
    if not frappe.db.exists("Company", name):
        raise CompanyInventoryTransferError(f"Company {name!r} does not exist")


def _source_warehouse_tree() -> list[dict]:
    root = frappe.db.get_value(
        "Warehouse", SOURCE_ROOT_WAREHOUSE, ["lft", "rgt", "company"], as_dict=True
    )
    if not root or root.get("company") != SOURCE_COMPANY:
        return []
    return frappe.get_all(
        "Warehouse",
        filters={
            "company": SOURCE_COMPANY,
            "lft": [">=", root["lft"]],
            "rgt": ["<=", root["rgt"]],
        },
        fields=[
            "name",
            "warehouse_name",
            "parent_warehouse",
            "is_group",
            "disabled",
            "warehouse_type",
            "lft",
        ],
        order_by="lft asc",
        limit_page_length=0,
    )


def _source_balances(warehouses: list[dict]) -> list[dict]:
    names = [row["name"] for row in warehouses]
    if not names:
        return []
    placeholders = ", ".join(["%s"] * len(names))
    return frappe.db.sql(
        f"""
        SELECT
            bin.item_code,
            bin.warehouse,
            bin.actual_qty,
            bin.valuation_rate,
            bin.stock_value,
            item.stock_uom,
            item.has_serial_no,
            item.has_batch_no
        FROM `tabBin` bin
        INNER JOIN `tabItem` item ON item.name = bin.item_code
        WHERE bin.warehouse IN ({placeholders})
          AND ABS(bin.actual_qty) > 0.000001
        ORDER BY bin.warehouse, bin.item_code
        """,
        tuple(names),
        as_dict=True,
    )


def _validate_existing_target_warehouses(source_rows: list[dict]) -> set[str]:
    allowed = set()
    for source in source_rows:
        target_name = target_warehouse_name(source["name"])
        existing = frappe.db.get_value(
            "Warehouse",
            target_name,
            ["name", "company", "parent_warehouse", "is_group"],
            as_dict=True,
        )
        if not existing:
            continue
        expected_parent = (
            target_warehouse_name(source["parent_warehouse"])
            if source.get("parent_warehouse")
            else None
        )
        if (
            existing.get("company") != TARGET_COMPANY
            or existing.get("parent_warehouse") != expected_parent
            or int(existing.get("is_group") or 0) != int(source.get("is_group") or 0)
        ):
            raise CompanyInventoryTransferError(
                f"Existing target warehouse {target_name!r} does not match the source tree"
            )
        allowed.add(target_name)
    return allowed


def _create_target_warehouse_tree(rows: list[dict]) -> None:
    for row in rows:
        target_name = row["target_name"]
        if frappe.db.exists("Warehouse", target_name):
            continue
        if not target_name.endswith(TARGET_SUFFIX):
            raise CompanyInventoryTransferError(
                f"Target warehouse {target_name!r} does not use the approved target suffix"
            )
        # ERPNext derives the document name by appending the company abbreviation
        # to warehouse_name.  Some legacy records incorrectly persisted their
        # abbreviation inside warehouse_name as well, so never copy that field.
        warehouse_title = target_name[: -len(TARGET_SUFFIX)]
        doc = frappe.get_doc(
            {
                "doctype": "Warehouse",
                "warehouse_name": warehouse_title,
                "company": TARGET_COMPANY,
                "parent_warehouse": row.get("target_parent_warehouse"),
                "is_group": int(row.get("is_group") or 0),
                "disabled": 0,
                "warehouse_type": row.get("warehouse_type"),
            }
        )
        doc.insert(ignore_permissions=True)
        if doc.name != target_name:
            raise CompanyInventoryTransferError(
                f"Created warehouse {doc.name!r}; expected {target_name!r}"
            )


def _posting_timestamp():
    from frappe.utils import now_datetime

    timestamp = now_datetime()
    return timestamp.date(), timestamp.time().replace(microsecond=0)


def _create_reconciliation_draft(
    *,
    name: str,
    company: str,
    rows: list[dict],
    target: bool,
    posting_date,
    posting_time,
    snapshot_hash: str,
) -> None:
    if frappe.db.exists("Stock Reconciliation", name):
        raise CompanyInventoryTransferError(
            f"Stock Reconciliation {name!r} already exists"
        )
    doc = frappe.get_doc(
        {
            "doctype": "Stock Reconciliation",
            "company": company,
            "purpose": "Stock Reconciliation",
            "posting_date": posting_date,
            "posting_time": posting_time,
            "set_posting_time": 1,
            "items": [
                {
                    "item_code": row["item_code"],
                    "warehouse": row["target_warehouse"] if target else row["warehouse"],
                    "qty": row["actual_qty"] if target else 0,
                    "valuation_rate": row["valuation_rate"],
                    "allow_zero_valuation_rate": int(
                        target and _decimal(row["valuation_rate"]) == 0
                    ),
                }
                for row in rows
            ],
        }
    )
    marker = f"{MIGRATION_ID}:{snapshot_hash}"
    if doc.meta.has_field("custom_transaction_type"):
        doc.custom_transaction_type = marker[:140]
    doc.insert(ignore_permissions=True, set_name=name)


def _audit_snapshot(snapshot: dict) -> dict:
    mismatches = []
    actual_target_qty = Decimal("0")
    actual_target_value = Decimal("0")
    for row in snapshot["balances"]:
        source_qty, source_value = _bin_state(row["item_code"], row["warehouse"])
        target_qty, target_value = _bin_state(
            row["item_code"], row["target_warehouse"]
        )
        expected = _decimal(row["actual_qty"])
        expected_value = _decimal(row["stock_value"])
        actual_target_qty += target_qty
        actual_target_value += target_value
        if (
            source_qty.copy_abs() > QUANTITY_TOLERANCE
            or source_value.copy_abs() > VALUE_TOLERANCE
        ):
            mismatches.append(
                {
                    "item_code": row["item_code"],
                    "warehouse": row["warehouse"],
                    "expected_qty": "0",
                    "actual_qty": str(source_qty),
                    "expected_stock_value": "0",
                    "actual_stock_value": str(source_value),
                }
            )
        if (
            (target_qty - expected).copy_abs() > QUANTITY_TOLERANCE
            or (target_value - expected_value).copy_abs() > VALUE_TOLERANCE
        ):
            mismatches.append(
                {
                    "item_code": row["item_code"],
                    "warehouse": row["target_warehouse"],
                    "expected_qty": str(expected),
                    "actual_qty": str(target_qty),
                    "expected_stock_value": str(expected_value),
                    "actual_stock_value": str(target_value),
                }
            )
    if mismatches:
        raise CompanyInventoryTransferError(
            "Inventory transfer audit failed: "
            + json.dumps(mismatches[:20], ensure_ascii=False, sort_keys=True)
        )
    return {
        "ok": True,
        "checked_balances": len(snapshot["balances"]),
        "source_remaining_qty": 0.0,
        "target_migrated_qty": float(actual_target_qty),
        "target_migrated_stock_value": float(actual_target_value),
    }


def _bin_state(item_code: str, warehouse: str) -> tuple[Decimal, Decimal]:
    row = frappe.db.get_value(
        "Bin",
        {"item_code": item_code, "warehouse": warehouse},
        ["actual_qty", "stock_value"],
        as_dict=True,
    )
    return (
        _decimal(row.get("actual_qty") if row else 0),
        _decimal(row.get("stock_value") if row else 0),
    )


def _disable_migrated_source_warehouses(rows: list[dict]) -> None:
    # Descendants first keeps the tree valid while it is being retired.
    for row in reversed(rows):
        frappe.db.set_value("Warehouse", row["source_name"], "disabled", 1)


def _existing_reconciliation_names() -> list[str]:
    return frappe.get_all(
        "Stock Reconciliation",
        filters={"name": ["like", f"{RECONCILIATION_PREFIX}-%"]},
        pluck="name",
        limit_page_length=0,
    )


def _source_has_stock() -> bool:
    return any(
        _decimal(row.get("actual_qty")).copy_abs() > QUANTITY_TOLERANCE
        for row in _source_balance_totals()
    )


def _source_balance_totals() -> list[dict]:
    warehouses = _source_warehouse_tree()
    names = [row["name"] for row in warehouses]
    if not names:
        return []
    placeholders = ", ".join(["%s"] * len(names))
    return frappe.db.sql(
        f"""
        SELECT warehouse, SUM(actual_qty) AS actual_qty
        FROM `tabBin`
        WHERE warehouse IN ({placeholders})
        GROUP BY warehouse
        HAVING ABS(SUM(actual_qty)) > 0.000001
        """,
        tuple(names),
        as_dict=True,
    )


def _reconciliation_docs(side: str) -> list[dict]:
    return frappe.get_all(
        "Stock Reconciliation",
        filters={"name": ["like", f"{RECONCILIATION_PREFIX}-{side}-%"]},
        fields=["name", "docstatus"],
        order_by="name asc",
        limit_page_length=0,
    )


def _migration_target_quantity(target_docs: list[dict]) -> Decimal:
    names = [row["name"] for row in target_docs]
    if not names:
        return Decimal("0")
    placeholders = ", ".join(["%s"] * len(names))
    result = frappe.db.sql(
        f"""
        SELECT COALESCE(SUM(qty), 0) AS qty
        FROM `tabStock Reconciliation Item`
        WHERE parent IN ({placeholders})
        """,
        tuple(names),
        as_dict=True,
    )
    return _decimal(result[0]["qty"] if result else 0)
