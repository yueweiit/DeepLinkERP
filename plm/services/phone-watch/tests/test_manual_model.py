from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from phone_watch import db
from phone_watch.ui import render_app_html
from phone_watch.webapp import PhoneWatchHandler


class ManualModelTests(unittest.TestCase):
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

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_manual_model_elements_are_rendered(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('id="open-manual-model"', html)
        self.assertIn('id="manual-model-modal"', html)
        self.assertIn('id="manual-model-form"', html)
        self.assertIn("function openManualModel()", html)
        self.assertIn("function saveManualModel(event)", html)

    def test_post_manual_candidate_upserts_and_sets_labels(self) -> None:
        payload = {
            "type": "candidates",
            "brand": "MOTOROLA",
            "model": "moto g power 5G 2026 test",
            "source_country": "CN",
            "missing_country": "MX",
            "source_url": "https://example.com/manual-source",
            "source_name": "Manual",
            "badge": "新品预告",
            "sale_status": "未发布",
            "sampling_status": "未开模",
            "reason": "人工添加",
        }

        first_status, first_body = self.post_json("/api/manual-model", payload)
        second_status, second_body = self.post_json("/api/manual-model", payload)

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertTrue(first_body["ok"])
        self.assertEqual(first_body["type"], "candidates")
        self.assertEqual(first_body["normalized_model"], "gpower5g2026test")
        self.assertEqual(second_body["normalized_model"], "gpower5g2026test")
        with db.connect(self.db_path) as conn:
            rows = db.list_candidates(conn, brand="MOTOROLA", source_country="CN")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "moto g power 5G 2026 test")
        self.assertEqual(rows[0]["reason"], "人工添加")
        self.assertEqual(rows[0]["badge_override"], "新品预告")
        self.assertEqual(rows[0]["sale_status_override"], "未发布")

    def test_post_manual_phone_upserts_and_sets_labels(self) -> None:
        payload = {
            "type": "phones",
            "brand": "SAMSUNG",
            "model": "Galaxy S26 Manual Test",
            "source_country": "MX",
            "source_url": "https://example.com/manual-phone",
            "source_name": "Manual",
            "badge": "新品",
            "sale_status": "已售",
            "sampling_status": "未开模",
        }

        first_status, first_body = self.post_json("/api/manual-model", payload)
        second_status, second_body = self.post_json("/api/manual-model", payload)

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertTrue(first_body["ok"])
        self.assertEqual(first_body["type"], "phones")
        self.assertEqual(first_body["normalized_model"], "galaxys26manualtest")
        self.assertEqual(second_body["normalized_model"], "galaxys26manualtest")
        with db.connect(self.db_path) as conn:
            rows = db.list_phones(conn, brand="SAMSUNG", country="MX")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "Galaxy S26 Manual Test")
        self.assertEqual(rows[0]["source_name"], "Manual")
        self.assertEqual(rows[0]["badge_override"], "新品")
        self.assertEqual(rows[0]["sale_status_override"], "已售")
        self.assertEqual(rows[0]["clean_stage"], "manual")

    def test_post_manual_model_rejects_missing_source_url(self) -> None:
        status, body = self.post_json(
            "/api/manual-model",
            {"type": "candidates", "brand": "MOTOROLA", "model": "moto g power 5G 2026"},
        )

        self.assertEqual(status, 400)
        self.assertIn("来源链接不能为空", body["error"])

    def test_post_manual_model_rejects_invalid_type(self) -> None:
        status, body = self.post_json(
            "/api/manual-model",
            {
                "type": "manual",
                "brand": "MOTOROLA",
                "model": "moto g power 5G 2026",
                "source_url": "https://example.com/manual-source",
            },
        )

        self.assertEqual(status, 400)
        self.assertIn("入库类型只能是 phones 或 candidates", body["error"])

    def test_post_manual_model_rejects_invalid_status(self) -> None:
        status, body = self.post_json(
            "/api/manual-model",
            {
                "type": "candidates",
                "brand": "MOTOROLA",
                "model": "moto g power 5G 2026",
                "source_url": "https://example.com/manual-source",
                "sampling_status": "处理中",
            },
        )

        self.assertEqual(status, 400)
        self.assertIn("开模状态不合法", body["error"])


if __name__ == "__main__":
    unittest.main()
