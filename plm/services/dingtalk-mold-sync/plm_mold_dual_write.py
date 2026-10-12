"""Opt-in durable dual delivery for the existing dingtalk_all mold-code task.

No credential is persisted. ERP's existing sender/payload remains unchanged.
Each target acknowledges independently; this is not a distributed transaction.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

LOG = logging.getLogger(__name__)
SUCCESS_STATES = {"created", "duplicate", "linked_existing"}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_event(erp_payload: dict, context: dict | None = None) -> dict:
    """Whitelist code fields only, excluding tokens, callback user IDs and headers."""
    code, name = erp_payload.get("item_code"), erp_payload.get("item_name")
    if not isinstance(code, str) or not code.strip() or len(code) > 64:
        raise ValueError("Invalid original mold code")
    if not isinstance(name, str) or not name.strip() or len(name) > 512:
        raise ValueError("Invalid mold name")
    context = context or {}
    approval_id = context.get("approvalInstanceId") or context.get("processInstanceId")
    approval_status = context.get("approvalStatus")
    if approval_id is not None and (not isinstance(approval_id, str) or not approval_id.strip() or len(approval_id) > 128):
        raise ValueError("Invalid approval instance ID")
    if approval_status is not None and (approval_status != "approved" or not approval_id):
        raise ValueError("Only an explicitly approved, identified approval may declare approval status")
    item = {
        "itemCode": code,
        "itemName": name,
        "itemGroup": erp_payload.get("item_group"),
        "specifications": erp_payload.get("custom_specifications"),
        "originalAlias": erp_payload.get("custom_original_identifier_alias"),
        "disabled": bool(erp_payload.get("disabled", False)),
        "modified": None,
    }
    # A callback without an approval ID is honestly a code event, not an invented approval.
    body = {"approvalInstanceId": approval_id, "approvalStatus": approval_status, "item": item}
    body["eventId"] = "mold-code:" + hashlib.sha256(_canonical(body).encode()).hexdigest()
    return body


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PlmClient:
    def __init__(self, endpoint: str, token_provider: Callable[[], str], opener=None):
        url = urlsplit(endpoint)
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("PLM endpoint must not contain credentials or query parameters")
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("Non-local PLM requests require HTTPS")
        if url.path.rstrip("/") != "/api/v1/integrations/dingtalk/mold-codes":
            raise ValueError("Expected the PLM mold-code intake endpoint")
        # Authentication must not follow a redirect to a different recipient.
        handlers = [_NoRedirect()]
        if url.hostname in {"127.0.0.1", "localhost", "::1"}:
            # A loopback credential must not be sent to a system proxy.
            handlers.insert(0, ProxyHandler({}))
        self.endpoint, self.token_provider, self.opener = endpoint, token_provider, opener or build_opener(*handlers).open

    def __call__(self, event: dict) -> bool:
        token = self.token_provider()
        if not token:
            raise RuntimeError("PLM authentication unavailable")
        request = Request(self.endpoint, data=_canonical(event).encode(), method="POST",
                          headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with self.opener(request, timeout=15) as response:
                data = json.loads(response.read(512_000))
                result = data.get("data") if isinstance(data, dict) else None
                return (response.status in {200, 201} and isinstance(result, dict) and data.get("code") == 0
                        and result.get("eventId") == event["eventId"] and result.get("status") in SUCCESS_STATES)
        except HTTPError as exc:
            # Do not persist response bodies/URLs: upstream errors may contain secrets.
            status = exc.code
            exc.close()
            raise RuntimeError("PLM HTTP " + str(status)) from None
        except (URLError, OSError, ValueError, TypeError):
            raise RuntimeError("PLM transport or response error") from None


class MoldDualWriter:
    def __init__(self, path: str | Path, erp_sender: Callable[[dict], bool], plm_sender: Callable[[dict], bool], clock=time.time):
        self.path = str(path)
        self.senders = {"erp": erp_sender, "plm": plm_sender}
        self.clock = clock
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        with self._connect() as db:
            db.executescript("""
                create table if not exists events (
                    event_id text primary key, payload text not null, erp_payload text not null
                );
                create table if not exists deliveries (
                    event_id text not null references events(event_id), target text not null,
                    state text not null default 'pending', attempts integer not null default 0,
                    next_attempt real not null default 0, lease_until real not null default 0,
                    lease_key text, last_error text, primary key(event_id,target)
                );
            """)
        # The caller must provide a private directory outside the public web root.
        os.chmod(self.path, 0o600)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("pragma foreign_keys=on")
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, payload: dict, context: dict | None = None) -> str:
        event = make_event(payload, context)
        # ERP receives exactly its existing whitelisted Item payload, not a PLM payload.
        raw_erp = {key: payload[key] for key in ("item_code", "item_name", "item_group", "custom_specifications", "stock_uom", "is_stock_item", "custom_original_identifier_alias", "disabled") if key in payload}
        with self._connect() as db:
            db.execute("insert or ignore into events values(?,?,?)", (event["eventId"], _canonical(event), _canonical(raw_erp)))
            existing = db.execute("select payload,erp_payload from events where event_id=?", (event["eventId"],)).fetchone()
            if existing["payload"] != _canonical(event) or existing["erp_payload"] != _canonical(raw_erp):
                raise ValueError("Existing event payload differs")
            for target in self.senders:
                db.execute("insert or ignore into deliveries(event_id,target) values(?,?)", (event["eventId"], target))
        return event["eventId"]

    def _attempt(self, event_id: str, target: str) -> bool:
        now = self.clock()
        lease = os.urandom(16).hex()
        with self._connect() as db:
            db.execute("begin immediate")
            row = db.execute("select * from deliveries where event_id=? and target=?", (event_id, target)).fetchone()
            if row is None:
                return False
            if row["state"] == "succeeded":
                return True
            if row["next_attempt"] > now or row["lease_until"] > now:
                return False
            db.execute("update deliveries set lease_until=?,lease_key=?,attempts=attempts+1 where event_id=? and target=?", (now + 60, lease, event_id, target))
            event = db.execute("select * from events where event_id=?", (event_id,)).fetchone()
            attempts = row["attempts"] + 1
        error = None
        try:
            succeeded = self.senders[target](json.loads(event["erp_payload" if target == "erp" else "payload"])) is True
            if not succeeded:
                error = "target_not_acknowledged"
        except Exception:
            succeeded, error = False, "target_request_failed"
        with self._connect() as db:
            db.execute("""update deliveries set state=?,lease_until=0,lease_key=null,next_attempt=?,last_error=?
                          where event_id=? and target=? and lease_key=?""",
                       ("succeeded" if succeeded else "pending", 0 if succeeded else self.clock() + min(300, 2 ** min(attempts, 8)), error, event_id, target, lease))
        return succeeded

    def deliver(self, event_id: str) -> dict[str, bool]:
        # Separate failure boundaries ensure a failing ERP request still allows PLM delivery.
        return {target: self._attempt(event_id, target) for target in self.senders}

    def retry_pending(self, limit: int = 25) -> int:
        now = self.clock()
        with self._connect() as db:
            pending = db.execute("select event_id,target from deliveries where state='pending' and next_attempt<=? and lease_until<=? order by next_attempt,event_id limit ?", (now, now, limit)).fetchall()
        for row in pending:
            self._attempt(row["event_id"], row["target"])
        return len(pending)

    def status(self, event_id: str) -> dict:
        with self._connect() as db:
            return {row["target"]: {"state": row["state"], "attempts": row["attempts"], "lastError": row["last_error"]}
                    for row in db.execute("select * from deliveries where event_id=?", (event_id,))}

    def start_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        def loop():
            while not self._stop.is_set():
                try:
                    self.retry_pending()
                except Exception:
                    LOG.error("Mold dual-write retry store unavailable; pending work retained")
                self._stop.wait(5)
        self._worker = threading.Thread(target=loop, name="mold-dual-write-retry", daemon=True)
        self._worker.start()

    def close(self):
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=2)


_writer: MoldDualWriter | None = None
_erp_sender: Callable[[dict], bool] | None = None


def configure_mold_sync(erp_sender: Callable[[dict], bool]):
    """Disabled by default. No new account, credential, URL or service is inferred."""
    global _writer, _erp_sender
    if _writer is not None:
        _writer.close()
        _writer = None
    _erp_sender = erp_sender
    if os.environ.get("PLM_MOLD_SYNC_ENABLED", "false").lower() != "true":
        return
    endpoint = os.environ.get("PLM_MOLD_SYNC_URL", "")
    path = Path(os.environ.get("PLM_MOLD_SYNC_OUTBOX", ""))
    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError("An existing private outbox directory and absolute path are required")
    if path.parent.stat().st_mode & 0o077:
        raise ValueError("Outbox directory must be private (0700)")
    client = PlmClient(endpoint, lambda: os.environ.get("PLM_MOLD_SYNC_TOKEN", ""))
    _writer = MoldDualWriter(path, erp_sender, client)
    _writer.start_worker()


def dual_write_mold(payload: dict, context: dict | None = None) -> bool:
    if _erp_sender is None:
        raise RuntimeError("Mold sync has not been configured")
    if _writer is None:
        return _erp_sender(payload)
    try:
        event_id = _writer.enqueue(payload, context)
    except Exception:
        # Fail closed: do not send a code when durable retry recording failed.
        LOG.error("Mold dual-write enqueue failed; no external target invoked")
        return False
    result = _writer.deliver(event_id)
    if not all(result.values()):
        LOG.warning("Mold dual-write pending: ERP=%s PLM=%s event=%s", result["erp"], result["plm"], event_id)
    # Keep the old task's ERP success/failure semantics for existing DingTalk messages.
    return result["erp"]
