"""Fixed-marker helper contract and opt-in real sudo/installer checks."""

import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).parents[1]
DEPLOY = ROOT / "deploy/production"
HELPER = "deeplinkerp-main-maintenance"
MARKER = "/run/deeplinkerp-main-maintenance.on"
TARGET = "/usr/local/sbin/" + HELPER
SUDOERS = "/etc/sudoers.d/" + HELPER


def source(name):
	path = DEPLOY / name
	assert path.is_file(), f"Missing maintenance control source: {name}"
	return path.read_text()


class MaintenanceControlTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.base = Path(self.temporary.name)
		self.marker = self.base / "maintenance.on"

	def run_helper(self, *args, root=True, env=None):
		# Only the root identity and marker are isolated; there are no production knobs.
		isolated = source(HELPER).replace(MARKER, str(self.marker))
		self.assertIn("/usr/bin/id -u", isolated)
		isolated = isolated.replace("/usr/bin/id -u", f"/usr/bin/printf {0 if root else 1}")
		path = self.base / HELPER
		path.write_text(isolated)
		return subprocess.run(
			["/bin/sh", str(path), *args], capture_output=True, text=True, env=env, timeout=5
		)

	def test_idempotent_state_transitions(self):
		for action, expected in (
			("status", "off"),
			("off", "off"),
			("on", "on"),
			("on", "on"),
			("status", "on"),
			("off", "off"),
			("off", "off"),
		):
			with self.subTest(action=action, expected=expected):
				result = self.run_helper(action)
				self.assertEqual(result.returncode, 0, result.stderr)
				self.assertEqual(result.stdout.strip(), expected)
				self.assertEqual(self.marker.is_file(), expected == "on")
		self.marker.write_text("existing marker")
		before = self.marker.stat().st_mtime_ns
		self.assertEqual(self.run_helper("on").returncode, 0)
		self.assertEqual(self.marker.read_text(), "existing marker")
		self.assertEqual(self.marker.stat().st_mtime_ns, before)

	def test_argument_and_environment_boundaries(self):
		for args in (
			(),
			("on", "off"),
			("status", "extra"),
			("on", "/tmp/other"),
			("status", "MARKER=/tmp/other"),
			("/tmp/other",),
			("--help",),
			("ON",),
			("../status",),
			("status\non",),
			("on;id",),
			("",),
		):
			with self.subTest(args=args):
				self.assertNotEqual(self.run_helper(*args).returncode, 0)
				self.assertFalse(self.marker.exists())
		env = {"PATH": str(self.base), "MARKER": str(self.base / "other"), "SUDO_USER": "yuewei"}
		result = self.run_helper("on", env=env)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertTrue(self.marker.is_file())
		self.assertFalse((self.base / "other").exists())

	def test_root_required_for_helper_and_installer(self):
		for action in ("on", "off", "status"):
			with self.subTest(action=action):
				result = self.run_helper(action, root=False)
				self.assertNotEqual(result.returncode, 0)
				self.assertIn("root", result.stderr)
				self.assertFalse(self.marker.exists())
		installer = source("install_host_maintenance_control.sh")
		self.assertIn("/usr/bin/id -u", installer)
		path = self.base / "installer.sh"
		path.write_text(installer.replace("/usr/bin/id -u", "/usr/bin/printf 1"))
		result = subprocess.run(["/bin/sh", str(path)], capture_output=True, text=True, timeout=5)
		self.assertNotEqual(result.returncode, 0)
		self.assertIn("root", result.stderr)

	def test_abnormal_markers_refused_without_following_or_removing(self):
		victim = self.base / "victim"
		victim.write_text("keep")
		for kind in ("symlink", "dangling", "directory", "fifo"):
			if kind in ("symlink", "dangling"):
				self.marker.symlink_to(victim if kind == "symlink" else self.base / "missing")
			elif kind == "directory":
				self.marker.mkdir()
			else:
				os.mkfifo(self.marker)
			for action in ("on", "off", "status"):
				with self.subTest(kind=kind, action=action):
					result = self.run_helper(action)
					self.assertNotEqual(result.returncode, 0)
					self.assertTrue(os.path.lexists(self.marker))
					self.assertEqual(victim.read_text(), "keep")
			if kind == "directory":
				self.marker.rmdir()
			else:
				self.marker.unlink()

	def test_exact_sudoers_and_existing_ci_contract(self):
		lines = [
			line for line in source(HELPER + ".sudoers").splitlines() if line and not line.startswith("#")
		]
		self.assertEqual(
			lines,
			[
				f"yuewei ALL=(root) NOPASSWD: NOSETENV: {TARGET} {action}"
				for action in ("on", "off", "status")
			],
		)
		self.assertIn("tests.test_host_maintenance_control", (ROOT / ".github/workflows/ci.yml").read_text())


@unittest.skipUnless(
	os.environ.get("DEEPLINKERP_MAINTENANCE_TEST_IMAGE"),
	"Set DEEPLINKERP_MAINTENANCE_TEST_IMAGE to a local Linux image with sudo/visudo",
)
class RealSudoMaintenanceTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.name = "dlp-maintenance-control-test-" + uuid.uuid4().hex[:12]
		cls.docker(
			"run",
			"-d",
			"--name",
			cls.name,
			"--platform",
			"linux/amd64",
			"--pull",
			"never",
			"--network",
			"none",
			"--user",
			"0",
			"--entrypoint",
			"/bin/sh",
			os.environ["DEEPLINKERP_MAINTENANCE_TEST_IMAGE"],
			"-c",
			"exec sleep 600",
		)
		cls.addClassCleanup(cls.docker, "rm", "-f", cls.name)
		cls.command("/usr/sbin/visudo", "-c")
		cls.command("useradd", "-m", "yuewei")
		cls.command("usermod", "-a", "-G", "sudo", "yuewei")

	@staticmethod
	def docker(*args, check=True):
		return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=30)

	@classmethod
	def command(cls, *args, check=True, user="0"):
		return cls.docker("exec", "--user", user, cls.name, *args, check=check)

	def stage(self, installer=None):
		self.command("mkdir", "-p", "/root/maintenance-control")
		for name in (HELPER, HELPER + ".sudoers", "install_host_maintenance_control.sh"):
			source(name)
			if name == "install_host_maintenance_control.sh" and installer is not None:
				with tempfile.TemporaryDirectory() as directory:
					path = Path(directory) / name
					path.write_text(installer)
					self.docker("cp", str(path), self.name + ":/root/maintenance-control/" + name)
			else:
				self.docker("cp", str(DEPLOY / name), self.name + ":/root/maintenance-control/" + name)
		self.command("chown", "-R", "0:0", "/root/maintenance-control")
		self.command("chmod", "-R", "go-w", "/root/maintenance-control")

	def install(self, check=True):
		return self.command(
			"/bin/sh", "/root/maintenance-control/install_host_maintenance_control.sh", check=check
		)

	def remove_owned(self):
		self.command("rm", "-f", TARGET, SUDOERS, MARKER)

	def test_real_sudo_installation_and_privilege_boundaries(self):
		self.addCleanup(self.remove_owned)
		self.stage()
		self.assertNotEqual(
			self.command(
				"/bin/sh",
				"/root/maintenance-control/install_host_maintenance_control.sh",
				"--destination",
				"/tmp/other",
				check=False,
			).returncode,
			0,
		)
		self.assertEqual(self.install().returncode, 0)
		self.assertEqual(self.install().returncode, 0)
		for target, mode in ((TARGET, "755"), (SUDOERS, "440")):
			with self.subTest(target=target):
				self.assertEqual(self.command("stat", "-c", "%u:%g:%a", target).stdout.strip(), "0:0:" + mode)
		self.command("/usr/sbin/visudo", "-c")
		for action, state in (
			("status", "off"),
			("off", "off"),
			("off", "off"),
			("on", "on"),
			("on", "on"),
			("status", "on"),
			("off", "off"),
		):
			with self.subTest(action=action, state=state):
				self.assertEqual(
					self.command("sudo", "-n", TARGET, action, user="yuewei").stdout.strip(), state
				)
		for args in (
			(TARGET,),
			(TARGET, "on", "extra"),
			(TARGET, "/tmp/other"),
			(TARGET, "status", "extra"),
			("/bin/sh",),
			("/bin/rm", MARKER),
			("MARKER=/tmp/other", TARGET, "on"),
			("-E", TARGET, "status"),
			("-u", "nobody", TARGET, "status"),
		):
			with self.subTest(args=args):
				self.assertNotEqual(
					self.command("sudo", "-n", *args, user="yuewei", check=False).returncode, 0
				)
		self.assertNotEqual(self.command(TARGET, "status", user="yuewei", check=False).returncode, 0)
		self.assertNotEqual(self.command("test", "-e", MARKER, check=False).returncode, 0)

	def test_installer_refuses_unexpected_targets_and_on_state(self):
		self.addCleanup(self.remove_owned)
		self.stage()
		for target in (TARGET, SUDOERS):
			with self.subTest(target=target):
				self.command("/bin/sh", "-c", 'printf "%s\\n" keep > "$1"', "sh", target)
				self.assertNotEqual(self.install(check=False).returncode, 0)
				self.assertEqual(self.command("cat", target).stdout, "keep\n")
				self.command("rm", "--", target)
		self.command("touch", MARKER)
		self.assertNotEqual(self.install(check=False).returncode, 0)
		self.command("test", "-f", MARKER)
		self.assertNotEqual(self.command("test", "-e", TARGET, check=False).returncode, 0)

	def test_failed_activation_revokes_only_new_artifacts(self):
		self.addCleanup(self.remove_owned)
		# Inject a real invalid include just before final visudo; it is not installer-owned.
		unrelated = "/etc/sudoers.d/qa-unrelated"
		self.addCleanup(self.command, "rm", "-f", unrelated)
		installer = source("install_host_maintenance_control.sh")
		needle = "/usr/sbin/visudo -c\n"
		self.assertEqual(installer.count(needle), 2)
		before, after = installer.rsplit(needle, 1)
		failure = f"printf '%s\\n' 'invalid sudoers syntax !!!' > {unrelated}\n" + needle
		self.stage(before + failure + after)
		self.assertNotEqual(self.install(check=False).returncode, 0)
		for target in (TARGET, SUDOERS, MARKER):
			with self.subTest(target=target):
				self.assertNotEqual(self.command("test", "-e", target, check=False).returncode, 0)
		self.command("test", "-f", unrelated)
