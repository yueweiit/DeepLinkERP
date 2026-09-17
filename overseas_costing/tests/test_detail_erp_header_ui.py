"""批次详情顶栏 ERP 入口的行为回归测试。"""

import json
from pathlib import Path
import subprocess

import pytest


PARTS = Path(__file__).resolve().parents[1] / "page/overseas_cost_workbench/parts"


def run_view_js(script: str):
    source = f"""
const fs=require('fs');
global.OverseasCostWorkbenchState={{
  primaryActionForIssue:()=>({{action:'review',label:'核对成本'}}),
  parseWorkbenchState:()=>({{tab:'items'}}),
}};
const parts={json.dumps(str(PARTS))};
const calculation=fs.readFileSync(parts+'/30-calculation-erp.js','utf8').split('  applyRecalculateSummary(')[0];
const classSource=calculation
  +fs.readFileSync(parts+'/75-table-and-list.js','utf8')
  +fs.readFileSync(parts+'/80-drawer-profit.js','utf8')
  +fs.readFileSync(parts+'/82-detail-page.js','utf8');
const Harness=Function(`return class Harness {{${{classSource}}}}`)();
function makeView(batch) {{
  const view=new Harness();
  view.batches=[batch];
  view.detailState={{batchName:batch.name,versionName:batch.current_version||'',tab:'items',header:batch,detail:null,refreshRequestId:0,editToken:''}};
  view.findBatch=name=>view.batches.find(row=>row.name===name);
  view.escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
  view.hasText=value=>String(value??'').trim().length>0;
  view.isPositive=value=>Number(value)>0;
  view.formatMoney=value=>Number(value||0).toFixed(2);
  view.formatValue=value=>String(value??'');
  view.formatDateTimeMinute=value=>String(value??'');
  view.businessTypeLabel=()=>'';
  view.transportLabel=()=>'';
  view.issueLabel=value=>String(value??'');
  view.sumRowsNumber=(rows,key)=>rows.reduce((total,row)=>total+Number(row[key]||0),0);
  view.batchStatusInfo=(status)=>({{
    label:String(status||'').toLowerCase().includes('calculated')?'已试算':'待重算',
    needsRecalculate:['dirty','draft'].some(value=>String(status||'').toLowerCase().includes(value)),
  }});
  view.sourceStatusLabel=()=>'已关联资料';
  view.renderErpFlowBlockInline=()=>'';
  view.cleanupSkuScrollControls=()=>{{}};
  view.cleanupMaterialGridScrollControls=()=>{{}};
  view.html='';
  view.$root={{
    attr:key=>key==='data-screen'?'detail':'',
    find:selector=>({{
      html:value=>{{if(selector==="[data-area='detail-screen']")view.html=value;}},
      hasClass:()=>false,
      replaceWith:value=>{{
        view.html=view.html.replace(/<span class="ocw-detail-erp-action"[\\s\\S]*?<\\/span>/,value);
      }},
    }}),
  }};
  return view;
}}
function button(html,action) {{
  const tags=html.match(/<button[^>]*>[\\s\\S]*?<\\/button>/g)||[];
  const tag=tags.find(value=>value.includes(`data-action="${{action}}"`)||value.includes(`data-action='${{action}}'`));
  if(!tag)return null;
  const label=tag.slice(tag.indexOf('>')+1,tag.lastIndexOf('</button>')).replace(/<[^>]+>/g,'').trim();
  return {{tag,label,disabled:/\\sdisabled(?:[\\s>])/.test(tag)}};
}}
(async()=>{{
{script}
}})().catch(error=>{{console.error(error);process.exit(1)}});
"""
    completed = subprocess.run(
        ["node", "-e", source],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


ERP_STATES = [
    (
        "untried",
        {"name": "B-1", "status": "Draft", "current_version": "V-1"},
        "推送 ERP",
        False,
        "请先完成试算",
    ),
    (
        "unconfirmed",
        {"name": "B-1", "status": "Calculated", "current_version": "V-1"},
        "推送 ERP",
        False,
        "请先校验计算结果",
    ),
    (
        "partially_confirmed",
        {
            "name": "B-1",
            "status": "Calculated",
            "confirm_status": "Partially Confirmed",
            "current_version": "V-1",
        },
        "推送 ERP",
        False,
        "请先校验计算结果",
    ),
    (
        "status_only_confirmed",
        {"name": "B-1", "status": "Confirmed", "confirm_status": " ", "current_version": "V-1"},
        "推送 ERP",
        False,
        "请先完成试算",
    ),
    (
        "ready",
        {"name": "B-1", "status": "Calculated", "confirm_status": "Confirmed", "current_version": "V-1"},
        "推送 ERP",
        True,
        "可以推送 ERP",
    ),
    (
        "failed",
        {
            "name": "B-1",
            "status": "Calculated",
            "confirm_status": "Confirmed",
            "current_version": "V-1",
            "writeback_status": "Failed",
        },
        "重试 ERP",
        True,
        "可以重试 ERP",
    ),
    (
        "success",
        {
            "name": "B-1",
            "status": "Calculated",
            "confirm_status": "Confirmed",
            "current_version": "V-1",
            "writeback_status": "Success",
        },
        "ERP 已推送",
        False,
        "无需重复操作",
    ),
    (
        "invalid_business",
        {
            "name": "B-1",
            "status": "Calculated",
            "confirm_status": "Confirmed",
            "current_version": "V-1",
            "source_status": {"invalid_business": True, "invalid_business_reason": "采购审批已撤销"},
        },
        "推送 ERP",
        False,
        "采购审批已撤销",
    ),
]


@pytest.mark.parametrize(("_name", "batch", "label", "enabled", "reason"), ERP_STATES)
def test_detail_header_renders_all_erp_push_states(_name, batch, label, enabled, reason):
    result = run_view_js(
        f"""
const view=makeView({json.dumps(batch, ensure_ascii=False)});
const state=typeof view.erpPushActionState==='function'?view.erpPushActionState(view.getDetailBatch()):null;
view.renderDetailShell();
const rendered=button(view.html,'detail-writeback-to-erp');
console.log(JSON.stringify({{state,rendered,html:view.html}}));
"""
    )

    assert result["state"] is not None
    assert result["state"]["label"] == label
    assert result["state"]["enabled"] is enabled
    assert reason in result["state"]["reason"]
    assert result["rendered"]["label"] == label
    assert result["rendered"]["disabled"] is (not enabled)
    assert reason in result["rendered"]["tag"] or reason in result["html"]


def test_detail_erp_button_stays_in_header_outside_overview_tab():
    result = run_view_js(
        """
const view=makeView({name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1'});
view.detailState.tab='vouchers';
view.renderDetailShell();
console.log(JSON.stringify({button:button(view.html,'detail-writeback-to-erp'),tabs:view.html.includes('data-area="detail-content"')}));
"""
    )

    assert result["tabs"] is True
    assert result["button"]["label"] == "推送 ERP"
    assert result["button"]["disabled"] is False


def test_confirm_status_never_falls_back_to_batch_status():
    result = run_view_js(
        """
const view=makeView({name:'B-1',status:'Confirmed',confirm_status:' '});
console.log(JSON.stringify({
  empty:view.isCalculationConfirmed({status:'Confirmed',confirm_status:' '}),
  explicitPartial:view.isCalculationConfirmed({status:'Confirmed',confirm_status:'Partially Confirmed'}),
}));
"""
    )

    assert result == {"empty": False, "explicitPartial": False}


def test_detail_header_handler_delegates_exact_batch_without_direct_backend_call():
    source = f"""
const fs=require('fs');
const shell=fs.readFileSync({json.dumps(str(PARTS / '10-shell.js'))},'utf8');
const bindSource=shell.slice(shell.indexOf('  bindEvents() {{'));
const Harness=Function(`return class Harness {{${{bindSource}}\n}}`)();
const handlers={{}};
const view=new Harness();
view.detailState={{batchName:'DETAIL-BATCH'}};
view.drawerBatchName='DRAWER-BATCH';
view.$root={{on:(type,selector,handler)=>{{(handlers[selector]??=[]).push(handler);return view.$root;}}}};
let delegated=[],backendCalls=0;
view.writebackToErp=batchName=>delegated.push(batchName);
view.call=()=>{{backendCalls+=1;throw new Error('header must not call backend directly')}};
global.window={{}};
global.$=node=>node===window?{{off(){{return this}},on(){{return this}}}}:{{attr:()=>'',hasClass:()=>false,closest:()=>({{length:0}})}};
view.bindEvents();
const detailHandlers=handlers["[data-action='detail-writeback-to-erp']"]||[];
detailHandlers[0]({{currentTarget:{{}}}});
console.log(JSON.stringify({{delegated,backendCalls,bindingCount:detailHandlers.length}}));
"""
    completed = subprocess.run(["node", "-e", source], check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout) == {
        "delegated": ["DETAIL-BATCH"],
        "backendCalls": 0,
        "bindingCount": 1,
    }


def test_overview_keeps_confirmation_preview_and_push_safety_gates():
    result = run_view_js(
        """
function render(batch){const view=makeView(batch);const html=view.renderErpFlowPanel(batch,[]);return {
  confirm:button(html,'confirm-calculation-result'),preview:button(html,'preview-erp-payload'),push:button(html,'writeback-to-erp'),html
};}
console.log(JSON.stringify({
  unconfirmed:render({name:'B-1',status:'Calculated',current_version:'V-1'}),
  partial:render({name:'B-1',status:'Calculated',confirm_status:'Partially Confirmed',current_version:'V-1'}),
  statusOnly:render({name:'B-1',status:'Confirmed',confirm_status:' ',current_version:'V-1'}),
  ready:render({name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1'}),
  stale:render({name:'B-1',status:'Dirty',confirm_status:'Confirmed',current_version:'V-1'}),
  invalid:render({name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1',source_status:{invalid_business:true}}),
}));
"""
    )

    assert result["unconfirmed"]["confirm"]["disabled"] is False
    assert result["unconfirmed"]["preview"]["disabled"] is True
    assert result["unconfirmed"]["push"]["disabled"] is True
    assert result["partial"]["preview"]["disabled"] is True
    assert result["partial"]["push"]["disabled"] is True
    assert result["statusOnly"]["preview"]["disabled"] is True
    assert result["statusOnly"]["push"]["disabled"] is True
    assert result["ready"]["preview"]["disabled"] is False
    assert result["ready"]["push"]["disabled"] is False
    assert result["stale"]["confirm"]["disabled"] is True
    assert result["stale"]["push"]["disabled"] is True
    assert result["invalid"]["confirm"]["disabled"] is True
    assert result["invalid"]["preview"]["disabled"] is True
    assert result["invalid"]["push"]["disabled"] is True


@pytest.mark.parametrize("confirm_status", ["Partially Confirmed", ""])
def test_erp_queue_rejects_batch_without_exact_confirm_status(confirm_status):
    result = run_view_js(
        f"""
const batch={{name:'B-1',status:'Confirmed',confirm_status:{json.dumps(confirm_status)},current_version:'V-1',item_count:1}};
const view=makeView(batch);view.batchItems={{'B-1':[]}};
view.batchTotalCostNumber=()=>100;view.businessTypeCompactLabel=()=>'';
const html=view.renderErpQueueRow(batch);
console.log(JSON.stringify({{preview:button(html,'queue-preview-erp'),push:button(html,'queue-writeback-erp'),html}}));
"""
    )

    assert result["preview"] is None
    assert result["push"]["disabled"] is True
    assert "等待人工校验" in result["html"]


def test_failed_writeback_refreshes_detail_header_from_server_state():
    result = run_view_js(
        """
const initial={name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1',writeback_status:'Not Started'};
const view=makeView(initial);const endpoints=[],events=[];
view.call=async(endpoint,args)=>{
  endpoints.push([endpoint,args]);
  if(endpoint.endsWith('writeback_to_erp'))return {ok:false,batch_name:'B-1',writeback_status:'Failed',message:'ERP timeout'};
  if(endpoint.endsWith('get_batch_detail'))return {ok:true,batch_name:'B-1',version_name:'V-1',header:{...initial,writeback_status:'Failed',writeback_message:'ERP timeout'},summary:{}};
  throw new Error(endpoint);
};
view.recordUsage=(action,payload)=>events.push(['audit',action,payload.status]);
view.showErpFlowBlock=(payload,title)=>events.push(['block',payload.writeback_status,title]);
view.showError=error=>events.push(['error',error.message]);
view.switchDetailTab=async()=>{};
await view.queueErpWriteback('B-1');
const state=view.erpPushActionState(view.getDetailBatch());
console.log(JSON.stringify({endpoints,events,state,button:button(view.html,'detail-writeback-to-erp'),html:view.html,header:view.detailState.header}));
"""
    )

    assert [item[0].rsplit(".", 1)[-1] for item in result["endpoints"]] == [
        "writeback_to_erp",
        "get_batch_detail",
    ]
    assert [event[0] for event in result["events"]] == ["audit", "block"]
    assert result["header"]["writeback_status"] == "Failed"
    assert result["state"]["label"] == "重试 ERP"
    assert result["state"]["enabled"] is True
    assert result["state"]["reason"] == "ERP timeout"
    assert result["button"]["label"] == "重试 ERP"
    assert result["button"]["disabled"] is False
    assert "ERP timeout" in result["button"]["tag"]
    assert "ERP timeout" in result["html"]


def test_push_block_survives_refresh_and_incomplete_readiness_check():
    result = run_view_js(
        """
const initial={name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1',writeback_status:'Not Started'};
const view=makeView(initial);const endpoints=[];let tabRenders=0;
view.detailState.tab='vouchers';view.renderDetailShell();
view.call=async(endpoint,args)=>{
  endpoints.push(endpoint);
  if(endpoint.endsWith('writeback_to_erp'))return {ok:false,batch_name:'B-1',blocking_reasons:['ERP configuration missing','missing URL']};
  if(endpoint.endsWith('get_batch_detail'))return {ok:true,batch_name:'B-1',version_name:'V-1',header:{...initial},summary:{}};
  if(endpoint.endsWith('check_writeback_ready'))return {ok:true,ready:true};
  throw new Error(endpoint);
};
view.recordUsage=()=>{};view.switchDetailTab=async()=>{tabRenders+=1};
await view.queueErpWriteback('B-1');
await view.refreshDetailSummary();
await view.syncErpFlowBlock('B-1');
await view.refreshDetailSummary();
await view.syncErpFlowBlock('B-1');
const state=view.erpPushActionState(view.getDetailBatch());
console.log(JSON.stringify({endpoints,tabRenders,state,pushBlock:view.erpPushBlockState,genericBlock:view.erpFlowBlockState,button:button(view.html,'detail-writeback-to-erp'),html:view.html}));
"""
    )

    endpoint_names = [endpoint.rsplit(".", 1)[-1] for endpoint in result["endpoints"]]
    assert endpoint_names.count("get_batch_detail") == 3
    assert endpoint_names.count("check_writeback_ready") == 2
    assert result["tabRenders"] == 3
    assert result["pushBlock"]["batchName"] == "B-1"
    assert result["pushBlock"]["versionName"] == "V-1"
    assert result["state"]["label"] == "重试 ERP"
    assert result["state"]["enabled"] is True
    assert result["button"]["disabled"] is False
    assert "ERP configuration missing" in result["state"]["reason"]
    assert "missing URL" in result["html"]


def test_preview_block_does_not_overwrite_push_failure():
    result = run_view_js(
        """
const batch={name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1'};
const view=makeView(batch);
view.erpPushBlockState={batchName:'B-1',versionName:'V-1',message:'ERP configuration missing',blocking_reasons:['missing URL']};
view.showErpFlowBlock({batch_name:'B-1',message:'preview only'},'preview failed');
console.log(JSON.stringify({state:view.erpPushActionState(batch),pushBlock:view.erpPushBlockState,genericBlock:view.erpFlowBlockState}));
"""
    )

    assert result["genericBlock"]["result"]["message"] == "preview only"
    assert result["pushBlock"]["message"] == "ERP configuration missing"
    assert result["state"]["label"] == "重试 ERP"
    assert result["state"]["enabled"] is True
    assert result["state"]["reason"] == "ERP configuration missing"


def test_successful_push_clears_prior_push_block():
    result = run_view_js(
        """
const batch={name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1',writeback_status:'Not Started'};
const view=makeView(batch);view.erpPushBlockState={batchName:'B-1',versionName:'V-1',message:'missing URL',blocking_reasons:[]};
view.erpFlowBlockState={batchName:'B-1',action:'PUSH_ERP',result:{message:'missing URL'}};
view.call=async()=>({ok:true,writeback_status:'Success',message:'pushed'});
view.refreshBatch=async()=>{batch.writeback_status='Success';batch.writeback_message='pushed'};view.recordUsage=()=>{};
global.frappe={show_alert:()=>{}};
await view.queueErpWriteback('B-1');
console.log(JSON.stringify({pushBlock:view.erpPushBlockState,genericBlock:view.erpFlowBlockState,state:view.erpPushActionState(batch)}));
"""
    )

    assert result["pushBlock"] is None
    assert result["genericBlock"] is None
    assert result["state"] == {"label": "ERP 已推送", "enabled": False, "reason": "pushed"}


def test_push_block_identity_does_not_affect_other_batch_or_version():
    result = run_view_js(
        """
const batch={name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1'};
const view=makeView(batch);
view.erpPushBlockState={batchName:'B-1',versionName:'V-1',message:'missing URL',blocking_reasons:[]};
console.log(JSON.stringify({
  same:view.erpPushActionState(batch),
  otherBatch:view.erpPushActionState({...batch,name:'B-2'}),
  otherVersion:view.erpPushActionState({...batch,current_version:'V-2'}),
}));
"""
    )

    assert result["same"]["label"] == "重试 ERP"
    assert result["same"]["enabled"] is True
    assert result["otherBatch"]["label"] == "推送 ERP"
    assert result["otherBatch"]["enabled"] is True
    assert result["otherVersion"]["label"] == "推送 ERP"
    assert result["otherVersion"]["enabled"] is True


@pytest.mark.parametrize(
    ("batch", "reason"),
    [
        ({"name": "B-1", "status": "Dirty", "confirm_status": "Confirmed", "current_version": "V-1"}, "请先完成试算"),
        ({"name": "B-1", "status": "Calculated", "confirm_status": "", "current_version": "V-1"}, "请先校验计算结果"),
        (
            {
                "name": "B-1",
                "status": "Calculated",
                "confirm_status": "Confirmed",
                "current_version": "V-1",
                "source_status": {"invalid_business": True, "invalid_business_reason": "业务来源失效"},
            },
            "业务来源失效",
        ),
    ],
)
def test_push_retry_never_bypasses_hard_gate(batch, reason):
    result = run_view_js(
        f"""
const batch={json.dumps(batch, ensure_ascii=False)};
const view=makeView(batch);
view.erpPushBlockState={{batchName:'B-1',versionName:'V-1',message:'missing URL',blocking_reasons:[]}};
console.log(JSON.stringify(view.erpPushActionState(batch)));
"""
    )

    assert result["label"] != "重试 ERP"
    assert result["enabled"] is False
    assert reason in result["reason"]


def test_failed_writeback_keeps_original_block_after_drawer_refresh_sync():
    result = run_view_js(
        """
const batch={name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1',writeback_status:'Not Started'};
const view=makeView(batch);const endpoints=[],drawerStates=[];
view.detailState.batchName='';view.drawerBatchName='B-1';view.activeBatchName='B-1';
view.$root={attr:()=> 'workbench',find:()=>({hasClass:()=>true})};
view.call=async(endpoint)=>{
  endpoints.push(endpoint);
  if(endpoint.endsWith('writeback_to_erp'))return {ok:false,batch_name:'B-1',writeback_status:'Failed',message:'ERP timeout'};
  if(endpoint.endsWith('check_writeback_ready'))return {ok:true,ready:true};
  throw new Error(endpoint);
};
view.recordUsage=()=>{};view.loadBatchItems=async()=>{};view.loadAuditLogs=async()=>{};view.renderTable=()=>{};
view.renderBatchDrawer=()=>drawerStates.push(view.erpFlowBlockState?.result?.message||null);
await view.queueErpWriteback('B-1');
console.log(JSON.stringify({endpoints,drawerStates,block:view.erpFlowBlockState}));
"""
    )

    assert [endpoint.rsplit(".", 1)[-1] for endpoint in result["endpoints"]] == ["writeback_to_erp"]
    assert result["block"]["result"]["message"] == "ERP timeout"
    assert result["drawerStates"][-1] == "ERP timeout"


def test_refresh_failure_does_not_replace_original_erp_error():
    result = run_view_js(
        """
const batch={name:'B-1',status:'Calculated',confirm_status:'Confirmed',current_version:'V-1'};
const view=makeView(batch);let rejected='';
view.renderDetailShell();
view.call=async()=>({ok:false,batch_name:'B-1',writeback_status:'Failed',message:'ERP timeout'});
view.recordUsage=()=>{};view.refreshBatch=async()=>{throw new Error('detail refresh failed')};
view.switchDetailTab=async()=>{};
try{await view.queueErpWriteback('B-1')}catch(error){rejected=error.message}
console.log(JSON.stringify({rejected,block:view.erpFlowBlockState,button:button(view.html,'detail-writeback-to-erp'),html:view.html}));
"""
    )

    assert result["rejected"] == ""
    assert result["block"]["result"]["message"] == "ERP timeout"
    assert result["button"]["label"] == "重试 ERP"
    assert "ERP timeout" in result["html"]
