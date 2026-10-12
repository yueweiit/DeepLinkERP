from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from phone_watch import db
from phone_watch.ui import render_app_html
from phone_watch.webapp import PhoneWatchHandler


class FieldDictionaryDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_seed_default_all_managed_fields(self) -> None:
        expected_fields = {
            "brand",
            "sampling_status",
            "badge",
            "sale_status",
            "tipo_status",
            "country",
            "price_currency",
            "price_bucket",
            "manual_model_type",
        }

        self.assertTrue(expected_fields.issubset(db.VALID_MANAGED_FIELDS))
        with db.connect(self.db_path) as conn:
            for field_name in expected_fields:
                rows = db.field_options(conn, field_name, enabled_only=True)
                self.assertGreater(len(rows), 0, field_name)

    def test_upsert_sampling_status_option(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_field_option(
                conn,
                field_name=db.MANAGED_FIELD_SAMPLING_STATUS,
                value="测试状态",
                label="测试状态",
                enabled=True,
            )
            rows = db.field_options(conn, db.MANAGED_FIELD_SAMPLING_STATUS, enabled_only=True)

        self.assertTrue(any(row["value"] == "测试状态" for row in rows))

    def test_delete_field_option_removes_dictionary_row(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_field_option(conn, field_name=db.MANAGED_FIELD_BADGE, value="测试标签", label="测试标签")
            row = next(row for row in db.field_options(conn, db.MANAGED_FIELD_BADGE) if row["value"] == "测试标签")

            deleted = db.delete_field_option(conn, int(row["id"]))
            rows = db.field_options(conn, db.MANAGED_FIELD_BADGE)

        self.assertEqual(deleted, 1)
        self.assertFalse(any(row["value"] == "测试标签" for row in rows))


class FieldDictionaryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)
        PhoneWatchHandler.db_path = str(self.db_path)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PhoneWatchHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def get_json(self, path: str) -> tuple[int, object]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_api_field_options_returns_multiple_fields(self) -> None:
        query = urllib.parse.quote("brand,sampling_status,badge")
        status, body = self.get_json(f"/api/field-options?field_names={query}")

        self.assertEqual(status, 200)
        self.assertIn("brand", body)
        self.assertIn("sampling_status", body)
        self.assertIn("badge", body)
        self.assertTrue(body["brand"])
        self.assertTrue(body["sampling_status"])
        self.assertTrue(body["badge"])

    def test_api_field_options_delete(self) -> None:
        status, body = self.post_json(
            "/api/field-options",
            {"field_name": "badge", "value": "测试标签", "label": "测试标签"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        _, rows = self.get_json("/api/field-options?field_name=badge")
        option = next(row for row in rows if row["value"] == "测试标签")
        status, body = self.post_json("/api/field-options/delete", {"id": option["id"]})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["deleted"], 1)


class FieldDictionaryUiTests(unittest.TestCase):
    def test_dictionary_management_ui_contains_all_field_types(self) -> None:
        html = render_app_html(api_mode=True)

        for field_name in (
            "sampling_status",
            "badge",
            "sale_status",
            "tipo_status",
            "country",
            "price_currency",
            "price_bucket",
            "manual_model_type",
        ):
            self.assertIn(field_name, html)
        self.assertIn("delete-field", html)
        self.assertIn('id="toast"', html)
        self.assertIn("function showToast", html)


if __name__ == "__main__":
    unittest.main()
