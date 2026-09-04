from __future__ import annotations

import json


def test_comment_source_preview_rechecks_hash_and_delegates_to_existing_preview(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    comment = {
        "source_id": "a" * 64,
        "instance_id": "PROC-1",
        "operation_time": "2026-09-01T10:00:00+08:00",
        "user_id": "USER-1",
        "user_name": "张三",
        "remark": "MBA101283 1PCS，重量2.5kg",
    }
    monkeypatch.setattr(service, "_find_comment_source", lambda _batch, _source: comment)
    captured = {}

    def fake_preview(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "writeback_preview": {"matched_count": 1}}

    monkeypatch.setattr(service.import_service, "preview_packing_list_attachment", fake_preview)

    result = service.preview_packing_source("BATCH-1", "comment", "a" * 64)

    assert result["ok"] is True
    assert result["source_kind"] == "comment"
    assert result["source_revision"]
    rows = json.loads(captured["sheet_rows_json"])
    assert rows[0]["material_code"] == "MBA101283"
    assert rows[0]["gross_weight_kg"] == 2.5
    assert captured["attachment_name"] == f"DINGTALK-COMMENT:{'a' * 64}"
    assert "PROC-1" in rows[0]["source_remark"]
    assert "USER-1" in rows[0]["source_remark"]
    assert "2026-09-01T10:00:00+08:00" in rows[0]["source_remark"]
    assert "MBA101283 1PCS" in rows[0]["source_remark"]


def test_apply_rejects_stale_comment_revision(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    monkeypatch.setattr(service, "_find_comment_source", lambda _batch, _source: {
        "source_id": "b" * 64,
        "remark": "重量21kg，5200个袋子",
    })
    stale = service._encode_revision("comment", "b" * 64, "old-hash")

    result = service.apply_packing_source("BATCH-1", stale, "{}")

    assert result["ok"] is False
    assert result["source_changed"] is True


def test_attachment_preview_requires_local_download_before_parsing(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    monkeypatch.setattr(service, "_attachment_source", lambda _batch, _source: {
        "name": "ATTACH-1",
        "file_name": "装箱计划.xlsx",
        "file_url": "",
        "modified": "2026-09-04 10:00:00",
    })

    result = service.preview_packing_source("BATCH-1", "attachment", "ATTACH-1")

    assert result["ok"] is False
    assert result["download_required"] is True
    assert result["attachment_name"] == "ATTACH-1"


def test_revision_is_signed_and_bound_to_batch_and_version(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    monkeypatch.setattr(service, "_revision_signing_key", lambda: b"test-secret")
    token = service._encode_revision(
        "comment", "comment-1", "hash-1",
        batch_name="BATCH-1", version_name="VERSION-1",
        batch_modified="BATCH-MOD", version_modified="VERSION-MOD",
    )

    assert service._decode_revision(token)["batch"] == "BATCH-1"
    assert service._decode_revision(token)["version"] == "VERSION-1"
    payload, signature = token.split(".", 1)
    tampered = f"{payload[:-1]}A.{signature}"
    assert service._decode_revision(tampered) == {}


def test_apply_uses_one_preview_commit_and_recalculation(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    comment = {
        "source_id": "a" * 64,
        "instance_id": "PROC-1",
        "operation_time": "2026-09-01T10:00:00+08:00",
        "user_id": "USER-1",
        "remark": "MBA101283 1PCS，重量2.5kg",
    }
    monkeypatch.setattr(service, "_revision_signing_key", lambda: b"test-secret")
    monkeypatch.setattr(service, "_find_comment_source", lambda _batch, _source: comment)
    monkeypatch.setattr(service, "_source_context", lambda *_args: {
        "version_name": "VERSION-1",
        "batch_modified": "BATCH-MOD",
        "version_modified": "VERSION-MOD",
        "valid": True,
    })
    events = []
    calls = {"preview": 0, "apply": [], "resolve": [], "recalculate": [], "commit": 0, "rollback": 0}
    preview = {"ok": True, "batch_doc_name": "BATCH-1", "version_name": "VERSION-1", "writeback_preview": {}}

    def fake_preview(**_kwargs):
        calls["preview"] += 1
        return preview

    def fake_apply(**kwargs):
        calls["apply"].append(kwargs)
        return {"ok": True, "updated_count": 1, "created_count": 0, "batch_doc_name": "BATCH-1", "version_name": "VERSION-1"}

    def fake_resolve(**kwargs):
        calls["resolve"].append(kwargs)
        return {"ok": True, "changed_field_count": 1}

    monkeypatch.setattr(service.import_service, "preview_packing_list_attachment", fake_preview)
    monkeypatch.setattr(service.import_service, "apply_packing_list_fillable_fields", fake_apply)
    monkeypatch.setattr(service.import_service, "resolve_packing_list_conflict_row", fake_resolve)
    def fake_recalculate(**kwargs):
        events.append("recalculate")
        calls["recalculate"].append(kwargs)
        return {"action": "recalculated", "ok": True}

    monkeypatch.setattr(service.import_service, "_recalculate_after_writeback", fake_recalculate)
    monkeypatch.setattr(service, "_commit", lambda: events.append("commit") or calls.__setitem__("commit", calls["commit"] + 1))
    monkeypatch.setattr(service, "_rollback", lambda: calls.__setitem__("rollback", calls["rollback"] + 1))
    revision = service._encode_revision(
        "comment", "a" * 64, "a" * 64,
        batch_name="BATCH-1", version_name="VERSION-1",
        batch_modified="BATCH-MOD", version_modified="VERSION-MOD",
    )

    result = service.apply_packing_source(
        "BATCH-1", revision,
        {"conflicts": [{"target_item_name": "ITEM-1", "action": "use_attachment"}]},
        version_name="VERSION-1",
    )

    assert result["ok"] is True
    assert calls["preview"] == 1
    assert calls["commit"] == 1
    assert calls["rollback"] == 0
    assert len(calls["recalculate"]) == 1
    assert calls["recalculate"][0]["commit_after_recalculate"] is False
    assert events == ["recalculate", "commit"]
    assert calls["apply"][0]["preview_result"] is preview
    assert calls["apply"][0]["commit_after_writeback"] is False
    assert calls["apply"][0]["recalculate_after_writeback"] is False
    assert calls["resolve"][0]["preview_result"] is preview
    assert calls["resolve"][0]["commit_after_writeback"] is False
    assert calls["resolve"][0]["recalculate_after_writeback"] is False


def test_apply_rolls_back_all_changes_when_recalculation_fails(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    comment = {"source_id": "c" * 64, "remark": "MBA101283 1PCS，重量2.5kg"}
    monkeypatch.setattr(service, "_revision_signing_key", lambda: b"test-secret")
    monkeypatch.setattr(service, "_find_comment_source", lambda *_args: comment)
    monkeypatch.setattr(service, "_source_context", lambda *_args: {
        "version_name": "VERSION-1", "batch_modified": "BATCH-MOD", "version_modified": "VERSION-MOD", "valid": True,
    })
    monkeypatch.setattr(service.import_service, "preview_packing_list_attachment", lambda **_kwargs: {
        "ok": True, "batch_doc_name": "BATCH-1", "version_name": "VERSION-1", "writeback_preview": {},
    })
    monkeypatch.setattr(service.import_service, "apply_packing_list_fillable_fields", lambda **_kwargs: {
        "ok": True, "updated_count": 1, "created_count": 0, "batch_doc_name": "BATCH-1", "version_name": "VERSION-1",
    })
    monkeypatch.setattr(service.import_service, "_recalculate_after_writeback", lambda **_kwargs: {
        "action": "failed", "ok": False, "message": "boom",
    })
    calls = {"commit": 0, "rollback": 0}
    monkeypatch.setattr(service, "_commit", lambda: calls.__setitem__("commit", calls["commit"] + 1))
    monkeypatch.setattr(service, "_rollback", lambda: calls.__setitem__("rollback", calls["rollback"] + 1))
    revision = service._encode_revision(
        "comment", "c" * 64, "c" * 64,
        batch_name="BATCH-1", version_name="VERSION-1",
        batch_modified="BATCH-MOD", version_modified="VERSION-MOD",
    )

    result = service.apply_packing_source("BATCH-1", revision, {})

    assert result["ok"] is False
    assert result["recalculate_result"]["action"] == "failed"
    assert calls == {"commit": 0, "rollback": 1}


def test_source_context_rejects_version_from_another_batch(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    class FakeDB:
        @staticmethod
        def get_value(doctype, name, fields=None, as_dict=False):
            if doctype == "Overseas Cost Batch":
                return {"name": "BATCH-1", "current_version": "VERSION-1", "modified": "BATCH-MOD"}
            return {"name": "VERSION-1", "batch": "BATCH-2", "modified": "VERSION-MOD"}

    class FakeFrappe:
        db = FakeDB()

    monkeypatch.setattr(service, "frappe", FakeFrappe)

    assert service._source_context("BATCH-1", "VERSION-1")["valid"] is False


def test_comment_conflict_resolutions_round_trip_in_batch_extra_json(monkeypatch) -> None:
    from overseas_costing.services import packing_source_service as service

    stored = {"extra_json": json.dumps({"existing": {"keep": True}})}

    class FakeDB:
        @staticmethod
        def get_value(_doctype, _name, _field):
            return stored["extra_json"]

        @staticmethod
        def set_value(_doctype, _name, _field, value, **_kwargs):
            stored["extra_json"] = value

    class FakeFrappe:
        db = FakeDB()

    monkeypatch.setattr(service, "frappe", FakeFrappe)
    resolution = {"target_item_name": "ITEM-1", "action": "keep_system"}

    assert service._save_comment_resolutions("BATCH-1", "COMMENT-1", [resolution]) is True
    assert service._comment_resolutions("BATCH-1", "COMMENT-1") == [resolution]
    assert json.loads(stored["extra_json"])["existing"] == {"keep": True}
