from html.parser import HTMLParser
from pathlib import Path
import re

import pytest

from overseas_costing.tests.test_workbench_frontend_state import _fee_workspace_result


ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "page" / "overseas_cost_workbench" / "parts"


@pytest.mark.parametrize("button_class", ["ocw-primary-btn", "ocw-outline-btn"])
@pytest.mark.parametrize("state", ["", ":hover:not(:disabled)", ":disabled"])
def test_detached_autofill_modal_buttons_have_readable_explicit_colors(button_class, state):
    # Frappe appends dialogs outside the workbench theme-variable root.
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    selector = f".ocw-mf-ai-progress-modal .{button_class}{state}"
    declarations = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in [entry.strip() for entry in selectors.split(",")]:
            declarations.update(dict(re.findall(r"([\w-]+)\s*:\s*([^;]+)", body)))
    colors = {}
    for name in ("color", "background", "border-color"):
        value = declarations.get(name, "").strip()
        assert re.fullmatch(r"#[\da-fA-F]{6}", value), f"{selector} needs an explicit {name}, got {value!r}"
        colors[name] = value

    def luminance(hex_color):
        channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    lighter, darker = sorted([luminance(colors["color"]), luminance(colors["background"])], reverse=True)
    assert (lighter + 0.05) / (darker + 0.05) >= 4.5, f"{selector} text must remain readable"
    if state == ":disabled":
        assert declarations.get("opacity") == "1"
        assert declarations.get("cursor") == "not-allowed"


def test_toolbar_has_one_upload_entry_and_ai_action_on_one_line() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    render = source.split("\n  renderMaterialFeeWorkspace() {", 1)[1].split("\n  renderMaterialFeeMetric", 1)[0]
    assert "获取装箱资料" in render
    assert "自动填充资料" in render
    assert "导入 Excel 补资料" not in render
    assert "mf-import-xlsx" not in render


def test_source_tabs_keep_only_packing_plan_and_local_upload() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    tabs = source.split("renderMaterialSourceTabs(dialog)", 2)[2].split("renderMaterialAttachmentSources", 1)[0]
    assert "装箱计划表" in tabs
    assert "本地上传装箱单" in tabs
    assert "钉钉表单附件" not in tabs
    assert "评论附件与评论" not in tabs
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
    assert "data-action=\"mf-grid-scroll-left\"" in source
    assert "data-action=\"mf-grid-scroll-right\"" in source
    assert "data-mf-grid-scrollbar" in source
    assert ".ocw-mf-grid-table th:nth-child(-n+4)" not in css
    assert '[data-mf-grid-field="material_code"]' in css
    assert '[data-mf-grid-field="product_name"]' in css
    assert 'is-mf-grid-compact' in css
    assert "position: sticky" in css


def test_ai_review_ui_exposes_progress_candidates_and_single_confirmation_surface() -> None:
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
    assert "确认填充" in source
    assert 'data-action="mf-ai-review-cancel"' in source
    assert "renderSourceAIReviewProposals(true)" in source
    assert "data-action=\"mf-ai-adopt-candidate\"" in source
    assert ".is-ai-draft" in (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    workspace = source.split("renderMaterialFeeWorkspace()", 1)[1].split("renderMaterialFeeMetric", 1)[0]
    assert "renderSourceAIReviewProposals()" not in workspace
    assert "renderMaterialAIFillFooter()" not in workspace


def test_ai_poll_switches_progress_dialog_to_confirmation_without_rerendering_workspace() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    poll = source.split("async pollMaterialAIFill", 1)[1].split("updateMaterialAIDraftFromInput", 1)[0]
    assert "updateMaterialAIProgressSurface" in poll
    assert "renderMaterialFeeWorkspace" not in poll
    assert "showMaterialAIReadyDraft" in poll


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


def test_ai_analysis_never_flushes_or_writes_pending_business_inputs() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    start = source.split("async runMaterialAIFillStart", 1)[1].split(
        "async pollMaterialAIFill", 1
    )[0]
    assert "flushMaterialFeeInputs" not in start
    assert "pendingWrites.size" in start
    assert "selected_source_ids_json" in start


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
    updater = source.split("\n  updateMaterialAIProgressSurface()", 1)[1].split(
        "showMaterialAIReadyDraft", 1
    )[0]
    assert "replaceWith" not in updater
    assert "updateMaterialAIProgressSources" in updater


def test_ai_progress_dialog_becomes_wide_confirmation_with_fixed_actions() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    assert "openMaterialAIProgressDialog" in source
    assert 'data-action="mf-ai-minimize"' in source
    assert 'data-action="mf-ai-progress-restore"' in source
    assert 'data-action="mf-ai-review-cancel"' in source
    assert 'data-action="mf-ai-change-sources"' in source
    assert "确认填充" in source
    assert "系统直读" in source
    assert "AI 识别" in source
    assert "materialAIPhysicalSummary" in source
    assert "净重 ${this.escape(physical.netWeight)} kg" in source
    assert "毛重 ${this.escape(physical.grossWeight)} kg" in source
    assert "资料来源" in source
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


AUTOFILL_FIXTURE = r"""
const workspace=new Harness();
workspace.escape=(value)=>String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
workspace.detailState={batchName:'B1',versionName:'V1',tab:'documents'};
const state={batchName:'B1',materials:{items:[{name:'I1',material_code:'SKU1',product_name:'原物料',quantity:'2',net_weight_kg:'1'}]},fees:{fees:[]}};
workspace.materialFeeState=state;
workspace.ensureMaterialFeeState=()=>state;
state.aiFill=workspace.initializeMaterialAIDraft({run_id:'R1',status:'READY',review_mode:true,proposals:[
 {proposal_id:'logistics',proposal_type:'logistics_reconcile',default_selected:true,result_origin:'SYSTEM',payload:{}},
 {proposal_id:'packing',proposal_type:'item_update',target_item_name:'I1',default_selected:true,payload:{fields:{net_weight_kg:'12'}}},
 {proposal_id:'quote',proposal_type:'fee_update',default_selected:false,payload:{amount:'88',currency:'USD'},conflict:true}
],draft:{rows:{},autofill_preview:{items:[{name:'I1',stable_line_key:'K1',row_no:1,material_code:'SKU1',product_name:'<img src=x onerror=alert(1)>',quantity:'2',actual_shipped_qty:'3',shipped_uom:'箱',net_weight_kg:'12',gross_weight_kg:'14',volume_m3:'0.6',goods_value:'100'},{name:'I2',material_code:'SKU2',product_name:'完整第二行',quantity:'4'}],fees:[{proposal_id:'fee',fee_type:'国际运费',amount:'25',currency:'USD',previous_amount:'20',carrier:'<承运人>'}],unresolved:[{message:'<需要核对>'}],changes:[]}},source_progress:[{source_id:'S1',label:'<资料>',selected:true,read_status:'READ'}]});
"""


class _AutofillHTML(HTMLParser):
    def __init__(self, markup: str) -> None:
        super().__init__()
        self.details = []
        self.visible_checkboxes = 0
        self.actions = {}
        self.feed(markup)

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "details":
            self.details.append("open" in attributes)
        if tag == "input" and attributes.get("type") == "checkbox" and all(self.details):
            self.visible_checkboxes += 1
        if tag == "button" and "data-action" in attributes:
            self.actions[attributes["data-action"]] = attributes

    def handle_endtag(self, tag: str) -> None:
        if tag == "details":
            self.details.pop()


def test_autofill_ready_renders_full_table_without_visible_candidate_checkboxes() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + "console.log(JSON.stringify({html:workspace.renderMaterialAIReviewDialogContent(),selected:[...state.aiFill.selections]}));")
    markup = result["html"]
    assert "data-mf-ai-autofill-preview" in markup
    for content in ("SKU1", "SKU2", "完整第二行", "实发数量", "净重", "毛重", "体积", "货值", "国际运费", "25", "20"):
        assert content in markup
    assert "&lt;img src=x onerror=alert(1)&gt;" in markup
    assert "&lt;需要核对&gt;" in markup
    assert "&lt;承运人&gt;" in markup
    assert "<img" not in markup
    assert "高级：来源与其他方案" in markup
    assert _AutofillHTML(markup).visible_checkboxes == 0
    assert "确认填充" in markup
    assert "已选" not in markup
    assert "确认写入（" not in markup
    assert result["selected"] == ["logistics", "packing"]
    assert "disabled" not in _AutofillHTML(markup).actions["mf-ai-apply"]


def test_autofill_preview_distinguishes_purchase_and_shipment_quantities():
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill.draft.autofill_preview.items[0].quantity='200000';
state.aiFill.draft.autofill_preview.items[0].actual_shipped_qty='22000';
console.log(JSON.stringify({html:workspace.renderMaterialAIAutofillPreview(state.aiFill)}));
""")
    assert "<th>采购数量</th>" in result["html"]
    assert "<th>实发数量</th>" in result["html"]
    assert ">200000<" in result["html"]
    assert ">22000<" in result["html"]


def test_autofill_fee_preview_formats_change_without_mutating_payload_values():
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill.draft.autofill_preview.fees=[{fee_type:'国际运费',amount:'7756.2',previous_amount:2004,currency:'RMB'}];
const before=JSON.stringify(state.aiFill);
const html=workspace.renderMaterialAIAutofillPreview(state.aiFill);
console.log(JSON.stringify({html,unchanged:before===JSON.stringify(state.aiFill)}));
""")
    assert ">7756.20<" in result["html"]
    assert ">2004.00<" in result["html"]
    assert "2004.00 → 7756.20 RMB" in result["html"]
    assert "<input" not in result["html"]
    assert result["unchanged"] is True


def test_autofill_fee_preview_does_not_coerce_missing_or_unsafe_values_to_zero():
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill.draft.autofill_preview.fees=[{amount:'',previous_amount:null,currency:'<USD>'},{amount:'<invalid>',previous_amount:0}];
console.log(JSON.stringify({html:workspace.renderMaterialAIAutofillPreview(state.aiFill)}));
""")
    assert "— → — &lt;USD&gt;" in result["html"]
    assert "0.00 → &lt;invalid&gt;" in result["html"]
    assert "<invalid>" not in result["html"]
    assert "<USD>" not in result["html"]


def test_autofill_progress_and_ready_keep_actions_outside_scroll_body() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
const ready=workspace.renderMaterialAIReviewDialogContent();
state.aiFill={status:'RUNNING',progress_percent:30};
const progress=workspace.renderMaterialAIProgressDialogContent();
state.aiFill={status:'FAILED'};
const failed=workspace.renderMaterialAIProgressDialogContent();
state.aiFill={status:'RUNNING',stalled:true};
const stalled=workspace.renderMaterialAIProgressDialogContent();
console.log(JSON.stringify({ready,progress,failed,stalled}));
""")
    for markup in result.values():
        assert 'class="ocw-mf-ai-dialog-body"' in markup
        assert 'class="ocw-mf-ai-dialog-footer"' in markup
        assert markup.index("</main>") < markup.index('<footer class="ocw-mf-ai-dialog-footer"')
        assert "mf-ai-review-cancel" in _AutofillHTML(markup).actions
    for name in ("progress", "failed", "stalled"):
        assert "disabled" in _AutofillHTML(result[name]).actions["mf-ai-apply"]
    for name in ("failed", "stalled"):
        assert "hidden" not in _AutofillHTML(result[name]).actions["mf-ai-progress-retry"]
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    assert ".ocw-mf-ai-dialog-body" in css
    assert "overflow-y: auto" in css
    assert ".ocw-mf-ai-dialog-footer" in css


def test_autofill_falls_back_to_legacy_proposals_and_keeps_edits_in_preview() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
delete state.aiFill.draft.autofill_preview;
state.aiFill.edits.packing={net_weight_kg:'18'};
const before=workspace.renderMaterialAIReviewDialogContent();
state.aiFill.selections.delete('packing');
const after=workspace.renderMaterialAIReviewDialogContent();
console.log(JSON.stringify({before,after,original:state.materials.items[0].net_weight_kg}));
""")
    before = result["before"].split("<details", 1)[0]
    after = result["after"].split("<details", 1)[0]
    assert "SKU1" in before
    assert ">18<" in before
    assert ">18<" not in after
    assert result["original"] == "1"


def test_autofill_cancel_closes_and_preserves_ready_draft_without_writes() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
const handlers={};
const wrapper={length:1,addClass(){return this},off(){return this},on(name,selector,handler){handlers[name+selector]=handler;return this}};
let hides=0,writes=0;
frappe.ui={Dialog:class{constructor(){this.$wrapper=wrapper}show(){}hide(){hides+=1}}};
global.$=(value)=>value;
workspace.call=async()=>{writes+=1};
workspace.updateMaterialAIProgressSurface=()=>{};
workspace.renderMaterialAIReviewDialog=()=>{};
workspace.openMaterialAIProgressDialog();
handlers['click.ocwAIProgress[data-action]']({currentTarget:{attr:()=> 'mf-ai-review-cancel'}});
console.log(JSON.stringify({hides,writes,status:state.aiFill.status,selected:[...state.aiFill.selections],visible:state.aiFill.reviewDialogVisible}));
""")
    assert result == {"hides": 1, "writes": 0, "status": "READY", "selected": ["logistics", "packing"], "visible": False}


def test_autofill_apply_submits_default_logistics_action_and_refreshes_workspace() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
let submitted,refreshes=0;
workspace.ensureEditSession=async()=>true;
workspace.renderMaterialAIReviewDialog=()=>{};
workspace.updateMaterialFeeExpectedModified=()=>{};
workspace.loadMaterialFeeWorkspace=async()=>{refreshes+=1};
workspace.call=async(method,args)=>{submitted={method,args};return {ok:true}};
await workspace.applyMaterialAIFill();
console.log(JSON.stringify({submitted,refreshes,fill:state.aiFill}));
""")
    assert result["submitted"]["method"].endswith("apply_source_ai_review")
    assert result["submitted"]["args"]["selections_json"] == '["logistics","packing"]'
    assert result["refreshes"] == 1
    assert result["fill"] is None


def test_autofill_stalled_retry_starts_new_run_despite_previous_start_promise() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
const handlers={};
const wrapper={length:1,addClass(){return this},off(){return this},on(name,selector,handler){handlers[name+selector]=handler;return this}};
frappe.ui={Dialog:class{constructor(){this.$wrapper=wrapper}show(){}hide(){}}};
global.$=(value)=>value;
workspace.updateMaterialAIProgressSurface=()=>{};
workspace.renderMaterialAIReviewDialog=()=>{};
workspace.openMaterialAIProgressDialog();
workspace.openMaterialAIProgressDialog=()=>{};
state.aiFill={status:'RUNNING',runId:'OLD',stalled:true};
state.aiStartPromise=new Promise(()=>{});
state.pendingWrites=new Set();
let options;
workspace.runMaterialAIFillStart=async(_state,nextOptions)=>{options=nextOptions};
handlers['click.ocwAIProgress[data-action]']({currentTarget:{attr:()=> 'mf-ai-progress-retry'}});
await Promise.resolve();
console.log(JSON.stringify({force:options?.force??false,status:state.aiFill?.status}));
""")
    assert result == {"force": True, "status": "STARTING"}


def test_autofill_old_poll_reply_cannot_replace_retried_run() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill={status:'RUNNING',runId:'OLD'};
let release;
workspace.call=()=>new Promise((resolve)=>{release=resolve});
workspace.updateMaterialAIProgressSurface=()=>{};
const previousPoll=workspace.pollMaterialAIFill(state,'B1','V1','OLD');
state.aiFill={status:'RUNNING',runId:'NEW'};
release({ok:true,run_id:'OLD',status:'READY'});
await previousPoll;
console.log(JSON.stringify({runId:state.aiFill.runId,status:state.aiFill.status}));
""")
    assert result == {"runId": "NEW", "status": "RUNNING"}


def test_autofill_stale_apply_returns_to_retry_surface() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
workspace.ensureEditSession=async()=>true;
workspace.renderMaterialAIReviewDialog=()=>{};
let progressOpens=0;
workspace.openMaterialAIProgressDialog=()=>{progressOpens+=1};
workspace.call=async()=>({ok:false,stale:true,message:'资料已经变化'});
await workspace.applyMaterialAIFill();
console.log(JSON.stringify({status:state.aiFill.status,applying:state.aiFill.applying,progressOpens}));
""")
    assert result == {"status": "STALE", "applying": False, "progressOpens": 1}


def test_autofill_editing_alternative_replaces_conflicting_default_and_updates_preview() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill.proposals.push({proposal_id:'other',proposal_type:'fee_update',default_selected:true,conflict_group:'freight',payload:{amount:'25',currency:'USD'}});
state.aiFill.proposals.find((row)=>row.proposal_id==='quote').conflict_group='freight';
state.aiFill.selections.add('other');
workspace.updateMaterialAIReviewSelectionSurface=()=>{};
workspace.updateSourceAIReviewEdit({attr:(name)=>({'data-proposal-id':'quote','data-fieldname':'amount'}[name]),val:()=> '90'});
console.log(JSON.stringify({selected:[...state.aiFill.selections],preview:workspace.renderMaterialAIAutofillPreview(state.aiFill)}));
""")
    assert "quote" in result["selected"]
    assert "other" not in result["selected"]
    assert ">90.00<" in result["preview"]


def test_autofill_new_logistics_rows_cannot_create_browser_edits() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
const proposal={proposal_id:'new-row',proposal_type:'item_update',target_item_name:'draft-123',payload:{fields:{net_weight_kg:'2'}}};
state.aiFill.proposals.push(proposal);
workspace.updateMaterialAIReviewSelectionSurface=()=>{};
const accepted=workspace.updateMaterialAIDraftValue('draft-123','net_weight_kg','3','2');
workspace.updateSourceAIReviewEdit({attr:(name)=>({'data-proposal-id':'new-row','data-fieldname':'net_weight_kg'}[name]),val:()=> '4'});
workspace.updateSourceAIReviewEdit({attr:(name)=>({'data-proposal-id':'logistics','data-fieldname':'rows'}[name]),val:()=> 'unexpected'});
console.log(JSON.stringify({accepted,manual:state.aiFill.manualUpdates,edits:state.aiFill.edits,html:workspace.renderSourceAIReviewProposalFields(proposal)}));
""")
    assert result["accepted"] is False
    assert result["manual"] == {}
    assert result["edits"] == {}
    assert "data-mf-ai-edit" not in result["html"]


def test_autofill_force_retry_preserves_force_and_sources_after_network_failure() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.pendingWrites=new Set();
state.aiRunGeneration=1;
workspace.updateMaterialAIProgressSurface=()=>{};
workspace.openMaterialAIProgressDialog=()=>{};
workspace.pollMaterialAIFill=async()=>{};
global.window={setTimeout:(resolve)=>resolve()};
const requests=[];
workspace.call=async(_method,args)=>{requests.push(args);if(requests.length===1)throw new Error('connection failed before dispatch');return {ok:true,run_id:'NEW',status:'QUEUED'}};
await workspace.runMaterialAIFillStart(state,{force:true,selectedSourceIds:['S1']});
console.log(JSON.stringify({forces:requests.map((row)=>row.force),sources:requests.map((row)=>row.selected_source_ids_json)}));
""")
    assert result == {"forces": [1, 1], "sources": ['["S1"]', '["S1"]']}


def test_autofill_retired_start_generation_stops_before_request_after_backoff() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.pendingWrites=new Set();
state.aiRunGeneration=1;
workspace.updateMaterialAIProgressSurface=()=>{};
workspace.openMaterialAIProgressDialog=()=>{};
workspace.pollMaterialAIFill=async()=>{};
let calls=0;
workspace.call=async()=>{calls+=1;if(calls===1)throw new Error('network down');return {ok:true,run_id:'OLD',status:'QUEUED'}};
global.window={setTimeout:(resolve)=>{state.aiRunGeneration=2;state.aiFill={status:'RUNNING',runId:'NEW'};resolve()}};
await workspace.runMaterialAIFillStart(state,{force:true});
console.log(JSON.stringify({calls,runId:state.aiFill.runId}));
""")
    assert result == {"calls": 1, "runId": "NEW"}


def test_autofill_selected_material_split_and_edits_overlay_server_preview() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
const proposal={proposal_id:'split',proposal_type:'material_replace',target_item_name:'I1',default_selected:false,payload:{replacement_rows:[{product_name:'默认拆分A',quantity:'1'},{product_name:'默认拆分B',quantity:'1'}]}};
state.aiFill.proposals.push(proposal);
state.aiFill.selections.add('split');
const selected=workspace.materialAIAutofillPreview(state.aiFill);
state.aiFill.edits.split={replacement_rows:[{product_name:'修改拆分A',quantity:'3'},{product_name:'修改拆分B',quantity:'4'}]};
const edited=workspace.materialAIAutofillPreview(state.aiFill);
state.aiFill.selections.delete('split');
const deselected=workspace.materialAIAutofillPreview(state.aiFill);
console.log(JSON.stringify({selected:selected.items.map((row)=>row.product_name),edited:edited.items.map((row)=>[row.product_name,row.quantity]),deselected:deselected.items.map((row)=>row.name),original:state.aiFill.draft.autofill_preview.items[0].name}));
""")
    assert result["selected"] == ["默认拆分A", "默认拆分B", "完整第二行"]
    assert result["edited"] == [["修改拆分A", "3"], ["修改拆分B", "4"], ["完整第二行", "4"]]
    assert result["deselected"] == ["I1", "I2"]
    assert result["original"] == "I1"


def test_autofill_fee_category_preview_uses_exact_edited_submission() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill.proposals.push({proposal_id:'fee',proposal_type:'fee_update',default_selected:true,payload:{expense_category:'国际运费',amount:'25',currency:'USD'}});
state.aiFill.selections.add('fee');
workspace.updateMaterialAIReviewSelectionSurface=()=>{};
workspace.updateSourceAIReviewEdit({attr:(name)=>({'data-proposal-id':'fee','data-fieldname':'expense_category'}[name]),val:()=> '<修改费用类别>'});
console.log(JSON.stringify({preview:workspace.renderMaterialAIAutofillPreview(state.aiFill),category:state.aiFill.edits.fee.expense_category}));
""")
    assert result["category"] == "<修改费用类别>"
    assert "&lt;修改费用类别&gt;" in result["preview"]
    assert "国际运费" not in result["preview"]


def test_autofill_progress_sources_share_only_modal_body_vertical_scroll() -> None:
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    sources = css.split(".ocw-mf-ai-source-progress {", 1)[1].split("}", 1)[0]
    body = css.split(".ocw-mf-ai-dialog-body {", 1)[1].split("}", 1)[0]
    assert "max-height" not in sources
    assert "overflow" not in sources
    assert "overflow-y: auto" in body


def test_autofill_package_count_is_readonly_and_recovers_nested_packing_metadata() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill.draft.autofill_preview.items[0].package_count='17';
state.aiFill.draft.autofill_preview.items[1].extra_json=JSON.stringify({logistics_row:{packing:{package_count:'23'}}});
const server=workspace.renderMaterialAIAutofillPreview(state.aiFill);
delete state.aiFill.draft.autofill_preview;
state.materials.items[0].extra_json=JSON.stringify({logistics_row:{packing:{package_count:'31'}}});
const fallback=workspace.renderMaterialAIAutofillPreview(state.aiFill);
console.log(JSON.stringify({server,fallback}));
""")
    assert ">箱数<" in result["server"]
    assert ">17<" in result["server"]
    assert ">23<" in result["server"]
    assert ">31<" in result["fallback"]
    assert "<input" not in result["server"]
    assert "<input" not in result["fallback"]


def test_autofill_advanced_edit_updates_physical_totals_with_table() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
const updates={};
state.aiProgressDialog={$wrapper:{length:1,find(selector){return {each(){return this},html(value){updates[selector]=value;return this},prop(){return this},text(){return this}}}}};
state.aiFill.edits.packing={net_weight_kg:'18'};
workspace.updateMaterialAIReviewSelectionSurface();
console.log(JSON.stringify({summary:updates['.ocw-mf-ai-physical-summary']||'',table:updates['[data-mf-ai-autofill-preview]']||''}));
""")
    assert "净重 18 kg" in result["summary"]
    assert "毛重 14 kg" in result["summary"]
    assert ">18<" in result["table"]


def test_autofill_adopted_fee_keeps_other_quotes_readonly_inside_advanced_details() -> None:
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
state.aiFill.proposals.push({proposal_id:'approved-fee',proposal_type:'fee_update',default_selected:true,carrier:'大墨仓',payload:{expense_category:'海运费',amount:'7756.20',currency:'RMB'},alternatives:[
 {carrier:'大墨仓',amount:7756.2,currency:'RMB',unit_rate:3100,pricing_basis:'volume',source_field:'物流报价',evidence_line:'大墨仓报价：3100元/立方，费用7756.2元',evidence_line_no:2},
 {carrier:'<SISA>',amount:9982.98,currency:'RMB',unit_rate:3420,pricing_basis:'volume',source_field:'物流报价',evidence_line:'<报价原文>',evidence_line_no:3}
]});
state.aiFill.selections.add('approved-fee');
console.log(JSON.stringify({html:workspace.renderMaterialAIReviewDialogContent(),selected:[...state.aiFill.selections]}));
""")
    markup = result["html"]
    assert "data-mf-ai-alternative-quotes" in markup
    quotes = markup.split('data-mf-ai-alternative-quotes="1"', 1)[1].split("</section>", 1)[0]
    assert "报价记录（只读）" in quotes
    for text in ("审批采用", "其他报价", "7756.2", "9982.98", "3100", "3420", "体积", "物流报价", "第 3 行", "&lt;SISA&gt;", "&lt;报价原文&gt;"):
        assert text in quotes
    assert "<input" not in quotes
    assert "<button" not in quotes
    assert "<SISA>" not in quotes
    assert markup.index("高级：来源与其他方案") < markup.index("data-mf-ai-alternative-quotes")
    assert _AutofillHTML(markup).visible_checkboxes == 0
    assert result["selected"] == ["logistics", "packing", "approved-fee"]


def test_autofill_quote_history_ignores_invalid_optional_rows():
    result = _fee_workspace_result(AUTOFILL_FIXTURE + r"""
const proposal={proposal_type:'fee_update',carrier:'A',alternatives:[null,'unexpected',[],{carrier:'A',amount:50,currency:'RMB'}]};
let html='',error='';
try {html=workspace.renderSourceAIReviewAlternativeQuotes(proposal)} catch(exception) {error=exception.message}
console.log(JSON.stringify({html,error}));
""")
    assert result["error"] == ""
    assert ">50<" in result["html"]
    assert "unexpected" not in result["html"]
