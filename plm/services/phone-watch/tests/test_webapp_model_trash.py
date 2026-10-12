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
from phone_watch.webapp import PhoneWatchHandler


class WebappModelTrashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)
        PhoneWatchHandler.db_path = str(self.db_path)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PhoneWatchHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        with db.connect(self.db_path) as conn:
            db.upsert_candidate(
                conn,
                {
                    "brand": "VIVO",
                    "source_country": "CN",
                    "missing_country": "MX",
                    "model": "Vivo Trash API",
                    "normalized_model": "vivotrashapi",
                    "source_url": "https://example.com/vivo-trash-api",
                    "source_name": "Manual",
                    "reason": "test",
                    "first_seen_at": "2026-07-08T00:00:00+00:00",
                    "last_seen_at": "2026-07-08T00:00:00+00:00",
                    "sampling_status": "未开模",
                },
            )
            row = conn.execute(
                "SELECT id FROM candidates WHERE normalized_model = ?",
                ("vivotrashapi",),
            ).fetchone()
            self.candidate_id = int(row["id"])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

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

    def test_trash_restore_purge_endpoints(self) -> None:
        trash_status, trash_body = self.post_json(
            "/api/models/trash",
            {
                "items": [{"type": "candidates", "id": self.candidate_id}],
                "reason": "manual_bulk_delete",
                "now": "2026-07-08T00:00:00+00:00",
            },
        )
        list_status, list_body = self.get_json("/api/models/trash")

        self.assertEqual(trash_status, 200)
        self.assertTrue(trash_body["ok"])
        self.assertEqual(trash_body["updated"], 1)
        self.assertEqual(list_status, 200)
        self.assertTrue(list_body["ok"])
        self.assertEqual(len(list_body["items"]), 1)
        self.assertEqual(list_body["items"][0]["normalized_model"], "vivotrashapi")

        restore_status, restore_body = self.post_json(
            "/api/models/restore",
            {"items": [{"type": "candidates", "id": self.candidate_id}]},
        )
        self.assertEqual(restore_status, 200)
        self.assertTrue(restore_body["ok"])
        self.assertEqual(restore_body["restored"], 1)

        self.post_json(
            "/api/models/trash",
            {
                "items": [{"type": "candidates", "id": self.candidate_id}],
                "now": "2026-07-01T00:00:00+00:00",
            },
        )
        cleanup_status, cleanup_body = self.post_json(
            "/api/models/trash/cleanup",
            {"now": "2026-07-09T00:00:00+00:00"},
        )
        self.assertEqual(cleanup_status, 200)
        self.assertTrue(cleanup_body["ok"])
        self.assertEqual(cleanup_body["purged"], 1)


if __name__ == "__main__":
    unittest.main()
