"""Unified payment/packing workspace frontend contracts."""
from pathlib import Path

from overseas_costing.tests.test_freight_workspace_ui import HARNESS
from overseas_costing.tests.test_settlement_frontend import BATCH_CONTROLLER, PARTS, run_js


PAYMENT_DATA = r'''
const paymentCandidate={
 id:'payment-candidate',revision:'candidate-r',method:'deepseek',confidence:'0.91',reason:'运单号与付款说明一致',
 expense:{title:'TiffanyBU 清关费付款',approval_no:'PAY-2026-1',process_code:'TiffanyBU',amount:'1000',currency:'RMB',snapshot:'source-r',approved:true},
 approval_total:'1000',approval_currency:'RMB',active_claimed_amount:'200',remaining_amount:'800',claim_status:'current',source_revision:'source-r',
 lines:[{id:'line-tax',scope:'tax',logical_fee_key:'import_tax',label:'进口税费',amount:'300',currency:'RMB',revision:'line-r',evidence:{file_name:'tax.pdf'},available:false}],
 attachments:[{document_id:'doc-1',file_name:'tax.pdf',origin:'Comment',attachment_type:'Tax Certificate',status:'parsed',availability:'available',suggested_logical_fee_keys:['import_tax'],default_selected:true,selected:true,required:true}]
};
const paymentClaim={id:'pc-1',source_approval_no:'PAY-OLD',source_title:'费用支出',logical_fee_key:'customs_clearance_fee',amount:'80',currency:'RMB',amount_status:'ACTUAL',status:'active',active:true,stale:false,revision:'claim-r',available_actions:['amount','currency','status','reclassify','revoke']};
data.payment_candidates=[paymentCandidate];data.candidates=[paymentCandidate];data.payment_claims=[paymentClaim];data.payment_matching={status:'completed',model:'deepseek-chat',offset:0,limit:30,has_more:true,recommended:1,processed:30,total:80};data.matching={status:'completed',method:'identifier',recommended:1};data.transport_mode='SEA';
w.detailState={batchName:'B',versionName:'V',editToken:'TOKEN',expectedModified:'M1'};
w.ensureEditSession=async()=>true;
'''


def test_exact_entry_label_and_three_tabs_replace_legacy_words():
    run_js(HARNESS + PAYMENT_DATA + r'''
const strip=w.renderFreightStrip(data);const html=w.renderFreightContent(data,state);
assert(strip.includes('实际支付流程/装箱变更'));
for(const label of ['实际支付流程','装箱变更','操作记录'])assert(html.includes(label),label);
for(const old of ['查找实际运费／装箱变更','查看历史运费／装箱','>运费<','>装箱来源<'])assert(!strip.includes(old)&&!html.includes(old),old);
assert(w.renderFreightStrip({...data,historical:true}).includes('查看历史支付流程/装箱变更'));
const current=w.renderFreightStrip({...data,payment_claims:[...data.payment_claims,{amount:'999',currency:'RMB',status:'revoked',active:false}]});assert(!current.includes('999 RMB'));
''')


def test_open_is_cached_read_only_and_never_starts_rules_or_ai():
    run_js(BATCH_CONTROLLER + r'''
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,freight_mode:true,viewed_version:'V',matching:{status:'not_started'},payment_matching:{status:'not_started'},payment_candidates:[],payment_claims:[]}};
w.bindFreightInputs=()=>{};w.captureFreightDraft=()=>{};
await w.openBatchSettlementDialog('B','V');
assert.deepEqual(calls.map(row=>row.method),['get_batch_settlement']);
assert(!calls.some(row=>row.method==='start_payment_ai_matching'||row.method==='run_payment_rule_matching'||row.method==='start_batch_matching'));
w.stopSettlementDialog(active);
''')


def test_rule_and_ai_actions_are_explicit_separate_and_ai_hints_are_bounded():
    run_js(HARNESS + PAYMENT_DATA + r'''
state.detailContext=null;w.detailState={batchName:'B',versionName:'V',editToken:'TOKEN',expectedModified:'M1'};
global.setTimeout=()=>1;
w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
w.settlementApi=async(method,args)=>{calls.push({method,args});return method==='run_payment_rule_matching'?{ok:true,matching:{status:'completed'}}:{ok:true,payment_matching:{status:'queued',offset:0,limit:50}}};
await w.handleFreightAction(state,'payment-rule-match',button({}),noop);
assert.equal(calls[0].method,'run_payment_rule_matching');assert(!calls.some(row=>row.method==='start_payment_ai_matching'));
await w.handleFreightAction(state,'payment-ai-open',button({}),noop);
state.freightDraft={waybill:'WB-1',supplier:'SUP',project:'P',date:'2026-09-14',description:'清关费',ai_limit:'80'};
await w.handleFreightAction(state,'payment-ai-run',button({}),noop);
assert.equal(calls[1].method,'start_payment_ai_matching');assert.equal(calls[1].args.limit,50);assert.equal(calls[1].args.offset,0);
assert.deepEqual(JSON.parse(calls[1].args.hints),{waybill:'WB-1',supplier:'SUP',project:'P',date:'2026-09-14',description:'清关费'});
''')


def test_attachment_selection_can_be_mapped_to_confirmed_fee_items():
    run_js(HARNESS + PAYMENT_DATA + r'''
const html=w.renderPaymentAttachmentList(paymentCandidate.attachments,['customs_clearance_fee','import_tax'],data);
assert(html.includes('data-payment-attachment-keys="doc-1"'));
assert(html.includes('value="customs_clearance_fee"'));
assert(html.includes('value="import_tax" selected'));
assert(html.includes('附件对应费用项'));
''')


def test_payment_candidates_show_method_model_confidence_balance_version_and_safe_attachments():
    run_js(HARNESS + PAYMENT_DATA + r'''
const html=w.renderFreightContent(data,state);
for(const label of ['TiffanyBU 清关费付款','PAY-2026-1','1000 RMB','已认领 200','剩余 800','AI匹配（DeepSeek）','deepseek-chat','91%','运单号与付款说明一致','source-r','tax.pdf','评论附件'])assert(html.includes(label),label);
assert(!html.includes('/private/files/'));assert(!html.includes('file_url'));
''')


def test_payment_adoption_previews_then_confirms_with_server_token_and_edit_lease_only():
    run_js(HARNESS + PAYMENT_DATA + r'''
state.detailContext=null;w.detailState={batchName:'B',versionName:'V',editToken:'TOKEN',expectedModified:'M1'};w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
await w.handleFreightAction(state,'payment-review',button({'data-id':'payment-candidate'}),noop);
state.freightDraft={payment_rows:[{source_line_id:'line-tax',logical_fee_key:'import_tax',amount:'300',currency:'RMB',amount_status:'ACTUAL',replace_claim_ids:[]}],attachments:[{document_id:'doc-1',selected:true,logical_fee_keys:['import_tax']}],reason:'',negative_confirmed:false};
w.settlementApi=async(method,args)=>{calls.push({method,args});return method==='preview_payment_adoption'?{ok:true,preview:{preview_id:'PV',revision:'PVR',impacted_fees:[{logical_fee_key:'import_tax',amount:'300',currency:'RMB'}],attachments:[],warnings:[]}}:{ok:true,status:'applied',version:'V',batch_modified:'M2'}};
await w.handleFreightAction(state,'payment-preview',button({}),noop);
assert.equal(calls[0].method,'preview_payment_adoption');const selections=JSON.parse(calls[0].args.selections);assert.deepEqual(selections,state.freightDraft.payment_rows);
assert(!JSON.stringify(calls[0].args).includes('source-r'));assert(!JSON.stringify(calls[0].args).includes('source_snapshot'));
await w.handleFreightAction(state,'payment-confirm',button({}),noop);
assert.deepEqual(calls[1],{method:'confirm_payment_adoption',args:{batch_name:'B',preview_id:'PV',revision:'PVR',edit_token:'TOKEN',expected_modified:'M1'}});
''')


def test_first_write_acquires_edit_session_and_uses_the_fresh_lease_payload():
    run_js(HARNESS + PAYMENT_DATA + r'''
state.detailContext=null;w.detailState={batchName:'B',versionName:'V'};w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
let ensured=0;w.ensureEditSession=async()=>{ensured++;w.detailState.editToken='FRESH-TOKEN';w.detailState.expectedModified='FRESH-MODIFIED';return true};
state.paymentPreview={preview_id:'PV',revision:'PVR'};state.freightView={kind:'payment-preview'};
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,status:'applied',version:'V'}};
await w.handleFreightAction(state,'payment-confirm',button({}),noop);
assert.equal(ensured,1);assert.deepEqual(calls[0],{method:'confirm_payment_adoption',args:{batch_name:'B',preview_id:'PV',revision:'PVR',edit_token:'FRESH-TOKEN',expected_modified:'FRESH-MODIFIED'}});
''')


def test_payment_writes_acquire_edit_session_and_failed_acquire_keeps_draft():
    run_js(HARNESS + PAYMENT_DATA + r'''
state.detailContext=null;w.detailState={batchName:'B',versionName:'V'};w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};global.setTimeout=()=>1;
let ensured=0;w.ensureEditSession=async()=>{ensured++;w.detailState.editToken='T';w.detailState.expectedModified='M';return true};
w.settlementApi=async(method,args)=>{calls.push({method,args});if(method==='run_payment_rule_matching')return {ok:true,matching:{status:'completed'}};if(method==='start_payment_ai_matching')return {ok:true,payment_matching:{status:'completed'}};if(method==='preview_payment_adoption')return {ok:true,preview:{preview_id:'PV',revision:'R',attachments:[],warnings:[]}};return {ok:true,status:'applied'}};
await w.handleFreightAction(state,'payment-rule-match',button({}),noop);
state.freightDraft={ai_limit:10};await w.handleFreightAction(state,'payment-ai-run',button({}),noop);
state.freightView={kind:'payment-adopt',candidate_id:'payment-candidate'};state.freightDraft={candidate_id:'payment-candidate',payment_rows:[{source_line_id:'line-tax',logical_fee_key:'import_tax',amount:'300',currency:'RMB',amount_status:'ACTUAL',replace_claim_ids:[]}],attachments:[]};await w.handleFreightAction(state,'payment-preview',button({}),noop);
state.freightView={kind:'payment-amend',claim_id:'pc-1',expected_revision:'claim-r',action:'status'};state.freightDraft={amount_status:'ACTUAL',reason:'状态核对'};await w.handleFreightAction(state,'payment-amend-save',button({}),noop);
state.freightView={kind:'payment-decision',candidate_id:'payment-candidate',revision:'candidate-r',action:'reject'};state.freightDraft={reason:'不是本票'};await w.handleFreightAction(state,'payment-decision-save',button({}),noop);
assert.equal(ensured,5);
state.freightView={kind:'payment-amend',claim_id:'pc-1',expected_revision:'claim-r',action:'status'};state.freightDraft={amount_status:'ACTUAL',reason:'保留这段输入'};w.ensureEditSession=async()=>false;
await assert.rejects(()=>w.handleFreightAction(state,'payment-amend-save',button({}),noop),/编辑权/);assert.equal(state.freightDraft.reason,'保留这段输入');
''')


def test_replace_existing_claim_is_explicit_and_only_uses_public_claim_ids():
    run_js(HARNESS + PAYMENT_DATA + r'''
const current={...paymentClaim,id:'pc-tax',logical_fee_key:'import_tax',amount:'100'};data.payment_claims=[paymentClaim,current];
state.freightView={kind:'payment-adopt',candidate_id:'payment-candidate'};state.freightDraft={candidate_id:'payment-candidate',payment_rows:[{source_line_id:'line-tax',logical_fee_key:'import_tax',amount:'300',currency:'RMB',amount_status:'ACTUAL',replace_claim_ids:[]}],attachments:[],reason:''};
const html=w.renderPaymentAdoptionEditor(data,state);assert(html.includes('替换此认领'));assert(html.includes('data-payment-replace-claim="pc-tax"'));assert(!html.includes('data-payment-replace-claim="pc-1"'));
state.freightDraft.payment_rows[0].replace_claim_ids=['pc-tax'];assert.throws(()=>w.validatePaymentDraft(state),/替换.*原因/);
state.freightDraft.reason='改用本次实际支付';assert.deepEqual(w.paymentPublicRows(state.freightDraft)[0].replace_claim_ids,['pc-tax']);
''')


def test_readonly_payment_workspace_keeps_views_but_hides_every_write_action():
    run_js(HARNESS + PAYMENT_DATA + r'''
w.detailState={batchName:'B',readonly:true};const readonly={...data,confirm_status:'Confirmed'};const html=w.renderFreightContent(readonly,{...state,data:readonly});const strip=w.renderFreightStrip(readonly);
for(const action of ['payment-rule-match','payment-ai-open','payment-review','payment-reject','payment-reopen','payment-amend'])assert(!html.includes(`data-settlement-action="${action}"`),action);
assert(strip.includes('查看历史支付流程/装箱变更'));assert(html.includes('实际支付流程'));assert(html.includes('装箱变更'));assert(html.includes('操作记录'));
''')


def test_stale_attachment_mapping_follows_the_current_fee_classification():
    run_js(HARNESS + PAYMENT_DATA + r'''
state.detailContext=null;w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
state.freightView={kind:'payment-adopt',candidate_id:'payment-candidate'};
state.freightDraft={candidate_id:'payment-candidate',payment_rows:[{source_line_id:'line-tax',logical_fee_key:'import_tax',amount:'300',currency:'RMB',amount_status:'ACTUAL',replace_claim_ids:[]}],attachments:[{document_id:'doc-1',selected:true,logical_fee_keys:['customs_clearance_fee']}],reason:'',negative_confirmed:false};
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,preview:{preview_id:'PV',revision:'R',attachments:[],warnings:[]}}};
await w.handleFreightAction(state,'payment-preview',button({}),noop);
assert.deepEqual(JSON.parse(calls[0].args.attachment_selections)[0].logical_fee_keys,['import_tax']);
''')


def test_final_payment_preview_freezes_attachment_choices():
    run_js(HARNESS + PAYMENT_DATA + r'''
state.paymentPreview={preview_id:'PV',revision:'R',attachments:[{document_id:'doc-1',file_name:'tax.pdf',origin:'Comment',attachment_type:'Tax Certificate',availability:'available',status:'parsed',selected:true,logical_fee_keys:['import_tax']}],warnings:[]};
const html=w.renderPaymentPreview(state);assert(html.includes('data-payment-attachment="doc-1"'));assert(html.includes('disabled'));assert(html.includes('修改附件选择需返回候选重新预览'));
state.freightView={kind:'payment-preview'};state.freightDraft={candidate_id:'payment-candidate'};w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
await w.handleFreightAction(state,'freight-back',button({}),noop);assert.equal(state.paymentPreview,null);assert.equal(state.freightView.kind,'payment-adopt');
''')


def test_aggregate_split_balance_validation_and_failed_preview_preserves_input():
    run_js(HARNESS + PAYMENT_DATA + r'''
const aggregate={...paymentCandidate,lines:[],approval_total:'1000',active_claimed_amount:'200',remaining_amount:'800'};data.payment_candidates=[aggregate];data.candidates=[aggregate];
state.detailContext=null;w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
await w.handleFreightAction(state,'payment-review',button({'data-id':'payment-candidate'}),noop);
assert.equal(state.freightDraft.payment_rows[0].source_line_id,'approval_total');
state.freightDraft.payment_rows=[{source_line_id:'approval_total',logical_fee_key:'customs_clearance_fee',amount:'500',currency:'RMB',amount_status:'ACTUAL',replace_claim_ids:[]},{source_line_id:'approval_total',logical_fee_key:'import_tax',amount:'301',currency:'RMB',amount_status:'ACTUAL',replace_claim_ids:[]}];
await assert.rejects(()=>w.handleFreightAction(state,'payment-preview',button({}),noop),/剩余/);assert.equal(state.freightDraft.payment_rows.length,2);
state.freightDraft.payment_rows[1].amount='300';w.settlementApi=async()=>{throw Error('版本已过期')};
await assert.rejects(()=>w.handleFreightAction(state,'payment-preview',button({}),noop),/版本已过期/);assert.equal(state.freightDraft.payment_rows[0].amount,'500');
''')


def test_amend_reject_and_reopen_use_unified_apis_and_reason():
    run_js(HARNESS + PAYMENT_DATA + r'''
state.detailContext=null;w.detailState={batchName:'B',versionName:'V',editToken:'TOKEN',expectedModified:'M1'};w.captureFreightDraft=()=>{};w.renderFreightWorkspace=()=>{};
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,status:'applied'}};
await w.handleFreightAction(state,'payment-amend',button({'data-claim':'pc-1','data-payment-action':'reclassify'}),noop);state.freightDraft={reason:'分类核对',logical_fee_key:'import_tax'};
await w.handleFreightAction(state,'payment-amend-save',button({}),noop);
const amend=calls.find(row=>row.method==='amend_payment_claim');assert.deepEqual(JSON.parse(amend.args.edits),{logical_fee_key:'import_tax'});assert.equal(amend.args.edit_token,'TOKEN');
state.freightView={kind:'payment-amend',claim_id:'pc-1',action:'amount'};state.freightDraft={amount:'-10',reason:'冲抵费用'};assert(w.renderPaymentAmendEditor(data,state).includes('data-freight-field="negative_confirmed"'));
await assert.rejects(()=>w.handleFreightAction(state,'payment-amend-save',button({}),noop),/负数/);assert.equal(state.freightDraft.amount,'-10');
await w.handleFreightAction(state,'payment-reject',button({'data-id':'payment-candidate'}),noop);assert(w.renderPaymentEditor(data,state).includes('否决付款候选'));assert(!w.renderPaymentEditor(data,state).includes('预览并认领本票费用'));state.freightDraft.reason='不属于本票';await w.handleFreightAction(state,'payment-decision-save',button({}),noop);const rejected=calls.find(row=>row.method==='reject_payment_candidate');assert.equal(rejected.args.version_name,'V');assert.equal(rejected.args.edit_token,'TOKEN');assert.equal(rejected.args.expected_modified,'M1');
data.payment_rejected_candidates=[{...paymentCandidate,status:'rejected'}];await w.handleFreightAction(state,'payment-reopen',button({'data-id':'payment-candidate'}),noop);state.freightDraft.reason='人工重新核对';await w.handleFreightAction(state,'payment-decision-save',button({}),noop);const reopened=calls.find(row=>row.method==='reopen_payment_candidate');assert.equal(reopened.args.version_name,'V');assert.equal(reopened.args.edit_token,'TOKEN');assert.equal(reopened.args.expected_modified,'M1');
''')


def test_payment_workspace_has_responsive_layout_contract():
    css = (PARTS / "47-settlement.css").read_text(encoding="utf-8")
    assert ".ocw-payment-match-actions" in css
    assert ".ocw-payment-candidate-grid" in css
    assert "@media (max-width: 720px)" in css
    assert "grid-template-columns: 1fr" in css
