# Local settlement integration checks

`run_settlement_frappe_integration.py` exercises the settlement backend against real Frappe and MariaDB. It refuses to connect unless the site is `settlement-test.local` and its configured database host is `oc-settlement-test-db`.

Prerequisites: an isolated, migrated Frappe test site with the Overseas Costing app installed; the current app package copied to `/tmp/settlement-code/overseas_costing`; no OA, object storage or ERP connections are required. The script reads the site's existing configuration through Frappe and never prints credentials. It creates synthetic `LOCAL-*` test records with a unique run identifier and leaves them on the disposable site for inspection.

From the costing worktree, using the existing local backend container:

```sh
docker cp overseas_costing overseas-cost-local-backend-1:/tmp/settlement-code/
docker cp overseas_costing/tests/integration/run_settlement_frappe_integration.py overseas-cost-local-backend-1:/tmp/run_settlement_frappe_integration.py
docker exec -e PYTHONPATH=/tmp/settlement-code -w /home/frappe/frappe-bench/sites overseas-cost-local-backend-1 /home/frappe/frappe-bench/env/bin/python /tmp/run_settlement_frappe_integration.py
```

Successful runs print one JSON result per check and finish with `integration_complete`. Coverage includes idempotent schema installation and unique indexes, real document persistence, zero final fees, quantity changes and packing review, frozen confirmed versions and idempotent adjustment drafts, application/rebind rollback after injected failures, and concurrent confirmation through independent database connections on both sides of the one-to-one association.

This is an opt-in integration script, not part of the default pytest run. Do not change the site or database-host guard to target production or an existing demo site.

## Frappe document and precision checks

`run_settlement_document_frappe_integration.py` uses the same site/database guard and creates distinct `LOCAL-DOC-*` fixtures plus one local user with the costing role. Welcome email is disabled. After copying the current package as above, run:

```sh
docker exec -e PYTHONPATH=/tmp/settlement-code -w /home/frappe/frappe-bench/sites overseas-cost-local-backend-1 /home/frappe/frappe-bench/env/bin/python /tmp/settlement-code/overseas_costing/tests/integration/run_settlement_document_frappe_integration.py
```

The script tests actual Frappe File and Attachment insertion, private file access for the costing role and denial to Guest, physical packing fill precedence, separate shipped/purchase quantities, preservation of independent purchase values, item-review acknowledgement clearing document blockers, frozen adjustment/history preservation, explicit retirement, queued retry, and exact six-place fee persistence including stable remainder after reordered detail input. A previously unattached cached File may be adopted by Frappe's Attach-field hook; already-owned historical File links must remain unchanged when a new version reuses the same URL.

Parsed packing documents and their synthetic cached bytes are fixtures: this script does not validate XLSX extraction or contact object storage. The scheduled `resume_pending` queue inventory, cursor IDs and enable-control record are restricted to the new fixture using a Store wrapper, so concurrent browser QA batches are untouched. Target reads/writes, row locks, `apply_source`, File controllers and calculations all use real Frappe/MariaDB. No production implementation is patched by the test. A successful run finishes with `document_integration_complete`.

## PostgreSQL source adapter contract

`test_settlement_archive_postgres.py` is opt-in. It applies the actual upstream migration files using the upstream worktree's installed `node-pg-migrate`, then tests the costing adapter through real read-only psycopg connections and the `costing_reader` role. Set `SETTLEMENT_UPSTREAM_WORKTREE` when the upstream checkout is not the sibling `dingtalk-settlement-upstream` directory.

Use a disposable PostgreSQL instance listening only on loopback and a database named `settlement_test*`. The fixture truncates its approval, allowlist and attachment tables between tests. Local trust authentication is expected for the disposable `costing_reader` role; no live credentials are needed.

```sh
SETTLEMENT_ADAPTER_TEST_DSN='postgresql://postgres@127.0.0.1:PORT/settlement_test_adapter' \
  python3 -m pytest -q overseas_costing/tests/integration/test_settlement_archive_postgres.py
```

The eight tests cover migration grants and preflight, actual `bucket`/`object_key`/`content_quality` columns, raw-payload hydration and tenant isolation, keyset paging over 200 equal-timestamp rows, attachment changes/retirement and source tombstones, unchanged weekly metadata inventory, changed-source-only hydration, and empty changed-source requests. Default pytest runs skip these tests without the explicit DSN. The lightweight inventory does not transfer or hydrate full source payloads, but PostgreSQL still reads source content to compute its revision hash.
