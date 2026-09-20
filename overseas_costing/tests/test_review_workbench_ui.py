import json
import subprocess
from pathlib import Path

import pytest

PARTS = Path(__file__).resolve().parents[1] / 'page/overseas_cost_workbench/parts'


def run_js(script):
    source = f"""
const fs=require('fs');
global.OverseasCostWorkbenchState=require({json.dumps(str(PARTS / '05-workbench-state.js'))});
const calculation=fs.readFileSync({json.dumps(str(PARTS / '30-calculation-erp.js'))},'utf8');
const vouchers=fs.readFileSync({json.dumps(str(PARTS / '40-vouchers.js'))},'utf8');
const drawer=fs.readFileSync({json.dumps(str(PARTS / '80-drawer-profit.js'))},'utf8');
const View=Function('return class View {{'+calculation+vouchers+fs.readFileSync({json.dumps(str(PARTS / '35-workbench-view.js'))},'utf8')+drawer+fs.readFileSync({json.dumps(str(PARTS / '82-detail-page.js'))},'utf8')+'}}')();
function makeView(task='cost') {{
 const v=new View(); v.viewState={{task,page:1,q:'',screen:'workbench'}};
 v.filters={{review_status:'pending',review_warning:'',issue:''}};
 v.html={{}};v.$root={{
   attr:key=>key==='data-screen'?v.viewState.screen:undefined,
   find:key=>({{html:value=>{{v.html[key]=value;}},toggleClass:()=>{{}}}})
 }};
 v.escape=x=>String(x??'').replaceAll('<','&lt;');
 v.formatMoney=x=>String(x);v.formatDateTimeMinute=x=>String(x||'');
 v.businessTypeLabel=x=>x;v.businessTypeOptions=[];v.selectOptions={{business_type:[]}};
 v.exceptionCounts={{}};v.reviewCounts={{pending:2,confirmed:1,estimated:1,evidence_missing:2}};
 return v;
}}
(async()=>{{{script}}})().catch(e=>{{console.error(e);process.exit(1)}});
"""
    return json.loads(subprocess.check_output(['node', '-e', source], text=True))


def test_review_url_state_and_filters_roundtrip():
    result=run_js("""
const s=OverseasCostWorkbenchState.parseWorkbenchState('/desk/x?task=cost&review_status=confirmed&review_warning=estimated');
const v=makeView();v.filters.review_status=s.reviewStatus;v.filters.review_warning=s.reviewWarning;
console.log(JSON.stringify({s,filters:v.workbenchFilters()}));
""")
    assert result['s']['reviewStatus']=='confirmed'
    assert result['filters']['review_status']=='confirmed'
    assert result['filters']['review_warning']=='estimated'


def test_workbench_shell_has_no_summary_card_row_for_any_task():
    source = (PARTS / '35-workbench-view.js').read_text(encoding='utf-8')
    assert 'data-area="exception-summary"' not in source
    assert 'ocw-summary-card' not in source
    assert 'renderExceptionSummary' not in source
    assert "data-action='set-review-filter'" not in source
    assert "data-action='set-issue'" not in source


def test_cost_row_uses_review_action_and_warning_cells():
    text=run_js("""const v=makeView();console.log(JSON.stringify(v.renderWorkbenchBatchRow({
name:'B',batch_no:'B',primary_issue:'ready',primary_action:'review',review_state:'ready',
review_blockers:[],review_warnings:[{code:'ESTIMATED_AMOUNT',message:'含暂估费用'}],
result_is_current:true,estimated_total_cost_rmb:100,status:'Calculated'})));""")
    assert '核对成本' in text
    assert '含暂估费用' in text
    assert 'data-primary-action="review"' in text


def test_stale_row_shows_old_result_and_specific_blocker():
    text=run_js("""const v=makeView('pending');console.log(JSON.stringify(v.renderWorkbenchBatchRow({
name:'B',batch_no:'B',primary_issue:'calculation',primary_action:'recalculate',review_state:'processing',
review_blockers:[{code:'STALE',message:'费用已变化，请重新试算'}],review_warnings:[],
result_is_current:false,calculated_at:'2026-09-08',estimated_total_cost_rmb:100,status:'Dirty'})));""")
    assert '上次结果，待更新' in text
    assert '费用已变化，请重新试算' in text


def test_out_of_order_success_and_error_cannot_replace_latest_task():
    result=run_js("""
const v=makeView('pending');const calls=[];const renders=[];
v.resetBatchResultPreview=()=>{};v.renderWorkbenchLoading=()=>{};
v.renderWorkbench=()=>renders.push(v.batches[0]?.name);
v.call=(method,args)=>new Promise((resolve,reject)=>calls.push({method,args,resolve,reject}));
v.renderWorkbenchError=e=>renders.push('error');
const first=v.loadBatches();v.viewState.task='cost';const second=v.loadBatches();
calls[2].resolve({ok:true,items:[{name:'READY'}],total:1,page:1});
calls[3].resolve({ok:true,counts:{},review_counts:{pending:1}});await second;
calls[0].reject(new Error('old request failed'));calls[1].resolve({counts:{purchase:99}});await first;
console.log(JSON.stringify({renders,items:v.batches,summaryTask:calls[3].args.task}));
""")
    assert result['renders']==['READY']
    assert result['items']==[{'name':'READY'}]
    assert result['summaryTask']=='cost'


def test_review_filter_change_clears_warning_and_restarts_page():
    result=run_js("""
const v=makeView();v.viewState.page=4;v.filters.review_warning='estimated';
v.syncWorkbenchFiltersToUrl=()=>{};v.loadBatches=async()=>{};
await v.setReviewFilter('confirmed');
console.log(JSON.stringify({page:v.viewState.page,filters:v.filters}));
""")
    assert result['page']==1
    assert result['filters']['review_status']=='confirmed'
    assert result['filters']['review_warning']==''


@pytest.mark.parametrize(
    ('task', 'review_status'),
    [('pending', 'pending'), ('cost', 'pending'), ('cost', 'confirmed'), ('erp', 'pending')],
)
def test_all_workbench_lists_use_logistics_process_start_time_header(task, review_status):
    html=run_js(f"""
global.window={{requestAnimationFrame:()=>{{}}}};
const v=makeView({json.dumps(task)});v.batches=[];v.workbenchTotal=0;
v.filters.review_status={json.dumps(review_status)};
v.renderWorkbenchBatchList();console.log(JSON.stringify(v.html));
""")
    text=''.join(html.values())
    assert '流程发起时间' in text
    assert '更新时间' not in text
    assert '确认时间' not in text


def test_workbench_row_uses_only_source_created_at_and_preserves_status_detail():
    result=run_js("""
const v=makeView();
const base={name:'B',batch_no:'B',primary_issue:'calculation',primary_action:'recalculate',
 review_blockers:[],review_warnings:[],estimated_total_cost_rmb:100};
const active=v.renderWorkbenchBatchRow({...base,review_state:'processing',result_is_current:false,
 source_created_at:'2026-09-01 08:15:00',modified:'2026-09-15 12:30:00',status:'Dirty'});
const confirmed=v.renderWorkbenchBatchRow({...base,review_state:'confirmed',result_is_current:true,
 source_created_at:'2026-09-02 09:20:00',reviewed_at:'2026-09-16 10:45:00',reviewed_version:'V3'});
const missing=v.renderWorkbenchBatchRow({...base,review_state:'processing',result_is_current:true,
 source_created_at:'',modified:'2026-09-17 11:00:00',status:'Draft'});
console.log(JSON.stringify({active,confirmed,missing}));
""")
    assert '2026-09-01 08:15:00' in result['active']
    assert '2026-09-15 12:30:00' not in result['active']
    assert '待重新试算' in result['active']
    assert '2026-09-02 09:20:00' in result['confirmed']
    assert '2026-09-16 10:45:00' not in result['confirmed']
    assert '确认版本 V3' in result['confirmed']
    assert '<strong>—</strong>' in result['missing']
    assert '2026-09-17 11:00:00' not in result['missing']
    assert '<span>Draft</span>' in result['missing']


def test_batch_action_column_is_right_aligned_on_desktop_and_left_aligned_on_mobile():
    css = (PARTS / '25-workbench-redesign.css').read_text(encoding='utf-8')
    assert '.ocw-batch-grid-head > :last-child {' in css
    assert 'justify-self: end;' in css
    assert 'text-align: right;' in css
    mobile = css.split('@media (max-width: 980px) {', 1)[1]
    assert '.ocw-row-actions { justify-self: start; justify-content: flex-start; }' in mobile


def test_detail_navigation_invalidates_pending_list_without_reopening_detail():
    result=run_js("""
const v=makeView('pending'), calls=[], renders=[];
v.batches=[];v.detailState={batchName:'',requestId:0,refreshRequestId:0};
v.resetBatchResultPreview=()=>{};v.renderWorkbenchLoading=()=>{};
v.renderWorkbench=()=>renders.push('list');v.renderWorkbenchError=()=>renders.push('error');
v.renderDetailLoading=()=>{};v.renderDetailShell=()=>renders.push('detail');
v.renderDetailError=e=>{throw e};v.switchDetailTab=async()=>{};v.findBatch=()=>null;
v.getDefaultPullDateRange=()=>({start_date:'2026-08-10',end_date:'2026-09-08'});
v.$root={attr:()=>{},find:()=>({prop:()=>{}})};
v.call=(method,args)=>method.includes('get_batch_detail')
 ? (calls.push({method}),Promise.resolve({ok:true,batch_name:'DETAIL',header:{name:'DETAIL'}}))
 : new Promise(resolve=>calls.push({method,resolve}));
const oldList=v.loadBatches();
global.window={location:{href:'/desk/x?task=cost&review_status=confirmed&screen=detail&batch=DETAIL&tab=overview&page=3',pathname:'/desk/x'}};
await v.handleWorkbenchPopState();v.detailState.dirty=true;
calls[0].resolve({ok:true,items:[{name:'PENDING-1'}],total:1,page:1});
calls[1].resolve({counts:{}});await oldList;
console.log(JSON.stringify({renders,dirty:v.detailState.dirty,page:v.viewState.page,
 detailCalls:calls.filter(c=>c.method.includes('get_batch_detail')).length}));
""")
    assert result == {'renders': ['detail'], 'dirty': True, 'page': 3, 'detailCalls': 1}


@pytest.mark.parametrize('start,end', [('', ''), ('2026-01-01', ''), ('', '2026-09-08')])
def test_explicitly_cleared_date_boundaries_survive_url_reload_and_history(start, end):
    result=run_js(f"""
const expected={{start_date:{json.dumps(start)},end_date:{json.dumps(end)}}};
const url=OverseasCostWorkbenchState.buildWorkbenchUrl('/desk/x?task=cost&page=3',expected);
const v=makeView();v.detailState={{batchName:'',requestId:0,skuRequestId:0,refreshRequestId:0}};
global.window={{location:{{href:url}},history:{{state:{{}}}},scrollTo:()=>{{}}}};
global.requestAnimationFrame=()=>{{}};
v.getDefaultPullDateRange=()=>({{start_date:'2026-08-10',end_date:'2026-09-08'}});
v.$root={{find:()=>({{prop:()=>{{}}}})}};let requested;
v.loadBatches=async()=>{{requested=v.workbenchFilters()}};
await v.handleWorkbenchPopState();
console.log(JSON.stringify({{url,parsed:OverseasCostWorkbenchState.parseWorkbenchState(url),requested,page:v.viewState.page}}));
""")
    assert result['parsed']['hasDateRange'] is True
    assert result['requested']['start_date'] == start
    assert result['requested']['end_date'] == end
    assert result['page'] == 3


def test_successful_list_recalculation_refreshes_authoritative_groups_and_cards():
    result=run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('pending'), calls=[];
const old={name:'B',current_version:'V',review_state:'processing',result_is_current:false};
v.batches=[old];v.findBatch=()=>old;v.detailState={batchName:''};
v.acceptSavedComprehensiveCost=()=>{};v.applyRecalculateSummary=()=>{};
v.resetBatchResultPreview=()=>{};v.renderWorkbenchLoading=()=>{};v.renderWorkbench=()=>{};
v.loadBatchItems=async()=>{};v.loadAuditLogs=async()=>{};v.renderTable=()=>{};
v.renderRecalculateResult=()=>{};v.renderWorkbenchBatchList=()=>{};v.recordUsage=()=>{};
v.showError=e=>{throw e};v.$root={attr:()=> 'workbench'};
v.call=async(method)=>{calls.push(method);
 if(method.endsWith('acquire')) return {ok:true,edit_token:'TOKEN',modified:'BEFORE'};
 if(method.endsWith('recalculate_batch')) return {ok:true,saved:true,summary_snapshot:{total_cost_rmb:130}};
 if(method.endsWith('get_batches')) return {ok:true,items:[],total:0,page:1};
 if(method.endsWith('get_summary')) return {counts:{calculation:0},review_counts:{pending:1}};
 return {ok:true};};
await v.recalculate('B');
console.log(JSON.stringify({calls,rows:v.batches,counts:v.exceptionCounts,review:v.reviewCounts}));
""")
    assert 'overseas_costing.api.workbench.get_batches' in result['calls']
    assert 'overseas_costing.api.workbench.get_summary' in result['calls']
    assert result['rows'] == []
    assert result['counts']['calculation'] == 0
    assert result['review']['pending'] == 1
    assert result['calls'][-1] == 'overseas_costing.api.edit_session.release'


@pytest.mark.parametrize(
    ('batch', 'expected_label'),
    [
        ({'status': 'Draft', 'summary_snapshot': {}}, '开始试算'),
        ({'status': 'Dirty', 'calculated_at': '2026-09-12 15:00:00', 'result_is_current': False}, '重新计算'),
    ],
)
def test_detail_uses_one_header_calculation_entry_with_contextual_label(batch, expected_label):
    result = run_js(f"""
const v=makeView('pending');
const batch={{name:'B',batch_no:'B',current_version:'V',primary_issue:'calculation',item_count:1,...{json.dumps(batch)}}};
v.detailState={{batchName:'B',tab:'overview',header:batch,dingtalkApproval:{{batch_name:'B'}},detail:{{}}}};
v.batches=[batch];v.getDetailBatch=()=>batch;
v.cleanupSkuScrollControls=()=>{{}};v.cleanupMaterialGridScrollControls=()=>{{}};
v.sourceStatusLabel=()=>'已齐备';v.erpWritebackStatusInfo=()=>({{label:'未开始',state:'neutral'}});
v.batchStatusInfo=()=>({{label:'待试算',needsRecalculate:true}});v.renderDetailErpAction=()=>'';
v.issueLabel=x=>x;v.transportLabel=x=>x;v.formatValue=x=>String(x??'');
v.renderBatchDrawerOverview=()=>'';v.loadDingtalkApprovalDetail=async()=>{{}};
v.renderDetailShell();const shell=v.html["[data-area='detail-screen']"];
v.renderOverviewDetailTab();const overview=v.html["[data-area='detail-content']"];
console.log(JSON.stringify({{shell,overview}}));
""")
    assert expected_label in result['shell']
    assert result['shell'].count('data-primary-action="recalculate"') == 1
    assert 'data-action="detail-recalculate"' not in result['overview']


def test_gap_rows_keep_supplement_actions_but_point_to_the_header_calculation_entry():
    html = run_js("""
const v=makeView('pending');const batch={name:'B'};v.findBatch=()=>batch;
const html=v.renderErpFieldGapsWithActions({items:[{fieldname:'unit_price',label:'采购单价',item_name:'I-1'}]},'B',{});
console.log(JSON.stringify(html));
""")
    assert 'data-action="gap-open-item-edit"' in html
    assert 'gap-recalculate' not in html
    assert '页头' in html and '计算入口' in html


def test_saved_detail_recalculation_moves_ready_batch_to_cost_review_and_keeps_detail_open():
    result = run_js("""
global.frappe={show_alert:()=>{}};
global.window={location:{href:'/desk/x?task=pending&screen=detail&batch=B&tab=overview',pathname:'/desk/x'},history:{state:{}}};
const v=makeView('pending'), calls=[], replacements=[], opened=[];
const old={name:'B',current_version:'V',review_state:'processing',status:'Dirty'};
const ready={...old,review_state:'ready',review_blockers:[],status:'Calculated',calculated_at:'2026-09-20'};
v.viewState={task:'pending',screen:'detail',batch:'B',tab:'overview',page:1,q:''};
v.filters={review_status:'pending',review_warning:'',issue:''};v.batches=[old];
v.detailState={batchName:'B',tab:'overview',header:old,editToken:'TOKEN',expectedModified:'BEFORE'};
v.findBatch=name=>v.batches.find(row=>row.name===name)||null;v.ensureEditSession=async()=>true;
v.acceptSavedComprehensiveCost=()=>{};v.applyRecalculateSummary=()=>{};v.resetBatchResultPreview=()=>{};
v.renderWorkbenchLoading=()=>{};v.renderWorkbench=()=>{};v.renderDetailShell=()=>{};v.switchDetailTab=async()=>{};
v.refreshDetailSummary=async()=>{};v.recordUsage=()=>{};v.showError=e=>{throw e};
v.replaceViewState=values=>{replacements.push(values);v.viewState={...v.viewState,...values};};
v.openBatchDetail=async(name,tab)=>opened.push({name,tab,task:v.viewState.task});
v.call=async(method,args)=>{calls.push({method,args});
 if(method.endsWith('recalculate_batch'))return {ok:true,saved:true,summary_snapshot:{total_cost_rmb:130}};
 if(method.endsWith('get_batches')&&args.task==='cost'&&args.page_length===10)return {ok:true,items:[ready],total:1,page:1};
 if(method.endsWith('get_batches'))return {ok:true,items:[ready],total:1,page:1};
 if(method.endsWith('get_summary'))return {ok:true,counts:{},review_counts:{pending:1}};
 return {ok:true};};
await v.recalculate('B');
console.log(JSON.stringify({task:v.viewState.task,reviewStatus:v.filters.review_status,replacements,opened,calls,header:v.detailState.header}));
""")
    assert result['task'] == 'cost'
    assert result['reviewStatus'] == 'pending'
    assert result['replacements'][-1]['screen'] == 'detail'
    assert result['replacements'][-1]['batch'] == 'B'
    assert result['opened'][-1] == {'name': 'B', 'tab': 'overview', 'task': 'cost'}
    assert result['header']['review_state'] == 'ready'


def test_saved_detail_recalculation_keeps_processing_batch_pending_with_server_blocker():
    result = run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('pending'), calls=[];
const old={name:'B',current_version:'V',review_state:'processing',status:'Dirty'};
const processing={...old,review_blockers:[{code:'MISSING_PRICE',message:'还有 1 行采购单价待补'}]};
v.viewState={task:'pending',screen:'detail',batch:'B',tab:'overview',page:1,q:''};
v.filters={review_status:'pending',review_warning:'',issue:''};v.batches=[old];
v.detailState={batchName:'B',tab:'overview',header:old,editToken:'TOKEN',expectedModified:'BEFORE'};
v.findBatch=name=>v.batches.find(row=>row.name===name)||null;v.ensureEditSession=async()=>true;
v.acceptSavedComprehensiveCost=()=>{};v.applyRecalculateSummary=()=>{};v.resetBatchResultPreview=()=>{};
v.refreshDetailSummary=async()=>{};v.renderDetailShell=()=>{};v.switchDetailTab=async()=>{};
v.recordUsage=()=>{};v.showError=e=>{throw e};v.replaceViewState=values=>{v.viewState={...v.viewState,...values};};
v.loadBatches=async()=>{};
v.call=async(method,args)=>{calls.push({method,args});
 if(method.endsWith('recalculate_batch'))return {ok:true,saved:true,summary_snapshot:{total_cost_rmb:80}};
 if(method.endsWith('get_batches')&&args.task==='cost')return {ok:true,items:[],total:0,page:1};
 if(method.endsWith('get_batches')&&args.task==='pending')return {ok:true,items:[processing],total:1,page:1};
 return {ok:true};};
await v.recalculate('B');
console.log(JSON.stringify({task:v.viewState.task,header:v.detailState.header,calls}));
""")
    assert result['task'] == 'pending'
    assert result['header']['review_blockers'][0]['message'] == '还有 1 行采购单价待补'
    assert any(call['args'].get('task') == 'pending' for call in result['calls'] if call['method'].endswith('get_batches'))


def test_processing_detail_renders_authoritative_review_blockers():
    html = run_js("""
const v=makeView('pending');
console.log(JSON.stringify(v.renderDetailReviewBlockers({review_blockers:[{code:'MISSING_PRICE',message:'还有 1 行采购单价待补'}]})));
""")
    assert '还有 1 行采购单价待补' in html


def test_calculation_confirmation_is_hidden_and_blocked_outside_cost_task():
    result = run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('pending'),calls=[];
const batch={name:'B',current_version:'V',status:'Calculated',item_count:1,subsidiary_code:'MX'};
v.findBatch=()=>batch;v.drawerBatchName='B';v.showPendingFeature=message=>{v.blocked=message};
v.call=async(method)=>{calls.push(method);return {ok:true,confirmed:true};};
v.recordUsage=()=>{};v.refreshBatch=async()=>{};v.showError=e=>{throw e};
v.hasText=x=>Boolean(x);v.isCalculationConfirmed=()=>false;v.batchStatusInfo=()=>({label:'已试算',needsRecalculate:false});
v.erpWritebackStatusInfo=()=>({label:'未开始',state:'neutral'});v.erpPushActionState=()=>({label:'推送 ERP',enabled:false,reason:'待核对'});
v.isPositive=x=>Number(x)>0;v.formatValue=x=>String(x??'');v.renderErpFlowBlockInline=()=>'';
const pendingHtml=v.renderErpFlowPanel(batch,[]);
await v.confirmCalculationResult('B');
v.viewState.task='cost';const costHtml=v.renderErpFlowPanel(batch,[]);
console.log(JSON.stringify({pendingHtml,costHtml,calls,blocked:v.blocked}));
""")
    assert 'data-action="confirm-calculation-result"' not in result['pendingHtml']
    assert '校验计算结果' not in result['pendingHtml']
    assert 'data-action="confirm-calculation-result"' in result['costHtml']
    assert 'data-action="confirm-calculation-result" disabled' in result['costHtml']
    assert result['calls'] == []
    assert '成本核对' in result['blocked']


def test_cost_confirmation_refreshes_authoritative_erp_queue_without_auto_push():
    result = run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('cost'),calls=[],replacements=[];
const batch={name:'B',current_version:'V',status:'Calculated',review_state:'ready'};v.batches=[batch];v.findBatch=()=>batch;
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};v.detailState={batchName:'B',tab:'overview'};
v.replaceViewState=values=>{replacements.push(values);v.viewState={...v.viewState,...values};};
v.loadBatches=async()=>calls.push('loadBatches');v.refreshBatch=async()=>calls.push('refreshBatch');v.recordUsage=()=>{};v.showError=e=>{throw e};
v.call=async(method,args)=>{calls.push(method);
 if(method.endsWith('get_batches'))return {ok:true,items:[batch],total:1,page:1,page_length:100};
 return {ok:true,confirmed:true,message:'已确认'};};
await v.confirmCalculationResult('B');
console.log(JSON.stringify({task:v.viewState.task,calls,replacements}));
""")
    assert result['task'] == 'erp'
    assert result['calls'].count('loadBatches') == 1
    assert not any('writeback_to_erp' in call or 'queue_erp' in call for call in result['calls'])
    assert result['replacements'][-1]['screen'] == 'detail'
    assert result['replacements'][-1]['batch'] == 'B'


def test_cost_confirmation_requires_local_ready_state_before_any_api_call():
    result = run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('cost'),calls=[];
const batch={name:'B',current_version:'V',status:'Calculated',review_state:'processing'};
v.batches=[batch];v.findBatch=()=>batch;v.drawerBatchName='B';
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};
v.detailState={batchName:'B',tab:'overview',header:batch};
v.showPendingFeature=message=>{v.blocked=message};v.replaceViewState=values=>{v.viewState={...v.viewState,...values};};
v.loadBatches=async()=>{};v.recordUsage=()=>{};v.showError=e=>{v.blocked=e.message};
v.call=async method=>{calls.push(method);return {ok:true}};
await v.confirmCalculationResult('B');
console.log(JSON.stringify({task:v.viewState.task,calls,blocked:v.blocked}));
""")
    assert result['calls'] == []
    assert result['task'] == 'pending'
    assert '待处理' in result['blocked']


def test_cost_confirmation_rechecks_authoritative_ready_state_before_confirming():
    result = run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('cost'),calls=[];
const batch={name:'B',batch_no:'B-NO',current_version:'V',status:'Calculated',review_state:'ready'};
v.batches=[batch];v.findBatch=()=>batch;v.drawerBatchName='B';
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};v.detailState={batchName:'B',tab:'overview',header:batch,requestId:4};
v.replaceViewState=values=>{v.viewState={...v.viewState,...values};};v.loadBatches=async()=>{};
v.recordUsage=()=>{};v.showError=e=>{throw e};
v.call=async(method,args)=>{calls.push({method,args});
 if(method.endsWith('get_batches'))return {ok:true,items:[batch],total:1,page:1,page_length:100};
 if(method.endsWith('confirm_calculation_result'))return {ok:true,confirmed:true};
 throw new Error(method);};
await v.confirmCalculationResult('B');
console.log(JSON.stringify({calls,task:v.viewState.task}));
""")
    assert [call['method'].rsplit('.', 1)[-1] for call in result['calls']] == [
        'get_batches',
        'confirm_calculation_result',
    ]
    assert result['calls'][0]['args']['task'] == 'cost'


def test_cost_confirmation_downgrade_blocks_confirm_and_returns_to_pending():
    result = run_js("""
const v=makeView('cost'),calls=[];
const local={name:'B',batch_no:'B-NO',current_version:'V',status:'Calculated',review_state:'ready'};
const processing={...local,review_state:'processing',review_blockers:[{code:'STALE',message:'费用已变更'}]};
v.batches=[local];v.findBatch=()=>local;v.drawerBatchName='B';
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};v.detailState={batchName:'B',tab:'overview',header:local,requestId:2};
v.replaceViewState=values=>{v.viewState={...v.viewState,...values};};v.loadBatches=async()=>{};
v.renderDetailShell=()=>{};v.switchDetailTab=async()=>{};v.showPendingFeature=message=>{v.blocked=message};
v.recordUsage=()=>{};v.showError=e=>{v.blocked=e.message};
v.call=async(method,args)=>{calls.push({method,args});
 if(method.endsWith('get_batches')&&args.task==='cost')return {ok:true,items:[],total:0,page:1,page_length:100};
 if(method.endsWith('get_batches')&&args.task==='pending')return {ok:true,items:[processing],total:1,page:1,page_length:100};
 throw new Error('confirmation must stay blocked');};
await v.confirmCalculationResult('B');
console.log(JSON.stringify({calls,task:v.viewState.task,header:v.detailState.header,blocked:v.blocked}));
""")
    assert [call['args']['task'] for call in result['calls']] == ['cost', 'pending']
    assert result['task'] == 'pending'
    assert result['header']['review_state'] == 'processing'
    assert '待处理' in result['blocked']


def test_authoritative_classification_walks_pages_until_exact_batch_is_found():
    result = run_js("""
const v=makeView('pending'),calls=[];
const current={name:'TARGET',batch_no:'B-NO'};v.batches=[current];v.findBatch=()=>current;v.detailState={header:current};
v.call=async(method,args)=>{calls.push(args);
 if(args.task==='cost'&&args.page===1)return {ok:true,items:Array.from({length:100},(_,i)=>({name:`OTHER-${i}`})),total:101,page:1,page_length:100};
 if(args.task==='cost'&&args.page===2)return {ok:true,items:[{...current,review_state:'ready'}],total:101,page:2,page_length:100};
 throw new Error('pending should not be queried');};
const found=await v.getAuthoritativeReviewClassification('TARGET');
console.log(JSON.stringify({found,calls}));
""")
    assert result['found']['task'] == 'cost'
    assert result['found']['batch']['name'] == 'TARGET'
    assert [call['page'] for call in result['calls']] == [1, 2]
    assert all(call['page_length'] == 100 for call in result['calls'])


def test_saved_recalculation_refresh_failure_warns_without_marking_calculation_failed():
    result = run_js("""
const alerts=[];global.frappe={show_alert:value=>alerts.push(value)};
const v=makeView('pending'),events=[];
const batch={name:'B',batch_no:'B-NO',current_version:'V',review_state:'processing',status:'Dirty'};
v.batches=[batch];v.findBatch=()=>batch;v.viewState={task:'pending',screen:'detail',batch:'B',tab:'overview',page:1};
v.detailState={batchName:'B',tab:'overview',header:batch,editToken:'TOKEN',expectedModified:'M1',requestId:1};
v.ensureEditSession=async()=>true;v.acceptSavedComprehensiveCost=()=>{};v.applyRecalculateSummary=()=>{};v.resetBatchResultPreview=()=>{};
v.call=async method=>{if(method.endsWith('recalculate_batch'))return {ok:true,saved:true,summary_snapshot:{}};throw new Error('分类服务不可用')};
v.refreshDetailSummary=async()=>{events.push('fallback')};v.recordUsage=(action,payload)=>events.push(payload.status||'Success');v.showError=e=>events.push(`error:${e.message}`);
await v.recalculate('B');
console.log(JSON.stringify({events,alerts}));
""")
    assert result['events'] == ['fallback', 'Success']
    assert any('已保存' in alert['message'] for alert in result['alerts'])
    assert not any('试算失败' in alert['message'] for alert in result['alerts'])


def test_stale_recalculation_classification_cannot_navigate_a_new_detail_context():
    result = run_js("""
const alerts=[];global.frappe={show_alert:value=>alerts.push(value)};
const v=makeView('pending'),replacements=[];
const batch={name:'B',batch_no:'B-NO',current_version:'V',review_state:'processing',status:'Dirty'};
v.batches=[batch];v.findBatch=name=>v.batches.find(row=>row.name===name)||null;
v.viewState={task:'pending',screen:'detail',batch:'B',tab:'overview',page:1};
v.detailState={batchName:'B',tab:'overview',header:batch,editToken:'TOKEN',expectedModified:'M1',requestId:7};
v.ensureEditSession=async()=>true;v.acceptSavedComprehensiveCost=()=>{};v.applyRecalculateSummary=()=>{};v.resetBatchResultPreview=()=>{};
let release;v.call=async(method,args)=>{if(method.endsWith('recalculate_batch'))return {ok:true,saved:true,summary_snapshot:{}};
 return await new Promise(resolve=>{release=resolve})};
v.replaceViewState=values=>replacements.push(values);v.loadBatches=async()=>{};v.refreshDetailSummary=async()=>{};v.recordUsage=()=>{};v.showError=e=>{throw e};
const running=v.recalculate('B');await new Promise(resolve=>setImmediate(resolve));
v.detailState.batchName='OTHER';v.detailState.requestId=8;v.viewState.batch='OTHER';
release({ok:true,items:[{...batch,review_state:'ready'}],total:1,page:1,page_length:100});await running;
console.log(JSON.stringify({task:v.viewState.task,batch:v.detailState.batchName,replacements}));
""")
    assert result == {'task': 'pending', 'batch': 'OTHER', 'replacements': []}
