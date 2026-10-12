from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from phone_watch import db
from phone_watch.webapp import PhoneWatchHandler


class WebappDingTalkTipoStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)
        PhoneWatchHandler.db_path = str(self.db_path)
        with db.connect(self.db_path) as conn:
            db.upsert_candidate(
                conn,
                {
                    "brand": "MOTOROLA",
                    "source_country": "CN",
                    "missing_country": "MX",
                    "model": "Moto DingTalk Done Test",
                    "normalized_model": "motodingtalkdonetest",
                    "source_url": "https://example.com/dingtalk-done-test",
                    "source_name": "Manual",
                    "reason": "test",
                    "first_seen_at": "2026-07-10T00:00:00+00:00",
                    "last_seen_at": "2026-07-10T00:00:00+00:00",
                    "sampling_status": db.DEFAULT_STATUS,
                },
            )
            row = conn.execute(
                "SELECT id FROM candidates WHERE normalized_model = ?",
                ("motodingtalkdonetest",),
            ).fetchone()
            self.candidate_id = int(row["id"])

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

    @patch("phone_watch.webapp.load_dingtalk_config")
    @patch("phone_watch.webapp.sync_one_row_to_dingtalk")
    def test_sync_one_marks_tipo_done_after_success(self, sync_one, load_config) -> None:
        load_config.return_value = object()
        sync_one.return_value = {
            "ok": True,
            "source_table": "candidates",
            "source_id": self.candidate_id,
            "tipo": "Tipo Alpha",
            "process_instance_id": "proc-1",
        }

        status, body = self.post_json(
            "/api/dingtalk/sync-one",
            {
                "type": "candidates",
                "id": self.candidate_id,
                "tipo_values": ["Tipo Alpha"],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        with db.connect(self.db_path) as conn:
            records = db.molding_tipos_for_model(
                conn,
                "MOTOROLA",
                "motodingtalkdonetest",
            )
            row = conn.execute(
                "SELECT sampling_status FROM candidates WHERE id = ?",
                (self.candidate_id,),
            ).fetchone()
        self.assertEqual(records[0]["tipo_name"], "Tipo Alpha")
        self.assertEqual(records[0]["status"], db.TIPO_DONE_STATUS)
        self.assertEqual(row["sampling_status"], db.TIPO_DONE_STATUS)

    @patch("phone_watch.webapp.load_dingtalk_config")
    @patch("phone_watch.webapp.sync_one_row_to_dingtalk")
    def test_sync_selected_marks_tipo_done_after_success(self, sync_one, load_config) -> None:
        load_config.return_value = object()
        sync_one.return_value = {
            "ok": True,
            "source_table": "candidates",
            "source_id": self.candidate_id,
            "tipo": "Tipo Beta",
            "process_instance_id": "proc-2",
        }

        status, body = self.post_json(
            "/api/dingtalk/sync-selected",
            {
                "items": [
                    {
                        "type": "candidates",
                        "id": self.candidate_id,
                        "tipo_values": ["Tipo Beta"],
                    }
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        with db.connect(self.db_path) as conn:
            records = db.molding_tipos_for_model(
                conn,
                "MOTOROLA",
                "motodingtalkdonetest",
            )
            row = conn.execute(
                "SELECT sampling_status FROM candidates WHERE id = ?",
                (self.candidate_id,),
            ).fetchone()
        self.assertEqual(records[0]["tipo_name"], "Tipo Beta")
        self.assertEqual(records[0]["status"], db.TIPO_DONE_STATUS)
        self.assertEqual(row["sampling_status"], db.TIPO_DONE_STATUS)


if __name__ == "__main__":
    unittest.main()
