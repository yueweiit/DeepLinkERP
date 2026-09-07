"""中文用途：验证受控知识库快照到装箱确认、运费试算和历史的完整链路。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from overseas_costing.integrations.dingtalk_packing_source import PackingSnapshotArchive
from overseas_costing.services import freight_comparison_service, packing_snapshot_service
from overseas_costing.services.packing_grid import build_grid_from_dingtalk_snapshot
from overseas_costing.services.packing_parse_service import parse_packing_grid


def _oil_snapshot() -> dict:
    headers = ["物料编码", "中文品名", "数量", "长m", "宽m", "高m", "总净重", "总毛重", "总体积", "件数"]
    rows = [headers]
    groups = [
        (1, "500", "600", "1.2"),
        (1, "400", "500", "1.0"),
        (2, "600", "700", "1.5"),
        (1, "300", "400", "0.8"),
        (2, "800", "900", "2"),
        (2, "892", "1097.4", "2.2403305"),
    ]
    material = 0
    for size, net, gross, volume in groups:
        for offset in range(size):
            material += 1
            rows.append(
                [
                    f"FL{material:06d}",
                    f"油漆 {material}",
                    material * 10,
                    "1.27" if offset == 0 else None,
                    "0.97" if offset == 0 else None,
                    "1.245" if offset == 0 else None,
                    net if offset == 0 else None,
                    gross if offset == 0 else None,
                    volume if offset == 0 else None,
                    1 if offset == 0 else None,
                ]
            )
    rows.append(["合计", None, None, None, None, None, "3492", "4197.4", "8.7403305", 6])
    return {
        "schemaVersion": 1,
        "workbookId": "WB-2026",
        "sheetId": "st-d624e02f-88561",
        "sheetName": "油漆-packing list2026.9.05",
        "rangeAddress": "A1:J11",
        "values": rows,
        "displayValues": [["" if value is None else str(value) for value in row] for row in rows],
        "formulas": [["" for _value in row] for row in rows],
        "mergeRangesAvailable": False,
        "captureFinishedAt": "2026-09-07T12:00:00+08:00",
    }


class _ObjectResponse:
    def __init__(self, content: bytes):
        self.content = content

    def read(self):
        return self.content

    def close(self):
        return None

    def release_conn(self):
        return None


class _Minio:
    def __init__(self, content: bytes):
        self.content = content
        self.calls = []

    def get_object(self, bucket, key):
        self.calls.append((bucket, key))
        return _ObjectResponse(self.content)


class _SnapshotRepository:
    def __init__(self):
        self.saved = []
        self.current = None
        self.audits = []

    def lock_batch(self, _batch):
        return None

    def current_version(self, _batch):
        return "VERSION-1"

    def next_version(self, _batch):
        return len(self.saved) + 1

    def get_by_idempotency_key(self, key):
        return next((row for row in self.saved if row["idempotency_key"] == key), None)

    def get_current(self, _batch):
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
        return None

    def rollback(self):
        return None


class _FreightRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.saved = []
        self.audits = []

    def lock_batch(self, _batch):
        return None

    def get_snapshot(self, batch, revision):
        if batch == self.snapshot["batch"] and revision == self.snapshot["idempotency_key"]:
            return self.snapshot
        return None

    def get_by_request_id(self, request_id):
        return next((row for row in self.saved if row["request_id"] == request_id), None)

    def get_current_snapshot_name(self, _batch):
        return self.snapshot["name"]

    def insert_comparison(self, values):
        row = {"name": f"COMPARE-{len(self.saved) + 1}", **values}
        self.saved.append(row)
        return row

    def write_audit(self, values):
        self.audits.append(values)

    def commit(self):
        return None

    def rollback(self):
        return None


def test_cached_sheet_to_confirmed_snapshot_and_saved_freight_comparison(monkeypatch) -> None:
    payload = _oil_snapshot()
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    minio = _Minio(content)
    archive = PackingSnapshotArchive(bucket="dingtalk-packing-snapshots", client=minio)
    downloaded = archive.download(
        {
            "status": "ready",
            "bucket": "dingtalk-packing-snapshots",
            "object_key": f"corp/WB-2026/st-d624e02f-88561/{digest}.json",
            "actual_size": len(content),
            "content_sha256": digest,
        }
    )
    parsed = parse_packing_grid(build_grid_from_dingtalk_snapshot(downloaded))
    assert parsed["material_row_count"] == 9
    assert parsed["package_group_count"] == 6
    assert parsed["package_count"] == 6
    assert parsed["totals"]["gross_weight_kg"]["value"] == "4197.4"
    assert parsed["totals"]["volume_m3"]["value"] == "8.7403305"
    assert parsed["validation"]["needs_group_confirmation"] is True

    resolver = lambda **_kwargs: {
        "source_hash": digest,
        "source": {
            "source_kind": "wiki_sheet",
            "source_id": "WB-2026:st-d624e02f-88561",
            "source_label": payload["sheetName"],
            "sheet_name": payload["sheetName"],
        },
        "preview": parsed,
    }
    monkeypatch.setattr(packing_snapshot_service.packing_source_service, "_revision_signing_key", lambda: b"integration-secret")
    source_preview = packing_snapshot_service.preview_packing_source_v2(
        "BATCH-1", "wiki_sheet", "WB-2026:st-d624e02f-88561", resolver=resolver
    )
    resolutions = {
        "groups": {
            group["group_id"]: {"action": "confirm_shared"}
            for group in source_preview["groups"]
            if group.get("needs_confirmation")
        }
    }
    formal_state = {
        "expenses": [{"amount": "1000"}],
        "allocations": [{"amount": "100"}],
        "batch_status": "Calculated",
        "erp_status": "Not Started",
    }
    before = copy.deepcopy(formal_state)
    snapshot_repo = _SnapshotRepository()
    confirmed = packing_snapshot_service.confirm_packing_snapshot(
        "BATCH-1",
        source_preview["source_revision"],
        resolutions,
        repository=snapshot_repo,
        resolver=resolver,
    )
    assert confirmed["ok"] is True
    assert confirmed["snapshot"]["total_gross_weight_kg"] == "4197.4"
    assert confirmed["snapshot"]["total_net_weight_kg"] == "3492"

    freight_repo = _FreightRepository(snapshot_repo.saved[0])
    quote = {
        "currency": "USD",
        "scope_confirmed": True,
        "weight": {"unit_price": "1.2", "min_quantity": "4200", "rounding_increment": "10", "surcharge": "100"},
        "volume": {"unit_price": "560", "rounding_increment": "0.1", "surcharge": "80"},
        "quote_remark": "同一航线同一服务范围",
    }
    preview = freight_comparison_service.preview_freight_comparison(
        "BATCH-1", confirmed["snapshot"]["idempotency_key"], quote, repository=freight_repo
    )
    saved = freight_comparison_service.save_freight_comparison(
        "BATCH-1", confirmed["snapshot"]["idempotency_key"], "f" * 64, quote, repository=freight_repo
    )

    assert preview["calculation"]["recommended_basis"] == "volume"
    assert saved["comparison"]["packing_snapshot"] == confirmed["snapshot"]["name"]
    assert snapshot_repo.audits[0]["action_type"] == "PACKING_CONFIRM"
    assert freight_repo.audits[0]["action_type"] == "FREIGHT_COMPARE"
    assert formal_state == before
    assert minio.calls and all("dingtalk" not in key.lower() for _bucket, key in minio.calls)


def test_815_sample_keeps_24_groups_and_368_packages() -> None:
    rows = [["物料编码", "数量", "总毛重", "总体积", "件数"]]
    for index in range(1, 25):
        rows.append([f"ITEM-{index:02d}", 1, 1000 if index < 24 else 2360.08, 2 if index < 24 else 9.33429, 15 if index < 24 else 23])
    rows.append(["合计", None, 25360.08, 55.33429, 368])
    snapshot = {
        "schemaVersion": 1,
        "sheetName": "8.15日货柜",
        "rangeAddress": "A1:E26",
        "values": rows,
        "displayValues": [["" if value is None else str(value) for value in row] for row in rows],
        "formulas": [["", "", "", "", ""] for _row in rows],
        "mergeRangesAvailable": False,
    }
    result = parse_packing_grid(build_grid_from_dingtalk_snapshot(snapshot))

    assert (result["material_row_count"], result["package_group_count"], result["package_count"]) == (24, 24, 368)
    assert result["totals"]["gross_weight_kg"]["value"] == "25360.08"
    assert result["totals"]["volume_m3"]["value"] == "55.33429"


def test_deployment_smoke_checks_the_complete_packing_runtime() -> None:
    script = (Path(__file__).resolve().parents[2] / ".github" / "scripts" / "sync_and_verify_assets.sh").read_text(encoding="utf-8")

    for marker in (
        "from overseas_costing.api import packing_api",
        "Overseas Packing Snapshot",
        "Overseas Freight Comparison",
        "openPackingFlowDialog",
        "独立试算，不修改正式费用",
        "packing_workbooks_v1",
        "packing_sheet_index_v1",
        "packing_sheet_snapshots_v1",
        "packing_refresh_status_v1",
        "costing_job_submitter",
        "list_objects",
    ):
        assert marker in script


def test_rejected_or_revoked_attachment_policy_is_never_a_selectable_cost_source() -> None:
    from overseas_costing.services import packing_source_service

    assert packing_source_service._attachment_is_audit_only(
        {
            "batch": "BATCH-REJECTED",
            "parse_result_json": json.dumps(
                {"approval_excluded": True, "cost_source_allowed": False},
                ensure_ascii=False,
            ),
        }
    ) is True
