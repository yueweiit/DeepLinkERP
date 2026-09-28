"""多站点 ERP 同步界面：站点级预览、站点状态与只重试失败站点。

服务端那条链（预览/保存/账本/核对/重试）早就就绪，这里守住界面侧的几条硬要求：
站点与门槛只能来自服务端返回值、站点状态只能来自服务端 `erp_work` 投影、
终态不能渲染成成功、推送前必须先摊开冻结预览、双击不产生第二次业务。
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "page" / "overseas_cost_workbench" / "parts"

#: 一份形状与 `preview_site_sync_plan` 真实返回一致的两站点计划（含站点级 `erp_work` 投影）。
PLAN_JS = """
const plan={ready:true,complete:true,cost_result_hash:'%s',batch_name:'B-1',version_name:'V-1',
  erp_work:{overall:'PARTIAL',current_cost_result_hash:'%s',todo_count:2,
    counts:{SYNCED:0,UPDATE_REQUIRED:1,IN_PROGRESS:0,ATTENTION_REQUIRED:0,NOT_PUSHED:1},
    sites:[
      {site_code:'DEEPLINKERP',state:'NOT_PUSHED',cost_result_hash:'',request_id:'',status:'',
       attempt_count:0,error_code:'',error_message:'',
       todo:{code:'ERP_SYNC_REQUIRED',severity:'warning',action:'preview_site_sync',label:'该站点还没有推送当前计算结果'}},
      {site_code:'MXSITE',state:'UPDATE_REQUIRED',cost_result_hash:'b'.repeat(64),request_id:'R-2',status:'SUCCESS',
       attempt_count:1,error_code:'',error_message:'',
       todo:{code:'ERP_UPDATE_REQUIRED',severity:'warning',action:'review_erp_document',label:'该站点已同步的不是当前计算结果'}}
    ]},
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
""" % (("a" * 64), ("a" * 64))


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


def test_terminal_and_unknown_states_are_never_rendered_as_a_successful_push():
    result = _erp_site_result(_harness() + """
    const states=['SYNCED','UPDATE_REQUIRED','IN_PROGRESS','ATTENTION_REQUIRED','NOT_PUSHED','WHATEVER'];
    const overalls=['EMPTY','NOT_STARTED','IN_PROGRESS','PARTIAL','UPDATE_REQUIRED','ATTENTION_REQUIRED','SYNCED'];
    console.log(JSON.stringify({
      meta:Object.fromEntries(states.map(s=>[s,w.erpSiteStateMeta(s)])),
      overall:Object.fromEntries(overalls.map(s=>[s,w.erpSiteOverallMeta(s)])),
      manual:w.renderErpSiteTodoRow({site_code:'MXSITE',state:'ATTENTION_REQUIRED',status:'MANUAL_REQUIRED',
        request_id:'R-1',attempt_count:2,error_message:'稳定业务键命中多张采购单',
        todo:{code:'ERP_MANUAL_REQUIRED',severity:'error',action:'review_erp_document',label:'该站点的同步请求需要人工处理'}}),
      uncertain:w.renderErpSiteTodoRow({site_code:'MXSITE',state:'ATTENTION_REQUIRED',status:'UNCERTAIN',request_id:'R-2',
        todo:{code:'ERP_RECONCILE_REQUIRED',severity:'error',action:'reconcile_erp',label:'该站点的同步结果未确定，请核对远端'}}),
      synced:w.renderErpSiteStateChip({site_code:'P',state:'SYNCED',todo:null}),
      unknown:w.renderErpSiteStateChip({site_code:'P',state:'WHATEVER'}),
    }));
    """)
    assert result["meta"]["SYNCED"] == {"label": "已同步", "tone": "done"}
    assert result["meta"]["UPDATE_REQUIRED"]["tone"] == "warn"
    assert result["meta"]["ATTENTION_REQUIRED"]["tone"] == "error"
    # 未推送 / 认不出的状态都不许出现"已同步"的意思。
    assert result["meta"]["NOT_PUSHED"]["tone"] == "muted"
    assert result["meta"]["WHATEVER"] == {"label": "WHATEVER", "tone": "muted"}
    assert result["overall"]["ATTENTION_REQUIRED"]["tone"] == "error"
    assert result["overall"]["PARTIAL"]["tone"] == "warn"
    assert result["overall"]["EMPTY"]["tone"] == "muted" and result["overall"]["NOT_STARTED"]["tone"] == "muted"
    # 核对/重试入口只给服务端说可核对的那种待办：其余状态调到服务端只会得到 SKIP。
    assert "erp-site-reconcile" not in result["manual"] and "erp-site-retry" not in result["manual"]
    assert "需要人工处理" in result["manual"] and "稳定业务键命中多张采购单" in result["manual"]
    assert "data-action=\"erp-site-reconcile\"" in result["uncertain"]
    assert "data-action=\"erp-site-retry\"" in result["uncertain"]
    assert "已同步" in result["synced"] and "is-done" in result["synced"]
    assert "已同步" not in result["unknown"]


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


def test_site_panel_reads_the_server_projection_instead_of_deriving_states():
    """站点状态只来自服务端 `erp_work`，页面不再从账本行自己推一遍。"""

    result = _erp_site_result(_harness() + PLAN_JS + """
    const st=w.ensureErpSiteState();
    st.plan=plan;
    console.log(JSON.stringify({panel:w.renderErpSiteStatusPanel(),visible:w.erpSitePanelVisible({confirm_status:'Confirmed'})}));
    """)
    panel = result["panel"]
    assert "2 个站点" in panel and "2 个单据组" in panel
    # 两个站点一个是「未推送」、一个是「同步的是旧成本」，且整体口径跟着走。
    assert "未推送" in panel and "同步的是旧成本" in panel
    assert "部分站点未推送" in panel
    assert "还欠处理的站点（2 个）" in panel
    assert "该站点还没有推送当前计算结果" in panel
    assert "该站点已同步的不是当前计算结果" in panel
    # 这两条待办都不是「核对远端」那类，所以一个必然被拒的按钮都不该出现。
    assert panel.count("erp-site-reconcile") == 0
    assert panel.count("erp-site-retry") == 0
    assert "结果哈希 bbbbbbbbbbbb" in panel
    assert result["visible"] is True


def test_missing_server_projection_is_never_read_as_synced():
    """服务端没给站点状态时显示「状态未知」，绝不默认成功。"""

    result = _erp_site_result(_harness() + PLAN_JS + """
    const bare={...plan};delete bare.erp_work;
    const st=w.ensureErpSiteState();st.plan=bare;
    console.log(JSON.stringify({panel:w.renderErpSiteStatusPanel(),work:w.erpSiteWork(bare,null)}));
    """)
    assert result["work"] is None
    assert "状态未知" in result["panel"]
    assert "已同步" not in result["panel"]
    assert "还欠处理的站点" not in result["panel"]


def test_push_preview_lists_the_sites_that_still_owe_a_push():
    result = _erp_site_result(_harness() + PLAN_JS + """
    console.log(JSON.stringify({note:w.renderErpSiteOverdueNote(plan),empty:w.renderErpSiteOverdueNote({})}));
    """)
    assert "该站点还没有推送当前计算结果（DEEPLINKERP）" in result["note"]
    assert "该站点已同步的不是当前计算结果（MXSITE）" in result["note"]
    # 没有欠账的批次不该多一句噪音。
    assert result["empty"] == ""


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
