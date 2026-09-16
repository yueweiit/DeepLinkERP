"""Unified AI-fill payment-source preflight frontend contracts."""
import json
import subprocess

from overseas_costing.tests.test_workbench_frontend_state import PARTS


def run_ui(body):
    sources = [PARTS / name for name in ("78-material-fee-workspace.js", "87-freight.js")]
    script = "const fs=require('fs');const assert=require('assert').strict;"
    script += "const source=" + "+".join(
        f"fs.readFileSync({json.dumps(str(path))},'utf8')" for path in sources
    ) + ";"
    script += "const Harness=Function('return class {'+source+'}')();"
    script += r'''
const w=new Harness();
w.escape=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
w.detailState={batchName:'B',versionName:'V',tab:'documents'};
const state=w.ensureMaterialFeeState();
w.renderMaterialFeeWorkspacePreservingPosition=()=>{};
w.updateMaterialAIProgressSurface=()=>{};
w.openMaterialAIProgressDialog=()=>{};
w.pollMaterialAIFill=async()=>{};
w.materialAINewRequestId=()=> 'REQ';
global.window={setTimeout:(fn)=>fn()};
global.crypto={randomUUID:()=> 'REQ'};
'''
    script += "(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_standalone_payment_source_button_and_workspace_are_removed():
    run_ui(r'''
const data={payment_claims:[],payment_candidates:[],payment_matching:{status:'completed'},packing:{message:'保留当前资料'},logistics:{}};
const html=w.renderFreightStrip(data);
assert(!html.includes('实际支付流程/装箱资料来源'));
assert(!html.includes('实际支付流程/装箱变更'));
assert(!source.includes('renderPaymentSourceWorkspace'));
assert(!source.includes('preview_payment_source_selection'));
''')


def test_ambiguous_payment_sources_are_selected_inside_ai_fill_and_submit_only_refs():
    run_ui(r'''
const exact={candidate_id:'C1',revision:'R1',title:'DHL 月结付款',approval_no:'PAY-1',match_strength:'STRONG',match_reason:'审批号精确匹配'};
const weak={candidate_id:'C2',revision:'R2',title:'运输费用支出',approval_no:'PAY-2',match_strength:'WEAK',match_reason:'项目与日期相似'};
const calls=[];
w.call=async(method,args)=>{
  calls.push({method,args});
  if(method.endsWith('start_source_ai_review') && !args.payment_candidate_refs_json) return {ok:true,status:'PAYMENT_SELECTION',payment_preflight:{status:'NEEDS_SELECTION',version:'V',selected_refs:[],candidates:[exact,weak]}};
  if(method.endsWith('start_source_ai_review')) return {ok:true,run_id:'RUN',status:'QUEUED',progress_percent:0,source_progress:[]};
  throw new Error(method);
};
await w.startMaterialAIFill();
assert.equal(state.aiFill.status,'PAYMENT_SELECTION');
const html=w.renderMaterialAIProgressDialogContent();
for(const text of ['选择本次需要解析的支付流程','DHL 月结付款','运输费用支出','审批号精确匹配','使用所选来源并继续','跳过支付申请'])assert(html.includes(text),text);
state.aiFill.paymentSelection=new Set(['C1','C2']);
await w.continueMaterialAIPaymentSelection(false);
const start=calls.find(row=>row.method.endsWith('start_source_ai_review') && row.args.payment_candidate_refs_json);
assert(start);
assert.deepEqual(JSON.parse(start.args.payment_candidate_refs_json),[
  {candidate_id:'C1',revision:'R1',version:'V'},
  {candidate_id:'C2',revision:'R2',version:'V'},
]);
const payload=JSON.stringify(start.args);
for(const forbidden of ['3414.19','42.05','parsed_summary','source_snapshot'])assert(!payload.includes(forbidden),forbidden);
''')


def test_unique_strong_payment_match_continues_without_extra_confirmation():
    run_ui(r'''
const calls=[];
w.call=async(method,args)=>{
  calls.push({method,args});
  if(method.endsWith('start_source_ai_review')) return {ok:true,run_id:'RUN',status:'QUEUED',progress_percent:0,source_progress:[]};
  throw new Error(method);
};
await w.startMaterialAIFill();
assert(calls.some(row=>row.method.endsWith('start_source_ai_review')));
assert(!calls.some(row=>row.method.includes('preview_payment_source_selection')));
const start=calls.find(row=>row.method.endsWith('start_source_ai_review'));
assert.equal(start.args.payment_candidate_refs_json,undefined);
assert.equal(calls.length,1);
''')


def test_payment_preflight_can_skip_payment_and_continue_lower_stages():
    run_ui(r'''
const calls=[];
w.call=async(method,args)=>{
  calls.push({method,args});
  if(method.endsWith('start_source_ai_review') && !args.payment_candidate_refs_json) return {ok:true,status:'PAYMENT_SELECTION',payment_preflight:{status:'NEEDS_SELECTION',version:'V',selected_refs:[],candidates:[{candidate_id:'C1',revision:'R1',title:'月结付款'}]}};
  if(method.endsWith('start_source_ai_review')) return {ok:true,run_id:'RUN',status:'QUEUED',progress_percent:0,source_progress:[]};
};
await w.startMaterialAIFill();
await w.continueMaterialAIPaymentSelection(true);
const start=calls.find(row=>row.args.payment_candidate_refs_json==='[]');
assert.equal(start.args.payment_candidate_refs_json,'[]');
''')
