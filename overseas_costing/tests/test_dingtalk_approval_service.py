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
