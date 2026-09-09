"""Execute the actual workbench methods in Node, including asynchronous lifecycle guards."""
import json
import subprocess
from pathlib import Path

PARTS = Path(__file__).resolve().parents[1] / 'page/overseas_cost_workbench/parts'


def run_js(body):
    prelude = '''const fs=require('fs');
const Workbench=new Function('return class {'+fs.readFileSync(PART,'utf8')+'}')();
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
assert.deepEqual(calls.map(x=>x.method),['find_expenses']);
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
assert.deepEqual(calls,[['B','documents',{updateUrl:false}]]);
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
