from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from phone_watch import db
from phone_watch.webapp import PhoneWatchHandler


class InternalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = {key: os.environ.get(key) for key in (
            "PHONE_WATCH_DB_BACKEND", "PHONE_WATCH_INTERNAL_TOKEN", "PHONE_WATCH_LEGACY_API_ENABLED"
        )}
        os.environ["PHONE_WATCH_DB_BACKEND"] = "sqlite"
        os.environ["PHONE_WATCH_INTERNAL_TOKEN"] = "test-service-token"
        os.environ["PHONE_WATCH_LEGACY_API_ENABLED"] = "false"
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)
        with db.connect(self.db_path) as conn:
            for index, seen in enumerate(("2026-10-08T08:00:00+00:00", "2026-10-09T08:00:00+00:00"), start=1):
                db.upsert_phone(conn, {
                    "brand": "HONOR", "country": "MX", "model": f"Honor Test {index}",
                    "normalized_model": f"honortest{index}", "image_url": None, "price": f"MXN {index}999",
                    "release_date": None, "launch_date": None, "source_url": f"https://example.com/{index}",
                    "source_name": "Official MX", "badge": "新品", "first_seen_at": seen, "last_seen_at": seen,
                    "sampling_status": db.DEFAULT_STATUS, "clean_stage": "test",
                })
        PhoneWatchHandler.db_path = str(self.db_path)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PhoneWatchHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.tmpdir.cleanup()
        for key, value in self.before.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value

    def request(self, path: str, method: str = "GET", payload: dict | None = None, token: str | None = "test-service-token"):
        headers = {"Content-Type": "application/json"}
        if token is not None: headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.base_url + path, method=method, headers=headers,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def json_request(self, *args, **kwargs):
        status, _, body = self.request(*args, **kwargs)
        return status, json.loads(body.decode("utf-8"))

    def test_token_is_required_and_legacy_api_is_closed(self) -> None:
        self.assertEqual(self.json_request("/internal/v1/summary", token=None)[0], 401)
        self.assertEqual(self.json_request("/internal/v1/summary", token="wrong")[0], 401)
        self.assertEqual(self.json_request("/api/summary", token=None)[0], 404)

    def test_pagination_filter_detail_and_updates(self) -> None:
        status, page = self.json_request("/internal/v1/items?kind=phone&page=1&size=1&keyword=honor&country=MX")
        self.assertEqual(status, 200); self.assertEqual(page["totalElements"], 2); self.assertEqual(len(page["content"]), 1)
        newest = page["content"][0]
        self.assertEqual(newest["model"], "Honor Test 2"); self.assertEqual(newest["priceCurrency"], "MXN")

        status, updated = self.json_request(
            f"/internal/v1/items/phone/{newest['id']}", method="PATCH",
            payload={"status": "部分开模", "badge": "新品预告", "saleStatus": "未发售"},
        )
        self.assertEqual(status, 200); self.assertEqual(updated["sampling_status"], "部分开模")
        self.assertEqual(updated["badge"], "新品预告"); self.assertEqual(updated["sale_status"], "未发售")

        ids = [item["id"] for item in self.json_request("/internal/v1/items?kind=phone&page=1&size=10")[1]["content"]]
        status, bulk = self.json_request("/internal/v1/items/bulk", method="POST", payload={"kind": "phone", "ids": ids, "status": "已开模"})
        self.assertEqual(status, 200); self.assertEqual(bulk["updated"], 2)

    def test_csv_and_health_are_token_protected(self) -> None:
        self.assertEqual(self.json_request("/internal/v1/health")[1]["status"], "ok")
        status, headers, body = self.request("/internal/v1/export.csv?kind=phone")
        self.assertEqual(status, 200); self.assertIn("text/csv", headers.get("Content-Type")); self.assertIn("Honor Test", body.decode("utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
