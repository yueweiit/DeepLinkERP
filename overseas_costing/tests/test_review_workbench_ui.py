import json
import subprocess
from pathlib import Path

import pytest

PARTS = Path(__file__).resolve().parents[1] / 'page/overseas_cost_workbench/parts'


def run_js(script):
    source = f"""
const fs=require('fs');
global.OverseasCostWorkbenchState=require({json.dumps(str(PARTS / '05-workbench-state.js'))});
const View=Function('return class View {{'+fs.readFileSync({json.dumps(str(PARTS / '35-workbench-view.js'))},'utf8')+fs.readFileSync({json.dumps(str(PARTS / '82-detail-page.js'))},'utf8')+'}}')();
function makeView(task='cost') {{
 const v=new View(); v.viewState={{task,page:1,q:'',screen:'workbench'}};
 v.filters={{review_status:'pending',review_warning:'',issue:''}};
 v.html={{}};v.$root={{find:key=>({{html:value=>{{v.html[key]=value;}},toggleClass:()=>{{}}}})}};
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


def test_cost_cards_and_review_selector_replace_pending_cards():
    html=run_js("const v=makeView();v.renderExceptionSummary();v.renderWorkbenchSearch();console.log(JSON.stringify(v.html));")
    text=''.join(html.values())
    assert '待核对' in text and '已核对' in text
    assert '含暂估' in text and '待补凭证' in text
    assert '采购资料待补' not in text
    assert 'data-workbench-filter="review_status"' in text


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


def test_cost_history_headers_and_empty_state_are_explicit():
    html=run_js("""
global.window={requestAnimationFrame:()=>{}};
const v=makeView();v.batches=[];v.workbenchTotal=0;v.filters.review_status='confirmed';
v.renderWorkbenchBatchList();console.log(JSON.stringify(v.html));
""")
    text=''.join(html.values())
    assert '已核对批次' in text and '核对状态' in text and '确认时间' in text


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
