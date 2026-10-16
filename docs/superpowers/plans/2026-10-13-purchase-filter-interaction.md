# Purchase filter interaction repair

> Execution: inline, test-driven; reuse the existing attached Branding worktree. The user approved fixing the diagnosed filter interaction and deploying it.

**Goal:** One visible, removable representation of every applied condition; company and status controls must not contradict hidden native controls.

**Architecture:** Reuse Frappe standard controls, FilterArea/FilterGroup and the compact-list lifecycle. Preserve advanced AND/OR restrictions, permissions, business-date ordering, export and OA source separation. Convert reused PO standard company/status values to the existing unified query's shared quick fields; advanced criteria stay native. No data migration or business writes.

**Tech stack:** Existing JavaScript/jQuery/Frappe, Node tests, local Frappe browser QA, scoped Vultr image release.

## Reuse and cleanup

- `compact_list.js`: replace the clickable text summary with accessible removable tags. Reuse standard controls instead of constructing a second company/status control. Batch removals/clear with native refresh suppressed and a single final refresh. Delete the duplicated text-summary handler and clear-button handlers.
- `unified_purchase_list.js`: project reused standard company/status values through the existing shared filters, so changing company in the OA tab does not accidentally limit sources to already-linked POs. Keep child-table/advanced native constraints intact and share the same request with export.
- `purchase_order_list.css`: restrained tags, keyboard-focusable removal and responsive wrapping; keep table scrolling, column header and densities.
- Existing Node test files: add independent regression scenarios, reuse fixtures and parameterize shared controls. No parallel filter/query framework.

## Algorithm and boundaries

About 571 orders and fewer than 20 conditions. The old summary scans metadata per condition (`O(MF)`) and opens a different filter layer. Index field metadata once, collect applied conditions once, and remove exact native tuples rather than every condition on a field. Collection/removal is `O(M+F+Q)` time/space, where Q is the bounded quick-control count. Existing backend ordering remains unchanged.

An exception during mutation restores refresh flags, renders actual remaining conditions and reports failure; it must not clear unrelated criteria. Escaped display values and translated Select values; zero/false/arrays handled explicitly. Repeated clicks disabled while filtering. Existing filter storage/native API remains compatible, no migration/retired endpoint required.

## Tasks

- [ ] Baseline: related Node suite and clean production-compatible base.
- [ ] RED: reused control values, exact tag removal, clear batching, OA shared-company query and export consistency.
- [ ] GREEN: implement in the existing functions; remove replaced handlers.
- [ ] Verify: all frontend tests, targeted Python contracts, independent code review.
- [ ] Local browser: company/status with URL/saved filters; remove one/clear all; pagination/sort; expanded items; four procurement pages, desktop/mobile and Classic/DL.
- [ ] Release: single owner, wait for sync lock; current SHA/image and bounded disk prechecks. Build from verified fixed base, use installed on/off/status maintenance helper only at cutover. No migrations, source replay or payment/stock/GL writes.
- [ ] Production read-only acceptance: fresh assets, filters and original symptom; protected business-table audit unchanged. Preserve current/rollback images and audit, clean only proved owned temporary build files.

## Cross-module linkage / consistency

Filter change → procurement list/count/totals/export → same existing query conditions, page reset → no document state change. Company selection in OA source scope → existing authorized source projection → no source reassignment or PO creation. Check request equality, exact retained conditions and unchanged protected business hashes; no database transaction is needed for UI-only state changes.

## Delivery

Report new/modified/deleted code, test scenarios and line changes; no duplicated logic. Remaining unconverted sources still require actual company/supplier/item completion; do not invent values or mass-create orders. Unrelated accounting/source approval UX is outside this repair.
