"""AI request failures stay actionable inside the existing progress dialog."""
import json
import re

import pytest

from overseas_costing.tests.test_workbench_frontend_state import PARTS, _fee_workspace_result


FIXTURE = f"""
const helperSource=fs.readFileSync({json.dumps(str(PARTS / '110-helpers.js'))},'utf8').trim().replace(/}}$/, '');
const importSource=fs.readFileSync({json.dumps(str(PARTS / '50-import-category.js'))},'utf8');
const serverMethod=importSource.slice(importSource.indexOf('  extractServerMessage('),importSource.indexOf('  fileNameFromRef('));
const Helpers=Function('return class Helpers {{'+helperSource+serverMethod+'}}')();
for(const name of ['extractStructuredError','normalizeErrorMessage','extractReadableError','extractServerMessage'])Harness.prototype[name]=Helpers.prototype[name];
const workspace=new Harness();
workspace.detailState={{batchName:'B1',versionName:'V1',tab:'documents'}};
const state=workspace.ensureMaterialFeeState();
workspace.escape=(value)=>String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
let opens=0,updates=0,globalErrors=0;
workspace.openMaterialAIProgressDialog=()=>{{opens++}};
workspace.updateMaterialAIProgressSurface=()=>{{updates++}};
workspace.showError=()=>{{globalErrors++}};
workspace.showMaterialAIReadyDraft=()=>{{}};
global.window={{setTimeout:(resolve)=>resolve()}};
"""

ERROR = {
    'ok': False, 'code': 'SOURCE_SCOPE_MISMATCH', 'message': '资料与当前批次不一致',
    'error': {'code': 'SOURCE_SCOPE_MISMATCH', 'reason': '资料与当前批次不一致',
              'stage': '读取资料', 'scope': '批次 B1', 'source_id': 'S1',
              'approval_no': 'OA-1', 'source_label': '采购附件',
              'next_action': '请重新绑定资料后重试', 'retryable': False},
    'retryable': False,
}


@pytest.mark.parametrize('expression, expected', [
    (json.dumps(ERROR, ensure_ascii=False), '资料与当前批次不一致'),
    ("({responseJSON:{_server_messages:JSON.stringify([JSON.stringify({message:'审批附件无法读取'})])}})", '审批附件无法读取'),
    ("({message:{error:{reason:'装箱来源不匹配',next_action:'重新选择来源'}}})", '装箱来源不匹配'),
    ("({responseJSON:{message:{ok:false,message:'启动暂时失败',trace_id:'trace-42'}}})", '启动暂时失败'),
    ("({unexpected:{field:'value'}})", '可读的默认提示'),
])
def test_ai_errors_use_readable_messages_without_object_serialization(expression, expected):
    result = _fee_workspace_result(FIXTURE + f"""
console.log(JSON.stringify({{message:workspace.materialAIErrorMessage({expression},'可读的默认提示')}}));
""")
    assert expected in result['message']
    assert '[object Object]' not in result['message']
    assert not result['message'].startswith('{')


@pytest.mark.parametrize('rejected', [False, True])
def test_business_start_failure_stops_once_and_preserves_source_choice_and_clarification(rejected):
    result = _fee_workspace_result(FIXTURE + f"const failure={json.dumps(ERROR, ensure_ascii=False)};" + f"const rejected={str(rejected).lower()};" + r"""
state.aiClarification='两款为一套';state.aiClarificationRevision=3;state.aiClarificationLoaded=true;
state.aiFill={status:'FAILED',source_progress:[{source_id:'S1',label:'采购附件',selected:true}]};
let calls=0;workspace.call=async()=>{calls++;if(rejected)throw {responseJSON:{message:failure}};return failure};
await workspace.startMaterialAIFill({force:true,selectedSourceIds:['S1']});
console.log(JSON.stringify({calls,globalErrors,fill:state.aiFill,note:state.aiClarification,
 html:workspace.renderMaterialAIProgressDialogContent()}));
""")
    assert result['calls'] == 1 and result['globalErrors'] == 0
    assert result['note'] == '两款为一套'
    assert result['fill']['source_progress'][0]['selected'] is True
    for text in ('资料与当前批次不一致', '读取资料', '批次 B1', '采购附件', 'OA-1', '请重新绑定资料后重试'):
        assert text in result['html']
    assert '[object Object]' not in result['html']


def test_start_only_retries_transient_transport_failures_at_most_three_attempts():
    result = _fee_workspace_result(FIXTURE + r"""
const requests=[];workspace.call=async(method,args,freeze,options)=>{requests.push({method,args,freeze,options});throw {status:503,statusText:'Service Unavailable'}};
await workspace.startMaterialAIFill({force:true,selectedSourceIds:['S1']});
console.log(JSON.stringify({requests,globalErrors,status:state.aiFill.status}));
""")
    assert len(result['requests']) == 3
    assert result['globalErrors'] == 0 and result['status'] == 'FAILED'
    assert all(request['args']['selected_source_ids_json'] == '["S1"]' for request in result['requests'])
    assert all(request['options']['inlineErrors'] for request in result['requests'])


def test_status_fetch_stops_after_three_failures_and_retry_resumes_existing_run():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiFill={status:'RUNNING',runId:'R1',progress_revision:8,source_progress:[{source_id:'S1',selected:true}]};
const requests=[];workspace.call=async(method,args)=>{requests.push({method,args});throw {status:0,statusText:'error'}};
await workspace.pollMaterialAIFill(state,'B1','V1','R1');
const stopped={calls:requests.length,runId:state.aiFill.runId,status:state.aiFill.status,polling:state.aiFill.polling};
workspace.call=async(method,args)=>{requests.push({method,args});return {ok:true,status:'READY',run_id:'R1',progress_revision:9}};
if(workspace.retryMaterialAIProgress)await workspace.retryMaterialAIProgress();
console.log(JSON.stringify({stopped,requests,runId:state.aiFill.runId,status:state.aiFill.status,globalErrors}));
""")
    assert result['stopped'] == {'calls': 3, 'runId': 'R1', 'status': 'RUNNING', 'polling': False}
    assert result['runId'] == 'R1' and result['status'] == 'READY'
    assert len(result['requests']) == 4
    assert all(row['method'].endswith('get_source_ai_review_status') for row in result['requests'])
    assert result['requests'][-1]['args']['after_revision'] == 8
    assert result['globalErrors'] == 0


def test_status_business_error_stops_immediately_and_unchanged_success_resets_failure_count():
    result = _fee_workspace_result(FIXTURE + f"const failure={json.dumps(ERROR, ensure_ascii=False)};" + r"""
state.aiFill={status:'RUNNING',runId:'R1'};
let calls=0;workspace.call=async()=>{calls++;return failure};
await workspace.pollMaterialAIFill(state,'B1','V1','R1');
const business={calls,html:workspace.renderMaterialAIProgressDialogContent(),runId:state.aiFill.runId};
let next=0;workspace.call=async()=>{next++;if(next===3)return {ok:true,unchanged:true};if(next===6)return {ok:true,status:'READY'};throw new Error('network down')};
await workspace.pollMaterialAIFill(state,'B1','V1','R1');
console.log(JSON.stringify({business,next,status:state.aiFill.status,warning:state.aiFill.connection_error||''}));
""")
    assert result['business']['calls'] == 1 and result['business']['runId'] == 'R1'
    assert '请重新绑定资料后重试' in result['business']['html']
    assert result['next'] == 6 and result['status'] == 'READY' and result['warning'] == ''


def test_actual_failed_run_retry_creates_new_run_preserving_previous_selected_sources():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiFill={status:'FAILED',runId:'OLD',source_progress:[{source_id:'S1',selected:true}]};
state.aiStartOptions={force:true,selectedSourceIds:['S1']};
workspace.pollMaterialAIFill=async()=>{};
const requests=[];workspace.call=async(method,args)=>{requests.push({method,args});return {ok:true,run_id:'NEW',status:'QUEUED'}};
if(workspace.retryMaterialAIProgress)await workspace.retryMaterialAIProgress();
console.log(JSON.stringify({requests,runId:state.aiFill.runId}));
""")
    assert len(result['requests']) == 1 and result['requests'][0]['method'].endswith('start_source_ai_review')
    assert result['requests'][0]['args']['selected_source_ids_json'] == '["S1"]'
    assert result['runId'] == 'NEW'


def test_source_restrictions_are_visible_and_unusable_sources_cannot_be_selected_for_rerun():
    result = _fee_workspace_result(FIXTURE + r"""
const excluded={source_id:'bad',selected:true,selectable:true,analysis_allowed:false,adoption_allowed:false,
 read_status:'EXCLUDED',label:'外部附件',analysis_reason:'附件不属于当前批次'};
const analysisOnly={source_id:'read',selected:true,analysis_allowed:true,adoption_allowed:false,
 read_status:'READ',label:'草稿审批',adoption_restriction:'审批通过后才能采用'};
state.aiFill={status:'READY',source_progress:[excluded,analysisOnly]};
const review=workspace.renderMaterialAIReviewSources(state.aiFill);
const progress=workspace.renderMaterialAIProgressSourceRow(analysisOnly,1);
let selected;workspace.startMaterialAIFill=async(options)=>{selected=options.selectedSourceIds};
await workspace.restartMaterialAIWithSources({$wrapper:{removeClass(){}}});
console.log(JSON.stringify({review,progress,selected}));
""")
    assert '附件不属于当前批次' in result['review']
    assert re.search(r'value="bad"[^>]*disabled', result['review'])
    assert '审批通过后才能采用' in result['review'] and '审批通过后才能采用' in result['progress']
    assert result['selected'] == ['read']


def test_material_scrollbar_has_sixteen_pixel_visible_thumb_and_single_track():
    css = (PARTS / '48-material-fee-workspace.css').read_text(encoding='utf-8')
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    rules = {selector.strip(): body for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css)}
    outer = rules['.ocw-mf-grid-scrollbar']
    assert re.search(r'height:\s*24px', outer)
    assert 'overflow-x: scroll' in outer
    assert re.search(r'height:\s*20px\s*!important', rules['.ocw-mf-grid-scrollbar::-webkit-scrollbar'])
    thumb = rules['.ocw-mf-grid-scrollbar::-webkit-scrollbar-thumb']
    assert 'border: 2px solid' in thumb
    assert '#78bdf0' not in thumb
    assert 'display: none' in rules['.ocw-mf-grid-scroll::-webkit-scrollbar']


@pytest.mark.parametrize('method', ['start_source_ai_review', 'get_source_ai_review_status'])
def test_inline_ai_transport_uses_local_ajax_and_preserves_failure_response(method):
    result = _fee_workspace_result(FIXTURE + f"const method='overseas_costing.api.materials.{method}';" + f"""
const callSource=fs.readFileSync({json.dumps(str(PARTS / '20-data-filters.js'))},'utf8').split('  async loadBatches(')[0];
workspace.call=Function('return class Api {{'+callSource+'}}')().prototype.call;
""" + r"""
let request,normal=0;frappe.csrf_token='csrf-test';frappe.call=async()=>{normal++;return {message:{ok:true}}};
const failure={status:403,responseJSON:{message:'没有读取当前批次的权限'}};
global.$={ajax:async(options)=>{request=options;throw failure}};
let caught;try{await workspace.call(method,{batch_name:'B1'},false,{inlineErrors:true})}catch(error){caught=error===failure}
console.log(JSON.stringify({normal,request,caught}));
""")
    assert result['normal'] == 0 and result['caught']
    assert result['request']['url'] == '/api/method/overseas_costing.api.materials.' + method
    assert result['request']['type'] == 'POST'
    assert result['request']['data'] == {'batch_name': 'B1'}
    assert result['request']['headers']['X-Frappe-CSRF-Token'] == 'csrf-test'
    assert result['request']['headers']['Accept'] == 'application/json'


def test_other_calls_keep_frappe_transport_even_if_inline_option_is_supplied():
    result = _fee_workspace_result(FIXTURE + f"""
const callSource=fs.readFileSync({json.dumps(str(PARTS / '20-data-filters.js'))},'utf8').split('  async loadBatches(')[0];
workspace.call=Function('return class Api {{'+callSource+'}}')().prototype.call;
""" + r"""
const calls=[];frappe.call=async(options)=>{calls.push(options);return {message:{value:42}}};
global.$={ajax:async()=>{throw new Error('unrelated calls must retain Frappe transport')}};
const a=await workspace.call('overseas_costing.api.materials.get_material_grid',{batch_name:'B1'},true,{inlineErrors:true});
const b=await workspace.call('overseas_costing.api.materials.start_source_ai_review',{},false);
console.log(JSON.stringify({calls,a,b}));
""")
    assert result['a'] == result['b'] == {'value': 42}
    assert result['calls'][0]['freeze'] is True and result['calls'][1]['freeze'] is False


@pytest.mark.parametrize('status, message', [(401, '登录'), (403, '权限'), (0, '网络'), (504, '服务')])
def test_transport_errors_have_readable_inline_recovery_message(status, message):
    result = _fee_workspace_result(FIXTURE + f"""
const error={{status:{status},statusText:'error'}};
console.log(JSON.stringify({{message:workspace.materialAIErrorMessage(error),retryable:workspace.materialAIRequestRetryable(error)}}));
""")
    assert message in result['message']
    assert result['retryable'] is (status in (0, 504))


def test_unusable_sources_cannot_be_sent_in_explicit_start_selection():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiFill={status:'FAILED',source_progress:[{source_id:'bad',selected:true,analysis_allowed:false},{source_id:'read',selected:true,analysis_allowed:true}]};
workspace.pollMaterialAIFill=async()=>{};
let sent;workspace.call=async(_method,args)=>{sent=args.selected_source_ids_json;return {ok:true,run_id:'R1',status:'QUEUED'}};
await workspace.startMaterialAIFill({selectedSourceIds:['bad','read']});
console.log(JSON.stringify({sent}));
""")
    assert result['sent'] == '["read"]'


def test_workspace_refresh_does_not_restart_paused_polling():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiFill={status:'RUNNING',runId:'R1',polling:false,polling_paused:true};
workspace.getDetailBatch=()=>({name:'B1',current_version:'V1'});
workspace.applyMaterialFeeHeaderSnapshot=()=>{};workspace.renderMaterialFeeWorkspace=()=>{};
workspace.renderDetailTabError=(_label,error)=>{throw error};
let polls=0;workspace.pollMaterialAIFill=async()=>{polls++};workspace.call=async()=>({});
await workspace.loadMaterialFeeWorkspace({quiet:true});
console.log(JSON.stringify({polls,paused:state.aiFill.polling_paused}));
""")
    assert result == {'polls': 0, 'paused': True}


def test_retry_retires_old_reply_for_same_run_and_ignores_duplicate_retry_click():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiFill={status:'RUNNING',runId:'R1',connection_error:'网络连接已中断'};
let calls=0,releaseOld,releaseNew;
workspace.call=()=>new Promise(resolve=>{calls++;if(calls===1)releaseOld=resolve;else releaseNew=resolve});
const old=workspace.pollMaterialAIFill(state,'B1','V1','R1');
const retried=workspace.retryMaterialAIProgress();const duplicate=workspace.retryMaterialAIProgress();
releaseNew({ok:true,run_id:'R1',status:'READY',progress_revision:5});await retried;await duplicate;
releaseOld({ok:true,run_id:'R1',status:'FAILED',progress_revision:4});await old;
console.log(JSON.stringify({calls,status:state.aiFill.status,revision:state.aiFill.progress_revision}));
""")
    assert result == {'calls': 2, 'status': 'READY', 'revision': 5}


def test_stopped_deadlock_request_does_not_claim_automatic_retry():
    result = _fee_workspace_result(FIXTURE + r"""
const error=new Error('QueryDeadlockError: changed since last read');
console.log(JSON.stringify({message:workspace.materialAIErrorMessage(error),retryable:workspace.materialAIRequestRetryable(error)}));
""")
    assert not result['retryable']
    assert '自动重试' not in result['message']


def test_lost_start_response_reuses_request_id_for_automatic_and_manual_retry():
    result = _fee_workspace_result(FIXTURE + r"""
workspace.pollMaterialAIFill=async()=>{};
const requests=[];workspace.call=async(_method,args)=>{
 requests.push(args);if(requests.length<=3)throw {status:504,statusText:'Gateway Timeout'};
 return {ok:true,run_id:'SERVER-ALREADY-CREATED',status:'QUEUED'};
};
await workspace.startMaterialAIFill({force:true,selectedSourceIds:['S1']});
const failed=state.aiFill.status;
await workspace.retryMaterialAIProgress();
console.log(JSON.stringify({requests,failed,stored:state.aiStartOptions.request_id,runId:state.aiFill.runId}));
""")
    assert result['failed'] == 'FAILED' and len(result['requests']) == 4
    ids = [request.get('request_id') for request in result['requests']]
    assert all(ids), 'Every start needs an idempotency key before sending the request'
    assert len(set(ids)) == 1 and result['stored'] == ids[0]
    assert len(ids[0]) <= 100 and re.fullmatch(r'[A-Za-z0-9-]+', ids[0])
    assert result['runId'] == 'SERVER-ALREADY-CREATED'


@pytest.mark.parametrize('stalled_flag', ['stalled', 'is_stalled'])
def test_server_stalled_run_restarts_with_new_request_id(stalled_flag):
    result = _fee_workspace_result(FIXTURE + f"const stalledFlag={json.dumps(stalled_flag)};" + r"""
workspace.pollMaterialAIFill=async()=>{};
const requests=[];workspace.call=async(_method,args)=>{requests.push(args);return {ok:true,run_id:requests.length===1?'OLD':'NEW',status:'QUEUED'}};
await workspace.startMaterialAIFill({selectedSourceIds:['S1']});
state.aiFill.status='RUNNING';state.aiFill[stalledFlag]=true;
state.aiStartPromise=new Promise(()=>{});
await workspace.retryMaterialAIProgress();
console.log(JSON.stringify({requests,runId:state.aiFill.runId}));
""")
    assert len(result['requests']) == 2 and result['runId'] == 'NEW'
    first, second = result['requests']
    assert first.get('request_id') and second.get('request_id')
    assert first['request_id'] != second['request_id']
    assert second['force'] == 1 and second['selected_source_ids_json'] == '["S1"]'


@pytest.mark.parametrize('action', ['sources', 'clarification', 'new_analysis'])
def test_explicit_new_analysis_changes_request_id(action):
    result = _fee_workspace_result(FIXTURE + f"const action={json.dumps(action)};" + r"""
workspace.pollMaterialAIFill=async()=>{};
const requests=[];workspace.call=async(_method,args)=>{requests.push(args);return {ok:true,run_id:'R'+requests.length,status:'QUEUED'}};
await workspace.startMaterialAIFill({selectedSourceIds:['S1']});
state.aiFill.status='READY';state.aiFill.source_progress=[{source_id:'S2',selected:true}];
if(action==='sources')await workspace.restartMaterialAIWithSources({$wrapper:{removeClass(){}}});
if(action==='clarification'){
 workspace.saveMaterialAIClarification=async()=>{state.aiClarificationLoaded=true;state.aiClarificationRevision=4;return true};
 workspace.updateMaterialAIClarificationStatus=()=>{};
 await workspace.reanalyzeMaterialAIClarification();
}
if(action==='new_analysis')await workspace.startMaterialAIFill({restart:true});
console.log(JSON.stringify({requests}));
""")
    assert len(result['requests']) == 2
    first, second = result['requests']
    assert first.get('request_id') and second.get('request_id')
    assert first['request_id'] != second['request_id']
    if action == 'sources':
        assert second['selected_source_ids_json'] == '["S2"]'
    if action == 'clarification':
        assert second['expected_clarification_revision'] == 4


def test_request_id_uses_secure_random_bytes_when_random_uuid_is_unavailable():
    result = _fee_workspace_result(FIXTURE + r"""
const crypto=globalThis.crypto;
Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:crypto.getRandomValues.bind(crypto)}});
workspace.pollMaterialAIFill=async()=>{};
let requestId;workspace.call=async(_method,args)=>{requestId=args.request_id;return {ok:true,run_id:'R1',status:'QUEUED'}};
await workspace.startMaterialAIFill();
console.log(JSON.stringify({requestId:requestId||''}));
""")
    assert re.fullmatch(r'[0-9a-f]{32}', result['requestId'])


@pytest.mark.parametrize('with_source_selection', [False, True])
def test_unknown_run_retry_preserves_entire_original_start_payload(with_source_selection):
    result = _fee_workspace_result(FIXTURE + f"const withSourceSelection={str(with_source_selection).lower()};" + r"""
workspace.pollMaterialAIFill=async()=>{};
state.aiClarification='原说明';
const requests=[];workspace.call=async(_method,args)=>{
 requests.push(JSON.parse(JSON.stringify(args)));
 if(requests.length<=3)throw {status:504,statusText:'Gateway Timeout'};
 return {ok:true,run_id:'SERVER-ALREADY-CREATED',status:'QUEUED'};
};
await workspace.startMaterialAIFill({force:false,...(withSourceSelection?{selectedSourceIds:['S1']}:{})});
state.aiFill.source_progress=[{source_id:'S2',selected:true}];
state.aiClarification='尚未重新分析的新说明';
await workspace.retryMaterialAIProgress();
console.log(JSON.stringify({requests,runId:state.aiFill.runId}));
""")
    assert len(result['requests']) == 4
    original = result['requests'][0]
    assert original['force'] == 0 and original['request_id']
    assert ('selected_source_ids_json' in original) is with_source_selection
    assert all(request == original for request in result['requests'][1:])
    assert result['runId'] == 'SERVER-ALREADY-CREATED'
