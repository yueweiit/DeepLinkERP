"""Execute the actual workbench methods in Node, including asynchronous lifecycle guards."""
import json
import subprocess
from pathlib import Path

PARTS = Path(__file__).resolve().parents[1] / 'page/overseas_cost_workbench/parts'


def run_js(body):
    prelude = '''const fs=require('fs');
const Workbench=new Function('return class {'+fs.readFileSync(PART,'utf8')+fs.readFileSync(PART.replace('85-settlement.js','87-freight.js'),'utf8')+'}')();
const w=new Workbench();
w.escape=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const assert=require('assert').strict;
'''.replace('PART', json.dumps(str(PARTS / '85-settlement.js')))
    result = subprocess.run(['node', '-e', prelude + '\n(async()=>{' + body + '})().catch(e=>{console.error(e);process.exit(1)});'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_fees_are_exclusive_of_total_and_zero_and_source_text_are_preserved():
    run_js('''
const html=w.renderSettlementSource({approval_no:'<img src=x onerror=1>',approved:true,amount:'90',currency:'USD',fees:[{label:'运费<script>',amount:'0',currency:'USD'}],goods:[]});
assert(html.includes('0 USD')); assert(!html.includes('90 USD'));
assert(html.includes('&lt;img')); assert(!html.includes('<script>'));
assert(w.settlementAmount({amount:0,currency:'MXN'}).includes('0 MXN'));
assert(w.settlementAmount({amount:null}).includes('未识别'));
''')


def test_freight_dialog_separates_claims_packing_and_bill_total():
    run_js('''
const html=w.renderFreightContent({viewed_version:'v',logistics:{approval_no:'LOG'},freight:{claims:[{id:'c',amount:'2600',currency:'RMB',approval_no:'PAY'}]},packing:{message:'装箱保留待核对'},candidates:[{id:'p',revision:'r',status:'pending',expense:{approval_no:'PAY',amount:'9000',currency:'RMB'},lines:[{id:'line',amount:'2600',currency:'RMB',waybill:'1234567890',evidence:{file_name:'monthly.xlsx',sheet:'DHL',row:2},cargo_text:'Oppo <unsafe>'}],packing_available:true}]});
assert(html.includes('已审批运费'));assert(html.includes('装箱保留待核对'));assert(html.includes('整单合计，仅供核对'));
assert(html.includes('2600 RMB'));assert(html.includes('第 2 行'));assert(html.includes('freight-review'));assert(html.includes('packing-review'));
assert(!html.includes('<unsafe>'));assert(!html.includes('已付款'));
''')


def test_history_distinguishes_eligible_expenses_from_all_read_sources():
    run_js('''
let html=''; w.settlementBody=(s,value)=>html=value;
w.renderSettlementHistory({status:'pending',pages:[]},{job:{status:'running',phase:'load',item_count:800,processed_count:0,excluded_count:622},health:{scope_counts:{logistics:141,expense:37,approved_expense:23,excluded:622}},counts:{},candidates:[]});
assert(html.includes('物流类采购支出 37')); assert(html.includes('审批通过 23'));
assert(html.includes('国际物流 141')); assert(html.includes('不符合分类 622'));
assert(!html.includes('已发现 800')); assert(html.includes('服务类采购 → 物流及运输服务'));
''')


def test_deepseek_second_pass_is_available_after_rules_and_shows_persisted_progress():
    run_js('''
let html='';w.settlementBody=(s,value)=>html=value;
w.renderSettlementHistory({status:'pending',pages:[]},{job:{status:'partial'},ai_job:{id:'ai',status:'completed',total:5,processed:5,recommended:2,no_match:3,failed:0}});
assert(html.includes('DeepSeek 补充匹配'));assert(html.includes('推荐 2'));assert(html.includes('证据不足 3'));
w.renderSettlementHistory({status:'pending',pages:[]},{job:{status:'running'}});
assert(!html.includes('data-settlement-action="ai-match"'));
''')


def test_linked_status_never_implies_calculated_and_invalid_source_cannot_be_final():
    run_js('''
assert(w.settlementAdoption({binding:{application_status:'pending'},expense:{approved:true}}).includes('待采用'));
assert(w.settlementAdoption({binding:{application_status:'applied_pending'},expense:{approved:true}}).includes('待核对'));
assert(w.settlementAdoption({binding:{application_status:'applied'},expense:{approved:true,invalid:true}}).includes('失效'));
assert(!w.settlementAdoption({binding:{application_status:'applied'},expense:{approved:true}}).includes('计算完成'));
''')


def test_selection_submits_identifiers_and_choices_only_and_conflicts_need_reason():
    run_js('''
const c={id:'c1',revision:4,status:'conflict',expense:{amount:300,goods:[{quantity:999}]}};
assert.throws(()=>w.settlementSelection(c,{}));
const result=w.settlementSelection(c,{reason:'核对同一运单',coverage:['freight'],negative_confirmed:true});
assert.deepEqual(result,{id:'c1',revision:4,resolve:true,reason:'核对同一运单',coverage:['freight'],negative_confirmed:true});
assert(!JSON.stringify(result).includes('quantity'));
assert.throws(()=>w.settlementSelection({...c,status:'confirmed'},{}));
''')


def test_closed_history_dialog_ignores_inflight_result_and_does_not_schedule_poll():
    run_js('''
let resolve; let rendered=0; let scheduled=0;
w.settlementApi=()=>new Promise(r=>resolve=r);
w.renderSettlementHistory=()=>rendered++;
global.setTimeout=()=>{scheduled++;return 1};
const state={open:true,request:0,jobId:'j',after:null,status:'pending'};
const request=w.loadSettlementHistory(state);
w.stopSettlementDialog(state);
resolve({ok:true,job:{id:'j',status:'running'},candidates:[]});
await request;
assert.equal(rendered,0); assert.equal(scheduled,0);
''')


def test_history_filter_change_discards_older_response_and_history_has_no_recent_filters():
    run_js('''
const calls=[];const resolvers=[];const rendered=[];
w.settlementApi=(method,args)=>{calls.push({method,args});return new Promise(r=>resolvers.push(r))};
w.renderSettlementHistory=(s,data)=>rendered.push(data.marker);
const state={open:true,request:0,jobId:'j',after:null,status:'pending'};
const a=w.loadSettlementHistory(state); state.status='conflict';const b=w.loadSettlementHistory(state);
resolvers[1]({ok:true,marker:'new',job:{status:'completed'}});await b;
resolvers[0]({ok:true,marker:'old',job:{status:'running'}});await a;
assert.deepEqual(rendered,['new']); assert.equal(calls[1].args.status,'conflict');
assert(!('start' in calls[0].args)); assert(!('limit' in calls[0].args));
''')


def test_cargo_comparison_and_item_review_keep_distinct_source_values():
    run_js('''
const html=w.renderSettlementComparison({goods:[{material_code:'A',quantity:5}]},{goods:[{material_code:'A',quantity:0}]});
assert(html.includes('5'));assert(html.includes('0'));assert(html.includes('存在差异'));
const reviews=w.renderSettlementItemReviews([{item_name:'i',revision:'r',material_code:'A',quantity:0,packing_quantity:5,packing_pending:true}]);
assert(reviews.includes('packing_confirmed'));assert(reviews.includes('装箱数量'));assert(reviews.includes('0'));
''')


CONTROLLER = '''
let active; const calls=[];
w.settlementDialog=(title,fields)=>active={open:true,request:0,fields,dialog:{get_value:key=>key==='settlement_reason'?'核对原单':false}};
w.settlementBody=(s,html)=>s.html=html;
w.settlementActions=(s,html)=>s.actions=html;
w.settlementEvents=(s,handler)=>s.handler=handler;
w.settlementWrite=async(s,fn)=>fn();
w.refreshSettlementBatch=async()=>{};
'''


def test_batch_confirmation_retains_partial_failure_receipt():
    run_js(CONTROLLER + '''
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:false,confirmed_count:1,failed_count:1,results:[{candidate_id:'a',ok:true,application_status:'pending'},{candidate_id:'b',ok:false,message:'版本已变化<script>'}]}};
w.openSettlementCandidateReview([{id:'a',revision:1,status:'pending',expense:{},logistics:{}},{id:'b',revision:2,status:'pending',expense:{},logistics:{}}]);
await active.handler('confirm');
assert.equal(calls[0].method,'confirm_matches');
assert.deepEqual(JSON.parse(calls[0].args.selections).map(x=>[x.id,x.revision]),[['a',1],['b',2]]);
assert(active.html.includes('关联成功 1，失败 1'));assert(active.html.includes('版本已变化&lt;script&gt;'));assert(active.html.includes('成功项已保留'));
''')


def test_correction_reviews_old_and_new_and_passes_both_revisions():
    run_js(CONTROLLER + '''
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,application_status:'pending'}};
w.openSettlementCandidateReview([{id:'new',revision:7,status:'conflict',expense:{approval_no:'NEW'},logistics:{}}],{batchName:'B',correction:{binding:{id:'binding',revision:3},expense:{approval_no:'OLD'}}});
assert(active.html.includes('OLD'));assert(active.html.includes('NEW'));
await active.handler('confirm');
assert.deepEqual(calls[0],{method:'correct_match',args:{batch_name:'B',binding_id:'binding',expected_revision:3,candidate_id:'new',candidate_revision:7,reason:'核对原单'}});
''')


def test_history_start_uses_no_recent_date_limit_or_transport_values():
    run_js('''
let read=0;const calls=[];
w.filters={start_date:'2026-09-01',end_date:'2026-09-09',transport_mode:'SEA',limit:80};
w.settlementBody=()=>{};w.settlementWrite=async(s,fn)=>fn();w.loadSettlementHistory=async()=>read++;
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,job:{id:'history'}}};
const state={open:true,selected:new Set()};await w.startSettlementHistory(state);
assert.deepEqual(calls,[{method:'start_history_matching',args:{}}]);assert.equal(read,1);
''')


def test_manual_search_rejects_missing_reason_without_preparing_a_candidate():
    run_js(CONTROLLER + '''
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,items:[]}};
await w.openSettlementSearch('B');active.dialog.get_value=()=>'';
await assert.rejects(()=>active.handler('choose',{attr:()=> 'expense'}),/人工关联依据/);
assert.deepEqual(calls,[]);
''')


BATCH_CONTROLLER = CONTROLLER + '''
w.detailState={batchName:'B',versionName:'V',tab:'documents'};
const timers=new Map();let timerId=0;
global.setTimeout=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId};
global.clearTimeout=id=>timers.delete(id);
w.settlementNotice=(s,message)=>s.notice=message;
'''


def test_batch_rpc_reads_with_get_and_starts_with_post():
    run_js('''
const calls=[];global.frappe={call:async request=>{calls.push(request);return {message:{ok:true}}}};
w.call=async(method,args)=>{calls.push({method,args});return {ok:true}};
assert.deepEqual(await w.settlementApi('get_batch_settlement',{batch_name:'B',version_name:'V'}),{ok:true});
await w.settlementApi('start_batch_matching',{batch_name:'B',version_name:'V'});
assert.equal(calls[0].type,'GET');assert.equal(calls[1].type,'POST');
assert(calls.every(x=>x.args.batch_name==='B'&&x.args.version_name==='V'));
''')


def test_batch_open_starts_rules_once_and_polls_only_current_ticket():
    run_js(BATCH_CONTROLLER + '''
let status='not_started';
w.settlementApi=async(method,args)=>{calls.push({method,args});
 if(method==='start_batch_matching'){status='running';return {ok:true,matching:{status,stage:'rules',approval_no:'LOG-123'}};}
 return {ok:true,viewed_version:'V',logistics:{approval_no:'LOG-123'},matching:{status,stage:'rules',total:5,processed:1}};
};
await w.openBatchSettlementDialog('B','V');
assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,1);
assert(calls.every(x=>x.args.batch_name==='B'&&x.args.version_name==='V'));
assert.equal(timers.size,1);assert.equal([...timers.values()][0].ms,3000);
assert(active.html.includes('本票匹配'));assert(active.html.includes('LOG-123'));assert(active.html.includes('规则匹配'));
assert(!active.html.includes('一键匹配历史'));assert(!active.html.includes('data-settlement-action="history"'));
await active.handler('refresh');assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,1);
status='completed';const poll=[...timers.values()][0];timers.clear();await poll.fn();
assert.equal(calls.at(-1).method,'get_batch_settlement');assert.equal(timers.size,0);
assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,1);
''')


def test_batch_cached_no_match_and_global_candidates_are_read_without_restarting():
    run_js(BATCH_CONTROLLER + '''
for(const candidates of [[],[{id:'c',revision:1,status:'pending',reason:'同一运单',expense:{approval_no:'EXP'},logistics:{approval_no:'LOG'}}]]){
 calls.length=0;
 w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,logistics:{approval_no:'LOG'},candidates,matching:{status:'completed',stage:'saved',cached:true,no_match:candidates.length?0:4,recommended:candidates.length,finished_at:'2026-09-10T08:00:00Z',message:'已读取本票保存结果'}}};
 await w.openBatchSettlementDialog('B','V');await active.handler('refresh');
 assert(calls.every(x=>x.method==='get_batch_settlement'));assert.equal(timers.size,0);
 assert(active.html.includes('2026-09-10T08:00:00Z'));assert(active.html.includes('已读取本票保存结果'));
 assert(active.html.includes(candidates.length?'同一运单':'未找到可靠匹配'));
 w.stopSettlementDialog(active);
}
''')


def test_failed_and_partial_batch_jobs_wait_for_explicit_ticket_retry():
    run_js(BATCH_CONTROLLER + '''
for(const initial of ['failed','partial']){
 calls.length=0;let status=initial;
 w.settlementApi=async(method,args)=>{calls.push({method,args});if(method==='start_batch_matching')status='running';return {ok:true,logistics:{approval_no:'LOG'},matching:{status,stage:'deepseek',error:'模型错误<script>',failed:2}}};
 await w.openBatchSettlementDialog('B','V');await active.handler('refresh');
 assert(calls.every(x=>x.method==='get_batch_settlement'));assert.equal(timers.size,0);
 assert(active.html.includes('本票重试'));assert(active.html.includes('模型错误&lt;script&gt;'));assert(!active.html.includes('<script>'));
 await active.handler('retry-matching');
 assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,1);
 assert(active.html.includes('DeepSeek'));assert.equal(timers.size,1);w.stopSettlementDialog(active);
}
''')


def test_automatic_batch_matching_is_decided_once_per_opening_even_when_status_changes():
    run_js(BATCH_CONTROLLER + '''
for(const initial of ['completed','partial','failed','stale']){
 calls.length=0;let status=initial;
 w.settlementApi=async(method,args)=>{calls.push({method,args});if(method==='start_batch_matching')status='completed';return {ok:true,matching:{status}}};
 await w.openBatchSettlementDialog('B','V');
 assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,initial==='stale'?1:0);
 status='stale';await active.handler('refresh');
 assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,initial==='stale'?1:0);
 assert(active.html.includes('本票重试'));w.stopSettlementDialog(active);
}
''')


def test_start_failure_keeps_ticket_retry_without_automatic_resubmission():
    run_js(BATCH_CONTROLLER + '''
const actualWrite=Workbench.prototype.settlementWrite;
w.settlementWrite=(state,action)=>{state.dialog.$wrapper={find:()=>({prop:()=>{}})};return actualWrite.call(w,state,action)};
w.settlementApi=async(method,args)=>{calls.push({method,args});if(method==='start_batch_matching')throw Error('连接中断');return {ok:true,matching:{status:'not_started'}}};
await w.openBatchSettlementDialog('B','V');
assert(active.html.includes('连接中断'));assert(active.html.includes('本票重试'));assert.equal(active.busy,false);
await active.handler('refresh');assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,1);
await active.handler('retry-matching');assert.equal(calls.filter(x=>x.method==='start_batch_matching').length,2);
assert.equal(timers.size,0);
''')


def test_bound_and_historical_batch_never_auto_match_or_offer_retry():
    run_js(BATCH_CONTROLLER + '''
for(const data of [{binding:{},expense:{approval_no:'BOUND'},matching:{status:'not_started'}},{historical:true,matching:{status:'stale'}}]){
 calls.length=0;w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,...data}};
 await w.openBatchSettlementDialog('B','V');
 assert.deepEqual(calls.map(x=>x.method),['get_batch_settlement']);assert.equal(timers.size,0);
 assert(!active.html.includes('data-settlement-action="retry-matching"'));
 if(data.binding)assert(active.html.includes('BOUND'));
 if(data.historical)await assert.rejects(()=>active.handler('retry-matching'),/历史版本/);
 w.stopSettlementDialog(active);
}
''')


def test_closed_or_navigated_batch_result_cannot_start_or_schedule_matching():
    run_js(BATCH_CONTROLLER + '''
for(const change of ['close','version','batch']){
 w.detailState={batchName:'B',versionName:'V',tab:'documents'};calls.length=0;let resolve;
 w.settlementApi=(method,args)=>{calls.push({method,args});return new Promise(r=>resolve=r)};
 const pending=w.openBatchSettlementDialog('B','V');
 if(change==='close')w.stopSettlementDialog(active);else if(change==='version')w.detailState.versionName='V2';else w.detailState.batchName='OTHER';
 resolve({ok:true,logistics:{approval_no:'WRONG'},matching:{status:'not_started'}});await pending;
 assert.deepEqual(calls.map(x=>x.method),['get_batch_settlement']);assert.equal(timers.size,0);assert(!active.html);
}
''')


def test_batch_latest_read_wins_and_late_start_after_close_has_no_poll():
    run_js(BATCH_CONTROLLER + '''
const resolvers=[];w.settlementApi=(method,args)=>{calls.push({method,args});return new Promise(r=>resolvers.push(r))};
const opening=w.openBatchSettlementDialog('B','V');const refresh=active.handler('refresh');
resolvers[1]({ok:true,matching:{status:'completed',message:'NEW'}});await refresh;
resolvers[0]({ok:true,matching:{status:'not_started',message:'OLD'}});await opening;
assert(active.html.includes('NEW'));assert(!active.html.includes('OLD'));assert.equal(calls.length,2);
w.stopSettlementDialog(active);calls.length=0;resolvers.length=0;
const next=w.openBatchSettlementDialog('B','V');resolvers[0]({ok:true,matching:{status:'not_started'}});
await new Promise(r=>setImmediate(r));assert.equal(calls[1].method,'start_batch_matching');
w.stopSettlementDialog(active);resolvers[1]({ok:true,matching:{status:'running',stage:'rules'}});await next;
assert.equal(calls.length,2);assert.equal(timers.size,0);
''')


def test_batch_review_confirmation_carries_fixed_batch_and_version_context():
    run_js(BATCH_CONTROLLER + '''
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,viewed_version:'V',logistics:{approval_no:'LOG'},matching:{status:'completed'},candidates:[{id:'C',revision:4,status:'pending',expense:{approval_no:'E'},logistics:{approval_no:'LOG'}}]}};
await w.openBatchSettlementDialog('B','V');await active.handler('candidate',{attr:()=> 'C'});
await active.handler('confirm');const confirmation=calls.find(x=>x.method==='confirm_matches');
assert.equal(confirmation.args.batch_name,'B');assert.equal(confirmation.args.version_name,'V');
assert.deepEqual(JSON.parse(confirmation.args.selections).map(x=>x.id),['C']);
''')


def test_manual_batch_search_stays_empty_until_query_and_keeps_target_and_version():
    run_js(BATCH_CONTROLLER + '''
const values={settlement_query:'',settlement_reason:'核对本票运单'};let review;
w.settlementApi=async(method,args)=>{calls.push({method,args});return method==='prepare_manual_candidate'?{ok:true,candidate:{id:'C'}}:{ok:true,items:[{id:'E',approval_no:'EXP'}]}};
w.openSettlementCandidateReview=(candidates,context)=>review={candidates,context};
await w.openSettlementSearch('B',null,null,{versionName:'V',logistics:{approval_no:'LOG-123'}});
active.dialog.get_value=key=>values[key];assert.equal(calls.length,0);
assert(active.html.includes('LOG-123'));assert(active.html.includes('请输入'));assert(active.html.includes('本票'));
await active.handler('search');assert.equal(calls.length,0);
values.settlement_query='运单 A';await active.handler('search');
assert.deepEqual(calls[0],{method:'find_expenses',args:{batch_name:'B',query:'运单 A',after:null}});
assert(active.html.includes('LOG-123'));assert(active.html.includes('EXP'));
await active.handler('choose',{attr:()=> 'E'});
assert.equal(review.context.batchName,'B');assert.equal(review.context.versionName,'V');
assert.equal(calls.at(-1).args.reason,'核对本票运单');
''')


def test_global_history_scope_accepts_purchase_names_and_parent_aliases():
    run_js('''
let html='';w.settlementBody=(s,value)=>html=value;
w.renderSettlementHistory({status:'pending',pages:[]},{job:{},candidates:[]});
assert(html.includes('所有名称含'));assert(html.includes('父级'));assert(html.includes('别名'));
assert(html.includes('物流及运输服务'));assert(html.includes('已拒绝'));assert(html.includes('已撤销'));assert(html.includes('已删除'));
assert(!html.includes('采购支出＝服务类采购'));
''')


def test_all_built_assets_match_and_complete_javascript_parses():
    page = PARTS.parent
    deployed = page.parents[1] / 'overseas_costing/page/overseas_cost_workbench'
    for suffix in ('js', 'css'):
        name = f'overseas_cost_workbench.{suffix}'
        assert (page / name).read_bytes() == (deployed / name).read_bytes()
    javascript = page / 'overseas_cost_workbench.js'
    assert (PARTS / '85-settlement.js').read_text() in javascript.read_text()
    subprocess.run(['node', '--check', str(javascript)], check=True, capture_output=True, text=True)


def test_adoption_refresh_follows_current_adjustment_version_and_respects_batch_navigation():
    run_js('''
const calls=[];w.detailState={batchName:'B',tab:'documents',versionName:'old-confirmed'};
w.openBatchDetail=async(...args)=>calls.push(args);
w.markBatchDirty=()=>{};
await w.refreshSettlementBatch('B');
assert.deepEqual(calls,[['B','documents',{updateUrl:false,propagateError:true}]]);
w.detailState.batchName='OTHER';await w.refreshSettlementBatch('B');assert.equal(calls.length,1);
''')


def test_item_verification_submits_checked_flags_and_server_hash_only():
    run_js(CONTROLLER + '''
global.$=node=>({attr:()=>node});
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,application_status:'applied_pending'}};
const data={binding:{revision:9},item_reviews:[{item_name:'line',revision:'currenthash',quantity:15,goods_value:800,packing_pending:true,goods_value_pending:true}]};
w.openSettlementItemReview('B',data,async()=>{});
active.dialog.fields_dict={settlement_body:{$wrapper:{find:()=>({each:fn=>fn(0,'packing_confirmed')})}}};
await active.handler('verify');
assert.equal(calls[0].method,'resolve_item_checks');
assert.deepEqual(JSON.parse(calls[0].args.selections),[{item_name:'line',expected_item_hash:'currenthash',packing_confirmed:true}]);
assert.equal(calls[0].args.expected_revision,9);
''')


def test_historical_adoption_shows_frozen_source_and_no_write_actions():
    run_js(CONTROLLER + '''
const data={historical:true,binding:{application_status:'historical',version:'old'},expense:{approval_no:'OLD',amount:0,currency:'MXN',approved:true},logistics:{},item_reviews:[{packing_pending:true}]};
w.renderBatchSettlementDialog({},data);
assert(w.settlementAdoption(data).includes('历史采用来源'));
const state={};w.renderBatchSettlementDialog(state,data);
assert(state.html.includes('OLD'));assert(state.html.includes('0 MXN'));
for(const action of ['correct','apply','items','search','history'])assert(!state.html.includes('data-settlement-action="'+action+'"'));
''')


def test_negative_acknowledgement_is_bound_to_reviewed_snapshot_and_version():
    run_js(CONTROLLER + '''
w.settlementApi=async(method,args)=>{calls.push({method,args});return {ok:true,application_status:'pending'}};
w.openSettlementApplicationReview('B',{binding:{revision:2},viewed_version:'v1',expense:{amount:-10,coverage:'unknown',snapshot:'minus-ten'}},async()=>{});
active.dialog.get_value=key=>key==='negative_confirmed'||key==='coverage_freight';
await active.handler('apply');
assert.equal(calls[0].args.expected_snapshot,'minus-ten');assert.equal(calls[0].args.expected_version,'v1');
assert.equal(calls[0].args.negative_confirmed,true);assert(!('amount' in calls[0].args));
''')


def test_oa_archive_cards_are_read_only_and_manual_cards_keep_existing_controls():
    manual = json.dumps(str(PARTS / '65-manual-documents.js'))
    run_js('''
const Manual=new Function('return class {'+fs.readFileSync(MANUAL,'utf8')+'}')();
const m=new Manual();m.escape=w.escape;
const plan=[{code:'sea_packing_list',label:'装箱单',attachmentType:'Packing List'}];
const archive={name:'a',source_type:'OA',file_url:'/private/files/packing.xlsx',file_name:'packing.xlsx'};
const html=m.renderManualDocumentCards(plan,{sea_packing_list:archive},'SEA',{});
assert(html.includes('preview-manual-document'));
for(const action of ['delete-manual-document','upload-manual-document','manual-fill-gap','open-dingtalk-packing-picker'])assert(!html.includes('data-action="'+action+'"'));
assert(m.renderManualDocumentCards(plan,{sea_packing_list:{...archive,source_type:'Manual'}},'SEA',{}).includes('delete-manual-document'));
assert(m.renderManualDocumentCards(plan,{sea_packing_list:{...archive,source_type:'Manual'}},'SEA',{}).includes('open-packing-flow'));
'''.replace('MANUAL', manual))


def test_health_keeps_local_and_upstream_freshness_distinct_and_missing_unknown():
    run_js('''
assert(w.renderSettlementHealth({}).includes('未知／未同步'));
const html=w.renderSettlementHealth({sync:{last_success:'LOCAL'},health:{health:{last_success_at:'UPSTREAM',pending_count:0,retry_count:2,manual_required_count:1,last_error:'<script>'}},pending_failure_count:3,control:{enabled:false}});
assert(html.includes('本地同步：LOCAL'));assert(html.includes('上游归档最近成功：UPSTREAM'));assert(html.includes('待归档 0'));assert(html.includes('未解决任务失败 3'));assert(html.includes('后台同步已暂停'));assert(!html.includes('<script>'));
''')


def test_packing_ack_shows_preserved_and_candidate_values_before_confirmation():
    run_js('''
const html=w.renderSettlementItemReviews([{item_name:'i',quantity:4,packing_pending:true,packing_candidates:[{document_id:'<doc>',reason:'冲突',line:2,conflicts:[{field:'gross_weight_kg',existing:8,candidate:0}]}]}]);
assert(html.includes('现有 8 → 归档候选 0'));assert(html.includes('毛重 kg'));assert(html.includes('&lt;doc&gt;'));
''')


def test_unidentified_goods_and_amount_are_not_described_as_matched_or_usable():
    run_js('''
const html=w.renderSettlementComparison({goods:[]},{goods:[]});
assert(!html.includes('识别字段一致'));assert(html.includes('尚未识别'));
assert(!w.renderSettlementSource({amount:null}).includes('使用总额'));
''')


def test_existing_coverage_can_be_reviewed_even_when_new_source_has_known_scope():
    run_js('''
const fields=w.settlementChoiceFields({coverage:'freight',amount:100},['freight','customs']);
assert(fields.some(f=>f.fieldname==='coverage_customs'&&f.default===1));
assert(fields.some(f=>f.fieldname==='coverage_freight'));
''')


WORKSPACE_METHODS = '''
const Workspace=new Function('return class {'+fs.readFileSync(WORKSPACE,'utf8')+'}')();
for (const name of Object.getOwnPropertyNames(Workspace.prototype)) if(name!=='constructor') w[name]=Workspace.prototype[name];
'''.replace('WORKSPACE', json.dumps(str(PARTS / '78-material-fee-workspace.js')))


def test_current_inline_workspace_retains_material_fee_and_packing_controls_with_settlement_strip():
    run_js(WORKSPACE_METHODS + '''
const state={batchName:'B',materials:{},fees:{summary:{}},preview:{}};
w.ensureMaterialFeeState=()=>state;w.detailState={batchName:'B',versionName:'V',tab:'documents'};
let html='';let loaded;
w.$root={find:()=>({html:value=>html=value})};w.closeMaterialAICandidatePopover=()=>{};
w.renderMaterialAIProgressChip=()=>'';w.renderMaterialFeeGrid=()=>'<table data-current-material-grid></table>';
w.renderMaterialFeeTable=()=>'<table data-current-fee-table></table>';w.renderMaterialFeeCostTable=()=>'<section data-current-cost-result></section>';
w.renderMaterialFeeTodos=()=>'';w.bindMaterialGridScrollControls=()=>{};w.restoreMaterialFeeInputFocus=()=>{};
w.loadSettlementStrip=(batch)=>loaded=batch;
w.renderMaterialFeeWorkspace();
assert(html.includes('data-area="settlement-strip"'));
assert(html.indexOf('ocw-mf-page-head')<html.indexOf('data-area="settlement-strip"'));
assert(html.indexOf('data-area="settlement-strip"')<html.indexOf('ocw-mf-material-section'));
for(const marker of ['data-current-material-grid','data-current-fee-table','data-current-cost-result','mf-import-wiki','mf-ai-fill','mf-show-sources'])assert(html.includes(marker));
assert.equal(loaded,'B');assert(!html.includes('manual-documents'));
''')


def test_archive_evidence_uses_current_sources_dialog_and_ignores_late_closed_response():
    run_js(WORKSPACE_METHODS + '''
const state={batchName:'B',fees:{evidence_candidates:[{attachment:'manual',file_name:'manual.xlsx'}]}};
w.ensureMaterialFeeState=()=>state;w.detailState={batchName:'B',versionName:'V',tab:'documents'};
const calls=[];let resolve;let sourceHtml='';let active;
w.call=(method,args)=>{calls.push({method,args});return new Promise(r=>resolve=r)};
global.frappe={ui:{Dialog:class {constructor(options){this.options=options;this.fields_dict={sources:{$wrapper:{html:html=>sourceHtml=html}}};this.$wrapper={addClass:()=>{},on:()=>{}};active=this;}show(){}hide(){this.onhide?.();}}}};
w.openMaterialFeeSourcesDialog();
assert.equal(calls.length,1);assert.equal(calls[0].method,'overseas_costing.api.packing_api.list_current_source_documents');
assert.equal(calls[0].args.version_name,'V');
active.hide();resolve({ok:true,items:[{name:'oa',source_type:'OA',file_name:'<archived>',file_url:'/private/files/a.xlsx'}]});
await new Promise(r=>setImmediate(r));assert.equal(sourceHtml,'');
w.materialFeeState=state;w.openMaterialFeeSourcesDialog();
resolve({ok:true,source_context:{root_kind:'expense'},items:[{source_label:'当前支出正文',available:true}],historical_items:[{name:'oa',file_name:'<archived>',file_url:'/private/files/a.xlsx'}]});
await new Promise(r=>setImmediate(r));
assert(!sourceHtml.includes('manual.xlsx'));assert(sourceHtml.includes('&lt;archived&gt;'));assert(sourceHtml.includes('历史留存，不参与当前核算与 AI'));assert(sourceHtml.includes('当前资料来源：采购支出'));
assert(sourceHtml.includes('data-mf-preview-source'));assert(!sourceHtml.includes('delete-manual-document'));
''')


def test_settlement_quantity_is_readonly_and_distinct_from_original_packing_values():
    run_js(WORKSPACE_METHODS + '''
w.materialFeeState={};w.materialAICell=()=>null;w.renderMaterialAICandidates=()=>'';w.formatValue=x=>String(x);
const item={name:'A',actual_shipped_qty:4,shipped_uom:'箱',effective_shipping_quantity:6,effective_shipping_uom:'件',settlement_cargo:{quantity:6,unit:'件'}};
const quantity=w.renderMaterialFeeGridCell(item,{field:'actual_shipped_qty',label:'发货数量'},new Set(),1);
const unit=w.renderMaterialFeeGridCell(item,{field:'shipped_uom',label:'发货单位'},new Set(),2);
assert(quantity.includes('采购支出采用'));assert(quantity.includes('6'));assert(quantity.includes('装箱原值 4 箱'));
assert(!quantity.includes('<input'));assert(!unit.includes('<input'));assert(unit.includes('件'));
assert(w.renderMaterialFeeGridCell({...item,settlement_cargo:null},{field:'actual_shipped_qty',label:'发货数量'},new Set(),1).includes('<input'));
''')


def test_detail_entry_uses_production_inline_workspace_and_history_entry_stays_in_pull_dialog():
    detail = (PARTS / '82-detail-page.js').read_text()
    documents = detail.split('  async renderDocumentsDetailTab() {', 1)[1].split('\n  }', 1)[0]
    assert 'loadMaterialFeeWorkspace' in documents
    assert 'renderManualDocumentPanel' not in documents
    pull = (PARTS / '50-import-category.js').read_text()
    assert 'data-action="settlement-history"' in pull
    assert 'this.openSettlementHistory(start)' in pull


def test_final_source_fee_row_is_readonly_while_ordinary_fee_remains_editable():
    run_js(WORKSPACE_METHODS + '''
w.materialFeeState={preview:{included_fees:[{fee_key:'final'}]}};w.materialFeeSavedCostPreview=()=>null;w.formatMoney=x=>String(x);
const fee={logical_fee_key:'final',source_binding_id:'binding',source_label:'银行支付流程',is_final:1,amount_state:'ACTUAL',currency:'RMB',amount:0,allocation_basis:'volume',allocation:{basis:'gross_weight'}};
const html=w.renderMaterialFeeRow(fee);
assert(!html.includes('<input'));assert(!html.includes('<select'));assert(!html.includes('mf-edit-fee'));
assert(html.includes('RMB 0'));assert(html.includes('银行支付流程'));assert(!html.includes('物流采购支出'));assert(html.includes('mf-view-settlement-source'));
for(const action of ['amount','replace','revoke'])assert(html.includes(`data-mf-freight-action="${action}"`));
assert(html.includes('分摊'));assert(html.includes('毛重'));
assert(w.renderMaterialFeeRow({...fee,source_binding_id:null,is_final:0}).includes('data-mf-fee-amount'));
''')
