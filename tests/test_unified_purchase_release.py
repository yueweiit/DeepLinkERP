"""Test isolated recovery and native CLI parsing; never invoke a release."""

import contextlib
import hashlib
import io
import json
import runpy
import shlex
import shutil
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

	def test_shared_cutover_preserves_immutable_assets_manifest(self):
		source = self.release_source()
		self.assertFalse('/usr/bin/touch /home/frappe/frappe-bench/sites/assets/assets.json' in source)

	def test_retirement_proofs_are_not_tenant_database_audits(self):
		source = self.release_source()
		self.assertFalse("glob('*.before.json')" in source)
		self.assertFalse('glob("*.before.json")' in source)
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / 'tenants.json').write_text(json.dumps({'sites': {'deeplinkerp.com': {}, 'other.test': {}}}))
			(root / 'retirement-routing.before.json').write_text('{}')
			for name in ('before.json', 'other.test.before.json'):
				(root / name).write_text('{}')
			code = self.shell_function('tenant_audit_paths') + '\ntenant_audit_paths "$1"\n'
			result = subprocess.run(['bash', '-c', code, 'test', tmp], capture_output=True, text=True)
			self.assertEqual(result.returncode, 0, result.stderr)
			self.assertEqual(json.loads(result.stdout), [str(root / 'before.json'), str(root / 'other.test.before.json')])

	def test_release_backup_never_invokes_retention_cleanup(self):
		source = self.release_source()
		self.assertFalse('bench --site deeplinkerp.com backup --with-files --compress' in source)
		backup = self.shell_function('capture_native_backup')
		self.assertIn('BackupGenerator', backup)
		self.assertIn('get_backup(force=True', backup)
		self.assertNotIn('new_backup(', backup)
		self.assertNotIn('delete_temp_backups', backup)
		code = backup.split(" -c '\n", 1)[1].split("\n' \"release-$release_key\"", 1)[0]
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / 'private/backups').mkdir(parents=True)
			retained = root / 'private/backups/retained-directory'
			retained.mkdir()
			(retained / 'old-backup').write_bytes(b'keep')
			calls = []
			class NativeBackup:
				def __init__(self, *args, **kwargs):
					calls.append(('init', kwargs))
					self.root = Path(kwargs['backup_path'])
				def get_backup(self, **kwargs):
					calls.append(('backup', kwargs))
					for name in ('backup_path_db', 'backup_path_files', 'backup_path_private_files', 'backup_path_conf'):
						path = self.root / name
						path.write_bytes(b'nonempty')
						setattr(self, name, str(path))
			frappe = types.SimpleNamespace(
				init=lambda **kwargs: calls.append(('site', kwargs)), connect=lambda: None,
				destroy=lambda: calls.append(('destroy', {})), get_site_path=lambda *parts: str(root.joinpath(*parts)),
				conf=types.SimpleNamespace(db_name='db', db_user='user', db_password='test-only', db_socket=None, db_host='db', db_port=3306, db_type='mariadb'),
			)
			with patch.dict(sys.modules, {'frappe': frappe, 'frappe.utils': types.ModuleType('frappe.utils'), 'frappe.utils.backups': types.SimpleNamespace(BackupGenerator=NativeBackup)}), patch.object(sys, 'argv', ['-c', 'release-test']), contextlib.redirect_stdout(io.StringIO()) as output:
				exec(code, {})
			self.assertTrue(calls[1][1]['ignore_conf'])
			self.assertTrue(calls[1][1]['compress_files'])
			self.assertEqual(calls[2], ('backup', {'force': True, 'ignore_files': False}))
			self.assertEqual(calls[-1][0], 'destroy')
			self.assertTrue(json.loads(output.getvalue())['full_backup'])
			self.assertEqual((retained / 'old-backup').read_bytes(), b'keep')

	def test_explicit_main_only_entrypoint_reuses_build_and_never_enters_shared_cutover(self):
		source = self.release_source()
		self.assertIn("--main-only", source, "Explicit authorized main-only lane is missing")
		self.assertIn("run_main_only_release() {", source)
		main = self.shell_function("run_main_only_release")
		self.assertIn('--joint-apply --receipt "$native_receipt"', main)
		self.assertIn('capture_release_audit before "$release_dir/before.json"', main)
		self.assertIn('capture_release_audit after "$release_dir/after.json"', main)
		self.assertNotIn("--native-only", main)
		self.assertNotIn("--with-files", main)
		self.assertNotIn('"${dc[@]}"', main)
		self.assertNotIn("assets.json", main)
		self.assertLess(main.index("--record-resume"), main.index("main_lane resume"))
		self.assertIn("if (( main_only )); then run_main_only_release; exit; fi", source)

	def worker_staging_commands(self):
		return [
			shlex.split(line.strip())[1:]
			for line in self.release_source().splitlines()
			if line.strip().startswith('"${dc[@]}"')
			and "queue-long queue-short scheduler" in line
			and shlex.split(line.strip())[1] in {"create", "up"}
		]

	def test_shared_single_site_approval_requires_retirement_pin_and_cannot_mix_isolated_lane(self):
		prefix = self.release_source().split("# The final joint candidate", 1)[0]
		for mode in ("legacy", "bare-main", "retired", "mixed-isolated", "missing-pin"):
			with self.subTest(mode=mode):
				flags = [] if mode in {"legacy", "bare-main"} else ["--retirement-receipt", "/home/frappe/frappe-bench/sites/.deeplinkerp-retired-sites/2026-10-10/retirement-receipt.json", "d" * 64 if mode != "missing-pin" else ""]
				if mode == "mixed-isolated":
					flags.insert(0, "--main-only")
				approval = ("deeplinkerp.com,akivision.deeplinkerp.com,latingo.deeplinkerp.com,yuewei.deeplinkerp.com", "akivision.deeplinkerp.com,latingo.deeplinkerp.com,yuewei.deeplinkerp.com") if mode == "legacy" else ("deeplinkerp.com", "")
				args = ["archive", "a" * 40, "old-image", "old-id", "", "", "finance", "b" * 40, "oa", "c" * 40, *approval]
				result = subprocess.run(["bash", "-c", prefix, "release-test", *flags, *args], capture_output=True, text=True)
				self.assertEqual(result.returncode == 0, mode in {"legacy", "retired"}, result.stderr)

	def test_command_runner_passes_pinned_retirement_to_existing_shared_container(self):
		script = self.shell_function("command_runner") + """
set -eo pipefail
main_prepared=0
private_runtime_gid=1000
release_network=shared-net
build_dir=/frozen-source
release_dir=/verified-evidence
sites_spec=existing-sites
branding_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
resume_receipt=/existing-resume
retirement_receipt=/home/frappe/frappe-bench/sites/.deeplinkerp-retired-sites/2026-10-10/retirement-receipt.json
retirement_sha256=dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
main_lane() { return 0; }
docker() { printf '%s\\n' "$@"; }
command_runner old-image python guard --runtime-proof
"""
		result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("DEEPLINKERP_RETIREMENT_RECEIPT=/home/frappe/frappe-bench/sites/.deeplinkerp-retired-sites/2026-10-10/retirement-receipt.json", result.stdout)
		self.assertIn("DEEPLINKERP_RETIREMENT_SHA256=" + "d" * 64, result.stdout)
		self.assertNotIn("deeplinkerp_main", result.stdout)

	def test_worker_staging_never_starts_jobs_and_checks_cli_before_maintenance(self):
		commands = self.worker_staging_commands()
		self.assertEqual(len(commands), 2, "Both forward cutover and recovery must stage stopped workers")
		for command in commands:
			self.assertEqual(command[0], "up", "Compose create does not support --no-deps")
			for flag in ("--no-start", "--force-recreate", "--no-deps"):
				self.assertIn(flag, command)
		source = self.release_source()
		preflight = '"${dc[@]}" up --no-start --force-recreate --no-deps --help > /dev/null'
		self.assertIn(preflight, source)
		self.assertLess(source.index(preflight), source.index("--maintenance-on --tenant-receipt"))

	def test_secondary_native_scope_requires_separate_approval_and_all_audits_before_shared_resume(self):
		source = self.release_source()
		self.assertIn("approved_native_schema_sites=${12:-}", source)
		self.assertLess(
			source.index("approved_native_schema_sites=${12:-}"), source.index("systemctl --user stop")
		)
		self.assertIn('--site "$site" --native-only', source)
		self.assertIn('metadata_started_sites+=("$site")', source)
		legacy = source.split("# All six containers are staged stopped.", 1)[1]
		self.assertLess(legacy.index('for site in "${sites[@]}"; do'), legacy.index("verify_audit_ownership"))
		self.assertLess(source.index("for site in sites:"), source.index("--producer candidate-serving"))
		self.assertIn("for ((i=${#metadata_started_sites[@]}-1; i>=0; i--)); do", source)

	@unittest.skipUnless(shutil.which("docker"), "Docker CLI is unavailable; semantic guard still runs")
	def test_worker_staging_flags_are_accepted_by_actual_compose_parser(self):
		for command in self.worker_staging_commands():
			with self.subTest(command=command):
				# --help validates native flags but does not load a site or contact Docker's daemon.
				args = command[: command.index("queue-long")]
				result = subprocess.run(
					["docker", "compose", *args, "--help"], capture_output=True, text=True
				)
				self.assertEqual(result.returncode, 0, result.stderr)

	def shell_function(self, name):
		source = self.release_source()
		self.assertIn(name + "() {", source)
		return name + "() {" + source.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"

	def test_existing_source_timer_retargets_only_after_release_unlock_with_new_pins(self):
		source = self.release_source()
		self.assertIn("retarget_existing_source_sync() {", source)
		tail = source.split("# Cutover is verified;", 1)[1]
		self.assertLess(
			tail.index('retarget_existing_source_sync "$new_image_id"'),
			tail.index("trap - EXIT"),
			"Source handoff failure must retain the forward-only recovery trap",
		)
		self.assertLess(tail.index("flock -u 9"), tail.index('retarget_existing_source_sync "$new_image_id"'))
		function = self.shell_function("retarget_existing_source_sync")
		for active in (0, 1):
			with self.subTest(active=active):
				script = (
					function
					+ """
set -euo pipefail
source_sync_timer_active=ACTIVE
build_dir=/verified-build
branding_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
sha256sum() { printf '%s  %s\\n' bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb "$1"; }
python3() { printf 'INSTALL %s\\n' "$*"; }
systemctl() { printf 'TIMER %s\\n' "$*"; }
retarget_existing_source_sync sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
""".replace("ACTIVE", str(active))
				)
				result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
				self.assertEqual(result.returncode, 0, result.stderr)
				if active:
					self.assertIn("dedicated_source_sync.py retarget --revision " + "a" * 40, result.stdout)
					self.assertIn("--image-id sha256:" + "c" * 64, result.stdout)
					self.assertIn("--runner-sha256 " + "b" * 64 + " --start-timer", result.stdout)
					self.assertIn(
						"TIMER --user is-active --quiet deeplinkerp-source-sync.timer", result.stdout
					)
				else:
					self.assertEqual(result.stdout, "")

	def audit_module(self, fake_frappe):
		metadata = types.ModuleType("procurement_release_metadata")
		metadata.__dict__.update(
			runpy.run_path(
				str(Path(__file__).parents[1] / "deploy/production/procurement_release_metadata.py")
			)
		)
		guard = types.ModuleType("joint_release_guards")
		guard.__dict__.update(
			runpy.run_path(str(Path(__file__).parents[1] / "deploy/production/joint_release_guards.py"))
		)
		binding = patch.dict(
			sys.modules, {"procurement_release_metadata": metadata, "joint_release_guards": guard}
		)
		binding.start()
		self.addCleanup(binding.stop)
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
		self.assertNotIn("reload-doc crm_integration doctype sales_production_release_permission", source)
		self.assertIn("CRM must remain the independently verified base package", source)
		self.assertLess(
			source.index('capture_release_audit before "$release_dir/before.json"'),
			source.index("# All six containers are staged stopped."),
		)
		self.assertLess(
			source.index('capture_release_audit after "$release_dir/after.json"'),
			source.index("--producer candidate-serving"),
		)
		page_path = "deeplinkerp_branding/deeplinkerp_branding/page/purchase_payment_records/purchase_payment_records.json"
		self.assertIn('chmod -R a+rX "$build_dir"', source)
		args = source.rsplit("audit_args=", 1)[1].split("\n", 1)[0]
		mock = (
			self.shell_function("capture_release_audit")
			+ f"""
build_dir="$1"
native_receipt=/private/joint-receipt.json
old_image_id=old-image
dc=(docker compose)
audit_args={args}
chmod() {{ return 0; }}
command_runner() {{ printf '%s\\n' "$*"; }}
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
			self.assertEqual(result.stdout, "", "No live-backend file copy during command-only audit")
			for phase in ("before", "after"):
				output = (root / (phase + ".json")).read_text()
				self.assertIn("--purchase-payment-page-source /release/" + page_path, output)
				self.assertIn("--release-manifest /release/release-source-manifest.json", output)
				self.assertIn("--phase " + phase, output)

	def test_private_metadata_inputs_keep_host_ownership_with_scoped_runtime_group(self):
		source = self.release_source()
		self.assertFalse(
			'test "$(docker exec frappe_docker-backend-1 id -u)" = "$(id -u)"' in source,
			"Host/runtime UID equality is not a private access contract",
		)
		self.assertIn("main_lane runtime-access", source)
		runner = self.shell_function("command_runner")
		self.assertIn('--group-add "$private_runtime_gid"', runner)
		self.assertLess(runner.index("main_lane runtime-access"), runner.index("docker run"))
		self.assertLess(
			source.index('main_lane runtime-access > "$release_dir/private-access.json"'),
			source.index("systemctl --user stop"),
		)
		self.assertIn("target=/release-evidence,readonly", source)
		self.assertIn("--before-audit /release-evidence/before.json", source)
		self.assertNotIn('chmod 644 "$release_dir/', source)
		self.assertIn('--joint-rollback --receipt "$native_receipt"', source)
		self.assertIn('command_runner "$new_image_id" "$python" -c', source)
		self.assertNotIn("chmod 644 /tmp/procurement-metadata-receipt.json", source)

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
oa_sha=oa-target
services=(backend frontend queue-long queue-short scheduler websocket)
docker() {{
  case "$*" in
    *'.Image'* ) if [[ "$*" == *frontend* ]]; then printf '{image}'; else printf 'image-target'; fi ;;
    *'.State.Running'* ) if [[ "$*" == *frontend* ]]; then printf '{running}'; else printf 'true'; fi ;;
    *branding.revision* ) if [[ "$*" == *frontend* && '{mixed_label}' == branding ]]; then printf 'other'; else printf 'branding-target'; fi ;;
    *crm.revision* ) if [[ "$*" == *frontend* && '{mixed_label}' == crm ]]; then printf 'other'; else printf 'crm-current'; fi ;;
    *finance.revision* ) if [[ "$*" == *frontend* && '{mixed_label}' == finance ]]; then printf 'other'; else printf '{finance}'; fi ;;
    *oa.revision* ) if [[ "$*" == *frontend* && '{mixed_label}' == oa ]]; then printf 'other'; else printf 'oa-target'; fi ;;
  esac
}}
{functions}
release_is_current
"""
				result = subprocess.run(["bash", "-c", mock], capture_output=True, text=True)
				self.assertEqual(result.returncode, expected, result.stderr)

	def test_already_current_checks_live_native_contract_before_unlocking_or_retargeting_sync(self):
		source = self.release_source()
		branch = source.split("if release_is_current; then", 1)[1].split("\nfi", 1)[0]
		self.assertIn('capture_release_audit current "$release_dir/current-contract.json"', branch)
		self.assertLess(branch.index("capture_release_audit current"), branch.index("flock -u 9"))
		self.assertLess(
			branch.index("current_contract_verified"), branch.index("retarget_existing_source_sync")
		)
		self.assertLess(
			source.index("capture_release_audit() {"), source.index("if release_is_current; then")
		)

	def test_current_audit_checks_frozen_sources_before_read_only_native_contract_without_historical_rows(
		self,
	):
		events = []
		fake = types.SimpleNamespace(
			init=lambda **kw: events.append("init"),
			connect=lambda: events.append("connect"),
			destroy=lambda: events.append("destroy"),
			db=types.SimpleNamespace(rollback=lambda: events.append("rollback")),
		)
		audit = self.audit_module(fake)
		metadata = sys.modules["procurement_release_metadata"]
		with tempfile.TemporaryDirectory() as directory:
			manifest = Path(directory) / "manifest.json"
			manifest.write_text('{"apps": {}}')
			with (
				patch.dict(
					audit["main"].__globals__,
					{
						"verify_sources": lambda frozen, phase: events.append(("source", phase)),
						"capture_audit": lambda **kw: self.fail(
							"Current verification must not compare historical business rows"
						),
					},
				),
				patch.object(
					metadata,
					"verify_current_joint_contract",
					lambda **kw: events.append("native") or {"current_contract_verified": True},
					create=True,
				),
				patch.object(
					sys, "argv", ["audit", "--phase", "current", "--release-manifest", str(manifest)]
				),
				contextlib.redirect_stdout(io.StringIO()),
			):
				audit["main"]()
		self.assertEqual(events, ["init", "connect", ("source", "after"), "native", "rollback", "destroy"])

	def test_capture_stages_the_same_importable_audit_filename_used_by_current_native_verification(self):
		capture = self.shell_function("capture_release_audit")
		self.assertIn(
			'command_runner "$image" /home/frappe/frappe-bench/env/bin/python /release/deploy/production/audit_unified_purchase.py',
			capture,
		)
		self.assertNotIn("docker cp", capture)
		self.assertNotIn("/tmp/audit-unified-purchase.py", capture)

	def test_current_branch_rejects_complete_source_drift_before_timer_handoff(self):
		branch = self.release_source().split("if release_is_current; then", 1)[1].split("\nfi", 1)[0]
		self.assertIn("capture_pinned_sources", branch)
		for drift in (False, True):
			with self.subTest(drift=drift), tempfile.TemporaryDirectory() as directory:
				current = {
					"current_contract_verified": True,
					"release_sources_all": {
						"deeplinkerp_branding": {"unchanged.py": "changed" if drift else "pinned"}
					},
				}
				pinned = {"deeplinkerp_branding": {"unchanged.py": "pinned"}}
				mock = f"""set -e
build_dir="$1"
release_dir="$1"
resume_receipt=/private/resume.json
private_runtime_gid=1001
branding_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
python=/env/bin/python
dc=(docker compose)
curl() {{ return 0; }}
docker() {{ printf 'image-current'; }}
capture_release_audit() {{ printf '%s' '{json.dumps(current)}' > "$2"; }}
capture_pinned_sources() {{ printf '%s' '{json.dumps(pinned)}' > "$2"; }}
flock() {{ printf 'UNLOCK\\n'; }}
retarget_existing_source_sync() {{ printf 'RETARGET\\n'; }}
release_is_current() {{ return 0; }}
command_runner() {{ printf 'CHECK RESUME\\n'; }}
{branch}
"""
				result = subprocess.run(
					["bash", "-c", mock, "current-contract-test", directory], capture_output=True, text=True
				)
				self.assertEqual(result.returncode, 1 if drift else 0, result.stderr)
				self.assertEqual("UNLOCK" in result.stdout, not drift)
				self.assertEqual("RETARGET" in result.stdout, not drift)

	def test_current_audit_does_not_claim_cutover_quiescence(self):
		mock = (
			self.shell_function("command_runner")
			+ self.shell_function("capture_release_audit")
			+ """
set -eo pipefail
build_dir="$1"
release_dir="$1"
release_network=verified
sites_spec=sites-volume
branding_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
resume_receipt=/private/resume.json
private_runtime_gid=1001
old_image_id=old-image
dc=(docker compose)
audit_args=()
chmod() { return 0; }
docker() { printf '%s\\n' "$*"; }
main_lane() { return 0; }
capture_release_audit current "$build_dir/current.json"
"""
		)
		with tempfile.TemporaryDirectory() as directory:
			result = subprocess.run(
				["bash", "-c", mock, "current-audit-proof", directory], capture_output=True, text=True
			)
			self.assertEqual(result.returncode, 0, result.stderr)
			output = (Path(directory) / "current.json").read_text()
			self.assertIn("--group-add 1001", output)
			self.assertNotIn("DEEPLINKERP_RELEASE_DRAIN_RECEIPT", output)
			self.assertNotIn("DEEPLINKERP_RELEASE_QUIESCENT=1", output)

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
		staged = (
			self.shell_function("revision_label")
			+ self.shell_function("verify_staged_release")
			+ """
services=(backend frontend queue-long queue-short scheduler websocket)
docker() { case "$*" in *'.Image'*) printf 'image';; *'.State.Running'*) case "$*" in *queue-long*|*queue-short*|*scheduler*) printf 'false';; *) printf 'true';; esac;; *branding.revision*) printf 'branding';; *crm.revision*) printf 'crm';; *finance.revision*) return 1;; esac; }
verify_staged_release image branding crm ''
"""
		)
		result = subprocess.run(["bash", "-c", staged], capture_output=True, text=True)
		self.assertEqual(result.returncode, 1)

	def test_joint_overlays_preserve_crm_and_capture_legacy_finance_and_oa_labels(self):
		source = self.release_source()
		block = source.split("current_revision=$(", 1)[1].split("\nsource_sync_timer_active=", 1)[0]
		for finance in ("finance-current", "<no value>"):
			with self.subTest(finance=finance):
				mock = (
					self.shell_function("revision_label")
					+ f"""
docker() {{ case "$*" in *branding.revision*) printf 'branding-current';; *crm.revision*) printf 'crm-current';; *finance.revision*) printf '{finance}';; *oa.revision*) printf '<no value>';; esac; }}
crm_archive=''
finance_archive=''
crm_sha=preserved
finance_sha=preserved
current_revision=$({block}
printf '%s|%s|%s|%s' "$crm_sha" "$finance_sha" "$current_finance" "$current_oa"
"""
				)
				result = subprocess.run(["bash", "-c", mock], capture_output=True, text=True)
				self.assertEqual(result.returncode, 0, result.stderr)
				self.assertEqual(
					result.stdout,
					"crm-current|preserved|" + ("" if finance == "<no value>" else finance) + "|",
				)

	def compare_audits(self, before, after, manifest, active_sites=None):
		active_sites = active_sites or ["deeplinkerp.com", "akivision.deeplinkerp.com", "latingo.deeplinkerp.com", "yuewei.deeplinkerp.com"]
		_source = self.release_source()
		code = self.shell_function("verify_audit_ownership").split("<<'PY'\n", 1)[1].split("\nstats=", 1)[0]
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			roles = [{"name": "original-child-" + str(index)} for index in range(5)]
			digest = runpy.run_path(
				str(Path(__file__).parents[1] / "deploy/production/procurement_release_metadata.py")
			)["digest"]
			metadata = {
				"scope": {"Page": [{"name": "purchase-payables"}], "Has Role": []},
				"outside": {"Has Role": digest(roles)},
				"outside_rows": {"Has Role": roles},
			}
			before = dict(before, joint_metadata=metadata)
			after = dict(after, joint_metadata=metadata)
			before["release_sources_all"] = dict(
				before["release_sources"], crm_integration={"original.py": "crm"}
			)
			before["approved_sources_after"] = json.loads(json.dumps(before["release_sources_all"]))
			for app, files in manifest["apps"].items():
				for name, version in files.items():
					before["approved_sources_after"][app][name] = version["after"]
			after["release_sources_all"] = dict(
				after["release_sources"], crm_integration={"original.py": "crm"}
			)
			old_schema = {
				"columns": {"name": {"type": "varchar(140)"}},
				"indexes": {"PRIMARY": [{"column": "name", "unique": 1}]},
				"table": {"engine": "InnoDB"},
			}
			new_schema = json.loads(json.dumps(old_schema))
			new_schema["columns"]["custom_operating_event_key"] = {"type": "varchar(140)"}
			new_schema["indexes"]["custom_operating_event_key"] = [
				{"column": "custom_operating_event_key", "unique": 1, "prefix": None, "type": "BTREE"}
			]
			before["schemas"], after["schemas"] = {"Journal Entry": old_schema}, {"Journal Entry": new_schema}
			for audit in (before, after):
				audit["tables"]["Journal Entry"] = digest([])
			models = {
				name: {"schema": None, "rows": []}
				for name in runpy.run_path(
					str(Path(__file__).parents[1] / "deploy/production/procurement_release_metadata.py")
				)["JOINT_MODELS"]
			}
			receipt = {
				"status": "applied",
				"steps": [{"status": "complete"}],
				"before": {
					"metadata": metadata,
					"je": {"schema": old_schema, "rows": [], "original_columns": ["name"]},
					"models": models,
					"operating_singles": [],
				},
				"after": {
					"metadata": metadata,
					"je": {"schema": new_schema, "rows": [], "original_columns": ["name"]},
					"models": models,
					"operating_singles": [],
				},
				"contract": {
					"sources_before": before["release_sources_all"],
					"sources_after": before["approved_sources_after"],
					"model_schemas": {name: None for name in models},
				},
			}
			receipt["contract"]["custom_fields"] = {"custom_operating_event_key": {}}
			(root / "joint-receipt.json").write_text(json.dumps(receipt))
			deployment = root / "deploy/production"
			deployment.mkdir(parents=True)
			(deployment / "procurement_release_metadata.py").write_text(
				(Path(__file__).parents[1] / "deploy/production/procurement_release_metadata.py").read_text()
			)
			(deployment / "joint_release_guards.py").write_text(
				(Path(__file__).parents[1] / "deploy/production/joint_release_guards.py").read_text()
			)
			(root / "before.json").write_text(json.dumps(before))
			(root / "after.json").write_text(json.dumps(after))
			(root / "tenants.json").write_text(json.dumps({"sites": {site: {} for site in active_sites}}))
			for site in active_sites[1:]:
				for phase, value in (("before", before), ("after", after), ("joint-receipt", receipt)):
					(root / (site + "." + phase + ".json")).write_text(json.dumps(value))
			(root / "release-source-manifest.json").write_text(json.dumps(manifest))
			return subprocess.run(
				[sys.executable, "-c", code, tmp, tmp, "candidate", "image", "old-image", "0"],
				capture_output=True,
				text=True,
			)

	def test_finance_manifest_preserves_crm_and_rejects_unlisted_or_wrong_sources(self):
		manifest = {
			"apps": {
				"deeplinkerp_branding": {"page.js": {"before": "old", "after": "new"}},
			}
		}
		before = {
			"tables": {
				"Has Role": runpy.run_path(
					str(Path(__file__).parents[1] / "deploy/production/procurement_release_metadata.py")
				)["digest"]([{"name": "original-child-" + str(index)} for index in range(5)])
			},
			"preserved_apps": {"crm_integration": "crm", "china_finance": "old"},
			"release_sources": {
				"deeplinkerp_branding": {"page.js": "old"},
				"china_finance": {"services/voucher.py": "old", "private.py": "keep"},
			},
		}
		after = json.loads(json.dumps(before))
		for app in manifest["apps"]:
			after["release_sources"][app][next(iter(manifest["apps"][app]))] = "new"
		self.assertEqual(self.compare_audits(before, after, manifest).returncode, 0)
		self.assertEqual(self.compare_audits(before, after, manifest, active_sites=["deeplinkerp.com"]).returncode, 0)
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
			for app in ("deeplinkerp_branding", "china_finance", "crm_integration", "oa_purchase_request"):
				(root / "apps" / app / app).mkdir(parents=True)
			(root / "sites/assets/assets.json").write_text('{"bundle": "same"}')
			(root / "sites/common_site_config.json").write_text('{"maintenance_mode": 1, "secret": "hidden"}')
			config = root / "sites/deeplinkerp.com/site_config.json"
			config.write_text('{"maintenance_mode": 1, "mes_callback_url": "updated"}')
			queried = []
			new_oa = {"present": False, "nonnull": 0}
			_, page = self.purchase_payment_page_fixture()
			roles = page["roles"]
			settings = {"CRM Integration Settings", "MES Integration Settings", "China Finance Settings"}

			def meta(name):
				return types.SimpleNamespace(
					issingle=name in settings,
					fields=[types.SimpleNamespace(fieldtype="Table", options=name + " Child")],
				)

			def sql(query, values=None, **kwargs):
				queried.append(query)
				if "information_schema.COLUMNS" in query:
					rows = [
						{
							"name": "name",
							"position": 1,
							"type": "varchar(140)",
							"nullable": "NO",
							"default_value": None,
							"charset": "utf8mb4",
							"collation": "utf8mb4_unicode_ci",
							"extra": "",
							"expression": None,
						}
					]
					if new_oa["present"] and values == ("tabOA Purchase Request",):
						field = new_oa.get("field", "custom_purchase_source_json")
						check = field == "custom_purchase_company_confirmed"
						rows.append(
							dict(
								rows[0],
								name=field,
								position=2,
								type="tinyint(4)" if check else "longtext",
								nullable="NO" if check else "YES",
								default_value="0" if check else "NULL",
								charset=None if check else "utf8mb4",
								collation=None if check else "utf8mb4_unicode_ci",
							)
						)
					return rows
				if "information_schema.STATISTICS" in query:
					return [
						{
							"name": "PRIMARY",
							"sequence": 1,
							"column": "name",
							"unique": 1,
							"prefix": None,
							"collation": "A",
							"type": "BTREE",
							"nullable": "",
						}
					]
				if "information_schema.TABLES" in query:
					return [
						{
							"engine": "InnoDB",
							"row_format": "Dynamic",
							"collation": "utf8mb4_unicode_ci",
							"options": "",
						}
					]
				if "tabHas Role`" in query:
					self.assertEqual(query, "select * from `tabHas Role` order by name")
					return roles
				if query.startswith("select count(*) from `tabOA Purchase Request`"):
					return [[new_oa["nonnull"]]]
				return (
					[{"doctype": "MES Integration Settings", "field": "callback_url", "value": "updated"}]
					if "tabSingles" in query
					else []
				)

			fake = types.SimpleNamespace(
				local=types.SimpleNamespace(site="deeplinkerp.com"),
				db=types.SimpleNamespace(exists=lambda *args: True, sql=sql),
				get_meta=meta,
				get_installed_apps=lambda: [],
			)
			module = self.audit_module(fake)
			capture = module["capture_audit"]
			capture.__globals__["BENCH"] = root
			capture.__globals__["source_digest"] = lambda app: "source"
			before = capture()
			capture(oa_columns=["name", "manual_user_text"])
			self.assertIn(
				"select `name`,`manual_user_text` from `tabOA Purchase Request` order by name", queried
			)
			self.assertIn("Operating Expense Source", before["operating_models"])
			new_oa["present"] = True
			self.assertEqual(
				capture(oa_columns=["name"])["oa_new_columns"], {"custom_purchase_source_json": 0}
			)
			new_oa["nonnull"] = 1
			self.assertEqual(
				capture(oa_columns=["name"])["oa_new_columns"], {"custom_purchase_source_json": 1}
			)
			new_oa.update(field="custom_purchase_company_confirmed", nonnull=0)
			self.assertEqual(
				capture(oa_columns=["name"])["oa_new_columns"], {"custom_purchase_company_confirmed": 0}
			)
			self.assertIn(
				"select count(*) from `tabOA Purchase Request` where `custom_purchase_company_confirmed` is null or `custom_purchase_company_confirmed` <> 0",
				queried,
			)
			new_oa["nonnull"] = 1
			self.assertEqual(
				capture(oa_columns=["name"])["oa_new_columns"], {"custom_purchase_company_confirmed": 1}
			)
			fake.conf = {"purchase_source_sync_enabled": True, "maintenance_mode": 1}
			with patch.dict(
				sys.modules, {"joint_release_guards": types.SimpleNamespace(verified_quiescence=lambda: True)}
			):
				self.assertTrue(capture()["release_quiescent"])
			with patch.dict(
				sys.modules,
				{"joint_release_guards": types.SimpleNamespace(verified_quiescence=lambda: False)},
			):
				self.assertFalse(capture()["release_quiescent"])
			fake.conf["maintenance_mode"] = 0
			with patch.dict(
				sys.modules,
				{
					"joint_release_guards": types.SimpleNamespace(
						verified_quiescence=lambda: self.fail("Live audit must not claim quiescence")
					)
				},
			):
				self.assertFalse(capture()["release_quiescent"])
			fake.conf = {}
			new_oa["present"] = False
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
			for parent in (
				"Journal Entry",
				"China Cash Flow Assignment",
				"China Voucher Sync Issue",
				"Company",
				*settings,
			):
				self.assertIn(parent + " Child", before["tables"])
			self.assertEqual(before["schemas"]["Journal Entry"]["columns"]["name"]["nullable"], "NO")
			self.assertIsNone(before["schemas"]["Journal Entry"]["columns"]["name"]["default_value"])
			self.assertEqual(before["schemas"]["Journal Entry"]["indexes"]["PRIMARY"][0]["unique"], 1)
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
			"services/voucher.py",
			"tests/test_cancellation_sync.py",
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
		permission_fix = 'chmod -R a+rX "$build_dir"'
		self.assertIn(permission_fix, source)
		self.assertLess(
			source.index(permission_fix),
			source.index('capture_release_audit current "$release_dir/current-contract.json"'),
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
		resume_marker=None,
	):
		source = (Path(__file__).parents[1] / "deploy/production/deploy_unified_purchase.sh").read_text()
		function = source.split("recover() {", 1)[1].split("\ntrap recover EXIT", 1)[0]
		capture = self.shell_function("capture_release_audit")
		release_functions = "".join(
			self.shell_function(name)
			for name in (
				"revision_label",
				"quiesce_release_workers",
				"verify_staged_release",
				"verify_running_release",
				"verify_retired_routes",
			)
		)
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
sites=(deeplinkerp.com akivision.deeplinkerp.com latingo.deeplinkerp.com yuewei.deeplinkerp.com)
baseline_captured={int(baseline_captured)}
metadata_started=1
metadata_started_sites=(akivision.deeplinkerp.com latingo.deeplinkerp.com yuewei.deeplinkerp.com)
release_dir="$1"
build_dir="$1"
audit_args=(--release-manifest /release/release-source-manifest.json)
frozen_base=mock-base
old_image_id=sha256:expected
new_image_id=sha256:candidate
current_revision=branding-old
current_crm=crm-old
current_finance=finance-old
current_oa=oa-old
branding_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
native_receipt=/private/absent-joint-receipt.json
resume_receipt=/private/resume.json
python=/env/bin/python
guard=/release/deploy/production/joint_release_guards.py
metadata=/release/deploy/production/procurement_release_metadata.py
maintenance_calls=0
workers_running=0
cp() {{ printf 'COPY %s\\n' "$*"; }}
chmod() {{ return 0; }}
sleep() {{ :; }}
docker() {{
  case "$*" in
    'image inspect '*) printf '%s\\n' "$old_image_id" ;;
    inspect*'.Image'* ) printf '%s\\n' "$old_image_id" ;;
    inspect*'.State.Running'* ) if (( workers_running )); then printf 'true\\n'; else printf 'false\\n'; fi ;;
    inspect*branding.revision*) printf '%s' "$current_revision" ;;
    inspect*crm.revision*) printf '%s' "$current_crm" ;;
    inspect*finance.revision*) printf '%s' "$current_finance" ;;
    inspect*oa.revision*) printf '%s' "$current_oa" ;;
    'compose up '*) case "$*" in *--no-start*) workers_running=0; printf 'STAGE STOPPED\\n';; *) workers_running=1; printf 'UP\\n';; esac; return {up_status} ;;
    *) printf 'DOCKER %s\\n' "$*" ;;
  esac
}}
command_runner() {{
  printf 'COMMAND %s\\n' "$*" >&2
  case "$*" in
    *--assert-pre-resume*) [[ '{resume_marker or "absent"}' == absent ]] ;;
    *--maintenance-on*) printf 'MAINTENANCE ON\\n'; return 0 ;;
    *--maintenance-restore*) printf 'RESTORE EXACT CONFIG\\n'; return 0 ;;
    *--joint-rollback*) printf 'METADATA ROLLBACK\\n'; return {copy_status} ;;
    *--record-resume*) printf 'DURABLE OLD RESUME\\n' >&2; printf '{{}}'; return 0 ;;
    *'/audit_unified_purchase.py'*)
      if (( {audit_status} )); then return {audit_status}; fi
      command cat "$release_dir/rollback-fixture.json" ;;
    *) return 0 ;;
  esac
}}
curl() {{ printf 'HEALTH\\n'; return {health_status}; }}
{capture}
{release_functions}
recover() {{{function}
false
recover
"""
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "tenants.json").write_text(json.dumps({"sites": {site: {} for site in ("deeplinkerp.com", "akivision.deeplinkerp.com", "latingo.deeplinkerp.com", "yuewei.deeplinkerp.com")}}))
			if baseline_present:
				(root / "before.json").write_text(json.dumps(baseline))
				for site in (
					"akivision.deeplinkerp.com",
					"latingo.deeplinkerp.com",
					"yuewei.deeplinkerp.com",
				):
					(root / (site + ".before.json")).write_text(json.dumps(baseline))
			(root / "rollback-fixture.json").write_text(json.dumps(rollback))
			(root / "release-source-manifest.json").write_text('{"apps": {}}')
			return subprocess.run(["bash", "-c", mock, "recovery-test", tmp], capture_output=True, text=True)

	def test_recovered_image_requires_fresh_full_audit_before_maintenance_off(self):
		result = self.run_recovery()
		self.assertEqual(result.returncode, 1)
		self.assertIn("--phase before", result.stderr)
		self.assertIn("/release/deploy/production/audit_unified_purchase.py", result.stderr)
		self.assertIn("/release/release-source-manifest.json", result.stderr)
		self.assertIn("Restored full audit matches original baseline", result.stdout)
		self.assertLess(
			result.stdout.index("Restored full audit"), result.stdout.index("RESTORE EXACT CONFIG")
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
				self.assertNotIn("RESTORE EXACT CONFIG", result.stdout)
				self.assertNotIn("HEALTH", result.stdout)
				self.assertNotIn("stop frappe_docker-frontend-1", result.stdout)
				self.assertIn("HOLD", result.stderr)

	def test_failed_rollback_never_disables_maintenance(self):
		result = self.run_recovery(up_status=1)
		self.assertEqual(result.returncode, 1)
		self.assertIn("MAINTENANCE ON", result.stdout)
		self.assertNotIn("RESTORE EXACT CONFIG", result.stdout)
		self.assertIn("HOLD", result.stderr)

	def test_verified_rollback_checks_health_before_accepting_recovery(self):
		result = self.run_recovery()
		self.assertEqual(result.returncode, 1)  # Original release still failed.
		self.assertIn("RESTORE EXACT CONFIG", result.stdout)
		self.assertIn("HEALTH", result.stdout)
		self.assertNotIn("Manual recovery required", result.stderr)

	def test_unhealthy_rollback_reenables_maintenance(self):
		result = self.run_recovery(health_status=1)
		self.assertEqual(result.returncode, 1)
		self.assertEqual(result.stdout.count("MAINTENANCE ON"), 1)
		self.assertIn("HOLD", result.stderr)

	def test_dead_new_backend_does_not_block_host_side_rollback(self):
		result = self.run_recovery(initial_maintenance_status=1)
		self.assertEqual(result.returncode, 1)
		self.assertNotIn("stop frappe_docker-frontend-1", result.stdout)
		self.assertEqual(result.stdout.count("UP"), 1)
		self.assertIn("RESTORE EXACT CONFIG", result.stdout)
		self.assertNotIn("Manual recovery required", result.stderr)

	def test_present_or_unreadable_first_resume_prevents_every_destructive_recovery(self):
		for marker in ("present", "unreadable"):
			with self.subTest(marker=marker):
				result = self.run_recovery(resume_marker=marker)
				self.assertEqual(result.returncode, 1)
				self.assertIn("forward-only", result.stderr)
				self.assertIn("MAINTENANCE ON", result.stdout)
				for forbidden in ("--joint-rollback", "compose up", "COPY", "RESTORE EXACT CONFIG", "HEALTH"):
					self.assertNotIn(forbidden, result.stdout + result.stderr)


if __name__ == "__main__":
	unittest.main()
