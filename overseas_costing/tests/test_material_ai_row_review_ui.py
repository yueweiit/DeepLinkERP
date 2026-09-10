"""Exercise row review selection, request fencing and inline fee edits in Node."""
import json
import subprocess
from overseas_costing.tests.test_workbench_frontend_state import PARTS


def run_ui(body):
    sources = [PARTS / name for name in ("78-material-fee-workspace.js", "87-freight.js")]
    script = "const fs=require('fs');const assert=require('assert').strict;"
    script += "const source=" + "+".join(f"fs.readFileSync({json.dumps(str(path))},'utf8')" for path in sources) + ";"
    script += "const Harness=Function('return class {'+source+'}')();"
    script += r"""
const w=new Harness();w.escape=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
w.detailState={batchName:'B',versionName:'V',tab:'documents',editToken:'token',expectedModified:'before'};
const state=w.ensureMaterialFeeState();w.renderMaterialAIReviewDialog=()=>{};w.renderMaterialFeeWorkspacePreservingPosition=()=>{};
w.loadMaterialFeeWorkspace=async()=>true;w.ensureEditSession=async()=>true;
global.frappe={show_alert:()=>{}};
const catalog={policy:'ai-row-review-1',fingerprint:'fp',rows:[
 {row_id:'source',origin:'source',values:{material_code:'NEW',gross_weight_kg:0},can_fill:true,can_replace:true,default_selected:true},
 {row_id:'current',origin:'current',values:{material_code:'OLD'},can_fill:false,can_replace:true,default_selected:false},
 {row_id:'ambiguous',origin:'source',label:'待核对',values:{material_code:'DUP'},can_fill:false,can_replace:true,blocked_reason:'匹配不唯一'}
],fees:[{proposal_id:'fee',payload:{expense_category:'运费',amount:0,currency:'RMB'},can_apply:true,default_selected:true},{proposal_id:'quote',payload:{expense_category:'旧报价',amount:999},can_apply:false,default_selected:true,blocked_reason:'已采用实际费用'}]};
const ready=()=>{state.aiFill=w.initializeMaterialAIDraft({status:'READY',run_id:'run',row_review:catalog});return state.aiFill};
const calls=[];
"""
    script += "(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_selections_modes_and_blocked_fees_are_independent():
    run_ui(r"""
const fill=ready();const review=fill.rowSelection;
assert.equal(fill.draftVisible,false,'Row selections must never overlay the saved material grid');
assert.equal(review.mode,'fill_missing');assert.deepEqual([...review.rows],['source']);assert.deepEqual([...review.fees],['fee']);
w.scheduleMaterialAIRowPreview=()=>{};
w.changeMaterialAIRowSelection('rows','ambiguous',true);assert(!review.rows.has('ambiguous'));
w.changeMaterialAIRowSelection('fees','quote',true);assert(!review.fees.has('quote'));
w.changeMaterialAIRowSelection('rows','all',false);assert.equal(review.rows.size,0);assert(review.fees.has('fee'));
w.changeMaterialAIRowSelection('mode','replace_all');w.changeMaterialAIRowSelection('rows','all',true);
assert.deepEqual([...review.rows],['source','current','ambiguous']);
w.changeMaterialAIRowSelection('mode','fill_missing');assert.deepEqual([...review.rows],['source']);
const html=w.renderMaterialAIReviewDialogContent();
for(const text of ['本次识别','当前已有','待核对','只补缺失','替换整表','已采用实际费用','全选','全不选'])assert(html.includes(text),text);
assert(!html.includes('data-mf-ai-proposal-select'));assert(!html.includes('data-mf-ai-edit'));
assert(html.includes('data-mf-ai-row-select="source"'));assert(html.includes('data-mf-ai-fee-select="quote" disabled'));
""")


def test_only_latest_server_preview_is_displayed_and_can_be_confirmed():
    run_ui(r"""
const fill=ready();const pending=[];w.call=(method,args)=>{calls.push({method,args});return new Promise(resolve=>pending.push(resolve))};
const first=w.previewMaterialAIRowSelection();
fill.rowSelection.rows.clear();const second=w.previewMaterialAIRowSelection();
assert.equal(w.canConfirmMaterialAIRowSelection(fill),false);
assert.equal(pending.length,1,'Serialize previews so a late older request cannot replace the server current preview');
pending[0]({ok:true,preview:{id:'old',revision:1,can_apply:true,rows:[{material_code:'STALE'}]}});await first;
assert.equal(fill.rowSelection.preview,null);assert.equal(w.canConfirmMaterialAIRowSelection(fill),false);
pending[1]({ok:true,preview:{id:'new',revision:2,can_apply:true,rows:[{material_code:'SERVER',gross_weight_kg:0}],added_count:3,removed_count:1,missing_fields:['volume_m3']}});await second;
assert.equal(fill.rowSelection.preview.id,'new');assert(w.canConfirmMaterialAIRowSelection(fill));
const html=w.renderMaterialAIReviewDialogContent();assert(html.includes('SERVER'));assert(!html.includes('STALE'));assert(html.includes('新增 3'));assert(html.includes('移除 1'));assert(html.includes('缺项 1'));
assert.equal(calls[1].args.row_ids_json,'[]');assert(!('rows' in calls[1].args));
w.scheduleMaterialAIRowPreview();assert.equal(w.canConfirmMaterialAIRowSelection(fill),false);clearTimeout(fill.rowSelection.timer);
""")


def test_preview_failure_and_version_change_keep_selection_without_stale_confirmation():
    run_ui(r"""
const fill=ready();w.call=async()=>({ok:false,message:'来源已变化'});await w.previewMaterialAIRowSelection();
assert.equal(fill.rowSelection.error,'来源已变化');assert.deepEqual([...fill.rowSelection.rows],['source']);assert(!w.canConfirmMaterialAIRowSelection(fill));
let release;w.call=()=>new Promise(r=>release=r);const request=w.previewMaterialAIRowSelection();w.detailState.versionName='V2';
release({ok:true,preview:{id:'wrong',revision:1,can_apply:true}});await request;assert(!fill.rowSelection.preview);
""")


def test_preview_queue_coalesces_intermediate_choices_and_replace_requires_one_row():
    run_ui(r"""
const fill=ready();const pending=[];w.call=(method,args)=>{calls.push({method,args});return new Promise(resolve=>pending.push(resolve))};
const first=w.previewMaterialAIRowSelection();fill.rowSelection.rows.clear();const middle=w.previewMaterialAIRowSelection();
fill.rowSelection.rows.add('source');fill.rowSelection.fees.clear();const latest=w.previewMaterialAIRowSelection();
assert.equal(calls.length,1);pending[0]({ok:true,preview:{id:'old',revision:1,can_apply:true}});await first;await middle;
assert.equal(calls.length,2);assert.equal(calls[1].args.fee_ids_json,'[]');assert.equal(calls[1].args.row_ids_json,'["source"]');
pending[1]({ok:true,preview:{id:'latest',revision:2,can_apply:true}});await latest;assert(w.canConfirmMaterialAIRowSelection(fill));
fill.rowSelection.mode='replace_all';fill.rowSelection.rows.clear();fill.rowSelection.previewKey=w.materialAIRowSelectionKey(fill);
assert.equal(w.canConfirmMaterialAIRowSelection(fill),false);
""")


def test_row_review_discard_error_stays_inside_dialog_and_preserves_choice():
    run_ui(r"""
const fill=ready();w.renderMaterialFeeWorkspace=()=>{};w.call=async()=>({ok:false,message:'暂时无法放弃'});
await w.discardMaterialAIFill();assert.equal(state.aiFill,fill);assert.equal(fill.discarding,false);
assert.equal(fill.rowSelection.error,'暂时无法放弃');assert.deepEqual([...fill.rowSelection.rows],['source']);
""")


def test_row_review_refresh_keeps_table_and_dialog_scroll_position():
    run_ui(r"""
ready();const body={top:420,scrollTop(value){if(value===undefined)return this.top;this.top=value;return this}};
const table={left:180,scrollLeft(value){if(value===undefined)return this.left;this.left=value;return this}};
global.$=node=>node;
const tables={each:callback=>callback(0,table)};
const wrapper={length:1,addClass:()=>{},find:selector=>selector==='.ocw-mf-ai-dialog-body'?body:tables};
state.aiProgressDialog={$wrapper:wrapper,fields_dict:{progress_html:{$wrapper:{html:()=>{body.top=0;table.left=0}}}}};
Harness.prototype.renderMaterialAIReviewDialog.call(w);assert.equal(body.top,420);assert.equal(table.left,180);
""")


def test_confirmation_submits_only_server_identifiers_and_preserves_failed_draft():
    run_ui(r"""
const fill=ready();w.call=async()=>({ok:true,preview:{id:'p',revision:7,can_apply:true,rows:[]}});await w.previewMaterialAIRowSelection();
w.call=async(method,args)=>{calls.push({method,args});return {ok:false,message:'并发修改，请重试'}};
await w.applyMaterialAIFill();assert.equal(fill.rowSelection.error,'并发修改，请重试');assert.equal(state.aiFill,fill);assert.deepEqual([...fill.rowSelection.rows],['source']);
assert.equal(calls[0].method,'overseas_costing.api.materials.confirm_source_ai_selection');
assert.deepEqual(calls[0].args,{batch_name:'B',run_id:'run',preview_id:'p',preview_revision:7,edit_token:'token',expected_modified:'before'});
w.call=async()=>({ok:true,status:'APPLIED',version_name:'V2',batch_modified:'after'});await w.applyMaterialAIFill();
assert.equal(state.aiFill,null);assert.equal(w.detailState.versionName,'V2');assert.equal(w.detailState.expectedModified,'after');
""")


INLINE = r"""
const fee={logical_fee_key:'freight',source_binding_id:'claim',source_label:'银行支付流程',amount:80,currency:'RMB'};
state.fees={fees:[fee]};
const data={ok:true,freight_mode:true,viewed_version:'V',freight:{revision:'r1',claims:[{id:'claim',line_id:'line',label:'运输费',amount:80,applied_amount:80,original_amount:100,currency:'RMB',approval_no:'PAY-OLD'}]},candidates:[{id:'new',revision:'r2',expense:{approved:true,approval_no:'PAY-NEW'},lines:[{id:'line2',amount:60,currency:'RMB',available:true,label:'运输费'}]}]};
w.call=async(method,args)=>{calls.push({method,args});return method.endsWith('get_batch_settlement')?data:{ok:true,version:'V2'}};
w.renderMaterialFeeFreightSurface=()=>{};
"""


def test_inline_amount_keeps_zero_and_failure_inputs_and_never_opens_modal():
    run_ui(INLINE + r"""
w.openBatchSettlementDialog=()=>{throw Error('Must stay inline')};
await w.openMaterialFeeFreightEditor('freight','amount');const editor=state.freightEditor;
assert.equal(editor.freightView.claim_id,'claim');assert.equal(calls.length,1);
const html=w.renderMaterialFeeFreightEditor('freight');assert(html.startsWith('<tr'));assert(html.includes('原始证据金额'));assert(html.includes('保存'));assert(html.includes('取消'));
editor.freightDraft={amount:'0',reason:'核对原单'};
w.call=async(method,args)=>{calls.push({method,args});return {ok:false,message:'版本冲突'}};
await w.saveMaterialFeeFreightEditor();assert.equal(editor.freightError,'版本冲突');assert.equal(editor.freightDraft.amount,'0');assert.equal(editor.freightDraft.reason,'核对原单');
assert.equal(calls[1].args.amount,'0');assert.equal(calls[1].args.expected_revision,'r1');assert(!('currency' in calls[1].args));
editor.freightDraft.amount='-5';await w.saveMaterialFeeFreightEditor();assert(editor.freightError.includes('负数'));assert.equal(calls.length,2);
""")


def test_inline_source_replacement_delta_and_success_refresh_keep_new_version():
    run_ui(INLINE + r"""
await w.openMaterialFeeFreightEditor('freight','replace');const editor=state.freightEditor;
editor.freightDraft={candidate_id:'new',line_ids:['line2'],reason:'本票新账单'};
assert(w.renderMaterialFeeFreightEditor('freight').includes('-20 RMB'));assert.equal(calls.length,1);
w.loadMaterialFeeWorkspace=async()=>{throw Error('模拟刷新失败')};
await w.saveMaterialFeeFreightEditor();assert.equal(w.detailState.versionName,'V2');assert(editor.saved);assert.equal(calls[1].args.action,'replace');assert.equal(calls[1].args.line_ids,'["line2"]');
assert(editor.freightError.includes('已保存'));await w.saveMaterialFeeFreightEditor();assert.equal(calls.length,2);
""")


def test_inline_pending_read_is_fenced_and_cancel_does_not_write():
    run_ui(INLINE + r"""
let release;w.call=()=>new Promise(r=>release=r);
const request=w.openMaterialFeeFreightEditor('freight','amount');const editor=state.freightEditor;
state.freightEditor=null;release(data);await request;assert.equal(state.freightEditor,null);assert(!editor.freightView);
w.call=async()=>({...data,historical:true});await w.openMaterialFeeFreightEditor('freight','amount');
assert(state.freightEditor.freightError.includes('历史版本'));assert(!state.freightEditor.freightView);
""")


def test_inline_source_row_uses_payment_label_and_expands_below_its_own_row():
    run_ui(INLINE + r"""
w.formatMoney=v=>String(v);w.materialFeeSavedCostPreview=()=>null;
fee.original_amount=100;fee.applied_amount=80;fee.amount_status='ACTUAL';
await w.openMaterialFeeFreightEditor('freight','replace');
const html=w.renderMaterialFeeRow(fee);
for(const text of ['银行支付流程','原始证据金额：RMB 100','当前采用金额','改金额','换来源','撤销采用'])assert(html.includes(text),text);
assert(!html.includes('物流采购支出'));assert(html.indexOf('data-mf-freight-editor')>html.indexOf('</tr>'));
state.freightEditor.freightDraft.candidate_id='new';
assert(!w.renderMaterialFeeFreightEditor('freight').includes('data-settlement-action="freight-evidence"'),'Inline candidate evidence must not use an unbound modal action');
""")
