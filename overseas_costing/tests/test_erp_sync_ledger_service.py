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


import json


def _request_row(status="UNCERTAIN", **overrides):
    row = {
        "name": "SYNC-1",
        "request_id": "R1",
        "status": status,
        "attempt_count": 1,
        "batch": "B1",
        "site_code": "DEEPLINKERP",
        "business_key": "BK1",
        "cost_result_hash": "H1",
        "payload_hash": "P1",
        "safe_payload_json": json.dumps(
            {"business_key": "BK1", "items": [{"stable_line_key": "L1"}, {"stable_line_key": "L2"}]}
        ),
        "started_at": None,
    }
    row.update(overrides)
    return row


class _LinkDB:
    def __init__(self, row, links):
        self.row = row
        self.links = links
        self.commits = 0

    def sql(self, query, values, as_dict=False):
        return [dict(self.row)] if self.row else []

    def set_value(self, doctype, name, fieldname, value, update_modified=True):
        if doctype == ledger.DOCTYPE and name == self.row.get("name"):
            self.row[fieldname] = value
            return
        for link in self.links:
            if link.get("name") == name:
                link[fieldname] = value
                return

    def get_value(self, doctype, filters, fieldname, *args, **kwargs):
        if doctype == ledger.LINK_DOCTYPE:
            for link in self.links:
                if all(link.get(key) == value for key, value in filters.items()):
                    return link.get("name")
            return None
        assert doctype == ledger.DOCTYPE
        if filters == {"batch": self.row.get("batch"), "request_id": self.row.get("request_id")}:
            return self.row.get("name")
        return None

    def commit(self):
        self.commits += 1


class _LinkDoc:
    counter = 0

    def __init__(self, values, links):
        _LinkDoc.counter += 1
        self.values = values
        self.name = f"LINK-{_LinkDoc.counter}"
        self.links = links

    def insert(self, ignore_permissions=True):
        self.links.append({**self.values, "name": self.name})
        return self


class _LinkFrappe:
    class DuplicateEntryError(Exception):
        pass

    def __init__(self, row=None, links=None):
        self.row = row if row is not None else {}
        self.links = links if links is not None else []
        self.db = _LinkDB(self.row, self.links)

    def get_doc(self, values):
        return _LinkDoc(values, self.links)


def _submitted_inspection(**overrides):
    result = {
        "ok": True,
        "found": True,
        "ambiguous": False,
        "name": "PO-1",
        "docstatus": 1,
        "lines": {"L1": "POI-1", "L2": "POI-2"},
    }
    result.update(overrides)
    return result


def _no_remote_purchase():
    return {"ok": True, "found": False, "ambiguous": False, "name": "", "docstatus": None, "lines": {}}


def _pending_document(**overrides):
    document = {
        "name": "S1",
        "batch": "B1",
        "status": "PENDING",
        "site_code": "DEEPLINKERP",
        "attempt_count": 0,
        "cost_result_hash": "H1",
        "payload_hash": "P1",
        "safe_payload_json": json.dumps({"business_key": "BK1", "items": [{"stable_line_key": "L1"}]}),
    }
    document.update(overrides)
    return document


# ---- 推送成功后落远端行级关联 ------------------------------------------------


def test_successful_push_records_remote_line_links() -> None:
    documents = [_pending_document()]
    recorded = []

    result = ledger.execute_request_documents(
        documents,
        push_payload=lambda payload, config: {"ok": True, "erp_target_doc": "PO-1"},
        config_loader=lambda site: {},
        now_text="2026-09-28 10:00:00",
        record_links=lambda doc, payload, response: recorded.append(
            (doc["name"], payload["business_key"], response["erp_target_doc"])
        )
        or 3,
    )

    assert result["success_count"] == 1
    assert recorded == [("S1", "BK1", "PO-1")]
    assert result["results"][0]["linked_row_count"] == 3
    # 关联数量只是执行结果的一部分，不能被当成请求文档的字段写进账本。
    assert "linked_row_count" not in documents[0]


def test_link_failure_never_downgrades_a_successful_push() -> None:
    documents = [_pending_document()]

    def broken_links(doc, payload, response):
        raise RuntimeError("关联表写入失败")

    result = ledger.execute_request_documents(
        documents,
        push_payload=lambda payload, config: {"ok": True, "erp_target_doc": "PO-1"},
        config_loader=lambda site: {},
        now_text="2026-09-28 10:00:00",
        record_links=broken_links,
    )

    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    assert documents[0]["status"] == "SUCCESS"
    assert result["results"][0]["link_error"] == "关联表写入失败"
    assert "保存远端单据关联失败" in documents[0]["error_message"]


def test_failed_push_writes_a_usable_error_code_when_response_has_none() -> None:
    documents = [_pending_document()]

    ledger.execute_request_documents(
        documents,
        push_payload=lambda payload, config: {"ok": False, "message": "物料准备未通过"},
        config_loader=lambda site: {},
        now_text="2026-09-28 10:00:00",
    )

    assert documents[0]["status"] == "FAILED"
    assert documents[0]["error_code"] == "ERP_PUSH_FAILED"
    assert documents[0]["error_message"] == "物料准备未通过"


def test_save_document_links_writes_one_row_per_material_line_key(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row())
    monkeypatch.setattr(ledger, "frappe", fake)

    saved = ledger._save_document_links(
        batch="B1",
        site_code="DEEPLINKERP",
        business_key="BK1",
        cost_result_hash="H1",
        payload_hash="P1",
        remote_document="PO-1",
        remote_docstatus=1,
        payload={"items": [{"stable_line_key": "L1"}, {"stable_line_key": "L2"}]},
        lines={"L1": "POI-1", "L2": "POI-2"},
        now_text="2026-09-28 10:00:00",
    )

    assert saved == 2
    assert [(row["stable_line_key"], row["remote_row"], row["status"]) for row in fake.links] == [
        ("L1", "POI-1", "ACTIVE"),
        ("L2", "POI-2", "ACTIVE"),
    ]
    assert fake.links[0]["remote_doctype"] == "Purchase Order"
    assert fake.links[0]["remote_document"] == "PO-1"
    assert fake.links[0]["remote_docstatus"] == 1
    assert fake.links[0]["last_cost_result_hash"] == "H1"
    assert fake.links[0]["last_payload_hash"] == "P1"
    assert fake.links[0]["verified_at"] == "2026-09-28 10:00:00"


def test_save_document_links_marks_unmatched_remote_row_for_manual_review(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row())
    monkeypatch.setattr(ledger, "frappe", fake)

    ledger._save_document_links(
        batch="B1",
        site_code="DEEPLINKERP",
        business_key="BK1",
        cost_result_hash="H1",
        payload_hash="P1",
        remote_document="PO-1",
        remote_docstatus=1,
        payload={"items": [{"stable_line_key": "L9"}]},
        lines={"L1": "POI-1"},
        now_text="2026-09-28 10:00:00",
    )

    assert fake.links[0]["status"] == "MANUAL_REQUIRED"
    assert fake.links[0]["remote_row"] == ""


def test_save_document_links_updates_the_existing_row_instead_of_duplicating(monkeypatch) -> None:
    existing = [{"name": "LINK-9", "business_key": "BK1", "stable_line_key": "L1", "remote_row": ""}]
    fake = _LinkFrappe(_request_row(), existing)
    monkeypatch.setattr(ledger, "frappe", fake)

    saved = ledger._save_document_links(
        batch="B1",
        site_code="DEEPLINKERP",
        business_key="BK1",
        cost_result_hash="H1",
        payload_hash="P1",
        remote_document="PO-1",
        remote_docstatus=1,
        payload={"items": [{"stable_line_key": "L1"}]},
        lines={"L1": "POI-1"},
        now_text="2026-09-28 10:00:00",
    )

    assert saved == 1
    assert len(fake.links) == 1
    assert fake.links[0]["name"] == "LINK-9"
    assert fake.links[0]["remote_row"] == "POI-1"
    assert fake.links[0]["status"] == "ACTIVE"


# ---- 未知结果核对与重试 ------------------------------------------------------


def test_reconcile_promotes_uncertain_request_when_remote_purchase_is_submitted(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="UNCERTAIN"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {"site": site})

    result = ledger.reconcile_sync_request(
        "SYNC-1",
        inspector=lambda payload, config: _submitted_inspection(),
        now_text="2026-09-28 10:00:00",
    )

    assert result["status"] == "SUCCESS"
    assert result["previous_status"] == "UNCERTAIN"
    assert result["erp_target_doc"] == "PO-1"
    assert result["linked_row_count"] == 2
    assert fake.row["status"] == "SUCCESS"
    assert fake.row["error_message"] == ""
    assert [row["remote_row"] for row in fake.links] == ["POI-1", "POI-2"]


def test_reconcile_corrects_a_failed_request_whose_purchase_actually_exists(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="FAILED"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {})

    result = ledger.reconcile_sync_request(
        "SYNC-1",
        inspector=lambda payload, config: _submitted_inspection(),
        now_text="2026-09-28 10:00:00",
    )

    assert result["status"] == "SUCCESS"
    assert fake.row["status"] == "SUCCESS"


def test_reconcile_keeps_failed_when_the_remote_purchase_is_still_a_draft(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="FAILED"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {})

    result = ledger.reconcile_sync_request(
        "SYNC-1",
        inspector=lambda payload, config: _submitted_inspection(docstatus=0),
        now_text="2026-09-28 10:00:00",
    )

    assert result["status"] == "FAILED"
    assert fake.row["error_code"] == "REMOTE_DOCUMENT_NOT_SUBMITTED"
    assert fake.links == []


def test_reconcile_returns_failed_when_the_remote_has_no_purchase(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="UNCERTAIN"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {})

    result = ledger.reconcile_sync_request(
        "SYNC-1",
        inspector=lambda payload, config: _no_remote_purchase(),
        now_text="2026-09-28 10:00:00",
    )

    assert result["status"] == "FAILED"
    assert result["linked_row_count"] == 0
    assert fake.row["error_code"] == "REMOTE_DOCUMENT_ABSENT"
    assert fake.links == []


def test_reconcile_flags_ambiguous_remote_business_key_for_manual_review(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="UNCERTAIN"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {})

    result = ledger.reconcile_sync_request(
        "SYNC-1",
        inspector=lambda payload, config: _submitted_inspection(ambiguous=True, name="", lines={}),
        now_text="2026-09-28 10:00:00",
    )

    assert result["status"] == "MANUAL_REQUIRED"
    assert fake.row["error_code"] == "AMBIGUOUS_REMOTE_BUSINESS_KEY"
    assert fake.links == []


def test_reconcile_keeps_status_when_the_remote_lookup_fails(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="UNCERTAIN"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {})

    def unreachable(payload, config):
        raise TimeoutError("远端不可达")

    result = ledger.reconcile_sync_request("SYNC-1", inspector=unreachable, now_text="2026-09-28 10:00:00")

    assert result["ok"] is False
    assert result["action"] == "UNKNOWN"
    assert result["status"] == "UNCERTAIN"
    assert fake.row["status"] == "UNCERTAIN"
    assert fake.db.commits == 1


def test_reconcile_skips_requests_that_need_no_reconciliation(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="SUCCESS"))
    monkeypatch.setattr(ledger, "frappe", fake)

    def must_not_touch_remote(payload, config):
        raise AssertionError("已成功的请求不应再触达远端")

    result = ledger.reconcile_sync_request(
        "SYNC-1", inspector=must_not_touch_remote, now_text="2026-09-28 10:00:00"
    )

    assert result["action"] == "SKIP"
    assert result["status"] == "SUCCESS"


def test_retry_never_resends_when_reconcile_found_the_document(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="UNCERTAIN"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {})

    def must_not_execute(rows):
        raise AssertionError("核对已确认远端有单据，不得重发")

    monkeypatch.setattr(ledger, "execute_saved_sync_requests", must_not_execute)

    result = ledger.retry_sync_request(
        "SYNC-1",
        inspector=lambda payload, config: _submitted_inspection(),
        now_text="2026-09-28 10:00:00",
    )

    assert result["executed"] is False
    assert result["status"] == "SUCCESS"


def test_retry_resends_only_after_the_remote_is_confirmed_empty(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row(status="UNCERTAIN"))
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {})
    executed = []
    monkeypatch.setattr(
        ledger,
        "execute_saved_sync_requests",
        lambda rows: executed.append(rows) or {"success_count": 1, "failed_count": 0, "uncertain_count": 0},
    )

    result = ledger.retry_sync_request(
        "SYNC-1",
        inspector=lambda payload, config: _no_remote_purchase(),
        now_text="2026-09-28 10:00:00",
    )

    assert executed == [[{"name": "SYNC-1"}]]
    assert result["executed"] is True
    assert result["status"] == "SUCCESS"


# ---- 批次内定位请求 ----------------------------------------------------------


def test_find_batch_request_name_scopes_the_lookup_to_the_batch(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row())
    monkeypatch.setattr(ledger, "frappe", fake)

    assert ledger.find_batch_request_name("B1", "R1") == "SYNC-1"
    # 同一个请求键在别的批次下不成立，必须返回空而不是命中本批次的请求。
    assert ledger.find_batch_request_name("B-OTHER", "R1") == ""


def test_find_batch_request_name_ignores_blank_request_id(monkeypatch) -> None:
    fake = _LinkFrappe(_request_row())
    monkeypatch.setattr(ledger, "frappe", fake)

    assert ledger.find_batch_request_name("B1", "") == ""


# ---- 成功推送后按响应单号落关联 ----------------------------------------------


def test_record_success_links_uses_the_pushed_document_name(monkeypatch) -> None:
    from overseas_costing.services import erp_client

    fake = _LinkFrappe(_pending_document())
    monkeypatch.setattr(ledger, "frappe", fake)
    monkeypatch.setattr(ledger, "_load_site_config", lambda site: {"site": site})
    seen = []
    monkeypatch.setattr(
        erp_client,
        "read_remote_purchase_state",
        lambda docname, config: seen.append((docname, config))
        or {"docstatus": 1, "lines": {"L1": "POI-1"}},
    )

    saved = ledger._record_success_links(
        fake.row,
        {"business_key": "BK1", "items": [{"stable_line_key": "L1"}]},
        {"ok": True, "erp_target_doc": "PO-9"},
    )

    assert seen == [("PO-9", {"site": "DEEPLINKERP"})]
    assert saved == 1
    assert fake.links[0]["remote_document"] == "PO-9"
    assert fake.links[0]["remote_row"] == "POI-1"
    assert fake.links[0]["remote_docstatus"] == 1


def test_record_success_links_skips_when_the_response_carries_no_document_name(monkeypatch) -> None:
    fake = _LinkFrappe(_pending_document())
    monkeypatch.setattr(ledger, "frappe", fake)

    saved = ledger._record_success_links(
        fake.row,
        {"business_key": "BK1", "items": [{"stable_line_key": "L1"}]},
        {"ok": True},
    )

    assert saved == 0
    assert fake.links == []


def test_site_config_dispatches_the_default_site_to_settings_and_named_sites_to_their_record(
    monkeypatch,
) -> None:
    """配置真源是分裂的，而且不能合并成一个。

    `Overseas Cost ERP Settings` 是单例（issingle=1），只描述默认站点；非默认站点必须去读
    `Overseas Cost ERP Site` 表。线上那张表 0 条 ⇒ 只有默认站点这一路真的跑过，把两者"顺手"
    归一（比如统一走 Settings）不会有任何别的测试变红，但命名站点的 base_url / 鉴权 / 公司
    会一起错掉，而错误现场只在远端表现为 403。把分派关系钉在这里。
    """
    from overseas_costing.services import erp_client, erp_site_service
    from overseas_costing.services.erp_routing_service import DEFAULT_SITE_CODE

    calls: list[str] = []
    monkeypatch.setattr(
        erp_client, "get_erp_push_config", lambda: calls.append("settings") or {"site": "settings"}
    )
    monkeypatch.setattr(
        erp_site_service,
        "get_site_push_config",
        lambda site_code: calls.append(str(site_code)) or {"site": str(site_code)},
    )

    assert ledger._load_site_config(DEFAULT_SITE_CODE) == {"site": "settings"}
    assert ledger._load_site_config("MXSITE") == {"site": "MXSITE"}
    assert calls == ["settings", "MXSITE"]


# --- 远端单据：本批次到底建到了 ERP 的哪张单，点哪里看 --------------------------------

_LINK_ROWS = [
    {"name": "LINK-1", "batch": "B1", "site_code": "MX", "business_key": "BK1",
     "remote_doctype": "Purchase Order", "remote_document": "PO-1", "remote_docstatus": 1},
    # 同一张采购单的每一行物料都是一条关联记录：必须收敛成一张单。
    {"name": "LINK-2", "batch": "B1", "site_code": "MX", "business_key": "BK1",
     "remote_doctype": "Purchase Order", "remote_document": "PO-1", "remote_docstatus": 1},
    {"name": "LINK-3", "batch": "B1", "site_code": "MX", "business_key": "BK1",
     "remote_doctype": "Purchase Order", "remote_document": "PO-2", "remote_docstatus": 0},
    {"name": "LINK-4", "batch": "B1", "site_code": "PROD", "business_key": "BK2",
     "remote_doctype": "Purchase Order", "remote_document": "PO-3", "remote_docstatus": 1},
    # 旧版本的业务键：不属于本次结果。
    {"name": "LINK-5", "batch": "B1", "site_code": "MX", "business_key": "BK-OLD",
     "remote_doctype": "Purchase Order", "remote_document": "PO-9", "remote_docstatus": 1},
    # 没有远端单号的关联行（推送未成或只写了行键）不能变成一张"空单"。
    {"name": "LINK-6", "batch": "B1", "site_code": "MX", "business_key": "BK1",
     "remote_doctype": "Purchase Order", "remote_document": "", "remote_docstatus": 0},
]


def _site_config_by_code(site_code):
    return {"base_url": "https://%s.example.com/api/resource" % str(site_code).lower()}


def test_remote_documents_are_grouped_by_site_with_clickable_links(monkeypatch) -> None:
    monkeypatch.setattr(ledger, "frappe", _FakeFrappe(list(_LINK_ROWS)))
    monkeypatch.setattr(ledger, "_load_site_config", _site_config_by_code)

    result = ledger.list_remote_documents("B1", business_keys=["BK1", "BK2"])

    assert [group["site_code"] for group in result] == ["MX", "PROD"]
    assert result[0]["documents"] == [
        {"name": "PO-1", "doctype": "Purchase Order", "docstatus": 1, "line_count": 2,
         "url": "https://mx.example.com/desk/purchase-order/PO-1"},
        {"name": "PO-2", "doctype": "Purchase Order", "docstatus": 0, "line_count": 1,
         "url": "https://mx.example.com/desk/purchase-order/PO-2"},
    ]
    assert result[1]["documents"][0]["url"] == "https://prod.example.com/desk/purchase-order/PO-3"


def test_remote_documents_only_cover_the_business_keys_of_this_result(monkeypatch) -> None:
    """关联表没有版本列：必须按本次账本行的业务键过滤，别把历史版本建的单当成这次的成果。"""

    monkeypatch.setattr(ledger, "frappe", _FakeFrappe(list(_LINK_ROWS)))
    monkeypatch.setattr(ledger, "_load_site_config", _site_config_by_code)

    result = ledger.list_remote_documents("B1", business_keys=["BK1"])

    names = [document["name"] for group in result for document in group["documents"]]
    assert [group["site_code"] for group in result] == ["MX"]
    assert names == ["PO-1", "PO-2"]
    assert "PO-3" not in names and "PO-9" not in names


def test_remote_documents_without_business_keys_never_touch_the_database(monkeypatch) -> None:
    """没有任何账本请求时「一张单都没有」是确定结论，不该顺手查一次库。"""

    class _Exploding:
        def get_all(self, *args, **kwargs):
            raise AssertionError("没有业务键时不该查询关联表")

    monkeypatch.setattr(ledger, "frappe", _Exploding())

    assert ledger.list_remote_documents("B1", business_keys=[]) == []
    assert ledger.list_remote_documents("B1", business_keys=[None, ""]) == []
    assert ledger.list_remote_documents("B1") == []


def test_remote_documents_keep_the_document_number_when_the_link_cannot_be_built(monkeypatch) -> None:
    """站点配置读不出来时单号照给、链接留空：页面据此说明"地址拼不出来"，而不是假装没有单。"""

    monkeypatch.setattr(ledger, "frappe", _FakeFrappe(list(_LINK_ROWS)))

    def _missing(site_code):
        raise RuntimeError("站点配置不存在")

    monkeypatch.setattr(ledger, "_load_site_config", _missing)

    result = ledger.list_remote_documents("B1", business_keys=["BK1"])

    documents = result[0]["documents"]
    assert [document["name"] for document in documents] == ["PO-1", "PO-2"]
    assert [document["url"] for document in documents] == ["", ""]


def test_remote_documents_leave_out_links_the_target_site_cannot_resolve(monkeypatch) -> None:
    """站点没配接口地址（或配的不是 http(s)）时不硬拼相对路径，链接留空。"""

    monkeypatch.setattr(ledger, "frappe", _FakeFrappe(list(_LINK_ROWS)))
    monkeypatch.setattr(ledger, "_load_site_config", lambda site_code: {"base_url": ""})

    documents = ledger.list_remote_documents("B1", business_keys=["BK1"])[0]["documents"]

    assert [document["url"] for document in documents] == ["", ""]
