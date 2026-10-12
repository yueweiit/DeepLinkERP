import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plm_mold_dual_write import MoldDualWriter, PlmClient, make_event

PAYLOAD = {"item_code": "MBA200052", "item_name": "IP 11\t", "item_group": "MBA20PC", "custom_specifications": "PC\t", "stock_uom": "个: pieza", "is_stock_item": 1}


class Response(io.BytesIO):
    status = 200


class DualWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "outbox.sqlite"
        self.now = 1000.0
        self.erp, self.plm = Mock(return_value=True), Mock(return_value=True)
        self.writer = MoldDualWriter(self.path, self.erp, self.plm, lambda: self.now)

    def tearDown(self):
        self.writer.close()
        self.tmp.cleanup()

    def test_event_preserves_original_values_without_inventing_approval_or_actor(self):
        event = make_event(PAYLOAD, {"userId": "untrusted", "token": "secret", "password": "secret"})
        self.assertEqual(event["item"]["itemCode"], "MBA200052")
        self.assertEqual(event["item"]["itemName"], "IP 11\t")
        self.assertIsNone(event["approvalInstanceId"])
        self.assertIsNone(event["approvalStatus"])
        self.assertNotIn("secret", json.dumps(event))
        self.assertNotIn("untrusted", json.dumps(event))
        self.assertEqual(make_event(PAYLOAD)["eventId"], event["eventId"])

    def test_explicit_approval_metadata_must_be_approved_and_identified(self):
        for context in ({"approvalStatus": "rejected", "approvalInstanceId": "id"}, {"approvalStatus": "approved"}):
            with self.assertRaises(ValueError):
                make_event(PAYLOAD, context)
        event = make_event(PAYLOAD, {"approvalStatus": "approved", "approvalInstanceId": "real-instance"})
        self.assertEqual(event["approvalInstanceId"], "real-instance")

    def test_both_targets_acknowledge_and_repeated_callback_sends_neither_again(self):
        event_id = self.writer.enqueue(PAYLOAD)
        self.assertEqual(self.writer.deliver(event_id), {"erp": True, "plm": True})
        self.assertEqual(self.writer.enqueue(PAYLOAD), event_id)
        self.writer.deliver(event_id)
        self.erp.assert_called_once_with(PAYLOAD)
        self.plm.assert_called_once_with(make_event(PAYLOAD))
        self.assertEqual(self.writer.status(event_id)["erp"]["attempts"], 1)

    def test_erp_success_survives_plm_failure_and_restart_retries_only_plm(self):
        self.plm.side_effect = [RuntimeError("secret-bearing error"), True]
        event_id = self.writer.enqueue(PAYLOAD)
        self.assertEqual(self.writer.deliver(event_id), {"erp": True, "plm": False})
        self.assertNotIn("secret", self.path.read_bytes().decode(errors="ignore"))
        restored = MoldDualWriter(self.path, self.erp, self.plm, lambda: self.now)
        self.assertEqual(restored.retry_pending(), 0)
        self.now += 3
        self.assertEqual(restored.retry_pending(), 1)
        self.erp.assert_called_once()
        self.assertEqual(self.plm.call_count, 2)
        self.assertEqual(restored.status(event_id)["plm"]["state"], "succeeded")
        restored.close()

    def test_erp_failure_still_delivers_plm_and_retries_only_erp(self):
        self.erp.side_effect = [False, True]
        event_id = self.writer.enqueue(PAYLOAD)
        self.assertEqual(self.writer.deliver(event_id), {"erp": False, "plm": True})
        self.now += 3
        self.writer.retry_pending()
        self.assertEqual(self.erp.call_count, 2)
        self.plm.assert_called_once()

    def test_active_lease_prevents_two_workers_sending_same_target(self):
        entered, release = threading.Event(), threading.Event()
        def send(payload):
            entered.set()
            release.wait(2)
            return True
        self.writer.senders["plm"] = send
        event_id = self.writer.enqueue(PAYLOAD)
        first = threading.Thread(target=lambda: self.writer._attempt(event_id, "plm"))
        first.start()
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.writer._attempt(event_id, "plm"))
        release.set()
        first.join(2)
        self.assertEqual(self.writer.status(event_id)["plm"]["attempts"], 1)

    def test_http_client_requires_https_auth_and_matching_business_ack(self):
        with self.assertRaises(ValueError):
            PlmClient("http://example.com/api/v1/integrations/dingtalk/mold-codes", lambda: "token")
        event = make_event(PAYLOAD)
        opener = Mock(side_effect=lambda request, timeout: Response(json.dumps({"code": 0, "data": {"eventId": event["eventId"], "status": "duplicate"}}).encode()))
        client = PlmClient("http://127.0.0.1:8080/api/v1/integrations/dingtalk/mold-codes", lambda: "runtime-token", opener)
        self.assertTrue(client(event))
        self.assertEqual(opener.call_args.args[0].get_header("Authorization"), "Bearer runtime-token")
        opener.side_effect = lambda request, timeout: Response(b'{"code":40101,"data":{}}')
        self.assertFalse(client(event))
        opener.side_effect = lambda request, timeout: Response(b'{"code":0,"data":{"eventId":"other","status":"created"}}')
        self.assertFalse(client(event))
        missing = PlmClient(client.endpoint, lambda: "", opener)
        with self.assertRaises(RuntimeError):
            missing(event)

    def test_pending_auth_failure_is_not_treated_as_success_or_lost(self):
        self.writer.senders["plm"] = PlmClient("http://localhost:8080/api/v1/integrations/dingtalk/mold-codes", lambda: "")
        event_id = self.writer.enqueue(PAYLOAD)
        self.writer.deliver(event_id)
        status = self.writer.status(event_id)
        self.assertEqual(status["erp"]["state"], "succeeded")
        self.assertEqual(status["plm"]["state"], "pending")

    def test_authenticated_client_does_not_follow_redirects(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        visits = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                visits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/unexpected-recipient")
                self.end_headers()
            def do_GET(self):
                visits.append(self.path)
                self.send_response(200)
                self.end_headers()
            def log_message(self, *args):
                pass
        # DNS is not part of this redirect test; avoid a reverse lookup of loopback.
        with patch("http.server.socket.getfqdn", return_value="localhost"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = PlmClient("http://127.0.0.1:" + str(server.server_port) + "/api/v1/integrations/dingtalk/mold-codes", lambda: "dummy-test-token")
            with self.assertRaisesRegex(RuntimeError, "PLM HTTP 302"):
                client(make_event(PAYLOAD))
            self.assertEqual(visits, ["/api/v1/integrations/dingtalk/mold-codes"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_disabled_adapter_preserves_existing_erp_path_and_starts_no_worker(self):
        import plm_mold_dual_write as module
        with patch.dict("os.environ", {"PLM_MOLD_SYNC_ENABLED": "false"}), patch.object(module, "_writer", None), patch.object(module, "_erp_sender", None):
            module.configure_mold_sync(self.erp)
            self.assertTrue(module.dual_write_mold(PAYLOAD))
            self.assertIsNone(module._writer)
            self.erp.assert_called_once_with(PAYLOAD)


if __name__ == "__main__":
    unittest.main()
