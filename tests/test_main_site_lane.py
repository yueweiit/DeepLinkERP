"""Main-only topology/account/route boundaries; never contact a live host."""

import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]


class MainSiteLaneTests(unittest.TestCase):
	def module(self):
		path = ROOT / "deploy/production/main_site_lane.py"
		self.assertTrue(path.exists(), "Executable main-only isolation helper is missing")
		sys.path.insert(0, str(path.parent))
		self.addCleanup(sys.path.pop, 0)
		spec = importlib.util.spec_from_file_location("main_site_lane", path)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
		return module

	def test_future_frontend_bind_preserves_every_unrelated_dirty_compose_byte(self):
		lane = self.module()
		original = b"# local dirty note\nservices:\n  backend:\n    image: old\n  frontend:\n    image: old # keep\n    volumes:\n      - sites:/home/frappe/frappe-bench/sites\n    ports:\n      - '8888:8080'\nvolumes:\n  sites:\n    external: true\n"
		binding = (
			"/release/private/main-routes/deeplinkerp-main.conf:/etc/nginx/conf.d/deeplinkerp-main.conf:ro"
		)
		changed = lane.frontend_bind(original, binding)
		self.assertEqual(changed.replace(("      - " + json.dumps(binding) + "\n").encode(), b""), original)
		with self.assertRaisesRegex(AssertionError, "already|Unknown"):
			lane.frontend_bind(changed, binding)

	def test_exact_main_server_covers_assets_files_protected_and_socket_urls(self):
		lane = self.module()
		maintenance = lane.main_route(maintenance=True)
		serving = lane.main_route(maintenance=False)
		self.assertIn("server_name deeplinkerp.com;", maintenance)
		self.assertIn("return 503;", maintenance)
		self.assertIn("location /", serving)
		self.assertIn("proxy_pass $dlp_main_frontend;", serving)
		self.assertIn("deeplinkerp_main-frontend-1:8080", serving)
		self.assertIn("proxy_set_header Upgrade $http_upgrade;", serving)
		self.assertNotIn("try_files", serving)
		self.assertNotIn("akivision", serving)

	def test_subpath_lane_has_private_config_and_separate_processes_with_bounded_memory(self):
		lane = self.module()
		model = lane.lane_compose(
			"sha256:" + "a" * 64,
			"sha256:" + "b" * 64,
			"/private/release",
			".deeplinkerp-main-lane/release/deeplinkerp.com",
		)
		services = model["services"]
		self.assertEqual(
			set(services),
			{
				"main-backend",
				"main-frontend",
				"main-websocket",
				"main-queue-long",
				"main-queue-short",
				"main-redis-queue",
				"main-redis-cache",
			},
		)
		total = sum(service["mem_limit"] for service in services.values())
		self.assertLessEqual(total, 4 * 1024**3)
		self.assertGreater(total, 2 * 1024**3)
		for name, service in services.items():
			self.assertEqual(
				service["container_name"], "deeplinkerp_main-" + name.removeprefix("main-") + "-1"
			)
			self.assertNotIn("ports", service)
			if name.startswith("main-redis-"):
				continue
			mounts = service["volumes"]
			site = next(value for value in mounts if value["target"].endswith("/sites/deeplinkerp.com"))
			self.assertEqual(site["volume"]["subpath"], ".deeplinkerp-main-lane/release/deeplinkerp.com")
			config = next(value for value in mounts if value["target"].endswith("/site_config.json"))
			self.assertEqual(config["source"], "/private/release/main-site-config.json")
			self.assertTrue(config["read_only"])
			self.assertFalse(any(value["target"].endswith("/sites/assets") for value in mounts))
			self.assertEqual(len([value for value in mounts if value["type"] == "volume"]), 1)
		self.assertEqual(model["volumes"]["sites"], {"external": True, "name": "frappe_docker_sites"})
		self.assertEqual(model["networks"]["default"]["name"], "frappe_docker_default")

	def test_account_preflight_accepts_all_original_hosts_and_refuses_other_database_grants(self):
		lane = self.module()
		accounts = [
			{
				"user": "_main",
				"host": host,
				"priv": {"account_locked": False, "authentication_string": "hash"},
				"grants": [
					"GRANT USAGE ON *.* TO `_main`@`" + host + "`",
					"GRANT ALL PRIVILEGES ON `_maindb`.* TO `_main`@`" + host + "`",
				],
			}
			for host in ("%", "172.18.0.9", "172.18.0.5")
		]
		lane.validate_accounts(accounts, "_main", "_maindb")
		for drift in ("other-db", "grant-option", "role", "locked", "other-user"):
			changed = copy.deepcopy(accounts)
			if drift == "other-db":
				changed[0]["grants"][1] = changed[0]["grants"][1].replace("_maindb", "otherdb")
			elif drift == "grant-option":
				changed[0]["grants"][1] += " WITH GRANT OPTION"
			elif drift == "role":
				changed[0]["grants"].append("GRANT `role` TO `_main`@`%`")
			elif drift == "locked":
				changed[0]["priv"]["account_locked"] = True
			else:
				changed[0]["user"] = "other"
			with self.subTest(drift=drift), self.assertRaises(AssertionError):
				lane.validate_accounts(changed, "_main", "_maindb")

	def test_private_credentials_are_outside_every_original_container_host_mount(self):
		lane = self.module()
		self.assertTrue(
			hasattr(lane, "assert_private_host_boundary"), "Private host credential boundary is missing"
		)
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp) / "private/evidence"
			root.mkdir(parents=True)
			lane.assert_private_host_boundary(
				root, [{"Mounts": [{"Type": "volume", "Source": str(Path(tmp) / "sites-volume")}]}]
			)
			for exposed in (root, root.parent, Path(tmp)):
				with (
					self.subTest(exposed=exposed),
					self.assertRaisesRegex(AssertionError, "private|credential"),
				):
					lane.assert_private_host_boundary(
						root, [{"Mounts": [{"Type": "bind", "Source": str(exposed)}]}]
					)

	def test_private_runtime_access_rejects_public_groups_and_shares_only_host_inputs(self):
		lane = self.module()
		self.assertTrue(hasattr(lane, "runtime_access"), "Cross-UID private input access is missing")
		owner = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_name="release")
		group = types.SimpleNamespace(gr_mem=[])
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "before.json").write_text('{"private":"receipt"}')
			(root / "host-only.py").write_text("private host tool")
			(root / "main_site_lane.py").write_text("frozen main helper")
			os.chmod(root / "main_site_lane.py", 0o600)
			os.chmod(root, 0o700)
			os.chmod(root / "before.json", 0o600)
			os.chmod(root / "host-only.py", 0o600)
			with (
				patch.object(lane.pwd, "getpwuid", return_value=owner),
				patch.object(lane.pwd, "getpwall", return_value=[owner]),
				patch.object(lane.grp, "getgrgid", return_value=group),
			):
				result = lane.runtime_access(root)
				self.assertEqual(result, {"private_gid": os.getgid(), "host_uid": os.getuid()})
				self.assertEqual(root.stat().st_mode & 0o777, 0o750)
				self.assertEqual((root / "before.json").stat().st_mode & 0o777, 0o640)
				self.assertEqual((root / "host-only.py").stat().st_mode & 0o777, 0o600)
				self.assertEqual((root / "main_site_lane.py").stat().st_mode & 0o777, 0o640)
				self.assertEqual((root / "before.json").stat().st_uid, os.getuid())
				lane.DDLReceipt(root / "before.json", {})._write(b'{"private":"updated"}')
				self.assertEqual((root / "before.json").stat().st_mode & 0o777, 0o600)
				lane.runtime_access(root)
				self.assertEqual((root / "before.json").stat().st_mode & 0o777, 0o640)
				for foreign in ("primary", "supplemental", "symlink"):
					with self.subTest(foreign=foreign):
						others = (
							[owner, types.SimpleNamespace(pw_uid=os.getuid() + 1, pw_gid=os.getgid())]
							if foreign == "primary"
							else [owner]
						)
						members = ["another-user"] if foreign == "supplemental" else []
						if foreign == "symlink":
							(root / "outside.json").symlink_to(root / "before.json")
						with (
							patch.object(lane.pwd, "getpwall", return_value=others),
							patch.object(
								lane.grp, "getgrgid", return_value=types.SimpleNamespace(gr_mem=members)
							),
							self.assertRaisesRegex(AssertionError, "private|owned|symlink"),
						):
							lane.runtime_access(root)
						if foreign == "symlink":
							(root / "outside.json").unlink()

	def test_new_main_services_and_command_runner_share_frozen_private_group_without_changing_user(self):
		lane = self.module()
		self.assertIn(
			"private_gid", lane.lane_compose.__code__.co_varnames, "Main runtime private group is missing"
		)
		model = lane.lane_compose(
			"candidate",
			"redis",
			"/private/release",
			".deeplinkerp-main-lane/release/deeplinkerp.com",
			private_gid=1001,
		)
		for name, service in model["services"].items():
			self.assertNotIn("user", service)
			if name.startswith("main-redis-"):
				self.assertNotIn("group_add", service)
			else:
				self.assertEqual(service["group_add"], ["1001"])

	def test_private_access_cli_failure_retains_private_identity_report_without_other_changes(self):
		lane = self.module()
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "before.json").write_text('{"unchanged":true}')
			stderr = io.StringIO()
			with (
				patch.object(lane, "runtime_access", side_effect=AssertionError("public group")),
				patch.object(sys, "argv", ["main_site_lane", "runtime-access", "--evidence", str(root)]),
				contextlib.redirect_stderr(stderr),
			):
				self.assertEqual(lane.main(), 1)
			report = json.loads(stderr.getvalue())
			self.assertEqual(report["outcome"], "PRIVATE_ACCESS_FAILED")
			self.assertEqual(report.get("host_uid"), os.getuid())
			self.assertEqual(report.get("private_gid"), os.getgid())
			self.assertEqual(json.loads((root / "private-access-failure.json").read_bytes()), report)
			self.assertEqual((root / "private-access-failure.json").stat().st_mode & 0o777, 0o600)
			self.assertEqual((root / "before.json").read_text(), '{"unchanged":true}')
			self.assertFalse((root / "main-seal.json").exists())

	def test_cli_failure_reports_safe_locations_without_payload_or_error_text(self):
		lane = self.module()
		for unavailable in (None, "stat", "write"):
			with self.subTest(unavailable=unavailable), tempfile.TemporaryDirectory() as tmp:
				root = Path(tmp)
				stderr = io.StringIO()
				secret = "SECRET_FIXTURE_PASSWORD_AND_PAYLOAD"
				with (
					patch.object(lane, "prepare", side_effect=RuntimeError(secret)),
					patch.object(sys, "argv", ["main_site_lane", "prepare", "--evidence", str(root)]),
					patch.object(Path, "is_dir", return_value=True)
					if unavailable == "stat"
					else contextlib.nullcontext(),
					patch.object(Path, "stat", side_effect=PermissionError(secret))
					if unavailable == "stat"
					else contextlib.nullcontext(),
					patch.object(lane.DDLReceipt, "_write", side_effect=PermissionError(secret))
					if unavailable == "write"
					else contextlib.nullcontext(),
					contextlib.redirect_stderr(stderr),
				):
					try:
						self.assertEqual(lane.main(), 1)
					except PermissionError:
						self.fail("Log ownership/stat failure must retain a redacted structured HOLD")
				report = json.loads(stderr.getvalue())
				self.assertEqual(report.get("phase"), "prepare")
				self.assertEqual(report.get("exception_type"), "RuntimeError")
				self.assertTrue(report.get("locations"))
				for location in report["locations"]:
					self.assertEqual(set(location), {"file", "function", "line"})
					self.assertIn(location["file"], {"main_site_lane.py", "joint_release_guards.py"})
					self.assertGreater(location["line"], 0)
				log = root / "main-action-failure.json"
				if unavailable:
					self.assertEqual(report.get("durable_log"), "unconfirmed")
					self.assertFalse(log.exists())
				else:
					self.assertEqual(json.loads(log.read_bytes()), report)
					self.assertEqual(log.stat().st_mode & 0o777, 0o600)
					self.assertNotIn(secret, log.read_text())
				self.assertNotIn(secret, stderr.getvalue())
				self.assertFalse((root / "main-seal.json").exists())

	def test_private_scaffold_keeps_config_read_only_and_logs_group_writable(self):
		lane = self.module()
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			volume = {
				"common": base64.b64encode(b"{}").decode(),
				"apps": base64.b64encode(b"frappe\nerpnext\n").decode(),
				"assets_link": lane.BENCH + "/assets",
			}
			lane.private_roots(root, volume, {"db_password": "fixture", "maintenance_mode": 1})
			for name in ("main-sites", "main-sites/deeplinkerp.com"):
				self.assertEqual((root / name).stat().st_mode & 0o7777, 0o750)
			self.assertTrue((root / "main-sites/assets").is_symlink())
			self.assertEqual(os.readlink(root / "main-sites/assets"), lane.BENCH + "/assets")
			self.assertEqual((root / "main-sites/logs").stat().st_mode & 0o7777, 0o2770)
			for name in (
				"main-sites/apps.txt",
				"main-sites/common_site_config.json",
				"main-site-config.json",
			):
				self.assertEqual((root / name).stat().st_mode & 0o777, 0o640)
				self.assertEqual((root / name).stat().st_uid, os.getuid())
			for alias in ("/unreviewed/assets", "../assets"):
				with self.subTest(alias=alias), self.assertRaisesRegex(AssertionError, "asset|alias"):
					lane.private_roots(root / "unexpected", {**volume, "assets_link": alias}, {})

	def test_owned_cleanup_image_tools_keep_private_access_when_build_is_evidence(self):
		lane = self.module()
		owner = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_name="release")
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			for name in ("main_site_lane.py", "joint_release_guards.py"):
				(root / name).write_text("frozen helper")
				os.chmod(root / name, 0o600)
			with (
				patch.object(lane.pwd, "getpwuid", return_value=owner),
				patch.object(lane.pwd, "getpwall", return_value=[owner]),
				patch.object(lane.grp, "getgrgid", return_value=types.SimpleNamespace(gr_mem=[])),
				patch.object(lane, "host_call", return_value="{}") as call,
			):
				lane.image_call("frozen-base", root, "volume", payload={"action": "proof"})
			command = call.call_args.args[0]
			self.assertIn("--group-add", command)
			self.assertEqual(command[command.index("--group-add") + 1], str(os.getgid()))
			self.assertIn(
				"type=bind,source=" + str(root.resolve()) + ",target=/release-tools,readonly", command
			)
			for name in ("main_site_lane.py", "joint_release_guards.py"):
				self.assertEqual((root / name).stat().st_mode & 0o777, 0o640)

	def test_image_asset_and_startup_probes_mount_no_sites_volume(self):
		lane = self.module()
		for action in ("assets", "startup"):
			with self.subTest(action=action), patch.object(lane, "host_call", return_value="{}") as call:
				lane.image_call("frozen-image", ROOT, action, assets_only=True)
			command = call.call_args.args[0]
			mounts = [command[i + 1] for i, arg in enumerate(command[:-1]) if arg == "--mount"]
			self.assertEqual(len(mounts), 1, "Image-only proof must expose only frozen tools, not sites")
			self.assertIn("target=/release-tools,readonly", mounts[0])
			self.assertIn("--read-only", command)
			self.assertEqual(command[command.index("--network") + 1], "none")

	def test_original_auth_intent_survives_a_partial_host_lock_failure(self):
		lane = self.module()
		with tempfile.TemporaryDirectory() as tmp:
			receipt = lane.DDLReceipt.create(
				Path(tmp) / "seal.json", {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}, {}, {}
			)
			accounts = [
				{"user": "_main", "host": host, "priv": {}} for host in ("%", "172.18.0.9", "172.18.0.5")
			]

			def sql(query):
				if "172.18.0.9" in query:
					raise RuntimeError("database unavailable")

			with (
				patch.object(lane, "db_call", side_effect=sql),
				patch.object(
					lane, "account_snapshot", return_value=[{**accounts[0], "priv": {"account_locked": True}}]
				),
			):
				with self.assertRaises(RuntimeError):
					lane.lock_accounts(receipt, accounts)
			durable = lane.DDLReceipt.load(receipt.path).state
			self.assertEqual([step["id"] for step in durable["steps"]], ["lock-old-%", "lock-old-172.18.0.9"])
			self.assertEqual([step["status"] for step in durable["steps"]], ["complete", "pending"])
			self.assertEqual(durable["steps"][1]["before"]["priv"], {})

	def test_same_volume_rename_hides_main_discovery_without_exposing_new_credentials(self):
		lane = self.module()
		self.assertTrue(hasattr(lane, "site_boundary"), "Physical namespace seal is missing")
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			for site in lane.SHARED_SITES:
				(root / site / "private/files").mkdir(parents=True)
				(root / site / "site_config.json").write_text(
					json.dumps(
						{
							"db_name": "_db_" + site.split(".")[0],
							"db_user": "_user_" + site.split(".")[0],
							"db_password": "old",
							"maintenance_mode": 0,
						}
					)
				)
			(root / "common_site_config.json").write_text('{"redis_queue":"redis://old:6379"}')
			(root / "apps.txt").write_text("frappe\nerpnext\n")
			(root / "assets").symlink_to(lane.BENCH + "/assets")
			before = lane.site_boundary(root, "snapshot", ".deeplinkerp-main-lane/release/deeplinkerp.com")
			self.assertEqual(before.get("assets_link"), lane.BENCH + "/assets")
			for alias in ("/unreviewed/assets", "../assets"):
				(root / "assets").unlink()
				(root / "assets").symlink_to(alias)
				with self.subTest(alias=alias), self.assertRaisesRegex(AssertionError, "asset|alias"):
					lane.site_boundary(root, "snapshot", ".deeplinkerp-main-lane/release/deeplinkerp.com")
			(root / "assets").unlink()
			(root / "assets").symlink_to(lane.BENCH + "/assets")
			inode = (root / lane.SITE).stat().st_ino
			lane.site_boundary(root, "maintenance", ".deeplinkerp-main-lane/release/deeplinkerp.com", before)
			after = lane.site_boundary(
				root, "relocate", ".deeplinkerp-main-lane/release/deeplinkerp.com", before
			)
			self.assertNotIn(lane.SITE, after["discovered_sites"])
			destination = root / ".deeplinkerp-main-lane/release/deeplinkerp.com"
			self.assertEqual(destination.stat().st_ino, inode)
			self.assertEqual(
				json.loads((destination / "site_config.json").read_bytes())["db_password"], "old"
			)
			lane.site_boundary(root, "restore", ".deeplinkerp-main-lane/release/deeplinkerp.com", before)
			self.assertEqual((root / lane.SITE).stat().st_ino, inode)
			for site in lane.SHARED_SITES:
				self.assertEqual(
					(root / site / "site_config.json").read_bytes(), base64.b64decode(before["configs"][site])
				)

	def test_asset_reuse_proves_exact_symlink_target_and_manifest_body_without_writes(self):
		lane = self.module()
		self.assertTrue(hasattr(lane, "asset_view"), "Image-resolved readonly asset proof is missing")
		with tempfile.TemporaryDirectory() as tmp:
			bench = Path(tmp)
			assets = bench / "assets"
			assets.mkdir()
			public = bench / "apps/deeplinkerp_branding/deeplinkerp_branding/public"
			(public / "dist").mkdir(parents=True)
			(public / "dist/frozen.js").write_bytes(b"compiled")
			(assets / "deeplinkerp_branding").symlink_to(public)
			(assets / "assets.json").write_text('{"bundle.js":"/assets/deeplinkerp_branding/dist/frozen.js"}')
			before = (assets / "assets.json").read_bytes()
			try:
				proof = lane.asset_view(bench)
			except FileNotFoundError:
				self.fail("Image asset proof must use the physical root even without a sites/assets alias")
			self.assertEqual(
				proof["manifest_bodies"]["/assets/deeplinkerp_branding/dist/frozen.js"],
				hashlib.sha256(b"compiled").hexdigest(),
			)
			self.assertEqual((assets / "assets.json").read_bytes(), before)
			(assets / "deeplinkerp_branding").unlink()
			(assets / "deeplinkerp_branding").symlink_to(public / "dist")
			with self.assertRaisesRegex(AssertionError, "symlink|target"):
				lane.asset_view(bench)

	def test_runner_uses_real_subpath_mounts_and_verified_receipt_instead_of_env_boolean(self):
		lane = self.module()
		self.assertTrue(hasattr(lane, "runner_command"), "Main bounded command runner is missing")
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			contract = {
				"image_id": "sha256:" + "a" * 64,
				"base_image": "sha256:" + "c" * 64,
				"redis_image_id": "sha256:" + "b" * 64,
				"subpath": ".deeplinkerp-main-lane/release/deeplinkerp.com",
				"private_gid": 1001,
			}
			lane.DDLReceipt.create(
				root / "main-seal.json",
				{"candidate_sha": "a" * 40, "contract_sha256": "b" * 64},
				{},
				contract,
			)
			(root / "main.compose.json").write_text(
				json.dumps(
					lane.lane_compose(
						contract["image_id"],
						contract["redis_image_id"],
						str(root),
						contract["subpath"],
						private_gid=1001,
					)
				)
			)
			(root / "main-sites").mkdir()
			(root / "main-sites/assets").symlink_to(lane.BENCH + "/assets")
			binding = patch.object(
				lane, "runtime_access", return_value={"private_gid": 1001, "host_uid": os.getuid()}
			)
			binding.start()
			self.addCleanup(binding.stop)
			command = lane.runner_command(
				root,
				"/frozen/build",
				"sha256:" + "a" * 64,
				lane.BENCH + "/env/bin/python",
				["/release/deploy/production/audit_unified_purchase.py"],
				"a" * 40,
			)
			self.assertEqual(command[command.index("--group-add") + 1], "1001")
			mounts = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--mount"]
			self.assertTrue(
				any(
					"volume-subpath=.deeplinkerp-main-lane/release/deeplinkerp.com" in mount
					for mount in mounts
				)
			)
			self.assertFalse(any("volume-subpath=assets" in mount for mount in mounts))
			self.assertIn("DEEPLINKERP_MAIN_SEAL_RECEIPT=/release-evidence/main-seal.json", command)
			self.assertNotIn("DEEPLINKERP_RELEASE_QUIESCENT=1", command)
			with self.assertRaisesRegex(AssertionError, "image|identity"):
				lane.runner_command(
					root, "/frozen/build", "unapproved-image", lane.BENCH + "/env/bin/python", [], "a" * 40
				)

	def test_main_route_records_intent_before_nginx_and_never_recreates_shared_frontend(self):
		lane = self.module()
		self.assertTrue(hasattr(lane, "install_route"), "Durable main route install is missing")
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			compose = root / "compose.custom.yaml"
			source = b"services:\n  frontend:\n    image: old\n    volumes:\n      - sites:/home/frappe/frappe-bench/sites\n"
			compose.write_bytes(source)
			route = root / "private/main-routes/deeplinkerp-main.conf"
			receipt = lane.DDLReceipt.create(
				root / "seal.json",
				{"candidate_sha": "a" * 40, "contract_sha256": "b" * 64},
				{"compose": base64.b64encode(source).decode()},
				{"route_path": str(route), "compose_path": str(compose)},
			)
			calls = []

			def command(argv, **kwargs):
				calls.append(argv)
				self.assertEqual(lane.DDLReceipt.load(receipt.path).state["steps"][-1]["status"], "pending")
				if "nginx" in argv and "-t" in argv:
					raise RuntimeError("invalid nginx config")
				return ""

			with patch.object(lane, "host_call", side_effect=command):
				with self.assertRaises(RuntimeError):
					lane.install_route(receipt, maintenance=True, first=True)
			self.assertIn("server_name deeplinkerp.com;", route.read_text())
			self.assertEqual(
				route.stat().st_mode & 0o777,
				0o644,
				"Non-secret Nginx route must be readable by the unchanged frontend UID",
			)
			self.assertEqual(
				compose.read_bytes().replace(
					("      - " + json.dumps(str(route) + ":" + lane.ROUTE_TARGET + ":ro") + "\n").encode(),
					b"",
				),
				source,
			)
			self.assertEqual(lane.DDLReceipt.load(receipt.path).state["steps"][-1]["status"], "pending")
			self.assertFalse(
				any("restart" in argv or ("compose" in argv and "config" not in argv) for argv in calls)
			)
			self.assertFalse(any("reload" in argv for argv in calls))

	def test_main_queue_persists_accepted_jobs_and_cache_remains_separate(self):
		lane = self.module()
		model = lane.lane_compose(
			"sha256:" + "a" * 64,
			"sha256:" + "b" * 64,
			"/private/release",
			".deeplinkerp-main-lane/release/deeplinkerp.com",
		)
		queue = model["services"]["main-redis-queue"]
		self.assertEqual(queue["command"][queue["command"].index("--appendonly") + 1], "yes")
		self.assertIn("noeviction", queue["command"])
		self.assertEqual(queue["volumes"], [{"type": "volume", "source": "main-rq", "target": "/data"}])
		self.assertEqual(model["volumes"]["main-rq"]["name"], "deeplinkerp_main_rq")
		self.assertNotIn("volumes", model["services"]["main-redis-cache"])

	def test_private_maintenance_write_retains_the_bind_inode_and_records_intent(self):
		lane = self.module()
		self.assertTrue(hasattr(lane, "private_maintenance"), "Stable private config update is missing")
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			config = root / "main-site-config.json"
			config.write_text('{"db_user":"new","db_password":"private","maintenance_mode":1}')
			inode = config.stat().st_ino
			receipt = lane.DDLReceipt.create(
				root / "seal.json", {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}, {}, {}
			)
			lane.private_maintenance(receipt, root, enable=False)
			self.assertEqual(config.stat().st_ino, inode)
			self.assertEqual(
				json.loads(config.read_bytes()),
				{"db_user": "new", "db_password": "private", "maintenance_mode": 0},
			)
			self.assertEqual(lane.DDLReceipt.load(receipt.path).state["steps"][-1]["status"], "complete")

	def test_forward_hold_pauses_only_the_existing_main_source_timer(self):
		lane = self.module()
		for failure in (
			None,
			"compose-drift",
			"cp",
			"nginx-test",
			"nginx-reload",
			"private-config",
			"source-timer",
		):
			with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
				root = Path(tmp)
				compose = root / "compose.custom.yaml"
				route = root / "main.conf"
				source = b"services:\n  frontend:\n    image: old\n    volumes:\n      - sites:/home/frappe/frappe-bench/sites\n"
				changed = lane.frontend_bind(source, str(route) + ":" + lane.ROUTE_TARGET + ":ro")
				actual = changed + (b"# newer owner's bytes\n" if failure == "compose-drift" else b"")
				compose.write_bytes(actual)
				route.write_text(lane.main_route(maintenance=False))
				lane.DDLReceipt.create(
					root / "main-seal.json",
					{"candidate_sha": "a" * 40, "contract_sha256": "b" * 64},
					{"compose": base64.b64encode(source).decode()},
					{"route_path": str(route), "compose_path": str(compose)},
				)
				config = root / "main-site-config.json"
				config.write_text("{" if failure == "private-config" else '{"maintenance_mode":0}')
				calls = []

				def command(argv, **kwargs):
					calls.append(argv)
					failed = (
						(failure == "cp" and argv[:2] == ["docker", "cp"])
						or (failure == "nginx-test" and "-t" in argv)
						or (failure == "nginx-reload" and "reload" in argv)
						or (failure == "source-timer" and argv[0] == "systemctl")
					)
					return types.SimpleNamespace(returncode=int(failed), stdout="")

				# Real install_route/private_maintenance/host_call: only the
				# external subprocess boundary is replaced, never live hosts.
				with patch.object(lane.subprocess, "run", side_effect=command):
					if failure:
						with self.assertRaises(Exception) as error:
							lane.hold(root)
					else:
						self.assertEqual(
							lane.hold(root), {"main_maintenance": True, "forward_only_after_resume": True}
						)
				if failure != "private-config":
					self.assertEqual(json.loads(config.read_bytes())["maintenance_mode"], 1)
				self.assertEqual(
					[argv for argv in calls if argv[0] == "systemctl"],
					[["systemctl", "--user", "stop", "deeplinkerp-source-sync.timer"]],
				)
				self.assertEqual(compose.read_bytes(), actual)
				if failure == "compose-drift":
					self.assertEqual(route.read_text(), lane.main_route(maintenance=False))
				report_path = root / "main-hold-attempt.json"
				self.assertTrue(report_path.is_file(), "HOLD attempt result must be durably reported")
				report = json.loads(report_path.read_bytes())
				self.assertEqual(report["confirmed"], failure is None)
				if failure:
					self.assertIn("HOLD unconfirmed", str(error.exception))
					expected = (
						"private-maintenance"
						if failure == "private-config"
						else "source-timer"
						if failure == "source-timer"
						else "route"
					)
					self.assertEqual(report["failed_actions"], [expected])
		function = (
			(ROOT / "deploy/production/deploy_unified_purchase.sh")
			.read_text()
			.split("recover_main_only() {", 1)[1]
			.split("\n}\nrun_main_only_release()", 1)[0]
		)
		for phase in ("post-writer", "restore-failure"):
			for hold_ok in (False, True):
				with self.subTest(phase=phase, hold_ok=hold_ok), tempfile.TemporaryDirectory() as tmp:
					(Path(tmp) / "main-seal.json").write_text("{}")
					script = (
						"release_dir=$1\nmetadata_started=0\nsource_sync_timer_active=0\nrecover_main_only() {"
						+ function
						+ "\n}\n"
					)
					script += (
						'main_lane() { case "$1" in boundary-pre-resume) return '
						+ ("1" if phase == "post-writer" else "0")
						+ ";; hold) return "
						+ ("0" if hold_ok else "1")
						+ ";; restore) return 1;; esac; }\ntrap recover_main_only EXIT\nexit 23\n"
					)
					result = subprocess.run(
						["bash", "-c", script, "main-hold-test", tmp], capture_output=True, text=True
					)
					self.assertEqual(result.returncode, 23)
					if hold_ok:
						self.assertIn("maintenance HOLD", result.stderr)
					else:
						self.assertIn("HOLD UNCONFIRMED", result.stderr)
						self.assertNotIn("maintenance HOLD", result.stderr)

	def test_main_service_names_cannot_add_old_three_site_dns_aliases(self):
		lane = self.module()
		model = lane.lane_compose(
			"sha256:" + "a" * 64,
			"sha256:" + "b" * 64,
			"/private/release",
			".deeplinkerp-main-lane/release/deeplinkerp.com",
		)
		self.assertTrue(
			all(name.startswith("main-") for name in model["services"]),
			"Compose adds service names as DNS aliases on the shared network",
		)
		self.assertFalse(
			set(model["services"]) & {"backend", "frontend", "websocket", "redis-queue", "redis-cache"}
		)
		if shutil.which("docker"):
			parsed = subprocess.run(
				["docker", "compose", "-f", "-", "config", "--format", "json"],
				input=json.dumps(model),
				capture_output=True,
				text=True,
			)
			self.assertEqual(parsed.returncode, 0, parsed.stderr)
			actual = json.loads(parsed.stdout)
			self.assertEqual(set(actual["services"]), set(model["services"]))
			self.assertTrue(
				all(value["networks"] == {"default": None} for value in actual["services"].values())
			)

	def test_health_rejects_private_route_model_or_original_auth_drift(self):
		lane = self.module()
		for drift in (None, "route", "private-config", "compose-model", "old-auth", "asset-alias"):
			with self.subTest(drift=drift), tempfile.TemporaryDirectory() as tmp:
				root = Path(tmp)
				image = "sha256:" + "a" * 64
				redis_image = "sha256:" + "b" * 64
				source = b"services:\n  frontend:\n    image: old\n    volumes:\n      - sites:/home/frappe/frappe-bench/sites\n"
				route, compose = root / "route.conf", root / "compose.custom.yaml"
				config = {
					"db_name": "main_db",
					"db_user": "new_main",
					"db_password": "private",
					"maintenance_mode": 1,
				}
				contract = {
					"image_id": image,
					"redis_image_id": redis_image,
					"base_image": "sha256:" + "c" * 64,
					"subpath": ".deeplinkerp-main-lane/" + root.name + "/deeplinkerp.com",
					"route_path": str(route),
					"compose_path": str(compose),
					"candidate_sha": "a" * 40,
					"old_user": "old_main",
					"new_user": "new_main",
					"database": "main_db",
					"original_hosts": ["%"],
					"private_gid": os.getgid(),
				}
				baseline = {service: {"id": service} for service in lane.RELEASE_SERVICES}
				old_account = {"user": "old_main", "host": "%", "priv": {"authentication_string": "original"}}
				receipt = lane.DDLReceipt.create(
					root / "main-seal.json",
					{"candidate_sha": "a" * 40, "contract_sha256": "b" * 64},
					{
						"compose": base64.b64encode(source).decode(),
						"private_config": config,
						"containers": baseline,
						"accounts": [old_account],
					},
					contract,
				)
				receipt.finish({})
				metadata = lane.DDLReceipt.create(
					root / "joint-receipt.json",
					{"candidate_sha": "a" * 40, "contract_sha256": "b" * 64},
					{},
					{},
				)
				metadata.finish({})
				model = lane.lane_compose(image, redis_image, root, contract["subpath"])
				if drift == "compose-model":
					model["services"]["main-backend"]["image"] = "unapproved"
				(root / "main.compose.json").write_text(json.dumps(model))
				(root / "main-sites").mkdir()
				(root / "main-sites/assets").symlink_to(
					"/unreviewed/assets" if drift == "asset-alias" else lane.BENCH + "/assets"
				)
				route.write_text("drift" if drift == "route" else lane.main_route(maintenance=False))
				compose.write_bytes(lane.frontend_bind(source, str(route) + ":" + lane.ROUTE_TARGET + ":ro"))
				(root / "main-site-config.json").write_text(
					json.dumps({**config, "maintenance_mode": int(drift == "private-config")})
				)
				locked = {**old_account, "priv": {**old_account["priv"], "account_locked": True}}
				if drift == "old-auth":
					locked["priv"]["authentication_string"] = "changed"
				new_account = {
					"user": "new_main",
					"host": "%",
					"priv": {},
					"grants": [
						"GRANT USAGE ON *.* TO `new_main`@`%`",
						"GRANT ALL PRIVILEGES ON `main_db`.* TO `new_main`@`%`",
					],
				}

				def inspected(name):
					if name.startswith("frappe_docker-"):
						return {"logical": name.removeprefix("frappe_docker-").removesuffix("-1")}
					value = next(
						service for service in model["services"].values() if service["container_name"] == name
					)
					return {"Image": value["image"], "State": {"Running": True}}

				def call(argv, **kwargs):
					if "redis-cli" in argv:
						return "PONG" if "PING" in argv else "aof_enabled:1\naof_last_write_status:ok"
					if lane.ROUTE_TARGET in argv:
						return lane.main_route(maintenance=False)
					return "pong"

				with (
					patch.object(lane, "inspect", side_effect=inspected),
					patch.object(
						lane, "container_identity", side_effect=lambda value: baseline[value["logical"]]
					),
					patch.object(lane, "host_call", side_effect=call),
					patch.object(
						lane,
						"account_snapshot",
						side_effect=lambda user: [locked] if user == "old_main" else [new_account],
					),
					patch.object(lane, "sessions", return_value=0),
					patch.object(lane, "db_call", return_value="0"),
					patch.object(
						lane,
						"volume_call",
						return_value={
							"discovered_sites": sorted(lane.SHARED_SITES[1:]),
							"maintenance_mode": 1,
						},
					),
				):
					if drift:
						with self.assertRaises(AssertionError):
							lane.health(root, root)
					else:
						self.assertTrue(lane.health(root, root)["main_running"])

	def test_pre_resume_restore_handles_unattempted_partial_route_and_preserves_external_drift(self):
		lane = self.module()
		for phase in ("before-route", "intent-only", "route-file", "future-bind", "external-drift"):
			with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
				root = Path(tmp)
				route = root / "route.conf"
				compose = root / "compose.custom.yaml"
				source = b"# owner's dirty bytes\nservices:\n  frontend:\n    image: old\n    volumes:\n      - sites:/home/frappe/frappe-bench/sites\n"
				changed = lane.frontend_bind(source, str(route) + ":" + lane.ROUTE_TARGET + ":ro")
				compose.write_bytes(changed if phase == "future-bind" else source)
				if phase == "external-drift":
					compose.write_bytes(source + b"# newer owner change\n")
				if phase in {"route-file", "future-bind"}:
					route.write_text(lane.main_route(maintenance=True))
				account = {
					"user": "old_main",
					"host": "%",
					"priv": {"authentication_string": "original"},
					"grants": ["original"],
				}
				baseline = {service: {"id": service} for service in lane.RELEASE_SERVICES}
				receipt = lane.DDLReceipt.create(
					root / "main-seal.json",
					{"candidate_sha": "a" * 40, "contract_sha256": "b" * 64},
					{
						"compose": base64.b64encode(source).decode(),
						"accounts": [account],
						"containers": baseline,
					},
					{
						"compose_path": str(compose),
						"route_path": str(route),
						"base_image": "sha256:" + "c" * 64,
						"new_user": "new_main",
						"old_user": "old_main",
						"subpath": ".deeplinkerp-main-lane/release/deeplinkerp.com",
					},
				)
				if phase != "before-route":
					receipt.plan(
						"route-maintenance-first", {"route": None}, {"route": "maintenance"}, kind="route"
					)
				events = []
				calls = []

				def image(*args, **kwargs):
					events.append(args[2])
					return {"pre_resume": True}

				def volume(*args):
					events.append("restore-volume")
					return {}

				def sql(query):
					events.append("restore-auth")
					return ""

				def command(argv, **kwargs):
					calls.append(argv)
					return ""

				with (
					patch.object(lane, "image_call", side_effect=image),
					patch.object(lane, "volume_call", side_effect=volume),
					patch.object(lane, "db_call", side_effect=sql),
					patch.object(
						lane,
						"account_snapshot",
						side_effect=lambda user: [] if user == "new_main" else [account],
					),
					patch.object(lane, "host_call", side_effect=command),
					patch.object(
						lane,
						"inspect",
						side_effect=lambda name: {
							"logical": name.removeprefix("frappe_docker-").removesuffix("-1")
						},
					),
					patch.object(
						lane, "container_identity", side_effect=lambda value: baseline[value["logical"]]
					),
				):
					if phase == "external-drift":
						with self.assertRaisesRegex(AssertionError, "Compose|drift"):
							lane.restore(root, root)
						self.assertEqual(compose.read_bytes(), source + b"# newer owner change\n")
						self.assertNotIn("old-resume", events)
						self.assertNotIn("restore-volume", events)
					else:
						lane.restore(root, root)
						self.assertEqual(compose.read_bytes(), source)
						self.assertFalse(route.exists())
						self.assertLess(events.index("old-resume"), events.index("restore-volume"))
						self.assertLess(events.index("old-resume"), events.index("restore-auth"))
						self.assertEqual(
							any("rm" in argv for argv in calls), phase in {"route-file", "future-bind"}
						)

	def test_actual_private_receipt_bytes_must_fit_the_reserved_budget_before_resume(self):
		lane = self.module()
		self.assertTrue(hasattr(lane, "receipt_budget"), "Actual receipt budget enforcement missing")
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "space-budget.json").write_text('{"receipt_limit_bytes": 1000}')
			lane.DDLReceipt.create(
				root / "main-seal.json",
				{"candidate_sha": "a" * 40, "contract_sha256": "b" * 64},
				{},
				{"base_image": "frozen", "subpath": ".deeplinkerp-main-lane/release/deeplinkerp.com"},
			)
			with patch.object(lane, "image_call", return_value={"native_receipt_bytes": 100}):
				(root / "main-sites").mkdir()
				alias = root / "main-sites/assets"
				alias.symlink_to(lane.BENCH + "/assets")
				self.assertLess(lane.receipt_budget(root, root)["observed_receipt_bytes"], 1000)
				for path, target in (
					(root / "unexpected-link", lane.BENCH + "/assets"),
					(alias, "/unreviewed/assets"),
				):
					if path.is_symlink():
						path.unlink()
					path.symlink_to(target)
					with (
						self.subTest(path=path, target=target),
						self.assertRaisesRegex(AssertionError, "storage|alias"),
					):
						lane.receipt_budget(root, root)
					path.unlink()
				alias.symlink_to(lane.BENCH + "/assets")
				(root / "oversized-audit.json").write_bytes(b"a" * 1000)
				with self.assertRaisesRegex(AssertionError, "receipt|budget"):
					lane.receipt_budget(root, root)

	@unittest.skipUnless(
		os.environ.get("DEEPLINKERP_MAIN_LANE_DOCKER_QA") == "1", "Explicit owned local Docker QA only"
	)
	def test_owned_docker_asset_root_alias_avoids_host_subpath_resolution(self):
		lane = self.module()

		def docker(*argv):
			return subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=30)

		self.assertEqual(docker("context", "show").stdout.strip(), "desktop-linux")
		endpoint = docker("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}")
		self.assertEqual(json.loads(endpoint.stdout), "unix:///Users/smk/.docker/run/docker.sock")
		image = os.environ.get(
			"DEEPLINKERP_MAIN_LANE_QA_IMAGE",
			"sha256:07b192aca907fe5880a8817077896c1b32307679c08ba858f62de49c4b23aebe",
		)
		volume = "deeplinkerp-owned-assets-qa-" + uuid.uuid4().hex
		container = volume + "-failed-probe"
		created = docker("volume", "create", "--label", "org.deeplinkerp.qa=asset-root-alias", volume)
		self.assertEqual(created.returncode, 0, created.stderr)
		try:
			initialized = docker(
				"run",
				"--rm",
				"--read-only",
				"--network",
				"none",
				"--user",
				"0",
				"--mount",
				"type=volume,source=" + volume + ",target=/fixture-sites",
				"--entrypoint",
				lane.BENCH + "/env/bin/python",
				image,
				"-c",
				"from pathlib import Path;Path('/fixture-sites/assets').symlink_to('/home/frappe/frappe-bench/assets')",
			)
			self.assertEqual(initialized.returncode, 0, initialized.stderr)
			broken = docker(
				"run",
				"--rm",
				"--name",
				container,
				"--read-only",
				"--network",
				"none",
				"--mount",
				"type=volume,source=" + volume + ",volume-subpath=assets,target=/proof,readonly",
				"--entrypoint",
				lane.BENCH + "/env/bin/python",
				image,
				"-c",
				"pass",
			)
			self.assertNotEqual(broken.returncode, 0, "Docker must reproduce the host-resolved alias failure")
			self.assertIn("no such file or directory", broken.stderr)
			with patch.object(lane, "SITES_VOLUME", volume):
				try:
					proof = lane.image_call(image, ROOT, "assets", assets_only=True)
				except RuntimeError:
					self.fail("Image-only asset proof still tries the invalid shared volume alias subpath")
			self.assertTrue(proof["manifest_bodies"])
			with tempfile.TemporaryDirectory() as tmp:
				root = Path(tmp)
				volume_state = {
					"common": base64.b64encode(b"{}").decode(),
					"apps": base64.b64encode(b"frappe\n").decode(),
					"assets_link": lane.BENCH + "/assets",
				}
				lane.private_roots(root, volume_state, {})
				resolved = docker(
					"run",
					"--rm",
					"--read-only",
					"--network",
					"none",
					"--group-add",
					str(os.getgid()),
					"--mount",
					"type=bind,source="
					+ str((root / "main-sites").resolve())
					+ ",target="
					+ lane.BENCH
					+ "/sites,readonly",
					"--entrypoint",
					lane.BENCH + "/env/bin/python",
					image,
					"-c",
					"import hashlib;from pathlib import Path;b=Path('/home/frappe/frappe-bench');assert (b/'sites/assets').resolve()==b/'assets';print(hashlib.sha256((b/'sites/assets/assets.json').read_bytes()).hexdigest())",
				)
				self.assertEqual(resolved.returncode, 0, resolved.stderr)
				self.assertEqual(resolved.stdout.strip(), proof["manifest_sha256"])
		finally:
			docker("rm", "--force", container)
			removed = docker("volume", "rm", volume)
			self.assertEqual(removed.returncode, 0, removed.stderr)
		self.assertNotEqual(docker("volume", "inspect", volume).returncode, 0)

	@unittest.skipUnless(
		os.environ.get("DEEPLINKERP_MAIN_LANE_DOCKER_QA") == "1", "Explicit owned local Docker QA only"
	)
	def test_owned_linux_cross_uid_private_inputs_and_serving_permissions(self):
		context = subprocess.run(["docker", "context", "show"], capture_output=True, text=True, check=True)
		self.assertEqual(context.stdout.strip(), "desktop-linux")
		endpoint = subprocess.run(
			["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"],
			capture_output=True,
			text=True,
			check=True,
		)
		self.assertEqual(json.loads(endpoint.stdout), "unix:///Users/smk/.docker/run/docker.sock")
		image = os.environ.get(
			"DEEPLINKERP_MAIN_LANE_QA_IMAGE",
			"sha256:07b192aca907fe5880a8817077896c1b32307679c08ba858f62de49c4b23aebe",
		)
		code = r"""
import base64,json,os,subprocess,sys,tempfile
from pathlib import Path
Path('/etc/passwd').write_text('root:x:0:0::/root:/bin/sh\nfrappe:x:1000:1000::/tmp:/bin/sh\nrelease:x:1001:1001::/tmp:/bin/sh\nintruder:x:1002:1002::/tmp:/bin/sh\n')
Path('/etc/group').write_text('root:x:0:\nfrappe:x:1000:\nrelease:x:1001:\nintruder:x:1002:\n')
assert 1001 in os.getgroups(), 'Actual Docker supplemental group missing'
sys.path.insert(0,'/release-tools')
root=Path(tempfile.mkdtemp(prefix='private-uid-proof.'))
os.chown(root,1001,1001);os.chmod(root,0o700)
private=root/'before.json';private.write_text('{"private":"fixture"}')
os.chown(private,1001,1001);os.chmod(private,0o600)
prefix="import os,sys,json,base64;from pathlib import Path;sys.path.insert(0,'/release-tools');import main_site_lane as lane;root=Path("+repr(str(root))+");"
def child(uid,gid,groups,source,expected=0):
 def identity():
  os.setgroups(groups);os.setgid(gid);os.setuid(uid)
 result=subprocess.run([sys.executable,'-c',prefix+source],capture_output=True,text=True,preexec_fn=identity)
 assert result.returncode==expected,(uid,gid,groups,result.returncode,result.stderr)
 return result
read="assert json.loads((root/'before.json').read_bytes())['private']=='fixture'"
child(1000,1000,[1001],read,1)
child(1001,1001,[],"[(root/name).write_bytes((Path('/release-tools')/name).read_bytes()) for name in ('main_site_lane.py','joint_release_guards.py')];lane.runtime_access(root);lane.private_roots(root,{'common':base64.b64encode(b'{}').decode(),'apps':base64.b64encode(b'frappe\\nerpnext\\n').decode(),'assets_link':lane.BENCH+'/assets'},{'db_password':'fixture','maintenance_mode':1})")
assert private.stat().st_uid==1001 and private.stat().st_gid==1001 and private.stat().st_mode&0o777==0o640
assert root.stat().st_mode&0o777==0o750
child(1000,1000,[1001],read+";assert (root/'main-sites/apps.txt').read_bytes()==b'frappe\\nerpnext\\n';assert (root/'main_site_lane.py').read_bytes();assert (root/'joint_release_guards.py').read_bytes();assert json.loads((root/'main-sites/common_site_config.json').read_bytes());assert json.loads((root/'main-site-config.json').read_bytes())['maintenance_mode']==1;os.umask(0o007);(root/'main-sites/logs/runtime.log').write_text('fixture')")
child(1000,1000,[1001],"(root/'main-site-config.json').write_text('{}')",1)
for uid,gid,groups in ((1000,1000,[]),(1002,1002,[])):
 child(uid,gid,groups,read,1)
config=root/'main-site-config.json';inode=config.stat().st_ino
child(1001,1001,[],"receipt=lane.DDLReceipt.create(root/'seal.json',{'candidate_sha':'a'*40,'contract_sha256':'b'*64},{},{});lane.private_maintenance(receipt,root,enable=False);assert (root/'main-sites/logs/runtime.log').read_text()=='fixture';lane.DDLReceipt(root/'before.json',{})._write(b'{\"private\":\"fixture\"}')")
assert config.stat().st_ino==inode
child(1000,1000,[1001],read,1)
child(1001,1001,[],"lane.runtime_access(root)")
child(1000,1000,[1001],read+";assert json.loads((root/'main-site-config.json').read_bytes())['maintenance_mode']==0")
Path('/etc/group').write_text('root:x:0:\nfrappe:x:1000:\nrelease:x:1001:intruder\nintruder:x:1002:\n')
failed=child(1001,1001,[],"sys.argv=['main_site_lane','runtime-access','--evidence',str(root)];sys.exit(lane.main())",1)
report=json.loads(failed.stderr)
assert report['outcome']=='PRIVATE_ACCESS_FAILED' and report['host_uid']==1001 and report['private_gid']==1001
assert (root/'private-access-failure.json').stat().st_mode&0o777==0o600
assert not (root/'main-seal.json').exists()
print('UID 1001 host / UID 1000 runtime: private read, denied write/unauthorized read, setgid logs, stable config, refreshed receipt and failure report verified')
"""
		result = subprocess.run(
			[
				"docker",
				"run",
				"--rm",
				"-i",
				"--read-only",
				"--network",
				"none",
				"--user",
				"0",
				"--group-add",
				"1001",
				"--tmpfs",
				"/tmp",
				"--tmpfs",
				"/etc",
				"--mount",
				"type=bind,source=" + str(ROOT / "deploy/production") + ",target=/release-tools,readonly",
				"--entrypoint",
				"/home/frappe/frappe-bench/env/bin/python",
				image,
				"-",
			],
			input=code,
			capture_output=True,
			text=True,
			timeout=45,
		)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("UID 1001 host / UID 1000 runtime", result.stdout)

	@unittest.skipUnless(
		os.environ.get("DEEPLINKERP_MAIN_LANE_DOCKER_QA") == "1", "Explicit owned local Docker QA only"
	)
	def test_owned_docker_queue_restart_and_namespaced_dns(self):
		lane = self.module()

		def docker(*argv, data=None):
			result = subprocess.run(["docker", *argv], input=data, capture_output=True, text=True, timeout=45)
			self.assertEqual(result.returncode, 0, result.stderr)
			return result.stdout.strip()

		self.assertEqual(docker("context", "show"), "desktop-linux")
		endpoint = json.loads(docker("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"))
		self.assertEqual(
			endpoint, "unix:///Users/smk/.docker/run/docker.sock", "Never run this QA against a remote daemon"
		)
		image = json.loads(docker("image", "inspect", "redis:8.6-alpine"))[0]["Id"]
		project = "dlp-main-lane-qa-" + uuid.uuid4().hex[:12]
		main, old, network, volume = (
			project + "-main-redis-queue-1",
			project + "-redis-queue-1",
			project + "-net",
			project + "-rq",
		)
		self.assertFalse({main, old} & set(docker("ps", "-a", "--format", "{{.Names}}").splitlines()))
		self.assertNotIn(network, docker("network", "ls", "--format", "{{.Name}}").splitlines())
		self.assertNotIn(volume, docker("volume", "ls", "--format", "{{.Name}}").splitlines())
		queue = copy.deepcopy(
			lane.lane_compose("unused", image, "/unused", ".deeplinkerp-main-lane/release/deeplinkerp.com")[
				"services"
			]["main-redis-queue"]
		)
		queue.update(container_name=main, restart="no")
		model = {
			"services": {
				"main-redis-queue": queue,
				"redis-queue": {
					"image": image,
					"container_name": old,
					"command": ["redis-server", "--save", "", "--appendonly", "no"],
				},
			},
			"networks": {"default": {"name": network}},
			"volumes": {"main-rq": {"name": volume}},
		}

		def compose(*argv):
			return docker("compose", "-p", project, "-f", "-", *argv, data=json.dumps(model))

		def redis(container, *argv):
			return docker("exec", container, "redis-cli", "--raw", *argv)

		try:
			compose("up", "-d", "--pull", "never")
			start = time.monotonic()
			while True:
				ping = subprocess.run(
					["docker", "exec", main, "redis-cli", "PING"], capture_output=True, text=True
				)
				if ping.returncode == 0 and ping.stdout.strip() == "PONG":
					break
				self.assertLess(time.monotonic() - start, 20, "Owned Redis did not start")
				time.sleep(0.1)
			self.assertIn("redis_version:8.6.", redis(main, "INFO", "server"))
			redis(main, "SET", "lane-marker", "main")
			redis(old, "SET", "lane-marker", "old")
			self.assertEqual(redis(main, "-h", "main-redis-queue", "GET", "lane-marker"), "main")
			self.assertEqual(redis(main, "-h", "redis-queue", "GET", "lane-marker"), "old")
			aliases = json.loads(docker("inspect", main))[0]["NetworkSettings"]["Networks"][network][
				"Aliases"
			]
			self.assertIn("main-redis-queue", aliases)
			self.assertFalse(
				set(aliases) & {"backend", "frontend", "websocket", "redis-queue", "redis-cache"}
			)
			job = "deeplinkerp.com||accepted-qa"
			redis(main, "SADD", "rq:queues", "rq:queue:bench:short")
			redis(
				main,
				"HSET",
				"rq:job:" + job,
				"status",
				"queued",
				"origin",
				"bench:short",
				"data",
				"accepted-qa-only",
			)
			redis(main, "RPUSH", "rq:queue:bench:short", job)
			compose("stop", "-t", "10", "main-redis-queue")
			compose("start", "main-redis-queue")
			self.assertEqual(redis(main, "LRANGE", "rq:queue:bench:short", "0", "-1"), job)
			self.assertEqual(redis(main, "HGET", "rq:job:" + job, "data"), "accepted-qa-only")
			self.assertIn("aof_enabled:1", redis(main, "INFO", "persistence"))
			self.assertEqual(redis(main, "CONFIG", "GET", "maxmemory-policy"), "maxmemory-policy\nnoeviction")
		finally:
			# Only this just-created UUID project's containers, network and RQ
			# volume; no existing QA volumes/images or general prune.
			compose("down", "--volumes", "--timeout", "10")
			self.assertFalse({main, old} & set(docker("ps", "-a", "--format", "{{.Names}}").splitlines()))
			self.assertNotIn(network, docker("network", "ls", "--format", "{{.Name}}").splitlines())
			self.assertNotIn(volume, docker("volume", "ls", "--format", "{{.Name}}").splitlines())


if __name__ == "__main__":
	unittest.main()
