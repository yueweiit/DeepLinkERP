from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import db
from .dingtalk_sync import load_config, sync_rows_to_dingtalk


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def parse_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


class DingTalkSyncHandler(BaseHTTPRequestHandler):
    server_version = "PhoneWatchDingTalk/1.0"

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_json(200, {"ok": True})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/health", "/dingtalk/sync"}:
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "phone_watch_dingtalk_sync",
                    "endpoint": "/dingtalk/sync",
                    "message": "ready",
                },
            )
            return
        self.send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/dingtalk/sync":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return

        try:
            body = self.read_json_body()
            query = parse_qs(parsed.query)
            run_sync = parse_bool(body.get("run_sync") or first_query_value(query, "run_sync"))
            if not run_sync:
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "service": "phone_watch_dingtalk_sync",
                        "endpoint": "/dingtalk/sync",
                        "message": "ready",
                    },
                )
                return

            dry_run = parse_bool(body.get("dry_run") or first_query_value(query, "dry_run"))
            source_table = str(body.get("source_table") or first_query_value(query, "source_table") or "candidates")
            status = body.get("status") or first_query_value(query, "status")
            seen_date = body.get("seen_date") or first_query_value(query, "seen_date")
            latest_date = parse_bool(body.get("latest_date") or first_query_value(query, "latest_date"))
            limit = int(body.get("limit") or first_query_value(query, "limit") or 50)

            with db.connect() as conn:
                selected_date = db.latest_collected_date(conn) if latest_date else seen_date
                counts = sync_rows_to_dingtalk(
                    conn,
                    config=load_config(),
                    source_table=source_table,
                    status=status,
                    seen_date=selected_date,
                    limit=limit,
                    dry_run=dry_run,
                )
            self.send_json(200, {"ok": True, "counts": counts})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def run_server(host: str = "127.0.0.1", port: int = 5011) -> None:
    server = ThreadingHTTPServer((host, port), DingTalkSyncHandler)
    print(f"DingTalk sync HTTP server running at http://{host}:{port}", flush=True)
    server.serve_forever()
