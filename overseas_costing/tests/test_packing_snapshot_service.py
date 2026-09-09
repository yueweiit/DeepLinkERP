"""中文用途：四类装箱来源预览、版本校验和不可变确认快照测试。"""

from __future__ import annotations

import copy

from openpyxl import Workbook

import pytest

from overseas_costing.services import packing_snapshot_service as service
from overseas_costing.integrations import dingtalk_packing_source


def _preview(*, needs_confirmation=False):
    group = {
        "group_id": "package-1",
        "row_numbers": [2, 3],
        "needs_confirmation": needs_confirmation,
        "gross_weight_kg": {"value": "4197.4", "count_once": not needs_confirmation},
        "volume_m3": {"value": "8.7403305", "count_once": not needs_confirmation},
        "net_weight_kg": {"value": "3492", "count_once": not needs_confirmation},
        "package_count": {"value": "6", "count_once": not needs_confirmation},
        "dimensions": {},
        "evidence": [],
    }
    return {
        "ok": not needs_confirmation,
        "source": {"source_kind": "wiki_sheet", "sheet_name": "油漆"},
        "material_row_count": 9,
        "package_count": 6,
        "material_rows": [{"source_row": 2, "material_code": "FL001"}],
        "groups": [group],
        "totals": {
            "net_weight_kg": {"value": "3492", "kind": "calculated_detail_sum"},
            "gross_weight_kg": {"value": "4197.4", "kind": "source_total"},
            "volume_m3": {"value": "8.7403305", "kind": "source_total"},
        },
        "validation": {
            "blocking": ([{"code": "group_confirmation_required", "message": "待确认"}] if needs_confirmation else []),
            "warnings": [],
            "needs_group_confirmation": needs_confirmation,
        },
    }


class FakeRepository:
    def __init__(self):
        self.current = None
        self.saved = []
        self.audits = []
        self.locked = []
        self.commits = 0
        self.rollbacks = 0
        self.domain_state = {
            "items": [{"name": "ITEM-1", "amount": "100"}],
            "expense_pool": [{"amount": "200"}],
            "batch_status": "Calculated",
            "erp_state": "Not Started",
        }

    def lock_batch(self, batch_name):
        self.locked.append(batch_name)

    def current_version(self, _batch_name):
        return "VERSION-1"

    def get_by_idempotency_key(self, key):
        return next((item for item in self.saved if item["idempotency_key"] == key), None)

    def get_current(self, _batch_name):
        return self.current

    def supersede(self, snapshot):
        snapshot["status"] = "Superseded"
        snapshot["is_current"] = 0

    def insert_snapshot(self, values):
        row = {"name": f"SNAP-{len(self.saved) + 1}", **values}
        self.saved.append(row)
        self.current = row
        return row

    def write_audit(self, values):
        self.audits.append(values)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_preview_signs_trusted_source_and_never_uses_browser_totals(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    captured = {}

    def resolver(**kwargs):
        captured.update(kwargs)
        return {
            "source_hash": "a" * 64,
            "source": {"source_kind": "wiki_sheet", "source_id": "WB:st-1", "source_label": "油漆"},
            "preview": _preview(),
        }

    result = service.preview_packing_source_v2(
        "BATCH-1",
        "wiki_sheet",
        "WB:st-1",
        sheet_name="油漆",
        browser_payload={"total_gross_weight_kg": "1", "workbook_url": "https://evil"},
        resolver=resolver,
    )

    assert result["ok"] is True
    assert result["totals"]["gross_weight_kg"]["value"] == "4197.4"
    assert result["source_revision"]
    assert "browser_payload" not in captured
    assert "workbook_url" not in result["source"]


def test_confirmation_blocks_unresolved_groups(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    resolver = lambda **_kwargs: {
        "source_hash": "b" * 64,
        "source": {"source_kind": "wiki_sheet", "source_id": "WB:st-1", "source_label": "油漆"},
        "preview": _preview(needs_confirmation=True),
    }
    preview = service.preview_packing_source_v2("BATCH-1", "wiki_sheet", "WB:st-1", resolver=resolver)

    result = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], {}, repository=FakeRepository(), resolver=resolver
    )

    assert result["ok"] is False
    assert result["needs_group_confirmation"] is True


def test_confirmation_is_idempotent_supersedes_old_and_does_not_touch_formal_cost(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    repository = FakeRepository()
    old = {"name": "SNAP-OLD", "status": "Confirmed", "is_current": 1}
    repository.current = old
    resolver = lambda **_kwargs: {
        "source_hash": "c" * 64,
        "source": {
            "source_kind": "wiki_sheet",
            "source_id": "WB:st-1",
            "source_label": "油漆",
            "source_updated_at": "2026-09-05T14:41:00+08:00",
        },
        "preview": _preview(needs_confirmation=True),
    }
    preview = service.preview_packing_source_v2("BATCH-1", "wiki_sheet", "WB:st-1", resolver=resolver)
    before = copy.deepcopy(repository.domain_state)
    resolutions = {"groups": {"package-1": {"action": "confirm_shared"}}}

    first = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], resolutions, repository=repository, resolver=resolver
    )
    second = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], resolutions, repository=repository, resolver=resolver
    )

    assert first["ok"] is True
    assert first["snapshot"]["name"] == "SNAP-1"
    assert second["snapshot"]["name"] == "SNAP-1"
    assert second["idempotent"] is True
    assert len(repository.saved) == 1
    assert old == {"name": "SNAP-OLD", "status": "Superseded", "is_current": 0}
    assert repository.audits[0]["action_type"] == "PACKING_CONFIRM"
    assert repository.domain_state == before
    assert repository.commits == 1


def test_confirmation_rechecks_source_hash_and_rejects_stale_preview(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    hashes = iter(("d" * 64, "e" * 64))

    def resolver(**_kwargs):
        return {
            "source_hash": next(hashes),
            "source": {"source_kind": "manual_attachment", "source_id": "ATT-1", "source_label": "装箱单.xlsx"},
            "preview": _preview(),
        }

    preview = service.preview_packing_source_v2("BATCH-1", "manual_attachment", "ATT-1", resolver=resolver)
    result = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], {}, repository=FakeRepository(), resolver=resolver
    )

    assert result["ok"] is False
    assert result["source_changed"] is True


def test_attachment_sheet_names_are_read_server_side_without_exposing_path(tmp_path) -> None:
    path = tmp_path / "packing.xlsx"
    workbook = Workbook()
    workbook.active.title = "民打印-packing list2026.9.05"
    workbook.create_sheet("油漆-packing list2026.9.05")
    workbook.save(path)

    result = service._attachment_sheet_names({"file_url": str(path)})

    assert result == ["民打印-packing list2026.9.05", "油漆-packing list2026.9.05"]
    assert str(path) not in repr(result)


def test_user_can_split_a_suggested_shared_group_without_double_counting() -> None:
    resolved = service._apply_resolutions(
        _preview(needs_confirmation=True),
        {"groups": {"package-1": {"action": "split"}}},
    )

    assert resolved["validation"]["blocking"] == []
    assert resolved["validation"]["needs_group_confirmation"] is False
    assert resolved["package_group_count"] == 2
    assert resolved["package_count"] == 6
    assert [group["row_numbers"] for group in resolved["groups"]] == [[2], [3]]
    assert resolved["groups"][0]["gross_weight_kg"]["value"] == "4197.4"
    assert resolved["groups"][0]["gross_weight_kg"]["count_once"] is True
    assert resolved["groups"][1]["gross_weight_kg"]["value"] is None


def test_resolved_merge_conflict_blocker_is_removed() -> None:
    preview = _preview(needs_confirmation=True)
    preview["groups"][0]["merge_conflict"] = True
    preview["validation"]["blocking"].insert(
        0, {"code": "conflicting_merge_ranges", "message": "合并范围冲突"}
    )

    resolved = service._apply_resolutions(
        preview,
        {"groups": {"package-1": {"action": "confirm_shared"}}},
    )

    assert resolved["validation"]["blocking"] == []


def test_user_can_partition_three_rows_and_metric_stays_with_source_row() -> None:
    preview = _preview(needs_confirmation=True)
    preview["groups"][0]["row_numbers"] = [2, 3, 4]
    for field in ("gross_weight_kg", "volume_m3", "net_weight_kg", "package_count"):
        preview["groups"][0][field]["source_row"] = 2

    resolved = service._apply_resolutions(
        preview,
        {
            "groups": {
                "package-1": {
                    "action": "partition",
                    "partitions": [[2, 3], [4]],
                }
            }
        },
    )

    assert [group["row_numbers"] for group in resolved["groups"]] == [[2, 3], [4]]
    assert resolved["groups"][0]["gross_weight_kg"]["value"] == "4197.4"
    assert resolved["groups"][0]["gross_weight_kg"]["count_once"] is True
    assert resolved["groups"][1]["gross_weight_kg"]["value"] is None
    assert resolved["validation"]["blocking"] == []


def test_total_mismatch_requires_explicit_basis_resolution() -> None:
    preview = _preview()
    preview["totals"]["gross_weight_kg"].update(
        {"value": "999", "declared_value": "999", "calculated_value": "4197.4", "kind": "source_total"}
    )
    preview["validation"]["blocking"] = [
        {"code": "total_mismatch", "field": "gross_weight_kg", "message": "合计不一致"}
    ]

    unresolved = service._apply_resolutions(preview, {})
    assert unresolved["validation"]["blocking"][0]["code"] == "total_mismatch"

    resolved = service._apply_resolutions(
        preview,
        {"totals": {"gross_weight_kg": {"action": "use_calculated"}}},
    )
    assert resolved["totals"]["gross_weight_kg"]["value"] == "4197.4"
    assert resolved["totals"]["gross_weight_kg"]["kind"] == "user_selected_calculated"
    assert resolved["validation"]["blocking"] == []


def test_same_source_revision_cannot_be_reconfirmed_with_different_decisions(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    repository = FakeRepository()
    resolver = lambda **_kwargs: {
        "source_hash": "9" * 64,
        "source": {"source_kind": "wiki_sheet", "source_id": "WB:st-1", "source_label": "油漆"},
        "preview": _preview(needs_confirmation=True),
    }
    preview = service.preview_packing_source_v2("BATCH-1", "wiki_sheet", "WB:st-1", resolver=resolver)

    first = service.confirm_packing_snapshot(
        "BATCH-1",
        preview["source_revision"],
        {"groups": {"package-1": {"action": "confirm_shared"}}},
        repository=repository,
        resolver=resolver,
    )
    second = service.confirm_packing_snapshot(
        "BATCH-1",
        preview["source_revision"],
        {"groups": {"package-1": {"action": "split"}}},
        repository=repository,
        resolver=resolver,
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["resolution_conflict"] is True
    assert len(repository.saved) == 1


def _dingtalk_sheet_snapshot(sheet_name, item_codes):
    values = [["物料编码", "中文品名", "数量"]]
    values.extend([[code, f"物料 {code}", 1] for code in item_codes])
    return {
        "schemaVersion": 1,
        "sheetName": sheet_name,
        "mergeRangesAvailable": False,
        "values": values,
        "displayValues": values,
        "formulas": [[None for _cell in row] for row in values],
    }


def test_list_sources_recommends_cached_sheet_without_submitting_refresh(monkeypatch) -> None:
    class FakeDB:
        @staticmethod
        def get_value(doctype, name, fields, as_dict=False):
            assert doctype == "Overseas Cost Batch"
            assert name == "BATCH-1"
            assert as_dict is True
            return {
                "name": "BATCH-1",
                "batch_no": "202609032107000062462",
                "waybill_no": "",
                "source_approval_no": "LOG-001",
                "source_instance_id": "MAIN-1",
                "project_collection": "指环扣",
                "creation": "2026-09-03 10:00:00",
            }

    class FakeFrappe:
        db = FakeDB()

        def __init__(self):
            self.item_queries = 0

        def get_list(self, doctype, filters, fields, limit_page_length):
            if doctype == "Overseas Cost Attachment":
                return []
            assert doctype == "Overseas Cost Item"
            assert filters == {"batch": "BATCH-1"}
            self.item_queries += 1
            return [
                {"material_code": code, "product_name": "指环扣", "source_doc_no": "PO-001"}
                for code in ("FL000427", "FL000428", "FL000429", "FL000430", "FL003377")
            ]

    class FakeCatalog:
        def __init__(self):
            self.snapshot_queries = 0

        @staticmethod
        def list_workbooks():
            return [{"workbook_id": "WB-2026", "year": 2026, "label": "2026 海运装箱计划"}]

        @staticmethod
        def list_sheets(_workbook_id, limit):
            assert limit == 500
            return [
                {"workbook_id": "WB-2026", "sheet_id": "st-ring", "sheet_name": "指环扣-packing list2026.9.05"},
                {"workbook_id": "WB-2026", "sheet_id": "st-broken", "sheet_name": "油漆-packing list2026.9.05"},
            ]

        def list_latest_snapshots(self, workbook_id):
            assert workbook_id == "WB-2026"
            self.snapshot_queries += 1
            return [
                {
                    "sheet_id": "st-ring",
                    "status": "ready",
                    "created_at": "2026-09-07T10:00:00+08:00",
                    "content_sha256": "a" * 64,
                },
                {
                    "sheet_id": "st-broken",
                    "status": "ready",
                    "created_at": "2026-09-07T09:00:00+08:00",
                    "content_sha256": "b" * 64,
                },
            ]

    class FakeArchive:
        def __init__(self):
            self.downloads = []

        def download(self, manifest):
            self.downloads.append(manifest["sheet_id"])
            if manifest["sheet_id"] == "st-broken":
                raise ValueError("corrupt cached object")
            return _dingtalk_sheet_snapshot(
                "指环扣-packing list2026.9.05",
                ["FL000427", "FL000428", "FL000429", "FL000430", "FL003377", "CW000224"],
            )

    fake_frappe = FakeFrappe()
    fake_catalog = FakeCatalog()
    fake_archive = FakeArchive()
    clients = type("Clients", (), {"catalog": fake_catalog, "archive": fake_archive})()
    detail_calls = []
    detail = {
        "ok": True,
        "main_approval": {
            "instance_id": "MAIN-1",
            "business_id": "LOG-001",
            "title": "指环扣国际物流",
            "form_fields": [{"label": "采购审批号", "value": "PO-001"}],
            "timeline": [],
        },
        "linked_purchase_approvals": [
            {
                "instance_id": "PURCHASE-1",
                "business_id": "PO-001",
                "title": "指环扣采购支出",
                "form_fields": [],
                "timeline": [],
            }
        ],
        "excluded_linked_purchase_approvals": [
            {"instance_id": "REJECTED-1", "business_id": "PO-REJECTED", "excluded": True}
        ],
    }

    monkeypatch.setattr(service, "frappe", fake_frappe)
    monkeypatch.setattr(
        service.packing_source_service.dingtalk_approval_service,
        "get_batch_dingtalk_approval_detail",
        lambda batch_name: detail_calls.append(batch_name) or detail,
    )
    monkeypatch.setattr(dingtalk_packing_source, "get_packing_runtime_clients", lambda: clients)

    result = service.list_packing_sources("BATCH-1")

    assert detail_calls == ["BATCH-1"]
    assert fake_frappe.item_queries == 1
    assert fake_catalog.snapshot_queries == 1
    assert fake_archive.downloads == ["st-ring", "st-broken"]
    sheets = result["wiki_workbooks"][0]["sheets"]
    assert sheets[0]["source_id"] == "WB-2026:st-ring"
    assert sheets[0]["is_recommended"] is True
    assert sheets[0]["recommendation_confidence"] == "high"
    assert "匹配当前批次 5/5 个 SKU" in sheets[0]["recommendation_reasons"]
    assert sheets[0]["extra_item_codes"] == ["CW000224"]
    assert sheets[0]["snapshot_updated_at"] == "2026-09-07T10:00:00+08:00"
    assert sheets[0]["content_hash"] == "a" * 64
    broken = next(item for item in sheets if item["source_id"] == "WB-2026:st-broken")
    assert broken["snapshot_status"] == "unreadable"
    assert result["wiki_error"] == ""


def test_recommended_workbook_is_globally_pinned_without_reordering_its_sheets() -> None:
    workbooks = [
        {"workbook_id": "WB-2026", "sheets": [{"source_id": "WB-2026:new"}]},
        {
            "workbook_id": "WB-2025",
            "sheets": [
                {"source_id": "WB-2025:recommended", "is_recommended": True},
                {"source_id": "WB-2025:other"},
            ],
        },
    ]

    result = service._pin_recommended_workbook(workbooks)

    assert [row["workbook_id"] for row in result] == ["WB-2025", "WB-2026"]
    assert [row["source_id"] for row in result[0]["sheets"]] == [
        "WB-2025:recommended",
        "WB-2025:other",
    ]


def test_list_sources_includes_unsaved_approval_excel_files_and_safe_download_identity(monkeypatch):
    import json
    from types import SimpleNamespace

    local = [{"name": "ATT-1", "batch": "B1", "source_type": "OA", "file_name": "already.xlsx",
              "file_url": "/private/files/already.xlsx", "attachment_type": "Other",
              "parse_result_json": json.dumps({"instance_id": "MAIN", "file_id": "F1"})}]
    monkeypatch.setattr(service, "frappe", SimpleNamespace(get_list=lambda *args, **kwargs: local))
    monkeypatch.setattr(service, "_attachment_sheet_names", lambda row: ["Sheet1"] if row.get("file_url") else [])
    detail = {"main_approval": {"instance_id": "MAIN", "attachments": [
        {"file_id": "F1", "process_instance_id": "MAIN", "file_name": "already.xlsx", "attachment_name": "", "archive_status": "archived"},
        {"file_id": "F2", "process_instance_id": "MAIN", "file_name": "货物资料.xlsx", "origin": "Form", "archive_status": "archived", "packing_candidate": False,
         "object_key": "private/secret", "raw_json": "secret"},
        {"file_id": "PDF", "file_name": "packing.pdf", "archive_status": "archived"},
    ]}, "linked_purchase_approvals": [{"instance_id": "PURCHASE", "attachments": [
        {"file_id": "F3", "file_name": "采购附表.xlsx", "origin": "Comment", "archive_status": "pending"},
        {"file_id": "F4", "file_name": "macro.xlsm", "origin": "Form", "archive_status": "archived"},
    ]}], "excluded_linked_purchase_approvals": [{"instance_id": "REJECTED", "excluded": True, "attachments": [
        {"file_id": "BAD", "file_name": "packing.xlsx", "archive_status": "archived"}]}]}
    monkeypatch.setattr(service.packing_source_service.dingtalk_approval_service,
                        "get_batch_dingtalk_approval_detail", lambda _batch: detail)
    monkeypatch.setattr(dingtalk_packing_source, "get_packing_runtime_clients", lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    result = service.list_packing_sources("B1")
    sources = result["approval_sources"]
    assert len(sources) == 6
    assert len({row["source_id"] for row in sources}) == 6
    by_file = {row["file_id"]: row for row in sources}
    assert by_file["F1"]["source_id"] == "ATT-1"
    assert by_file["F1"]["available"] is True
    assert by_file["F2"]["attachment_name"] == ""
    assert by_file["F2"]["process_instance_id"] == "MAIN"
    assert by_file["F2"]["origin"] == "Form"
    assert by_file["F2"]["can_download"] is True
    assert by_file["F2"]["download_required"] is True
    assert by_file["F2"]["archive_status"] == "archived"
    assert by_file["F3"]["origin"] == "Comment"
    assert by_file["F3"]["process_instance_id"] == "PURCHASE"
    assert by_file["F3"]["can_download"] is False
    assert by_file["F4"]["supported_for_material_import"] is True
    assert by_file["PDF"]["supported_for_material_import"] is False
    assert by_file["BAD"]["excluded"] is True
    assert "已失效" in by_file["BAD"]["exclude_reason"]
    assert "secret" not in repr(result)


def test_list_sources_includes_free_comments_even_without_packing_keyword_classification(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(service, "frappe", SimpleNamespace(get_list=lambda *_args, **_kwargs: []))
    monkeypatch.setattr(
        service.packing_source_service.dingtalk_approval_service,
        "get_batch_dingtalk_approval_detail",
        lambda _batch: {
            "main_approval": {
                "instance_id": "MAIN",
                "business_id": "LOG-1",
                "attachments": [],
                "timeline": [
                    {
                        "source_id": "COMMENT-HASH",
                        "remark": "请以最终报价为准",
                        "packing_candidate": False,
                        "user_name": "张三",
                        "operation_time": "2026-09-08 11:00:00",
                    }
                ],
            },
            "linked_purchase_approvals": [],
        },
    )
    monkeypatch.setattr(
        dingtalk_packing_source,
        "get_packing_runtime_clients",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = service.list_packing_sources("B1")

    assert result["approval_sources"] == [
        {
            "source_kind": "approval_comment",
            "source_id": "COMMENT-HASH",
            "source_label": "评论 · 张三",
            "source_updated_at": "2026-09-08 11:00:00",
            "process_instance_id": "MAIN",
            "approval_no": "LOG-1",
            "actor_name": "张三",
            "occurred_at": "2026-09-08 11:00:00",
            "available": True,
            "excluded": False,
            "exclude_reason": "",
            "remark_preview": "请以最终报价为准",
        }
    ]


def test_material_ai_source_manifest_uses_current_version_and_marks_audit_only_excluded(monkeypatch):
    import json
    from types import SimpleNamespace

    monkeypatch.setattr(
        service,
        "list_packing_sources",
        lambda _batch, **_kwargs: {
            "wiki_workbooks": [{"sheets": [
                {
                    "source_kind": "wiki_sheet",
                    "source_id": "WB:S1",
                    "source_label": "Sheet1",
                    "is_recommended": True,
                    "recommendation_confidence": "high",
                    "snapshot_status": "ready",
                },
                {
                    "source_kind": "wiki_sheet",
                    "source_id": "WB:UNRELATED",
                    "source_label": "历史 Sheet",
                    "is_recommended": False,
                    "recommendation_confidence": "none",
                    "snapshot_status": "ready",
                },
            ]}],
            "approval_sources": [
                {
                    "source_kind": "approval_attachment",
                    "source_id": "oa:pending",
                    "source_label": "待下载.pdf",
                    "process_instance_id": "P1",
                    "file_id": "F1",
                    "available": False,
                    "download_required": True,
                }
            ],
        },
    )
    rows = [
        {
            "name": "CURRENT",
            "version": "V1",
            "source_type": "Manual",
            "file_name": "packing.pdf",
            "file_url": "/private/files/packing.pdf",
            "modified": "2026-09-08",
            "parse_result_json": "{}",
        },
        {
            "name": "OLD",
            "version": "V0",
            "source_type": "Manual",
            "file_name": "old.xlsx",
            "file_url": "/private/files/old.xlsx",
            "modified": "2026-09-01",
            "parse_result_json": "{}",
        },
        {
            "name": "REJECTED",
            "version": "V1",
            "source_type": "OA",
            "file_name": "rejected.docx",
            "file_url": "/private/files/rejected.docx",
            "modified": "2026-09-08",
            "parse_result_json": json.dumps({"approval_excluded": True, "cost_source_allowed": False}),
        },
    ]
    monkeypatch.setattr(service, "frappe", SimpleNamespace(get_list=lambda *_args, **_kwargs: rows))
    monkeypatch.setattr(service, "_attachment_sheet_names", lambda _row: [])
    monkeypatch.setattr(
        service,
        "_list_approval_body_ai_sources",
        lambda _batch, **_kwargs: [
            {
                "source_kind": "approval_form",
                "source_id": "approval:MAIN:form",
                "source_label": "国际物流审批正文",
                "process_instance_id": "MAIN",
                "source_updated_at": "2026-09-08 09:31:00",
                "approval_role": "international_logistics",
            }
        ],
    )

    result = service.list_material_ai_sources("B1", version_name="V1")

    identities = {row["logical_source_id"] for row in result}
    assert identities == {"approval:MAIN:form", "oa:P1:F1", "CURRENT", "REJECTED"}
    assert "WB:S1" not in identities
    assert "OLD" not in repr(result)
    rejected = next(row for row in result if row["logical_source_id"] == "REJECTED")
    assert rejected["excluded"] is True
    assert "审计专用" in rejected["exclude_reason"]
    assert "UNRELATED" not in repr(result)


def test_material_ai_manifest_fingerprint_includes_trusted_wiki_content_hash(monkeypatch):
    from types import SimpleNamespace

    trusted_hash = {"value": "a" * 64}
    monkeypatch.setattr(
        service,
        "list_packing_sources",
        lambda _batch, **_kwargs: {
            "wiki_workbooks": [
                {
                    "sheets": [
                        {
                            "source_kind": "wiki_sheet",
                            "source_id": "WB:S1",
                            "source_label": "Sheet1",
                            "source_updated_at": "2026-09-09 10:00:00",
                            "source_hash": trusted_hash["value"],
                        }
                    ]
                }
            ],
            "approval_sources": [],
        },
    )
    monkeypatch.setattr(
        service,
        "get_current_packing_snapshot",
        lambda _batch: {"source_kind": "wiki_sheet", "source_id": "WB:S1"},
    )
    monkeypatch.setattr(service, "_list_approval_body_ai_sources", lambda _batch, **_kwargs: [])
    monkeypatch.setattr(
        service,
        "frappe",
        SimpleNamespace(get_list=lambda *_args, **_kwargs: []),
    )

    first = service.list_material_ai_sources("B1", version_name="V1")
    trusted_hash["value"] = "b" * 64
    second = service.list_material_ai_sources("B1", version_name="V1")

    assert first[0]["source_hash"] != second[0]["source_hash"]


def test_current_wiki_refreshes_only_its_manifest_without_catalog_scan(monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.integrations import dingtalk_packing_source

    current_hash = {"value": "a" * 64}
    calls = []
    def latest(workbook, sheet):
        calls.append((workbook, sheet))
        return {"content_sha256": current_hash["value"], "capture_finished_at": "2026-09-09"}
    monkeypatch.setattr(dingtalk_packing_source, "get_packing_runtime_clients", lambda: SimpleNamespace(
        catalog=SimpleNamespace(get_latest_snapshot=latest)))
    monkeypatch.setattr(service, "frappe", SimpleNamespace(get_list=lambda *a, **kw: []))
    monkeypatch.setattr(service, "list_packing_sources", lambda *a, **kw: {"wiki_workbooks": [], "approval_sources": []})
    monkeypatch.setattr(service, "_list_approval_body_ai_sources", lambda *a, **kw: [])
    monkeypatch.setattr(service, "get_current_packing_snapshot", lambda *a: {
        "source_kind": "wiki_sheet", "source_id": "WB:S1", "source_hash": "old-confirmed-hash"})
    first = service.list_material_ai_sources("B1")
    current_hash["value"] = "b" * 64
    second = service.list_material_ai_sources("B1")
    assert first[0]["source_hash"] != second[0]["source_hash"]
    assert calls == [("WB", "S1"), ("WB", "S1")]
