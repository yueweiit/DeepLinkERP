# Procurement module integration acceptance

Candidate base: `c4ea01e46a3ba2be7fc3984d1f586a685e93548d`, also the remote HEAD at the final read-only check. This is a local branding candidate on `codex/procurement-integration-recovery`; it has not been pushed or deployed. Implementation follows the three approved procurement drawings, whose pixels were inspected. Group finance restructuring and operating expenses remain outside this change.

## Delivered behavior

Buying now groups Purchase Orders, Purchase Receipts, purchase-source payables and purchase payment records in both navigation modes, the Buying Workspace and procurement list tabs. Existing unrelated ERP navigation, custom filtered shortcuts, charts, cards and generic Purchase Invoice/Payment Entry routes remain available. Navigation reconciliation preserves existing child-row identities and is unchanged on a second run. It neither reloads nor saves existing Pages or Roles.

Purchase Orders use the Sales compact engine's inline detail table: the row arrow opens permitted material quantities, prices, received quantities and fixed order progress. Progress is fetched in batches of at most 100; material detail is fetched only when expanded. Financial refreshes update the expanded progress even when the PO timestamp has not changed, retaining permitted material detail. Order unpaid is explicitly distinguished from invoice outstanding.

The new payables Page includes a native PI only when it has a readable PO or PR source. A PI referencing both is listed once. Operating-only invoices and unreadable sources are excluded. Amount and outstanding remain the entire native invoice; shared or mixed invoices have a visible label and explanation. Draft, submitted, cancelled and return states remain distinct.

Finance keeps the existing payment drawer: Confirm payment is primary, Save draft secondary, an existing draft is reviewed and continued, and native document/record links and return context are retained. Clicking a particular invoice does not resume an unrelated invoice's draft; a now-ineligible clicked invoice is not silently substituted. Native accounting, company permissions, field permissions and workflow approval remain authoritative.

## Permission boundary

The order-progress service checks native PO/source/company/field access before any private accounting read and returns only fixed order summary fields and permitted material fields. It returns no PI/PE identifiers, bank accounts or financial document details to procurement users.

In native synthetic QA, a Purchase User + Purchase Manager can read permitted order progress but cannot create/write/submit/cancel/delete PI or PE. Actual `frappe.client.save` and `frappe.client.cancel` calls are also rejected for both doctypes. Payables and payment-create APIs reject the buyer. A combined Purchase + Accounts user retains finance capability; role membership is not used as a blanket purchase-role rejection.

The new payables Page allows System Manager, Accounts User and Accounts Manager. Existing payment-records Page role rows are unchanged. Procurement financial controls and navigation are disabled when native Payment Entry read access is absent; this is supplemented by server/API and native document checks.

Production custom DocPerm, user-role and User Permission assignments, including Nelly, could not be inspected because production SSH authentication was unavailable. No shared production permission or user assignment has been changed. Any necessary permission change must first identify affected roles, users and companies for the release owner to approve.

## Reuse and changes

Recovered task-3 work was read and copied serially into this independently registered local worktree. The old worktree, database, Redis, volumes and containers were not modified. The recovery manifest is outside Git at `../evidence/recovered-source-manifest.json`.

Reused: compact list paging/filter/sort/selection/viewport support; Sales' detail table; `_RecordReader`, `_read`, `_source_links`, `_invoice_row` and native `invoice_balance`; existing payment drawer, draft continuation, company/workflow checks and return context. There is no second compact engine, balance formula, ledger, permission allocator or payment drawer.

Source/test diff excluding this report: **21 files, +893 / -147 lines**. Product/configuration/translations: **+576 / -136**. Tests and guarded native QA: **+317 / -11**. The six new files are the Page JS/JSON, navigation reconciler, PO summary service, navigation contract tests and native integration QA. Fifteen existing files are modified; no whole file is deleted. Most CSS replacements extend shared selectors to the new Page. The former Sales-specific table-render loop is removed in favor of the shared renderer; stale default-column and exact old asset-version assertions are updated.

The existing selection implementation is unchanged. Its test now checks the compact asset's presence and relative ordering without hardcoding the previous cache version; the original baseline assertion is retained in `../evidence/selection-baseline.py`.

Generic native PI/PE callers, OA union mode, existing advance columns and the existing payment APIs remain compatible. The new source-scoped Page/service supplement those real callers. There is no temporary compatibility wrapper or deadline in this candidate: removal requires an explicit feature retirement and a verified zero-caller migration.

## Executed verification

| Check | Actual result and evidence outside Git |
| --- | --- |
| Node | 223 passed, zero failures/skips: `../evidence/candidate-node-final.log`. |
| Configuration | 55 passed in the original affected-suite run; final expanded run passes all 63 in isolated module processes: `../evidence/candidate-config-isolated.log`. |
| Branding Python | 328 passed and 46 subtests passed: `../evidence/qa/python-final.log`. |
| Existing native QA | 22 purchase-payment, 13 document/action and 6 payment-completion cases passed: `../evidence/qa/native-regressions.log`. Each rolled back its changes. |
| New native QA | Seven business scenarios passed, including actual native RPC mutation denials: `../evidence/qa/integration-final-native-api.log`. |
| Navigation | First reconcile updates Buying; the second makes no change: `../evidence/qa/initialize.log`. Contract tests preserve existing IDs/custom entries and prohibit Page/Role saves. |
| Static checks | Node syntax, Python AST parsing and staged/unstaged whitespace checks passed. Python AST checks avoid writing host cache directories. |

An aggregate discovery attempt is also retained in `../evidence/candidate-config-final.log`: older configuration modules share cached fake Frappe modules, causing three failures and three errors in interface-mode tests. Running each module in a fresh process passes all 63, including interface-mode tests, without modifying unrelated test or product code. The affected-suite run remains 55/55.

The seven new native scenarios are separate business/privilege relationships: (1) applied advance 1000 + direct payment 2000 gives PO paid 3000/unpaid 7000 and 40% received without double counting; (2) buyer fixed projection and PI/PE native mutation denial; (3) buyer payables/payment API denial; (4) cross-company source denial before private reads; (5) combined purchase/finance roles with native outstanding 1000; (6) shared purchase/operating PI deduplication with whole-invoice amounts and no fabricated order allocation; (7) orphan PI uncertainty rather than an incorrect zero-paid claim.

The new integration script refuses any site/database other than `po-grid-qa.localhost` / `qa_procurement_5`. Final before/after counts match: PO139, PR114, PI5, PE6, GL16, Payment Ledger8, User6 and User Permission3.

Five new server scope tests parameterize equivalent PO-only/PR-only/both-source and document-state cases. Three navigation tests cover different identity/content/mutation contracts. Two drawer tests cover clicked-invoice eligibility and draft choice. The added financial-refresh frontend regression covers a changing accounting summary with an unchanged PO timestamp. These assertions exercise independent behavior, rather than reproducing implementation branches line by line; test-runner/subtest counts are not presented as independent scenarios.

## Actual browser evidence

All UI screenshots are from the independently running localhost64234 synthetic site. They are not the approved drawings and contain no production transactions. No fault injection or long Chrome wait was used. The independent Compose project is `dlp-procurement-recovery-5`; the old 64232/64233 environments and production were untouched.

Chinese and Spanish, Classic and DL, and 1920×1080 / 1440×900 / 1024×768 were exercised. Final order screenshots are `../evidence/ui/orders-final-{classic,dl}-{zh,es}-{1920,1440,1024}.jpg`, with matching geometry JSON. At all 12 combinations, document width equals the viewport, expanded detail is present, header/body columns align at zero-pixel displacement and paging remains within the viewport.

The 12 finance drawer screenshots use `finance-{classic,dl}-{zh,es}-drawer-{1920,1440,1024}.jpg`; footer controls remain inside the viewport, including wrapped Spanish labels. Existing synthetic draft ACC-PAY-2026-00016 is resumed; no confirm/save action was performed during UI inspection.

Actual mouse drags exercised both scrollbars. An observed failure where horizontal scrolling hid procurement tabs was fixed by placing the tabs outside the result scroller. Final proof is `scroll-classic-zh-fixed-{before,horizontal,both}.jpg` / `.json` and `scroll-dl-es-{horizontal,both}.jpg` / `.json`: frozen select/sequence/name/supplier columns remain interactive, headers stay pinned, expanded material remains reachable and row/header alignment is unchanged. `scroll-pointer-selection.json` verifies an actual coordinate checkbox click preserves horizontal/vertical scroll and expansion.

Page 2 of 139 orders, native name sorting, quick filtering, selection across density changes, native Company advanced search, drawer close and native PI return-to-context were exercised. Supporting images include `list-classic-zh-page2.jpg`, `company-selection-live.jpg` and `finance-native-pi-return.jpg`. The shared-invoice Spanish label and date header are visually verified in `payables-final-es-shared.jpg`.

Two delivery copies are explicitly named as synthetic QA and saved in Library, with successful local identity writeback:

| Image | Library identity |
| --- | --- |
| 采购隔离QA-合成数据-订单物料与进度.jpg | `libfile_b0247928339c8191b96a66623de957b6` |
| 采购隔离QA-合成数据-财务付款抽屉.jpg | `libfile_ab6251c81cf48191a4cf1f33da4d31d3` |

They also remain at `../evidence/deliverables/`. Library create confirmations and local metadata evidence are retained outside Git. The prepared helper was unavailable before any preparation/write; the documented direct-create fallback then succeeded for both images.

## Release conditions and debt

The release owner must obtain explicit deployment authorization, restore the authorized production SSH identity and run the existing strict source/business/permission audit, backup and frozen-image rollback process against the final candidate. No deployment is claimed here.

The cached synthetic QA image lacks Git metadata for China Finance and CRM; their exact requested revisions `4f019f91` / `b0a9c211` are therefore not claimed as verified. This candidate changes branding only and leaves those application sources untouched. Their production revisions still need the release owner's legitimate read-only audit.

Remaining debt: permission/source filtering currently evaluates candidate invoices before pagination to keep counts exact; it follows the existing reader and bulk preload pattern but scales with candidate count. Shared/cross-currency/return/mismatched/orphan invoice settlement deliberately shows an uncertainty notice instead of invented PO allocation. Complex accounting remains in native forms. Some older untouched native ERP labels retain their previous localization. No unrelated finance redesign or permission migration is introduced.
