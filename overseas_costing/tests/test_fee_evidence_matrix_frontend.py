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
    {proposal_id:'component:3',item:'ITEM-2',component_type:'CUSTOMS_SERVICE',fee_logical_key:'customs_clearance_fee',currency:'MXN',original_amount:'30',amount_rmb:null},
    {proposal_id:'component:ledger',item:'ITEM-1',component_type:'REFUND_REVERSAL',accounting_role:'SETTLEMENT',cost_effect:'LEDGER_ONLY',currency:'MXN',original_amount:'8',amount_rmb:'3.2',default_selected:true,warning:'只记录退款台账',source_refs:[{file_name:'refund.pdf',page:5,text_line:12}]}
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


def test_indexed_ledger_component_is_resolved_only_from_ledger_unmatched_reference() -> None:
    run_js(
        r"""
const draft={components:[],component_contract:{mode:'INDEXED_COLUMNS_V1'},component_store:{format:'INDEXED_COLUMNS_V1',count:2,columns:{
 proposal_id:{values:['ledger','matrix']},component_type:{values:['REFUND_REVERSAL','IMPORT_TAX']},accounting_role:{values:['SETTLEMENT','FINAL_BILL']},cost_effect:{values:['LEDGER_ONLY','COST']},default_selected:{values:[true,true]},currency:{constant:'MXN'},original_amount:{values:['8','2']},item:{constant:'ITEM-1'},tax_code:{values:['','IGI']},source_refs:{values:[[{file_name:'indexed-refund.pdf',page:6}],[]]}
}},material_matrix:{columns:w.feeEvidenceMatrixColumns(),saved_components:[],unmatched_lines:[{reason_code:'MATERIAL_MATRIX_LEDGER_ONLY',message:'只保留台账',proposal_index:0}],rows:[{item:'ITEM-1',material_code:'SKU',hs_code:'1',cells:{IGI:{proposals:[1],saved:[]}}}]}};
assert.deepEqual(w.feeEvidenceLedgerComponents(draft).map(x=>x.proposal_id),['ledger']);
const selected=w.defaultFeeEvidenceReviewSelections(draft);
assert(selected.has('ledger'));assert(!selected.has('matrix'));
const html=w.renderFeeEvidenceReviewDraft(draft,{selections:selected,edits:{},matrixEdits:{}});
assert(html.includes('indexed-refund.pdf')&&html.includes('第 6 页'));
assert(!html.includes('无法归属到具体物料的凭证明细'));
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


def test_legacy_ledger_component_with_tax_code_stays_outside_matrix() -> None:
    run_js(
        r"""
const draft={item_options:[{item:'A',material_code:'A-1'}],components:[
 {proposal_id:'ledger',item:'A',component_type:'REFUND_REVERSAL',accounting_role:'SETTLEMENT',cost_effect:'LEDGER_ONLY',tax_code:'IGI',currency:'MXN',original_amount:'4',default_selected:true}
]};
const matrix=w.feeEvidenceMaterialMatrix(draft);
assert.deepEqual(matrix.rows[0].cells,{});
assert.deepEqual(w.feeEvidenceLedgerComponents(draft).map(x=>x.proposal_id),['ledger']);
assert.deepEqual(w.serializeFeeEvidenceMatrix(draft,{matrixEdits:{}}),{cells:[]});
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
assert(selected.has('component:ledger'));
assert(!selected.has('component:1'));
"""
    )


def test_ledger_only_component_is_visible_outside_matrix_with_amount_source_and_warning() -> None:
    run_js(
        DRAFT
        + r"""
const ledger=w.feeEvidenceLedgerComponents(draft);
assert.deepEqual(ledger.map(x=>x.proposal_id),['component:ledger']);
const review={selections:w.defaultFeeEvidenceReviewSelections(draft),edits:{},matrixEdits:{}};
const html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('矩阵外台账分项'));
assert(html.includes('component:ledger'));
assert(html.includes('MXN 8'));
assert(html.includes('<strong>退款／冲回 · MXN 8</strong>'));
assert(html.includes('refund.pdf')&&html.includes('第 5 页')&&html.includes('文本第 12 行'));
assert(html.includes('只记录退款台账'));
assert.deepEqual(w.serializeFeeEvidenceMatrix(draft,review).cells.filter(x=>x.source_proposal_ids.includes('component:ledger')),[]);
review.selections.delete('component:ledger');
const cancelled=w.renderFeeEvidenceReviewDraft(draft,review);
assert(!cancelled.includes('data-proposal-id="component:ledger" checked'));
"""
    )


def test_default_ledger_selection_also_selects_its_evidence_when_matrix_is_empty() -> None:
    run_js(
        DRAFT
        + r"""
draft.evidence.default_selected=false;
draft.fee_splits.forEach(row=>row.default_selected=false);
draft.material_matrix.rows.forEach(row=>row.cells={});
const selected=w.defaultFeeEvidenceReviewSelections(draft);
assert(selected.has('component:ledger'));
assert(selected.has('evidence:classification'));
assert(!selected.has('component:1'));
"""
    )


def test_ledger_source_refs_keep_distinct_nested_image_regions() -> None:
    run_js(
        r"""
const component={source_refs:[
 {file_name:'voucher.png',image_region:{x:1,y:2}},
 {file_name:'voucher.png',image_region:{x:8,y:9}}
]};
const labels=w.feeEvidenceComponentSourceRefs(component).map(ref=>w.feeEvidenceSourceLabel(ref));
assert.equal(labels.length,2);
assert(labels[0].includes('"x":1')&&labels[1].includes('"x":8'));
"""
    )


def test_matrix_sources_include_referenced_legacy_proposals_and_saved_components() -> None:
    run_js(
        DRAFT
        + r"""
draft.components[0].source_refs=[{file_name:'matrix-proposal.pdf',page:2},{file_name:'shared.pdf',page:1}];
draft.components[1].source_evidence={file_name:'matrix-source-evidence.pdf',text_line:7};
draft.material_matrix.saved_components[0].source_refs=[{file_name:'matrix-saved.pdf',page:3},{page:1,file_name:'shared.pdf'}];
const refs=w.feeEvidenceMatrixSourceRefs(draft);
const labels=refs.map(ref=>w.feeEvidenceSourceLabel(ref));
assert(labels.some(x=>x.includes('matrix-proposal.pdf')));
assert(labels.some(x=>x.includes('matrix-source-evidence.pdf')));
assert(labels.some(x=>x.includes('matrix-saved.pdf')));
assert.equal(labels.filter(x=>x.includes('shared.pdf')).length,1);
const html=w.renderFeeEvidenceReviewDraft(draft,{selections:w.defaultFeeEvidenceReviewSelections(draft),edits:{},matrixEdits:{}});
assert(html.includes('matrix-proposal.pdf')&&html.includes('matrix-source-evidence.pdf')&&html.includes('matrix-saved.pdf'));
"""
    )


def test_matrix_sources_resolve_only_referenced_indexed_proposals() -> None:
    run_js(
        r"""
const draft={components:[],component_contract:{mode:'INDEXED_COLUMNS_V1'},component_store:{format:'INDEXED_COLUMNS_V1',count:3,columns:{
 proposal_id:{values:['used','unused','also-used']},item:{constant:'ITEM-1'},tax_code:{values:['IGI','IVA','IGI']},currency:{constant:'MXN'},original_amount:{constant:'1'},amount_rmb:{constant:'0.5'},source_refs:{values:[[{file_name:'used.pdf',page:1}],[{file_name:'must-not-scan.pdf',page:2}],[{file_name:'also-used.pdf',page:3}]]}
}},material_matrix:{saved_components:[],unmatched_lines:[],rows:[{item:'ITEM-1',cells:{IGI:{proposals:[0,2],saved:[]}}}]}};
const labels=w.feeEvidenceMatrixSourceRefs(draft).map(ref=>w.feeEvidenceSourceLabel(ref));
assert(labels.some(x=>x.includes('used.pdf'))&&labels.some(x=>x.includes('also-used.pdf')));
assert(!labels.some(x=>x.includes('must-not-scan.pdf')));
"""
    )


def test_ten_thousand_rows_are_paged_cached_and_keep_dirty_edits_across_pages() -> None:
    run_js(
        r"""
const rows=Array.from({length:10000},(_,index)=>({item:`ITEM-${index}`,material_code:`SKU-${index}`,product_name:`P-${index}`,hs_code:'9001',cells:{}}));
const draft={evidence:{proposal_id:'e',currency:'MXN',default_selected:true},fee_splits:[{proposal_id:'fee',logical_fee_key:'import_tax',currency:'MXN',amount:'10000',default_selected:true}],components:[],material_matrix:{rows,saved_components:[],unmatched_lines:[]}};
const review={selections:new Set(['e','fee']),edits:{},matrixEdits:{}};
let aggregateCalls=0;
const aggregate=w.feeEvidenceAggregateComponents.bind(w);
w.feeEvidenceAggregateComponents=(rows)=>{aggregateCalls+=1;return aggregate(rows)};
let html=w.renderFeeEvidenceReviewDraft(draft,review);
assert.equal((html.match(/data-mf-fee-matrix-hs=/g)||[]).length,100);
assert(html.includes('SKU-0')&&!html.includes('SKU-9999'));
assert(html.includes('共 10000 行')&&html.includes('data-action="mf-fee-matrix-next-page"'));
assert(html.length<1000000);
w.setFeeEvidenceMatrixPage(review,draft,999);
html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('SKU-9999')&&!html.includes('SKU-0</strong>'));
const beforeEdit=aggregateCalls;
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-9999','IGI','1');
w.renderFeeEvidenceMatrixFooter(draft,review);
assert(aggregateCalls-beforeEdit<20);
w.setFeeEvidenceMatrixPage(review,draft,0);
w.renderFeeEvidenceReviewDraft(draft,review);
w.setFeeEvidenceMatrixPage(review,draft,99);
html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('value="1"')&&html.includes('人工调整'));
"""
    )


def test_dense_ten_thousand_row_totals_apply_single_cell_delta() -> None:
    run_js(
        r"""
const rows=Array.from({length:10000},(_,index)=>({item:`ITEM-${index}`,material_code:`SKU-${index}`,cells:{IGI:{proposals:[],saved:[0]}}}));
const draft={evidence:{proposal_id:'e'},fee_splits:[{proposal_id:'fee',logical_fee_key:'import_tax',currency:'MXN',amount:'10001',default_selected:true}],components:[],material_matrix:{rows,saved_components:[{currency:'MXN',original_amount:'1',amount_rmb:'0.5'}]}};
const review={selections:new Set(['e','fee']),edits:{},matrixEdits:{}};
let effectiveCalls=0;const effective=w.feeEvidenceMatrixEffectiveCell.bind(w);
w.feeEvidenceMatrixEffectiveCell=(...args)=>{effectiveCalls+=1;return effective(...args)};
let totals=w.feeEvidenceMatrixTotals(draft,review);assert.equal(totals.import_tax.allocatedText,'10000');
effectiveCalls=0;
w.setFeeEvidenceMatrixValue(review,draft,'ITEM-5000','IGI','2');
totals=w.feeEvidenceMatrixTotals(draft,review);
assert.equal(totals.import_tax.allocatedText,'10001');assert(effectiveCalls<20);
"""
    )


def test_large_matrix_source_evidence_is_paged_and_every_reference_remains_accessible() -> None:
    run_js(
        r"""
const components=Array.from({length:10000},(_,index)=>({proposal_id:`p-${index}`,item:`I-${index}`,tax_code:'IGI',currency:'MXN',original_amount:'0',amount_rmb:'0',source_refs:[{file_name:`source-${index}.pdf`,page:index+1}]}));
const rows=components.map((_,index)=>({item:`I-${index}`,material_code:`S-${index}`,cells:{IGI:{proposals:[index],saved:[]}}}));
const draft={evidence:{proposal_id:'e'},fee_splits:[{proposal_id:'fee',logical_fee_key:'import_tax',currency:'MXN',amount:'0',default_selected:true}],components,material_matrix:{rows,saved_components:[]}};
const review={selections:new Set(['e','fee']),edits:{},matrixEdits:{}};
let html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('source-0.pdf')&&!html.includes('source-9999.pdf'));
assert(html.includes('来源第 1 / 100 页')&&html.length<1000000);
w.setFeeEvidenceSourcePage(review,draft,99);
html=w.renderFeeEvidenceReviewDraft(draft,review);
assert(html.includes('source-9999.pdf')&&!html.includes('source-0.pdf ·'));
"""
    )


def test_workspace_binds_matrix_pager_actions() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text()
    assert "[data-action='mf-fee-matrix-prev-page'], [data-action='mf-fee-matrix-next-page']" in source
    assert "setFeeEvidenceMatrixPage" in source


def test_workspace_invalidates_matrix_authority_totals_on_review_selection_or_edit() -> None:
    source = (PARTS / "78-material-fee-workspace.js").read_text()
    selection = source[source.index('dialog.$wrapper.on("change", "[data-mf-fee-review-select]"'):]
    selection = selection[: selection.index('dialog.$wrapper.on("input change", "[data-mf-fee-review-edit]"')]
    assert "invalidateFeeEvidenceMatrixTotals(review)" in selection
    assert "renderFeeEvidenceMatrixFooter" in selection
    edit = source[source.index('dialog.$wrapper.on("input change", "[data-mf-fee-review-edit]"'):]
    edit = edit[: edit.index('dialog.$wrapper.on("input", "[data-mf-fee-matrix-input]"')]
    assert "invalidateFeeEvidenceMatrixTotals(review)" in edit


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


def test_matrix_requires_one_selected_single_currency_fee_authority_per_nonempty_group() -> None:
    run_js(
        DRAFT
        + r"""
const review={selections:new Set(['evidence:classification','fee:customs_clearance_fee']),edits:{},matrixEdits:{}};
let totals=w.feeEvidenceFeeTotals(draft,review);
assert.equal(totals.import_tax.feeTotal,0);assert.equal(totals.import_tax.currency,'');
assert.equal(w.feeEvidenceMatrixEffectiveCell(draft,review,0,'IGI').currency,'');
assert(w.renderFeeEvidenceReviewDraft(draft,review).includes('待选择费用币种'));
assert.throws(()=>w.validateFeeEvidenceMatrix(draft,review),/请选择.*费用拆分/);
draft.fee_splits.push({proposal_id:'fee:import_tax:usd',logical_fee_key:'import_tax',currency:'USD',amount:'100',default_selected:false});
review.selections.add('fee:import_tax');review.selections.add('fee:import_tax:usd');
w.invalidateFeeEvidenceMatrixTotals(review);
assert.throws(()=>w.validateFeeEvidenceMatrix(draft,review),/币种/);
review.selections.delete('fee:import_tax:usd');
w.invalidateFeeEvidenceMatrixTotals(review);
assert.doesNotThrow(()=>w.validateFeeEvidenceMatrix(draft,review));
"""
    )


def test_effective_cell_uses_selected_fee_currency_and_drops_stale_rmb_ratio() -> None:
    run_js(
        DRAFT
        + r"""
const review={selections:new Set(['evidence:classification','fee:import_tax','fee:customs_clearance_fee']),edits:{'fee:import_tax':{currency:'USD'}},matrixEdits:{}};
let cell=w.feeEvidenceMatrixEffectiveCell(draft,review,0,'IGI');
assert.equal(cell.currency,'USD');assert.equal(cell.amountRmb,null);assert.equal(cell.missingFx,true);
review.edits['fee:import_tax'].currency='RMB';w.invalidateFeeEvidenceMatrixTotals(review);
cell=w.feeEvidenceMatrixEffectiveCell(draft,review,0,'IGI');
assert.equal(cell.currency,'RMB');assert.equal(cell.amountRmb,'18');assert.equal(cell.missingFx,false);
"""
    )


def test_fee_authority_currency_matches_server_supported_currency_semantics() -> None:
    run_js(
        DRAFT
        + r"""
const review={selections:new Set(['evidence:classification','fee:import_tax','fee:customs_clearance_fee']),edits:{'fee:import_tax':{currency:'EUR'}},matrixEdits:{}};
assert.throws(()=>w.validateFeeEvidenceMatrix(draft,review),/币种/);
review.edits['fee:import_tax'].currency='CNY';w.invalidateFeeEvidenceMatrixTotals(review);
const cell=w.feeEvidenceMatrixEffectiveCell(draft,review,0,'IGI');
assert.equal(cell.currency,'RMB');assert.equal(cell.amountRmb,'18');
assert.doesNotThrow(()=>w.validateFeeEvidenceMatrix(draft,review));
"""
    )


def test_large_amount_overage_uses_exact_minor_units_beyond_number_safe_integer() -> None:
    run_js(
        r"""
const draft={evidence:{proposal_id:'e',currency:'MXN',default_selected:true},fee_splits:[{proposal_id:'fee',logical_fee_key:'import_tax',currency:'MXN',amount:'9007199254740992.01',default_selected:true}],components:[],material_matrix:{saved_components:[],rows:[{item:'I',material_code:'S',cells:{}}]}};
const review={selections:new Set(['e','fee']),edits:{},matrixEdits:{}};
w.setFeeEvidenceMatrixValue(review,draft,'I','IGI','9007199254740992.01');
let totals=w.feeEvidenceMatrixTotals(draft,review);
assert.equal(totals.import_tax.overage,false);
assert.equal(totals.import_tax.remainingText,'0');
assert(w.renderFeeEvidenceMatrixFooter(draft,review).includes('费用总额 9007199254740992.01'));
assert(w.renderFeeEvidenceReviewDraft(draft,review).includes('<td class="ocw-mf-matrix-row-total"><strong>MXN 9007199254740992.01</strong>'));
w.setFeeEvidenceMatrixValue(review,draft,'I','IGI','9007199254740992.02');
totals=w.feeEvidenceMatrixTotals(draft,review);
assert.equal(totals.import_tax.overage,true);
assert.equal(totals.import_tax.remainingText,'-0.01');
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


def test_empty_matrix_still_submits_selected_ledger_and_honors_cancellation() -> None:
    run_integrated_js(
        DRAFT
        + r"""
const emptyDraft=structuredClone(draft);
emptyDraft.material_matrix.rows.forEach(row=>row.cells={});
const calls=[];
w.detailState={batchName:'B',versionName:'V',editToken:'TOKEN',expectedModified:'M',tab:'overview'};
w.ensureMaterialFeeEditSession=async()=>true;
w.call=async(method,args)=>{calls.push({method,args});return {ok:true,message:'ok'}};
w.updateMaterialFeeExpectedModified=()=>{};
global.frappe={show_alert:()=>{}};
const makeState=selections=>({batchName:'B',feeDrafts:{},pendingWrites:new Set(),materialCellWrites:new Map(),materialCellWriteTargets:{},materialCellSaveErrors:{},materialDrafts:{},packingGroupSelections:new Set(),feeEvidenceReview:{status:'READY',batchName:'B',runId:'RUN',draft:emptyDraft,selections,edits:{},matrixEdits:{}},feeEvidenceReviewDialog:{$wrapper:{find:()=>({length:0})},hide:()=>{}}});
let selections=w.defaultFeeEvidenceReviewSelections(emptyDraft);
assert(selections.has('component:ledger'));assert(!selections.has('component:1'));
w.materialFeeState=makeState(selections);
await w.applyFeeEvidenceReview();
assert.deepEqual(JSON.parse(calls[0].args.component_matrix_json),{cells:[]});
assert(JSON.parse(calls[0].args.selections_json).includes('component:ledger'));
selections=w.defaultFeeEvidenceReviewSelections(emptyDraft);selections.delete('component:ledger');
w.materialFeeState=makeState(selections);
await w.applyFeeEvidenceReview();
assert(!JSON.parse(calls[1].args.selections_json).includes('component:ledger'));
"""
    )


def test_apply_and_discard_are_single_flight_and_restore_action_buttons() -> None:
    run_integrated_js(
        DRAFT
        + r"""
const disabled=[];
const buttons={prop:(name,value)=>{if(name==='disabled')disabled.push(value);return buttons}};
const wrapper={find:(selector)=>selector.includes('data-current-source-review')?{length:0}:buttons};
const makeReview=()=>({status:'READY',batchName:'B',runId:'RUN',draft,selections:new Set(['evidence:classification','fee:import_tax','fee:customs_clearance_fee']),edits:{},matrixEdits:{}});
const makeState=review=>({batchName:'B',feeDrafts:{},pendingWrites:new Set(),materialCellWrites:new Map(),materialCellWriteTargets:{},materialCellSaveErrors:{},materialDrafts:{},packingGroupSelections:new Set(),feeEvidenceReview:review,feeEvidenceReviewDialog:{$wrapper:wrapper,hide:()=>{}}});
w.detailState={batchName:'B',versionName:'V',editToken:'TOKEN',expectedModified:'M',tab:'overview'};
w.ensureMaterialFeeEditSession=async()=>true;w.updateMaterialFeeExpectedModified=()=>{};global.frappe={show_alert:()=>{}};
let releaseApply;const applyGate=new Promise(resolve=>{releaseApply=resolve});let applyCalls=0;
w.call=async method=>{applyCalls+=1;await applyGate;return {ok:true,message:method}};
w.materialFeeState=makeState(makeReview());
const apply1=w.applyFeeEvidenceReview();const apply2=w.applyFeeEvidenceReview();
await Promise.resolve();await Promise.resolve();
assert.equal(applyCalls,1);assert.equal(disabled.at(-1),true);
releaseApply();await Promise.all([apply1,apply2]);assert.equal(disabled.at(-1),false);
let releaseDiscard;const discardGate=new Promise(resolve=>{releaseDiscard=resolve});let discardCalls=0;
w.call=async method=>{discardCalls+=1;await discardGate;return {ok:true,message:method}};
w.materialFeeState=makeState(makeReview());
const discard1=w.discardFeeEvidenceReview();const discard2=w.discardFeeEvidenceReview();
await Promise.resolve();assert.equal(discardCalls,1);assert.equal(disabled.at(-1),true);
releaseDiscard();await Promise.all([discard1,discard2]);assert.equal(disabled.at(-1),false);
"""
    )


def test_failed_review_action_restores_buttons_and_allows_retry() -> None:
    run_integrated_js(
        DRAFT
        + r"""
const disabled=[];const buttons={prop:(name,value)=>{if(name==='disabled')disabled.push(value);return buttons}};
const wrapper={find:(selector)=>selector.includes('data-current-source-review')?{length:0}:buttons};
const review={status:'READY',batchName:'B',runId:'RUN',draft,selections:new Set(['evidence:classification','fee:import_tax','fee:customs_clearance_fee']),edits:{},matrixEdits:{}};
w.detailState={batchName:'B',editToken:'T',expectedModified:'M',tab:'overview'};w.ensureMaterialFeeEditSession=async()=>true;
w.materialFeeState={batchName:'B',feeDrafts:{},pendingWrites:new Set(),materialCellWrites:new Map(),materialCellWriteTargets:{},materialCellSaveErrors:{},materialDrafts:{},packingGroupSelections:new Set(),feeEvidenceReview:review,feeEvidenceReviewDialog:{$wrapper:wrapper,hide:()=>{}}};
let calls=0;w.call=async()=>{calls+=1;throw new Error('network')};
await assert.rejects(()=>w.applyFeeEvidenceReview(),/network/);
assert.equal(disabled.at(-1),false);assert.equal(review.actionPromise,null);
await assert.rejects(()=>w.applyFeeEvidenceReview(),/network/);assert.equal(calls,2);
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
