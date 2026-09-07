"""费用待办 API 的权限、大小和字段边界测试。"""

import importlib
import json
import sys
from types import ModuleType

import pytest


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.fees", None)
    return importlib.import_module("overseas_costing.api.fees")


def test_fee_worklist_checks_read_permission_before_query(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_fee_workflow_permission",
        lambda batch, operation: calls.append((batch, operation)) or "BATCH-DOC",
    )
    monkeypatch.setattr(
        api.fee_service,
        "get_fee_worklist",
        lambda batch, version: {"batch": batch, "version": version},
    )

    assert api.get_fee_worklist("BATCH-NO", "V1") == {"batch": "BATCH-DOC", "version": "V1"}
    assert calls == [("BATCH-NO", "read")]


def test_save_fee_rejects_client_controlled_fields(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_fee_workflow_permission", lambda *_args: "BATCH-DOC")
    monkeypatch.setattr(
        api.fee_service,
        "save_fee",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not save")),
    )

    with pytest.raises(ValueError, match="不允许字段"):
        api.save_fee(
            "BATCH",
            "V1",
            json.dumps({"logical_fee_key": "TAX", "amount_status": "ACTUAL", "allocated_amount": 1}),
            "EDIT",
            "MOD",
        )
    with pytest.raises(ValueError, match="过大"):
        api.save_fee("BATCH", "V1", "x" * 100_000, "EDIT", "MOD")


def test_link_evidence_checks_batch_and_attachment_permissions(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_fee_workflow_permission",
        lambda batch, operation: calls.append(("batch", batch, operation)) or "BATCH-DOC",
    )
    monkeypatch.setattr(
        api,
        "require_attachment_permission",
        lambda attachment, ptype: calls.append(("attachment", attachment, ptype)) or "ATT-DOC",
    )
    monkeypatch.setattr(api.fee_service, "link_fee_evidence", lambda *args, **_kwargs: {"args": args})

    result = api.link_fee_evidence("BATCH", "RULE-1", "ATT-1", "tax_certificate", "EDIT", "MOD")

    assert calls == [("batch", "BATCH", "write"), ("attachment", "ATT-1", "read")]
    assert result["args"][:3] == ("BATCH-DOC", "RULE-1", "ATT-DOC")


def test_evidence_status_and_completion_hash_are_server_bounded(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_fee_workflow_permission", lambda *_args: "BATCH-DOC")

    with pytest.raises(ValueError, match="凭证状态"):
        api.set_fee_evidence_status("BATCH", "E1", "CLIENT_VALID", "", "EDIT", "MOD")
    with pytest.raises(ValueError, match="64 位"):
        api.confirm_all_fees_complete("BATCH", "V1", "client-hash", "EDIT", "MOD")
