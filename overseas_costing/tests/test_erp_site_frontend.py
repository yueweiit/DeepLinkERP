"""多站点 ERP 同步界面：站点级预览、状态与只重试失败站点。

服务端那条链（预览/保存/账本/核对/重试）早就就绪，这里守住界面侧的几条硬要求：
站点与门槛只能来自服务端返回值、`MANUAL_REQUIRED` 不能渲染成成功、部分失败只能
重试失败的站点、推送前必须先摊开冻结预览、双击不产生第二次业务。
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "page" / "overseas_cost_workbench" / "parts"

#: 一份形状与 `preview_site_sync_plan` 真实返回一致的两站点计划。
PLAN_JS = """
const plan={ready:true,complete:true,cost_result_hash:'%s',batch_name:'B-1',version_name:'V-1',
  push_state:{blocking:[],preview:{blocking:[],source_total_cost_rmb:'5234.56',preview_total_cost_rmb:'5234.56',
    source_fee_total_rmb:'178.90',preview_allocated_fee_rmb:'178.90',
    sites:[
      {site_code:'DEEPLINKERP',total_cost_rmb:'5000.00',allocated_fee_rmb:'150.00',items:[{stable_line_key:'L1'},{stable_line_key:'L2'}],groups:[
        {site_code:'DEEPLINKERP',subsidiary_code:'拉丁购国际电子商务（东莞）有限公司',warehouse:'成品仓',supplier:'SUP-001',
         purchase_currency:'CNY',erp_stock_uom:'个：PCS',warnings:[],items:[{stable_line_key:'L1'},{stable_line_key:'L2'}],
         total_cost_rmb:'5000.00',allocated_fee_rmb:'150.00'}
      ]},
      {site_code:'MXSITE',total_cost_rmb:'234.56',allocated_fee_rmb:'28.90',items:[{stable_line_key:'L3'}],groups:[
        {site_code:'MXSITE',subsidiary_code:'YW MOLDES MX模具',warehouse:'MX-仓库',supplier:'SUP-002',
         purchase_currency:'MXN',erp_stock_uom:'套：SET',warnings:[],items:[{stable_line_key:'L3'}],
         total_cost_rmb:'234.56',allocated_fee_rmb:'28.90'}
      ]}
    ]}}};
""" % ("a" * 64)


def _erp_site_result(script: str) -> dict:
    source = (PARTS / "79-erp-sites.js").read_text(encoding="utf-8")
    completed = subprocess.run(
        [
            "node",
            "-e",
            (
                "const source=" + json.dumps(source) + ";"
                "const Harness=Function(`return class ErpSiteHarness {${source}}`)();"
                "global.alerts=[];"
                "global.frappe={show_alert:(value)=>global.alerts.push(value),"
                # `addClass` 记在 $wrapper 上（跟真实 jQuery 一致），别记到 Dialog 实例上。
                "ui:{Dialog:class{constructor(config){this.config=config;this.shown=false;"
                "this.$wrapper={classes:[],addClass(name){this.classes.push(name);}};}show(){this.shown=true;}hide(){this.shown=false;}}}};"
                f"(async()=>{{{script}}})().catch((error)=>{{console.error(error);process.exit(1)}});"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _harness(extra: str = "") -> str:
    return (
        "const w=Object.create(Harness.prototype);"
        "w.escape=v=>String(v??'');"
        "w.formatMoney=v=>String(v??'');"
        "w.detailState={batchName:'B-1',versionName:'V-1'};"
        "w.viewState={task:'erp'};"
        "w.$root={find:()=>({length:0,html:()=>{},replaceWith:()=>{}})};"
        "w.findBatch=()=>({name:'B-1',current_version:'V-1'});"
        "w.getDetailBatch=()=>({name:'B-1',current_version:'V-1',confirm_status:'Confirmed'});"
        + extra
    )


def test_manual_required_is_never_rendered_as_a_successful_push():
    result = _erp_site_result(_harness() + """
    const statuses=['PENDING','RUNNING','SUCCESS','FAILED','UNCERTAIN','MANUAL_REQUIRED','SUPERSEDED','WHATEVER'];
    console.log(JSON.stringify({
      meta:Object.fromEntries(statuses.map(s=>[s,w.erpSiteStatusMeta(s)])),
      chips:w.renderErpSiteStatusChips([{status:'SUCCESS'},{status:'SUCCESS'},{status:'MANUAL_REQUIRED'}]),
      manualRow:w.renderErpSiteLedgerRow({site_code:'MXSITE',status:'MANUAL_REQUIRED',request_id:'R-1',attempt_count:2}),
      failedRow:w.renderErpSiteLedgerRow({site_code:'MXSITE',status:'FAILED',request_id:'R-2'}),
      runningRow:w.renderErpSiteLedgerRow({site_code:'MXSITE',status:'RUNNING',request_id:'R-3'}),
      successRow:w.renderErpSiteLedgerRow({site_code:'MXSITE',status:'SUCCESS',request_id:'R-4'}),
    }));
    """)
    assert result["meta"]["MANUAL_REQUIRED"] == {"label": "需人工处理", "tone": "warn"}
    assert result["meta"]["UNCERTAIN"] == {"label": "结果待核对", "tone": "warn"}
    assert result["meta"]["FAILED"]["tone"] == "error"
    assert result["meta"]["SUCCESS"]["tone"] == "done"
    # 未知取值不猜成功，也不假装认得。
    assert result["meta"]["WHATEVER"] == {"label": "WHATEVER", "tone": "muted"}
    assert "已推送 2" in result["chips"] and "需人工处理 1" in result["chips"]
    assert "需人工处理" in result["manualRow"] and "已推送" not in result["manualRow"]
    # 终态不给"点了会被拒"的按钮：MANUAL_REQUIRED 调到服务端只会得到 SKIP。
    assert "erp-site-reconcile" not in result["manualRow"] and "erp-site-retry" not in result["manualRow"]
    assert "不会再自动重试" in result["manualRow"]
    assert "推送队列处理中" in result["runningRow"]
    # 只有结论未定的请求才给核对/重试入口。
    assert "data-action=\"erp-site-reconcile\"" in result["failedRow"]
    assert "data-action=\"erp-site-retry\"" in result["failedRow"]
    assert "erp-site-reconcile" not in result["successRow"]


def test_site_preview_takes_sites_companies_and_amounts_from_the_server_plan():
    result = _erp_site_result(_harness() + PLAN_JS + """
    const preview=w.erpSitePlanPreview(plan);
    const html=w.renderErpSiteSyncPreview(plan);
    console.log(JSON.stringify({preview,html,estimated:w.erpEstimatedFeeCount()}));
    """)
    preview = result["preview"]
    assert [site["site_code"] for site in preview["sites"]] == ["DEEPLINKERP", "MXSITE"]
    assert [site["itemCount"] for site in preview["sites"]] == [2, 1]
    assert preview["sites"][0]["companies"] == ["拉丁购国际电子商务（东莞）有限公司"]
    html = result["html"]
    assert "DEEPLINKERP" in html and "MXSITE" in html
    assert "拉丁购国际电子商务（东莞）有限公司" in html and "YW MOLDES MX模具" in html
    assert "SUP-001" in html and "成品仓" in html and "MXN / 套：SET" in html
    assert "5234.56" in html and "178.9" in html
    # 结果哈希是幂等键的来源，必须让用户看见它对应哪一版计算结果。
    assert "结果哈希 aaaaaaaaaaaa" in html
    assert "重复点击不会在远端多建一张采购单" in html


def test_partial_plan_says_which_groups_will_not_be_sent():
    result = _erp_site_result(_harness() + PLAN_JS + """
    const partial={...plan,complete:false,ready:true};
    partial.push_state.preview.blocking=[{code:'ITEM_ROUTE_REQUIRED',stable_line_key:'L9'},{code:'ITEM_WAREHOUSE_REQUIRED',stable_line_key:'L8'}];
    console.log(JSON.stringify({preview:w.renderErpSiteSyncPreview(partial),panel:(()=>{
      const st=w.ensureErpSiteState();st.plan=partial;st.ledger={items:[]};return w.renderErpSiteStatusPanel();
    })()}));
    """)
    assert "另有 2 个物料组未通过路由、供应商或仓库门槛" in result["preview"]
    assert "仅部分可推送" in result["panel"]
    assert "还有 2 个物料组未通过路由、供应商或仓库门槛" in result["panel"]


def test_site_panel_merges_the_local_ledger_onto_the_planned_sites():
    result = _erp_site_result(_harness() + PLAN_JS + """
    const st=w.ensureErpSiteState();
    st.plan=plan;
    st.ledger={ok:true,total:3,items:[
      {site_code:'DEEPLINKERP',status:'SUCCESS',request_id:'R-1',cost_result_hash:'b'.repeat(64)},
      {site_code:'MXSITE',status:'FAILED',request_id:'R-2',error_message:'远端返回 500',attempt_count:1},
      {site_code:'MXSITE',status:'UNCERTAIN',request_id:'R-3'}
    ]};
    console.log(JSON.stringify({panel:w.renderErpSiteStatusPanel(),visible:w.erpSitePanelVisible({confirm_status:'Confirmed'})}));
    """)
    panel = result["panel"]
    assert "2 个站点" in panel and "2 个单据组" in panel
    assert "已推送 1" in panel and "推送失败 1" in panel and "结果待核对 1" in panel
    # 两条没定论的请求各给一组核对/重试，成功的那条不给。
    assert panel.count("erp-site-reconcile") == 2
    assert panel.count("erp-site-retry") == 2
    assert "远端返回 500" in panel
    assert result["visible"] is True


def test_site_panel_stays_out_of_the_way_until_the_cost_result_is_confirmed():
    result = _erp_site_result(_harness() + """
    w.viewState={task:'pending'};
    console.log(JSON.stringify({
      pending:w.erpSitePanelVisible({confirm_status:'Pending',status:'Calculated'}),
      confirmed:w.erpSitePanelVisible({confirm_status:'Confirmed'}),
      markup:w.renderDetailErpSites({confirm_status:'Pending',status:'Calculated'}),
      erpQueue:(()=>{w.viewState={task:'erp'};const visible=w.erpSitePanelVisible({confirm_status:'Pending'});w.viewState={task:'pending'};return visible;})(),
    }));
    """)
    assert result["pending"] is False
    assert result["confirmed"] is True
    assert result["erpQueue"] is True
    # 未确认批次不该多出一块永远空的区域。
    assert result["markup"] == ""


def test_push_preview_shows_blockers_instead_of_a_confirmation_when_not_ready():
    result = _erp_site_result(_harness() + """
    let blocks=[],dialogs=0;
    w.showErpFlowBlock=(value,title)=>blocks.push({title,ready:value.ready});
    global.frappe.ui.Dialog=class{constructor(){dialogs++;}show(){}hide(){}};
    w.call=async()=>({ready:false,ok:false,blocking:[{code:'CALCULATION_CONFIRMATION_REQUIRED'}],batch_name:'B-1'});
    const dialog=await w.openErpSiteSyncDialog('B-1');
    console.log(JSON.stringify({blocks,dialogs,dialog:Boolean(dialog)}));
    """)
    # 阻断原因继续交给既有弹窗渲染，这里不另造一套文案。
    assert result["blocks"] == [{"title": "暂不能推送 ERP", "ready": False}]
    assert result["dialogs"] == 0
    assert result["dialog"] is False


def test_push_preview_confirm_pushes_once_through_the_existing_executor():
    result = _erp_site_result(_harness() + PLAN_JS + """
    let pushes=0,ignored=null,second=0;
    w.call=async(method,args)=>{
      if(method.endsWith('preview_site_sync_plan'))return plan;
      return {ok:true,items:[],total:0,batch_name:'B-1'};
    };
    w.queueErpWriteback=async(name)=>{pushes++;};
    w.showError=(error)=>{ignored=String(error&&error.message||error);};
    const dialog=await w.openErpSiteSyncDialog('B-1');
    // 连击是并发两次调用，不是先后两次：第二次必须在第一次还没回来时就被吞掉。
    await Promise.all([dialog.config.primary_action(),dialog.config.primary_action()]);
    w.queueErpWriteback=async()=>{second++;};
    const reopened=await w.openErpSiteSyncDialog('B-1');
    await reopened.config.primary_action();
    console.log(JSON.stringify({pushes,ignored,second,title:dialog.config.title,classes:dialog.$wrapper.classes,shown:dialog.shown}));
    """)
    # 一次确认只对应一次业务推送 —— 双击不该在远端多建一张采购单。
    assert result["pushes"] == 1
    assert result["ignored"] is None
    assert result["title"] == "ERP 站点推送预览（2 个站点）"
    assert result["classes"] == ["ocw-erp-site-dialog"]
    assert result["shown"] is False
    # 守卫只挡同一次确认里的连击，不封死后续推送。
    assert result["second"] == 1


def test_reconcile_and_retry_are_batch_scoped_and_do_not_double_fire():
    result = _erp_site_result(_harness() + PLAN_JS + """
    const calls=[];
    w.call=async(method,args)=>{
      calls.push({method,args});
      if(method.endsWith('preview_site_sync_plan'))return plan;
      if(method.endsWith('get_site_sync_requests'))return {ok:true,items:[],total:0};
      return {ok:true,message:'远端已核对，确认没有单据后重发',status:'FAILED'};
    };
    const st=w.ensureErpSiteState();st.plan=plan;
    await Promise.all([w.retryErpSiteRequest('R-2'),w.retryErpSiteRequest('R-2')]);
    await w.reconcileErpSiteRequest('R-3');
    console.log(JSON.stringify({calls,alerts:global.alerts,blank:await w.retryErpSiteRequest('')}));
    """)
    methods = [call["method"] for call in result["calls"]]
    assert methods.count("overseas_costing.api.writeback.retry_erp_request") == 1
    assert "overseas_costing.api.writeback.reconcile_erp_request" in methods
    # 请求必须在批次内定位：账本按 (batch, request_id) 查，防跨批次误操作。
    retry = next(call for call in result["calls"] if call["method"].endswith("retry_erp_request"))
    assert retry["args"] == {"batch_name": "B-1", "request_id": "R-2"}
    assert result["blank"] is None


def test_writeback_button_opens_the_frozen_preview_instead_of_a_blind_confirm():
    source = (PARTS / "30-calculation-erp.js").read_text(encoding="utf-8")
    writeback = source.split("writebackToErp(batchName = \"\")", 1)[1].split("async queueErpWriteback", 1)[0]

    assert "frappe.confirm" not in writeback
    assert "openErpSiteSyncDialog(batch.name)" in writeback
    # 执行入口没有被换掉：预览只是确认前的门，推送仍走同一条账本链路。
    assert "queueErpWriteback" in source.split("openErpSiteSyncDialog(batch.name)", 1)[1][:400]
