from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from phone_watch import db
from phone_watch.ui import render_app_html
from phone_watch.webapp import PhoneWatchHandler


class Row(dict):
    def keys(self):
        return super().keys()


class PriceFilteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def insert_phone(self, conn, *, model: str, price: str | None, country: str = "MX") -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.upsert_phone(
            conn,
            {
                "brand": "MOTOROLA",
                "country": country,
                "model": model,
                "normalized_model": model.lower().replace(" ", ""),
                "image_url": None,
                "price": price,
                "release_date": None,
                "launch_date": None,
                "source_url": f"https://example.com/{model}",
                "source_name": "Test",
                "badge": None,
                "first_seen_at": now,
                "last_seen_at": now,
                "sampling_status": db.DEFAULT_STATUS,
                "clean_stage": "test",
            },
        )

    def insert_candidate(self, conn, *, model: str, price: str | None, source_country: str = "CN") -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.upsert_candidate(
            conn,
            {
                "brand": "MOTOROLA",
                "source_country": source_country,
                "missing_country": "MX",
                "model": model,
                "normalized_model": model.lower().replace(" ", ""),
                "image_url": None,
                "price": price,
                "release_date": None,
                "launch_date": None,
                "source_url": f"https://example.com/{model}",
                "source_name": "Test",
                "reason": "test",
                "first_seen_at": now,
                "last_seen_at": now,
                "sampling_status": db.DEFAULT_STATUS,
            },
        )

    def test_parse_price_for_filter_recognizes_supported_original_currencies(self) -> None:
        self.assertEqual(db.parse_price_for_filter("$4,999"), ("MXN", 4999.0))
        self.assertEqual(db.parse_price_for_filter("MXN 12,499"), ("MXN", 12499.0))
        self.assertEqual(db.parse_price_for_filter("MX$2,499"), ("MXN", 2499.0))
        self.assertEqual(db.parse_price_for_filter("¥1,999"), ("CNY", 1999.0))
        self.assertEqual(db.parse_price_for_filter("￥1,999"), ("CNY", 1999.0))
        self.assertEqual(db.parse_price_for_filter("1999 元"), ("CNY", 1999.0))
        self.assertEqual(db.parse_price_for_filter("RMB 2999"), ("CNY", 2999.0))
        self.assertEqual(db.parse_price_for_filter("₩599,000"), ("KRW", 599000.0))
        self.assertEqual(db.parse_price_for_filter("599,000원"), ("KRW", 599000.0))
        self.assertEqual(db.parse_price_for_filter("US$299"), ("USD", 299.0))
        self.assertEqual(db.parse_price_for_filter("USD 299.99"), ("USD", 299.99))

    def test_parse_price_for_filter_returns_empty_tuple_for_unrecognized_price(self) -> None:
        self.assertEqual(db.parse_price_for_filter(""), (None, None))
        self.assertEqual(db.parse_price_for_filter(None), (None, None))
        self.assertEqual(db.parse_price_for_filter("Consultar precio"), (None, None))
        self.assertEqual(db.parse_price_for_filter("299 EUR"), (None, None))

    def test_filter_rows_by_original_currency_range_and_bucket(self) -> None:
        rows = [
            Row(id=1, price="$4,999"),
            Row(id=2, price="MXN 9,999"),
            Row(id=3, price="¥1,999"),
            Row(id=4, price="Consultar precio"),
            Row(id=5, price=""),
        ]

        mxn_range = db.filter_rows_by_price(rows, "MXN", 4000, 8000)
        unpriced = db.filter_rows_by_price(rows, price_bucket="unpriced")
        priced_cny = db.filter_rows_by_price(rows, currency="CNY", price_bucket="priced")
        all_rows = db.filter_rows_by_price(rows, None, None, None, "all")

        self.assertEqual([row["id"] for row in mxn_range], [1])
        self.assertEqual([row["id"] for row in unpriced], [4, 5])
        self.assertEqual([row["id"] for row in priced_cny], [3])
        self.assertEqual([row["id"] for row in all_rows], [1, 2, 3, 4, 5])

    def test_list_functions_accept_price_filters(self) -> None:
        with db.connect(self.db_path) as conn:
            self.insert_phone(conn, model="MX low", price="$4,999")
            self.insert_phone(conn, model="MX high", price="MXN 9,999")
            self.insert_candidate(conn, model="CN mid", price="¥1,999")
            self.insert_candidate(conn, model="No price", price="Consultar precio")

            phones = db.list_phones(conn, price_currency="MXN", price_min=4000, price_max=8000)
            candidates = db.list_candidates(conn, price_currency="CNY", price_min=1000, price_max=3000)
            unpriced = db.list_candidates(conn, price_bucket="unpriced")

        self.assertEqual([row["model"] for row in phones], ["MX low"])
        self.assertEqual([row["model"] for row in candidates], ["CN mid"])
        self.assertEqual([row["model"] for row in unpriced], ["No price"])


class PriceFilteringWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)
        with db.connect(self.db_path) as conn:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for model, price in (("MX low", "$4,999"), ("MX high", "MXN 9,999")):
                db.upsert_phone(
                    conn,
                    {
                        "brand": "MOTOROLA",
                        "country": "MX",
                        "model": model,
                        "normalized_model": model.lower().replace(" ", ""),
                        "image_url": None,
                        "price": price,
                        "release_date": None,
                        "launch_date": None,
                        "source_url": f"https://example.com/{model}",
                        "source_name": "Test",
                        "badge": None,
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "sampling_status": db.DEFAULT_STATUS,
                        "clean_stage": "test",
                    },
                )
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
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_api_applies_price_range_filters(self) -> None:
        status, body = self.get_json("/api/phones?price_currency=MXN&price_min=4000&price_max=8000")

        self.assertEqual(status, 200)
        self.assertEqual([row["model"] for row in body], ["MX low"])

    def test_api_returns_400_for_invalid_price_number(self) -> None:
        status, body = self.get_json("/api/phones?price_min=abc")

        self.assertEqual(status, 400)
        self.assertIn("Invalid price filter", body["error"])

    def test_price_filter_controls_are_rendered(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('id="price-currency"', html)
        self.assertIn('id="price-min"', html)
        self.assertIn('id="price-max"', html)
        self.assertIn('id="price-bucket"', html)
        self.assertIn("function parsePriceForFilter(price)", html)
        self.assertIn("function priceMatches(row, f)", html)


if __name__ == "__main__":
    unittest.main()
