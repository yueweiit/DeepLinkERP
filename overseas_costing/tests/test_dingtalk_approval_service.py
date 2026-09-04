from __future__ import annotations

import json


def test_batch_detail_normalizes_main_linked_comments_and_archives(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class FakeDB:
        @staticmethod
        def get_value(doctype, name, fields, as_dict=False):
            assert doctype == "Overseas Cost Batch"
            assert name == "BATCH-1"
            return {
                "name": "BATCH-1",
                "batch_no": "OA-001",
                "source_type": "oa_logistics",
                "source_approval_no": "OA-001",
                "source_instance_id": "PROC-MAIN",
                "extra_json": json.dumps(
                    {"linked_purchase_approvals": [{"source_instance_id": "PROC-BUY"}]},
                    ensure_ascii=False,
                ),
            }

    class FakeFrappe:
        db = FakeDB()

    class FakeSource:
        calls = []

        def get_instance_bundle(self, instance_ids):
            self.calls.append(list(instance_ids))
            return {
                "instances": {
                    "PROC-MAIN": {
                        "processInstanceId": "PROC-MAIN",
                        "businessId": "OA-001",
                        "title": "国际物流",
                        "status": "COMPLETED",
                        "originatorUserId": "USER-1",
                        "originatorUserName": "张三",
                        "formComponentValues": [{"name": "物流方式", "value": "海运"}],
                        "operationRecords": [{
                            "userId": "USER-2",
                            "userName": "李四",
                            "date": "2026-09-01T10:00:00+08:00",
                            "remark": "规格33*20*23，重量42.05kg，1套模具",
                        }],
                    },
                    "PROC-BUY": {
                        "processInstanceId": "PROC-BUY",
                        "businessId": "OA-002",
                        "title": "采购支出",
                        "formComponentValues": [],
                    },
                },
                "attachments": [{
                    "process_instance_id": "PROC-MAIN",
                    "file_id": "FILE-1",
                    "file_name": "装箱计划.xlsx",
                    "attachment_origin": "form",
                    "archive_status": "archived",
                    "archive_method": "legacy_file_url",
                    "content_quality": "original",
                }],
                "health": {"source_lag_seconds": 9, "source_updated_at": "2026-09-04T06:00:00Z"},
            }

    source = FakeSource()
    monkeypatch.setattr(service, "frappe", FakeFrappe)
    monkeypatch.setattr(service, "_get_approval_source", lambda: source)
    monkeypatch.setattr(service, "_trusted_linked_instance_ids", lambda _payload: ["PROC-BUY"])

    result = service.get_batch_dingtalk_approval_detail("BATCH-1")

    assert source.calls == [["PROC-MAIN", "PROC-BUY"]]
    assert result["main_approval"]["form_fields"] == [{"label": "物流方式", "value": "海运"}]
    assert result["main_approval"]["attachments"][0]["archive_method"] == "legacy_file_url"
    assert result["main_approval"]["attachments"][0]["comment_user_name"] == ""
    assert result["main_approval"]["timeline"][0]["packing_candidate"] is True
    assert len(result["main_approval"]["timeline"][0]["source_id"]) == 64
    assert result["linked_purchase_approvals"][0]["instance_id"] == "PROC-BUY"
    assert result["source_lag_seconds"] == 9
    assert "raw_payload" not in result["main_approval"]


def test_form_fields_render_structured_values_without_download_credentials() -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    fields = service._form_fields({
        "formComponentValues": [
            {
                "name": "装箱单附件",
                "value": json.dumps([{
                    "fileName": "装箱计划.xlsx",
                    "fileId": "FILE-SECRET",
                    "spaceId": "SPACE-SECRET",
                    "thumbnail": {"authMediaId": "AUTH-SECRET"},
                }], ensure_ascii=False),
            },
            {
                "name": "货物信息",
                "value": json.dumps([{
                    "rowNumber": "ROW-SECRET",
                    "rowValue": [
                        {"label": "物料编码", "value": "FL000429", "key": "FIELD-SECRET"},
                        {"label": "数量", "value": "100000", "key": "FIELD-SECRET-2"},
                    ],
                }], ensure_ascii=False),
            },
        ],
    })

    assert fields == [
        {"label": "装箱单附件", "value": "装箱计划.xlsx"},
        {"label": "货物信息", "value": "物料编码：FL000429；数量：100000"},
    ]
    rendered = json.dumps(fields, ensure_ascii=False)
    assert "SECRET" not in rendered


def test_batch_detail_resolves_actor_names_and_audits_excluded_linked_approval(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class FakeDB:
        @staticmethod
        def get_value(_doctype, _name, _fields, as_dict=False):
            return {
                "name": "BATCH-1",
                "batch_no": "OA-001",
                "source_type": "oa_logistics",
                "source_approval_no": "OA-001",
                "source_instance_id": "PROC-MAIN",
                "extra_json": json.dumps({
                    "linked_purchase_approvals": [
                        {"source_instance_id": "PROC-BUY-VALID"},
                        {"source_instance_id": "PROC-BUY-REFUSED"},
                    ]
                }),
            }

    class FakeFrappe:
        db = FakeDB()

    class FakeSource:
        @staticmethod
        def get_instance_bundle(instance_ids):
            assert instance_ids == ["PROC-MAIN", "PROC-BUY-VALID", "PROC-BUY-REFUSED"]
            return {
                "instances": {
                    "PROC-MAIN": {
                        "corpId": "CORP-1",
                        "processInstanceId": "PROC-MAIN",
                        "businessId": "OA-001",
                        "status": "COMPLETED",
                        "result": "agree",
                        "originatorUserId": "0217304551217188371",
                        "operationRecords": [
                            {"userId": "16693147192083157833", "type": "EXECUTE_TASK_NORMAL", "date": "2026-09-04"},
                            {"userId": "UNKNOWN", "type": "PROCESS_CC", "date": "2026-09-04"},
                            {"userId": "bpms_system", "type": "SYSTEM", "date": "2026-09-04"},
                        ],
                    },
                    "PROC-BUY-VALID": {
                        "corpId": "CORP-1",
                        "processInstanceId": "PROC-BUY-VALID",
                        "businessId": "PUR-VALID",
                        "status": "COMPLETED",
                        "result": "agree",
                        "originatorUserId": "USER-3",
                    },
                    "PROC-BUY-REFUSED": {
                        "corpId": "CORP-1",
                        "processInstanceId": "PROC-BUY-REFUSED",
                        "businessId": "PUR-REFUSED",
                        "status": "COMPLETED",
                        "result": "refuse",
                        "originatorUserId": "USER-4",
                    },
                },
                "attachments": [{
                    "corp_id": "CORP-1",
                    "process_instance_id": "PROC-MAIN",
                    "file_id": "FILE-1",
                    "file_name": "评论附件.pdf",
                    "attachment_origin": "comment",
                    "archive_status": "archived",
                    "comment_user_id": "USER-3",
                }],
                "actors": {"CORP-1": {
                    "0217304551217188371": {"name": "李仲华"},
                    "16693147192083157833": {"name": "周汉琴"},
                    "USER-3": {"name": "陈一"},
                    "USER-4": {"name": "王二"},
                }},
                "health": {},
            }

    monkeypatch.setattr(service, "frappe", FakeFrappe)
    monkeypatch.setattr(service, "_get_approval_source", lambda: FakeSource())
    monkeypatch.setattr(
        service,
        "_trusted_linked_instance_ids",
        lambda _payload: ["PROC-BUY-VALID", "PROC-BUY-REFUSED"],
    )

    result = service.get_batch_dingtalk_approval_detail("BATCH-1")

    main = result["main_approval"]
    assert main["originator_user_name"] == "李仲华"
    assert main["originator_name_source"] == "directory"
    assert main["timeline"][0]["user_name"] == "周汉琴"
    assert main["timeline"][0]["user_name_source"] == "directory"
    assert main["timeline"][1]["user_name_unresolved"] is True
    assert main["timeline"][2]["user_name"] == "系统"
    assert main["attachments"][0]["comment_user_name"] == "陈一"
    assert main["raw_status"] == "COMPLETED"
    assert main["raw_result"] == "agree"
    assert main["process_status"] == "COMPLETED"
    assert main["approval_result"] == "agree"
    assert main["effective_status"] == "COMPLETED"
    assert main["excluded"] is False

    assert [row["instance_id"] for row in result["linked_purchase_approvals"]] == ["PROC-BUY-VALID"]
    excluded = result["excluded_linked_purchase_approvals"][0]
    assert excluded["instance_id"] == "PROC-BUY-REFUSED"
    assert excluded["originator_user_name"] == "王二"
    assert excluded["effective_status"] == "REJECTED"
    assert excluded["excluded"] is True
    assert excluded["exclusion_reason"] == "审批结果为拒绝"


def test_materialize_rechecks_existing_attachment_while_batch_is_locked(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    sql_calls = []

    class FakeDB:
        @staticmethod
        def sql(query, params):
            sql_calls.append((query, params))

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_all(*_args, **_kwargs):
            return [{
                "name": "ATT-EXISTING",
                "parse_result_json": json.dumps({
                    "process_instance_id": "PROC-MAIN",
                    "file_id": "FILE-1",
                }),
            }]

        @staticmethod
        def get_doc(*_args, **_kwargs):
            raise AssertionError("duplicate attachment must not be inserted")

    monkeypatch.setattr(service, "frappe", FakeFrappe)
    monkeypatch.setattr(service, "get_batch_dingtalk_approval_detail", lambda _batch: {
        "ok": True,
        "main_approval": {
            "instance_id": "PROC-MAIN",
            "attachments": [{
                "file_id": "FILE-1",
                "attachment_name": "",
                "archive_status": "archived",
            }],
        },
        "linked_purchase_approvals": [],
    })

    result = service.materialize_batch_dingtalk_attachment("BATCH-1", "PROC-MAIN", "FILE-1")

    assert result == {"ok": True, "attachment_name": "ATT-EXISTING", "created": False}
    assert "FOR UPDATE" in sql_calls[0][0]


def test_materialize_allows_download_from_excluded_approval_audit(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class FakeFrappe:
        @staticmethod
        def get_all(*_args, **_kwargs):
            return [{
                "name": "ATT-EXCLUDED",
                "parse_result_json": json.dumps({
                    "process_instance_id": "PROC-REFUSED",
                    "file_id": "FILE-REFUSED",
                }),
            }]

    monkeypatch.setattr(service, "frappe", FakeFrappe)
    monkeypatch.setattr(service, "get_batch_dingtalk_approval_detail", lambda _batch: {
        "ok": True,
        "main_approval": {"instance_id": "PROC-MAIN", "attachments": []},
        "linked_purchase_approvals": [],
        "excluded_linked_purchase_approvals": [{
            "instance_id": "PROC-REFUSED",
            "excluded": True,
            "attachments": [{
                "file_id": "FILE-REFUSED",
                "attachment_name": "ATT-EXCLUDED",
                "archive_status": "archived",
            }],
        }],
    })

    result = service.materialize_batch_dingtalk_attachment(
        "BATCH-1", "PROC-REFUSED", "FILE-REFUSED"
    )

    assert result == {"ok": True, "attachment_name": "ATT-EXCLUDED", "created": False}


def test_materialize_backfills_audit_policy_on_existing_excluded_attachment(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class FakeAttachmentDoc:
        parse_result_json = json.dumps({
            "process_instance_id": "PROC-REFUSED",
            "file_id": "FILE-REFUSED",
        })
        attachment_type = "Packing List"
        save_count = 0

        def save(self, **_kwargs):
            self.save_count += 1

    attachment_doc = FakeAttachmentDoc()

    class FakeFrappe:
        @staticmethod
        def get_doc(doctype, name):
            assert (doctype, name) == ("Overseas Cost Attachment", "ATT-EXCLUDED")
            return attachment_doc

    monkeypatch.setattr(service, "frappe", FakeFrappe)
    monkeypatch.setattr(service, "get_batch_dingtalk_approval_detail", lambda _batch: {
        "ok": True,
        "main_approval": {"instance_id": "PROC-MAIN", "attachments": []},
        "linked_purchase_approvals": [],
        "excluded_linked_purchase_approvals": [{
            "instance_id": "PROC-REFUSED",
            "excluded": True,
            "exclusion_reason": "审批结果为拒绝",
            "attachments": [{
                "file_id": "FILE-REFUSED",
                "attachment_name": "ATT-EXCLUDED",
                "archive_status": "archived",
            }],
        }],
    })

    result = service.materialize_batch_dingtalk_attachment(
        "BATCH-1", "PROC-REFUSED", "FILE-REFUSED"
    )

    assert result == {"ok": True, "attachment_name": "ATT-EXCLUDED", "created": False}
    snapshot = json.loads(attachment_doc.parse_result_json)
    assert snapshot["approval_excluded"] is True
    assert snapshot["cost_source_allowed"] is False
    assert snapshot["exclusion_reason"] == "审批结果为拒绝"
    assert attachment_doc.attachment_type == "Other"
    assert attachment_doc.save_count == 1


def test_materialize_allows_attachment_from_excluded_linked_approval(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    monkeypatch.setattr(service, "frappe", object())
    monkeypatch.setattr(service, "get_batch_dingtalk_approval_detail", lambda _batch: {
        "ok": True,
        "main_approval": {"instance_id": "PROC-MAIN", "attachments": []},
        "linked_purchase_approvals": [],
        "excluded_linked_purchase_approvals": [{
            "instance_id": "PROC-REFUSED",
            "excluded": True,
            "attachments": [{
                "file_id": "FILE-EXCLUDED",
                "attachment_name": "ATT-EXCLUDED",
                "archive_status": "archived",
            }],
        }],
    })

    result = service.materialize_batch_dingtalk_attachment(
        "BATCH-1",
        "PROC-REFUSED",
        "FILE-EXCLUDED",
    )

    assert result == {"ok": True, "attachment_name": "ATT-EXCLUDED", "created": False}


def test_materialized_excluded_attachment_is_persisted_as_audit_only(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    inserted = []

    class FakeDoc:
        name = "ATT-NEW"

        def __init__(self, payload):
            self.payload = payload

        def insert(self, **_kwargs):
            inserted.append(self.payload)
            return self

    class FakeDB:
        @staticmethod
        def sql(*_args, **_kwargs):
            return []

        @staticmethod
        def get_value(_doctype, _name, _fields, as_dict=False):
            return {"name": "BATCH-1", "current_version": "VERSION-1"}

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_all(*_args, **_kwargs):
            return []

        @staticmethod
        def get_doc(payload):
            return FakeDoc(payload)

    monkeypatch.setattr(service, "frappe", FakeFrappe)
    monkeypatch.setattr(service, "get_batch_dingtalk_approval_detail", lambda _batch: {
        "ok": True,
        "main_approval": {"instance_id": "PROC-MAIN", "attachments": []},
        "linked_purchase_approvals": [],
        "excluded_linked_purchase_approvals": [{
            "instance_id": "PROC-REFUSED",
            "business_id": "PUR-REFUSED",
            "excluded": True,
            "exclusion_reason": "审批结果为拒绝",
            "attachments": [{
                "file_id": "FILE-REFUSED",
                "file_name": "装箱单.xlsx",
                "process_instance_id": "PROC-REFUSED",
                "archive_status": "archived",
                "packing_candidate": True,
            }],
        }],
    })

    result = service.materialize_batch_dingtalk_attachment(
        "BATCH-1", "PROC-REFUSED", "FILE-REFUSED"
    )

    assert result["created"] is True
    assert inserted[0]["attachment_type"] == "Other"
    snapshot = json.loads(inserted[0]["parse_result_json"])
    assert snapshot["approval_excluded"] is True
    assert snapshot["cost_source_allowed"] is False
    assert snapshot["exclusion_reason"] == "审批结果为拒绝"
