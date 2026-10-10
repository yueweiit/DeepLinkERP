"""Main-only topology/account/route boundaries; never contact a live host."""

import base64
import copy
import hashlib
import importlib.util
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
			assets = next(value for value in mounts if value["target"].endswith("/sites/assets"))
			self.assertTrue(assets["read_only"])
			self.assertEqual(assets["volume"]["subpath"], "assets")
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
			before = lane.site_boundary(root, "snapshot", ".deeplinkerp-main-lane/release/deeplinkerp.com")
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
			assets = bench / "sites/assets"
			assets.mkdir(parents=True)
			public = bench / "apps/deeplinkerp_branding/deeplinkerp_branding/public"
			(public / "dist").mkdir(parents=True)
			(public / "dist/frozen.js").write_bytes(b"compiled")
			(assets / "deeplinkerp_branding").symlink_to(
				"../../apps/deeplinkerp_branding/deeplinkerp_branding/public"
			)
			(assets / "assets.json").write_text('{"bundle.js":"/assets/deeplinkerp_branding/dist/frozen.js"}')
			before = (assets / "assets.json").read_bytes()
			proof = lane.asset_view(bench)
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
						contract["image_id"], contract["redis_image_id"], str(root), contract["subpath"]
					)
				)
			)
			command = lane.runner_command(
				root,
				"/frozen/build",
				"sha256:" + "a" * 64,
				lane.BENCH + "/env/bin/python",
				["/release/deploy/production/audit_unified_purchase.py"],
				"a" * 40,
			)
			mounts = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--mount"]
			self.assertTrue(
				any(
					"volume-subpath=.deeplinkerp-main-lane/release/deeplinkerp.com" in mount
					for mount in mounts
				)
			)
			self.assertTrue(any("volume-subpath=assets" in mount and "readonly" in mount for mount in mounts))
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
		for drift in (None, "route", "private-config", "compose-model", "old-auth"):
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
				self.assertLess(lane.receipt_budget(root, root)["observed_receipt_bytes"], 1000)
				(root / "oversized-audit.json").write_bytes(b"a" * 1000)
				with self.assertRaisesRegex(AssertionError, "receipt|budget"):
					lane.receipt_budget(root, root)

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
