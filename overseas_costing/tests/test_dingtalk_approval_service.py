from __future__ import annotations

import json

import pytest


def _oa_attachment_row(name: str, *, version: str = "VERSION-1", archived: bool) -> dict:
    snapshot = {
        "process_instance_id": "PROC-MAIN",
        "file_id": "FILE-1",
    }
    if archived:
        snapshot["settlement_document"] = {
            "document_id": "DOC-1",
            "source_id": "SOURCE-1",
            "fingerprint": "FINGERPRINT-1",
            "manifest": {
                "process_instance_id": "PROC-MAIN",
                "file_id": "FILE-1",
                "sha256": "a" * 64,
            },
        }
    return {
        "name": name,
        "version": version,
        "file_name": "fuel.png",
        "file_url": "/private/files/fuel.png",
        "modified": "2026-09-21 12:53:11",
        "parse_result_json": json.dumps(snapshot),
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_local_attachment_map_prefers_current_fully_archived_row_independent_of_db_order(
    monkeypatch, reverse
) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    rows = [
        _oa_attachment_row("ATT-TEMP", archived=False),
        _oa_attachment_row("ATT-CANONICAL", archived=True),
    ]
    if reverse:
        rows.reverse()

    class FakeFrappe:
        @staticmethod
        def get_list(*_args, **_kwargs):
            return rows

    monkeypatch.setattr(service, "frappe", FakeFrappe)

    result = service._local_attachment_map("BATCH-1", current_version="VERSION-1")

    assert result[("PROC-MAIN", "FILE-1")]["name"] == "ATT-CANONICAL"


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


def test_missing_main_returns_structured_repair_state_not_false_unlinked_message(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class DB:
        @staticmethod
        def get_value(*_args, **_kwargs):
            return {
                "name": "B1", "batch_no": "OA-1", "source_type": "oa_logistics",
                "source_approval_no": "OA-1", "source_instance_id": "PROC-MISSING", "extra_json": "{}",
            }

    class Source:
        @staticmethod
        def get_instance_bundle(_ids):
            return {"instances": {}, "attachments": [], "health": {}}

        @staticmethod
        def get_repair_statuses(_ids):
            return {"PROC-MISSING": {"status": "retry", "attempts": 2, "error_code": "HTTP_500", "error_message": "temporary"}}

    monkeypatch.setattr(service, "frappe", type("F", (), {"db": DB()})())
    monkeypatch.setattr(service, "_get_approval_source", lambda: Source())

    result = service.get_batch_dingtalk_approval_detail("B1")

    assert result["ok"] is False
    assert result["source_state"]["code"] == "repairing"
    assert result["source_state"]["purchase_link_state"] == "unknown"
    assert result["repair_status"]["attempts"] == 2
    assert "正在补同步" in result["message"]


def test_missing_postgres_config_returns_structured_unavailable_state(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class DB:
        @staticmethod
        def get_value(*_args, **_kwargs):
            return {
                "name": "B1",
                "batch_no": "OA-1",
                "source_type": "oa_logistics",
                "source_approval_no": "OA-1",
                "source_instance_id": "PROC-1",
                "extra_json": "{}",
            }

    def fail_source():
        raise ValueError("missing PostgreSQL OA source config")

    monkeypatch.setattr(service, "frappe", type("F", (), {"db": DB()})())
    monkeypatch.setattr(service, "_get_approval_source", fail_source)

    result = service.get_batch_dingtalk_approval_detail("B1")

    assert result["ok"] is False
    assert result["data_source"] == "postgres"
    assert result["source_state"]["code"] == "data_source_unavailable"
    assert result["source_state"]["failure_code"] == "missing_postgres_config"
    assert result["source_state"]["repairable"] is False
    assert "PostgreSQL OA" in result["message"]


def test_main_payload_links_are_trusted_even_when_old_batch_trace_is_empty(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class DB:
        @staticmethod
        def get_value(*_args, **_kwargs):
            return {
                "name": "B1", "batch_no": "OA-1", "source_type": "oa_logistics",
                "source_approval_no": "OA-1", "source_instance_id": "MAIN", "extra_json": "{}",
            }

    class Source:
        calls = []

        def get_instance_bundle(self, ids):
            self.calls.append(list(ids))
            if len(self.calls) == 1:
                return {"instances": {"MAIN": {"processInstanceId": "MAIN", "businessId": "OA-1", "status": "RUNNING"}}, "attachments": [], "health": {}}
            return {"instances": {"BUY": {"processInstanceId": "BUY", "businessId": "PUR-1", "status": "COMPLETED", "result": "agree"}}, "attachments": [], "health": {}}

    source = Source()
    monkeypatch.setattr(service, "frappe", type("F", (), {"db": DB()})())
    monkeypatch.setattr(service, "_get_approval_source", lambda: source)
    monkeypatch.setattr(service, "_trusted_linked_instance_ids", lambda _payload: ["BUY"])

    result = service.get_batch_dingtalk_approval_detail("B1")

    assert source.calls == [["MAIN"], ["BUY"]]
    assert result["source_state"]["purchase_link_state"] == "available"
    assert result["linked_purchase_approvals"][0]["instance_id"] == "BUY"


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


def test_attachment_item_keeps_workflow_field_identity_without_exposing_credentials() -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    item = service._attachment_item({
        "process_instance_id": "PROC-1",
        "file_id": "FILE-1",
        "file_name": "任意名称.xlsx",
        "source_field": "装箱单附件（Excel）",
        "component_id": "COMPONENT-1",
        "auth_media_id": "SECRET",
        "archive_status": "archived",
    }, None)

    assert item["source_field"] == "装箱单附件（Excel）"
    assert item["workflow_field_id"] == "COMPONENT-1"
    assert "SECRET" not in repr(item)


def test_attachment_field_identity_is_resolved_from_trusted_approval_component() -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    payload = {
        "formComponentValues": [{
            "name": "装箱单附件（Excel）",
            "componentId": "COMPONENT-PACKING-EXCEL",
            "value": json.dumps([{
                "fileName": "指环扣+亮甲包装袋2.0+宠物用品发货清单-packing list2026.9.5.xlsx",
                "fileId": "FILE-PACKING-1",
                "spaceId": "SPACE-SECRET",
                "authMediaId": "AUTH-SECRET",
            }], ensure_ascii=False),
        }],
    }

    identities = service._attachment_field_identities(payload)

    assert identities == {
        "FILE-PACKING-1": {
            "source_field": "装箱单附件（Excel）",
            "workflow_field_id": "COMPONENT-PACKING-EXCEL",
        },
    }
    assert "SECRET" not in repr(identities)


def test_batch_detail_enriches_archive_attachment_from_approval_component(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    class DB:
        @staticmethod
        def get_value(*_args, **_kwargs):
            return {
                "name": "B1", "batch_no": "OA-1", "source_type": "oa_logistics",
                "source_approval_no": "OA-1", "source_instance_id": "MAIN", "extra_json": "{}",
            }

    class Source:
        @staticmethod
        def get_instance_bundle(_ids):
            return {
                "instances": {
                    "MAIN": {
                        "processInstanceId": "MAIN",
                        "businessId": "OA-1",
                        "status": "COMPLETED",
                        "formComponentValues": [{
                            "name": "装箱单附件（Excel）",
                            "id": "PACKING-FIELD",
                            "componentType": "DDAttachment",
                            "extValue": json.dumps([{
                                "fileName": "任意文件名.xlsx",
                                "fileId": "FILE-1",
                                "spaceId": "SPACE-SECRET",
                            }], ensure_ascii=False),
                        }],
                    },
                },
                "attachments": [{
                    "process_instance_id": "MAIN",
                    "file_id": "FILE-1",
                    "file_name": "任意文件名.xlsx",
                    "source_field": "其他附件",
                    "component_id": "WRONG-FIELD",
                    "attachment_origin": "form",
                    "archive_status": "archived",
                }],
                "health": {},
            }

    monkeypatch.setattr(service, "frappe", type("F", (), {"db": DB()})())
    monkeypatch.setattr(service, "_get_approval_source", lambda: Source())

    result = service.get_batch_dingtalk_approval_detail("B1")

    attachment = result["main_approval"]["attachments"][0]
    assert attachment["source_field"] == "装箱单附件（Excel）"
    assert attachment["workflow_field_id"] == "PACKING-FIELD"
    assert attachment["packing_candidate"] is True
    assert "SECRET" not in repr(attachment)


def test_batch_detail_discovers_unindexed_workflow_attachment_from_approval_component(monkeypatch) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    file_name = "指环扣+亮甲包装袋2.0+宠物用品发货清单-packing list2026.9.5.xlsx"

    class DB:
        @staticmethod
        def get_value(*_args, **_kwargs):
            return {
                "name": "B1", "batch_no": "OA-1", "source_type": "oa_logistics",
                "source_approval_no": "OA-1", "source_instance_id": "MAIN", "extra_json": "{}",
            }

    class Source:
        archive_ready = False

        @staticmethod
        def get_instance_bundle(_ids):
            return {
                "instances": {
                    "MAIN": {
                        "processInstanceId": "MAIN",
                        "businessId": "OA-1",
                        "status": "COMPLETED",
                        "formComponentValues": [{
                            "name": "装箱单附件（Excel）",
                            "componentId": "PACKING-FIELD",
                            "componentType": "DDAttachment",
                            "extValue": json.dumps([{
                                "fileName": file_name,
                                "fileId": "FILE-PACKING",
                                "spaceId": "SPACE-PACKING",
                                "fileSize": 9876,
                                "authMediaId": "AUTH-SECRET",
                            }], ensure_ascii=False),
                        }],
                    },
                },
                # The authoritative form already exposes the file, but the archive
                # index has not produced its row yet.
                "attachments": [],
                "health": {},
            }

        @staticmethod
        def get_attachment_manifest(process_instance_id, file_id):
            assert (process_instance_id, file_id) == ("MAIN", "FILE-PACKING")
            if not Source.archive_ready:
                return None
            return {
                "process_instance_id": process_instance_id,
                "file_id": file_id,
                "archive_status": "archived",
                "archive_method": "dingtalk_original",
                "content_quality": "original",
            }

    monkeypatch.setattr(service, "frappe", type("F", (), {"db": DB()})())
    monkeypatch.setattr(service, "_get_approval_source", lambda: Source())

    result = service.get_batch_dingtalk_approval_detail("B1")

    assert result["ok"] is True
    assert len(result["main_approval"]["attachments"]) == 1
    attachment = result["main_approval"]["attachments"][0]
    assert attachment["file_name"] == file_name
    assert attachment["file_id"] == "FILE-PACKING"
    assert attachment["space_id"] == "SPACE-PACKING"
    assert attachment["source_field"] == "装箱单附件（Excel）"
    assert attachment["workflow_field_id"] == "PACKING-FIELD"
    assert attachment["archive_status"] == "pending"
    assert attachment["packing_candidate"] is True
    assert attachment["downloadable"] is False
    assert attachment["declared_size"] == 9876
    assert "AUTH-SECRET" not in repr(attachment)

    Source.archive_ready = True
    refreshed = service.get_batch_dingtalk_approval_detail("B1")
    archived = refreshed["main_approval"]["attachments"][0]
    assert archived["archive_status"] == "archived"
    assert archived["archive_method"] == "dingtalk_original"
    assert archived["content_quality"] == "original"
    assert archived["downloadable"] is True


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


@pytest.mark.parametrize("reverse", [False, True])
def test_materialize_reuses_canonical_archive_when_temporary_duplicate_exists(
    monkeypatch, reverse
) -> None:
    from overseas_costing.services import dingtalk_approval_service as service

    rows = [
        _oa_attachment_row("ATT-TEMP", archived=False),
        _oa_attachment_row("ATT-CANONICAL", archived=True),
    ]
    if reverse:
        rows.reverse()

    class FakeDB:
        @staticmethod
        def sql(*_args, **_kwargs):
            return []

        @staticmethod
        def get_value(*_args, **_kwargs):
            return {"name": "BATCH-1", "current_version": "VERSION-1"}

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_all(*_args, **_kwargs):
            return rows

        @staticmethod
        def get_doc(*_args, **_kwargs):
            raise AssertionError("existing canonical attachment must be reused")

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

    result = service.materialize_batch_dingtalk_attachment(
        "BATCH-1", "PROC-MAIN", "FILE-1"
    )

    assert result == {
        "ok": True,
        "attachment_name": "ATT-CANONICAL",
        "created": False,
    }


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
