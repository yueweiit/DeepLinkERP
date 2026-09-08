import json
import subprocess
from pathlib import Path

PARTS = Path(__file__).resolve().parents[1] / 'page/overseas_cost_workbench/parts'


def run_js(script):
    source = f"""
const fs=require('fs');
global.OverseasCostWorkbenchState=require({json.dumps(str(PARTS / '05-workbench-state.js'))});
const View=Function('return class View {{'+fs.readFileSync({json.dumps(str(PARTS / '35-workbench-view.js'))},'utf8')+'}}')();
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
