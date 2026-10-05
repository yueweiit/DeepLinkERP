"""Exercise only the shell recovery function with mocks; never invoke a release."""

import hashlib
import io
import json
import runpy
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ReleaseRecoveryTests(unittest.TestCase):
	def release_source(self):
		return (Path(__file__).parents[1] / "deploy/production/deploy_unified_purchase.sh").read_text()

	def shell_function(self, name):
		source = self.release_source()
		self.assertIn(name + "() {", source)
		return name + "() {" + source.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"

	def audit_module(self, fake_frappe):
		with patch.dict(sys.modules, {"frappe": fake_frappe}):
			return runpy.run_path(
				str(Path(__file__).parents[1] / "deploy/production/audit_unified_purchase.py")
			)

	def source_validator(self, root):
		module = self.audit_module(types.ModuleType("frappe"))
		module["verify_sources"].__globals__["BENCH"] = root
		return module["verify_sources"]

	def purchase_payment_page_fixture(self):
		path = (
			Path(__file__).parents[1]
			/ "deeplinkerp_branding/deeplinkerp_branding/page/purchase_payment_records/purchase_payment_records.json"
		)
		source = json.loads(path.read_text())
		page = json.loads(json.dumps(source))
		for index, role in enumerate(page["roles"], 1):
			role.update(
				doctype="Has Role",
				name=f"existing-child-{index}",
				idx=index,
				parent=page["name"],
				parenttype="Page",
				parentfield="roles",
			)
		return source, page

	def page_validator(self, page, raw_roles=None):
		def get_doc(doctype, name):
			self.assertEqual((doctype, name), ("Page", "purchase-payment-records"))
			if page is None:
				raise LookupError("Missing Page")
			return page

		def sql(query, values, *, as_dict):
			self.assertEqual(
				query,
				"select role, parent, parenttype, parentfield, idx from `tabHas Role` where parent = %s order by idx, name",
			)
			self.assertEqual(values, ("purchase-payment-records",))
			self.assertTrue(as_dict)
			return page["roles"] if raw_roles is None else raw_roles

		module = self.audit_module(
			types.SimpleNamespace(
				get_doc=get_doc, DoesNotExistError=LookupError, db=types.SimpleNamespace(sql=sql)
			)
		)
		self.assertTrue("verify_purchase_payment_page" in module, "Read-only Page verification is required")
		return module["verify_purchase_payment_page"]

	def test_matching_purchase_payment_page_verification_preserves_permission_child_ids(self):
		source, page = self.purchase_payment_page_fixture()
		before = json.dumps(page, sort_keys=True)
		verify = self.page_validator(page)
		verify(source)
		verify(source)
		self.assertEqual(json.dumps(page, sort_keys=True), before)
		self.assertEqual(
			[role["name"] for role in page["roles"]], [f"existing-child-{i}" for i in range(1, 6)]
		)

	def test_purchase_payment_page_verification_rejects_missing_page(self):
		source, _ = self.purchase_payment_page_fixture()
		verify = self.page_validator(None)
		with self.assertRaisesRegex(AssertionError, "Missing Page: purchase-payment-records"):
			verify(source)

	def test_purchase_payment_page_rejects_raw_values_normalized_by_document_loading(self):
		source, normalized = self.purchase_payment_page_fixture()
		for field, value in (("idx", 0), ("idx", None), ("parenttype", "User"), ("parentfield", "other")):
			with self.subTest(field=field, value=value):
				raw_roles = json.loads(json.dumps(normalized["roles"]))
				raw_roles[0][field] = value
				before = json.dumps(raw_roles, sort_keys=True)
				verify = self.page_validator(normalized, raw_roles)
				with self.assertRaisesRegex(AssertionError, "Page metadata drift: purchase-payment-records"):
					verify(source)
				self.assertEqual(json.dumps(raw_roles, sort_keys=True), before)

	def test_purchase_payment_page_verification_rejects_metadata_and_permission_drift(self):
		source, original = self.purchase_payment_page_fixture()
		for scenario in (
			"doctype",
			"name",
			"module",
			"title",
			"standard",
			"missing-role",
			"extra-role",
			"role",
			"role-order",
			"parent",
			"parenttype",
			"parentfield",
			"idx",
		):
			with self.subTest(scenario=scenario):
				page = json.loads(json.dumps(original))
				if scenario in {"doctype", "name", "module", "title", "standard"}:
					page[scenario] = "different"
				elif scenario == "missing-role":
					page["roles"].pop()
				elif scenario == "extra-role":
					page["roles"].append(dict(page["roles"][-1], name="extra-child", idx=6))
				elif scenario == "role-order":
					page["roles"].reverse()
				else:
					page["roles"][0][scenario] = "different"
				verify = self.page_validator(page)
				with self.assertRaisesRegex(AssertionError, "Page metadata drift: purchase-payment-records"):
					verify(source)

	def test_release_verifies_frozen_page_before_and_after_without_reloading_it(self):
		source = self.release_source()
		self.assertFalse(
			"reload-doc deeplinkerp_branding page purchase_payment_records" in source,
			"Page reload recreates permission children",
		)
		self.assertIn("reload-doc crm_integration doctype sales_production_release_permission", source)
		self.assertLess(
			source.index('capture_release_audit before "$release_dir/before.json"'),
			source.index("switched=1"),
		)
		self.assertLess(
			source.index('capture_release_audit after "$release_dir/after.json"'),
			source.index("maintenance=0", source.index("switched=1")),
		)
		page_path = "deeplinkerp_branding/deeplinkerp_branding/page/purchase_payment_records/purchase_payment_records.json"
		self.assertIn(f'chmod 644 "$build_dir/{page_path}"', source)
		args = source.split("audit_args=", 1)[1].split("\n# The private release umask", 1)[0]
		mock = (
			self.shell_function("capture_release_audit")
			+ f"""
build_dir="$1"
dc=(docker compose)
audit_args={args}
docker() {{ printf '%s\\n' "$*"; }}
capture_release_audit before "$build_dir/before.json"
capture_release_audit after "$build_dir/after.json"
"""
		)
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "release-source-manifest.json").write_text('{"apps": {}}')
			result = subprocess.run(
				["bash", "-c", mock, "page-release-test", tmp], capture_output=True, text=True
			)
			self.assertEqual(result.returncode, 0, result.stderr)
			self.assertEqual(
				result.stdout.count(
					f"cp {tmp}/{page_path} frappe_docker-backend-1:/tmp/purchase-payment-records.json"
				),
				2,
			)
			for phase in ("before", "after"):
				output = (root / (phase + ".json")).read_text()
				self.assertIn("--purchase-payment-page-source /tmp/purchase-payment-records.json", output)
				self.assertIn("--release-manifest /tmp/release-source-manifest.json", output)
				self.assertIn("--phase " + phase, output)

	def test_private_metadata_inputs_are_owned_by_frappe_before_apply_or_rollback(self):
		source = self.release_source()
		for filename, action in (("procurement-before-audit.json", "--apply /tmp/purchase-payables.json"),
		                         ("procurement-metadata-receipt.json", "--rollback /tmp/procurement-metadata-receipt.json")):
			with self.subTest(filename=filename):
				owner = "docker exec --user root frappe_docker-backend-1 chown frappe:frappe /tmp/" + filename
				self.assertIn(owner, source)
				self.assertLess(source.index(owner), source.index(action))
				self.assertNotIn("chmod 644 /tmp/" + filename, source)

	def test_release_source_manifest_accepts_expected_new_file_and_version(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			target = root / "apps/crm_integration/crm_integration/new.py"
			verify = self.source_validator(root)
			manifest = {
				"apps": {
					"crm_integration": {
						"new.py": {"before": None, "after": hashlib.sha256(b"new").hexdigest()}
					}
				}
			}
			verify(manifest, "before")
			target.parent.mkdir(parents=True)
			target.write_bytes(b"new")
			verify(manifest, "after")

	def test_release_source_manifest_accepts_frozen_finance_overlay(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			target = root / "apps/china_finance/china_finance/services/voucher.py"
			target.parent.mkdir(parents=True)
			target.write_bytes(b"old finance")
			manifest = {
				"apps": {
					"china_finance": {
						"services/voucher.py": {
							"before": hashlib.sha256(b"old finance").hexdigest(),
							"after": hashlib.sha256(b"verified finance").hexdigest(),
						}
					}
				}
			}
			verify = self.source_validator(root)
			verify(manifest, "before")
			target.write_bytes(b"verified finance")
			verify(manifest, "after")

	def test_release_source_manifest_rejects_an_unexpected_running_edit(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			target = root / "apps/crm_integration/crm_integration/order.py"
			target.parent.mkdir(parents=True)
			target.write_bytes(b"other task")
			manifest = {
				"apps": {
					"crm_integration": {
						"order.py": {"before": hashlib.sha256(b"baseline").hexdigest(), "after": "candidate"}
					}
				}
			}
			with self.assertRaisesRegex(AssertionError, "Source drift: crm_integration/order.py"):
				self.source_validator(root)(manifest, "before")

	def test_release_source_manifest_rejects_incomplete_candidate_copy(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			target = root / "apps/deeplinkerp_branding/deeplinkerp_branding/grid.js"
			target.parent.mkdir(parents=True)
			target.write_bytes(b"old")
			manifest = {
				"apps": {
					"deeplinkerp_branding": {
						"grid.js": {
							"before": hashlib.sha256(b"old").hexdigest(),
							"after": hashlib.sha256(b"new").hexdigest(),
						}
					}
				}
			}
			with self.assertRaisesRegex(AssertionError, "Source drift: deeplinkerp_branding/grid.js"):
				self.source_validator(root)(manifest, "after")

	def test_release_source_manifest_rejects_unsafe_app_and_paths(self):
		with tempfile.TemporaryDirectory() as tmp:
			verify = self.source_validator(Path(tmp))
			for app, path in [
				("other_app", "new.py"),
				("crm_integration", "../new.py"),
				("crm_integration", "/new.py"),
				("crm_integration", "a/../../new.py"),
			]:
				with self.subTest(app=app, path=path), self.assertRaises(AssertionError):
					verify({"apps": {app: {path: {"before": None, "after": "candidate"}}}}, "before")
			outside = Path(tmp) / "outside.py"
			outside.write_bytes(b"outside")
			app_root = Path(tmp) / "apps/crm_integration/crm_integration"
			app_root.mkdir(parents=True)
			(app_root / "escaped.py").symlink_to(outside)
			with self.assertRaises(AssertionError):
				verify(
					{
						"apps": {
							"crm_integration": {
								"escaped.py": {"before": hashlib.sha256(b"outside").hexdigest()}
							}
						}
					},
					"before",
				)

	def test_target_revision_requires_finance_pair_and_all_six_labels(self):
		functions = (
			self.shell_function("revision_label")
			+ self.shell_function("verify_running_release")
			+ self.shell_function("release_is_current")
		)
		for finance, mixed_label, running, image, expected in [
			("finance-target", "", "true", "image-target", 0),
			("finance-old", "", "true", "image-target", 1),
			("finance-target", "crm", "true", "image-target", 1),
			("finance-target", "branding", "true", "image-target", 1),
			("finance-target", "finance", "true", "image-target", 1),
			("finance-target", "", "false", "image-target", 1),
			("finance-target", "", "true", "image-other", 1),
		]:
			with self.subTest(finance=finance, mixed_label=mixed_label, running=running, image=image):
				mock = f"""
branding_sha=branding-target
crm_sha=crm-current
finance_sha=finance-target
services=(backend frontend queue-long queue-short scheduler websocket)
docker() {{
  case "$*" in
    *'.Image'* ) if [[ "$*" == *frontend* ]]; then printf '{image}'; else printf 'image-target'; fi ;;
    *'.State.Running'* ) if [[ "$*" == *frontend* ]]; then printf '{running}'; else printf 'true'; fi ;;
    *branding.revision* ) if [[ "$*" == *frontend* && '{mixed_label}' == branding ]]; then printf 'other'; else printf 'branding-target'; fi ;;
    *crm.revision* ) if [[ "$*" == *frontend* && '{mixed_label}' == crm ]]; then printf 'other'; else printf 'crm-current'; fi ;;
    *finance.revision* ) if [[ "$*" == *frontend* && '{mixed_label}' == finance ]]; then printf 'other'; else printf '{finance}'; fi ;;
  esac
}}
{functions}
release_is_current
"""
				result = subprocess.run(["bash", "-c", mock], capture_output=True, text=True)
				self.assertEqual(result.returncode, expected, result.stderr)

	def test_failed_label_inspection_is_not_an_empty_legacy_revision(self):
		functions = self.shell_function("revision_label") + self.shell_function("verify_running_release")
		mock = (
			functions
			+ """
services=(backend frontend queue-long queue-short scheduler websocket)
docker() { case "$*" in *'.Image'*) printf 'image';; *'.State.Running'*) printf 'true';; *branding.revision*) printf 'branding';; *crm.revision*) printf 'crm';; *finance.revision*) return 1;; esac; }
verify_running_release image branding crm ''
"""
		)
		result = subprocess.run(["bash", "-c", mock], capture_output=True, text=True)
		self.assertEqual(result.returncode, 1)

	def test_empty_overlays_preserve_current_labels_including_legacy_finance(self):
		source = self.release_source()
		block = source.split("current_revision=$(", 1)[1].split("\nif release_is_current", 1)[0]
		for finance in ("finance-current", "<no value>"):
			with self.subTest(finance=finance):
				mock = (
					self.shell_function("revision_label")
					+ f"""
docker() {{ case "$*" in *branding.revision*) printf 'branding-current';; *crm.revision*) printf 'crm-current';; *finance.revision*) printf '{finance}';; esac; }}
crm_archive=''
finance_archive=''
crm_sha=preserved
finance_sha=preserved
current_revision=$({block}
printf '%s|%s' "$crm_sha" "$finance_sha"
"""
				)
				result = subprocess.run(["bash", "-c", mock], capture_output=True, text=True)
				self.assertEqual(result.returncode, 0, result.stderr)
				self.assertEqual(result.stdout, "crm-current|" + ("" if finance == "<no value>" else finance))

	def compare_audits(self, before, after, manifest):
		source = self.release_source()
		code = source.split('python3 - "$release_dir" "$build_dir" <<\'PY\'\n', 1)[1].split("\nPY", 1)[0]
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			metadata = {
				"scope": {"Page": [{"name": "purchase-payables"}], "Has Role": []},
				"outside": {"Has Role": before["tables"]["Has Role"]},
			}
			before = dict(before, procurement_metadata=metadata)
			after = dict(after, procurement_metadata=metadata)
			receipt = {
				"semantic_validated": True,
				"second_reconcile_unchanged": True,
				"new_page": False,
				"before": metadata,
				"after": metadata,
			}
			(root / "metadata.json").write_text(json.dumps(receipt))
			deployment = root / "deploy/production"
			deployment.mkdir(parents=True)
			(deployment / "procurement_release_metadata.py").write_text(
				(Path(__file__).parents[1] / "deploy/production/procurement_release_metadata.py").read_text()
			)
			(root / "before.json").write_text(json.dumps(before))
			(root / "after.json").write_text(json.dumps(after))
			(root / "release-source-manifest.json").write_text(json.dumps(manifest))
			return subprocess.run([sys.executable, "-c", code, tmp, tmp], capture_output=True, text=True)

	def test_finance_manifest_preserves_crm_and_rejects_unlisted_or_wrong_sources(self):
		manifest = {
			"apps": {
				"deeplinkerp_branding": {"page.js": {"before": "old", "after": "new"}},
				"china_finance": {"services/voucher.py": {"before": "old", "after": "new"}},
			}
		}
		before = {
			"tables": {"Has Role": {"count": 5, "sha256": "original-child-identities"}},
			"preserved_apps": {"crm_integration": "crm", "china_finance": "old"},
			"release_sources": {
				"deeplinkerp_branding": {"page.js": "old"},
				"china_finance": {"services/voucher.py": "old", "private.py": "keep"},
			},
		}
		after = json.loads(json.dumps(before))
		after["preserved_apps"]["china_finance"] = "new"
		for app in manifest["apps"]:
			after["release_sources"][app][next(iter(manifest["apps"][app]))] = "new"
		self.assertEqual(self.compare_audits(before, after, manifest).returncode, 0)
		for change in ("unlisted", "listed", "crm", "page-role-identities"):
			with self.subTest(change=change):
				bad = json.loads(json.dumps(after))
				if change == "page-role-identities":
					bad["tables"]["Has Role"]["sha256"] = "recreated-child-identities"
				elif change == "crm":
					bad["preserved_apps"]["crm_integration"] = "drift"
				else:
					bad["release_sources"]["china_finance"][
						"private.py" if change == "unlisted" else "services/voucher.py"
					] = "drift"
				self.assertNotEqual(self.compare_audits(before, bad, manifest).returncode, 0)

	def test_audit_covers_finance_children_company_settings_and_configuration(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "sites/assets").mkdir(parents=True)
			(root / "sites/deeplinkerp.com").mkdir()
			(root / "sites/assets/assets.json").write_text('{"bundle": "same"}')
			(root / "sites/common_site_config.json").write_text('{"maintenance_mode": 1, "secret": "hidden"}')
			config = root / "sites/deeplinkerp.com/site_config.json"
			config.write_text('{"maintenance_mode": 1, "mes_callback_url": "updated"}')
			queried = []
			_, page = self.purchase_payment_page_fixture()
			roles = page["roles"]
			settings = {"CRM Integration Settings", "MES Integration Settings", "China Finance Settings"}

			def meta(name):
				return types.SimpleNamespace(
					issingle=name in settings,
					fields=[types.SimpleNamespace(fieldtype="Table", options=name + " Child")],
				)

			def sql(query, **kwargs):
				queried.append(query)
				if "tabHas Role`" in query:
					self.assertEqual(query, "select * from `tabHas Role` order by name")
					return roles
				return (
					[{"doctype": "MES Integration Settings", "field": "callback_url", "value": "updated"}]
					if "tabSingles" in query
					else []
				)

			fake = types.SimpleNamespace(
				local=types.SimpleNamespace(site="deeplinkerp.com"),
				db=types.SimpleNamespace(exists=lambda *args: True, sql=sql),
				get_meta=meta,
			)
			module = self.audit_module(fake)
			capture = module["capture_audit"]
			capture.__globals__["BENCH"] = root
			capture.__globals__["source_digest"] = lambda app: "source"
			before = capture()
			self.assertEqual(
				before["tables"]["Has Role"],
				{
					"count": 5,
					"sha256": hashlib.sha256(
						json.dumps(roles, sort_keys=True, default=str, ensure_ascii=False).encode()
					).hexdigest(),
				},
			)
			for role in roles:
				role["name"] = "recreated-" + role["name"]
			recreated = capture()["tables"]["Has Role"]
			self.assertEqual(recreated["count"], before["tables"]["Has Role"]["count"])
			self.assertNotEqual(recreated["sha256"], before["tables"]["Has Role"]["sha256"])
			for parent in ("China Cash Flow Assignment", "China Voucher Sync Issue", "Company", *settings):
				self.assertIn(parent + " Child", before["tables"])
			self.assertTrue(any("tabSingles" in query for query in queried))
			self.assertFalse(any("tabCRM Integration Settings`" in query for query in queried))
			self.assertNotIn("hidden", json.dumps(before))
			self.assertNotIn("updated", json.dumps(before))
			config.write_text('{"mes_callback_url": "updated", "maintenance_mode": 0}')
			after = capture()
			self.assertEqual(before["configuration_sha256"], after["configuration_sha256"])
			config.write_text('{"mes_callback_url": "overwritten", "maintenance_mode": 1}')
			self.assertNotEqual(before["configuration_sha256"], capture()["configuration_sha256"])

	def test_overlay_archives_require_matching_manifest_and_precise_finance_files(self):
		function = self.shell_function("prepare_sources")
		finance_files = [
			"services/cash_flow_assignment.py",
			"services/voucher.py",
			"tests/test_cancellation_sync.py",
			"tests/test_cancellation_sync_concurrency.py",
			"translations/zh.csv",
		]
		manifest = {
			"apps": {
				"deeplinkerp_branding": {
					"page.js": {"before": None, "after": hashlib.sha256(b"new").hexdigest()}
				},
				"china_finance": {
					path: {"before": None, "after": hashlib.sha256(b"new").hexdigest()}
					for path in finance_files
				},
			}
		}
		for scenario in (
			"valid",
			"valid-directory",
			"missing",
			"conflicting",
			"unknown",
			"unknown-directory",
			"escape",
			"symlink",
			"missing-file",
			"wrong-hash",
			"duplicate-directory",
			"duplicate-file",
		):
			with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
				root = Path(tmp)
				build = root / "build"
				build.mkdir()
				archives = []
				for name in ("branding", "finance"):
					archive = root / (name + ".tar.gz")
					archives.append(str(archive))
					files = (
						{"deeplinkerp_branding/page.js": b"new"}
						if name == "branding"
						else {"finance-overlay/china_finance/" + path: b"new" for path in finance_files}
					)
					if scenario != "missing":
						files["release-source-manifest.json"] = json.dumps(manifest).encode()
					if name == "finance":
						if scenario == "conflicting":
							files["release-source-manifest.json"] = json.dumps({"apps": {}}).encode()
						if scenario == "unknown":
							files["finance-overlay/china_finance/hooks.py"] = b"unexpected"
						if scenario == "escape":
							files["finance-overlay/../../escape.py"] = b"unexpected"
						if scenario == "missing-file":
							files.pop("finance-overlay/china_finance/services/voucher.py")
						if scenario == "wrong-hash":
							files["finance-overlay/china_finance/services/voucher.py"] = b"drift"
					with tarfile.open(archive, "w:gz") as tar:
						for path, data in files.items():
							entry = tarfile.TarInfo(path)
							entry.size = len(data)
							tar.addfile(entry, io.BytesIO(data))
						if scenario == "symlink" and name == "finance":
							entry = tarfile.TarInfo("finance-overlay/china_finance/link")
							entry.type = tarfile.SYMTYPE
							entry.linkname = "/tmp"
							tar.addfile(entry)
						if scenario == "unknown-directory" and name == "finance":
							entry = tarfile.TarInfo("finance-overlay/unknown_app/")
							entry.type = tarfile.DIRTYPE
							tar.addfile(entry)
						if scenario in {"duplicate-directory", "valid-directory"} and name == "finance":
							directories = (
								(
									"finance-overlay/china_finance/services",
									"finance-overlay/china_finance/services/",
								)
								if scenario == "duplicate-directory"
								else ("finance-overlay/china_finance/services/",)
							)
							for directory in directories:
								entry = tarfile.TarInfo(directory)
								entry.type = tarfile.DIRTYPE
								entry.mode = 0o755
								tar.addfile(entry)
						if scenario == "duplicate-file" and name == "finance":
							entry = tarfile.TarInfo("finance-overlay/china_finance/services/voucher.py")
							entry.size = 3
							tar.addfile(entry, io.BytesIO(b"new"))
				mock = (
					function
					+ '\nbuild_dir="$1"\narchive="$2"\ncrm_archive=""\nfinance_archive="$3"\nprepare_sources\n'
				)
				result = subprocess.run(
					["bash", "-c", mock, "release-test", str(build), *archives],
					capture_output=True,
					text=True,
				)
				self.assertEqual(
					result.returncode == 0, scenario in {"valid", "valid-directory"}, result.stderr
				)

	def test_copied_audit_is_readable_despite_private_release_umask(self):
		source = (Path(__file__).parents[1] / "deploy/production/deploy_unified_purchase.sh").read_text()
		permission_fix = 'chmod 644 "$build_dir/deploy/production/audit_unified_purchase.py"'
		self.assertIn(permission_fix, source)
		self.assertLess(
			source.index(permission_fix),
			source.index('docker cp "$build_dir/deploy/production/audit_unified_purchase.py"'),
		)

	def run_recovery(
		self,
		up_status=0,
		health_status=0,
		initial_maintenance_status=0,
		audit_change=None,
		audit_status=0,
		copy_status=0,
		baseline_present=True,
		baseline_captured=True,
	):
		source = (Path(__file__).parents[1] / "deploy/production/deploy_unified_purchase.sh").read_text()
		function = source.split("recover() {", 1)[1].split("\ntrap recover EXIT", 1)[0]
		capture = self.shell_function("capture_release_audit")
		baseline = {
			"site": "deeplinkerp.com",
			"maintenance_mode": 1,
			"tables": {
				"GL Entry": {"count": 2, "sha256": "business"},
				"User Permission": {"count": 1, "sha256": "permissions"},
				"Has Role": {"count": 5, "sha256": "original-child-identities"},
			},
			"singles": {"count": 3, "sha256": "settings"},
			"preserved_apps": {"crm_integration": "crm", "china_finance": "finance"},
			"release_sources": {
				"deeplinkerp_branding": {"page.js": "old", "unlisted.py": "keep"},
				"china_finance": {"services/voucher.py": "old", "unlisted.py": "keep"},
			},
			"configuration_sha256": {
				"common_site_config.json": "common",
				"deeplinkerp.com/site_config.json": "site",
			},
			"assets_manifest_sha256": "assets",
		}
		rollback = json.loads(json.dumps(baseline))
		if audit_change == "business":
			rollback["tables"]["GL Entry"]["sha256"] = "changed"
		elif audit_change == "permissions":
			rollback["tables"]["User Permission"]["sha256"] = "changed"
		elif audit_change == "page-role-identities":
			rollback["tables"]["Has Role"]["sha256"] = "recreated-child-identities"
		elif audit_change == "settings":
			rollback["singles"]["sha256"] = "changed"
		elif audit_change == "source":
			rollback["release_sources"]["china_finance"]["unlisted.py"] = "changed"
		elif audit_change == "branding-source":
			rollback["release_sources"]["deeplinkerp_branding"]["unlisted.py"] = "changed"
		elif audit_change == "crm-source":
			rollback["preserved_apps"]["crm_integration"] = "changed"
		elif audit_change == "config":
			rollback["configuration_sha256"]["deeplinkerp.com/site_config.json"] = "changed"
		elif audit_change == "common-config":
			rollback["configuration_sha256"]["common_site_config.json"] = "changed"
		elif audit_change == "assets":
			rollback["assets_manifest_sha256"] = "changed"
		mock = f"""
dc=(docker compose)
services=(backend frontend queue-long queue-short scheduler websocket)
switched=1
maintenance=1
baseline_captured={int(baseline_captured)}
release_dir="$1"
build_dir="$1"
audit_args=(--release-manifest /tmp/release-source-manifest.json)
frozen_base=mock-base
old_image_id=sha256:expected
maintenance_calls=0
cp() {{ printf 'COPY %s\\n' "$*"; }}
sleep() {{ :; }}
docker() {{
  case "$*" in
    'image inspect '*) printf '%s\\n' "$old_image_id" ;;
    inspect*'.Image'* ) printf '%s\\n' "$old_image_id" ;;
    inspect*'.State.Running'* ) printf 'true\\n' ;;
    'compose up '*) printf 'UP\\n'; return {up_status} ;;
    cp*) printf 'DOCKER %s\\n' "$*"; return {copy_status} ;;
    *'/env/bin/python /tmp/audit-unified-purchase.py'*)
      printf 'AUDIT %s\\n' "$*" >&2
      if (( {audit_status} )); then return {audit_status}; fi
      command cat "$release_dir/rollback-fixture.json" ;;
    *'set-maintenance-mode on'*)
      maintenance_calls=$((maintenance_calls+1))
      printf 'MAINTENANCE ON\\n'
      if (( maintenance_calls == 1 )); then return {initial_maintenance_status}; fi ;;
    *) printf 'DOCKER %s\\n' "$*" ;;
  esac
}}
curl() {{ printf 'HEALTH\\n'; return {health_status}; }}
{capture}
recover() {{{function}
false
recover
"""
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			if baseline_present:
				(root / "before.json").write_text(json.dumps(baseline))
			(root / "rollback-fixture.json").write_text(json.dumps(rollback))
			(root / "release-source-manifest.json").write_text('{"apps": {}}')
			return subprocess.run(["bash", "-c", mock, "recovery-test", tmp], capture_output=True, text=True)

	def test_recovered_image_requires_fresh_full_audit_before_maintenance_off(self):
		result = self.run_recovery()
		self.assertEqual(result.returncode, 1)
		self.assertIn("--phase before", result.stderr)
		self.assertIn("/tmp/audit-unified-purchase.py", result.stdout)
		self.assertIn("/tmp/release-source-manifest.json", result.stdout)
		self.assertIn("Restored full audit matches original baseline", result.stdout)
		self.assertLess(
			result.stdout.index("Restored full audit"), result.stdout.index("set-maintenance-mode off")
		)
		self.assertNotIn("Manual recovery required", result.stderr)

	def test_recovery_rejects_changed_full_audit_and_unavailable_baseline(self):
		for scenario in (
			"business",
			"permissions",
			"page-role-identities",
			"settings",
			"source",
			"branding-source",
			"crm-source",
			"config",
			"common-config",
			"assets",
			"missing-baseline",
			"uncaptured-baseline",
			"read-failure",
			"copy-failure",
		):
			with self.subTest(scenario=scenario):
				result = self.run_recovery(
					audit_change=scenario,
					baseline_present=scenario != "missing-baseline",
					audit_status=1 if scenario == "read-failure" else 0,
					copy_status=1 if scenario == "copy-failure" else 0,
					baseline_captured=scenario != "uncaptured-baseline",
				)
				self.assertEqual(result.returncode, 1)
				self.assertIn("MAINTENANCE ON", result.stdout)
				self.assertNotIn("set-maintenance-mode off", result.stdout)
				self.assertNotIn("HEALTH", result.stdout)
				self.assertIn("stop frappe_docker-frontend-1", result.stdout)
				self.assertIn("Manual recovery required", result.stderr)

	def test_failed_rollback_never_disables_maintenance(self):
		result = self.run_recovery(up_status=1)
		self.assertEqual(result.returncode, 1)
		self.assertIn("MAINTENANCE ON", result.stdout)
		self.assertNotIn("set-maintenance-mode off", result.stdout)
		self.assertIn("Manual recovery required", result.stderr)

	def test_verified_rollback_checks_health_before_accepting_recovery(self):
		result = self.run_recovery()
		self.assertEqual(result.returncode, 1)  # Original release still failed.
		self.assertIn("set-maintenance-mode off", result.stdout)
		self.assertIn("HEALTH", result.stdout)
		self.assertNotIn("Manual recovery required", result.stderr)

	def test_unhealthy_rollback_reenables_maintenance(self):
		result = self.run_recovery(health_status=1)
		self.assertEqual(result.returncode, 1)
		self.assertEqual(result.stdout.count("MAINTENANCE ON"), 3)
		self.assertIn("Manual recovery required", result.stderr)

	def test_dead_new_backend_does_not_block_host_side_rollback(self):
		result = self.run_recovery(initial_maintenance_status=1)
		self.assertEqual(result.returncode, 1)
		self.assertIn("stop frappe_docker-frontend-1", result.stdout)
		self.assertEqual(result.stdout.count("UP"), 2)
		self.assertIn("set-maintenance-mode off", result.stdout)
		self.assertNotIn("Manual recovery required", result.stderr)


if __name__ == "__main__":
	unittest.main()
