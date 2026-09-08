from pathlib import Path

from overseas_costing.tests.test_workbench_frontend_state import _fee_workspace_result


ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "page" / "overseas_cost_workbench" / "parts"


def test_toolbar_has_one_upload_entry_and_ai_action_on_one_line() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    render = source.split("\n  renderMaterialFeeWorkspace() {", 1)[1].split("\n  renderMaterialFeeMetric", 1)[0]
    assert "获取装箱资料" in render
    assert "AI 分析资料" in render
    assert "导入 Excel 补资料" not in render
    assert "mf-import-xlsx" not in render


def test_source_tabs_are_four_non_wrapping_items_with_named_local_upload() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    tabs = source.split("renderMaterialSourceTabs(dialog)", 2)[2].split("renderMaterialAttachmentSources", 1)[0]
    assert "装箱计划表" in tabs
    assert "钉钉表单附件" in tabs
    assert "评论附件与评论" in tabs
    assert "本地上传装箱单" in tabs
    assert "allowed_file_types" in source
    for suffix in (".xlsx", ".xlsm", ".pdf", ".png", ".doc", ".docx"):
        assert suffix in source
    css = "\n".join(
        (PARTS / name).read_text(encoding="utf-8")
        for name in ("47-packing-flow.css", "48-material-fee-workspace.css")
    )
    assert "grid-auto-flow: column" in css
    assert "overflow-x: auto" in css
    assert "white-space: nowrap" in css


def test_material_grid_uses_sticky_readable_identity_columns_and_scroll_controls() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    assert 'width: 54' in source
    assert 'width: 220' in source
    assert 'width: 120' in source
    assert 'width: 260' in source
    assert "data-action=\"mf-grid-scroll-left\"" in source
    assert "data-action=\"mf-grid-scroll-right\"" in source
    assert "data-mf-grid-scrollbar" in source
    assert ".ocw-mf-grid-table th:nth-child(-n+4)" in css
    assert "position: sticky" in css


def test_ai_draft_ui_exposes_progress_candidates_and_explicit_apply_discard() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    for endpoint in (
        "start_source_ai_review",
        "get_source_ai_review_status",
        "apply_source_ai_review",
        "discard_source_ai_review",
    ):
        assert endpoint in source
    for step in ("读取资料", "解析/OCR", "DeepSeek 识别", "合并候选"):
        assert step in source
    assert "AI 草稿" in source
    assert "告诉 AI 如何理解" in source
    assert "确认所选草稿" in source
    assert "放弃草稿" in source
    assert "data-action=\"mf-ai-adopt-candidate\"" in source
    assert ".is-ai-draft" in (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    footer = source.split("renderMaterialAIFillFooter()", 2)[2].split("bindMaterialGridScrollControls", 1)[0]
    assert 'data-action="mf-ai-discard" ${mutating ? "disabled" : ""}' in footer


def test_purchase_source_copy_distinguishes_logistics_source_from_missing_purchase_link() -> None:
    source = (PARTS / "75-table-and-list.js").read_text(encoding="utf-8")
    assert "资料来自国际物流审批" in source
    assert "采购审批待关联" in source
    status_source = (PARTS / "80-drawer-profit.js").read_text(encoding="utf-8")
    status_method = status_source.split("\n  sourceStatusLabel(sourceStatus, batch)", 1)[1].split(
        "purchaseApprovalStatusLabel", 1
    )[0]
    assert status_method.index("has_oa_logistics") < status_method.index("invalid_business")


def test_workspace_restores_latest_background_review_and_inserts_replacements_in_grid() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    load_method = source.split("async loadMaterialFeeWorkspace", 1)[1].split(
        "materialFeeBasisLabel", 1
    )[0]
    assert "get_source_ai_review_status" in load_method
    assert 'run_id: ""' in load_method
    assert "initializeMaterialAIDraft" in load_method
    grid_method = source.split("renderMaterialFeeGrid()", 1)[1].split(
        "approvalLinkNeedsReview", 1
    )[0]
    assert "materialReplacementRows" in grid_method
    assert "renderMaterialReplacementGridRow" in grid_method


def test_apply_does_not_reclassify_automatic_ai_values_as_manual_edits() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    apply_method = source.split("async applyMaterialAIFill()", 1)[1].split("async discardMaterialAIFill()", 1)[0]
    assert 'find("[data-mf-cell-input]").each' not in apply_method
    assert "result?.stale" in apply_method
    assert "const isCurrent" in apply_method
    discard_method = source.split("async discardMaterialAIFill()", 1)[1].split("findMaterialFeeItem", 1)[0]
    assert "const isCurrent" in discard_method
    assert "fill.discarding = true" in discard_method


def test_only_auto_adoptable_cells_initialize_as_ai_updates() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();
const fill=workspace.initializeMaterialAIDraft({run_id:'R1',status:'READY',draft:{rows:{I1:{gross_weight_kg:{status:'AI_DRAFT',can_auto_adopt:true,value:'12.5'},volume_m3:{status:'LOW_CONFIDENCE',can_auto_adopt:false,value:null}}}}});
console.log(JSON.stringify(fill));
""")
    assert result["runId"] == "R1"
    assert result["updates"] == {
        "I1:gross_weight_kg": {
            "item_name": "I1",
            "fieldname": "gross_weight_kg",
            "value": "12.5",
            "user_edited": False,
        }
    }


def test_editing_main_grid_in_ai_mode_changes_only_local_draft() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();
const state={aiFill:{status:'READY',updates:{}},materialDrafts:{},inputRevision:0};
workspace.ensureMaterialFeeState=()=>state;
const input={attr(name){return {'data-item-name':'I1','data-fieldname':'volume_m3','data-original-value':''}[name]},val(){return '1.25'}};
workspace.updateMaterialDraftFromInput(input);
console.log(JSON.stringify({ai:state.aiFill.updates,normal:state.materialDrafts}));
""")
    assert result["normal"] == {}
    assert result["ai"]["I1:volume_m3"]["value"] == "1.25"
    assert result["ai"]["I1:volume_m3"]["user_edited"] is True
