"""Freight workspace behavior with synthetic, non-production source records."""
from overseas_costing.tests.test_settlement_frontend import run_js, BATCH_CONTROLLER
from overseas_costing.tests.test_workbench_frontend_state import _fee_workspace_result


HARNESS = r'''
const claim={id:'claim',line_id:'old-line',amount:'80',original_amount:'100',applied_amount:'80',currency:'RMB',approval_no:'PAY-OLD',label:'运输费',waybill:'WB-TEST',manual_corrected:true,evidence:{file_name:'old.xlsx'}};
const candidate={id:'candidate',revision:'source-r',expense:{approval_no:'PAY-NEW',approved:true,amount:'900',currency:'RMB'},lines:[{id:'new-line',amount:'60',currency:'RMB',available:true,label:'运输费',waybill:'WB-TEST',evidence:{file_name:'new.xlsx'}},{id:'credit',amount:'-5',currency:'RMB',available:true,label:'折扣'}]};
const data={ok:true,freight_mode:true,viewed_version:'V',logistics:{approval_no:'LOG-TEST'},freight:{revision:4,claims:[claim]},packing:{message:'当前装箱资料'},candidates:[candidate],audit:[{action:'freight_amount_corrected',reason:'核对原单',actor:'测试员'}]};
const state={open:true,busy:false,request:0,batchName:'B',versionName:'V',data,freightTab:'freight',dialog:{$wrapper:{find:()=>({prop:()=>{}})}}};
w.batchSettlementState=state;w.detailState={};w.settlementBody=(s,html)=>s.html=html;w.settlementActions=(s,html)=>s.actions=html;w.settlementNotice=(s,message)=>s.notice=message;
w.settlementDialog=()=>{throw Error('Nested dialog forbidden')};w.bindFreightInputs=()=>{};w.captureFreightDraft=()=>{};
const calls=[];w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,status:'applied',version:'V2'}};
w.refreshSettlementBatch=async()=>{calls.push({method:'refresh'})};
const button=attrs=>({attr:key=>attrs[key]});const noop=async()=>{};
'''


def test_claim_table_has_separate_columns_and_internal_tabs():
    run_js(HARNESS + r'''
const html=w.renderFreightContent(data,state);
for(const label of ['运费','装箱来源','操作记录','原始金额','当前采用金额','费用名称','运单号','改金额','换来源','撤销采用'])assert(html.includes(label),label);
assert(html.includes('data-freight-tab="packing"'));assert(html.includes('人工更正'));assert(html.includes('100 RMB'));assert(html.includes('80 RMB'));
assert(!html.includes('80 RMB · PAY-OLD'));
''')


def test_amend_amount_keeps_currency_and_revision_and_requires_negative_confirmation():
    run_js(HARNESS + r'''
await w.handleFreightAction(state,'freight-amount',button({'data-claim':'claim'}),noop);
assert.equal(state.freightView.kind,'amount');assert.equal(calls.length,0);
state.freightDraft={amount:'0',reason:'按原单更正',negative_confirmed:false};
await w.handleFreightAction(state,'freight-save',button({}),noop);
assert.equal(calls[0].method,'amend_freight_claim');assert.equal(calls[0].args.amount,'0');assert.equal(calls[0].args.expected_revision,4);assert.equal(calls[0].args.claim_id,'claim');assert(!('currency' in calls[0].args));
await w.handleFreightAction(state,'freight-amount',button({'data-claim':'claim'}),noop);state.freightDraft={amount:'-5',reason:'冲抵'};
await assert.rejects(()=>w.handleFreightAction(state,'freight-save',button({}),noop),/负数/);
assert.equal(calls.filter(r=>r.method==='amend_freight_claim').length,1);
''')


def test_revoke_submits_no_replacement_and_errors_preserve_the_draft():
    run_js(HARNESS + r'''
await w.handleFreightAction(state,'freight-revoke',button({'data-claim':'claim'}),noop);
state.freightDraft={reason:'重复计入'};
w.settlementApi=async(method,args)=>{calls.push({method,args});throw Error('版本已变化')};
await assert.rejects(()=>w.handleFreightAction(state,'freight-save',button({}),noop),/版本已变化/);
assert.equal(state.freightDraft.reason,'重复计入');assert.equal(state.freightView.kind,'revoke');assert.equal(state.freightWriting,false);
assert.equal(calls[0].args.action,'revoke');assert(!('line_ids' in calls[0].args));assert(!('candidate_id' in calls[0].args));
''')


def test_replacement_previews_delta_and_does_not_write_on_selection():
    run_js(HARNESS + r'''
await w.handleFreightAction(state,'freight-replace',button({'data-claim':'claim'}),noop);
state.freightDraft={candidate_id:'candidate',line_ids:['new-line'],reason:'换用本票账单'};
const html=w.renderFreightContent(data,state);assert(html.includes('更正前'));assert(html.includes('更正后'));assert(html.includes('-20 RMB'));assert.equal(calls.length,0);
await w.handleFreightAction(state,'freight-save',button({}),noop);
assert.equal(calls[0].args.action,'replace');assert.equal(calls[0].args.candidate_revision,'source-r');assert.deepEqual(JSON.parse(calls[0].args.line_ids),['new-line']);
''')


def test_packing_source_preview_is_readonly_then_explicit_whole_replacement():
    run_js(HARNESS + r'''
const source={id:'catalog',revision:'catalog-r',source_kind:'approval_attachment',source_label:'packing.xlsx',approval_no:'PAY-NEW',can_adopt:true,row_count:1,status:'approved'};
const preview={id:'preview',revision:'preview-r',selection:{can_adopt:true,text:'原始来源 <source>',descriptor:source},goods:[{line_key:'row',material_code:'SKU-TEST',product_name:'测试物料',quantity:0,unit:'件',physical:{gross_weight_kg:0}}],complete:false,new_count:1,removed_count:2,missing_fields:['volume_m3']};
w.settlementApi=async(method,args)=>{calls.push({method,args});return method==='list_shipment_packing_sources'?{ok:true,sources:[source]}:method==='preview_shipment_packing_source'?{ok:true,preview}:{ok:true,status:'applied'}};
await w.handleFreightAction(state,'freight-tab',button({'data-freight-tab':'packing'}),noop);
assert.equal(state.freightTab,'packing');for(const label of ['正文','附件','评论附件','评论'])assert(state.html.includes(label));
await w.handleFreightAction(state,'packing-source-preview',button({'data-id':'catalog'}),noop);
assert.equal(calls.length,2);assert(state.html.includes('待补'));assert(state.html.includes('新增 1'));assert(state.html.includes('移除 2'));assert(state.html.includes('原始来源 &lt;source&gt;'));
assert(!state.html.includes('data-packing-target'));assert(!state.html.includes('data-packing-line'));assert(!state.html.includes('type="checkbox"'));assert(state.actions.includes('采用此来源并替换本票装箱资料'));
await w.handleFreightAction(state,'packing-source-confirm',button({}),noop);
assert.equal(calls[2].method,'confirm_shipment_packing_source');assert.deepEqual(calls[2].args,{batch_name:'B',version_name:'V',preview_id:'preview',revision:'preview-r',replace_all:1});
''')


def test_unusable_preview_has_no_adoption_and_stale_preview_response_is_discarded():
    run_js(HARNESS + r'''
state.freightTab='packing';state.packingPreview={id:'empty',revision:'r',selection:{can_adopt:false},goods:[]};
w.renderFreightWorkspace(state);assert(!state.actions.includes('packing-source-confirm'));
state.packingSources=[{id:'catalog',revision:'r'}];let resolve;w.settlementApi=()=>new Promise(r=>resolve=r);
const pending=w.handleFreightAction(state,'packing-source-preview',button({'data-id':'catalog'}),noop);
state.versionName='V2';resolve({ok:true,preview:{id:'late',revision:'r',selection:{can_adopt:true},goods:[{material_code:'X'}]}});await pending;
assert.notEqual(state.packingPreview?.id,'late');
''')


def test_history_can_view_tabs_and_evidence_but_cannot_amend():
    run_js(HARNESS + r'''
state.data={...data,historical:true};
let html=w.renderFreightContent(state.data,state);assert(!html.includes('data-settlement-action="freight-amount"'));
await w.handleFreightAction(state,'freight-tab',button({'data-freight-tab':'audit'}),noop);assert.equal(state.freightTab,'audit');assert(!state.html.includes('freight_amount_corrected'));
w.settlementApi=async()=>({ok:true,evidence:{label:'运输费',amount:'80',currency:'RMB',source:{approval_no:'PAY-OLD'},evidence:{file_name:'old.xlsx'}}});
await w.handleFreightAction(state,'freight-evidence',button({'data-line':'old-line'}),noop);assert(state.html.includes('old.xlsx'));
await assert.rejects(()=>w.handleFreightAction(state,'freight-amount',button({'data-claim':'claim'}),noop),/历史版本/);
''')


def test_duplicate_submission_is_blocked_until_refresh_finishes():
    run_js(HARNESS + r'''
await w.handleFreightAction(state,'freight-amount',button({'data-claim':'claim'}),noop);state.freightDraft={amount:'20',reason:'更正'};
let resolve;w.settlementApi=async(method,args)=>{calls.push({method,args});return new Promise(r=>resolve=r)};
const pending=w.handleFreightAction(state,'freight-save',button({}),noop);
await w.handleFreightAction(state,'freight-save',button({}),noop);assert.equal(calls.length,1);assert(state.freightWriting);
resolve({ok:true,status:'queued'});await pending;assert.equal(state.freightWriting,false);
''')


def test_main_dialog_routes_historical_read_actions_inside_the_existing_modal():
    run_js(BATCH_CONTROLLER + r'''
w.settlementApi=async()=>({ok:true,freight_mode:true,historical:true,viewed_version:'V',freight:{claims:[]}});
w.bindFreightInputs=()=>{};w.captureFreightDraft=()=>{};await w.openBatchSettlementDialog('B','V');
await active.handler('freight-tab',{attr:key=>key==='data-freight-tab'?'audit':null});assert.equal(active.freightTab,'audit');
w.stopSettlementDialog(active);
''')


def test_edit_keeps_the_reviewed_revision_when_matching_refreshes_in_background():
    run_js(HARNESS + r'''
await w.handleFreightAction(state,'freight-amount',button({'data-claim':'claim'}),noop);
state.data={...data,freight:{...data.freight,revision:5}};state.freightDraft={amount:'30',reason:'依据已核对原单'};
await w.handleFreightAction(state,'freight-save',button({}),noop);
assert.equal(calls[0].args.expected_revision,4);
''')


def test_real_audit_actions_and_direct_source_descriptor_have_readable_labels():
    run_js(HARNESS + r'''
const html=w.renderFreightAudit({audit:['freight_amount','freight_replace','freight_revoke','freight_lines_adopted','packing_source_replaced'].map(action=>({action}))});
for(const label of ['更正费用金额','更换费用来源','撤销费用采用','采用运费','替换装箱来源'])assert(html.includes(label),label);
const evidence=w.renderFreightScopedEvidence({approval_no:'PAY-DIRECT',source_label:'packing-test.xlsx',evidence:{file_name:'packing-test.xlsx',sheet:'清单'},text:'<scoped original>'});
assert(evidence.includes('PAY-DIRECT'));assert(evidence.includes('packing-test.xlsx'));assert(evidence.includes('&lt;scoped original&gt;'));
''')


def test_inline_search_and_reject_never_open_a_second_modal():
    run_js(HARNESS + r'''
await w.handleFreightAction(state,'search',button({}),noop);state.freightDraft={query:'SYNTHETIC',reason:'同一测试运单'};
w.settlementApi=async(method,args)=>{calls.push({method,args});return method==='find_expenses'?{ok:true,items:[{id:'source',approval_no:'PAY-SEARCH'}]}:method==='prepare_manual_candidate'?{ok:true,freight_mode:true,candidate}:{ok:true,status:'applied'}};
await w.handleFreightAction(state,'freight-search-run',button({}),noop);assert(state.html.includes('PAY-SEARCH'));
await w.handleFreightAction(state,'freight-search-choose',button({'data-id':'source'}),noop);assert.equal(state.freightView.kind,'adopt');assert.deepEqual(state.freightDraft.line_ids,[]);
assert(!calls.some(row=>row.method==='confirm_freight_lines'));
await w.handleFreightAction(state,'freight-reject',button({'data-id':'candidate'}),noop);state.freightDraft.reason='运单不对应';
await w.handleFreightAction(state,'freight-save',button({}),noop);assert.equal(calls[2].method,'reject_freight_candidate');
''')


def test_corrected_amount_strip_is_current_adoption_and_null_packaging_stays_pending():
    run_js(HARNESS + r'''
const strip=w.renderFreightStrip(data);assert(strip.includes('当前采用运费'));assert(!strip.includes('已审批运费'));
state.freightTab='packing';state.packingSources=[];state.packingPreview={id:'preview',revision:'r',selection:{can_adopt:true},goods:[{material_code:'SKU-TEST',quantity:1,unit:'件',physical:null,packaging:null}]};
const html=w.renderFreightContent(data,state);assert(html.includes('待补'));assert(!html.includes('null'));
''')


def test_original_packing_entry_can_open_packing_tab_and_load_sources_directly():
    run_js(BATCH_CONTROLLER + r'''
w.bindFreightInputs=()=>{};w.captureFreightDraft=()=>{};
w.settlementApi=async(method,args)=>{calls.push({method,args});return method==='get_batch_settlement'?{ok:true,freight_mode:true,viewed_version:'V',freight:{claims:[]}}:{ok:true,sources:[]}};
await w.openBatchSettlementDialog('B','V','packing');assert.equal(active.freightTab,'packing');assert(calls.some(row=>row.method==='list_shipment_packing_sources'));assert(active.html.includes('选择整票装箱来源'));w.stopSettlementDialog(active);
''')


def test_saved_new_version_survives_detail_refresh_failure_and_retries_only_the_read():
    run_js(BATCH_CONTROLLER + r'''
w.bindFreightInputs=()=>{};w.captureFreightDraft=()=>{};
// Exercise the real refresh method and real afterWrite closure. Only the detail
// request fails, after the business write has already created V2.
w.refreshSettlementBatch=Workbench.prototype.refreshSettlementBatch;
const detailRequests=[];
w.openBatchDetail=async(batchName,tab,options)=>{detailRequests.push({batchName,tab,options});throw Error('模拟详情读取失败')};
let saved=false;
const claim={id:'claim',line_id:'line',amount:'100',currency:'RMB',approval_no:'PAY-TEST'};
w.settlementApi=async(method,args)=>{
 calls.push({method,args});
 if(method==='amend_freight_claim'){saved=true;return {ok:true,status:'applied',version:'V2'}}
 return {ok:true,freight_mode:true,viewed_version:args.version_name,historical:saved&&args.version_name!=='V2',freight:{revision:'revision',claims:[{...claim,amount:saved?'80':'100'}]}};
};
await w.openBatchSettlementDialog('B','V');
await active.handler('freight-amount',{attr:()=> 'claim'});
active.freightDraft={amount:'80',reason:'按测试原单更正'};
await active.handler('freight-save',{attr:()=>null});
assert.equal(w.detailState.versionName,'V2');assert.equal(active.versionName,'V2');
assert.equal(active.data.viewed_version,'V2');assert.equal(active.data.historical,false);
assert.equal(active.freightView,null);assert.equal(active.freightWriting,false);
assert(active.html.includes('已保存，新版本资料读取失败'));assert(active.html.includes('模拟详情读取失败'));
assert.deepEqual(detailRequests,[{batchName:'B',tab:'documents',options:{updateUrl:false,propagateError:true}}]);
assert.equal(calls.filter(row=>row.method==='amend_freight_claim').length,1);
await active.handler('refresh');
assert.equal(calls.at(-1).args.version_name,'V2');assert.equal(active.data.historical,false);
assert.equal(calls.filter(row=>row.method==='amend_freight_claim').length,1);
w.stopSettlementDialog(active);
''')


def test_audit_shows_before_after_amounts_sources_reason_and_packing_version_change():
    run_js(HARNESS + r'''
const before={amount:'100',currency:'RMB',approval_no:'PAY-OLD'};
const after={amount:'80',currency:'RMB',approval_no:'PAY-NEW'};
const html=w.renderFreightAudit({audit:[
 {action:'freight_amount',actor:'测试员',before:[before],after:[{...before,applied_amount:0}],reason:'依据 <original>'},
 {action:'freight_replace',before:[before],after:[after],reason:'本票新账单'},
 {action:'freight_revoke',before:[after],after:[],reason:'重复费用'},
 {action:'packing_source_replaced',source:'packing-test.xlsx',old_version:'V1',version:'V2'}
]});
const rows=html.split('<tbody>')[1].split('</tr>');
assert(rows[0].includes('100 RMB'));assert(rows[0].includes('0 RMB'));assert(rows[0].includes('PAY-OLD'));assert(rows[0].includes('依据 &lt;original&gt;'));assert(!rows[0].includes('<original>'));
assert(rows[1].includes('100 RMB'));assert(rows[1].includes('80 RMB'));assert(rows[1].includes('PAY-OLD'));assert(rows[1].includes('PAY-NEW'));assert(rows[1].includes('本票新账单'));
assert(rows[2].includes('80 RMB'));assert(rows[2].includes('无采用费用'));assert(rows[2].includes('重复费用'));
assert(rows[3].includes('packing-test.xlsx'));assert(rows[3].includes('V1 → V2'));assert(rows[3].includes('替换装箱来源'));
''')


PACKING_ENTRY = r'''
const workspace=new Harness();
workspace.detailState={batchName:'B1',versionName:'V1',tab:'documents'};
const state=workspace.ensureMaterialFeeState();
const handlers={};const opened=[];const errors=[];const requests=[];
workspace.$root={on:(event,selector,handler)=>{handlers[event+selector]=handler}};
workspace.bindMaterialFeeWorkspaceEvents();
workspace.openBatchSettlementDialog=async(...args)=>opened.push({kind:'freight',args});
workspace.openWikiMaterialImportDialog=async()=>opened.push({kind:'legacy'});
workspace.showError=error=>errors.push(error.message);
const openPacking=()=>handlers["click[data-action='mf-import-wiki']"]();
'''


def test_unknown_freight_mode_waits_for_server_before_opening_the_packing_entry():
    result = _fee_workspace_result(PACKING_ENTRY + r'''
let release;
workspace.settlementApi=(method,args)=>{requests.push({method,args});return new Promise(resolve=>{release=resolve})};
const pending=openPacking();
const openedBeforeResponse=[...opened];
release({ok:true,freight_mode:true,viewed_version:'V1'});await pending;
console.log(JSON.stringify({openedBeforeResponse,opened,errors,requests,cachedMode:state.settlementData.freight_mode}));
''')
    assert result['openedBeforeResponse'] == []
    assert result['opened'] == [{'kind': 'freight', 'args': ['B1', 'V1', 'packing']}]
    assert result['requests'] == [{'method': 'get_batch_settlement', 'args': {'batch_name': 'B1', 'version_name': 'V1'}}]
    assert result['cachedMode'] is True and result['errors'] == []


def test_confirmed_legacy_mode_opens_legacy_picker_only_after_the_mode_read():
    result = _fee_workspace_result(PACKING_ENTRY + r'''
let release;
workspace.settlementApi=()=>new Promise(resolve=>{release=resolve});
const pending=openPacking();const openedBeforeResponse=[...opened];
release({ok:true,freight_mode:false});await pending;
console.log(JSON.stringify({openedBeforeResponse,opened,errors}));
''')
    assert result == {'openedBeforeResponse': [], 'opened': [{'kind': 'legacy'}], 'errors': []}


def test_failed_or_outdated_mode_read_never_falls_back_to_legacy_picker():
    result = _fee_workspace_result(PACKING_ENTRY + r'''
workspace.settlementApi=async()=>({ok:false,message:'来源读取失败'});
await openPacking();
let release;workspace.settlementApi=()=>new Promise(resolve=>{release=resolve});
const pending=openPacking();workspace.detailState.batchName='B2';
release({ok:true,freight_mode:true});await pending;
console.log(JSON.stringify({opened,errors,cached:state.settlementData||null}));
''')
    assert result == {'opened': [], 'errors': ['来源读取失败'], 'cached': None}
