# Previewed Payment Fee Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and execute each behavior RED then GREEN.

**Goal:** Add a server-owned preview/confirm/amend workflow that safely allocates approved payment sources across shipment batches and writes only the selected fee rules.

**Architecture:** Add additive `payment_preview`, `payment_claim`, and `payment_application` Store tables. A focused `payment_adoption` service reconstructs evidence from current candidates and sources, binds private previews to every mutable dependency, and performs claim/rule writes under the global settlement lock. Existing API/runtime modules only supply permissions, edit leases, and public projections; legacy freight paths remain untouched.

**Tech Stack:** Python, Decimal, SQLite/MariaDB Store adapter, Frappe ledger adapter, pytest.

---

### Task 1: Additive storage

- [ ] Write a failing Store installation test for all three tables and indexes.
- [ ] Run the test and verify missing-table failure.
- [ ] Add schemas and idempotent SQLite/MariaDB indexes.
- [ ] Run the test green.

### Task 2: Server-owned preview and atomic confirmation

- [ ] Write failing tests for read-only preview, safe output, line/key validation, aggregate splitting, exclusive/global capacity, stale dependencies, Decimal precision, replacement isolation, and idempotency.
- [ ] Run each focused test and verify expected missing-behavior failure.
- [ ] Implement source reconstruction, private dependency snapshots, expiry, balance validation, and exact fee-rule creation.
- [ ] Run focused tests green after each minimal behavior group.

### Task 3: Amendments and public/API contracts

- [ ] Write failing tests for five amendment actions, immutable versions, edit lease ordering, audit history, safe public claims, and legacy freight compatibility.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement atomic amendment applications, lifecycle-safe claim release, API wrappers, and additive public projection.
- [ ] Run focused and affected regression tests green.

### Task 4: Verification and delivery

- [ ] Run all settlement/freight/fee tests.
- [ ] Run Python compileall and `git diff --check`.
- [ ] Inspect the diff for unrelated or frontend changes.
- [ ] Commit once as `feat: add previewed payment fee adoption`.
