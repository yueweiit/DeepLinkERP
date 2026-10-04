"""Exercise only the shell recovery function with mocks; never invoke a release."""
from pathlib import Path
import subprocess
import unittest
import hashlib
import runpy
import sys
import tempfile
import types
from unittest.mock import patch


class ReleaseRecoveryTests(unittest.TestCase):
	def source_validator(self, root):
		with patch.dict(sys.modules, {"frappe": types.ModuleType("frappe")}):
			module = runpy.run_path(str(Path(__file__).parents[1] / "deploy/production/audit_unified_purchase.py"))
		module["verify_sources"].__globals__["BENCH"] = root
		return module["verify_sources"]

	def test_release_source_manifest_accepts_expected_new_file_and_version(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp); target = root / "apps/crm_integration/crm_integration/new.py"
			verify = self.source_validator(root)
			manifest = {"apps": {"crm_integration": {"new.py": {"before": None, "after": hashlib.sha256(b"new").hexdigest()}}}}
			verify(manifest, "before")
			target.parent.mkdir(parents=True); target.write_bytes(b"new")
			verify(manifest, "after")

	def test_release_source_manifest_rejects_an_unexpected_running_edit(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp); target = root / "apps/crm_integration/crm_integration/order.py"
			target.parent.mkdir(parents=True); target.write_bytes(b"other task")
			manifest = {"apps": {"crm_integration": {"order.py": {"before": hashlib.sha256(b"baseline").hexdigest(), "after": "candidate"}}}}
			with self.assertRaisesRegex(AssertionError, "Source drift: crm_integration/order.py"):
				self.source_validator(root)(manifest, "before")

	def test_release_source_manifest_rejects_incomplete_candidate_copy(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp); target = root / "apps/deeplinkerp_branding/deeplinkerp_branding/grid.js"
			target.parent.mkdir(parents=True); target.write_bytes(b"old")
			manifest = {"apps": {"deeplinkerp_branding": {"grid.js": {"before": hashlib.sha256(b"old").hexdigest(), "after": hashlib.sha256(b"new").hexdigest()}}}}
			with self.assertRaisesRegex(AssertionError, "Source drift: deeplinkerp_branding/grid.js"):
				self.source_validator(root)(manifest, "after")

	def test_copied_audit_is_readable_despite_private_release_umask(self):
		source = (Path(__file__).parents[1] / "deploy/production/deploy_unified_purchase.sh").read_text()
		permission_fix = 'chmod 644 "$build_dir/deploy/production/audit_unified_purchase.py"'
		self.assertIn(permission_fix, source)
		self.assertLess(source.index(permission_fix), source.index('docker cp "$build_dir/deploy/production/audit_unified_purchase.py"'))

	def run_recovery(self, up_status=0, health_status=0, initial_maintenance_status=0):
		source = (Path(__file__).parents[1] / "deploy/production/deploy_unified_purchase.sh").read_text()
		function = source.split("recover() {", 1)[1].split("\ntrap recover EXIT", 1)[0]
		mock = f"""
dc=(docker compose)
services=(backend frontend queue-long queue-short scheduler websocket)
switched=1
maintenance=1
release_dir=mock
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
    *'set-maintenance-mode on'*)
      maintenance_calls=$((maintenance_calls+1))
      printf 'MAINTENANCE ON\\n'
      if (( maintenance_calls == 1 )); then return {initial_maintenance_status}; fi ;;
    *) printf 'DOCKER %s\\n' "$*" ;;
  esac
}}
curl() {{ printf 'HEALTH\\n'; return {health_status}; }}
recover() {{{function}
false
recover
"""
		return subprocess.run(["bash", "-c", mock], capture_output=True, text=True)

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
