# Fee Evidence AI Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver and deploy independently editable fee status, evidence-first AI review drafts, evidence-backed fee splitting, and authoritative SKU/tax allocation without automatic calculation, confirmation, or ERP writeback.

**Architecture:** Preserve the existing uncommitted implementation in `codex/fee-evidence-ai-review` and finish it through gap-driven tests. Deterministic parsers own every numeric fact and evidence locator; DeepSeek contributes only bounded semantic classifications and ambiguous SKU matches. Applying a reviewed draft is one locked Frappe transaction, while cost preview consumes confirmed SKU components first and allocates only the uncovered fee balance.

**Tech Stack:** Python 3.12, Frappe/ERPNext DocTypes and background jobs, `Decimal`, pytest, browser-side JavaScript/jQuery, CSS, GitHub Actions, GitHub CLI, SSH/Docker production deployment.

---

## File responsibility map

- `overseas_costing/services/fee_service.py`: fee-state transitions, placeholder fee materialization, evidence ledger presentation, and status audit integration.
- `overseas_costing/services/attachment_parse_service.py`: deterministic document extraction and precise page/line/cell/region evidence locators.
- `overseas_costing/services/fee_evidence_review_service.py`: review task lifecycle, DeepSeek semantic boundary, draft construction, fee/SKU allocation, validation, and transactional apply/discard.
- `overseas_costing/services/cost_preview_service.py`: component-first/residual-second calculation and mutually exclusive compatibility behavior.
- `overseas_costing/api/fees.py`: whitelisted, bounded fee-evidence APIs.
- `overseas_costing/doctype/overseas_cost_allocation_rule/*`: fee-state audit snapshot fields.
- `overseas_costing/doctype/overseas_cost_fee_evidence/*`: evidence accounting, fingerprint, review snapshot, confirmation, and refund-link fields.
- `overseas_costing/doctype/overseas_cost_fee_evidence_ai_run/*`: single-flight background run, progress, draft, and terminal state.
- `overseas_costing/doctype/overseas_cost_fee_sku_component/*`: per-SKU/per-tax source facts, conversion snapshot, settlement/cost effect, and reversal link.
- `overseas_costing/overseas_costing/doctype/...`: byte-identical deployed DocType mirrors.
- `overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js`: fee row state controls, evidence-first entry, progress state, and wide review dialog.
- `overseas_costing/page/overseas_cost_workbench/parts/40-vouchers.js`: shared review entry from the voucher page.
- `overseas_costing/page/overseas_cost_workbench/parts/48-material-fee-workspace.css`: wide dialog, conflict, low-confidence, source-evidence, and missing-FX presentation.
- `overseas_costing/scripts/build_workbench_assets.py`: deterministic assembly of source and deployed JS/CSS copies.
- `overseas_costing/tests/test_fee_evidence_review_service.py`: pure allocation, ledger, evidence safety, orchestration, and transaction contracts.
- `overseas_costing/tests/test_fee_evidence_review_ui.py`: focused UI source contracts.
- `overseas_costing/tests/test_fee_doctypes.py`: schema and mirror contracts.
- `overseas_costing/tests/test_fees_api.py`: permission, payload bound, and endpoint delegation contracts.
- `overseas_costing/tests/test_cost_preview_service.py`: authoritative source priority, residual allocation, missing-FX, and input-hash contracts.
- `overseas_costing/tests/test_workbench_frontend_state.py`: compiled workbench event/state regression coverage.

### Task 1: Stabilize schema and fee-state lifecycle

**Files:**
- Modify: `overseas_costing/tests/test_fee_doctypes.py`
- Modify: `overseas_costing/tests/test_fee_evidence_review_service.py`
- Modify: `overseas_costing/services/fee_service.py`
- Modify: `overseas_costing/doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json`
- Modify: `overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json`
- Modify: `overseas_costing/doctype/overseas_cost_fee_sku_component/overseas_cost_fee_sku_component.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_sku_component/overseas_cost_fee_sku_component.json`

- [ ] **Step 1: Add failing schema and transition tests**

Add explicit contracts for the new DocTypes, byte-identical mirrors, refund linkage, cost effect, and every reason-gated status transition:

```python
def test_fee_evidence_and_component_support_refund_linkage_and_cost_effect():
    evidence = _fields(_doctype("doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json"))
    component = _fields(_doctype("doctype/overseas_cost_fee_sku_component/overseas_cost_fee_sku_component.json"))
    assert evidence["related_evidence"]["options"] == "Overseas Cost Fee Evidence"
    assert component["accounting_role"]["options"].splitlines() == ["ESTIMATE", "FINAL_BILL", "SETTLEMENT"]
    assert component["cost_effect"]["options"].splitlines() == ["COST", "LEDGER_ONLY"]
    assert component["reverses_component"]["options"] == "Overseas Cost Fee SKU Component"

@pytest.mark.parametrize(
    ("before", "after"),
    [("MISSING", "NOT_INCURRED"), ("MISSING", "INCLUDED"),
     ("ESTIMATED", "ACTUAL"), ("ACTUAL", "ESTIMATED")],
)
def test_reason_gated_status_transitions_reject_blank_reason(before, after):
    with pytest.raises(ValueError, match="原因"):
        fee_service.validate_fee_status_transition(
            before, after, reason="", has_valid_final_evidence=False
        )
```

- [ ] **Step 2: Run the focused tests and confirm the new contracts fail**

Run:

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_doctypes.py overseas_costing/tests/test_fee_evidence_review_service.py -k 'refund_linkage or reason_gated'
```

Expected: failures for absent linkage/cost-effect fields; status transition tests pass only after the rules match the specification.

- [ ] **Step 3: Complete the schemas and state transition implementation**

Keep amount status independent from evidence status, preserve first-entry `MISSING -> ESTIMATED`, and add these persisted fields:

```json
{"fieldname":"related_evidence","fieldtype":"Link","label":"关联原付款凭证","options":"Overseas Cost Fee Evidence"}
{"fieldname":"accounting_role","fieldtype":"Select","label":"会计作用","options":"ESTIMATE\nFINAL_BILL\nSETTLEMENT","reqd":1}
{"fieldname":"cost_effect","fieldtype":"Select","label":"成本作用","options":"COST\nLEDGER_ONLY","default":"COST","reqd":1}
{"fieldname":"reverses_component","fieldtype":"Link","label":"冲回原分项","options":"Overseas Cost Fee SKU Component"}
```

In `save_fee`, persist `status_change_reason`, `status_changed_by`, and `status_changed_at` only when the status changes, and write an `Overseas Cost Audit Log` containing both old and new status.

- [ ] **Step 4: Synchronize both DocType trees and run the focused suite**

Apply the same field-order and field-definition patch to each deployed mirror path listed above, then run:

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_doctypes.py overseas_costing/tests/test_fee_evidence_review_service.py -k 'doctype or status or amount'
```

Expected: selected tests pass and each mirror assertion is byte-identical.

- [ ] **Step 5: Commit the lifecycle and schema changes**

```bash
git add overseas_costing/doctype overseas_costing/overseas_costing/doctype overseas_costing/services/fee_service.py overseas_costing/tests/test_fee_doctypes.py overseas_costing/tests/test_fee_evidence_review_service.py
git commit -m "feat: model fee evidence review lifecycle"
```

### Task 2: Bind every proposed number to deterministic source evidence

**Files:**
- Modify: `overseas_costing/tests/test_attachment_parse_service.py`
- Modify: `overseas_costing/tests/test_fee_evidence_review_service.py`
- Modify: `overseas_costing/services/attachment_parse_service.py`
- Modify: `overseas_costing/services/fee_service.py`
- Modify: `overseas_costing/services/fee_evidence_review_service.py`

- [ ] **Step 1: Add failing evidence-locator and conflict tests**

```python
def test_tax_amounts_have_page_and_text_line_evidence():
    parsed = attachment_parse_service.parse_tax_certificate_text(
        "--- Page 3 ---\nDTA 0 10.00\nIGI/IGE 0 20.00\nIMPORTE PAGADO: $ 30.00",
        "pedimento.pdf",
    )
    assert parsed["source_evidence"]["header.paid_total_mxn"]["page"] == 3
    assert parsed["source_evidence"]["tax_totals.dta_mxn"]["text_line"] == 2

def test_amount_without_precise_locator_is_not_default_selected():
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="customs_clearance_fee",
        attachment={"name":"A1", "parse_result_json":{"total_amount":100}},
        items=[],
    )
    assert draft["evidence"]["default_selected"] is False
    assert draft["evidence"]["needs_review"] is True

def test_ai_rule_conflict_is_yellow_and_not_default_selected():
    draft = service.build_fee_evidence_review_draft(
        logical_fee_key="import_tax",
        attachment={"name":"A1", "file_name":"完税凭证.pdf", "parse_result_json": {
            "parser":"mexico_tax_certificate_pedimento",
            "header":{"paid_total_mxn":"30"},
            "tax_totals":{"igi_mxn":"30"},
            "line_items":[],
            "validation":{"status":"passed"},
            "source_evidence":{"header.paid_total_mxn":{"page":1,"text_line":4}},
        }},
        items=_items(),
        ai_review={"evidence_type":"QUOTE", "accounting_role":"ESTIMATE", "confidence":"0.99"},
    )
    assert draft["evidence"]["has_conflict"] is True
    assert draft["evidence"]["default_selected"] is False
```

- [ ] **Step 2: Run the tests and confirm they fail for locator/conflict handling**

Run:

```bash
python3 -m pytest -q overseas_costing/tests/test_attachment_parse_service.py overseas_costing/tests/test_fee_evidence_review_service.py -k 'locator or precise or conflict'
```

Expected: failures because current snapshots expose only a JSON path and AI values can replace rule classification without a conflict marker.

- [ ] **Step 3: Implement deterministic locators and safe draft selection**

Add a locator helper that tracks page markers and one-based text lines:

```python
def _source_locator(text: str, pattern: str) -> dict:
    page = 1
    for line_no, line in enumerate(str(text or "").splitlines(), start=1):
        marker = re.fullmatch(r"---\s*Page\s*(\d+)\s*---", line.strip(), re.I)
        if marker:
            page = int(marker.group(1))
        if re.search(pattern, line, re.I):
            return {"page": page, "text_line": line_no, "text_excerpt": line.strip()[:500]}
    return {}
```

Return a `source_evidence` map for header amounts, tax totals, and each line-item tax amount. In draft construction, copy the exact locator into every evidence, fee-split, and component proposal. Set `default_selected` only when confidence is at least `0.90`, a precise locator exists, deterministic sources agree, and semantic classifications do not conflict. Mark other proposals with `needs_review`, `has_conflict`, and a Chinese warning.

- [ ] **Step 4: Record human amount edits explicitly**

When `_selected_proposals` applies an edit to `original_amount` or a fee split `amount`, append:

```python
row["human_edits"] = sorted(set([*(row.get("human_edits") or []), fieldname]))
row["source_refs"] = [*(row.get("source_refs") or []), {
    "type": "MANUAL_REVIEW", "field": fieldname, "operator": _session_user()
}]
```

This allows manual recovery after OCR failure without presenting a human-entered amount as an AI-extracted fact.

- [ ] **Step 5: Run parser and draft tests, then commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_attachment_parse_service.py overseas_costing/tests/test_fee_evidence_review_service.py
git add overseas_costing/services/attachment_parse_service.py overseas_costing/services/fee_service.py overseas_costing/services/fee_evidence_review_service.py overseas_costing/tests/test_attachment_parse_service.py overseas_costing/tests/test_fee_evidence_review_service.py
git commit -m "feat: attach source evidence to fee proposals"
```

Expected: all parser and review-service tests pass.

### Task 3: Complete tax, service-fee, refund, and missing-FX allocation

**Files:**
- Modify: `overseas_costing/tests/test_fee_evidence_review_service.py`
- Modify: `overseas_costing/services/fee_evidence_review_service.py`
- Modify: `overseas_costing/doctype/overseas_cost_fee_sku_component/overseas_cost_fee_sku_component.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_sku_component/overseas_cost_fee_sku_component.json`

- [ ] **Step 1: Add failing allocation tests**

```python
def test_components_can_be_confirmed_in_original_currency_without_fx():
    result = service.validate_component_amount_conservation(
        {"amount":"100", "currency":"MXN"},
        [{"currency":"MXN", "original_amount":"100", "amount_rmb":None}],
        {},
    )
    assert result == {"original_currency":"MXN", "original_total":"100.00", "missing_fx":True}

def test_clearance_service_without_line_scope_uses_purchase_value():
    result = service.allocate_service_fee_components(
        [{"amount_mxn":"30", "source_evidence":{"page":2,"text_line":8}}],
        _items(),
        fx_context={"fx_rmb_to_mxn":"2"},
    )
    assert [row["original_amount"] for row in result["components"]] == ["20.00", "10.00"]
    assert all(row["allocation_basis"] == "purchase_goods_value" for row in result["components"])

def test_linked_refund_reverses_original_sku_tax_proportions_as_ledger_only():
    reversed_rows = service.build_refund_reversal_components(
        "30", [{"name":"C1","item":"I1","tax_code":"IVA","original_amount":"20"},
               {"name":"C2","item":"I2","tax_code":"IVA","original_amount":"10"}],
    )
    assert [row["original_amount"] for row in reversed_rows] == ["-20.00", "-10.00"]
    assert all(row["cost_effect"] == "LEDGER_ONLY" for row in reversed_rows)
```

- [ ] **Step 2: Run the allocation tests and verify the present gaps**

Run:

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_evidence_review_service.py -k 'without_fx or clearance_service or linked_refund'
```

Expected: missing-FX validation currently raises, and service/refund helpers are absent.

- [ ] **Step 3: Implement independent per-tax allocation and service-fee allocation**

Keep `_allocate_money` deterministic and run it separately for every tax code. For service fees, use an explicit item list when every referenced item belongs to the batch; otherwise require complete positive `goods_value` for every applicable item and allocate by purchase value. Incomplete bases return `needs_review=True` without component proposals.

- [ ] **Step 4: Allow original-currency persistence without weakening conservation**

Change `validate_component_amount_conservation` to validate original currency totals first. If conversion is unavailable, require every `amount_rmb` and `exchange_rate` to be empty and return `missing_fx=True`. If conversion exists, require converted totals within `0.005` RMB and reject component totals above the fee total. Negative values are allowed only for linked `SETTLEMENT` reversal rows with `cost_effect=LEDGER_ONLY` and `reverses_component` populated.

- [ ] **Step 5: Implement reliable refund linkage**

Only offer a refund reversal when the selected `related_evidence` is a valid `PAYMENT` evidence for the same batch, version, fee, and currency. Allocate the refund amount by the original component proportions, persist links to each original component, and keep these rows out of cost preview unless a later explicit fee-status action adopts net settlement as the actual fee total.

- [ ] **Step 6: Run allocation tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_evidence_review_service.py
git add overseas_costing/services/fee_evidence_review_service.py overseas_costing/doctype/overseas_cost_fee_sku_component overseas_costing/overseas_costing/doctype/overseas_cost_fee_sku_component overseas_costing/tests/test_fee_evidence_review_service.py
git commit -m "feat: allocate evidence amounts to SKU components"
```

Expected: tax conservation, purchase-value fallback, refund reversal, and missing-FX cases pass.

### Task 4: Harden task orchestration and atomic apply

**Files:**
- Modify: `overseas_costing/tests/test_fee_evidence_review_service.py`
- Modify: `overseas_costing/services/fee_evidence_review_service.py`
- Modify: `overseas_costing/api/fees.py`
- Modify: `overseas_costing/tests/test_fees_api.py`

- [ ] **Step 1: Add failing orchestration and transaction tests**

Add pure lock-order and duplicate-detection tests that assert:

```python
def test_apply_lock_order_contains_every_mutated_target():
    assert service.review_lock_targets(
        {"batch":"B1", "version":"V1"},
        {"name":"RUN1", "attachment":"A1", "evidence":"E1"},
    ) == [
        ("batch", "B1"), ("run", "RUN1"), ("version", "V1"),
        ("attachment", "A1"), ("fee_rules", "B1", "V1"),
        ("evidence", "E1"), ("items", "B1", "V1"),
        ("components", "B1", "V1"),
    ]

def test_duplicate_attachment_fingerprint_is_rejected():
    with pytest.raises(ValueError, match="重复凭证"):
        service.assert_no_duplicate_evidence(
            {"attachment":"A-NEW", "attachment_fingerprint":"sha256:x", "accounting_role":"FINAL_BILL", "direction":"DEBIT", "original_amount":"30"},
            [{"name":"E-OLD", "attachment":"A-OLD", "attachment_fingerprint":"sha256:x", "accounting_role":"FINAL_BILL", "direction":"DEBIT", "original_amount":"30"}],
        )
```

Also test single-flight reuse, `force` behavior, execution-token claim loss, incremental `after_revision`, attachment fingerprint staleness, archived-version refusal, and JSON size/type limits.

- [ ] **Step 2: Run task/API tests and confirm new lock/duplicate tests fail**

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_evidence_review_service.py overseas_costing/tests/test_fees_api.py -k 'lock or duplicate or fingerprint or single_flight or payload'
```

- [ ] **Step 3: Move all database operations behind repository methods**

Expose explicit repository operations for locking, finding fingerprints, upserting evidence, replacing components, auditing, marking dirty, and finishing a run. The service must not commit inside the apply try-block until every validation and write succeeds. On exception, call one rollback and leave the run `READY`; on attachment mutation, write only `STALE` in a separate transaction.

- [ ] **Step 4: Reject duplicate business evidence without blocking legitimate multi-fee splits**

The duplicate check rejects another valid evidence with the same `attachment_fingerprint`, accounting role, direction, and business amount when it belongs to a different attachment. It permits multiple fee links created by the same review run for one physical attachment, so import tax and clearance splits remain valid.

- [ ] **Step 5: Validate all edited fields after locks are held**

Re-check enum membership, three supported currencies, finite non-negative evidence/fee amounts, final-role consistency, fee-split conservation, per-tax component conservation, current-batch SKU membership, and refund-link membership. Only `FINAL_BILL + is_final=1` may write `ACTUAL`; other proposals remain `ESTIMATED` or ledger-only.

- [ ] **Step 6: Run service/API tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_evidence_review_service.py overseas_costing/tests/test_fees_api.py
git add overseas_costing/services/fee_evidence_review_service.py overseas_costing/api/fees.py overseas_costing/tests/test_fee_evidence_review_service.py overseas_costing/tests/test_fees_api.py
git commit -m "fix: apply fee review drafts atomically"
```

### Task 5: Enforce calculation source priority and residual behavior

**Files:**
- Modify: `overseas_costing/tests/test_cost_preview_service.py`
- Modify: `overseas_costing/tests/test_calculate_service.py`
- Modify: `overseas_costing/services/cost_preview_service.py`
- Modify: `overseas_costing/services/calculate_service.py`

- [ ] **Step 1: Add failing calculation-priority tests**

```python
def test_ledger_only_components_never_enter_cost():
    result = preview_comprehensive_cost_data(
        [{"name":"I1","stable_line_key":"L1","goods_value":100,"quantity":1,"purchase_uom":"个","unit_price_uom":"个"}],
        [{"name":"F1","logical_fee_key":"import_tax","expense_category":"进口税费","amount_status":"ACTUAL","amount":"100","currency":"RMB","allocation_basis":"goods_value","scope_type":"ALL_ITEMS","is_enabled":1}],
        {},
        fee_components=[{"fee_rule":"F1","item":"I1","stable_line_key":"L1","amount_rmb":"30","status":"CONFIRMED","is_active":1,"cost_effect":"LEDGER_ONLY"}],
    )
    assert result["included_fees"][0]["component_allocations"] == {}
    assert sum(Decimal(v) for v in result["included_fees"][0]["allocations"].values()) == Decimal("100.00")

def test_new_components_suppress_legacy_sku_tax_fields_and_allocate_only_residual():
    items = [
        {"name":"I1","stable_line_key":"L1","goods_value":100,"quantity":1,"purchase_uom":"个","unit_price_uom":"个","igi_amount":"40"},
        {"name":"I2","stable_line_key":"L2","goods_value":100,"quantity":1,"purchase_uom":"个","unit_price_uom":"个","igi_amount":"60"},
    ]
    result = preview_comprehensive_cost_data(
        items,
        [{"name":"F1","logical_fee_key":"import_tax","expense_category":"进口税费","amount_status":"ACTUAL","amount":"120","currency":"RMB","allocation_basis":"goods_value","scope_type":"ALL_ITEMS","is_enabled":1}],
        {},
        fee_components=[{"fee_rule":"F1","item":"I1","stable_line_key":"L1","amount_rmb":"50","status":"CONFIRMED","is_active":1,"cost_effect":"COST"}],
    )
    assert result["included_fees"][0]["component_allocations"] == {"L1":"50.00"}
    assert sum(Decimal(v) for v in result["included_fees"][0]["allocations"].values()) == Decimal("120.00")
```

Add a missing-FX case expecting `EVIDENCE_COMPONENT_FX_MISSING` in `incomplete_reasons`, plus an input-hash test proving component edits invalidate a saved trial.

- [ ] **Step 2: Run focused calculation tests and confirm ledger-only filtering fails**

```bash
python3 -m pytest -q overseas_costing/tests/test_cost_preview_service.py overseas_costing/tests/test_calculate_service.py -k 'component or legacy or residual or input_hash'
```

- [ ] **Step 3: Filter authoritative components and preserve exact totals**

`_fee_component_rows` must accept only active, confirmed rows with `cost_effect == "COST"`. Aggregate those rows by stable SKU key, subtract their RMB total from the fee total, allocate a positive residual using the fee's normal scope/basis rules, and reject an overage above `0.005`. When any selected cost component lacks RMB conversion, exclude that fee and emit a Chinese missing-rate reason.

- [ ] **Step 4: Keep history as compatibility-only input**

When a logical fee has one or more new confirmed cost components, do not add legacy item tax/customs fields for that logical fee. When it has none, retain the existing historical field path unchanged. Include sorted component snapshots in `cost_input_hash`, stored calculation summaries, and saved per-item allocation details.

- [ ] **Step 5: Run calculation tests and commit**

```bash
python3 -m pytest -q overseas_costing/tests/test_cost_preview_service.py overseas_costing/tests/test_calculate_service.py overseas_costing/tests/test_fee_status_service.py
git add overseas_costing/services/cost_preview_service.py overseas_costing/services/calculate_service.py overseas_costing/tests/test_cost_preview_service.py overseas_costing/tests/test_calculate_service.py
git commit -m "feat: calculate from confirmed fee SKU components"
```

### Task 6: Finish the wide review dialog and shared entry points

**Files:**
- Modify: `overseas_costing/tests/test_fee_evidence_review_ui.py`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/40-vouchers.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/48-material-fee-workspace.css`
- Generate: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Generate: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`
- Generate: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
- Generate: `overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css`

- [ ] **Step 1: Add failing UI contracts for warnings, source locations, and non-mutating behavior**

```python
def test_review_marks_conflicts_and_missing_fx_without_default_selection():
    source = PART.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "has_conflict" in source and "needs_review" in source
    assert "ocw-mf-review-warning" in source and ".ocw-mf-review-warning" in css
    assert "缺汇率：可保存原币事实，本次试算不会计入" in source

def test_review_shows_precise_source_locator_and_refund_parent():
    source = PART.read_text(encoding="utf-8")
    for token in ('ref.page', 'ref.text_line', 'ref.cell', 'ref.region', 'data-fieldname="related_evidence"'):
        assert token in source
```

Keep source tests asserting that starting/applying/discarding a review never calls calculation, confirmation, or ERP APIs.

- [ ] **Step 2: Run UI tests and confirm the warning/refund contracts fail**

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_evidence_review_ui.py overseas_costing/tests/test_workbench_frontend_state.py -k 'fee_evidence or independent_status or voucher'
```

- [ ] **Step 3: Complete fee-row and dialog behavior**

Render the five-value status select and collect a reason before saving required transitions. Keep “关联并解析凭证” enabled for virtual/blank-amount fees. In the wide dialog, preserve user edits while polling, show exact evidence locators, yellow unchecked conflict/low-confidence rows, per-tax SKU results, unclassified difference, refund-parent selection, and the missing-rate notice. Apply and discard remain explicit footer actions.

- [ ] **Step 4: Keep voucher and fee-row entry points on the same task API**

Both entry points call `openFeeEvidenceReviewDialog`; the voucher page resolves batch/version and uses logical fee key `import_tax`. Neither entry point calls old save/compare APIs before the user applies the draft.

- [ ] **Step 5: Rebuild assets and run JavaScript/UI checks**

```bash
python3 overseas_costing/scripts/build_workbench_assets.py
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
python3 -m pytest -q overseas_costing/tests/test_fee_evidence_review_ui.py overseas_costing/tests/test_workbench_frontend_state.py overseas_costing/tests/test_workbench_asset_builder.py
cmp -s overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
cmp -s overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
```

Expected: all commands exit zero and both deployed assets match their source copies.

- [ ] **Step 6: Commit the UI and generated assets**

```bash
git add overseas_costing/page/overseas_cost_workbench overseas_costing/overseas_costing/page/overseas_cost_workbench overseas_costing/tests/test_fee_evidence_review_ui.py overseas_costing/tests/test_workbench_frontend_state.py
git commit -m "feat: review fee evidence in a wide dialog"
```

### Task 7: Integration, migration, and regression verification

**Files:**
- Modify: `overseas_costing/tests/test_fee_evidence_review_service.py`
- Modify: `overseas_costing/tests/test_fee_evidence_review_ui.py`
- Modify: `overseas_costing/tests/test_fee_doctypes.py`
- Modify: `overseas_costing/tests/test_fees_api.py`
- Modify: `overseas_costing/tests/test_cost_preview_service.py`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`

- [ ] **Step 1: Add an end-to-end service fixture test**

The fixture starts with a blank `import_tax` fee, parses one mixed customs attachment, confirms import-tax and clearance splits, allocates same-HS taxes across two SKUs, preserves an unexplained difference, and verifies that no calculation/confirm/ERP collaborator was called until a separate explicit calculation invocation.

```python
assert applied["fee_count"] == 2
assert applied["component_count"] > 0
assert repository.run_status == "APPLIED"
assert repository.batch_status == "Dirty"
assert repository.unclassified_difference_writes == 0
assert repository.external_calls == []
```

- [ ] **Step 2: Run the integration fixture and fix only failures within this design**

```bash
python3 -m pytest -q overseas_costing/tests/test_fee_evidence_review_service.py -k 'end_to_end'
```

Expected: pass after the full review/apply chain is internally consistent.

- [ ] **Step 3: Run the complete local quality gate**

```bash
python3 -m pytest -q overseas_costing/tests
python3 -m compileall -q overseas_costing
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
python3 overseas_costing/scripts/build_workbench_assets.py
git diff --exit-code -- overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
git diff --check
```

Expected: the entire suite passes, compile/syntax checks exit zero, asset generation is repeatable, and diff checks are clean.

- [ ] **Step 4: Inspect the final migration surface and commit remaining test adjustments**

```bash
git diff --name-status 8e81330b949844aa383d2b982fef934d32b9422c..HEAD
git status --short
git add overseas_costing/tests
git commit -m "test: cover fee evidence review workflow"
```

Expected: new DocTypes exist in both trees, no fixture/cache output is staged, and the only uncommitted files after the commit are intentional implementation changes already assigned to a prior task.

### Task 8: Review, deploy once, and perform non-mutating production acceptance

**Files:**
- No new product files expected.

- [ ] **Step 1: Run completion review and confirm the exact release commit**

```bash
git status --short
git log -8 --oneline --decorate
git diff --check HEAD^
```

Expected: the worktree is clean and the release contains the design, schema, service, API, UI, generated assets, and tests.

- [ ] **Step 2: Confirm production target and rollback reference**

```bash
git fetch production overseas_costing
git rev-parse production/overseas_costing
git merge-base --is-ancestor 8e81330b949844aa383d2b982fef934d32b9422c HEAD
git ls-remote --heads production overseas_costing
```

Expected: production still points to the declared baseline or a fast-forward descendant already contained by this release; the merge-base check exits zero. Stop instead of force-pushing if production contains an unknown divergent commit.

- [ ] **Step 3: Push exactly once through the production pipeline**

The workflow's `Prepare production rollback point` step creates a site database/files backup and rollback image before migration.

```bash
git push production HEAD:overseas_costing
```

Expected: one new `Overseas Costing CI/CD` run starts in `yueweiit/DeepLinkERP`.

- [ ] **Step 4: Follow the pipeline through tests, backup, migration, assets, and health check**

```bash
DEPLOY_RUN_ID="$(gh run list -R yueweiit/DeepLinkERP --workflow 'Overseas Costing CI/CD' --branch overseas_costing --limit 1 --json databaseId,headSha --jq 'map(select(.headSha == \"'"$(git rev-parse HEAD)"'\"))[0].databaseId')"
test -n "$DEPLOY_RUN_ID"
gh run watch -R yueweiit/DeepLinkERP "$DEPLOY_RUN_ID" --exit-status --interval 10
```

Expected: `Run tests` and `Deploy to DeepLinkERP` both succeed, including rollback preparation, `bench migrate`, frontend asset synchronization, and the login-page check.

- [ ] **Step 5: Verify deployed schema and code read-only**

Use the configured deployment SSH identity and run Frappe metadata/code hash checks without writing business data:

```bash
ssh -i ~/.ssh/overseas_cost_deploy -o IdentitiesOnly=yes yuewei@155.138.234.129 \
  'cd /home/yuewei/ERPNext-Docker/frappe_docker && backend_container_id=$(docker compose -f compose.custom.yaml ps -q backend) && docker exec "$backend_container_id" bench --site deeplinkerp.com execute frappe.client.get_meta --kwargs '"'"'{"doctype":"Overseas Cost Fee Evidence AI Run"}'"'"''
```

Expected: the new DocType metadata is returned and includes `progress_revision`, `attachment_fingerprint`, and `draft_json`.

- [ ] **Step 6: Generate and discard one production draft without changing costs**

Select one active, editable batch and an existing attachment through read-only queries. Snapshot its batch/version/fee calculation and ERP state, call `start_fee_evidence_review`, wait for `READY` or `FAILED`, call `discard_fee_evidence_review`, and compare the snapshots. Acceptance succeeds only when the fee amount/status, calculation snapshot, version confirmation, and ERP state are byte-for-byte unchanged while the evidence link and discarded run remain auditable.

- [ ] **Step 7: Report deployment evidence without a second production push**

Return the release commit, workflow run URL/status, backup artifact location reported by the workflow, migration result, metadata check, draft run ID, discard result, and before/after business-state hashes in the final task response. Do not create or push a post-deployment commit, so production receives exactly one push and one workflow run.
