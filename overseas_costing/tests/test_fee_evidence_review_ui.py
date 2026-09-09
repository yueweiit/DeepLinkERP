"""费用凭证审核前端契约。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "page" / "overseas_cost_workbench" / "parts" / "78-material-fee-workspace.js"
CSS = ROOT / "page" / "overseas_cost_workbench" / "parts" / "48-material-fee-workspace.css"


def test_fee_row_has_independent_status_and_voucher_first_action() -> None:
    source = PART.read_text(encoding="utf-8")
    renderer = source.split("renderMaterialFeeRow(fee)", 1)[1].split("materialFeeGridColumns", 1)[0]

    assert 'data-mf-fee-status="1"' in renderer
    assert "待补" in renderer and "暂估" in renderer and "实际" in renderer
    assert "未发生" in renderer and "已包含" in renderer
    assert "关联并解析凭证" in renderer
    assert "请先编辑并保存这笔费用" not in source
    assert "default_status_for_amount_entry" not in source
    assert 'amount_status: amountStatus === "MISSING" ? "ESTIMATED" : amountStatus' in source


def test_fee_evidence_review_uses_wide_incremental_ai_dialog_and_new_apis() -> None:
    source = PART.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for endpoint in (
        "start_fee_evidence_review",
        "get_fee_evidence_review_status",
        "apply_fee_evidence_review",
        "discard_fee_evidence_review",
    ):
        assert endpoint in source
    for label in ("凭证总额", "费用拆分", "税种", "HS / SKU 匹配", "待归类差额", "来源证据"):
        assert label in source
    assert "ocw-mf-evidence-review-dialog" in source
    assert 'data-fieldname="item"' in source
    assert ".ocw-mf-evidence-review-modal .modal-dialog" in css
    assert "replaceWith" not in source.split("updateFeeEvidenceReviewProgress", 1)[1].split("renderFeeEvidenceReviewDraft", 1)[0]


def test_voucher_page_exposes_shared_ai_review_entry() -> None:
    source = (PARTS := ROOT / "page" / "overseas_cost_workbench" / "parts" / "40-vouchers.js").read_text(encoding="utf-8")
    assert "AI 解析并分摊到 SKU" in source
    assert "openFeeEvidenceReviewDialog" in source
