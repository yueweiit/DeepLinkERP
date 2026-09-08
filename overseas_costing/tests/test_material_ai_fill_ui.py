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


def test_ai_poll_updates_progress_surface_without_rerendering_workspace() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    poll = source.split("async pollMaterialAIFill", 1)[1].split("updateMaterialAIDraftFromInput", 1)[0]
    assert "updateMaterialAIProgressSurface" in poll
    assert "renderMaterialFeeWorkspace" not in poll
    assert "aiPendingReady" in poll


def test_ai_candidates_use_one_fixed_workspace_popover_instead_of_cell_details() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    renderer = source.split("renderMaterialAICandidates(itemName", 1)[1].split(
        "renderMaterialAIFillBanner", 1
    )[0]

    assert "<details" not in renderer
    assert 'data-action="mf-ai-open-candidate"' in renderer
    assert 'data-mf-ai-candidate-popover="1"' in source
    assert "openMaterialAICandidatePopover" in source
    assert "closeMaterialAICandidatePopover" in source
    assert ".ocw-mf-ai-candidate-popover" in css
    assert "position: fixed" in css.split(".ocw-mf-ai-candidate-popover", 1)[1].split("}", 1)[0]
    assert ".ocw-mf-ai-candidates[open]" not in css


def test_ai_start_is_single_flight_and_normal_click_does_not_force_new_run() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();
const state={aiFill:null,aiPendingReady:null,aiProgressDialog:null,aiProgressMinimized:false,aiClarification:'',pendingWrites:new Set(),materialDrafts:{},feeDrafts:{},inputRevision:0};
workspace.materialFeeState=state;
workspace.detailState={batchName:'B1',versionName:'V1',tab:'documents'};
workspace.ensureMaterialFeeState=()=>state;
workspace.flushMaterialFeeInputs=async()=>true;
workspace.openMaterialAIProgressDialog=()=>{};
workspace.updateMaterialAIProgressSurface=()=>{};
workspace.pollMaterialAIFill=async()=>{};
let callCount=0;
let sentForce=null;
let release;
workspace.call=async(_method,args)=>{
  callCount+=1;
  sentForce=args.force;
  await new Promise((resolve)=>{release=resolve});
  return {ok:true,run_id:'R1',status:'QUEUED',progress_revision:0};
};
const first=workspace.startMaterialAIFill();
const second=workspace.startMaterialAIFill();
await new Promise((resolve)=>setTimeout(resolve,0));
release();
await Promise.all([first,second]);
console.log(JSON.stringify({callCount,sentForce,status:state.aiFill.status,hasStartPromise:Boolean(state.aiStartPromise)}));
""")
    assert result == {
        "callCount": 1,
        "sentForce": 0,
        "status": "QUEUED",
        "hasStartPromise": False,
    }


def test_ai_poll_is_incremental_unfrozen_and_skips_unchanged_revision() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();
const state={aiFill:{status:'RUNNING',progress_revision:4},aiPendingReady:null};
workspace.materialFeeState=state;
workspace.detailState={batchName:'B1',versionName:'V1',tab:'documents'};
const calls=[];
const replies=[
  {ok:true,status:'RUNNING',progress_revision:4,unchanged:true},
  {ok:true,status:'RUNNING',progress_revision:5,progress_percent:60},
  {ok:true,status:'READY',progress_revision:6,progress_percent:100,run_id:'R1'},
];
workspace.call=async(method,args,freeze)=>{calls.push({args,freeze});return replies.shift();};
let surfaceUpdates=0;
workspace.updateMaterialAIProgressSurface=()=>{surfaceUpdates+=1};
global.window={setTimeout:(resolve)=>resolve()};
await workspace.pollMaterialAIFill(state,'B1','V1','R1');
console.log(JSON.stringify({surfaceUpdates,calls,pending:state.aiPendingReady?.status}));
""")
    assert result["surfaceUpdates"] == 2
    assert result["pending"] == "READY"
    assert all(call["freeze"] is False for call in result["calls"])
    assert result["calls"][0]["args"]["after_revision"] == 4
    assert result["calls"][1]["args"]["after_revision"] == 4
    assert result["calls"][2]["args"]["after_revision"] == 5


def test_ai_poll_retries_transient_status_errors_inside_progress_surface() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();
const state={aiFill:{status:'RUNNING',progress_revision:2},aiPendingReady:null};
workspace.materialFeeState=state;
workspace.detailState={batchName:'B1',versionName:'V1',tab:'documents'};
let calls=0;
workspace.call=async()=>{calls+=1;if(calls===1)throw new Error('network down');return {ok:true,status:'READY',progress_revision:3,progress_percent:100,run_id:'R1'};};
let globalErrors=0;
workspace.showError=()=>{globalErrors+=1};
workspace.openMaterialAIProgressDialog=()=>{};
let surfaceUpdates=0;
workspace.updateMaterialAIProgressSurface=()=>{surfaceUpdates+=1};
global.window={setTimeout:(resolve)=>resolve()};
await workspace.pollMaterialAIFill(state,'B1','V1','R1');
console.log(JSON.stringify({calls,globalErrors,surfaceUpdates,status:state.aiFill.status,connectionError:state.aiFill.connection_error||''}));
""")
    assert result == {
        "calls": 2,
        "globalErrors": 0,
        "surfaceUpdates": 2,
        "status": "READY",
        "connectionError": "",
    }


def test_progress_surface_updates_existing_nodes_without_replacing_roots() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    updater = source.split("updateMaterialAIProgressSurface()", 2)[2].split(
        "showMaterialAIReadyDraft", 1
    )[0]
    assert "replaceWith" not in updater
    assert "updateMaterialAIProgressSources" in updater


def test_ai_progress_uses_minimizable_dialog_and_explicit_view_draft() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    assert "openMaterialAIProgressDialog" in source
    assert 'data-action="mf-ai-minimize"' in source
    assert 'data-action="mf-ai-progress-restore"' in source
    assert 'data-action="mf-ai-view-draft"' in source
    assert "material_proposal_count" in source
    assert "packing_proposal_count" in source
    assert "fee_proposal_count" in source
    assert "ocw-mf-ai-progress-dialog" in css
    assert "ocw-mf-ai-progress-chip" in css


def test_material_grid_keeps_static_widths_while_scrolling() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    scroll = source.split("bindMaterialGridScrollControls()", 2)[2].split("initializeMaterialAIDraft", 1)[0]
    assert "is-horizontally-scrolled" not in scroll
    assert "column.style.width" not in scroll
    assert ".ocw-mf-grid-shell.is-horizontally-scrolled" not in css


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
    assert "aiPendingReady" in load_method
    assert "draftVisible: false" in load_method
    view_method = source.split("showMaterialAIReadyDraft()", 2)[2].split(
        "sourceAIReviewProposalLabel", 1
    )[0]
    assert "initializeMaterialAIDraft" in view_method
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
    assert "manual_updates_json" in apply_method
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
const state={aiFill:{status:'READY',draftVisible:true,updates:{}},materialDrafts:{},inputRevision:0};
workspace.ensureMaterialFeeState=()=>state;
const input={attr(name){return {'data-item-name':'I1','data-fieldname':'volume_m3','data-original-value':''}[name]},val(){return '1.25'}};
workspace.updateMaterialDraftFromInput(input);
console.log(JSON.stringify({ai:state.aiFill.updates,normal:state.materialDrafts}));
""")
    assert result["normal"] == {}
    assert result["ai"]["I1:volume_m3"]["value"] == "1.25"
    assert result["ai"]["I1:volume_m3"]["user_edited"] is True


def test_ai_review_allows_manual_edit_without_matching_ai_proposal() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();
const state={aiFill:{status:'READY',draftVisible:true,review_mode:true,updates:{},manualUpdates:{}},materialDrafts:{},inputRevision:0};
workspace.ensureMaterialFeeState=()=>state;
const input={attr(name){return {'data-item-name':'I1','data-fieldname':'goods_value','data-original-value':'--'}[name]},val(){return '120'}};
workspace.updateMaterialDraftFromInput(input);
console.log(JSON.stringify({updates:state.aiFill.updates,manual:state.aiFill.manualUpdates}));
""")
    assert result["updates"] == {}
    assert result["manual"]["I1:goods_value"] == {
        "item_name": "I1",
        "fieldname": "goods_value",
        "value": "120",
        "reason": "",
    }


def test_purchase_value_columns_are_editable_but_purchase_identity_stays_readonly() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();workspace.detailState={};
workspace.materialFeeState={batchName:'',showAuxiliary:true};
const columns=workspace.materialFeeGridColumns();
const mapped=Object.fromEntries(columns.map(column=>[column.field,Boolean(column.readonly)]));
console.log(JSON.stringify(mapped));
""")
    assert result["goods_value"] is False
    assert result["unit_price"] is False
    assert result["unit_price_uom"] is False
    assert result["purchase_currency"] is False
    assert result["purchase_uom"] is False
    assert result["source_doc_no"] is True
    assert result["material_code"] is True
    assert result["product_name"] is True
    assert result["quantity"] is True


def test_generic_grid_requires_reason_when_correcting_existing_purchase_value() -> None:
    source = (PARTS / "100-crud-edit.js").read_text(encoding="utf-8")
    commit = source.split("async commitCellEdit($cell)", 1)[1].split(
        "requestEditConfirm(fieldLabel, newValue)", 1
    )[0]
    assert "purchaseCorrectionFields" in commit
    assert "isPurchaseCorrection" in commit
    assert "isSpecialOverride || isPurchaseCorrection" in commit


def test_ready_result_does_not_change_grid_until_user_views_draft() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    replacements = source.split("materialReplacementRows(items = [])", 1)[1].split(
        "renderMaterialReplacementGridRow", 1
    )[0]
    assert "!fill.draftVisible" in replacements
    grid = source.split("renderMaterialFeeGrid()", 1)[1].split(
        "materialReplacementRows(items = [])", 1
    )[0]
    assert 'state.aiFill?.draftVisible' in grid


def test_polling_updates_only_progress_surface_until_ready() -> None:
    result = _fee_workspace_result(r"""
const workspace=new Harness();
const state={aiFill:{status:'RUNNING'},aiPendingReady:null};
workspace.materialFeeState=state;
workspace.detailState={batchName:'B1',versionName:'V1',tab:'documents'};
const replies=[{ok:true,status:'RUNNING',progress_percent:30},{ok:true,status:'READY',progress_percent:100,run_id:'R1'}];
workspace.call=async()=>replies.shift();
let surfaceUpdates=0;
let workspaceRenders=0;
workspace.updateMaterialAIProgressSurface=()=>{surfaceUpdates+=1};
workspace.renderMaterialFeeWorkspace=()=>{workspaceRenders+=1};
global.window={setTimeout:(resolve)=>resolve()};
await workspace.pollMaterialAIFill(state,'B1','V1','R1');
console.log(JSON.stringify({surfaceUpdates,workspaceRenders,pending:state.aiPendingReady?.status,draftVisible:state.aiFill.draftVisible}));
""")
    assert result == {
        "surfaceUpdates": 2,
        "workspaceRenders": 0,
        "pending": "READY",
        "draftVisible": False,
    }


def test_multicell_paste_uses_transactional_manual_ai_updates_and_protects_purchase_corrections() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    preview = source.split("previewMaterialPaste($startInput, text)", 1)[1].split(
        "async applyMaterialPaste", 1
    )[0]
    apply = source.split("async applyMaterialPaste(dialog, updates)", 1)[1].split(
        "findMaterialFee(feeKey)", 1
    )[0]
    assert "materialPurchaseCorrectionFields" in preview
    assert "已有有效采购值" in preview
    assert "updateMaterialAIDraftValue" in apply
    assert "fill.updates[`${item_name}:${fieldname}`]" not in apply
