# Procurement module integration acceptance

Candidate base: `c4ea01e46a3ba2be7fc3984d1f586a685e93548d`, also the remote HEAD at the final read-only check. This is a local branding candidate on `codex/procurement-integration-recovery`; it has not been pushed or deployed. It includes recovered procurement commit `bd8607b4594cb87df2d7d73215ccdf93df13b549` and the approved attachment/direct-payment increment. The three procurement drawings and payment drawing v2 were inspected as actual pixels. Group finance restructuring and operating expenses remain outside this change.

## Delivered behavior

Buying now groups Purchase Orders, Purchase Receipts, purchase-source payables and purchase payment records in both navigation modes, the Buying Workspace and procurement list tabs. Existing unrelated ERP navigation, custom filtered shortcuts, charts, cards and generic Purchase Invoice/Payment Entry routes remain available. Navigation reconciliation preserves existing child-row identities and is unchanged on a second run. It neither reloads nor saves existing Pages or Roles.

Purchase Orders use the Sales compact engine's inline detail table: the row arrow opens permitted material quantities, prices, received quantities and fixed order progress. Progress is fetched in batches of at most 100; material detail is fetched only when expanded. Financial refreshes update the expanded progress even when the PO timestamp has not changed, retaining permitted material detail. Order unpaid is explicitly distinguished from invoice outstanding.

The new payables Page includes a native PI only when it has a readable PO or PR source. A PI referencing both is listed once. Operating-only invoices and unreadable sources are excluded. Amount and outstanding remain the entire native invoice; shared or mixed invoices have a visible label and explanation. Draft, submitted, cancelled and return states remain distinct.

Finance uses the existing payment drawer with the approved v2 compact upload area, optional multiple private attachments, folded remarks, and Cancel/Confirm payment footer. Normal confirmation creates/submits once through the existing native transaction; it has no Save draft button. Native workflow/submit permissions still control whether a payment actually posts. Existing drafts require explicit review/continuation and are not deleted or silently replaced. Clicking a particular invoice does not resume an unrelated invoice's draft; a now-ineligible clicked invoice is not silently substituted. Native document/record links and return context remain available.

Uploads reuse native FileUploader and the native multipart handler. Every selected file must receive a private File acknowledgement before confirmation is enabled; the native uploader's early Promise resolution is insufficient. Failed files retain successful siblings, and explicit retry addresses only a known failed file. An unknown payment response retains the original payload/token and uploaded files for explicit retry; attachment additions/removals/retries are locked until that request is resolved. File selections are captured before clearing the browser's live FileList, a bug found and corrected in actual Chrome testing.

The server binds only files registered in this user's source-scoped session, with native source/company/PE and File permission checks, matching ownership, private status, and no prior attachment. Binding uses native `File.create_attachment_copy`, which preserves the existing blob without PDF text re-encoding or a custom storage path. Attachment links, payment changes and native ledger posting share the existing c4 transaction/rollback boundary. Exact upload/payment retries do not duplicate Files or ledger entries. Explicit remove/cancel deletes only this session's owned, private, unbound native Files; a committed/uncertain payment never triggers product cleanup.

## Permission boundary

The order-progress service checks native PO/source/company/field access before any private accounting read and returns only fixed order summary fields and permitted material fields. It returns no PI/PE identifiers, bank accounts or financial document details to procurement users.

In native synthetic QA, a Purchase User + Purchase Manager can read permitted order progress but cannot create/write/submit/cancel/delete PI or PE. Actual `frappe.client.save` and `frappe.client.cancel` calls are also rejected for both doctypes. Payables and payment-create APIs reject the buyer. A combined Purchase + Accounts user retains finance capability; role membership is not used as a blanket purchase-role rejection.

The new payables Page allows System Manager, Accounts User and Accounts Manager. Existing payment-records Page role rows are unchanged. Procurement financial controls and navigation are disabled when native Payment Entry read access is absent; this is supplemented by server/API and native document checks.

Attachment upload, binding and listing preserve the finance boundary. Procurement cannot begin a financial upload session or list PE attachments. Real HTTP downloads return 200 for finance and 403 for procurement, including after native submission. No bank-account read scope or role/user assignment is added.

Production custom DocPerm, user roles and company scope were subsequently inspected read-only after normal SSH authentication recovered. Four pure procurement users have no PI/PE mutation capability; Nelly retains finance capabilities and 14 companies. No shared production permission or user assignment has been changed.

## Reuse and changes

Recovered task-3 work was read and copied serially into this independently registered local worktree. The old worktree, database, Redis, volumes and containers were not modified. The recovery manifest is outside Git at `../evidence/recovered-source-manifest.json`.

Reused: compact list paging/filter/sort/selection/viewport support; Sales' detail table; `_RecordReader`, `_read`, `_source_links`, `_invoice_row` and native `invoice_balance`; existing payment drawer, draft continuation, company/workflow checks, request idempotency and return context; native FileUploader, private File lifecycle and attachment-copy API. There is no second compact engine, balance formula, ledger, permission allocator, payment drawer or file storage.

Final cumulative source/test/release-tool diff against c4, excluding this report: **32 files, +2469 / -199 lines**; product/configuration/translations **+1122 / -166**, tests/guarded QA **+1095 / -31**, release tooling/CI **+252 / -2**. Eleven files are added and twenty-one modified; none are deleted. New-file formatting accounts for part of the extra lines; legacy whole-file reformatting was removed. The new metadata helper and five unit methods (ten parameterized subcases) verify allowed differences, preserved identities, strict business equality and precise recovery instead of weakening the audit.

The recovered procurement portion before attachments changed **21 source/test files, +893 / -147 lines**: product/configuration/translations **+576 / -136**, tests/guarded native QA **+317 / -11**. It added six files and changed fifteen. The former Sales-specific table-render loop was removed for the shared renderer.

The attachment increment changes **10 source/test files, +604 / -45 lines**: product/configuration/translations **+308 / -33**, tests/guarded native QA **+296 / -12**. Its three new files are the session/scope attachment service, service contract tests and guarded native attachment QA. Seven existing files change. No whole file is deleted. The unused PE draft-save frontend function and two obsolete PE refresh-control test variants are removed; generic PI controls and real native save APIs remain. Asset assertions check presence/order rather than stale cache versions. The final JS cache version is `0.0.15`, CSS `0.0.5`.

The existing selection implementation is unchanged. Its test now checks the compact asset's presence and relative ordering without hardcoding the previous cache version; the original baseline assertion is retained in `../evidence/selection-baseline.py`.

Generic native PI/PE callers, OA union mode, existing advance columns and the existing payment APIs remain compatible. The new source-scoped Page/service supplement those real callers. There is no temporary compatibility wrapper or deadline in this candidate: removal requires an explicit feature retirement and a verified zero-caller migration.

## Executed verification

| Check | Actual result and evidence outside Git |
| --- | --- |
| Node | Final 229 passed, zero failures/skips: `../evidence/attachments-node-final.log`. |
| Configuration | 63 passed in isolated module processes: `../evidence/attachments-config-final.log`; final asset-version follow-up 11 passed: `../evidence/attachments-assets-final.log`. |
| Branding Python | Final 333 passed and 59 subtests passed: `../evidence/qa/attachments-python-final.log`. |
| Existing native QA | 22 purchase-payment, 13 document/action and 6 payment-completion cases passed again: `../evidence/qa/attachments-native-regressions.log`. Each rolled back its changes. |
| Procurement native QA | Seven business scenarios passed again, including actual native RPC mutation denials: `../evidence/qa/attachments-procurement-integration.log`. |
| Attachment native QA | Five transaction/lifecycle groups plus five scope variants passed: `../evidence/qa/attachments-native-third.log`. Includes post-ledger failure/full rollback and same-token recovery. |
| Native HTTP | Two real multipart PDF uploads, byte-identical finance downloads, exact retry deduplication, procurement 403 and scoped cancellation: `../evidence/qa/attachments-http.log`. |
| Actual browser submission | UI-confirmed PE16 posts one native GL pair, PI9 outstanding becomes 0, two private attachments remain byte-identical; downloads finance 200/procurement 403: `../evidence/qa/attachments-ui-submitted-verification.json` / `attachments-ui-submitted-http.json`. |
| Navigation | First reconcile updates Buying; the second makes no change: `../evidence/qa/initialize.log`. Contract tests preserve existing IDs/custom entries and prohibit Page/Role saves. |
| Static checks | Node syntax, Python AST parsing and staged/unstaged whitespace checks passed. Python AST checks avoid writing host cache directories. |

An aggregate discovery attempt is also retained in `../evidence/candidate-config-final.log`: older configuration modules share cached fake Frappe modules, causing three failures and three errors in interface-mode tests. Running each module in a fresh process passes all 63, including interface-mode tests, without modifying unrelated test or product code. The affected-suite run remains 55/55.

The seven new native scenarios are separate business/privilege relationships: (1) applied advance 1000 + direct payment 2000 gives PO paid 3000/unpaid 7000 and 40% received without double counting; (2) buyer fixed projection and PI/PE native mutation denial; (3) buyer payables/payment API denial; (4) cross-company source denial before private reads; (5) combined purchase/finance roles with native outstanding 1000; (6) shared purchase/operating PI deduplication with whole-invoice amounts and no fabricated order allocation; (7) orphan PI uncertainty rather than an incorrect zero-paid claim.

The new integration script refuses any site/database other than `po-grid-qa.localhost` / `qa_procurement_5`. Final before/after counts match: PO139, PR114, PI5, PE6, GL16, Payment Ledger8, User6 and User Permission3.

The attachment native script has the same exact site/database guard. Its native File/ledger scenarios all restore counts. Actual Chrome submission is separately protected by a newly created synthetic QA snapshot: after proof, normal-permission cleanup addresses only the two captured URLs/four owner-checked File IDs, then this task's QA database snapshot is restored. Final counts match PO139/PR114/PI5/PE6/GL16/Payment Ledger8/China Voucher8/File2 (the two native folders)/User6/User Permission3; PE16's draft status and exact original modified value are unchanged. Evidence: `../evidence/qa/attachments-ui-restored-verification.json`. No production or other QA snapshot is used.

Five new server scope tests parameterize equivalent PO-only/PR-only/both-source and document-state cases. Three navigation tests cover different identity/content/mutation contracts. Two drawer tests cover clicked-invoice eligibility and draft choice. The added financial-refresh frontend regression covers a changing accounting summary with an unchanged PO timestamp. These assertions exercise independent behavior, rather than reproducing implementation branches line by line; test-runner/subtest counts are not presented as independent scenarios.

Attachments add eight frontend behavior regressions, while removing the two obsolete PE refresh variants: FileList lifetime, per-file acknowledgement gating, partial failure, explicit cleanup, failed-only retry, uncertain-payment retention, staged-draft handoff and optional/no-file compatibility. Five backend methods use 13 subtests for equivalent invalid-file/list/scope inputs. Native QA reuses the existing synthetic seed instead of another fixture/ledger implementation; its five scope variants are parameterized rather than presented as five independent business workflows. The additional service/QA lines implement the upload-request versus payment-transaction boundary and verify its rollback/privilege contracts.

## Actual browser evidence

All UI screenshots are from the independently running localhost64234 synthetic site. They are not the approved drawings and contain no production transactions. No fault injection or long Chrome wait was used. The independent Compose project is `dlp-procurement-recovery-5`; the old 64232/64233 environments and production were untouched.

Chinese and Spanish, Classic and DL, and 1920×1080 / 1440×900 / 1024×768 were exercised. Final order screenshots are `../evidence/ui/orders-final-{classic,dl}-{zh,es}-{1920,1440,1024}.jpg`, with matching geometry JSON. At all 12 combinations, document width equals the viewport, expanded detail is present, header/body columns align at zero-pixel displacement and paging remains within the viewport.

The original procurement drawer screenshots remain as `finance-{classic,dl}-{zh,es}-drawer-{1920,1440,1024}.jpg`. The final v2 evidence is **12 actual uploaded-file screenshots**: `attachments-{classic,dl}-{zh,es}-uploaded-{1920,1440,1024}.jpg`, with geometry JSON. All pixels were inspected: two acknowledged files, long filenames ellipsized, folded remarks, document width equals viewport, and unobscured Cancel/Confirm footer. Native FileUploader uploads were exercised in all four language/mode combinations. Explicit removal/cancellation is also exercised, with native counts restored.

One real Chrome confirmation on the named synthetic PE16 is saved as `attachments-ui-native-submitted.jpg`; it shows submitted state, the actual payment record link and both private file links. This is the isolated test result before snapshot restoration, not a production payment. The actual browser-downloaded PDF matches the fixture's bytes. No Chrome fault injection or long wait was used.

The user explicitly authorized enabling the ChatGPT Chrome extension's file-URL access. The tool's internal-URL policy blocked opening extension settings; no alternate surface was used. The user completed the setting manually, the same Chrome profile/extension instance reconnected, and the original supported file chooser then succeeded. No other security/access setting was changed by this task; viewport overrides were reset after QA.

Actual mouse drags exercised both scrollbars. An observed failure where horizontal scrolling hid procurement tabs was fixed by placing the tabs outside the result scroller. Final proof is `scroll-classic-zh-fixed-{before,horizontal,both}.jpg` / `.json` and `scroll-dl-es-{horizontal,both}.jpg` / `.json`: frozen select/sequence/name/supplier columns remain interactive, headers stay pinned, expanded material remains reachable and row/header alignment is unchanged. `scroll-pointer-selection.json` verifies an actual coordinate checkbox click preserves horizontal/vertical scroll and expansion.

Page 2 of 139 orders, native name sorting, quick filtering, selection across density changes, native Company advanced search, drawer close and native PI return-to-context were exercised. Supporting images include `list-classic-zh-page2.jpg`, `company-selection-live.jpg` and `finance-native-pi-return.jpg`. The shared-invoice Spanish label and date header are visually verified in `payables-final-es-shared.jpg`.

Two delivery copies are explicitly named as synthetic QA and saved in Library, with successful local identity writeback:

| Image | Library identity |
| --- | --- |
| 采购隔离QA-合成数据-订单物料与进度.jpg | `libfile_b0247928339c8191b96a66623de957b6` |
| 采购隔离QA-合成数据-财务付款抽屉.jpg | `libfile_ab6251c81cf48191a4cf1f33da4d31d3` |

They also remain at `../evidence/deliverables/`. The finance image is updated to the actual v2 uploaded-file drawer under its same Library identity; the report is also replaced under its existing identity. Library confirmations and local metadata evidence remain outside Git. The prepared helper was unavailable before any preparation/write; the documented owned-file direct route is used without creating duplicate identities.

## Release conditions and debt

The user has explicitly authorized procurement and attachments to deploy together. Existing documented SSH authentication now succeeds, with no secret read or new credential. The production release has not yet cut over at this report revision.

Production read-only preflight confirms all six services at branding `c4ea01e`, Finance `4f019f91f36aa549df1854d2df0b60e20c01751c` and CRM `b0a9c211f234e3751cdd2e0bb0bac36fe726b45f`. Runtime source hashes match the protected commits; two existing Finance test-file differences and three CRM test-file differences are preserved, not overlaid. All tracked branding files match c4; existing AppleDouble/build outputs are retained. Four pure procurement users cannot create/write/submit/cancel/delete PI or PE. Nelly retains finance capabilities and all 14 companies. No shared role change is needed.

Release preparation reuses the existing exclusive lock, full database/files backup, frozen image, six-service cutover and strict source/business/configuration audit. It adds only the missing standard Page through Frappe's native importer; existing Pages are verified without reload. The exact Buying metadata receipt retains existing child IDs/custom entries, freezes all other navigation and Has Role rows, verifies a second reconcile writes nothing and supports exact restoration. A stale pre-existing Buying report link is preserved; new canonical targets are checked before saving. Seven native synthetic metadata scenarios and 28 release unit tests pass, with the original synthetic database restored.

Final local checks after release preparation: 229 Node, 333 Python plus 59 subtests, and 68 configuration/release tests pass. All new files pass the repository pre-commit configuration. The c4 baseline and candidate each have the same eight Ruff diagnostics; baseline whole-file formatting and ESLint failures also reproduce. Broad legacy reformatting is removed. Final CI statuses must be reported individually rather than called all green; the default branch API reports no protection, and no required check is bypassed.

Remaining debt: permission/source filtering currently evaluates candidate invoices before pagination to keep counts exact; it follows the existing reader and bulk preload pattern but scales with candidate count. Shared/cross-currency/return/mismatched/orphan invoice settlement deliberately shows an uncertainty notice instead of invented PO allocation. Complex accounting remains in native forms. Some older untouched native ERP labels retain their previous localization. No unrelated finance redesign or permission migration is introduced.

Native attachment copy retains the uploader's original private File metadata and adds the PE-bound copy, sharing one blob. Product cleanup deliberately excludes committed payment files. Browser exit, navigation, expired session metadata and unconfirmed upload outcomes may therefore retain private uploads; there is no File deletion timer, global orphan scan or automatic cleanup job. Any later retention policy requires separate approval and native permission/ownership rules. Existing real generic/native PI/PE callers and no-attachment request fingerprints remain compatible; removal requires a verified zero-caller retirement, with no invented migration deadline.
