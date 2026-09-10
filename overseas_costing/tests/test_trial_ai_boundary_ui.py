"""Trial calculation uses saved facts while unadopted AI proposals stay separate."""
import json

import pytest

from overseas_costing.tests.test_workbench_frontend_state import (
    PARTS, PREVIEW_WORKSPACE_FIXTURE, _fee_workspace_result,
)


AI_FIXTURE = r"""
state.materials={items:[{name:'saved',actual_shipped_qty:1}]};
state.fees={fees:[{name:'actual',amount:'2602.820000',currency:'RMB'}]};
const fill=state.aiFill={status:'READY',draftVisible:false,run_id:'AI',
  row_review:{rows:[{row_id:'unadopted',can_fill:true,default_selected:true,values:{actual_shipped_qty:99}}],fees:[]}};
const selection=workspace.ensureMaterialAIRowSelection(fill);
selection.preview={id:'preview',revision:1,can_apply:true};
selection.previewKey=workspace.materialAIRowSelectionKey(fill);
workspace.ensureEditSession=async()=>true;
"""


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING", "READY"])
def test_trial_uses_saved_facts_and_retains_unadopted_ai(status):
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + AI_FIXTURE +
        f"fill.status={json.dumps(status)};" + r"""
const before=JSON.stringify({materials:state.materials,fees:state.fees});
const requests=[];workspace.call=async(endpoint,args)=>{requests.push({endpoint,args});return {ok:true,saved:true,
 batch_modified:'M2',version_name:'V-1',summary:{total_cost_rmb:'2602.820000'},summary_snapshot:{item_count:1}}};
const ok=await workspace.refreshMaterialFeeCostPreview();
console.log(JSON.stringify({ok,requests,retained:state.aiFill===fill,selected:[...selection.rows],
 unchanged:before===JSON.stringify({materials:state.materials,fees:state.fees}),total:state.preview.summary.total_cost_rmb,
 notice:workspace.renderMaterialFeeCostTable().includes('本次按已保存资料试算，未采用的 AI 结果不计入。')}));
""")
    assert result["ok"] and result["retained"] and result["unchanged"] and result["notice"]
    assert result["selected"] == ["unadopted"]
    assert result["total"] == "2602.820000"
    assert len(result["requests"]) == 1
    assert result["requests"][0]["endpoint"].endswith("calculate_comprehensive_cost")
    assert set(result["requests"][0]["args"]) == {"batch_name", "version_name"}


def test_trial_waits_only_for_actual_saves_and_blocks_ai_confirm_until_done():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + AI_FIXTURE + r"""
let release;const writing=workspace.trackMaterialFeeWrite(()=>new Promise(resolve=>release=resolve));
const running=workspace.refreshMaterialFeeCostPreview();
await new Promise(resolve=>setImmediate(resolve));
const before={calls:workspace.calls,canApply:workspace.canConfirmMaterialAIRowSelection(fill)};
await workspace.applyMaterialAIFill();
await workspace.refreshMaterialFeeCostPreview();
release();await writing;await running;
console.log(JSON.stringify({before,calls:workspace.calls,canApply:workspace.canConfirmMaterialAIRowSelection(fill),retained:state.aiFill===fill}));
""")
    assert result == {"before": {"calls": 0, "canApply": False}, "calls": 1, "canApply": True, "retained": True}


def test_trial_rejects_actual_ai_write_with_specific_message():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + AI_FIXTURE + r"""
fill.applying=true;let error='';try{await workspace.refreshMaterialFeeCostPreview()}catch(e){error=e.message}
console.log(JSON.stringify({error,calls:workspace.calls,disabled:button.disabled,running:state.previewRunning}));
""")
    assert "正在保存" in result["error"]
    assert "放弃" not in result["error"]
    assert result["calls"] == 0 and result["disabled"] is True and result["running"] is False


@pytest.mark.parametrize("failure", ["fee", "material", "api"])
def test_ready_ai_does_not_bypass_save_or_calculation_failures(failure):
    setup = {
        "fee": "state.feeDrafts={fee:{error:'金额待修正'}};",
        "material": "state.materialSaveErrors={saved:'保存失败'};",
        "api": "workspace.call=async()=>{workspace.calls++;return {ok:false,message:'版本已变化'}};",
    }[failure]
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + AI_FIXTURE + setup + r"""
let error='';try{await workspace.refreshMaterialFeeCostPreview()}catch(e){error=e.message}
console.log(JSON.stringify({error,calls:workspace.calls,retained:state.aiFill===fill,preview:state.preview.summary.total_cost_rmb,disabled:button.disabled}));
""")
    assert result["error"] and "放弃" not in result["error"]
    assert result["calls"] == (1 if failure == "api" else 0)
    assert result["retained"] and result["preview"] == "100.00" and not result["disabled"]


def test_legacy_ai_confirmation_is_disabled_during_trial():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + r"""
state.aiFill={status:'READY',selections:new Set(['fee']),manualUpdates:{},draftVisible:true};
state.previewRunning=true;await workspace.applyMaterialAIFill();
console.log(JSON.stringify({calls:workspace.calls,html:workspace.renderMaterialAIFillFooter()}));
""")
    assert result["calls"] == 0
    assert 'data-action="mf-ai-apply" disabled' in result["html"]


def test_other_recalculate_entry_allows_ready_ai_and_reserves_write_guard():
    source_path = json.dumps(str(PARTS / "30-calculation-erp.js"))
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + AI_FIXTURE + f"""
const Recalc=Function('Base','return class extends Base {{'+fs.readFileSync({source_path},'utf8').split('  setMainView(')[0]+'}}')(Harness);
workspace.recalculate=Recalc.prototype.recalculate;
""" + r"""
workspace.detailState.tab='overview';
workspace.findBatch=()=>({name:'B-1',current_version:'V-1'});
workspace.recordUsage=()=>{};workspace.showError=e=>{workspace.error=e.message};
workspace.applyRecalculateSummary=()=>{};workspace.$root.attr=()=> 'detail';workspace.refreshDetailSummary=async()=>{};
let release;const endpoints=[];workspace.call=(endpoint)=>{endpoints.push(endpoint);return new Promise(resolve=>release=resolve)};
const running=workspace.recalculate('B-1');await new Promise(resolve=>setImmediate(resolve));
const before={canApply:workspace.canConfirmMaterialAIRowSelection(fill),requests:endpoints.length};
await workspace.recalculate('B-1');
if(release)release({ok:true,saved:true,batch_modified:'M2',version_name:'V-1',summary:{total_cost_rmb:'2602.82'},summary_snapshot:{}});
await running;
console.log(JSON.stringify({before,endpoints,error:workspace.error||'',retained:state.aiFill===fill,running:!!state.previewRunning}));
""")
    assert result["before"] == {"canApply": False, "requests": 1}
    assert result["endpoints"] == ["overseas_costing.api.calculate.recalculate_batch"]
    assert not result["error"] and result["retained"] and not result["running"]
