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


def test_cost_row_uses_review_action_and_compact_warning_tags():
    text=run_js("""const v=makeView();console.log(JSON.stringify(v.renderWorkbenchBatchRow({
name:'B',batch_no:'B',primary_issue:'ready',primary_action:'review',review_state:'ready',
review_blockers:[],review_warnings:[{code:'ESTIMATED_AMOUNT',message:'含暂估费用，可先审核，最终确认前仍需补充实际金额。'}],
result_is_current:true,estimated_total_cost_rmb:100,status:'Calculated'})));""")
    assert '核对成本' in text
    assert '实际费用待确认' in text
    assert 'ocw-review-tag' in text
    assert '最终确认前' not in text
    assert 'data-primary-action="review"' in text


def test_result_preview_uses_server_adopted_price_and_shared_native_scrollbar():
    source = (PARTS / '35-workbench-view.js').read_text(encoding='utf-8')
    renderer = source.split('renderBatchResultPreview(data)', 1)[1].split('bindResultPreviewScrollControls', 1)[0]
    assert 'item.adopted_price' in renderer
    assert 'data-ocw-scrollbar' in renderer
    assert 'type="range"' not in renderer
    assert 'shouldCompactResultPreviewColumns' not in source


def test_drawer_and_erp_preview_use_server_adopted_price_projection():
    drawer = (PARTS / "80-drawer-profit.js").read_text(encoding="utf-8")
    erp = (PARTS / "30-calculation-erp.js").read_text(encoding="utf-8")

    assert "item.adopted_price?.value ?? item.unit_price" in drawer
    assert "按货值÷采购数量计算" in drawer
    assert "item.adopted_price?.value ?? item.original_unit_price" in erp
    assert "按货值÷采购数量计算" in erp


def test_result_and_sku_tables_share_one_scroll_controller_without_geometry_feedback():
    result_source = (PARTS / '35-workbench-view.js').read_text(encoding='utf-8')
    sku_source = (PARTS / '82-detail-page.js').read_text(encoding='utf-8')
    material_source = (PARTS / '78-material-fee-workspace.js').read_text(encoding='utf-8')
    allocation_source = (PARTS / '76-allocation.js').read_text(encoding='utf-8')
    material_css = (PARTS / '48-material-fee-workspace.css').read_text(encoding='utf-8')
    helper_source = (PARTS / '15-horizontal-scroll.js').read_text(encoding='utf-8')

    assert 'bindHorizontalScrollController' in helper_source
    assert 'shouldCompactResultPreviewColumns' not in result_source
    assert 'shouldCompactSkuColumns' not in sku_source
    assert 'bindHorizontalScrollController' in result_source
    assert 'bindHorizontalScrollController' in sku_source
    assert 'bindHorizontalScrollController' in material_source
    assert 'bindHorizontalScrollController' in allocation_source
    assert 'const bindPair =' not in allocation_source
    assert 'compactWidth' not in material_source
    assert '--mf-grid-reduction' not in material_css
    assert 'column.style.width' not in helper_source


def test_missing_status_copy_uses_danger_color_while_pending_sources_remain_amber():
    settlement_css = (PARTS / '47-settlement.css').read_text(encoding='utf-8')
    shell_css = (PARTS / '10-shell.css').read_text(encoding='utf-8')

    assert '.ocw-freight-missing { color: #b42318; }' in settlement_css
    assert '.ocw-purchase-approval-metric.is-missing strong' in shell_css
    assert 'color: #b42318;' in shell_css.split('.ocw-purchase-approval-metric.is-missing strong', 1)[1].split('}', 1)[0]
    assert 'color: #9a6700;' in shell_css.split('.ocw-purchase-approval-metric.is-pending strong', 1)[1].split('}', 1)[0]


def test_stale_row_shows_old_result_and_specific_blocker():
    text=run_js("""const v=makeView('pending');console.log(JSON.stringify(v.renderWorkbenchBatchRow({
name:'B',batch_no:'B',primary_issue:'calculation',primary_action:'recalculate',review_state:'processing',
review_blockers:[{code:'STALE',message:'费用已变化，请重新试算'}],review_warnings:[],
result_is_current:false,calculated_at:'2026-09-08',estimated_total_cost_rmb:100,status:'Dirty'})));""")
    assert '上次结果，待更新' in text
    assert '待重新计算' in text
    assert '费用已变化，请重新试算' not in text


def test_processing_row_limits_short_tags_and_hides_raw_messages():
    text=run_js("""const v=makeView('pending');console.log(JSON.stringify(v.renderWorkbenchBatchRow({
name:'B',batch_no:'B',primary_issue:'logistics',primary_action:'supplement_fees',review_state:'processing',
review_blockers:[
 {code:'AMOUNT_MISSING',message:'存在未填金额的费用，请补充费用。'},
 {code:'PURCHASE_SOURCE_INVALID',message:'采购来源已失效或无法读取，请先核对采购资料。'},
 {code:'UNEXPECTED_REVIEW_CODE',message:'这是一段不应直接出现在列表中的长说明。'}
],
review_warnings:[{code:'EVIDENCE_MISSING',message:'费用凭证缺失或尚未通过校验，可先审核。'}],
result_is_current:false,calculated_at:'2026-09-08',estimated_total_cost_rmb:100,status:'Dirty'})));""")
    assert '资料待补' in text
    assert '费用金额待补' in text
    assert '采购资料待补' in text
    assert '其他问题待处理' in text
    assert '另有 1 项' in text
    assert text.count('ocw-review-tag ') == 4
    assert '存在未填金额的费用' not in text
    assert '不应直接出现' not in text


def test_review_tag_labels_cover_current_allocation_and_final_fee_codes():
    result=run_js("""const v=makeView();console.log(JSON.stringify({
allocation:v.workbenchReviewTagLabel('ALLOCATION_REQUIRED'),
finalFee:v.workbenchReviewTagLabel('FINAL_FEE_REVIEW_REQUIRED')}));""")
    assert result == {
        'allocation': '分摊资料待补',
        'finalFee': '费用待核对',
    }


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
        ({'status': 'Dirty', 'result_is_current': False, 'summary_snapshot': {}}, '开始试算'),
        ({'status': 'Dirty', 'calculated_at': '2026-09-12 15:00:00', 'result_is_current': False}, '重新试算'),
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
    header, status = result['shell'].split('<section class="ocw-detail-statusarea">', 1)
    assert 'data-primary-action="recalculate"' not in header
    assert 'data-primary-action="recalculate"' in status
    assert 'data-action="detail-recalculate"' not in result['overview']


def test_header_calculation_entry_switches_to_documents_and_opens_trial_without_direct_recalculate():
    result = run_js("""
const v=makeView('pending'),events=[];
v.viewState={task:'pending',screen:'detail',batch:'B',tab:'overview'};
v.detailState={batchName:'B',tab:'overview'};
v.$root={attr:key=>key==='data-screen'?'detail':undefined};
v.switchDetailTab=async tab=>{events.push(`tab:${tab}`);v.detailState.tab=tab;v.viewState.tab=tab};
v.refreshMaterialFeeCostPreview=async scroll=>events.push(`trial:${scroll}`);
v.recalculate=async()=>events.push('direct-recalculate');
await v.startDetailCostTrial();
console.log(JSON.stringify({events,tab:v.detailState.tab}));
""")
    assert result == {'events': ['tab:documents', 'trial:true'], 'tab': 'documents'}


def test_header_calculation_entry_stops_if_detail_changed_while_switching_tabs():
    result = run_js("""
const v=makeView('pending'),events=[];
v.viewState={task:'pending',screen:'detail',batch:'B',tab:'overview'};
v.detailState={batchName:'B',tab:'overview'};
v.$root={attr:key=>key==='data-screen'?v.viewState.screen:undefined};
v.switchDetailTab=async tab=>{events.push(`tab:${tab}`);v.detailState={...v.detailState,batchName:'OTHER',tab};v.viewState={...v.viewState,batch:'OTHER',tab}};
v.refreshMaterialFeeCostPreview=async()=>events.push('trial');
await v.startDetailCostTrial();
console.log(JSON.stringify({events,batch:v.detailState.batchName}));
""")
    assert result == {'events': ['tab:documents'], 'batch': 'OTHER'}


def test_detail_and_workspace_sources_have_no_legacy_trial_handlers():
    workbench = (PARTS / '35-workbench-view.js').read_text(encoding='utf-8')
    workspace = (PARTS / '78-material-fee-workspace.js').read_text(encoding='utf-8')
    assert "[data-action='detail-recalculate']" not in workbench
    assert "[data-action='mf-preview-cost']" not in workspace


@pytest.mark.parametrize(
    ('task', 'batch'),
    [
        ('erp', {'status': 'Confirmed', 'confirm_status': 'Confirmed', 'is_locked': 1}),
        ('pending', {'status': 'Confirmed'}),
        ('pending', {'status': 'Calculated', 'is_locked': 1}),
    ],
)
def test_detail_hides_calculation_entry_outside_pending_editable_flow(task, batch):
    result = run_js(f"""
const v=makeView({json.dumps(task)});const batch={{name:'B',current_version:'V',...{json.dumps(batch)}}};
v.viewState={{task:{json.dumps(task)},screen:'detail',batch:'B',tab:'overview'}};
v.detailState={{batchName:'B',tab:'overview',header:batch}};v.batches=[batch];v.getDetailBatch=()=>batch;
v.cleanupSkuScrollControls=()=>{{}};v.cleanupMaterialGridScrollControls=()=>{{}};
v.sourceStatusLabel=()=>'已齐备';v.erpWritebackStatusInfo=()=>({{label:'未开始',state:'neutral'}});
v.batchStatusInfo=()=>({{label:'已试算',needsRecalculate:false}});v.renderDetailErpAction=()=>'';
v.issueLabel=x=>x;v.transportLabel=x=>x;v.formatValue=x=>String(x??'');
v.renderDetailReviewBlockers=()=>'';v.renderDetailShell();
console.log(JSON.stringify(v.html["[data-area='detail-screen']"]));
""")
    assert 'data-primary-action="recalculate"' not in result


def test_cost_review_keeps_one_retrial_entry():
    result = run_js("""
const v=makeView('cost');const batch={name:'B',current_version:'V',status:'Calculated',review_state:'ready',calculated_at:'2026-09-20'};
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview'};
v.detailState={batchName:'B',tab:'overview',header:batch};v.batches=[batch];v.getDetailBatch=()=>batch;
v.cleanupSkuScrollControls=()=>{};v.cleanupMaterialGridScrollControls=()=>{};
v.sourceStatusLabel=()=>'已齐备';v.erpWritebackStatusInfo=()=>({label:'未开始',state:'neutral'});
v.batchStatusInfo=()=>({label:'已试算',needsRecalculate:false});v.renderDetailErpAction=()=>'';
v.issueLabel=x=>x;v.transportLabel=x=>x;v.formatValue=x=>String(x??'');
v.renderDetailShell();console.log(JSON.stringify(v.html["[data-area='detail-screen']"]));
""")
    assert result.count('data-primary-action="recalculate"') == 1
    assert '重新试算' in result


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


def test_failed_recalculation_uses_single_locally_handled_error():
    result = run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('pending'),calls=[],errors=[];
const batch={name:'B',current_version:'V',review_state:'processing',status:'Dirty'};
v.batches=[batch];v.findBatch=()=>batch;
v.viewState={task:'pending',screen:'detail',batch:'B',tab:'documents',page:1};
v.detailState={batchName:'B',tab:'documents',header:batch,editToken:'TOKEN',expectedModified:'M1'};
v.ensureEditSession=async()=>true;v.recordUsage=()=>{};v.showError=error=>errors.push(error.message);
v.call=async(method,args,freeze=false,options={})=>{
 calls.push({method,args,freeze,options});
 if(method.endsWith('recalculate_batch'))throw new Error('还有 2 行本次发货货值缺失或失效，请先补齐后再试算。');
 return {ok:true};
};
await v.recalculate('B');
console.log(JSON.stringify({calls,errors}));
""")

    trial_call = next(call for call in result['calls'] if call['method'].endswith('recalculate_batch'))
    assert trial_call['freeze'] is True
    assert trial_call['options'] == {}
    assert result['errors'] == ['还有 2 行本次发货货值缺失或失效，请先补齐后再试算。']


def test_processing_detail_renders_authoritative_review_blockers():
    html = run_js("""
const v=makeView('pending');
console.log(JSON.stringify(v.renderDetailReviewBlockers({review_blockers:[
 {code:'MISSING_PRICE',message:'还有 1 行采购单价待补'},
 {code:'MISSING_EVIDENCE',message:'还有 2 项凭证待补'},
 {code:'STALE',message:'费用已变化，请重新试算'}
]})));
""")
    assert '还有 1 行采购单价待补' in html
    assert 'ocw-detail-review-strip' in html
    assert 'ocw-erp-block-dialog' not in html
    assert '<summary>更多 2</summary>' in html
    assert '还有 2 项凭证待补' in html


def test_cost_review_renders_blocker_strip_and_no_blocker_keeps_single_status_line():
    result = run_js("""
const v=makeView('cost');
const withBlocker=v.renderDetailReviewBlockers({review_blockers:[{code:'STALE',message:'费用已变化，请重新试算'}]});
const clear=v.renderDetailReviewBlockers({review_blockers:[]});
console.log(JSON.stringify({withBlocker,clear}));
""")
    assert '费用已变化，请重新试算' in result['withBlocker']
    assert result['clear'] == ''


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


def test_double_confirmation_shares_one_batch_version_inflight_operation_and_releases_it():
    result = run_js("""
const alerts=[];global.frappe={show_alert:value=>alerts.push(value)};
const v=makeView('cost'),calls=[];
const batch={name:'B',batch_no:'B-NO',current_version:'V1',status:'Calculated',review_state:'ready'};
v.batches=[batch];v.findBatch=()=>batch;v.drawerBatchName='B';
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};v.detailState={batchName:'B',tab:'overview',header:batch,requestId:3};
v.replaceViewState=values=>{v.viewState={...v.viewState,...values}};v.loadBatches=async()=>{};
v.recordUsage=()=>{};v.showError=e=>{throw e};
const releaseClassifications=[];v.call=async(method,args)=>{calls.push({method,args});
 if(method.endsWith('get_batches'))return await new Promise(resolve=>{releaseClassifications.push(resolve)});
 if(method.endsWith('confirm_calculation_result'))return {ok:true,confirmed:true,message:'已确认'};
 throw new Error(method)};
const first=v.confirmCalculationResult('B');const second=v.confirmCalculationResult('B');
await new Promise(resolve=>setImmediate(resolve));const before=calls.map(call=>call.method);
releaseClassifications.forEach(release=>release({ok:true,items:[batch],total:1,page:1,page_length:100}));await Promise.all([first,second]);
console.log(JSON.stringify({before,calls:calls.map(call=>call.method),task:v.viewState.task,inflight:v._confirmCalculationInFlight?.size||0}));
""")
    assert len(result['before']) == 1
    assert result['calls'] == [
        'overseas_costing.api.workbench.get_batches',
        'overseas_costing.api.writeback.confirm_calculation_result',
    ]
    assert result['task'] == 'erp'
    assert result['inflight'] == 0


def test_failed_confirmation_releases_inflight_guard_for_retry():
    result = run_js("""
global.frappe={show_alert:()=>{}};
const v=makeView('cost'),calls=[];
const batch={name:'B',batch_no:'B-NO',current_version:'V1',status:'Calculated',review_state:'ready'};
v.batches=[batch];v.findBatch=()=>batch;v.drawerBatchName='B';
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};v.detailState={batchName:'B',tab:'overview',header:batch,requestId:3};
v.recordUsage=()=>{};v.showError=e=>{v.errors=(v.errors||0)+1};
v.call=async method=>{calls.push(method);throw new Error('分类失败')};
await v.confirmCalculationResult('B');await v.confirmCalculationResult('B');
console.log(JSON.stringify({calls,errors:v.errors,inflight:v._confirmCalculationInFlight?.size||0}));
""")
    assert result['calls'] == [
        'overseas_costing.api.workbench.get_batches',
        'overseas_costing.api.workbench.get_batches',
    ]
    assert result['errors'] == 2
    assert result['inflight'] == 0


def test_authoritative_apply_rechecks_navigation_after_list_reload():
    result = run_js("""
const v=makeView('cost'),replacements=[],renders=[];
const batch={name:'B',review_state:'ready'};const processing={name:'B',review_state:'processing'};
v.batches=[batch];v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};
v.detailState={batchName:'B',tab:'overview',header:batch,requestId:5};
v.replaceViewState=values=>{replacements.push(values);v.viewState={...v.viewState,...values}};
v.renderDetailShell=()=>renders.push('render');v.switchDetailTab=async()=>renders.push('tab');
let release;v.loadBatches=()=>new Promise(resolve=>{release=resolve});
const context=v.captureReviewNavigationContext('B');
const running=v.applyAuthoritativeReviewClassification('B',{task:'pending',batch:processing},context);
await new Promise(resolve=>setImmediate(resolve));
v.viewState.task='erp';v.detailState.header={name:'B',marker:'new-navigation'};
release();const applied=await running;
console.log(JSON.stringify({applied,task:v.viewState.task,header:v.detailState.header,renders,replacements}));
""")
    assert result['applied'] is False
    assert result['task'] == 'erp'
    assert result['header'] == {'name': 'B', 'marker': 'new-navigation'}
    assert result['renders'] == []


def test_authoritative_cost_list_placement_starts_review_even_with_processing_state():
    result = run_js("""
const v=makeView('pending'),replacements=[];
const batch={name:'B',review_state:'processing',cost_review_started:true};
v.batches=[batch];v.viewState={task:'pending',screen:'detail',batch:'B',tab:'documents',page:1};
v.detailState={batchName:'B',tab:'documents',header:batch,requestId:2};
v.replaceViewState=values=>{replacements.push(values);v.viewState={...v.viewState,...values}};
v.loadBatches=async()=>{};
const context=v.captureReviewNavigationContext('B');
const applied=await v.applyAuthoritativeReviewClassification('B',{task:'cost',batch},context);
console.log(JSON.stringify({applied,task:v.viewState.task,reviewStatus:v.filters.review_status,replacements}));
""")
    assert result['applied'] is True
    assert result['task'] == 'cost'
    assert result['reviewStatus'] == 'pending'
    assert result['replacements'][-1]['screen'] == 'detail'


def test_confirm_success_after_navigation_does_not_overwrite_new_view():
    result = run_js("""
const alerts=[];global.frappe={show_alert:value=>alerts.push(value)};
const v=makeView('cost'),calls=[],replacements=[],usage=[];
const batch={name:'B',batch_no:'B-NO',current_version:'V1',status:'Calculated',review_state:'ready'};
v.batches=[batch];v.findBatch=()=>batch;v.drawerBatchName='B';
v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};v.detailState={batchName:'B',tab:'overview',header:batch,requestId:1};
v.replaceViewState=values=>{replacements.push(values);v.viewState={...v.viewState,...values}};v.loadBatches=async()=>{};
v.recordUsage=(action,payload)=>usage.push({action,status:payload.status||'Success'});v.showError=e=>{throw e};
let releaseConfirm;v.call=async(method,args)=>{calls.push(method);
 if(method.endsWith('get_batches'))return {ok:true,items:[batch],total:1,page:1,page_length:100};
 if(method.endsWith('confirm_calculation_result'))return await new Promise(resolve=>{releaseConfirm=resolve});
 throw new Error(method)};
const running=v.confirmCalculationResult('B');await new Promise(resolve=>setImmediate(resolve));
v.viewState={...v.viewState,task:'pending',batch:'OTHER'};v.detailState={...v.detailState,batchName:'OTHER',requestId:2};
releaseConfirm({ok:true,confirmed:true,message:'服务端已确认'});await running;
console.log(JSON.stringify({task:v.viewState.task,batch:v.detailState.batchName,replacements,alerts,usage,calls}));
""")
    assert result['task'] == 'pending'
    assert result['batch'] == 'OTHER'
    assert result['replacements'] == []
    assert any('已确认' in alert['message'] for alert in result['alerts'])
    assert result['usage'] == [{'action': 'CONFIRM_RESULT', 'status': 'Success'}]


def test_authoritative_classification_falls_through_to_erp_then_confirmed_scope():
    result = run_js("""
const v=makeView('cost'),calls=[];const batch={name:'B',batch_no:'B-NO',review_state:'confirmed',confirm_status:'Confirmed'};
v.batches=[batch];v.findBatch=()=>batch;v.detailState={header:batch};
let mode='erp';v.call=async(method,args)=>{const filters=JSON.parse(args.filters_json);calls.push({task:args.task,review_status:filters.review_status});
 if(mode==='erp'&&args.task==='erp')return {ok:true,items:[batch],total:1,page:1};
 if(mode==='confirmed'&&args.task==='cost'&&filters.review_status==='confirmed')return {ok:true,items:[batch],total:1,page:1};
 return {ok:true,items:[],total:0,page:1}};
const erp=await v.getAuthoritativeReviewClassification('B');const erpCalls=calls.splice(0);
mode='confirmed';const confirmed=await v.getAuthoritativeReviewClassification('B');
console.log(JSON.stringify({erp,erpCalls,confirmed,confirmedCalls:calls}));
""")
    assert result['erp']['task'] == 'erp'
    assert [call['task'] for call in result['erpCalls']] == ['cost', 'pending', 'erp']
    assert result['confirmed']['task'] == 'confirmed'
    assert [call['task'] for call in result['confirmedCalls']] == ['cost', 'pending', 'erp', 'cost']
    assert result['confirmedCalls'][-1]['review_status'] == 'confirmed'


def test_unknown_authoritative_classification_only_refreshes_current_detail():
    result = run_js("""
const v=makeView('cost'),replacements=[];const batch={name:'B',batch_no:'B-NO',review_state:'ready'};
v.batches=[batch];v.findBatch=()=>batch;v.viewState={task:'cost',screen:'detail',batch:'B',tab:'overview',page:1};
v.detailState={batchName:'B',tab:'overview',header:batch,requestId:4};
v.call=async()=>({ok:true,items:[],total:0,page:1});v.replaceViewState=values=>replacements.push(values);
v.refreshDetailSummary=async()=>{v.refreshed=(v.refreshed||0)+1};v.loadBatches=async()=>{v.loaded=(v.loaded||0)+1};
const found=await v.getAuthoritativeReviewClassification('B');await v.refreshRecalculatedDetailClassification('B');
console.log(JSON.stringify({found,task:v.viewState.task,replacements,refreshed:v.refreshed||0,loaded:v.loaded||0}));
""")
    assert result['found']['task'] == 'unknown'
    assert result['task'] == 'cost'
    assert result['replacements'] == []
    assert result['refreshed'] == 1
    assert result['loaded'] == 0
