"""Simplified payment-source chooser frontend contracts."""
from overseas_costing.tests.test_freight_workspace_ui import HARNESS
from overseas_costing.tests.test_settlement_frontend import BATCH_CONTROLLER, PARTS, run_js


PAYMENT_SCOPE = r'''
const exact={candidate_id:'payment-candidate',revision:'candidate-r',workflow_template:'月结付款',title:'DHL 月结付款',approval_no:'PAY-2026-1',match_strength:'STRONG',match_reason:'审批号精确匹配',selected:true,parsed_summary:{approval_no:'202607211417000078258',waybill:'1841361513',freight:{amount:'3414.19',currency:'RMB'},packing:{material_code_hints:['MWV101144'],chargeable_weight_kg:'46',gross_weight_kg:'42.05',package_count:'1',dimensions_cm:['33','20','23'],volume_m3:'0.01518'},evidence:{file_name:'DHL(6.29-7.24)快递明细.xlsx',sheet:'DHL快递',row:14}}};
data.payment_claims=[];data.payment_candidates=[];data.payment_matching={status:'completed'};
data.payment_source_scope={policy:'payment-source-scope-1',version:'V',status:'AUTO_MATCHED',message:'已自动匹配唯一支付流程。',selected_refs:[{candidate_id:'payment-candidate',revision:'candidate-r',version:'V'}],candidates:[exact],material_rows:[{item_name:'I1',material_code:'MWV101144',product_name:'薇武士IP17 PRO',values:{gross_weight_kg:'42.05',chargeable_weight_kg:'46',package_count:'1',volume_m3:'0.01518'},fallback_fields:[]},{item_name:'I2',material_code:'MWV101145',product_name:'薇武士IP17 PRO MAX',values:{gross_weight_kg:'5'},fallback_fields:['chargeable_weight_kg','package_count','volume_m3']}]};
w.detailState={batchName:'B',versionName:'V'};
'''


def test_entry_is_single_simple_payment_source_workspace_without_legacy_editors():
    run_js(HARNESS + PAYMENT_SCOPE + r'''
const strip=w.renderFreightStrip(data);const html=w.renderFreightContent(data,state);
assert(strip.includes('实际支付流程/装箱资料来源'));
for(const label of ['自动匹配','DHL 月结付款','AI 解析摘要','物料字段结果','更换支付来源'])assert(html.includes(label),label);
for(const removed of ['实际支付流程</button>','装箱变更</button>','操作记录</button>','DeepSeek','本轮最多候选','费用分类','附件对应费用项','整体替换','确认认领费用'])assert(!html.includes(removed),removed);
''')


def test_unique_strong_match_shows_exact_row_and_only_target_material_overlay():
    run_js(HARNESS + PAYMENT_SCOPE + r'''
const html=w.renderFreightContent(data,state);
for(const label of ['PAY-2026-1','202607211417000078258','1841361513','3414.19 RMB','46 kg','42.05 kg','1 箱','33×20×23 cm','0.01518 m³','DHL(6.29-7.24)快递明细.xlsx','第 14 行'])assert(html.includes(label),label);
assert(html.includes('MWV101144'));assert(html.includes('MWV101145'));
assert(html.includes('向下补充'));
assert(!html.includes('3414.18994140625'));
''')


def test_ambiguous_candidates_allow_multi_select_and_submit_only_ids_revisions_and_version():
    run_js(HARNESS + PAYMENT_SCOPE + r'''
const weak={...exact,candidate_id:'weak-2',revision:'weak-r',approval_no:'PAY-2',match_strength:'WEAK',selected:false,parsed_summary:{}};
data.payment_source_scope={...data.payment_source_scope,status:'NEEDS_SELECTION',selected_refs:[],candidates:[exact,weak]};
state.data=data;state.freightDraft={payment_source_refs:[{candidate_id:'payment-candidate',revision:'candidate-r',version:'V'},{candidate_id:'weak-2',revision:'weak-r',version:'V'}]};
const html=w.renderFreightContent(data,state);
assert(html.includes('type="checkbox"'));assert(html.includes('data-payment-source-candidate="payment-candidate"'));assert(html.includes('data-payment-source-candidate="weak-2"'));
w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,payment_source_scope:{...data.payment_source_scope,status:'SELECTED',selected_refs:JSON.parse(args.selections_json)}}};
await w.handleFreightAction(state,'payment-source-apply',button({}),noop);
assert.equal(calls[0].method,'preview_payment_source_selection');
assert.deepEqual(JSON.parse(calls[0].args.selections_json),state.freightDraft.payment_source_refs);
const payload=JSON.stringify(calls[0].args);for(const forbidden of ['3414.19','42.05','DHL(6.29-7.24)','source_snapshot'])assert(!payload.includes(forbidden),forbidden);
assert.deepEqual(w.detailState.paymentSourceRefs,state.freightDraft.payment_source_refs);
assert.deepEqual(w.detailState.paymentSourceSelection,{batchName:'B',versionName:'V',refs:state.freightDraft.payment_source_refs});
''')


def test_open_initializes_missing_payment_candidates_once_without_ai_or_batch_matching():
    run_js(BATCH_CONTROLLER + r'''
let reads=0;
w.settlementApi=async(method,args)=>{
 calls.push({method,args});
 if(method==='run_payment_rule_matching')return {ok:true,matching:{status:'completed'}};
 reads++;
 return {ok:true,freight_mode:true,viewed_version:'V',matching:{status:reads===1?'not_started':'completed'},payment_source_scope:{status:reads===1?'UNAVAILABLE':'AUTO_MATCHED',version:'V',candidates:reads===1?[]:[{candidate_id:'payment-candidate',revision:'r',selected:true}],selected_refs:reads===1?[]:[{candidate_id:'payment-candidate',revision:'r',version:'V'}]}};
};
w.bindFreightInputs=()=>{};w.captureFreightDraft=()=>{};
await w.openBatchSettlementDialog('B','V');
assert.deepEqual(calls.map(row=>row.method),['get_batch_settlement','run_payment_rule_matching','get_batch_settlement']);
assert.deepEqual(calls[1].args,{batch_name:'B',version_name:'V'});
await active.handler('refresh');
assert.equal(calls.filter(row=>row.method==='run_payment_rule_matching').length,1);
assert(!calls.some(row=>['start_payment_ai_matching','start_batch_matching'].includes(row.method)));
w.stopSettlementDialog(active);
''')


def test_historical_or_final_payment_source_preview_never_initializes_candidates():
    run_js(BATCH_CONTROLLER + r'''
let mode='historical';
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,freight_mode:true,viewed_version:'V',historical:mode==='historical',confirm_status:mode==='final'?'Confirmed':'',matching:{status:'not_started'},payment_source_scope:{status:'UNAVAILABLE',version:'V',candidates:[],selected_refs:[]}}};
w.bindFreightInputs=()=>{};w.captureFreightDraft=()=>{};
await w.openBatchSettlementDialog('B','V');w.stopSettlementDialog(active);
mode='final';await w.openBatchSettlementDialog('B','V');w.stopSettlementDialog(active);
assert.equal(calls.filter(row=>row.method==='run_payment_rule_matching').length,0);
assert(!calls.some(row=>row.method==='start_payment_ai_matching'));
''')


def test_historical_version_uses_existing_readonly_tabs_instead_of_empty_chooser():
    run_js(HARNESS + PAYMENT_SCOPE + r'''
data.historical=true;data.payment_source_scope={status:'UNAVAILABLE',version:'V',candidates:[],selected_refs:[]};
data.payment_source_history=[{title:'DHL 月结付款',approval_no:'PAY-HISTORY',workflow_template:'月结付款',confirmed_by:'user',confirmed_at:'2026-09-16'}];
state.data=data;
const html=w.renderFreightContent(data,state);
assert(html.includes('data-freight-tab="freight"'));
assert(html.includes('历史版本仅供追溯'));
assert(html.includes('DHL 月结付款'));assert(html.includes('PAY-HISTORY'));
assert(!html.includes('AI 解析摘要'));
''')


def test_finalized_current_version_shows_persisted_payment_history_not_live_chooser():
    run_js(HARNESS + PAYMENT_SCOPE + r'''
data.confirm_status='Confirmed';
data.payment_source_history=[{title:'DHL 月结付款',approval_no:'PAY-HISTORY',workflow_template:'月结付款',confirmed_by:'user',confirmed_at:'2026-09-16'}];
state.data=data;
assert.equal(w.paymentReadOnly(data),true);
const html=w.renderFreightContent(data,state);
assert(html.includes('PAY-HISTORY'));assert(html.includes('已确认支付来源'));
assert(!html.includes('AI 解析摘要'));assert(!html.includes('更换支付来源'));
''')


def test_payment_source_workspace_has_responsive_layout_contract():
    css = (PARTS / "47-settlement.css").read_text(encoding="utf-8")
    assert ".ocw-payment-source-choice" in css
    assert ".ocw-payment-source-materials" in css
    assert "@media (max-width: 720px)" in css
