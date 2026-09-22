from overseas_costing.services import erp_sync_ledger_service as ledger


def _spec(request_id="R1", payload_hash="P1"):
    return {
        "ready": True,
        "requests": [
            {
                "request_id": request_id,
                "operation": "CREATE",
                "batch": "B1",
                "site_code": "MX",
                "business_key": "BK1",
                "cost_result_hash": "H1",
                "payload_hash": payload_hash,
                "payload": {"items": [{"stable_line_key": "L1"}]},
            }
        ],
    }


class _FakeDoc:
    def __init__(self, values, rows):
        self.values = values
        self.rows = rows
        self.name = "SYNC-" + str(len(rows) + 1)

    def insert(self, ignore_permissions=True):
        self.rows.append({"name": self.name, **self.values})
        return self


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def set_value(self, doctype, name, fieldname, value, update_modified=True):
        next(row for row in self.rows if row["name"] == name)[fieldname] = value


class _FakeFrappe:
    class DuplicateEntryError(Exception):
        pass

    def __init__(self, rows=None):
        self.rows = rows or []
        self.db = _FakeDB(self.rows)

    def get_all(self, doctype, filters, fields, order_by=None, limit_page_length=0):
        rows = [row for row in self.rows if all(row.get(fieldname) == value for fieldname, value in filters.items())]
        if order_by:
            rows = list(reversed(rows))
        return [{key: row.get(key) for key in fields} for row in rows[:limit_page_length]]

    def get_doc(self, values):
        return _FakeDoc(values, self.rows)


def test_save_sync_requests_creates_local_pending_ledger_without_external_client(monkeypatch) -> None:
    fake = _FakeFrappe()
    monkeypatch.setattr(ledger, "frappe", fake)

    result = ledger.save_sync_request_specs(_spec(), version="V1")

    assert result == {"ok": True, "blocking": [], "requests": [{"name": "SYNC-1", "request_id": "R1", "action": "CREATE"}]}
    assert fake.rows[0]["status"] == "PENDING"
    assert fake.rows[0]["version"] == "V1"
    assert fake.rows[0]["safe_payload_json"] == '{"items":[{"stable_line_key":"L1"}]}'


def test_save_sync_requests_reuses_identical_request(monkeypatch) -> None:
    fake = _FakeFrappe()
    monkeypatch.setattr(ledger, "frappe", fake)
    ledger.save_sync_request_specs(_spec())

    result = ledger.save_sync_request_specs(_spec())

    assert result["requests"][0]["action"] == "REUSE"
    assert len(fake.rows) == 1


def test_save_sync_requests_supersedes_only_unsent_draft(monkeypatch) -> None:
    fake = _FakeFrappe()
    monkeypatch.setattr(ledger, "frappe", fake)
    ledger.save_sync_request_specs(_spec(request_id="R1", payload_hash="P1"))

    result = ledger.save_sync_request_specs(_spec(request_id="R2", payload_hash="P2"))

    assert result["requests"][0]["action"] == "CREATE"
    assert [row["status"] for row in fake.rows] == ["SUPERSEDED", "PENDING"]


def test_save_sync_requests_returns_blocking_preview_without_writing(monkeypatch) -> None:
    fake = _FakeFrappe()
    monkeypatch.setattr(ledger, "frappe", fake)

    result = ledger.save_sync_request_specs({"ready": False, "blocking": ["存在未路由物料"]})

    assert result == {"ok": False, "blocking": ["存在未路由物料"], "requests": []}
    assert fake.rows == []


def test_list_sync_requests_scopes_to_batch_and_version(monkeypatch) -> None:
    fake = _FakeFrappe(
        [
            {"name": "S1", "batch": "B1", "version": "V1", "request_id": "R1", "site_code": "MX"},
            {"name": "S2", "batch": "B1", "version": "V2", "request_id": "R2", "site_code": "US"},
        ]
    )
    monkeypatch.setattr(ledger, "frappe", fake)

    result = ledger.list_sync_requests("B1", version="V1", limit=999)

    assert result["total"] == 1
    assert result["items"][0]["request_id"] == "R1"


def test_execute_request_documents_keeps_partial_success_and_retries_only_failed() -> None:
    documents = [
        {"name": "S1", "status": "PENDING", "site_code": "DEEPLINKERP", "attempt_count": 0, "safe_payload_json": '{"subsidiary_code":"A"}'},
        {"name": "S2", "status": "PENDING", "site_code": "DEEPLINKERP", "attempt_count": 0, "safe_payload_json": '{"subsidiary_code":"B"}'},
    ]
    calls = []

    def push(payload, config):
        calls.append(payload["subsidiary_code"])
        return {"ok": payload["subsidiary_code"] == "A", "erp_target_doc": "PO-A" if payload["subsidiary_code"] == "A" else ""}

    first = ledger.execute_request_documents(
        documents,
        push_payload=push,
        config_loader=lambda site: {"site": site},
        now_text="2026-09-22 10:00:00",
    )
    second = ledger.execute_request_documents(
        documents,
        push_payload=push,
        config_loader=lambda site: {"site": site},
        now_text="2026-09-22 10:01:00",
    )

    assert first["success_count"] == 1
    assert first["failed_count"] == 1
    assert second["success_count"] == 0
    assert second["failed_count"] == 1
    assert calls == ["A", "B", "B"]
    assert documents[0]["status"] == "SUCCESS"
    assert documents[0]["attempt_count"] == 1
    assert documents[1]["status"] == "FAILED"
    assert documents[1]["attempt_count"] == 2


def test_execute_request_documents_marks_unexpected_exception_uncertain() -> None:
    documents = [{"name": "S1", "status": "PENDING", "site_code": "DEEPLINKERP", "safe_payload_json": '{}'}]

    result = ledger.execute_request_documents(
        documents,
        push_payload=lambda payload, config: (_ for _ in ()).throw(TimeoutError("unknown remote state")),
        config_loader=lambda site: {},
        now_text="2026-09-22 10:00:00",
    )

    assert result["uncertain_count"] == 1
    assert documents[0]["status"] == "UNCERTAIN"


class _ClaimDB:
    def __init__(self, row):
        self.row = row
        self.queries = []
        self.commits = 0

    def sql(self, query, values, as_dict=False):
        self.queries.append((query, values, as_dict))
        return [dict(self.row)] if self.row else []

    def set_value(self, doctype, name, fieldname, value, update_modified=True):
        assert name == self.row["name"]
        self.row[fieldname] = value

    def commit(self):
        self.commits += 1


class _ClaimFrappe:
    def __init__(self, row):
        self.db = _ClaimDB(row)


def test_claim_sync_request_uses_database_lock_and_only_first_worker_claims(monkeypatch) -> None:
    fake = _ClaimFrappe(
        {
            "name": "S1",
            "status": "PENDING",
            "attempt_count": 0,
            "site_code": "DEEPLINKERP",
            "safe_payload_json": "{}",
            "started_at": None,
        }
    )
    monkeypatch.setattr(ledger, "frappe", fake)

    first = ledger._claim_sync_request("S1", "2026-09-22 10:00:00")
    second = ledger._claim_sync_request("S1", "2026-09-22 10:00:01")

    assert first["action"] == "CLAIM"
    assert first["attempt_count"] == 1
    assert second == {"name": "S1", "status": "RUNNING", "action": "SKIP", "attempt_count": 1}
    assert all("FOR UPDATE" in query.upper() for query, _values, _as_dict in fake.db.queries)
    assert fake.db.row["status"] == "RUNNING"
    assert fake.db.commits == 2


def test_stale_running_request_becomes_uncertain_without_resend(monkeypatch) -> None:
    fake = _ClaimFrappe(
        {
            "name": "S1",
            "status": "RUNNING",
            "attempt_count": 2,
            "site_code": "DEEPLINKERP",
            "safe_payload_json": "{}",
            "started_at": "2026-09-22 09:00:00",
        }
    )
    monkeypatch.setattr(ledger, "frappe", fake)

    result = ledger._claim_sync_request("S1", "2026-09-22 10:00:00")

    assert result["action"] == "STALE"
    assert result["status"] == "UNCERTAIN"
    assert fake.db.row["error_code"] == "STALE_RUNNING"
    assert "人工核对" in fake.db.row["error_message"]
