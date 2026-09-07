"""本地工作台验收样本测试。"""

from __future__ import annotations

from overseas_costing.scripts.seed_workbench_sample import build_sample_payloads
from overseas_costing.services.batch_service import EXCEL_FIELDNAMES


def test_sample_payloads_cover_admin_states_material_workflow_and_large_batch() -> None:
    samples = build_sample_payloads()
    assert len(samples) == 6
    assert all(sample["batch"]["batch_no"].startswith("LOCAL-SAMPLE-") for sample in samples)
    assert {sample["scenario"] for sample in samples} == {
        "purchase_missing",
        "logistics_missing",
        "pending_calculation",
        "calculated",
        "material_grid_acceptance",
        "fee_workflow_acceptance",
    }
    large = next(sample for sample in samples if sample["batch"]["batch_no"] == "LOCAL-SAMPLE-SEA-184-3")
    assert len(large["items"]) == 184
    assert all(set(EXCEL_FIELDNAMES).issubset(row) for row in large["items"])
