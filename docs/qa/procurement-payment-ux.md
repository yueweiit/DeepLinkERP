# Procurement payment UX acceptance

Baseline: `795ff7062e3aeba00882fcc45bd0843f93a2eb3d`. This change is branding only; CRM and China Finance source and production permissions are outside the change.

## Result and reuse

The payment drawer now has **Confirm payment** as its primary action and **Save draft** as its secondary action. Confirmation saves and submits the native Payment Entry in one HTTP transaction. It keeps native account validation, invoice balances, field permissions and workflow transitions. A configured workflow remains pending until the user selects an allowed action. A user without submit permission sees the next step rather than a payment-success message.

`record_payment` composes the existing `create_payment_draft` and `submit_document` APIs. `complete_payment` composes the existing draft editor and native submission API. Neither implements accounting or a new ledger. The invoice current-read lock serializes overlapping PO/PR requests; a per-user request token prevents identical retries from repeating the write. A known native rejection acknowledges failure only after full rollback. An uncertain network response keeps the original payload and token across drawer close/reopen.

Existing supplier-payment drafts require manual review of amount, account and references. Matching PI/company/supplier never implies that a business draft is the same intended payment. A discovered draft is shown without overwriting or submitting it. Several visible drafts are presented for the user to select. A completed operation retains a Payment Entry link, source link, payment-record link and refreshed native balance. Submitted, draft and cancelled entries remain distinct.

PO and PR drafts open the correct native form. The form provides a return action restoring the original procurement route, quick filters, page and grid scroll position. Receipt submission remains a native stock action; the payment flow never submits an unreceived receipt.

## Changes and compatibility

- Added: native completion/request orchestration, browser recovery token, native draft navigation/return context, success view, six guarded native QA scenarios and four server unit tests.
- Modified: existing payment drawer, receipt row actions, permission-aware order progress projection, Spanish strings, drawer layout and cache versions. Release evidence goes to `private/release-evidence`, avoiding the Frappe backup-cleanup namespace.
- Removed: the payment drawer's separate save-then-submit confirmation flow and assertions for that obsolete interaction. Purchase Invoice's existing explicit-save flow remains unchanged.
- No duplicate ledger, balance formula, permission rules or payment-plan allocator was added. The compatibility `create_payment_draft`, `update_payment_draft` and `submit_document` endpoints remain callable; existing native QA and older callers still use them. Their removal requires a separately verified zero-caller migration, not this release.

## Verification

| Check | Result |
| --- | --- |
| Node suite | 209 passed; baseline 204. Replaced obsolete two-step payment expectations and added independent failure/retry, concurrency, draft-resume and closed-drawer cases. |
| Configuration/release recovery suite | 60 passed, including frozen-image rollback and strict source/Page-permission audit checks. |
| Branding Python suite | 323 passed, 40 subtests passed; baseline 319. Four new independent completion-policy tests. |
| Existing native procurement QA | 22 payment/stock/advance/permission scenarios and 13 document/record scenarios passed; transaction counts restored. |
| New native completion QA | Six independent scenarios passed: direct/partial settlement, existing draft edit, native submit failure after posting, real workflow (including action named Submit), no-submit user, multiple business drafts. Every scenario rolled back transaction and temporary permissions/workflow records. |
| Native concurrent requests | Four independent Frappe connections, with repeated and distinct request IDs: one unique submitted PE, two native GL rows, outstanding 1000 after payment 3000 against PI4000. |
| Chrome UI | Chinese and Spanish at 1024/1280/1512 ×768. Primary/secondary buttons, long labels and scrolling drawer stayed within viewport. Actual partial payment showed PE link and native remaining balance; native PR draft navigation returned to the original list without stock submission. |

Counts above are test-runner counts, not a claim that parameter variants are independent scenarios. The no-submit/workflow frontend loop has two inputs to one policy test; native workflow tests and the native no-submit test are separate business scenarios. Existing 40 Python subtests retain their parameterization.

An additional real-browser network-block experiment did not complete because the Chrome control tool timed out; it is **not** counted as verified. The network-failure/retry and close/reopen behaviors are covered by executable frontend tests. Temporary CDP network blocking and viewport overrides were reset. The isolated QA Administrator language was restored from its recorded original value (`zh`). A pink floating translation-extension control visible in some screenshots belongs to `#immersive-translate-popup`, not the ERP drawer; no browser extension settings were changed.

The dedicated synthetic database uses `dlp-payment-ux-db-20261005`; the new QA script refuses any other site/database. The independent frontend is localhost64232; localhost64231 and production were untouched. Committed concurrent/browser fixtures are restored from the initial dedicated QA backup before handoff. Restoration evidence and screenshots are retained outside Git in the task's `evidence/payment-ux` directory.

## Release and debt

One coordinated release owner merges this commit with the sales-review candidate, merges `es.csv` by key and unifies hooks cache versions. The final combined SHA must pass full CI and affected browser checks before one release under the existing exclusive lock, complete backup, frozen previous image and strict before/after source/business/permission audit. CRM/Finance must remain at their existing revisions. This document does not claim production deployment or combined-SHA CI completion.

Remaining debt: older untouched procurement table/form text is not fully localized; complex shared/cross-currency/refund/advance cases continue through native forms; return context relies on optional session storage and preserves compact-list quick filters/page/scroll while native advanced filters retain the existing list's cache behavior. Idempotency records retain the existing 24-hour Redis lifetime. No compatibility endpoint or unrelated finance redesign is retired here.
