"""Byte-preserving host patch and opt-in real nginx maintenance behavior."""

import importlib.util
import json
import os
import ssl
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = b"""server {
    server_name deeplinkerp.com *.deeplinkerp.com;
    # Keep existing operator changes and location order.
    # listen 8443 ssl;
    # server_name other.example;
    location = /api/v1/mes/stock-entries {
        proxy_pass http://127.0.0.1:8888/api/method/mes_integration.api.create_stock_entry;
    }
    location = /api/v1/crm/sales-order {
        if ($request_method != POST) { return 405; }
        proxy_pass http://127.0.0.1:8888/api/method/crm_integration.crm_integration.api.create_and_submit_sales_order;
    }
    location / {
        proxy_pass http://127.0.0.1:8888;
    }
    listen 443 ssl; # managed by Certbot
    ssl_certificate /qa/cert.pem;
    ssl_certificate_key /qa/key.pem;
}

server {
    server_name deeplinkerp.com *.deeplinkerp.com;
    listen 80;
    return 301 https://$host$request_uri;
}
"""


def load_module():
	path = ROOT / "deploy/production/host_maintenance_nginx.py"
	assert path.exists(), "Host maintenance patch helper is missing"
	spec = importlib.util.spec_from_file_location("host_maintenance_nginx", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class HostMaintenancePatchTests(unittest.TestCase):
	def setUp(self):
		self.module = load_module()

	def test_preserves_every_original_byte_and_is_idempotent(self):
		patched = self.module.patch_main_nginx(SOURCE)
		self.assertNotEqual(patched, SOURCE)
		self.assertEqual(
			patched.replace(self.module.HTTP_MAPS, b"", 1).replace(self.module.SERVER_GATE, b"", 1), SOURCE
		)
		self.assertEqual(self.module.patch_main_nginx(patched), patched)

	def test_rejects_unknown_or_ambiguous_target_shapes(self):
		for source in (
			SOURCE + SOURCE,
			SOURCE.replace(b"deeplinkerp.com *.deeplinkerp.com", b"other.com", 1),
			SOURCE.replace(b"listen 443 ssl", b"listen 8443 ssl"),
			SOURCE.replace(b"listen 443 ssl;", b"listen 443 ssl;\n    listen 8443 ssl;"),
			SOURCE.replace(b"listen 443 ssl;", b"# listen 443 ssl;"),
			SOURCE.replace(b"listen 80;", b"# listen 80;"),
			SOURCE.replace(b"listen 80;", b"listen 80;\n    server_name other.example;"),
			SOURCE.replace(b"listen 80;", b"listen 80; server_name other.example;"),
			SOURCE.replace(b"location = /api/v1/mes/stock-entries", b"location /unrelated"),
			SOURCE.replace(b"proxy_pass http://127.0.0.1:8888", b"proxy_pass http://other", 3),
		):
			with self.subTest(source=source), self.assertRaises(ValueError):
				self.module.patch_main_nginx(source)

	def test_rejects_partial_or_modified_previous_installation(self):
		patched = self.module.patch_main_nginx(SOURCE)
		for source in (
			patched.replace(self.module.HTTP_MAPS, b"", 1),
			patched.replace(self.module.SERVER_GATE, b"", 1),
			patched.replace(b"Retry-After 60", b"Retry-After 5", 1),
			patched + self.module.SERVER_GATE,
		):
			with self.subTest(source=source), self.assertRaises(ValueError):
				self.module.patch_main_nginx(source)


@unittest.skipUnless(
	os.environ.get("DEEPLINKERP_NGINX_TEST_IMAGE"),
	"Set DEEPLINKERP_NGINX_TEST_IMAGE to an existing local nginx image",
)
class RealNginxMaintenanceTests(unittest.TestCase):
	def test_all_paths_hosts_content_types_and_recovery(self):
		module = load_module()
		image = os.environ["DEEPLINKERP_NGINX_TEST_IMAGE"]
		subprocess.run(["docker", "image", "inspect", image], check=True, capture_output=True)
		name = "dlp-maintenance-test-" + uuid.uuid4().hex[:12]
		with tempfile.TemporaryDirectory() as directory:
			base = Path(directory)
			frontend = (
				module.patch_main_nginx(SOURCE)
				.replace(b"listen 443 ssl", b"listen 8080 ssl")
				.replace(b"listen 80;", b"listen 8081;")
				.replace(b"127.0.0.1:8888", b"127.0.0.1:8082")
			)
			(base / "frontend.conf").write_bytes(
				b"pid /qa/frontend.pid;\nevents {}\nhttp {\n" + frontend + b"}\n"
			)
			(base / "upstream.conf").write_text("""pid /qa/upstream.pid;
events {}
http { server {
    listen 8082;
    location / { return 200 "upstream"; }
    location = /api/method/mes_integration.api.create_stock_entry {
        return 200 "stock-entry $request_method";
    }
    location = /api/method/crm_integration.crm_integration.api.create_and_submit_sales_order {
        return 200 "sales-order $request_method";
    }
    location = /fail { return 500 "real upstream failure"; }
    location = /unavailable { return 503 "real upstream unavailable"; }
} }
""")
			try:
				subprocess.run(
					[
						"docker",
						"run",
						"-d",
						"--name",
						name,
						"--platform",
						"linux/amd64",
						"--pull",
						"never",
						"--user",
						"0",
						"-p",
						"127.0.0.1::8080",
						"-v",
						f"{base}:/qa",
						"--entrypoint",
						"/bin/sh",
						image,
						"-c",
						"openssl req -x509 -newkey rsa:2048 -nodes -keyout /qa/key.pem -out /qa/cert.pem -days 1 -subj /CN=deeplinkerp.com >/dev/null 2>&1 && nginx -t -c /qa/frontend.conf && nginx -c /qa/upstream.conf && exec nginx -c /qa/frontend.conf -g 'daemon off;'",
					],
					check=True,
					capture_output=True,
				)
				port = (
					subprocess.run(
						["docker", "port", name, "8080/tcp"], check=True, capture_output=True, text=True
					)
					.stdout.strip()
					.rsplit(":", 1)[1]
				)

				def request(path, method="GET", host="deeplinkerp.com", accept="application/json"):
					req = urllib.request.Request(
						f"https://127.0.0.1:{port}{path}",
						data=b"{}" if method == "POST" else None,
						method=method,
						headers={"Host": host, "Accept": accept},
					)
					try:
						response = urllib.request.urlopen(
							req, context=ssl._create_unverified_context(), timeout=3
						)
					except urllib.error.HTTPError as error:
						response = error
					with response:
						return response.status, response.headers, response.read()

				for _attempt in range(40):
					try:
						self.assertEqual(request("/")[0], 200)
						break
					except urllib.error.URLError:
						time.sleep(0.1)
				else:
					self.fail(subprocess.run(["docker", "logs", name], capture_output=True, text=True).stderr)

				self.assertEqual(request("/fail")[::2], (500, b"real upstream failure"))
				self.assertEqual(request("/unavailable")[::2], (503, b"real upstream unavailable"))
				subprocess.run(
					["docker", "exec", name, "touch", module.MARKER], check=True, capture_output=True
				)
				for path in (
					"/",
					"/api/v1/mes/stock-entries",
					"/api/v1/crm/sales-order",
					"/assets/app.js",
					"/files/a.pdf",
					"/socket.io/?transport=polling",
				):
					for method in ("GET", "POST"):
						with self.subTest(path=path, method=method):
							status, headers, body = request(path, method)
							self.assertEqual(status, 503)
							self.assertEqual(headers["Retry-After"], "60")
							self.assertEqual(headers["Cache-Control"], "no-store")
							self.assertTrue(headers["Content-Type"].startswith("application/json"))
							payload = json.loads(body)
							self.assertEqual(payload["exc_type"], "SessionStopped")
							messages = [json.loads(item) for item in json.loads(payload["_server_messages"])]
							self.assertEqual(messages[0]["message"], module.MESSAGE)
				status, headers, body = request("/desk", accept="text/html,application/xhtml+xml")
				self.assertEqual(status, 503)
				self.assertEqual(headers["Retry-After"], "60")
				self.assertEqual(headers["Cache-Control"], "no-store")
				self.assertTrue(headers["Content-Type"].startswith("text/html"))
				self.assertIn(module.MESSAGE.encode(), body)
				self.assertNotIn(b"<script", body)
				self.assertNotIn(b"http-equiv", body)
				for host in ("tenant.deeplinkerp.com", "other.example"):
					with self.subTest(host=host):
						self.assertEqual(request("/", host=host)[::2], (200, b"upstream"))
						self.assertEqual(request("/api/v1/crm/sales-order", host=host)[0], 405)
				subprocess.run(
					["docker", "exec", name, "nginx", "-c", "/qa/upstream.conf", "-s", "stop"],
					check=True,
					capture_output=True,
				)
				self.assertEqual(request("/api/v1/crm/sales-order", "POST")[0], 503)
				subprocess.run(
					["docker", "exec", name, "rm", "--", module.MARKER], check=True, capture_output=True
				)
				self.assertEqual(request("/")[0], 502)
				subprocess.run(
					["docker", "exec", name, "nginx", "-c", "/qa/upstream.conf"],
					check=True,
					capture_output=True,
				)
				self.assertEqual(request("/")[::2], (200, b"upstream"))
				for path, method, expected_status, expected_body in (
					("/api/v1/mes/stock-entries", "GET", 200, b"stock-entry GET"),
					("/api/v1/mes/stock-entries", "POST", 200, b"stock-entry POST"),
					("/api/v1/crm/sales-order", "POST", 200, b"sales-order POST"),
					("/api/v1/crm/sales-order", "GET", 405, None),
				):
					with self.subTest(path=path, method=method, marker="off"):
						status, _, body = request(path, method)
						self.assertEqual(status, expected_status)
						if expected_body is not None:
							self.assertEqual(body, expected_body)
				self.assertEqual(request("/fail")[0], 500)
			finally:
				subprocess.run(["docker", "rm", "-f", name], capture_output=True)
