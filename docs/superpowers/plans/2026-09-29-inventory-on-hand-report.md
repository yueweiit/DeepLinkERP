# Inventory On Hand Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a focused actual-inventory report with original-bin traceability, concise quantity formatting, and a redirected Stock workspace shortcut without changing ERPNext stock calculations.

**Architecture:** Reuse ERPNext `Bin`, `Item`, and `Warehouse` as the only live inventory data sources. Extend the existing custom-field installer with one warehouse-specific trace field on `Bin` and one item-level source identifier field on `Item`; expose a small idempotent trace-backfill service; add a standard Frappe Script Report under the canonical `overseas_costing/overseas_costing/report` package; and update only the existing Stock workspace link that currently targets `Stock Projected Qty`.

**Tech Stack:** Python 3.12, Frappe/ERPNext v16 Script Reports, MariaDB through `frappe.db.sql`, Frappe Desk JavaScript, pytest.

---

## File map

- Modify `overseas_costing/install.py`: reuse the existing custom-field creation flow and update the existing Stock workspace link.
- Create `overseas_costing/overseas_costing/report/__init__.py`: canonical report package marker.
- Create `overseas_costing/overseas_costing/report/inventory_on_hand/__init__.py`: report module marker.
- Create `overseas_costing/overseas_costing/report/inventory_on_hand/inventory_on_hand.json`: standard Script Report metadata and roles.
- Create `overseas_costing/overseas_costing/report/inventory_on_hand/inventory_on_hand.py`: columns, filters, actual-quantity query, precision metadata, and warning metadata.
- Create `overseas_costing/overseas_costing/report/inventory_on_hand/inventory_on_hand.js`: report filters and row-aware quantity formatting.
- Create `overseas_costing/services/inventory_trace_service.py`: validate and idempotently backfill original locations and source identifiers without touching stock ledgers.
- Create `overseas_costing/api/inventory_trace.py`: System Manager-only whitelisted dry-run/apply wrapper.
- Create `overseas_costing/translations/zh.csv`: Chinese title for the internal report name.
- Create `overseas_costing/tests/test_inventory_on_hand_report.py`: report contract, filters, numeric precision, and abnormal-count tests.
- Create `overseas_costing/tests/test_inventory_trace_service.py`: dry-run, apply, idempotency, conflict protection, and corrected-item mapping tests.
- Create `overseas_costing/tests/test_inventory_install.py`: field-definition and Stock workspace-link reuse tests.

### Task 1: Extend the existing ERPNext field and workspace installer

**Files:**
- Modify: `overseas_costing/install.py`
- Test: `overseas_costing/tests/test_inventory_install.py`

- [ ] **Step 1: Write failing tests for the two trace fields and the existing workspace link update**

```python
from types import SimpleNamespace

from overseas_costing import install


def test_inventory_trace_fields_extend_existing_custom_field_map():
    fields = install.get_inventory_trace_custom_fields()
    assert fields == {
        "Item": [
            {
                "fieldname": "custom_original_identifier_alias",
                "label": "原始标识/别名",
                "fieldtype": "Small Text",
                "insert_after": "custom_external_code",
            }
        ],
        "Bin": [
            {
                "fieldname": "custom_original_location",
                "label": "原始库位",
                "fieldtype": "Data",
                "insert_after": "warehouse",
                "read_only": 1,
            }
        ],
    }


def test_update_stock_workspace_link_reuses_current_available_quantity_link():
    row = SimpleNamespace(
        label="可用数量",
        link_to="Stock Projected Qty",
        link_type="Report",
        report_ref_doctype="Item",
    )
    workspace = SimpleNamespace(get=lambda fieldname: [row] if fieldname == "links" else [])
    assert install._update_stock_workspace_inventory_link(workspace) is True
    assert row.link_to == "Inventory On Hand"
    assert row.link_type == "Report"
    assert row.report_ref_doctype == "Item"
```

- [ ] **Step 2: Run the focused tests and confirm they fail because the new functions do not exist**

Run: `python -m pytest -q overseas_costing/tests/test_inventory_install.py`

Expected: FAIL with missing `get_inventory_trace_custom_fields` and `_update_stock_workspace_inventory_link`.

- [ ] **Step 3: Add the field definitions to the existing `ensure_erpnext_standard_fields` flow**

```python
INVENTORY_ON_HAND_REPORT = "Inventory On Hand"


def get_inventory_trace_custom_fields() -> dict[str, list[dict]]:
    return {
        "Item": [{"fieldname": "custom_original_identifier_alias", "label": "原始标识/别名", "fieldtype": "Small Text", "insert_after": "custom_external_code"}],
        "Bin": [{"fieldname": "custom_original_location", "label": "原始库位", "fieldtype": "Data", "insert_after": "warehouse", "read_only": 1}],
    }
```

Merge the returned lists into the current `custom_fields` dictionary before its existing `create_custom_fields(...)` call. Add `Bin` to `required_doctypes`; do not add a second custom-field installer.

- [ ] **Step 4: Add an idempotent Stock workspace link updater and call it from `after_install` and `after_migrate`**

```python
def _update_stock_workspace_inventory_link(workspace) -> bool:
    for row in workspace.get("links") or []:
        if row.label == "可用数量" and row.link_to == "Stock Projected Qty":
            row.link_to = INVENTORY_ON_HAND_REPORT
            row.link_type = "Report"
            row.report_ref_doctype = "Item"
            return True
        if row.label == "可用数量" and row.link_to == INVENTORY_ON_HAND_REPORT:
            return False
    return False
```

The public wrapper must verify that `Workspace/Stock` and `Report/Inventory On Hand` exist, save only when the child row changes, and commit through the existing installation transaction pattern.

- [ ] **Step 5: Run the focused tests**

Run: `python -m pytest -q overseas_costing/tests/test_inventory_install.py`

Expected: PASS.

- [ ] **Step 6: Commit the installer change**

```bash
git add overseas_costing/install.py overseas_costing/tests/test_inventory_install.py
git commit -m "feat: add inventory trace fields and shortcut"
```

### Task 2: Build the focused actual-inventory Script Report

**Files:**
- Create: `overseas_costing/overseas_costing/report/__init__.py`
- Create: `overseas_costing/overseas_costing/report/inventory_on_hand/__init__.py`
- Create: `overseas_costing/overseas_costing/report/inventory_on_hand/inventory_on_hand.json`
- Create: `overseas_costing/overseas_costing/report/inventory_on_hand/inventory_on_hand.py`
- Create: `overseas_costing/overseas_costing/report/inventory_on_hand/inventory_on_hand.js`
- Create: `overseas_costing/translations/zh.csv`
- Test: `overseas_costing/tests/test_inventory_on_hand_report.py`

- [ ] **Step 1: Write failing tests for the exact ten-column contract and quantity precision**

```python
from overseas_costing.overseas_costing.report.inventory_on_hand import inventory_on_hand


def test_columns_match_the_approved_business_view():
    assert [column["fieldname"] for column in inventory_on_hand.get_columns()] == [
        "item_code", "item_name", "warehouse", "original_location", "item_group",
        "actual_qty", "stock_uom", "dpci", "external_code", "original_identifier_alias",
    ]


def test_quantity_precision_uses_zero_for_whole_count_units_and_two_for_continuous_units():
    assert inventory_on_hand.get_quantity_display(3300, "包：paquete") == (0, "")
    assert inventory_on_hand.get_quantity_display(19.6, "kg") == (2, "")
    assert inventory_on_hand.get_quantity_display(1.5, "个：pieza") == (2, "计数单位存在小数库存")
```

Add a fake `frappe.db.sql` test that asserts the query filters `bin.actual_qty != 0`, joins `Warehouse` for company filtering, uses bound parameters, and returns `quantity_precision`/`quantity_warning` metadata without adding visible columns.

- [ ] **Step 2: Run the focused test and confirm it fails because the report module is absent**

Run: `python -m pytest -q overseas_costing/tests/test_inventory_on_hand_report.py`

Expected: collection failure for the missing module.

- [ ] **Step 3: Create the report metadata**

Use a standard Script Report named `Inventory On Hand`, module `Overseas Costing`, `ref_doctype` `Item`, `add_total_row` disabled because a grand total across mixed UOMs is not physically meaningful, and the same eight stock-related roles already used by ERPNext's `Stock Projected Qty` report.

- [ ] **Step 4: Implement the report query and exact column order**

```python
def execute(filters=None):
    filters = frappe._dict(filters or {})
    rows = get_data(filters)
    for row in rows:
        row["quantity_precision"], row["quantity_warning"] = get_quantity_display(
            row["actual_qty"], row["stock_uom"]
        )
    return get_columns(), rows
```

Query `tabBin` joined to `tabItem` and `tabWarehouse`; select only nonzero `actual_qty`; apply optional exact company, warehouse, item, and item-group filters plus a bound `LIKE` original-location filter; order by warehouse, original location, and item code. Do not read planned, ordered, reserved, projected, reorder, valuation, or ledger fields.

- [ ] **Step 5: Implement row-aware formatting without converting quantities to text in the data source**

```javascript
formatter(value, row, column, data, default_formatter) {
    if (column.fieldname !== "actual_qty") {
        return default_formatter(value, row, column, data);
    }
    const formatted = default_formatter(
        value,
        row,
        Object.assign({}, column, { precision: data.quantity_precision ?? 2 }),
        data,
    );
    return data.quantity_warning
        ? `<span class="text-danger" title="${frappe.utils.escape_html(data.quantity_warning)}">${formatted}</span>`
        : formatted;
}
```

Filters are Company (required, default `YW Fabricación MX 核心制造`), Warehouse, Original Location, Item, and Item Group.

- [ ] **Step 6: Add the Chinese report-title translation and run focused tests**

Run: `python -m pytest -q overseas_costing/tests/test_inventory_on_hand_report.py`

Expected: PASS.

- [ ] **Step 7: Commit the report**

```bash
git add overseas_costing/overseas_costing/report overseas_costing/translations/zh.csv overseas_costing/tests/test_inventory_on_hand_report.py
git commit -m "feat: add focused inventory on hand report"
```

### Task 3: Add the idempotent trace-backfill service

**Files:**
- Create: `overseas_costing/services/inventory_trace_service.py`
- Create: `overseas_costing/api/inventory_trace.py`
- Test: `overseas_costing/tests/test_inventory_trace_service.py`

- [ ] **Step 1: Write failing tests for dry-run, apply, idempotency, and conflicts**

Use a fake repository with `get_bin`, `get_item_alias`, `set_bin_location`, and `set_item_alias`. Assert:

```python
rows = [{
    "item_code": "FL007979",
    "warehouse": "综合仓库 - YWFM",
    "original_location": "AI-4-C01",
    "original_identifier_alias": "FL000164",
}]
```

- dry-run reports two pending writes and performs none;
- apply writes both fields;
- a second apply reports unchanged and performs no writes;
- a different existing nonempty location or alias is returned in `conflicts` and is never overwritten;
- missing Item or Bin is returned in `missing` and does not partially write that row.

- [ ] **Step 2: Run the focused test and confirm the service is missing**

Run: `python -m pytest -q overseas_costing/tests/test_inventory_trace_service.py`

Expected: collection failure for the missing module.

- [ ] **Step 3: Implement validation and repository-based apply logic**

```python
def apply_inventory_trace(rows, *, dry_run=True, repository=None):
    repository = repository or FrappeInventoryTraceRepository()
    normalized = normalize_rows(rows)
    result = {"dry_run": bool(dry_run), "updated_bins": 0, "updated_items": 0,
              "unchanged": 0, "missing": [], "conflicts": []}
    # Validate both targets first, protect nonempty different values, then write only safe rows.
    return result
```

The Frappe repository uses `frappe.db.get_value` and `frappe.db.set_value`; it never creates or updates `Stock Reconciliation`, `Stock Ledger Entry`, quantity, UOM, or valuation fields.

- [ ] **Step 4: Add a System Manager-only whitelisted wrapper**

```python
@frappe.whitelist()
def backfill_inventory_trace(rows, dry_run=1):
    frappe.only_for("System Manager")
    parsed_rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
    result = apply_inventory_trace(parsed_rows, dry_run=frappe.utils.cint(dry_run))
    if not result["dry_run"] and not result["conflicts"] and not result["missing"]:
        frappe.db.commit()
    return result
```

Do not commit partial batches when conflicts or missing targets exist.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest -q overseas_costing/tests/test_inventory_trace_service.py`

Expected: PASS.

- [ ] **Step 6: Commit the service**

```bash
git add overseas_costing/services/inventory_trace_service.py overseas_costing/api/inventory_trace.py overseas_costing/tests/test_inventory_trace_service.py
git commit -m "feat: add inventory trace backfill service"
```

### Task 4: Verify locally and prepare the live trace payload

**Files:**
- Read: `outputs/inventory_final.json`
- Generate temporarily: `.codex_tmp/inventory_trace_payload.json`

- [ ] **Step 1: Run the three focused test files together**

Run: `python -m pytest -q overseas_costing/tests/test_inventory_install.py overseas_costing/tests/test_inventory_on_hand_report.py overseas_costing/tests/test_inventory_trace_service.py`

Expected: all focused scenarios pass.

- [ ] **Step 2: Run the full backend suite and compile check**

Run: `python -m pytest -q overseas_costing/tests && python -m compileall -q overseas_costing`

Expected: zero failures and compile exit code 0.

- [ ] **Step 3: Generate the 377-row payload from the existing audit JSON**

Create rows with `item_code`, `warehouse`, `original_location`, and the de-duplicated `source_codes` joined by ` / `. Apply the two submitted unit-correction mappings before export:

```python
corrections = {
    ("FL000164", "综合仓库 - YWFM"): "FL007979",
    ("YL000115", "IML 仓库 - YWFM"): "YL001974",
}
```

Assert 377 rows, 377 nonempty locations, 92 distinct locations, and 375 distinct final item codes. Keep the payload in `.codex_tmp`; do not commit business snapshot data.

- [ ] **Step 4: Review the final diff for duplicate paths and unrelated edits**

Run: `git diff --check && git status --short && git diff --stat HEAD~3..HEAD`

Expected: only the canonical nested report path, installer, service/API, translation, tests, design, and plan are changed; `.codex_tmp` and `outputs` remain untracked and uncommitted.

### Task 5: Deploy, backfill trace fields, and verify live behavior

**Files:**
- No additional tracked files.

- [ ] **Step 1: Confirm the production branch relationship and push the verified commits**

Run: `git fetch origin && git merge-base --is-ancestor origin/overseas_costing HEAD`

Expected: exit 0. Push the verified HEAD to `origin/overseas_costing` so the existing CI/CD workflow runs; do not force-push.

- [ ] **Step 2: Monitor the production workflow to completion**

Run: `gh run list -R yueweiit/DeepLinkERP --branch overseas_costing --limit 5` and `gh run watch <run-id> -R yueweiit/DeepLinkERP --exit-status`

Expected: tests, compile, migrate, asset synchronization, and login probe all succeed.

- [ ] **Step 3: Call the deployed trace endpoint in dry-run mode**

Send the 377 prepared rows to `overseas_costing.api.inventory_trace.backfill_inventory_trace` with `dry_run=1` through the authenticated ERP session.

Expected: no missing targets, no conflicts, 377 pending Bin locations, and 375 pending Item aliases (minus any already matching values).

- [ ] **Step 4: Apply the same payload once and re-run dry-run**

Call with `dry_run=0`, then `dry_run=1`.

Expected: apply succeeds atomically; the second dry-run reports zero pending writes, zero conflicts, and zero missing targets.

- [ ] **Step 5: Verify the live report and shortcut**

Open `/desk/query-report/Inventory%20On%20Hand` and confirm:

- exactly ten visible columns in the approved order;
- 377 nonzero YWFM rows;
- every row has original location;
- `FL007979 / 综合仓库 - YWFM / AI-4-C01 / 19.60 kg`;
- `YL001974 / IML 仓库 - YWFM / AI-4-C01 / 7.51 kg`;
- integer display for `个、件、套、卷、包、张、片、支、条、台`;
- two decimals for `kg` and `m²`;
- the Stock sidebar “可用数量” link opens the new report;
- direct `/desk/query-report/Stock%20Projected%20Qty` still works.

- [ ] **Step 6: Reconcile live inventory after metadata backfill**

Read `Bin` totals and Stock Ledger Entry counts before and after the backfill. Confirm the three YWFM warehouse quantity control remains `746,610.49`, stock value remains `0`, and no new or changed Stock Ledger Entry or Stock Reconciliation was created.

- [ ] **Step 7: Capture proof and write the completion report**

Save a screenshot showing the new report, exact columns, original locations, and mixed UOM formatting. Report additions, modifications, deletions, test scenario count versus pytest case count, line-count changes, absence of duplicate logic, retained standard report compatibility, and any remaining technical debt.
