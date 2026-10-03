# Classic Navigation and Historical OA Company Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation is inline; production release and data writes are serialized.

**Goal:** Align the classic first-level sidebar with the approved DL order and explicitly assign the 148 approved historical OA requests to YUEWEI MX.

**Architecture:** Reuse the existing root sorter and move existing classic button nodes, leaving authoritative layout data and handlers untouched. A non-whitelisted one-time operational script updates only the approved OA company field with standard Version history, manifest gating and transaction/audit verification; no recurring default or PO creation.

**Tech Stack:** Existing Frappe/ERPNext runtime, vanilla JS, Node tests, Python unittest, existing brand-only Docker release.

---

### Task 1: Classic sidebar ordering

**Files:** `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`, `deeplinkerp_branding/public/js/deeplinkerp_branding.js`, `deeplinkerp_branding/hooks.py`, `tests/navigation-model.test.js`.

- [ ] Extend the existing full-order test with `arrangeClassicSidebar(controller)`. Use the existing FakeElement node operations; preserve node identity, click handlers and original icon array. Add missing-controller, unknown-root and repeated-order assertions.
- [ ] Run `node --test tests/navigation-model.test.js` and verify failures identify the missing exported adapter.
- [ ] Implement `arrangeClassicSidebar(controller)`: resolve `.custom-filters-right-sidebar-items`, map each button's `dataset.iconLabel` to an existing `controller.items` icon, call `arrangeNavigationRoots` on that projection, and append the same nodes only when order differs. Return whether any order changed. Export the adapter, invoke it in the existing classic branch of `refreshDeskEnhancements`, and increment only navigation/branding asset versions.
- [ ] Run `node --test tests/*.test.js`, `python3 -m unittest tests.test_interface_mode tests.test_boot_branding tests.test_interface_mode_metadata tests.test_purchase_order_assets tests.test_unified_purchase_release`, and JS syntax/diff checks. Rebuild the local brand-only preview, verify classic node order, folders, route highlight, DL/classic switching and unchanged desktop layout.

### Task 2: Audited one-time OA backfill

**Files:** `deploy/production/backfill_historical_oa_company.py`, `tests/test_historical_oa_company.py`.

- [ ] Add pure candidate/manifest tests before implementation: apply_date else creation; exclusive 2026-07-01 boundary; preserve known company; reject missing/invalid dates, duplicate names, non-draft/linked records, wrong count and changed manifest.
- [ ] Run `python3 -m unittest tests.test_historical_oa_company` and verify the missing implementation fails; then implement pure planning/hash helpers and the CLI workflow.
- [ ] CLI accepts preview/dry-run/apply, fixed target YUEWEI MX, actor, expected count, expected manifest and private report path. Apply is restricted to deeplinkerp.com in maintenance mode. Read full OA rows with locks, verify Company/read and OA/write permissions, and reject any mismatched manifest/count before writing.
- [ ] Use `frappe.db.set_value('OA Purchase Request', name, 'target_company', 'YUEWEI MX')` and standard `Version.update_version_info(old_doc, new_doc)` after checking the diff contains exactly the company change and no child changes. Insert the Version as standard framework saves do, within the same transaction. Do not call OA save/submit, PO creation or attachment helpers.
- [ ] Compare all OA rows before/after, allowing only target_company/modified/modified_by for the selected names; require all other existing release-audit hashes unchanged and exactly one Version per changed row. Dry-run rolls back; apply writes its private report before the single commit. Refuse repeat/partial states, do not overwrite them.
- [ ] Run pure tests, Python compile checks and an isolated real-Frappe QA rollback trial to verify Version history and no persistent OA/Version/PO/GL/SLE changes.

### Task 3: Review, release, and acceptance

- [ ] Review changes against the approved spec; run all Node tests and the same isolated real-Frappe brand Python suite as existing CI. Include the new one-time script unit test in the existing unittest CI command.
- [ ] Commit, run CI, verify the remote branding branch is still the frozen ancestor, and coordinate the serial release with the other deployment chat. Use the existing `deploy_unified_purchase.sh` against the verified image and full ID; preserve unrelated applications/assets/business rows.
- [ ] Re-run the production OA preview; capture its exact manifest, perform the dry-run rollback, back up the database, enter maintenance and run the approved apply under the same ERP release lock. Restore service only after verification; errors roll back data and leave an explicit report.
- [ ] Check production health, classic sidebar exact order and interactions, all 148 OA company fields plus the individual Version entries, zero remaining historical pending-company rows, unchanged total/unconverted-order counts, and unchanged PO/GL/SLE/child hashes. Save browser proof.
- [ ] Report added/modified/deleted files, code/test/doc line changes, independent new scenarios versus parameterization, no duplicate sorting/workflow, and remaining external DOM dependency/unknown OA currency/PO generation boundaries.

## Pre-release verification (2026-10-04)

- Existing order cases were extended rather than copied; Node suite: 117 baseline -> 118 passing.
- Isolated Python suite: 28 baseline -> 36 passing (eight new one-time repair scenarios); real Frappe branding suite: 268 passing.
- JS/Python/shell syntax and `git diff --check` pass.
- QA real company/Version write followed by rollback, and injected failure after the second company write followed by rollback, both preserved all 21 audited tables and Version counts with zero persistent changes.
- Local browser confirms the exact classic root order, preserved accounting children, current-route highlighting and DL/classic switching. Authoritative desktop arrays and layouts are not written.
- Independent review found and resolved reverse-only/padded PO links and post-COMMIT exception ambiguity. Apply success now requires reopening a read-only DB connection and verifying durable OA rows, audit hashes and every company-only Version.
- Production release, dry-run/apply and logged-in acceptance remain pending at this commit.
