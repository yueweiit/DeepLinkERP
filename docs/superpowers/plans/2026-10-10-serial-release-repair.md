# Serial release repair

Goal: complete the authorized child-site archival and one joint main-site release without replaying business documents or overwriting the failed attempt.

Reuse `joint_release_guards.py`, native RQ reads, `DDLReceipt`, the frozen app overlays, and existing retirement/native metadata audits. Do not replace business code or clone a database.

The old all-PID1 TERM design is invalid: nginx has a Bash parent, scheduler handles INT, and native Node PID1 cannot complete its default signal exit. Business processes must finish normally. The stateless native relay may be terminated only after ingress, scheduler, workers, and backend have stopped, every old database session/transaction is absent, and relay-owned sockets contain no client or unreviewed connection. Record this accurately as an idle relay termination, not a graceful exit. Unknown installed handlers or outstanding work block this path.

The read-only RQ failure has now reproduced: an expired finished registry references a missing job hash. Reuse the existing atomic historical-presence and expiry evidence, across all shared sites, rather than deleting Redis data or pretending the queue is main-only. Missing live jobs still fail.

Input: six service identities, bounded process and RQ inventories, database sessions. Batch identity indexes and one socket inventory give O(P+R+D) time/space. Poll only changing liveness during the bounded stop window; no per-job source/user queries.

- [x] Add failing tests for service-specific plans, idle relay proof, complete shared historical RQ evidence, and private command error evidence.
- [x] Replace the single TERM loop; keep durable identity checks, warm worker/web logs and post-RQ verification.
- [x] Validate native frontend, scheduler and relay mechanisms in fresh isolated containers; preserve all failed native experiments. Local scheduler INT/Aborted!/1 and frontend master TERM/0 passed. Fresh Vultr frontend TERM/0 and idle relay KILL/137 passed without touching existing production containers. The initial frontend probe's missing external kill executable remains recorded; the shell builtin replacement passed.
- [ ] Run focused tests and independent review; freeze a new commit and archive, retaining unchanged app overlays.
- [ ] Use a new dated attempt, hold both release/source locks, verify 15 backup hashes and exact configs, pause only the existing timer, drain and archive exactly three child site directories. Keep every database and historical attachment.
- [ ] Verify durable exact-host 410 routes and main health, then execute existing joint release against the approved completed archival receipt. Capture main backup and metadata/business before/after audits.
- [ ] Verify logged-in operating expenses, navigation and original links read-only; restore source timer and perform only owned-build cleanup after acceptance.

No bank transfers, voucher/receipt submission, stock rebuild, opening balances or broad image/volume/cache pruning. Failures retain private stdout/stderr and the original Applying receipt. Rollback is limited to the pre-resume metadata/config window already implemented; after first serving resume, inspect and repair forward.

Focused verification: 158 tests, 3 environment-dependent skips; shell syntax and diff whitespace checks pass. Independent review identified and resolved full relay argv/preload/source-mount validation, unregistered terminal RQ evidence, and private command diagnostics. Source terminal failure is retained truthfully and distinguished from live work; the latest native source run has independently returned success.
