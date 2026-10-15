# Bounded CRM-only release contract

Use the existing `deploy_unified_purchase.sh` entry point with `--crm-only`.
Its positional arguments remain Branding archive/revision, old image/tag ID,
CRM archive/revision, empty Finance archive/retained revision, empty OA
archive/retained revision, and the established site approvals. CRM metadata is
limited to main: supply the verified retired-site receipt and main maintenance
approval, or the existing isolated `--main-only` lane. No global migrate runs.

The Branding archive carries the unchanged, complete retained Branding package,
the existing reviewed release-tool set and `release-source-manifest.json`.
The CRM archive contains exactly the manifest's changed files under
`crm-overlay/crm_integration/`; deletions, extra sources, links, duplicate paths,
and unsafe paths are rejected. Both archives carry the same manifest if both
include one. Finance and OA archives must be empty arguments. All four image
revision labels are supplied explicitly; only CRM changes its app revision.

The CRM manifest extends the existing fields with:

- `scope: "crm-only"`.
- `revisions`: exactly `deeplinkerp_branding`, `crm_integration`, `china_finance`,
  and `oa_purchase_request`, with full committed app SHAs.
- `baseline_revisions.crm_integration`: the independently verified old CRM SHA.
- `release_tools_commit`: the commit containing the reviewed release tools;
  `release_tools` retains the exact existing complete path-to-SHA256 map.
- `base_image_id` and optional `build_base_image_id`: immutable image IDs.
- `native_versions`: Frappe and ERPNext both exactly `16.23.0`.
- `apps`: exactly `crm_integration`, with changed package-relative paths mapped
  to `{before: <old SHA256 or null for addition>, after: <candidate SHA256>}`.
  Include `patches/add_crm_custom_fields.py`; the metadata adapter reads only
  the frozen definition builders from this source and does not execute hooks.
- `crm_sources_after`: the complete package-relative path-to-SHA256 map exported
  from the reviewed CRM commit. The resulting COPY map must equal it exactly;
  omitting a deletion from the changed-file manifest therefore also blocks.
- `runtime_deltas`: exact app/path `{before, after}` hashes for the independently
  audited generated runtime changes from the immutable base. This is not an
  ignore list. Only the six known generated sidebar/icon paths and removal of
  Branding AppleDouble metadata are eligible; every other byte remains exact.

Release identity is a 40-character digest of scope, base image, all four app
revisions, release-tools commit and all release-tool hashes. Native metadata,
drain, first-resume, cleanup ownership, image tags and evidence use this same
identity. Retained Branding labels and the existing source-sync timer revision
remain Branding revisions. An existing release evidence directory remains a
fail-closed HOLD; it is never overwritten to retry an interrupted release.
Metadata re-apply with the original complete receipt is a verified no-op.

The same native metadata adapter adds only the 19 CRM audit fields on Sales
Order Item, Delivery Note, Delivery Note Item, Stock Entry and Stock Entry
Detail. It preserves all original rows, columns, indexes, Custom Fields,
permissions and unrelated metadata, including the existing unique shipment
identity. New columns must remain NULL or their native numeric zero defaults.
The sole optional new business-type row is `CRM Outbound Temporary Receipt`,
with purpose `Material Receipt` and `is_standard=0`; an existing matching-purpose
row is kept byte-for-byte and a conflicting purpose blocks the release.

Every metadata/DDL intent is durable before its write. Pre-resume recovery
removes only receipted new, unused columns and the exact new type row; it
preserves historical types and rows. The first writer/resume receipt makes any
subsequent failure forward-only HOLD. No business shipment is run by this tool.

The shallower-base option retains the existing layer, full-source,
configuration, dependency and filesystem metadata proofs. In CRM scope only
proven empty Finance/OA COPY instructions may be removed; the Branding and CRM
COPY instructions remain. All physically present packages are audited,
including filesystem-only `client_akivision`.

The complete retained Branding overlay and CRM result are approved against the
immutable base before a candidate can import app code. After build, every
candidate package is hashed against that approved full map before tenant
preflight or metadata execution. Runtime package inventory is independently
discovered so an absent or unexpected filesystem-only app cannot be hidden by
the baseline app list.

Verification commands (Python 3.10 or later):

```sh
python3 -m unittest discover -s tests -p 'test_*release*.py'
python3 -m unittest discover -s tests -p 'test_joint_release_guards.py'
bash -n deploy/production/deploy_unified_purchase.sh
```

Pure tests simulate every one of the 19 CRM DDL autocommit boundaries and test
exact rollback, repeat receipts, nondefault-data refusal and first-resume HOLD.
They do not establish production cutover, native DDL execution or browser
acceptance; those require separate frozen package/image and live evidence.
