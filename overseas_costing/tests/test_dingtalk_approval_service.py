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
