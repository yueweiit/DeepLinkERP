"""费用凭证审核前端契约。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "page" / "overseas_cost_workbench" / "parts" / "78-material-fee-workspace.js"
MATRIX_PART = ROOT / "page" / "overseas_cost_workbench" / "parts" / "78-fee-evidence-review-matrix.js"
CSS = ROOT / "page" / "overseas_cost_workbench" / "parts" / "48-material-fee-workspace.css"
MATRIX_CSS = ROOT / "page" / "overseas_cost_workbench" / "parts" / "48-fee-evidence-review-matrix.css"


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
    matrix_source = MATRIX_PART.read_text(encoding="utf-8")
    css = MATRIX_CSS.read_text(encoding="utf-8")
    for endpoint in (
        "start_fee_evidence_review",
        "get_fee_evidence_review_status",
        "apply_fee_evidence_review",
        "discard_fee_evidence_review",
    ):
        assert endpoint in source
    for label in ("凭证总额", "费用拆分", "物料 / SKU", "清关服务费", "物料合计", "核对状态"):
        assert label in matrix_source
    assert "ocw-mf-evidence-review-dialog" in source
    assert 'data-fieldname="item"' not in source + matrix_source
    assert ".ocw-mf-evidence-review-modal .modal-dialog" in css
    assert "replaceWith" not in source.split("updateFeeEvidenceReviewProgress", 1)[1].split("renderFeeEvidenceReviewDraft", 1)[0]


def test_voucher_page_exposes_shared_ai_review_entry() -> None:
    source = (PARTS := ROOT / "page" / "overseas_cost_workbench" / "parts" / "40-vouchers.js").read_text(encoding="utf-8")
    assert "AI 解析并分摊到 SKU" in source
    assert "openFeeEvidenceReviewDialog" in source


def test_review_marks_conflicts_and_missing_fx_in_default_preview() -> None:
    source = MATRIX_PART.read_text(encoding="utf-8")
    css = MATRIX_CSS.read_text(encoding="utf-8")

    assert "has_conflict" in source and "needs_review" in source
    assert "ocw-mf-review-warning" in source
    assert ".ocw-mf-review-warning" in css
    assert "缺汇率：可保存原币事实" in source


def test_matrix_css_keeps_two_identity_columns_and_actions_usable_on_narrow_screens() -> None:
    css = MATRIX_CSS.read_text(encoding="utf-8")

    assert "position: sticky" in css
    assert ":is(th,td):first-child" in css
    assert ":is(th,td):nth-child(2)" in css
    assert "overflow: auto" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 560px)" in css
    assert "min-height: 44px" in css
    assert ".ocw-mf-matrix-totals { position: static" not in css


def test_review_shows_precise_source_locator_and_refund_parent() -> None:
    source = MATRIX_PART.read_text(encoding="utf-8")

    for token in (
        "ref.page",
        "ref.text_line",
        "ref.cell",
        "ref.region",
        'data-fieldname="related_evidence"',
    ):
        assert token in source


def test_review_matrix_is_extracted_and_only_submits_sparse_allowed_fields() -> None:
    source = PART.read_text(encoding="utf-8")
    matrix_source = MATRIX_PART.read_text(encoding="utf-8")

    assert "renderFeeEvidenceReviewDraft(draft" not in source
    assert "renderFeeEvidenceReviewDraft(draft" in matrix_source
    assert "component_matrix_json" in source
    assert "validateFeeEvidenceMatrix" in source
    assert "serializeFeeEvidenceMatrix" in matrix_source
    assert "amount_rmb" not in matrix_source.split("serializeFeeEvidenceMatrix", 1)[1].split("feeEvidenceFeeTotals", 1)[0]
    assert "hs_code" not in matrix_source.split("serializeFeeEvidenceMatrix", 1)[1].split("feeEvidenceFeeTotals", 1)[0]


def test_review_task_actions_do_not_calculate_confirm_or_push_erp() -> None:
    source = PART.read_text(encoding="utf-8")
    review_source = source.split("async openFeeEvidenceReviewDialog", 1)[1].split(
        "async setMaterialFeeEvidenceStatus", 1
    )[0]

    assert "calculate_comprehensive_cost" not in review_source
    assert "confirm_" not in review_source
    assert "erp" not in review_source.lower()
