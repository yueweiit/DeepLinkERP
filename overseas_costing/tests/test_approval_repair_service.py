from __future__ import annotations

import importlib
import sys
from types import ModuleType


def test_classification_distinguishes_available_missing_mismatch_and_excluded() -> None:
    from overseas_costing.services.approval_repair_service import classify_approval_sources

    batches = [
        {"name": "B-OK", "batch_no": "OA-1", "source_approval_no": "OA-1", "source_instance_id": "I-1"},
        {"name": "B-MISSING", "batch_no": "OA-2", "source_approval_no": "OA-2", "source_instance_id": "I-2"},
        {"name": "B-MISMATCH", "batch_no": "OA-3", "source_approval_no": "OA-3", "source_instance_id": "I-3"},
        {"name": "B-EXCLUDED", "batch_no": "OA-4", "source_approval_no": "OA-4", "source_instance_id": "I-4"},
        {"name": "B-NO-ID", "batch_no": "OA-5", "source_approval_no": "OA-5", "source_instance_id": ""},
    ]
    coverage = {
        "by_instance": {
            "I-1": {"process_instance_id": "I-1", "business_id": "OA-1", "process_code": "LOG", "status": "RUNNING", "result": ""},
            "I-3": {"process_instance_id": "I-3", "business_id": "OTHER", "process_code": "LOG", "status": "RUNNING", "result": ""},
            "I-4": {"process_instance_id": "I-4", "business_id": "OA-4", "process_code": "LOG", "status": "TERMINATED", "result": ""},
        },
        "by_business": {"OA-5": [{"process_instance_id": "I-5", "business_id": "OA-5", "process_code": "LOG"}]},
    }
    statuses = {"I-2": {"status": "retry", "attempts": 1}}

    result = classify_approval_sources(batches, coverage, statuses, expected_process_code="LOG")

    assert {row["batch_name"]: row["state"] for row in result} == {
        "B-OK": "available",
        "B-MISSING": "repairing",
        "B-MISMATCH": "manual_required",
        "B-EXCLUDED": "excluded",
        "B-NO-ID": "instance_id_recoverable",
    }


def test_global_audit_uses_bulk_queries_and_enqueues_only_missing(monkeypatch) -> None:
    from overseas_costing.services import approval_repair_service as service

    class Frappe:
        session = type("Session", (), {"user": "Administrator"})()

        @staticmethod
        def get_all(*_args, **_kwargs):
            return [
                {"name": "B1", "batch_no": "OA-1", "source_approval_no": "OA-1", "source_instance_id": "I-1", "source_type": "oa_logistics"},
                {"name": "B2", "batch_no": "OA-2", "source_approval_no": "OA-2", "source_instance_id": "I-2", "source_type": "oa_logistics"},
            ]

    class Source:
        coverage_calls = 0
        status_calls = 0

        def get_reference_coverage(self, instance_ids, business_ids):
            self.coverage_calls += 1
            assert instance_ids == ["I-1", "I-2"]
            assert business_ids == ["OA-1", "OA-2"]
            return {"by_instance": {"I-1": {"process_instance_id": "I-1", "business_id": "OA-1", "process_code": "LOG", "status": "RUNNING"}}, "by_business": {}}

        def get_repair_statuses(self, ids):
            self.status_calls += 1
            assert ids == ["I-1", "I-2"]
            return {}

        @staticmethod
        def get_process_context(_code):
            return {"corp_id": "CORP-1"}

        @staticmethod
        def get_instances(_ids):
            return {}

    class Submitter:
        calls = []

        def request_repair(self, **kwargs):
            self.calls.append(kwargs)
            return 9

    source = Source()
    submitter = Submitter()
    monkeypatch.setattr(service, "frappe", Frappe())
    monkeypatch.setattr(service, "_get_approval_source", lambda: source)
    monkeypatch.setattr(service, "_get_repair_submitter", lambda: submitter)
    monkeypatch.setattr(service, "resolve_logistics_process_code", lambda: "LOG")

    result = service.audit_and_queue_dingtalk_approval_repairs()

    assert source.coverage_calls == 1
    assert source.status_calls == 1
    assert result["counts"] == {"available": 1, "missing_in_postgres": 1}
    assert len(submitter.calls) == 1
    assert submitter.calls[0]["process_instance_id"] == "I-2"
    assert submitter.calls[0]["trigger_source"] == "costing_audit"


def test_request_api_requires_batch_write_permission(monkeypatch) -> None:
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    fake_frappe.session = type("Session", (), {"user": "Administrator"})()
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.workbench", None)
    api = importlib.import_module("overseas_costing.api.workbench")

    calls = []
    monkeypatch.setattr(api, "require_batch_permission", lambda batch, ptype: calls.append((batch, ptype)) or "B-DOC")
    monkeypatch.setattr(api.approval_repair_service, "request_batch_repair", lambda batch, requested_by: {"ok": True, "batch_name": batch, "requested_by": requested_by})
    monkeypatch.setattr(api.frappe, "session", type("Session", (), {"user": "finance@example.com"})())

    result = api.request_batch_dingtalk_approval_repair("OA-1")

    assert calls == [("OA-1", "write")]
    assert result["batch_name"] == "B-DOC"


def test_successful_repair_reconciles_from_postgres_without_auto_calculation(monkeypatch) -> None:
    from overseas_costing.services import approval_repair_service as service

    class Source:
        @staticmethod
        def get_instances(ids):
            assert ids == ["I-1"]
            return {"I-1": {"processInstanceId": "I-1", "businessId": "OA-1"}}

    saved = []
    monkeypatch.setattr(service, "summarize_approval", lambda payload, process_instance_id="": {
        "source_instance_id": process_instance_id,
        "source_approval_no": payload["businessId"],
    })
    monkeypatch.setattr(service, "save_sea_approvals_to_erp", lambda result, **kwargs: saved.append((result, kwargs)) or {
        "ok": True, "items": [{"batch_name": "B1"}], "failed_items": [],
    })
    monkeypatch.setattr(service, "_mark_repair_reconciled", lambda *_args, **_kwargs: None)

    result = service._reconcile_successful_repairs(
        batches=[{"name": "B1", "source_instance_id": "I-1", "extra_json": "{}"}],
        items=[{"batch_name": "B1", "process_instance_id": "I-1", "state": "available", "repair_status": {"id": 7, "status": "success"}}],
        source=Source(),
    )

    assert result["reconciled_count"] == 1
    assert saved[0][1] == {"recalculate_after_sync": False}


def test_linked_purchase_gap_is_submitted_with_purchase_purpose(monkeypatch) -> None:
    from overseas_costing.services import approval_repair_service as service

    monkeypatch.setattr(service, "extract_linked_purchase_approvals", lambda _payload: [{
        "source_instance_id": "BUY-1", "source_approval_no": "PUR-1",
    }])
    items = service._linked_purchase_repair_items(
        main_items=[{"batch_name": "B1", "process_instance_id": "MAIN", "state": "available"}],
        main_payloads={"MAIN": {"processInstanceId": "MAIN"}},
        coverage={"by_instance": {}, "by_business": {}},
        repair_statuses={},
        expected_process_code="PURCHASE",
    )

    assert items == [{
        "batch_name": "B1",
        "process_instance_id": "BUY-1",
        "expected_business_id": "PUR-1",
        "expected_process_code": "PURCHASE",
        "expected_purpose": "purchase_expense",
        "state": "missing_in_postgres",
        "reason_code": "APPROVAL_NOT_SYNCED",
        "reason": "综合成本已保存审批引用，但同步库中尚无该流程。",
    }]
