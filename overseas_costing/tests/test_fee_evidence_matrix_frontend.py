"""Execute the A1 fee-evidence matrix helpers in Node."""

import json
import subprocess
from pathlib import Path


PARTS = Path(__file__).resolve().parents[1] / "page/overseas_cost_workbench/parts"
MATRIX_PART = PARTS / "78-fee-evidence-review-matrix.js"


def run_js(body: str) -> None:
    prelude = f"""
const fs=require('fs');
const Workbench=new Function('return class {{'+fs.readFileSync({json.dumps(str(MATRIX_PART))},'utf8')+'}}')();
const w=new Workbench();
w.escape=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
w.materialFeeCurrencyOptions=()=>[{{value:'RMB',label:'人民币 (RMB)'}},{{value:'MXN',label:'墨西哥比索 (MXN)'}}];
w.renderCurrentSourceReviewControls=()=>'<div data-current-source-review></div>';
const assert=require('assert').strict;
"""
    result = subprocess.run(
        ["node", "-e", prelude + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def run_integrated_js(body: str) -> None:
    workspace_part = PARTS / "78-material-fee-workspace.js"
    prelude = f"""
const fs=require('fs');
const Workbench=new Function('return class {{'+fs.readFileSync({json.dumps(str(MATRIX_PART))},'utf8')+fs.readFileSync({json.dumps(str(workspace_part))},'utf8')+'}}')();
const w=new Workbench();
w.escape=v=>String(v??'');
const assert=require('assert').strict;
"""
    result = subprocess.run(
        ["node", "-e", prelude + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


DRAFT = r"""
const draft={
  evidence:{proposal_id:'evidence:classification',currency:'MXN',original_amount:'150',evidence_type:'TAX_CERTIFICATE',accounting_role:'FINAL_BILL',direction:'DEBIT',is_final:1,default_selected:true,reason:'完税凭证'},
  fee_splits:[
    {proposal_id:'fee:import_tax',logical_fee_key:'import_tax',label:'进口税费',currency:'MXN',amount:'100',amount_status:'ACTUAL',default_selected:true},
    {proposal_id:'fee:customs_clearance_fee',logical_fee_key:'customs_clearance_fee',label:'清关费',currency:'MXN',amount:'50',amount_status:'ACTUAL',default_selected:true}
  ],
  unclassified_difference:'10',
  components:[
    {proposal_id:'component:1',item:'ITEM-1',tax_code:'IGI',fee_logical_key:'import_tax',currency:'MXN',original_amount:'10',amount_rmb:'4',needs_review:true,warning:'低信心'},
    {proposal_id:'component:2',item:'ITEM-1',tax_code:'IGI',fee_logical_key:'import_tax',currency:'MXN',original_amount:'5',amount_rmb:'2'},
    {proposal_id:'component:3',item:'ITEM-2',component_type:'CUSTOMS_SERVICE',fee_logical_key:'customs_clearance_fee',currency:'MXN',original_amount:'30',amount_rmb:null}
  ],
  material_matrix:{
    columns:[
      {key:'IGI',label:'IGI',fee_logical_key:'import_tax'},
      {key:'IVA',label:'IVA',fee_logical_key:'import_tax'},
      {key:'DTA',label:'DTA',fee_logical_key:'import_tax'},
      {key:'PRV',label:'PRV',fee_logical_key:'import_tax'},
      {key:'PRV_IVA',label:'PRV_IVA',fee_logical_key:'import_tax'},
      {key:'CUSTOMS_SERVICE',label:'CUSTOMS_SERVICE',fee_logical_key:'customs_clearance_fee'}
    ],
    rows:[
      {item:'ITEM-1',material_code:'SKU-1',product_name:'眼镜',hs_code:'90041000',hs_suggestions:['99999999'],cells:{IGI:{proposals:[0,1],saved:[0]}}},
      {item:'ITEM-2',material_code:'SKU-2',product_name:'镜架',hs_code:'90031100',cells:{CUSTOMS_SERVICE:{proposals:[2],saved:[]}}}
    ],
    saved_components:[{id:'SAVED-1',item:'ITEM-1',tax_code:'IGI',currency:'MXN',original_amount:'18',amount_rmb:'7.2',status:'CONFIRMED'}],
    unmatched_lines:[{message:'凭证行无法归属具体物料'}],
    missing_fx:true
  }
};
"""


def test_a1_summary_is_collapsed_and_matrix_has_fixed_columns_and_all_rows() -> None:
    run_js(
        DRAFT
        + r"""
const review={selections:new Set(['evidence:classification','fee:import_tax','fee:customs_clearance_fee']),edits:{}};
const html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('<details class="ocw-mf-voucher-details"'));
assert(!html.includes('<details class="ocw-mf-voucher-details" open'));
assert(html.includes('凭证类型')&&html.includes('会计作用')&&html.includes('凭证总额')&&html.includes('费用拆分')&&html.includes('凭证待归类差额'));
const expected=['物料 / SKU','HS','IGI','IVA','DTA','PRV','PRV IVA','清关服务费','物料合计','核对状态'];
let last=-1; for(const label of expected){const next=html.indexOf(label);assert(next>last,label);last=next;}
assert(html.includes('SKU-1')&&html.includes('SKU-2'));
assert(html.includes('data-mf-fee-matrix-hs="ITEM-1"'));
assert(!html.includes('data-mf-fee-matrix-select'));
assert(html.includes('99999999')&&html.includes('HS 差异'));
assert(html.includes('无法归属具体物料'));
review.matrixDetailsOpen=true;
assert(w.renderFeeEvidenceReviewDraft(draft,review).includes('<details class="ocw-mf-voucher-details" data-mf-fee-voucher-details open>'));
"""
    )


def test_compact_legacy_cells_resolve_saved_value_before_ai_and_keep_suggestion() -> None:
    run_js(
        DRAFT
        + r"""
const cell=w.resolveFeeEvidenceMatrixCell(draft,0,'IGI');
assert.equal(cell.origin,'SAVED');
assert.equal(cell.originalAmount,'18');
assert.equal(cell.amountRmb,'7.2');
assert.equal(cell.suggestedOriginalAmount,'15');
assert.equal(cell.suggestedAmountRmb,'6');
assert.deepEqual(cell.sourceProposalIds,['component:1','component:2']);
assert(cell.warning.includes('低信心'));
assert.equal(w.resolveFeeEvidenceMatrixCell(draft,0,'IVA').warning,'');
"""
    )


def test_indexed_component_store_is_read_per_referenced_cell() -> None:
    run_js(
        r"""
const draft={components:[],component_contract:{mode:'INDEXED_COLUMNS_V1'},component_store:{format:'INDEXED_COLUMNS_V1',count:2,columns:{
 proposal_id:{values:['p1','p2']},item:{constant:'ITEM-1'},tax_code:{dictionary:['IGI','IVA'],indices:[0,1]},currency:{constant:'MXN'},original_amount:{values:['2','3']},amount_rmb:{values:['1','1.5']}
}},material_matrix:{columns:w.feeEvidenceMatrixColumns(),saved_components:[],rows:[{item:'ITEM-1',material_code:'SKU',hs_code:'1',cells:{IVA:{proposals:[1],saved:[]}}}]}};
const cell=w.resolveFeeEvidenceMatrixCell(draft,0,'IVA');
assert.equal(cell.originalAmount,'3');assert.equal(cell.amountRmb,'1.5');assert.deepEqual(cell.sourceProposalIds,['p2']);
"""
    )


def test_legacy_draft_without_matrix_still_builds_every_item_row() -> None:
    run_js(
        r"""
const draft={item_options:[{item:'A',material_code:'A-1',product_name:'A'},{item:'B',material_code:'B-1',product_name:'B'}],components:[{proposal_id:'p',item:'A',tax_code:'IVA',currency:'MXN',original_amount:'4',amount_rmb:'2'}]};
const matrix=w.feeEvidenceMaterialMatrix(draft);
assert.deepEqual(matrix.rows.map(x=>x.item),['A','B']);
assert.deepEqual(matrix.rows[0].cells.IVA.proposals,[0]);assert.deepEqual(matrix.rows[1].cells,{});
"""
    )


def test_legal_matrix_anomalies_initialize_required_evidence_and_fee_selections() -> None:
    run_js(
        DRAFT
        + r"""
draft.evidence.default_selected=false;
draft.fee_splits.forEach(row=>row.default_selected=false);
const selected=w.defaultFeeEvidenceReviewSelections(draft);
assert(selected.has('evidence:classification'));
assert(selected.has('fee:import_tax'));
assert(selected.has('fee:customs_clearance_fee'));
"""
    )


def test_manual_edit_clear_and_adopt_ai_preserve_dirty_state_and_sparse_payload() -> None:
    run_js(
        DRAFT
        + r"""
const review={matrixEdits:{}};
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-1','IGI','20');
assert.equal(review.matrixEdits['ITEM-1\u001fIGI'].value,'20');
w.ensureFeeEvidenceMatrixState(review,draft);
assert.equal(review.matrixEdits['ITEM-1\u001fIGI'].value,'20');
let payload=w.serializeFeeEvidenceMatrix(draft,review);
const edited=payload.cells.find(x=>x.item==='ITEM-1'&&x.column_key==='IGI');
assert.deepEqual(edited,{item:'ITEM-1',column_key:'IGI',original_amount:'20',source_proposal_ids:['component:1','component:2']});
assert.deepEqual(Object.keys(edited),['item','column_key','original_amount','source_proposal_ids']);
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-1','IGI','');
payload=w.serializeFeeEvidenceMatrix(draft,review);
assert(!payload.cells.some(x=>x.item==='ITEM-1'&&x.column_key==='IGI'));
w.adoptFeeEvidenceMatrixSuggestion(review,draft,'ITEM-1','IGI');
assert.equal(review.matrixEdits['ITEM-1\u001fIGI'].value,'15');
assert.deepEqual(review.matrixEdits['ITEM-1\u001fIGI'].sourceProposalIds,['component:1','component:2']);
assert.equal(w.feeEvidenceMatrixEffectiveCell(draft,review,0,'IGI').adoptedAI,true);
"""
    )


def test_blank_manual_cell_is_allowed_but_invalid_or_negative_amount_is_rejected() -> None:
    run_js(
        DRAFT
        + r"""
const review={matrixEdits:{}};
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-2','IVA','12.3400');
let payload=w.serializeFeeEvidenceMatrix(draft,review);
assert.deepEqual(payload.cells.find(x=>x.item==='ITEM-2'&&x.column_key==='IVA'),{item:'ITEM-2',column_key:'IVA',original_amount:'12.34',source_proposal_ids:[]});
draft.fee_splits.find(x=>x.logical_fee_key==='import_tax').currency='RMB';
let effective=w.feeEvidenceMatrixEffectiveCell(draft,review,1,'IVA');
assert.equal(effective.currency,'RMB');assert.equal(effective.amountRmb,'12.34');assert.equal(effective.missingFx,false);
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-2','IVA','-1');
assert.throws(()=>w.serializeFeeEvidenceMatrix(draft,review),/非负有限数/);
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-2','IVA','Infinity');
assert.throws(()=>w.serializeFeeEvidenceMatrix(draft,review),/非负有限数/);
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-2','IVA','12.345');
assert.throws(()=>w.serializeFeeEvidenceMatrix(draft,review),/最多保留两位小数/);
"""
    )


def test_totals_exclude_missing_fx_allow_positive_balance_and_block_overage() -> None:
    run_js(
        DRAFT
        + r"""
const review={matrixEdits:{},edits:{}};
let totals=w.feeEvidenceMatrixTotals(draft,review);
assert.equal(totals.import_tax.allocatedOriginal,18);
assert.equal(totals.import_tax.feeTotal,100);
assert.equal(totals.import_tax.remaining,82);
assert.equal(totals.import_tax.overage,false);
assert.equal(totals.import_tax.allocatedRmb,7.2);
assert.equal(totals.customs_clearance_fee.allocatedOriginal,30);
assert.equal(totals.customs_clearance_fee.allocatedRmb,0);
assert.equal(totals.customs_clearance_fee.missingFx,true);
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-1','IGI','101');
totals=w.feeEvidenceMatrixTotals(draft,review);
assert.equal(totals.import_tax.overage,true);
assert.throws(()=>w.validateFeeEvidenceMatrix(draft,review),/超过费用总额/);
"""
    )


def test_render_marks_manual_ai_action_missing_fx_and_fixed_footer_copy() -> None:
    run_js(
        DRAFT
        + r"""
const review={matrixEdits:{},edits:{}};
const html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('人工值'));
assert(html.includes('data-action="mf-fee-matrix-use-ai"'));
assert(html.includes('缺汇率'));
assert(html.includes('进口税费已分摊')&&html.includes('清关费已分摊'));
assert(html.includes('确认应用仅写入费用分项'));
"""
    )


def test_user_edited_cell_is_visibly_marked_as_manual_adjustment() -> None:
    run_js(
        DRAFT
        + r"""
const review={matrixEdits:{},edits:{}};
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-2','IVA','12');
const html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('ocw-mf-matrix-manual-badge">人工调整'));
"""
    )


def test_confirm_is_the_only_write_and_sends_the_sparse_matrix_payload() -> None:
    run_integrated_js(
        DRAFT
        + r"""
const calls=[];
w.detailState={batchName:'B',versionName:'V',editToken:'TOKEN',expectedModified:'M',tab:'overview'};
w.materialFeeState={batchName:'B',feeDrafts:{},pendingWrites:new Set(),materialCellWrites:new Map(),materialCellWriteTargets:{},materialCellSaveErrors:{},materialDrafts:{},packingGroupSelections:new Set(),feeEvidenceReview:{status:'READY',batchName:'B',runId:'RUN',draft,selections:new Set(['evidence:classification','fee:import_tax','fee:customs_clearance_fee']),edits:{},matrixEdits:{}},feeEvidenceReviewDialog:{$wrapper:{find:()=>({length:0})},hide:()=>{}}};
w.ensureMaterialFeeEditSession=async()=>true;
w.call=async(method,args)=>{calls.push({method,args});return {ok:true,message:'ok'}};
w.updateMaterialFeeExpectedModified=()=>{};
global.frappe={show_alert:()=>{}};
w.setFeeEvidenceMatrixValue(w.materialFeeState.feeEvidenceReview,draft,'ITEM-1','IGI','20');
assert.equal(calls.length,0);
await w.applyFeeEvidenceReview();
assert.equal(calls.length,1);
assert.equal(calls[0].method,'overseas_costing.api.fees.apply_fee_evidence_review');
const payload=JSON.parse(calls[0].args.component_matrix_json);
assert.deepEqual(payload.cells.find(x=>x.item==='ITEM-1'&&x.column_key==='IGI'),{item:'ITEM-1',column_key:'IGI',original_amount:'20',source_proposal_ids:['component:1','component:2']});
assert(!calls[0].method.toLowerCase().includes('calculate'));
assert(!calls[0].method.toLowerCase().includes('erp'));
"""
    )


def test_ready_poll_keeps_dirty_matrix_values() -> None:
    run_integrated_js(
        DRAFT
        + r"""
global.window={setTimeout:fn=>fn()};
const review={status:'RUNNING',runId:'RUN',progress_revision:1,selections:new Set(),edits:{},matrixEdits:{'ITEM-1\u001fIGI':{value:'21',dirty:true,sourceProposalIds:['component:1']}}};
const state={batchName:'B',feeEvidenceReview:review};
w.materialFeeState=state;
w.call=async()=>({ok:true,status:'READY',progress_revision:2,draft});
w.updateFeeEvidenceReviewProgress=()=>{};
await w.pollFeeEvidenceReview(state,'B','RUN');
assert.equal(state.feeEvidenceReview.matrixEdits['ITEM-1\u001fIGI'].value,'21');
assert.equal(state.feeEvidenceReview.edits,review.edits);
"""
    )
