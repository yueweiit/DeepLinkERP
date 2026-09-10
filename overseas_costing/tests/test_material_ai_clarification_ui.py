from overseas_costing.tests.test_workbench_frontend_state import _fee_workspace_result

FIXTURE = r"""
const workspace=new Harness();
workspace.detailState={batchName:'B1',versionName:'V1',tab:'documents'};
const state=workspace.ensureMaterialFeeState();
workspace.updateMaterialAIClarificationStatus=()=>{};
workspace.updateMaterialAIProgressSurface=()=>{};
workspace.openMaterialAIProgressDialog=()=>{};
workspace.pollMaterialAIFill=async()=>{};
workspace.showError=()=>{};
workspace.acceptMaterialAIClarification({text:'旧说明',revision:1});
"""


def test_new_saved_note_hides_old_ready_draft_and_stops_old_poll():
    result=_fee_workspace_result(FIXTURE+r'''
state.aiFill={status:'READY',clarification_revision:1};state.aiPendingReady={run_id:'OLD'};state.aiRunGeneration=3;
workspace.acceptMaterialAIClarification({text:'其他页面的新说明',revision:2});
console.log(JSON.stringify({status:state.aiFill.status,pending:state.aiPendingReady,generation:state.aiRunGeneration}));
''')
    assert result=={'status':'STALE','pending':None,'generation':4}


def test_dirty_input_and_unchanged_save_still_retire_older_analysis():
    result=_fee_workspace_result(FIXTURE+r'''
state.aiFill={status:'READY',clarification_revision:1};state.aiPendingReady={run_id:'OLD'};
state.aiClarification='我的草稿';state.aiClarificationDirty=true;
workspace.acceptMaterialAIClarification({text:'其他人已保存',revision:2});
const dirty={status:state.aiFill.status,text:state.aiClarification};
state.aiFill={status:'READY',clarification_revision:1};
workspace.call=async()=>({ok:true,unchanged:true,clarification:{text:'我的草稿',revision:2}});
await workspace.saveMaterialAIClarification();
console.log(JSON.stringify({dirty,status:state.aiFill.status,pending:state.aiPendingReady}));
''')
    assert result=={'dirty':{'status':'STALE','text':'我的草稿'},'status':'STALE','pending':None}


def test_delayed_workspace_restore_does_not_replace_newly_started_analysis():
    result = _fee_workspace_result(FIXTURE + r"""
workspace.getDetailBatch=()=>({name:'B1',current_version:'V1'});
workspace.applyMaterialFeeHeaderSnapshot=()=>{};
workspace.renderMaterialFeeWorkspace=()=>{};
workspace.renderDetailTabError=(_label,error)=>{throw error};
const polledRuns=[];
workspace.pollMaterialAIFill=async(_state,_batch,_version,runId)=>{
 polledRuns.push(runId);
 state.aiFill.polling=true;
 return new Promise(()=>{});
};
let releaseLatest;
workspace.call=async(method,args)=>{
 if(method.endsWith('get_source_ai_review_status'))return new Promise(resolve=>{releaseLatest=resolve});
 if(method.endsWith('save_source_ai_clarification'))return {ok:true,unchanged:false,clarification:{text:args.clarification_text,revision:2}};
 if(method.endsWith('start_source_ai_review'))return {ok:true,status:'QUEUED',run_id:'NEW'};
 return {};
};
const loading=workspace.loadMaterialFeeWorkspace({quiet:true});
state.aiClarification='新说明';state.aiClarificationDirty=true;
await workspace.reanalyzeMaterialAIClarification();
const generation=state.aiRunGeneration;
releaseLatest({ok:true,status:'READY',run_id:'OLD',clarification_revision:1,clarification:{text:'旧说明',revision:1}});
await loading;
console.log(JSON.stringify({runId:state.aiFill.runId,status:state.aiFill.status,revision:state.aiClarificationRevision,text:state.aiClarification,pending:state.aiPendingReady,generationUnchanged:state.aiRunGeneration===generation,polledRuns}));
""")
    assert result == {
        'runId': 'NEW', 'status': 'QUEUED', 'revision': 2, 'text': '新说明',
        'pending': None, 'generationUnchanged': True, 'polledRuns': ['NEW'],
    }


def test_clarification_save_button_persists_without_start_and_dirty_refresh_keeps_input():
    result = _fee_workspace_result(FIXTURE + r"""
const handlers={};
workspace.$root={on:(event,selector,handler)=>{handlers[event+selector]=handler}};
global.$=(value)=>value;
workspace.bindMaterialFeeWorkspaceEvents();
handlers['input[data-mf-ai-clarification]']({currentTarget:{val:()=> '新说明'}});
workspace.acceptMaterialAIClarification({text:'延迟的旧说明',revision:1});
const dirtyBefore=state.aiClarificationDirty;
const inputBefore=state.aiClarification;
const calls=[];
workspace.call=async(method,args)=>{calls.push({method,args});return {ok:true,clarification:{text:args.clarification_text,revision:2}}};
await handlers["click[data-action='mf-ai-clarification-save']"]();
console.log(JSON.stringify({dirtyBefore,inputBefore,calls,status:state.aiClarificationStatus,revision:state.aiClarificationRevision,dirty:state.aiClarificationDirty}));
""")
    assert result['dirtyBefore'] and result['inputBefore'] == '新说明'
    assert len(result['calls']) == 1
    assert result['calls'][0]['method'].endswith('save_source_ai_clarification')
    assert result['calls'][0]['args']['expected_revision'] == 1
    assert result['status'] == 'saved' and result['revision'] == 2 and not result['dirty']


def test_typing_during_save_preserves_newer_input_and_failed_save_keeps_retryable_draft():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiClarification='提交的说明';state.aiClarificationDirty=true;
let release;
workspace.call=async()=>new Promise(resolve=>{release=resolve});
const saving=workspace.saveMaterialAIClarification();
await Promise.resolve();
const duringStatus=state.aiClarificationStatus;
state.aiClarification='还在输入的新说明';state.aiClarificationDirty=true;
release({ok:true,clarification:{text:'提交的说明',revision:2}});
await saving;
const after={text:state.aiClarification,dirty:state.aiClarificationDirty,status:state.aiClarificationStatus};
workspace.call=async()=>{throw new Error('保存失败')};
try{await workspace.saveMaterialAIClarification()}catch(_error){}
console.log(JSON.stringify({duringStatus,after,failedStatus:state.aiClarificationStatus,text:state.aiClarification}));
""")
    assert result['duringStatus'] == 'saving'
    assert result['after'] == {'text': '还在输入的新说明', 'dirty': True, 'status': 'unsaved'}
    assert result['failedStatus'] == 'failed' and result['text'] == '还在输入的新说明'


def test_rerun_saves_first_and_supersedes_ready_or_running_with_force_false():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiFill={status:'RUNNING',runId:'OLD'};
state.aiStartPromise=new Promise(()=>{});
state.aiClarification='重新理解';state.aiClarificationDirty=true;
const calls=[];
workspace.call=async(method,args)=>{
 calls.push({method,args});
 if(method.endsWith('save_source_ai_clarification'))return {ok:true,unchanged:false,clarification:{text:'重新理解',revision:2}};
 return {ok:true,status:'QUEUED',run_id:'NEW'};
};
await workspace.reanalyzeMaterialAIClarification();
console.log(JSON.stringify({calls,runId:state.aiFill.runId,status:state.aiClarificationStatus}));
""")
    assert [c['method'].rsplit('.', 1)[-1] for c in result['calls']] == ['save_source_ai_clarification', 'start_source_ai_review']
    assert result['calls'][1]['args']['force'] == 0
    assert result['calls'][1]['args']['expected_clarification_revision'] == 2
    assert result['runId'] == 'NEW' and result['status'] == 'saved'


def test_concurrent_note_conflict_stops_rerun_and_preserves_input():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiClarification='我的说明';state.aiClarificationDirty=true;
const calls=[];
workspace.call=async(method)=>{calls.push(method);return {ok:false,conflict:true,message:'说明已变化',clarification:{text:'其他页面',revision:2}}};
try{await workspace.reanalyzeMaterialAIClarification()}catch(_error){}
console.log(JSON.stringify({calls,text:state.aiClarification,status:state.aiClarificationStatus,revision:state.aiClarificationRevision}));
""")
    assert len(result['calls']) == 1
    assert result['text'] == '我的说明' and result['status'] == 'failed'
    assert result['revision'] == 2


def test_rerun_can_be_requested_again_while_previous_analysis_is_polling():
    result = _fee_workspace_result(FIXTURE + r"""
state.aiFill={status:'READY',runId:'OLD'};
const requests=[];
workspace.pollMaterialAIFill=async()=>new Promise(()=>{});
workspace.call=async(method,args)=>{
 requests.push(method);
 if(method.endsWith('save_source_ai_clarification'))return {ok:true,unchanged:true,clarification:{text:'旧说明',revision:1}};
 return {ok:true,status:'QUEUED',run_id:'NEW'};
};
workspace.reanalyzeMaterialAIClarification();
await new Promise(resolve=>setTimeout(resolve,0));
console.log(JSON.stringify({status:state.aiFill.status,blocked:!!state.aiClarificationRerunPromise,requests}));
""")
    assert result['status'] == 'QUEUED'
    assert not result['blocked']


def test_clarification_renderer_exposes_accessible_status_and_distinct_save_rerun():
    result = _fee_workspace_result(FIXTURE + r"""
workspace.escape=value=>String(value);
console.log(JSON.stringify({html:workspace.renderMaterialAIClarification()}));
""")
    assert '保存说明' in result['html'] and '按说明重新分析' in result['html']
    assert 'role="status"' in result['html']
