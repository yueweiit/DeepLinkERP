from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "page" / "overseas_cost_workbench" / "parts"


def _state_result(script: str) -> dict:
    state_file = PARTS / "05-workbench-state.js"
    completed = subprocess.run(
        ["node", "-e", f"const s=require({json.dumps(str(state_file))}); {script}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _fee_workspace_result(script: str) -> dict:
    workspace_file = PARTS / "78-material-fee-workspace.js"
    grid_file = PARTS / "79-material-import-grid.js"
    completed = subprocess.run(
        [
            "node",
            "-e",
            (
                "const fs=require('fs');"
                f"const gridFile={json.dumps(str(grid_file))};"
                f"const source=fs.readFileSync({json.dumps(str(workspace_file))},'utf8')+(fs.existsSync(gridFile)?fs.readFileSync(gridFile,'utf8'):'');"
                "const Harness=Function(`return class FeeWorkspaceHarness {${source}}`)();"
                "global.frappe={show_alert:(value)=>global.alerts.push(value)};"
                "global.alerts=[];"
                f"(async()=>{{{script}}})().catch((error)=>{{console.error(error);process.exit(1)}});"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _detail_workspace_result(script: str) -> dict:
    workspace_file = PARTS / "82-detail-page.js"
    completed = subprocess.run(
        [
            "node",
            "-e",
            (
                "const fs=require('fs');"
                f"const source=fs.readFileSync({json.dumps(str(workspace_file))},'utf8');"
                "const Harness=Function(`return class DetailWorkspaceHarness {${source}}`)();"
                "global.alerts=[];global.frappe={show_alert:(value)=>global.alerts.push(value)};"
                "global.window={clearInterval:()=>{},setInterval:()=>42};"
                f"(async()=>{{{script}}})().catch((error)=>{{console.error(error);process.exit(1)}});"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


FEE_INPUT_FIXTURE = r"""
function makeFeeInput({amount, currency, originalAmount, originalCurrency, forceActual=false, feeKey='international_sea_freight'}) {
  const classes = new Set();
  const data = {};
  const attrs = {title: ''};
  const errorElement = {
    length: 1,
    value: '',
    hidden: true,
    text(next) { if (arguments.length > 0) { this.value = next; return this; } return this.value; },
    attr(name, next) { if (arguments.length > 1) { this[name] = next; return this; } return this[name]; },
    toggleClass(name, enabled) { if (name === 'is-visible') this.hidden = !enabled; return this; },
  };
  const amountInput = makeInput('amount', amount, originalAmount);
  const currencyInput = makeInput('currency', currency, originalCurrency);
  function makeInput(kind, value, original) {
    return {
      length: 1,
      kind,
      value,
      disabled: false,
      attrs: {
        'data-fee-key': feeKey,
        'data-mf-fee-input': kind,
        'data-original-value': original,
        ...(kind === 'amount' && forceActual ? {'data-mf-force-actual': '1'} : {}),
      },
      val(next) { if (arguments.length > 0) { this.value = next; return this; } return this.value; },
      attr(name, next) { if (arguments.length > 1) { this.attrs[name] = next; return this; } return this.attrs[name]; },
      data(name, next) { if (arguments.length > 1) { data[name] = next; return this; } return data[name]; },
      prop(name, next) { if (name === 'disabled') this.disabled = next; return this; },
      closest() { return cell; },
    };
  }
  const collection = {
    prop(name, next) { amountInput.prop(name, next); currencyInput.prop(name, next); return this; },
    attr(name, next) { amountInput.attr(name, next); currencyInput.attr(name, next); return this; },
  };
  const cell = {
    data(name, next) { if (arguments.length > 1) { data[name] = next; return this; } return data[name]; },
    addClass(name) { classes.add(name); return this; },
    removeClass(name) { name.split(/\s+/).forEach((item) => classes.delete(item)); return this; },
    hasClass(name) { return classes.has(name); },
    attr(name, next) { if (arguments.length > 1) { attrs[name] = next; return this; } return attrs[name]; },
    find(selector) {
      if (selector === '[data-mf-fee-amount]') return amountInput;
      if (selector === '[data-mf-fee-currency]') return currencyInput;
      if (selector === '[data-mf-fee-error]') return errorElement;
      return collection;
    },
  };
  amountInput.cell = cell;
  currencyInput.cell = cell;
  return {amountInput, currencyInput, errorElement, cell, classes, attrs};
}
"""


def test_dingtalk_detail_tab_has_stable_url_and_resource() -> None:
    result = _state_result(
        "console.log(JSON.stringify({"
        "tab:s.parseWorkbenchState('https://example.test/desk/overseas-cost-workbench?screen=detail&tab=dingtalk').tab,"
        "resource:s.detailTabResource('dingtalk')}));"
    )

    assert result == {"tab": "dingtalk", "resource": "dingtalk"}


def test_module_rail_is_not_confused_with_workspace_sidebar() -> None:
    bootstrap = (PARTS / "00-bootstrap.js").read_text(encoding="utf-8")
    shell = (PARTS / "10-shell.js").read_text(encoding="utf-8")

    ensure_block = bootstrap.split("function ensureDeskModuleSidebar", 1)[1].split(
        "function syncWorkspaceSidebarHeaderIcon", 1
    )[0]
    assert '$(".body-sidebar-container' not in ensure_block
    assert ".custom-filters-right-sidebar-container" in ensure_block
    hide_block = shell.split("hideDeskChrome()", 1)[1].split("restoreDeskChrome()", 1)[0]
    assert ".custom-filters-right-sidebar-container" not in hide_block
    on_show = bootstrap.split('frappe.pages["overseas-cost-workbench"].on_page_show', 1)[1]
    assert "applyModuleSidebarPreference()" in on_show


def test_workspace_header_reuses_authorized_desktop_icon_and_restores_original() -> None:
    bootstrap = (PARTS / "00-bootstrap.js").read_text(encoding="utf-8")
    shell = (PARTS / "10-shell.js").read_text(encoding="utf-8")
    stylesheet = (PARTS / "20-desk-layout.css").read_text(encoding="utf-8")

    assert "function syncWorkspaceSidebarHeaderIcon" in bootstrap
    assert "frappe.boot.desktop_icons" in bootstrap
    assert ".body-sidebar-container .sidebar-header > .sidebar-item-icon" in bootstrap
    assert "desktopIcon.logo_url || desktopIcon.icon_image" in bootstrap
    assert "ocw-workspace-sidebar-icon" in bootstrap
    assert "_workspaceSidebarIconSnapshot" in shell
    assert ".ocw-workspace-sidebar-icon" in stylesheet
    slot_selector = ".body-sidebar-container .sidebar-header > .sidebar-item-icon {"
    assert slot_selector in stylesheet
    slot_rule = stylesheet.split(slot_selector, 1)[1].split("}", 1)[0]
    assert "width: 32px" in slot_rule
    assert "height: 32px" in slot_rule
    assert "flex: 0 0 32px" in slot_rule


def test_generated_workbench_assets_include_dingtalk_parts_and_match_deployed_copy() -> None:
    page = ROOT / "page" / "overseas_cost_workbench"
    deployed = ROOT / "overseas_costing" / "page" / "overseas_cost_workbench"
    javascript = (page / "overseas_cost_workbench.js").read_text(encoding="utf-8")
    stylesheet = (page / "overseas_cost_workbench.css").read_text(encoding="utf-8")

    assert "renderDingtalkApprovalTab" in javascript
    assert "openDingtalkPackingSourcePicker" in javascript
    assert ".ocw-dingtalk-approval-card" in stylesheet
    assert javascript == (deployed / "overseas_cost_workbench.js").read_text(encoding="utf-8")
    assert stylesheet == (deployed / "overseas_cost_workbench.css").read_text(encoding="utf-8")


def test_packing_flow_source_switch_clears_unconfirmed_preview() -> None:
    result = _state_result(
        "let state=s.createPackingFlowState();"
        "state=s.selectPackingSource(state,'manual_attachment','ATT-1');"
        "state=s.applyPackingPreview(state,{source_revision:'old',groups:[],validation:{blocking:[]},totals:{gross_weight_kg:{value:'10'},volume_m3:{value:'2'}}});"
        "state=s.selectPackingSource(state,'wiki_sheet','WB:ST-1');"
        "console.log(JSON.stringify({kind:state.sourceKind,id:state.sourceId,preview:state.preview,snapshot:state.snapshot,step:state.step}));"
    )

    assert result == {
        "kind": "wiki_sheet",
        "id": "WB:ST-1",
        "preview": None,
        "snapshot": None,
        "step": 1,
    }


def test_packing_flow_requires_group_resolution_before_step_three() -> None:
    result = _state_result(
        "let state=s.selectPackingSource(s.createPackingFlowState(),'wiki_sheet','WB:ST-1');"
        "state=s.applyPackingPreview(state,{source_revision:'rev-1',groups:[{group_id:'G-1',needs_confirmation:true}],validation:{blocking:[{code:'group_confirmation_required'}]},totals:{gross_weight_kg:{value:'10'},volume_m3:{value:'2'}}});"
        "const before=state.canCompare;"
        "state=s.resolvePackageGroup(state,'G-1','confirm_shared');"
        "console.log(JSON.stringify({before,after:state.canCompare,action:state.resolutions.groups['G-1'].action}));"
    )

    assert result == {"before": False, "after": True, "action": "confirm_shared"}


def test_packing_flow_requires_total_basis_and_supports_explicit_row_partition() -> None:
    result = _state_result(
        "let state=s.selectPackingSource(s.createPackingFlowState(),'wiki_sheet','WB:ST-1');"
        "state=s.applyPackingPreview(state,{source_revision:'rev-1',groups:[{group_id:'G-1',row_numbers:[2,3,4],needs_confirmation:true}],validation:{blocking:[{code:'group_confirmation_required'},{code:'total_mismatch',field:'gross_weight_kg'}]},totals:{gross_weight_kg:{value:'0',declared_value:'0',calculated_value:'10'},volume_m3:{value:'2'}}});"
        "state=s.resolvePackageGroupRows(state,'G-1',[2,3,4],[2,3]);"
        "const before=state.canCompare;"
        "state=s.resolvePackingTotal(state,'gross_weight_kg','use_calculated');"
        "console.log(JSON.stringify({before,after:state.canCompare,group:state.resolutions.groups['G-1'],total:state.resolutions.totals.gross_weight_kg}));"
    )

    assert result == {
        "before": False,
        "after": True,
        "group": {"action": "partition", "partitions": [[2, 3], [4]]},
        "total": {"action": "use_calculated"},
    }


def test_freight_quote_requires_scope_confirmation_and_remark() -> None:
    result = _state_result(
        "const base={currency:'USD',weight_unit_price:'1',volume_unit_price:'2'};"
        "const missing=s.buildFreightQuotePayload(null,base);"
        "const ready=s.buildFreightQuotePayload(null,{...base,scope_confirmed:true,quote_remark:'same route'});"
        "console.log(JSON.stringify({missing:s.freightQuoteIsReady(missing),ready:s.freightQuoteIsReady(ready)}));"
    )

    assert result == {"missing": False, "ready": True}


def test_packing_flow_refresh_replaces_preview_and_quote_has_no_formal_cost_action() -> None:
    result = _state_result(
        "let state=s.selectPackingSource(s.createPackingFlowState(),'wiki_sheet','WB:ST-1');"
        "state=s.applyPackingPreview(state,{source_revision:'old',groups:[{group_id:'OLD'}],material_rows:[{material_code:'OLD'}],validation:{blocking:[]},totals:{gross_weight_kg:{value:'10'},volume_m3:{value:'2'}}});"
        "state=s.applyPackingPreview(state,{source_revision:'new',groups:[{group_id:'NEW'}],material_rows:[{material_code:'NEW'}],validation:{blocking:[]},totals:{gross_weight_kg:{value:'20'},volume_m3:{value:'3'}}});"
        "const quote=s.buildFreightQuotePayload(state,{currency:'usd',scope_confirmed:true,weight_unit_price:'1.2',volume_unit_price:'500',weight_surcharge:'10',volume_surcharge:'20',quote_remark:'test'});"
        "console.log(JSON.stringify({revision:state.preview.source_revision,groups:state.preview.groups.map(x=>x.group_id),rows:state.preview.material_rows.map(x=>x.material_code),quote,hasAction:Object.prototype.hasOwnProperty.call(quote,'action')}));"
    )

    assert result == {
        "revision": "new",
        "groups": ["NEW"],
        "rows": ["NEW"],
        "quote": {
            "currency": "USD",
            "scope_confirmed": True,
            "weight": {"unit_price": "1.2", "surcharge": "10"},
            "volume": {"unit_price": "500", "surcharge": "20"},
            "quote_remark": "test",
        },
        "hasAction": False,
    }


def test_packing_flow_static_ui_contract() -> None:
    flow = (PARTS / "86-packing-flow.js").read_text(encoding="utf-8")
    documents = (PARTS / "65-manual-documents.js").read_text(encoding="utf-8")
    stylesheet = (PARTS / "47-packing-flow.css").read_text(encoding="utf-8")
    source_service = (ROOT / "services" / "packing_source_service.py").read_text(encoding="utf-8")

    for label in (
        "本地上传",
        "钉钉审批附件/评论",
        "装箱计划表",
        "刷新列表",
        "刷新资料",
        "系统推荐",
        "预览这张装箱计划",
        "共享箱级数据",
        "保存草稿",
        "下一步：比较运费",
        "独立试算，不修改正式费用",
        "保存比较结果",
        "选择表内合计",
        "选择明细加总",
    ):
        assert label in flow
    assert "获取装箱单" in documents
    assert "openPackingFlowDialog" in flow
    assert "localStorage.getItem" in flow
    assert 'dialog.packingSourceTab = options.sourceTab || "wiki"' in flow
    assert flow.index('["wiki", "装箱计划表"]') < flow.index('["approval", "钉钉审批附件/评论"]')
    assert flow.index('["approval", "钉钉审批附件/评论"]') < flow.index('["local", "本地上传"]')
    assert "selectRecommendedPackingSource" in flow
    assert "auto_select_recommended" in flow
    assert "recommendation_reasons" in flow
    assert "business_date" in flow
    assert "知识库年度表" not in flow
    assert "需要刷新的年度表" not in flow
    assert "钉钉知识库刷新失败" not in flow
    assert "知识库 Sheet" not in source_service
    assert ".ocw-packing-flow" in stylesheet
    assert ".ocw-packing-recommendation" in stylesheet
    assert "position: sticky" in stylesheet
    dialog_rule = stylesheet.split(".ocw-packing-flow-dialog {", 1)[1].split("}", 1)[0]
    assert "--ocw-brand: #0b8cf0" in dialog_rule
    assert "--ocw-brand-dark: #076fbe" in dialog_rule
    assert "--ocw-brand-soft: #eaf5ff" in dialog_rule


def test_interactive_theme_uses_deeplink_blue_without_legacy_teal() -> None:
    redesign = (PARTS / "25-workbench-redesign.css").read_text(encoding="utf-8").lower()
    detail = (PARTS / "45-detail-page.css").read_text(encoding="utf-8").lower()
    all_styles = "\n".join(path.read_text(encoding="utf-8").lower() for path in PARTS.glob("*.css"))

    assert "--ocw-accent: #0b8cf0" in redesign
    assert "--ocw-accent-dark: #076fbe" in redesign
    assert "--ocw-accent-soft: #eaf5ff" in redesign
    for legacy_teal in ("#087d82", "#05666b", "#e9f7f6", "rgba(8, 125, 130", "#318e92"):
        assert legacy_teal not in redesign + detail
    for legacy_interactive_color in (
        "#0877d1",
        "#0d8bf2",
        "#0876d1",
        "#075fa5",
        "#cfe2dc",
        "#eef8f4",
        "#8ac8c1",
        "#f5fbfa",
        "#e9f5f3",
    ):
        assert legacy_interactive_color not in all_styles
    assert ".ocw-issue.is-ready { color: #067647; }" in redesign


def test_dingtalk_timeline_renders_name_as_primary_and_id_as_secondary() -> None:
    approval_page = (PARTS / "84-dingtalk-approval.js").read_text(encoding="utf-8")

    assert "renderDingtalkActor" in approval_page
    assert "ocw-dingtalk-actor-id" in approval_page
    assert "姓名未同步" in approval_page
    assert "excluded_linked_purchase_approvals" in approval_page
    assert "已排除审批" in approval_page
    assert "approval && !approval.excluded" in approval_page
    assert "renderDingtalkTimeline(approval.timeline || [], !approval.excluded)" in approval_page
    assert "renderDingtalkAttachments(approval.attachments || [], !approval.excluded)" in approval_page


def test_overview_reconciles_purchase_approval_status_from_postgres_detail() -> None:
    detail_page = (PARTS / "82-detail-page.js").read_text(encoding="utf-8")
    approval_page = (PARTS / "84-dingtalk-approval.js").read_text(encoding="utf-8")

    overview_block = detail_page.split("renderOverviewDetailTab()", 1)[1].split(
        "detailDocumentAdapter()", 1
    )[0]
    assert "this.loadDingtalkApprovalDetail()" in overview_block
    assert 'this.detailState.tab === "overview"' in overview_block
    assert "approval.batch_name !== batch.name" in overview_block

    assert "syncPurchaseApprovalStatusFromDingtalk" in approval_page
    assert 'excluded.length ? (approvals.length ? "partial" : "excluded") : "valid"' in approval_page
    assert 'sourceStatus.invalid_business = true' in approval_page
    assert 'sourceStatus.invalid_business_scope = "linked_purchase_approval"' in approval_page
    assert 'sourceStatus.invalid_business = false' in approval_page
    assert "linked_purchase_approval_statuses" in approval_page
    assert "if (attachmentName) return attachmentName;" not in approval_page
    assert "processInstanceId && fileId" in approval_page


def test_documents_tab_is_replaced_only_by_phase_one_material_fee_workspace() -> None:
    detail_page = (PARTS / "82-detail-page.js").read_text(encoding="utf-8")
    workspace = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    workspace += (PARTS / "79-material-import-grid.js").read_text(encoding="utf-8")
    stylesheet = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    documents_block = detail_page.split("async renderDocumentsDetailTab()", 1)[1].split(
        "async renderVoucherDetailTab()", 1
    )[0]

    assert "loadMaterialFeeWorkspace" in documents_block
    assert "renderManualDocumentPanel" not in documents_block
    for label in (
        "费用与凭证",
        "开始试算",
        "物料与装箱数据",
            "只看缺项",
            "展开辅助列",
            "获取装箱资料",
            "AI 填充装箱数据",
            "本地上传装箱单",
        "确认写入物料表",
        "净重 kg",
        "查看资料来源",
        "详细待办",
        "SKU 综合单价试算",
    ):
        assert label in workspace
    for endpoint in (
        "overseas_costing.api.materials.get_material_grid",
        "overseas_costing.api.materials.set_shipping_quantity",
        "overseas_costing.api.materials.preview_material_import",
        "overseas_costing.api.materials.apply_material_import",
        "overseas_costing.api.packing_api.list_packing_sources",
        "overseas_costing.api.packing_api.request_packing_sheet_refresh",
        "overseas_costing.api.calculate.update_item_field",
        "overseas_costing.api.calculate.batch_update_items",
        "overseas_costing.api.fees.get_fee_worklist",
        "overseas_costing.api.fees.save_fee",
        "overseas_costing.api.fees.link_fee_evidence",
        "overseas_costing.api.fees.set_fee_evidence_status",
        "overseas_costing.api.calculate.preview_comprehensive_cost",
        "overseas_costing.api.import_api.preview_oa_source_attachment",
    ):
        assert endpoint in workspace
    assert "带入费用表" in workspace
    assert "openWikiMaterialImportDialog" in workspace
    assert "previewWikiMaterialImport" in workspace
    assert "data-mf-wiki-source" in workspace
    assert "shared_groups" in workspace
    assert "confirmation_groups" in workspace
    assert "row_states" in workspace
    assert "candidate_regions" in workspace
    assert "批次外与未匹配行" in workspace
    assert "candidate?.reason" in workspace
    assert "批次外疑似合并组" not in workspace
    assert "source_fields" in workspace
    assert "merged_source_fields" in workspace
    assert "MERGED_PREVIEW_CONFIRMATION_REQUIRED" in workspace
    assert "已生成合并后的最终预览，请核对后确认写入" in workspace
    assert "group_confirmations" in workspace
    assert "allocations" in workspace
    assert "source_validation" in workspace
    assert "data-mf-source-validation" in workspace
    assert "DUPLICATE_TARGET_SELECTION" in workspace
    assert "本次未识别出金额，可手工补录" in workspace
    assert "writeback" not in workspace.lower()
    assert "recalculate" not in workspace.lower()
    assert ".ocw-mf-workspace" in stylesheet
    assert ".ocw-mf-cell.is-missing" in stylesheet
    assert ".ocw-mf-cell.is-default" in stylesheet
    assert ".ocw-mf-cell.is-save-error" in stylesheet


def test_fee_workspace_pending_evidence_is_linked_without_inflating_missing_count() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1'};"
        "workspace.materialFeeState={batchName:'B-1',materials:{missing_cell_count:0,items:[]},"
        "fees:{summary:{missing_evidence_fee_count:2,pending_evidence_fee_count:7},fees:[]},"
        "preview:{summary:{total_cost_rmb:'0.00'}}};"
        "workspace.escape=(value)=>String(value ?? '');"
        "workspace.formatValue=(value)=>String(value);"
        "workspace.renderMaterialFeeGrid=()=>'';workspace.renderMaterialFeeTodos=()=>'';"
        "workspace.renderMaterialFeeCostTable=()=>'';"
        "let html='';workspace.$root={find:()=>({html:(value)=>{html=value}})};"
        "workspace.renderMaterialFeeWorkspace();"
        "const row=workspace.renderMaterialFeeRow({logical_fee_key:'import_tax',expense_category:'\u8fdb\u53e3\u7a0e\u8d39',"
        "amount_status:'ACTUAL',amount:'2000',currency:'RMB',allocation:{status:'ALLOCATED'},"
        "evidence_state:'PENDING',evidence:[{name:'EV-1',evidence_role:'tax_certificate',validation_status:'PENDING'}]});"
        "console.log(JSON.stringify({metric:html.includes('<span>\u51ed\u8bc1\u5f85\u8865</span><strong>2</strong>'),"
        "linked:row.includes('is-info')&&row.includes('\u5df2\u5173\u8054'),"
        "pending:row.includes('\u7ec8\u6838\u72b6\u6001\uff1a\u5f85\u6838\u5bf9'),"
        "actions:row.includes('\u786e\u8ba4\u6709\u6548')&&row.includes('\u6807\u8bb0\u65e0\u6548')}));"
    )

    assert result == {"metric": True, "linked": True, "pending": True, "actions": True}


def test_fee_workspace_missing_saved_amount_is_visible_inline_and_keeps_more_settings() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);workspace.escape=(value)=>String(value ?? '');"
        "workspace.formatValue=(value)=>String(value);"
        "const row=workspace.renderMaterialFeeRow({logical_fee_key:'destination_delivery',"
        "expense_category:'\u76ee\u7684\u5730\u914d\u9001\u8d39',amount_status:'MISSING',amount:'2000',currency:'RMB',"
        "allocation_basis:'gross_weight',scope_type:'ALL_ITEMS',allocation:{status:'NOT_ALLOCATED'},evidence:[]});"
        "console.log(JSON.stringify({amount:row.includes('data-mf-fee-amount')&&row.includes('value=\"2000\"'),"
        "currency:row.includes('data-mf-fee-currency')&&row.includes('value=\"RMB\"'),"
        "notCounted:row.includes('\u5c1a\u672a\u8ba1\u5165'),forceActual:row.includes('data-mf-force-actual=\"1\"'),"
        "more:row.includes('\u66f4\u591a\u8bbe\u7f6e')}));"
    )

    assert result == {
        "amount": True,
        "currency": True,
        "notCounted": True,
        "forceActual": True,
        "more": True,
    }


def test_express_default_zero_row_explains_mexico_confirmation_without_actual_marker():
    from overseas_costing.services.fee_service import build_default_fee_templates
    fee = build_default_fee_templates('EXPRESS')[-1]
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);workspace.escape=(value)=>String(value ?? '');"
        f"const fee={json.dumps(fee, ensure_ascii=False)};"
        "console.log(JSON.stringify({html:workspace.renderMaterialFeeRow(fee)}));"
    )
    html = result['html']
    assert '当地快递费' in html
    assert 'value="MXN" selected' in html and 'value="0"' in html
    assert '默认暂估 0，待墨西哥确认' in html
    assert '由墨西哥同事补充' in html
    assert 'data-mf-force-actual="1"' not in html


def test_conflicting_fee_row_shows_saved_row_and_conflicts_without_edit_controls():
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);workspace.escape=(value)=>String(value ?? '');"
        "const fee={name:'OA-ROW',logical_fee_key:'international_air_freight',expense_category:'国际空运费',"
        "amount:20360,currency:'RMB',amount_status:'ESTIMATED',requires_review:true,"
        "duplicate_rule_names:['OA-ROW','MANUAL-ROW'],evidence:[{name:'E1',evidence_role:'freight_invoice'}]};"
        "console.log(JSON.stringify({html:workspace.renderMaterialFeeRow(fee)}));"
    )
    html = result['html']
    assert '费用重复' in html and 'OA-ROW' in html and 'MANUAL-ROW' in html
    assert '20360' in html and 'freight_invoice' in html
    assert 'data-mf-fee-input' not in html and 'data-action="mf-edit-fee"' not in html
    assert '已计入试算' not in html


@pytest.mark.parametrize('amount,currency,key', [('', 'MXN', 'import_tax'), ('0', 'MXN', 'destination_delivery'), ('0', 'RMB', 'express_surcharge')])
def test_untouched_mexico_fee_input_never_saves_or_reports_empty_error(amount, currency, key):
    result = _fee_workspace_result(FEE_INPUT_FIXTURE + f"""
const workspace=Object.create(Harness.prototype);workspace.detailState={{batchName:'B-1'}};
const state=workspace.ensureMaterialFeeState();
const fixture=makeFeeInput({{amount:{json.dumps(amount)},originalAmount:{json.dumps(amount)},currency:{json.dumps(currency)},originalCurrency:{json.dumps(currency)},feeKey:{json.dumps(key)}}});
let writes=0;workspace.call=async()=>{{writes++;throw new Error('Untouched input must not write')}};
await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);
console.log(JSON.stringify({{writes,error:fixture.errorElement.value,drafts:state.feeDrafts}}));
""")
    assert result == {'writes': 0, 'error': '', 'drafts': {}}


def test_clearing_saved_mexico_fee_still_requires_an_amount():
    result = _fee_workspace_result(FEE_INPUT_FIXTURE + """
const workspace=Object.create(Harness.prototype);workspace.detailState={batchName:'B-1'};
const fixture=makeFeeInput({amount:'',originalAmount:'100',currency:'MXN',originalCurrency:'MXN',feeKey:'import_tax'});
await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);
console.log(JSON.stringify({error:fixture.errorElement.value}));
""")
    assert '费用金额不能为空' in result['error']


def test_fee_workspace_enter_and_blur_share_inline_save_path() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);const handlers={};"
        "workspace.$root={on:(event,selector,handler)=>{handlers[`${event} ${selector}`]=handler}};"
        "workspace.loadMaterialFeeWorkspace=()=>{};workspace.ensureMaterialFeeState=()=>({});"
        "workspace.renderMaterialFeeWorkspace=()=>{};workspace.openMaterialFeeDialog=()=>{};"
        "workspace.openMaterialFeeEvidenceDialog=()=>{};workspace.setMaterialFeeEvidenceStatus=async()=>{};"
        "workspace.refreshMaterialFeeCostPreview=async()=>{};workspace.openMaterialFeeSourcesDialog=()=>{};"
        "workspace.openMaterialXlsxUploader=()=>{};workspace.saveMaterialFeeCell=async()=>{};"
        "workspace.previewMaterialPaste=()=>{};let saves=0;workspace.saveMaterialFeeInlineAmount=async()=>{saves+=1};"
        "global.$=(value)=>value;workspace.bindMaterialFeeWorkspaceEvents();"
        "let prevented=false,blurred=false;const input={blur:()=>{blurred=true}};"
        "handlers['keydown [data-mf-fee-input]']({key:'Enter',preventDefault:()=>{prevented=true},currentTarget:input});"
        "await handlers['blur [data-mf-fee-input]']({currentTarget:{}});await Promise.resolve();"
        "console.log(JSON.stringify({prevented,blurred,saves}));"
    )

    assert result == {"prevented": True, "blurred": True, "saves": 1}


def test_fee_workspace_tab_within_amount_cell_saves_only_after_leaving_cell() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);const handlers={};"
        "workspace.detailState={batchName:'B-1'};workspace.materialFeeState={batchName:'B-1',feeDrafts:{},focusedFeeInput:null};"
        "workspace.$root={on:(event,selector,handler)=>{handlers[`${event} ${selector}`]=handler}};"
        "workspace.loadMaterialFeeWorkspace=()=>{};workspace.renderMaterialFeeWorkspace=()=>{};workspace.openMaterialFeeDialog=()=>{};"
        "workspace.openMaterialFeeEvidenceDialog=()=>{};workspace.setMaterialFeeEvidenceStatus=async()=>{};workspace.refreshMaterialFeeCostPreview=async()=>{};"
        "workspace.openMaterialFeeSourcesDialog=()=>{};workspace.openMaterialXlsxUploader=()=>{};workspace.saveMaterialFeeCell=async()=>{};"
        "workspace.previewMaterialPaste=()=>{};let saves=0;workspace.saveMaterialFeeInlineAmount=async(input)=>{saves+=1;input.closest().find('[data-mf-fee-input]').prop('disabled',true)};"
        "const fixture=makeFeeInput({amount:'2400',currency:'USD',originalAmount:'2000',originalCurrency:'RMB'});global.$=(value)=>value;"
        "workspace.bindMaterialFeeWorkspaceEvents();"
        "handlers['focus [data-mf-fee-input]']({currentTarget:fixture.currencyInput});"
        "handlers['blur [data-mf-fee-input]']({currentTarget:fixture.currencyInput,relatedTarget:fixture.amountInput});await Promise.resolve();"
        "const within={saves,amountDisabled:fixture.amountInput.disabled,currencyDisabled:fixture.currencyInput.disabled};"
        "handlers['focus [data-mf-fee-input]']({currentTarget:fixture.amountInput});"
        "handlers['blur [data-mf-fee-input]']({currentTarget:fixture.amountInput,relatedTarget:null});await Promise.resolve();"
        "console.log(JSON.stringify({within,afterLeaving:{saves,amountDisabled:fixture.amountInput.disabled,currencyDisabled:fixture.currencyInput.disabled}}));"
    )

    assert result == {
        "within": {"saves": 0, "amountDisabled": False, "currencyDisabled": False},
        "afterLeaving": {"saves": 1, "amountDisabled": True, "currencyDisabled": True},
    }


def test_fee_workspace_blur_clears_focus_target_until_another_fee_input_focuses() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);const handlers={};"
        "workspace.detailState={batchName:'B-1'};workspace.materialFeeState={batchName:'B-1',feeDrafts:{},focusedFeeInput:null};"
        "workspace.$root={on:(event,selector,handler)=>{handlers[`${event} ${selector}`]=handler}};"
        "workspace.loadMaterialFeeWorkspace=()=>{};workspace.renderMaterialFeeWorkspace=()=>{};workspace.openMaterialFeeDialog=()=>{};"
        "workspace.openMaterialFeeEvidenceDialog=()=>{};workspace.setMaterialFeeEvidenceStatus=async()=>{};workspace.refreshMaterialFeeCostPreview=async()=>{};"
        "workspace.openMaterialFeeSourcesDialog=()=>{};workspace.openMaterialXlsxUploader=()=>{};workspace.saveMaterialFeeCell=async()=>{};"
        "workspace.previewMaterialPaste=()=>{};workspace.saveMaterialFeeInlineAmount=async()=>{};"
        "const input={attrs:{'data-fee-key':'fee-a','data-mf-fee-input':'amount'},attr(name){return this.attrs[name]}};global.$=(value)=>value;"
        "workspace.bindMaterialFeeWorkspaceEvents();handlers['focus [data-mf-fee-input]']({currentTarget:input});"
        "const afterFocus={...workspace.materialFeeState.focusedFeeInput};handlers['blur [data-mf-fee-input]']({currentTarget:input});"
        "console.log(JSON.stringify({afterFocus,afterBlur:workspace.materialFeeState.focusedFeeInput}));"
    )

    assert result == {"afterFocus": {"feeKey": "fee-a", "field": "amount"}, "afterBlur": None}


def test_fee_workspace_missing_saved_amount_submits_actual_and_refreshes_fee_preview() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{modified:'m1'}};"
        "const fee={logical_fee_key:'international_sea_freight',rule_code:'sea-freight',expense_category:'\u56fd\u9645\u6d77\u8fd0\u8d39',"
        "amount_status:'MISSING',amount:'2000',currency:'RMB',allocation_basis:'volume',basis_field:'volume',"
        "scope_type:'ITEMS',scope_value_json:'[\"LINE-1\"]',required_evidence_role:'freight_invoice',"
        "included_in_fee_key:'',priority_no:3,remark:'keep me',is_active:1,is_enabled:1};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},requestId:0};workspace.ensureEditSession=async()=>true;"
        "workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1'});"
        "workspace.escape=(value)=>String(value ?? '');workspace.normalizeErrorMessage=(error)=>error.message;"
        "workspace.renderMaterialFeeWorkspace=()=>{};const calls=[];workspace.call=async(endpoint,args)=>{calls.push({endpoint,args});"
        "if(endpoint.endsWith('save_fee'))return {ok:true,batch_modified:'m2',message:'saved'};"
        "if(endpoint.endsWith('get_batch_detail'))return {ok:true,header:{name:'B-1',modified:'m2'}};"
        "if(endpoint.endsWith('get_material_grid'))return {items:[]};"
        "if(endpoint.endsWith('get_fee_worklist'))return {summary:{missing_amount_fee_count:0},fees:[{...fee,amount_status:'ACTUAL'}]};"
        "return {summary:{total_cost_rmb:'2200.00'}}};"
        "const fixture=makeFeeInput({amount:'2000',currency:'RMB',originalAmount:'2000',originalCurrency:'RMB',forceActual:true});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "const payload=JSON.parse(calls[0].args.fee_payload);"
        "console.log(JSON.stringify({endpoints:calls.map((row)=>row.endpoint),payload,"
        "expectedModified:workspace.detailState.expectedModified,headerModified:workspace.detailState.header.modified,"
        "fees:workspace.materialFeeState.fees,preview:workspace.materialFeeState.preview,alerts:global.alerts}));"
    )

    assert result["endpoints"] == [
        "overseas_costing.api.fees.save_fee",
        "overseas_costing.api.batch.get_batch_detail",
        "overseas_costing.api.materials.get_material_grid",
        "overseas_costing.api.fees.get_fee_worklist",
        "overseas_costing.api.calculate.preview_comprehensive_cost",
    ]
    assert result["payload"] == {
        "logical_fee_key": "international_sea_freight",
        "rule_code": "sea-freight",
        "expense_category": "\u56fd\u9645\u6d77\u8fd0\u8d39",
        "amount_status": "ACTUAL",
        "amount": "2000",
        "currency": "RMB",
        "allocation_basis": "volume",
        "scope_type": "ITEMS",
        "scope_value_json": '["LINE-1"]',
        "required_evidence_role": "freight_invoice",
        "included_in_fee_key": "",
        "priority_no": 3,
        "remark": "keep me",
        "is_active": 1,
        "is_enabled": 1,
    }
    assert result["expectedModified"] == "m2"
    assert result["headerModified"] == "m2"
    assert result["fees"]["summary"]["missing_amount_fee_count"] == 0
    assert result["preview"]["summary"]["total_cost_rmb"] == "2200.00"
    assert result["alerts"][-1]["indicator"] == "green"


@pytest.mark.parametrize(
    ("amount", "currency", "message_fragment"),
    [
        ("", "RMB", "金额"),
        ("-1", "RMB", "金额"),
        ("Infinity", "RMB", "金额"),
        ("2400", "", "币种"),
        ("2400", "US", "币种"),
        ("2400", "U1D", "币种"),
        ("2400", "EUR", "币种"),
    ],
)
def test_fee_workspace_invalid_inline_value_stays_visible_without_writing(
    amount: str, currency: str, message_fragment: str
) -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{modified:'m1'}};"
        "const fee={logical_fee_key:'international_sea_freight',expense_category:'\\u56fd\\u9645\\u6d77\\u8fd0\\u8d39',"
        "amount_status:'ACTUAL',amount:'2000',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},requestId:0};workspace.ensureEditSession=async()=>true;"
        "workspace.renderMaterialFeeWorkspace=()=>{};workspace.normalizeErrorMessage=(error)=>error.message;let writeCalls=0;"
        "workspace.call=async(endpoint)=>{if(endpoint.endsWith('save_fee'))writeCalls+=1;return endpoint.endsWith('get_fee_worklist')?{fees:[fee]}:{ok:true,batch_modified:'m2',summary:{}}};"
        f"const fixture=makeFeeInput({{amount:{json.dumps(amount)},currency:{json.dumps(currency)},originalAmount:'2000',originalCurrency:'RMB'}});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "const draft=workspace.materialFeeState.feeDrafts?.international_sea_freight||{};"
        "console.log(JSON.stringify({writeCalls,amount:fixture.amountInput.val(),currency:fixture.currencyInput.val(),"
        "draft,errorText:fixture.errorElement.text(),red:fixture.cell.hasClass('is-save-error'),"
        "amountInvalid:fixture.amountInput.attr('aria-invalid'),currencyInvalid:fixture.currencyInput.attr('aria-invalid'),"
        "describedBy:fixture.amountInput.attr('aria-describedby')}));"
    )

    assert result["writeCalls"] == 0
    assert result["amount"] == amount
    assert result["currency"] == currency
    assert result["draft"]["amount"] == amount
    assert result["draft"]["currency"] == currency
    assert message_fragment in result["draft"]["error"]
    assert message_fragment in result["errorText"]
    assert result["red"] is True
    assert result["amountInvalid"] == "true"
    assert result["currencyInvalid"] == "true"
    assert result["describedBy"]


def test_fee_workspace_missing_saved_amount_currency_blur_also_submits_actual() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{modified:'m1'}};"
        "const fee={logical_fee_key:'international_sea_freight',expense_category:'\\u56fd\\u9645\\u6d77\\u8fd0\\u8d39',"
        "amount_status:'MISSING',amount:'2000',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},requestId:0};workspace.ensureEditSession=async()=>true;"
        "workspace.renderMaterialFeeWorkspace=()=>{};workspace.loadMaterialFeeWorkspace=async()=>true;let payload=null;workspace.call=async(endpoint,args)=>{"
        "if(endpoint.endsWith('save_fee')){payload=JSON.parse(args.fee_payload);return {ok:true,batch_modified:'m2'}}"
        "if(endpoint.endsWith('get_fee_worklist'))return {fees:[{...fee,amount_status:'ACTUAL'}]};return {summary:{}}};"
        "const fixture=makeFeeInput({amount:'2000',currency:'RMB',originalAmount:'2000',originalCurrency:'RMB',forceActual:true});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.currencyInput);"
        "console.log(JSON.stringify({payload}));"
    )

    assert result["payload"]["amount_status"] == "ACTUAL"
    assert result["payload"]["amount"] == "2000"
    assert result["payload"]["currency"] == "RMB"


def test_fee_workspace_unchanged_actual_blur_does_not_leave_stale_draft() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);workspace.detailState={batchName:'B-1'};"
        "const fee={logical_fee_key:'fee-a',expense_category:'A 费用',amount_status:'ACTUAL',amount:'100',currency:'RMB'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},feeDrafts:{},requestId:0,feeRequestId:0};let calls=0;"
        "workspace.call=async()=>{calls+=1};const fixture=makeFeeInput({amount:'100',currency:'RMB',originalAmount:'100',originalCurrency:'RMB',feeKey:'fee-a'});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "console.log(JSON.stringify({calls,draft:workspace.materialFeeState.feeDrafts['fee-a']||null}));"
    )

    assert result == {"calls": 0, "draft": None}


def test_fee_workspace_render_restores_draft_error_and_accessible_labels() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);workspace.escape=(value)=>String(value??'').replaceAll('&','&amp;').replaceAll('\\\"','&quot;');"
        "workspace.materialFeeState={feeDrafts:{'legacy:weird/key':{amount:'2400.5',currency:'USD',error:'\\u5e76\\u53d1\\u51b2\\u7a81'}}};"
        "const html=workspace.renderMaterialFeeRow({logical_fee_key:'legacy:weird/key',expense_category:'\\u7279\\u6b8a\\u8d39\\u7528',"
        "amount_status:'ACTUAL',amount:'2000',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',allocation:{status:'ALLOCATED'},evidence:[]});"
        "console.log(JSON.stringify({draftAmount:html.includes('value=\\\"2400.5\\\"'),draftCurrency:html.includes('value=\\\"USD\\\"'),"
        "inlineError:html.includes('\\u5e76\\u53d1\\u51b2\\u7a81'),invalid:html.includes('aria-invalid=\\\"true\\\"'),"
        "safeId:html.includes('ocw-mf-fee-error-legacy_58_weird_47_key'),amountLabel:html.includes('aria-label=\\\"特殊费用原币金额\\\"'),"
        "currencyLabel:html.includes('aria-label=\\\"特殊费用币种\\\"')}));"
    )

    assert result == {
        "draftAmount": True,
        "draftCurrency": True,
        "inlineError": True,
        "invalid": True,
        "safeId": True,
        "amountLabel": True,
        "currencyLabel": True,
    }


def test_fee_workspace_save_one_row_preserves_other_draft_and_restores_focus() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{modified:'m1'}};"
        "const feeA={logical_fee_key:'fee-a',expense_category:'A 费用',amount_status:'ACTUAL',amount:'100',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]',allocation:{status:'ALLOCATED'},evidence:[]};"
        "const feeB={...feeA,logical_fee_key:'fee-b',expense_category:'B 费用',amount:'200'};"
        "workspace.materialFeeState={batchName:'B-1',page:1,pageLength:200,fees:{fees:[feeA,feeB],summary:{}},materials:{items:[]},preview:{summary:{}},requestId:0,feeRequestId:0,feeDrafts:{},focusedFeeInput:null};"
        "workspace.ensureEditSession=async()=>true;workspace.escape=(value)=>String(value??'');workspace.formatValue=(value)=>String(value??'');"
        "workspace.renderMaterialFeeGrid=()=>'';workspace.renderMaterialFeeTodos=()=>'';workspace.renderMaterialFeeCostTable=()=>'';"
        "let html='';const content={html:(value)=>{html=value}};let focusCalls=0;const focusTarget={"
        "attr:(name)=>name==='data-fee-key'?'fee-b':name==='data-mf-fee-input'?'amount':'',"
        "focus:()=>{focusCalls+=1},value:'250',setSelectionRange:()=>{}};"
        "const allInputs={each:(callback)=>{callback(0,focusTarget)}};workspace.$root={find:(selector)=>selector===\"[data-area='detail-content']\"?content:selector==='[data-mf-fee-input]'?allInputs:{length:0}};global.$=(value)=>value;"
        "workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1'});"
        "let resolveSave;workspace.call=async(endpoint)=>{if(endpoint.endsWith('save_fee'))return await new Promise((resolve)=>{resolveSave=resolve});"
        "if(endpoint.endsWith('get_batch_detail'))return {ok:true,header:{name:'B-1',modified:'m2'}};"
        "if(endpoint.endsWith('get_material_grid'))return {items:[]};"
        "if(endpoint.endsWith('get_fee_worklist'))return {fees:[feeA,feeB],summary:{}};return {summary:{}}};"
        "const fixtureA=makeFeeInput({amount:'150',currency:'RMB',originalAmount:'100',originalCurrency:'RMB',feeKey:'fee-a'});"
        "const fixtureB=makeFeeInput({amount:'250',currency:'USD',originalAmount:'200',originalCurrency:'RMB',feeKey:'fee-b'});"
        "const saving=workspace.saveMaterialFeeInlineAmount(fixtureA.amountInput);await new Promise((resolve)=>setImmediate(resolve));"
        "workspace.updateMaterialFeeDraftFromInput(fixtureB.amountInput);workspace.materialFeeState.focusedFeeInput={feeKey:'fee-b',field:'amount'};"
        "resolveSave({ok:true,batch_modified:'m2'});await saving;"
        "console.log(JSON.stringify({draftA:workspace.materialFeeState.feeDrafts['fee-a']||null,draftB:workspace.materialFeeState.feeDrafts['fee-b']||null,"
        "focusCalls,bRendered:html.includes('data-fee-key=\\\"fee-b\\\"')&&html.includes('value=\\\"250\\\"')&&html.includes('value=\\\"USD\\\"')}));"
    )

    assert result["draftA"] is None
    assert result["draftB"]["amount"] == "250"
    assert result["draftB"]["currency"] == "USD"
    assert result["focusCalls"] == 1
    assert result["bRendered"] is True


def test_fee_workspace_inline_save_failure_preserves_value_and_allows_retry() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[{logical_fee_key:'international_sea_freight',"
        "expense_category:'\u56fd\u9645\u6d77\u8fd0\u8d39',amount_status:'ACTUAL',amount:'2000',currency:'RMB',"
        "allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'}]},requestId:0};"
        "workspace.ensureEditSession=async()=>true;workspace.normalizeErrorMessage=(error)=>error.message;"
        "const endpoints=[];workspace.call=async(endpoint)=>{endpoints.push(endpoint);throw new Error(endpoint.endsWith('save_fee')?'\u5e76\u53d1\u51b2\u7a81':'\u540c\u6b65\u5931\u8d25')};"
        "const fixture=makeFeeInput({amount:'2400',currency:'USD',originalAmount:'2000',originalCurrency:'RMB'});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "console.log(JSON.stringify({amount:fixture.amountInput.val(),currency:fixture.currencyInput.val(),"
        "disabled:fixture.amountInput.disabled||fixture.currencyInput.disabled,saving:fixture.cell.data('saving'),"
        "error:fixture.cell.hasClass('is-save-error'),title:fixture.attrs.title,errorText:fixture.errorElement.text(),"
        "amountInvalid:fixture.amountInput.attr('aria-invalid'),describedBy:fixture.amountInput.attr('aria-describedby'),alerts:global.alerts,endpoints}));"
    )

    assert result["amount"] == "2400"
    assert result["currency"] == "USD"
    assert result["disabled"] is False
    assert result["saving"] is False
    assert result["error"] is True
    assert "\u5e76\u53d1\u51b2\u7a81" in result["title"]
    assert "\u9875\u9762\u5237\u65b0" in result["title"]
    assert "\u5e76\u53d1\u51b2\u7a81" in result["errorText"]
    assert "\u9875\u9762\u5237\u65b0" in result["errorText"]
    assert result["amountInvalid"] == "true"
    assert result["describedBy"]
    assert result["endpoints"] == [
        "overseas_costing.api.fees.save_fee",
        "overseas_costing.api.batch.get_batch_detail",
        "overseas_costing.api.fees.get_fee_worklist",
        "overseas_costing.api.calculate.preview_comprehensive_cost",
    ]
    assert result["alerts"][-1]["indicator"] == "red"
    assert "\u5e76\u53d1\u51b2\u7a81" in result["alerts"][-1]["message"]
    assert "\u9875\u9762\u5237\u65b0" in result["alerts"][-1]["message"]


def test_fee_workspace_conflict_refreshes_revision_and_latest_fee_before_explicit_retry() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "const oldFee={logical_fee_key:'international_sea_freight',rule_code:'old-rule',expense_category:'\u56fd\u9645\u6d77\u8fd0\u8d39',"
        "amount_status:'ACTUAL',amount:'2000',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]',remark:'old'};"
        "const latestFee={...oldFee,rule_code:'latest-rule',allocation_basis:'gross_weight',remark:'latest'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[oldFee]},preview:{summary:{}},requestId:0};"
        "workspace.ensureEditSession=async()=>true;workspace.normalizeErrorMessage=(error)=>error.message;let renders=0;"
        "workspace.renderMaterialFeeWorkspace=()=>{renders+=1};workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1'});"
        "const saves=[];const endpoints=[];let detailCalls=0;"
        "workspace.call=async(endpoint,args)=>{endpoints.push(endpoint);"
        "if(endpoint.endsWith('save_fee')){saves.push(args);if(saves.length===1)throw new Error('\u5e76\u53d1\u51b2\u7a81');"
        "if(args.expected_modified!=='m2')throw new Error('\u4ecd\u4f7f\u7528\u65e7\u7248\u672c');return {ok:true,batch_modified:'m3',message:'saved'}}"
        "if(endpoint.endsWith('get_batch_detail')){detailCalls+=1;return {ok:true,batch_name:'B-1',version_name:'V-1',header:{name:'B-1',modified:detailCalls===1?'m2':'m3'}}}"
        "if(endpoint.endsWith('get_material_grid'))return {items:[]};"
        "if(endpoint.endsWith('get_fee_worklist'))return {summary:{},fees:[latestFee]};"
        "return {summary:{total_cost_rmb:'2400.00'}}};"
        "const fixture=makeFeeInput({amount:'2400',currency:'USD',originalAmount:'2000',originalCurrency:'RMB'});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "const afterConflict={saveCount:saves.length,expectedModified:workspace.detailState.expectedModified,"
        "headerModified:workspace.detailState.header.modified,fee:workspace.materialFeeState.fees.fees[0],"
        "amount:fixture.amountInput.val(),currency:fixture.currencyInput.val(),red:fixture.cell.hasClass('is-save-error'),renders};"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "console.log(JSON.stringify({afterConflict,saveCount:saves.length,secondExpected:saves[1]?.expected_modified,"
        "secondPayload:JSON.parse(saves[1]?.fee_payload||'{}'),finalExpected:workspace.detailState.expectedModified,endpoints}));"
    )

    assert result["afterConflict"] == {
        "saveCount": 1,
        "expectedModified": "m2",
        "headerModified": "m2",
        "fee": {
            "logical_fee_key": "international_sea_freight",
            "rule_code": "latest-rule",
            "expense_category": "\u56fd\u9645\u6d77\u8fd0\u8d39",
            "amount_status": "ACTUAL",
            "amount": "2000",
            "currency": "RMB",
            "allocation_basis": "gross_weight",
            "scope_type": "ALL_ITEMS",
            "scope_value_json": "[]",
            "remark": "latest",
        },
        "amount": "2400",
        "currency": "USD",
        "red": True,
        "renders": 0,
    }
    assert result["saveCount"] == 2
    assert result["secondExpected"] == "m2"
    assert result["secondPayload"]["amount"] == "2400"
    assert result["secondPayload"]["currency"] == "USD"
    assert result["secondPayload"]["rule_code"] == "latest-rule"
    assert result["secondPayload"]["allocation_basis"] == "gross_weight"
    assert result["secondPayload"]["remark"] == "latest"
    assert result["finalExpected"] == "m3"


def test_fee_workspace_edit_session_failure_is_visible_and_refreshes_readonly_state() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "const fee={logical_fee_key:'international_sea_freight',expense_category:'\u56fd\u9645\u6d77\u8fd0\u8d39',amount_status:'ACTUAL',amount:'2000',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},preview:{summary:{}},requestId:0};"
        "workspace.ensureEditSession=async()=>false;workspace.normalizeErrorMessage=(error)=>error.message;const endpoints=[];"
        "workspace.call=async(endpoint)=>{endpoints.push(endpoint);if(endpoint.endsWith('get_batch_detail'))return {ok:true,header:{modified:'m2'}};"
        "if(endpoint.endsWith('get_fee_worklist'))return {fees:[fee]};return {summary:{}}};"
        "const fixture=makeFeeInput({amount:'2400',currency:'RMB',originalAmount:'2000',originalCurrency:'RMB'});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "console.log(JSON.stringify({red:fixture.cell.hasClass('is-save-error'),disabled:fixture.amountInput.disabled,"
        "expectedModified:workspace.detailState.expectedModified,endpoints,alerts:global.alerts}));"
    )

    assert result["red"] is True
    assert result["disabled"] is False
    assert result["expectedModified"] == "m2"
    assert "overseas_costing.api.fees.save_fee" not in result["endpoints"]
    assert result["endpoints"] == [
        "overseas_costing.api.batch.get_batch_detail",
        "overseas_costing.api.fees.get_fee_worklist",
        "overseas_costing.api.calculate.preview_comprehensive_cost",
    ]
    assert result["alerts"][-1]["indicator"] == "red"


def test_fee_workspace_manual_reload_refreshes_batch_modified() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "workspace.materialFeeState={batchName:'B-1',page:1,pageLength:200,requestId:0};"
        "workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1'});workspace.renderDetailTabLoading=()=>{};"
        "let renders=0;workspace.renderMaterialFeeWorkspace=()=>{renders+=1};const endpoints=[];"
        "workspace.call=async(endpoint)=>{endpoints.push(endpoint);if(endpoint.endsWith('get_batch_detail'))"
        "return {ok:true,batch_name:'B-1',version_name:'V-1',header:{name:'B-1',modified:'m2',status:'Dirty'}};"
        "if(endpoint.endsWith('get_material_grid'))return {items:[]};if(endpoint.endsWith('get_fee_worklist'))return {fees:[]};"
        "return {summary:{}}};await workspace.loadMaterialFeeWorkspace();"
        "console.log(JSON.stringify({expectedModified:workspace.detailState.expectedModified,"
        "header:workspace.detailState.header,endpoints,renders}));"
    )

    assert result["expectedModified"] == "m2"
    assert result["header"]["modified"] == "m2"
    assert result["header"]["status"] == "Dirty"
    assert result["endpoints"] == [
        "overseas_costing.api.batch.get_batch_detail",
        "overseas_costing.api.materials.get_material_grid",
        "overseas_costing.api.fees.get_fee_worklist",
        "overseas_costing.api.calculate.preview_comprehensive_cost",
    ]
    assert result["renders"] == 1


def test_fee_workspace_save_does_not_render_after_switching_to_vouchers() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{modified:'m1'}};"
        "const fee={logical_fee_key:'international_sea_freight',expense_category:'\u56fd\u9645\u6d77\u8fd0\u8d39',amount_status:'ACTUAL',amount:'2000',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},preview:{summary:{}},requestId:0};"
        "workspace.ensureEditSession=async()=>true;workspace.normalizeErrorMessage=(error)=>error.message;let renders=0;"
        "workspace.renderMaterialFeeWorkspace=()=>{renders+=1};workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1'});"
        "let releaseReads;const readsGate=new Promise((resolve)=>{releaseReads=resolve});workspace.call=async(endpoint)=>{"
        "if(endpoint.endsWith('save_fee'))return {ok:true,batch_modified:'m2'};await readsGate;"
        "if(endpoint.endsWith('get_batch_detail'))return {ok:true,header:{name:'B-1',modified:'m2'}};"
        "if(endpoint.endsWith('get_material_grid'))return {items:[]};if(endpoint.endsWith('get_fee_worklist'))return {fees:[fee]};"
        "return {summary:{total_cost_rmb:'2400.00'}}};"
        "const fixture=makeFeeInput({amount:'2400',currency:'RMB',originalAmount:'2000',originalCurrency:'RMB'});"
        "const saving=workspace.saveMaterialFeeInlineAmount(fixture.amountInput);await new Promise((resolve)=>setImmediate(resolve));"
        "workspace.detailState.tab='vouchers';releaseReads();"
        "await saving;console.log(JSON.stringify({renders,tab:workspace.detailState.tab}));"
    )

    assert result == {"renders": 0, "tab": "vouchers"}


def test_fee_workspace_save_response_does_not_mutate_a_new_batch() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "const fee={logical_fee_key:'international_sea_freight',expense_category:'\u56fd\u9645\u6d77\u8fd0\u8d39',amount_status:'ACTUAL',amount:'2000',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},preview:{summary:{}},requestId:0};"
        "workspace.ensureEditSession=async()=>true;workspace.normalizeErrorMessage=(error)=>error.message;let renders=0;"
        "workspace.renderMaterialFeeWorkspace=()=>{renders+=1};let resolveSave;const endpoints=[];"
        "workspace.call=async(endpoint)=>{endpoints.push(endpoint);if(endpoint.endsWith('save_fee'))"
        "return await new Promise((resolve)=>{resolveSave=resolve});if(endpoint.endsWith('get_fee_worklist'))return {fees:[]};return {summary:{}}};"
        "const fixture=makeFeeInput({amount:'2400',currency:'RMB',originalAmount:'2000',originalCurrency:'RMB'});"
        "const saving=workspace.saveMaterialFeeInlineAmount(fixture.amountInput);await new Promise((resolve)=>setImmediate(resolve));"
        "workspace.detailState={batchName:'B-2',versionName:'V-2',tab:'documents',editToken:'token-2',expectedModified:'n1',header:{name:'B-2',modified:'n1'}};"
        "workspace.materialFeeState={batchName:'B-2',fees:{fees:[]},preview:{summary:{}},requestId:0};"
        "resolveSave({ok:true,batch_modified:'m2'});await saving;"
        "console.log(JSON.stringify({renders,expectedModified:workspace.detailState.expectedModified,"
        "headerModified:workspace.detailState.header.modified,endpoints,disabled:fixture.amountInput.disabled}));"
    )

    assert result == {
        "renders": 0,
        "expectedModified": "n1",
        "headerModified": "n1",
        "endpoints": ["overseas_costing.api.fees.save_fee"],
        "disabled": True,
    }


def test_fee_workspace_load_does_not_apply_previous_batch_results() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "workspace.materialFeeState={batchName:'B-1',page:1,pageLength:200,requestId:0};"
        "workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1'});workspace.renderDetailTabLoading=()=>{};"
        "let renders=0;workspace.renderMaterialFeeWorkspace=()=>{renders+=1};let release;const gate=new Promise((resolve)=>{release=resolve});"
        "workspace.call=async(endpoint)=>{await gate;if(endpoint.endsWith('get_batch_detail'))return {ok:true,header:{modified:'m2'}};"
        "if(endpoint.endsWith('get_material_grid'))return {items:[{name:'OLD'}]};if(endpoint.endsWith('get_fee_worklist'))return {fees:[]};return {summary:{}}};"
        "const loading=workspace.loadMaterialFeeWorkspace();workspace.detailState.batchName='B-2';release();await loading;"
        "console.log(JSON.stringify({renders,expectedModified:workspace.detailState.expectedModified,materials:workspace.materialFeeState.materials||null}));"
    )

    assert result == {"renders": 0, "expectedModified": "m1", "materials": None}


def test_fee_workspace_local_recovery_does_not_cancel_full_reload() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "workspace.materialFeeState={batchName:'B-1',page:1,pageLength:200,loading:false,requestId:0,feeRequestId:0,"
        "feeDrafts:{'fee-a':{amount:'2400',currency:'USD',error:'\\u5e76\\u53d1\\u51b2\\u7a81',touched:true}},materials:null,fees:null,preview:null};"
        "workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1'});workspace.renderDetailTabLoading=()=>{};let renders=0;"
        "workspace.renderMaterialFeeWorkspace=()=>{renders+=1};let releaseFull;const fullGate=new Promise((resolve)=>{releaseFull=resolve});"
        "let detailCalls=0,feeCalls=0,previewCalls=0;workspace.call=async(endpoint)=>{"
        "if(endpoint.endsWith('get_batch_detail')){detailCalls+=1;if(detailCalls===1){await fullGate;return {ok:true,header:{modified:'m3'}}}return {ok:true,header:{modified:'m2'}}}"
        "if(endpoint.endsWith('get_material_grid')){await fullGate;return {items:[{name:'FULL'}]}}"
        "if(endpoint.endsWith('get_fee_worklist')){feeCalls+=1;if(feeCalls===1){await fullGate;return {fees:[{logical_fee_key:'fee-full'}]}}return {fees:[{logical_fee_key:'fee-recovery'}]}}"
        "previewCalls+=1;if(previewCalls===1){await fullGate;return {summary:{source:'full'}}}return {summary:{source:'recovery'}}};"
        "const full=workspace.loadMaterialFeeWorkspace();await new Promise((resolve)=>setImmediate(resolve));"
        "const recovered=await workspace.recoverMaterialFeeReadonlyState('B-1');releaseFull();await full;"
        "console.log(JSON.stringify({recovered,loading:workspace.materialFeeState.loading,renders,requestId:workspace.materialFeeState.requestId,"
        "feeRequestId:workspace.materialFeeState.feeRequestId,expectedModified:workspace.detailState.expectedModified,"
        "materials:workspace.materialFeeState.materials,draft:workspace.materialFeeState.feeDrafts['fee-a']}));"
    )

    assert result["recovered"] is True
    assert result["loading"] is False
    assert result["renders"] == 1
    assert result["requestId"] == 1
    assert result["feeRequestId"] == 1
    assert result["expectedModified"] == "m3"
    assert result["materials"] == {"items": [{"name": "FULL"}]}
    assert result["draft"]["amount"] == "2400"
    assert result["draft"]["error"] == "并发冲突"


def test_fee_workspace_successful_save_invalidates_write_before_full_reload() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1',header:{name:'B-1',modified:'m1'}};"
        "const oldFee={logical_fee_key:'fee-a',expense_category:'A 费用',amount_status:'ACTUAL',amount:'100',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "const newFee={...oldFee,amount:'150',currency:'USD'};"
        "workspace.materialFeeState={batchName:'B-1',page:1,pageLength:200,loading:false,requestId:0,feeRequestId:0,"
        "feeDrafts:{'fee-b':{amount:'88',currency:'EUR',error:'',touched:true}},materials:{items:[]},fees:{fees:[oldFee]},preview:{summary:{}}};"
        "workspace.getDetailBatch=()=>({name:'B-1',current_version:'V-1',modified:workspace.detailState.expectedModified});"
        "workspace.ensureEditSession=async()=>true;workspace.renderDetailTabLoading=()=>{};let renders=0;workspace.renderMaterialFeeWorkspace=()=>{renders+=1};"
        "let releaseOld;const oldGate=new Promise((resolve)=>{releaseOld=resolve});const counts={detail:0,materials:0,fees:0,preview:0};let writes=0;"
        "workspace.call=async(endpoint)=>{if(endpoint.endsWith('save_fee')){writes+=1;return {ok:true,batch_modified:'m2',message:'saved'}}"
        "const kind=endpoint.endsWith('get_batch_detail')?'detail':endpoint.endsWith('get_material_grid')?'materials':endpoint.endsWith('get_fee_worklist')?'fees':'preview';"
        "counts[kind]+=1;const old=counts[kind]===1;if(old)await oldGate;"
        "if(kind==='detail')return {ok:true,batch_name:'B-1',version_name:'V-1',header:{name:'B-1',modified:old?'m1':'m2'}};"
        "if(kind==='materials')return {items:[{name:old?'OLD':'NEW'}]};if(kind==='fees')return {fees:[old?oldFee:newFee],summary:{}};"
        "return {summary:{total_cost_rmb:old?'100.00':'150.00'}}};"
        "const oldFull=workspace.loadMaterialFeeWorkspace();await new Promise((resolve)=>setImmediate(resolve));"
        "const fixture=makeFeeInput({amount:'150',currency:'USD',originalAmount:'100',originalCurrency:'RMB',feeKey:'fee-a'});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);releaseOld();await oldFull;"
        "console.log(JSON.stringify({writes,counts,requestId:workspace.materialFeeState.requestId,loading:workspace.materialFeeState.loading,"
        "expectedModified:workspace.detailState.expectedModified,headerModified:workspace.detailState.header.modified,"
        "fee:workspace.materialFeeState.fees.fees[0],materials:workspace.materialFeeState.materials,draftA:workspace.materialFeeState.feeDrafts['fee-a']||null,"
        "draftB:workspace.materialFeeState.feeDrafts['fee-b'],renders,alerts:global.alerts}));"
    )

    assert result["writes"] == 1
    assert result["counts"] == {"detail": 2, "materials": 2, "fees": 2, "preview": 2}
    assert result["requestId"] == 2
    assert result["loading"] is False
    assert result["expectedModified"] == "m2"
    assert result["headerModified"] == "m2"
    assert result["fee"]["amount"] == "150"
    assert result["fee"]["currency"] == "USD"
    assert result["materials"] == {"items": [{"name": "NEW"}]}
    assert result["draftA"] is None
    assert result["draftB"]["amount"] == "88"
    assert result["renders"] == 1
    assert result["alerts"][-1] == {"message": "saved", "indicator": "green"}


def test_fee_workspace_duplicate_blur_is_ignored_while_inline_save_is_pending() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'token-1',expectedModified:'m1'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[{logical_fee_key:'international_sea_freight',"
        "expense_category:'\u56fd\u9645\u6d77\u8fd0\u8d39',amount_status:'ACTUAL',amount:'2000',currency:'RMB',"
        "allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'}]}};"
        "let resolveSave;let saveCalls=0;workspace.ensureEditSession=async()=>true;"
        "workspace.normalizeErrorMessage=(error)=>error.message;workspace.loadMaterialFeeWorkspace=async()=>true;"
        "workspace.call=async()=>{saveCalls+=1;return await new Promise((resolve)=>{resolveSave=resolve})};"
        "const fixture=makeFeeInput({amount:'2400',currency:'RMB',originalAmount:'2000',originalCurrency:'RMB'});"
        "const first=workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "const second=workspace.saveMaterialFeeInlineAmount(fixture.amountInput);await Promise.resolve();await Promise.resolve();"
        "resolveSave({ok:true,batch_modified:'m2'});await Promise.all([first,second]);"
        "console.log(JSON.stringify({saveCalls}));"
    )

    assert result == {"saveCalls": 1}


def test_fee_workspace_edit_session_acquire_is_single_flight() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);workspace.detailState={batchName:'B-1',editToken:'',editExpiresAt:''};"
        "workspace.materialFeeState={batchName:'B-1',feeDrafts:{},requestId:0,feeRequestId:0};let acquireCalls=0,release;"
        "workspace.ensureEditSession=async()=>{acquireCalls+=1;await new Promise((resolve)=>{release=resolve});workspace.detailState.editToken='token-1';return true};"
        "const first=workspace.ensureMaterialFeeEditSession();const second=workspace.ensureMaterialFeeEditSession();"
        "await new Promise((resolve)=>setImmediate(resolve));release();const results=await Promise.all([first,second]);"
        "console.log(JSON.stringify({acquireCalls,results,token:workspace.detailState.editToken}));"
    )

    assert result == {"acquireCalls": 1, "results": [True, True], "token": "token-1"}


def test_edit_session_late_old_batch_acquire_releases_without_overwriting_current_token() -> None:
    result = _detail_workspace_result(
        "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',editToken:'',editExpiresAt:'',expectedModified:'m1',renewTimer:null};"
        "workspace.batches={'B-1':{name:'B-1',modified:'m1'},'B-2':{name:'B-2',modified:'n1'}};"
        "workspace.getDetailBatch=()=>workspace.batches[workspace.detailState.batchName];workspace.updateEditLeaseStatus=()=>{};"
        "workspace.formatDateTimeMinute=(value)=>String(value||'');workspace.$root={find:()=>({addClass(){return this},text(){return this},attr(){return this}})};"
        "const pending={};const releases=[];workspace.call=async(endpoint,args)=>{"
        "if(endpoint.endsWith('acquire'))return await new Promise((resolve)=>{pending[args.batch_name]=resolve});"
        "if(endpoint.endsWith('release')){releases.push(args);return {ok:true}}throw new Error(endpoint)};"
        "const first=workspace.ensureEditSession();await new Promise((resolve)=>setImmediate(resolve));"
        "workspace.detailState.batchName='B-2';workspace.detailState.expectedModified='n1';"
        "const second=workspace.ensureEditSession();await new Promise((resolve)=>setImmediate(resolve));"
        "pending['B-2']({ok:true,edit_token:'token-b2',expires_at:'2099-01-01',modified:'n1'});const secondReady=await second;"
        "pending['B-1']({ok:true,edit_token:'token-b1',expires_at:'2099-01-01',modified:'m1'});const firstReady=await first;"
        "console.log(JSON.stringify({firstReady,secondReady,batchName:workspace.detailState.batchName,token:workspace.detailState.editToken,"
        "expectedModified:workspace.detailState.expectedModified,releases,alerts:global.alerts}));"
    )

    assert result == {
        "firstReady": False,
        "secondReady": True,
        "batchName": "B-2",
        "token": "token-b2",
        "expectedModified": "n1",
        "releases": [{"batch_name": "B-1", "edit_token": "token-b1"}],
        "alerts": [],
    }


def test_fee_workspace_builds_save_payload_from_latest_fee_after_lease() -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'',editExpiresAt:'',expectedModified:'m1',header:{modified:'m1'}};"
        "const oldFee={logical_fee_key:'fee-a',rule_code:'OLD',expense_category:'A 费用',amount_status:'ACTUAL',amount:'100',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]',remark:'old'};"
        "const newFee={...oldFee,rule_code:'NEW',allocation_basis:'gross_weight',scope_type:'ITEMS',scope_value_json:'[\\\"LINE-2\\\"]',remark:'new'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[oldFee]},feeDrafts:{},requestId:0,feeRequestId:0};"
        "let releaseLease;workspace.ensureEditSession=async()=>{await new Promise((resolve)=>{releaseLease=resolve});workspace.detailState.editToken='token-2';return true};"
        "workspace.loadMaterialFeeWorkspace=async()=>true;let saveArgs=null;workspace.call=async(endpoint,args)=>{if(endpoint.endsWith('save_fee')){saveArgs=args;return {ok:true,batch_modified:'m3'}}};"
        "const fixture=makeFeeInput({amount:'150',currency:'USD',originalAmount:'100',originalCurrency:'RMB',feeKey:'fee-a'});"
        "const saving=workspace.saveMaterialFeeInlineAmount(fixture.amountInput);await new Promise((resolve)=>setImmediate(resolve));"
        "workspace.materialFeeState.fees={fees:[newFee]};workspace.detailState.expectedModified='m2';workspace.detailState.header.modified='m2';releaseLease();await saving;"
        "console.log(JSON.stringify({expectedModified:saveArgs.expected_modified,token:saveArgs.edit_token,payload:JSON.parse(saveArgs.fee_payload)}));"
    )

    assert result["expectedModified"] == "m2"
    assert result["token"] == "token-2"
    assert result["payload"]["rule_code"] == "NEW"
    assert result["payload"]["allocation_basis"] == "gross_weight"
    assert result["payload"]["scope_type"] == "ITEMS"
    assert result["payload"]["scope_value_json"] == '["LINE-2"]'
    assert result["payload"]["remark"] == "new"


@pytest.mark.parametrize(
    "lease_error",
    ["编辑会话已过期，请重新进入编辑。", "当前批次正在被其他用户编辑。"],
)
def test_fee_workspace_expired_or_invalid_lease_reacquires_on_next_explicit_save(lease_error: str) -> None:
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + "const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:'expired-token',editExpiresAt:'2000-01-01T00:00:00Z',expectedModified:'m1',header:{modified:'m1'}};"
        "const fee={logical_fee_key:'fee-a',expense_category:'A 费用',amount_status:'ACTUAL',amount:'100',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},feeDrafts:{},requestId:0,feeRequestId:0};"
        "let acquireCalls=0;const tokensAtAcquire=[];workspace.ensureEditSession=async()=>{acquireCalls+=1;tokensAtAcquire.push(workspace.detailState.editToken);workspace.detailState.editToken=`fresh-${acquireCalls}`;workspace.detailState.editExpiresAt='2099-01-01T00:00:00Z';return true};"
        "workspace.normalizeErrorMessage=(error)=>error.message;workspace.recoverMaterialFeeReadonlyState=async()=>true;workspace.loadMaterialFeeWorkspace=async()=>true;"
        f"let saveCalls=0;workspace.call=async()=>{{saveCalls+=1;if(saveCalls===1)throw new Error({json.dumps(lease_error)});return {{ok:true,batch_modified:'m2'}}}};"
        "const fixture=makeFeeInput({amount:'150',currency:'RMB',originalAmount:'100',originalCurrency:'RMB',feeKey:'fee-a'});"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);const afterFirst={saveCalls,acquireCalls,token:workspace.detailState.editToken};"
        "await workspace.saveMaterialFeeInlineAmount(fixture.amountInput);"
        "console.log(JSON.stringify({tokensAtAcquire,afterFirst,saveCalls,acquireCalls,finalToken:workspace.detailState.editToken}));"
    )

    assert result["tokensAtAcquire"] == ["", ""]
    assert result["afterFirst"] == {"saveCalls": 1, "acquireCalls": 1, "token": ""}
    assert result["saveCalls"] == 2
    assert result["acquireCalls"] == 2
    assert result["finalToken"] == "fresh-2"


@pytest.mark.parametrize("stale_phase", ["lease", "success", "save", "recovery"])
@pytest.mark.parametrize("stale_reason", ["tab", "full_reload"])
def test_fee_workspace_stale_failure_does_not_touch_detached_input_or_toast(
    stale_phase: str, stale_reason: str
) -> None:
    switch_statement = (
        "workspace.detailState.tab='vouchers';"
        if stale_reason == "tab"
        else "workspace.materialFeeState.requestId+=1;"
    )
    result = _fee_workspace_result(
        FEE_INPUT_FIXTURE
        + f"const stalePhase={json.dumps(stale_phase)};const workspace=Object.create(Harness.prototype);"
        "workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',editToken:stalePhase==='lease'?'':'token-1',expectedModified:'m1',header:{modified:'m1'}};"
        "const fee={logical_fee_key:'fee-a',expense_category:'A 费用',amount_status:'ACTUAL',amount:'100',currency:'RMB',allocation_basis:'volume',scope_type:'ALL_ITEMS',scope_value_json:'[]'};"
        "workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},feeDrafts:{},requestId:0,feeRequestId:0};"
        "workspace.normalizeErrorMessage=(error)=>error.message;let resolveSave,rejectSave,releaseRecovery,releaseLease;"
        "workspace.ensureEditSession=async()=>{if(stalePhase!=='lease')return true;await new Promise((resolve)=>{releaseLease=resolve});workspace.detailState.editToken='token-1';return true};"
        "workspace.call=async()=>{if(stalePhase==='recovery')throw new Error('并发冲突');"
        "if(stalePhase==='save'||stalePhase==='success')return await new Promise((resolve,reject)=>{resolveSave=resolve;rejectSave=reject});return {ok:true,batch_modified:'m2'}};"
        "workspace.loadMaterialFeeWorkspace=async()=>{workspace.materialFeeState.requestId+=1;return false};"
        "let recoverCalls=0;workspace.recoverMaterialFeeReadonlyState=async()=>{recoverCalls+=1;if(stalePhase==='save')return false;"
        "return await new Promise((resolve)=>{releaseRecovery=resolve})};let renders=0;workspace.renderMaterialFeeWorkspace=()=>{renders+=1};"
        "const fixture=makeFeeInput({amount:'150',currency:'USD',originalAmount:'100',originalCurrency:'RMB',feeKey:'fee-a'});"
        "let stale=false,postStaleMutations=0;for(const [target,names] of [[fixture.cell,['data','addClass','removeClass','attr']],[fixture.amountInput,['prop','attr']],[fixture.currencyInput,['prop','attr']]]){"
        "for(const name of names){const original=target[name].bind(target);target[name]=(...args)=>{if(stale)postStaleMutations+=1;return original(...args)}}}"
        "const saving=workspace.saveMaterialFeeInlineAmount(fixture.amountInput);await new Promise((resolve)=>setImmediate(resolve));"
        + switch_statement
        + "stale=true;if(stalePhase==='lease')releaseLease();else if(stalePhase==='success')resolveSave({ok:true,batch_modified:'m2'});"
        "else if(stalePhase==='save')rejectSave(new Error('并发冲突'));else releaseRecovery(false);"
        "await saving;const draft=workspace.materialFeeState.feeDrafts['fee-a']||null;"
        "console.log(JSON.stringify({postStaleMutations,recoverCalls,renders,alerts:global.alerts,draft,tab:workspace.detailState.tab,requestId:workspace.materialFeeState.requestId}));"
    )

    assert result["postStaleMutations"] == 0
    assert result["recoverCalls"] == (1 if stale_phase == "recovery" else 0)
    assert result["alerts"] == []
    if stale_phase == "success":
        assert result["draft"] is None
    else:
        assert result["draft"]["amount"] == "150"
        assert result["draft"]["currency"] == "USD"
    if stale_phase == "lease":
        assert not result["draft"].get("error")
    elif stale_phase != "success":
        assert "并发冲突" in result["draft"]["error"]
    assert result["renders"] == (1 if stale_phase == "save" and stale_reason == "full_reload" else 0)


def test_fee_workspace_exclusion_is_in_trial_result_without_an_allocation_column() -> None:
    result = _fee_workspace_result(
        "const workspace=Object.create(Harness.prototype);workspace.escape=(value)=>String(value ?? '');"
        "workspace.formatValue=(value)=>String(value);"
        "const row=workspace.renderMaterialFeeRow({logical_fee_key:'import_tax',expense_category:'\u8fdb\u53e3\u7a0e\u8d39',"
        "amount_status:'ESTIMATED',amount:'88',currency:'EUR',allocation_basis:'goods_value',"
        "scope_type:'ALL_ITEMS',allocation:{status:'MISSING_BASIS'},evidence:[]});"
        "workspace.detailState={batchName:'B-1',header:{summary_snapshot:{comprehensive_cost:{excluded_fees:[{expense_category:'进口税费',reason_code:'ALLOCATION_DENOMINATOR_ZERO'}]}}}};workspace.materialFeeState={batchName:'B-1'};"
        "const trial=workspace.renderMaterialFeeCostTable();"
        "console.log(JSON.stringify({basis:row.includes('采购货值'),rawCode:trial.includes('ALLOCATION_DENOMINATOR_ZERO'),excluded:trial.includes('未计入费用'),chinese:trial.includes('采购货值')}));"
    )

    assert result == {"basis": False, "rawCode": False, "excluded": True, "chinese": True}


def test_wiki_material_source_dialog_refreshes_globally_and_previews_each_sheet() -> None:
    workspace = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    workspace += (PARTS / "79-material-import-grid.js").read_text(encoding="utf-8")

    assert "request_packing_workbook_refresh" in workspace
    assert 'data-action="mf-wiki-refresh-all"' in workspace
    assert 'data-action="mf-wiki-preview-card"' in workspace
    assert "wikiMaterialRefreshedSources = new Set()" in workspace
    assert "refreshWikiMaterialCatalogs" in workspace
    assert "previewFreshWikiMaterialImport" in workspace
    assert "wikiMaterialClosed" in workspace
    assert "hide.bs.modal.ocwMfWiki" in workspace
    assert "preserveOnError" in workspace
    assert 'data-action="mf-wiki-refresh"' not in workspace
    assert "系统只读取服务器已授权的钉钉装箱计划表" not in workspace
    assert "预览所选 Sheet" not in workspace
    assert "确认写入物料表" in workspace


def test_recalculate_ui_blocks_invalid_approval_batches() -> None:
    calculation = (PARTS / "30-calculation-erp.js").read_text(encoding="utf-8")
    table = (PARTS / "75-table-and-list.js").read_text(encoding="utf-8")
    audit = (PARTS / "90-audit-logs.js").read_text(encoding="utf-8")

    assert "batch.source_status || {}" in calculation
    assert "invalid_business" in calculation
    assert "已拒绝、撤销或终止" in calculation
    assert "if (!result?.ok)" in calculation
    assert "recalculateDisabled" in table
    assert "sourceStatus.invalid_business" in audit


def test_manual_oa_pull_does_not_report_failed_save_as_completed() -> None:
    import_ui = (PARTS / "50-import-category.js").read_text(encoding="utf-8")
    pull_block = import_ui.split("async pullOaLogisticsApprovals(dialog, values)", 1)[1].split(
        "async repullGapDingtalk", 1
    )[0]

    assert "if (!result?.ok)" in pull_block
    assert "failed_count" in pull_block
    assert "throw new Error" in pull_block


def test_batch_source_provenance_fields_are_not_editable_by_cost_users() -> None:
    path = ROOT / "overseas_costing" / "doctype" / "overseas_cost_batch" / "overseas_cost_batch.json"
    definition = json.loads(path.read_text(encoding="utf-8"))
    fields = {row["fieldname"]: row for row in definition["fields"]}

    for fieldname in ("source_type", "source_data_id", "source_approval_no", "source_instance_id", "extra_json"):
        assert fields[fieldname]["permlevel"] == 1


def test_fee_workspace_currency_is_a_three_option_select_and_dialog_has_no_basis():
    result = _fee_workspace_result(r"""
const workspace=Object.create(Harness.prototype);
workspace.detailState={batchName:'B-1'};
const fee={logical_fee_key:'freight',amount_status:'ACTUAL',amount:0,currency:'CNY'};
workspace.materialFeeState={batchName:'B-1',fees:{fees:[fee]},materials:{items:[]}};
workspace.escape=(value)=>String(value??'');
const row=workspace.renderMaterialFeeRow(fee);
let fields;global.frappe.ui={Dialog:class {constructor(options){fields=options.fields;this.$wrapper={addClass(){}}}show(){}}};
workspace.openMaterialFeeDialog('freight');
console.log(JSON.stringify({row,fields}));
""")
    assert '<select data-mf-fee-input="currency"' in result["row"]
    assert result["row"].count("<option ") == 3
    assert 'value="RMB" selected' in result["row"]
    assert "人民币" in result["row"] and "比索" in result["row"] and "美金" in result["row"]
    fields = {field["fieldname"]: field for field in result["fields"]}
    assert "allocation_basis" not in fields
    assert fields["currency"]["fieldtype"] == "Select"
    assert [option["value"] for option in fields["currency"]["options"]] == ["RMB", "MXN", "USD"]
    assert fields["currency"]["default"] == "RMB"
    assert fields["amount"]["default"] == 0


PREVIEW_WORKSPACE_FIXTURE = r"""
const workspace=Object.create(Harness.prototype);
workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents'};
const state=workspace.ensureMaterialFeeState();state.preview={summary:{total_cost_rmb:'100.00'}};
const button={disabled:false,label:'',prop(name,value){this[name]=value;return this},text(value){this.label=value;return this},attr(){return this}};
workspace.$root={find(selector){if(selector.includes('mf-preview-cost'))return button;return {length:0,toArray:()=>[],each(){},get(){return null},filter(){return this},first(){return this}}}};
workspace.escape=(value)=>String(value??'');workspace.renderMaterialFeeWorkspace=()=>{workspace.renders=(workspace.renders||0)+1};
workspace.renders=0;workspace.calls=0;
workspace.call=async()=>{workspace.calls++;return {ok:true,summary:{total_cost_rmb:'200.00'}}};
"""


def test_trial_saves_current_version_and_updates_other_tabs():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + r"""
workspace.detailState.editToken='TOKEN';workspace.detailState.expectedModified='M1';
workspace.ensureEditSession=async()=>true;
workspace.batches=[{name:'B-1',estimated_total_cost_rmb:100}];
let endpoint,args;workspace.call=async(e,a)=>{endpoint=e;args=a;return {ok:true,saved:true,batch_modified:'M2',summary:{total_cost_rmb:'64800.00'},summary_snapshot:{total_cost_rmb:'64800.00',calculation_schema:2}}};
await workspace.refreshMaterialFeeCostPreview();
console.log(JSON.stringify({endpoint,args,modified:workspace.detailState.expectedModified,batch:workspace.batches[0]}));
""")
    assert result["endpoint"].endswith(".calculate_comprehensive_cost")
    assert result["args"]["edit_token"] == "TOKEN" and result["args"]["expected_modified"] == "M1"
    assert result["modified"] == "M2"
    assert float(result["batch"]["estimated_total_cost_rmb"]) == 64800
    assert result["batch"]["status"] == "Calculated"


def test_packing_attachment_prepares_downloads_then_previews_exact_sheet():
    result = _fee_workspace_result(r"""
const workspace=Object.create(Harness.prototype);workspace.detailState={batchName:'B',versionName:'V'};
workspace.ensureEditSession=async()=>true;workspace.renderWikiMaterialSources=()=>{};
const source={source_id:'oa:source',source_kind:'approval_attachment',process_instance_id:'OA',file_id:'F',available:false};
const dialog={materialBatchName:'B',materialVersionName:'V',materialAttachmentSources:[source],hide(){this.hidden=true}};
workspace.loadWikiMaterialSources=async()=>{dialog.materialAttachmentSources=[{...source,source_id:'ATT',attachment_name:'ATT',available:true,sheets:['采购明细']}];return true};
const calls=[];workspace.call=async(endpoint,args)=>{calls.push([endpoint,args]);if(endpoint.endsWith('prepare_dingtalk_archive_attachment'))return {ok:true,attachment_name:'ATT'};if(endpoint.endsWith('download_oa_form_attachment'))return {ok:true};return {ok:true,rows:[]}};
workspace.openMaterialImportPreviewDialog=()=>{};
await workspace.previewMaterialAttachmentSource(dialog,'oa:source');console.log(JSON.stringify(calls));
""")
    assert [call[0].split(".")[-1] for call in result] == ["prepare_dingtalk_archive_attachment", "download_oa_form_attachment", "preview_material_import"]
    assert result[-1][1] == dict(batch_name="B", source_kind="approval_attachment", source_id="ATT", sheet_name="采购明细")


def test_packing_attachment_failure_preserves_picker_for_retry():
    result = _fee_workspace_result(r"""
const workspace=Object.create(Harness.prototype);workspace.detailState={batchName:'B',versionName:'V'};
workspace.ensureEditSession=async()=>true;workspace.renderWikiMaterialSources=()=>{};
const dialog={materialBatchName:'B',materialVersionName:'V',materialAttachmentSources:[{source_id:'ATT',attachment_name:'ATT',source_kind:'approval_attachment',available:false}],hide(){this.hidden=true}};
workspace.call=async()=>({ok:false,message:'附件正在归档，请稍后重试。'});
let error='';try{await workspace.previewMaterialAttachmentSource(dialog,'ATT')}catch(e){error=e.message}
console.log(JSON.stringify({error,busy:dialog.wikiMaterialBusy,hidden:Boolean(dialog.hidden)}));
""")
    assert result == dict(error="附件正在归档，请稍后重试。", busy="", hidden=False)


def test_trial_waits_for_pending_writes_and_ignores_duplicate_clicks():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + r"""
let release;const writing=workspace.trackMaterialFeeWrite(()=>new Promise(resolve=>{release=resolve}));
const first=workspace.refreshMaterialFeeCostPreview();
await new Promise(resolve=>setImmediate(resolve));
const before={calls:workspace.calls,disabled:button.disabled,label:button.label};
await workspace.refreshMaterialFeeCostPreview();release();await writing;await first;
console.log(JSON.stringify({before,calls:workspace.calls,preview:state.preview,disabled:button.disabled,running:state.previewRunning}));
""")
    assert result["before"] == {"calls": 0, "disabled": True, "label": "计算中…"}
    assert result["calls"] == 1
    assert result["preview"]["summary"]["total_cost_rmb"] == "200.00"
    assert result["disabled"] is False and result["running"] is False


@pytest.mark.parametrize("change", ["batch", "version", "tab", "reload", "input"])
def test_trial_discards_response_if_context_or_inputs_changed(change):
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + r"""
let release;workspace.call=()=>new Promise(resolve=>{release=resolve});
const running=workspace.refreshMaterialFeeCostPreview();await new Promise(resolve=>setImmediate(resolve));
""" + {
        "batch": "workspace.detailState.batchName='B-2';workspace.materialFeeState={batchName:'B-2',preview:{summary:{total_cost_rmb:'999.00'}}};",
        "version": "workspace.detailState.versionName='V-2';",
        "tab": "workspace.detailState.tab='vouchers';",
        "reload": "state.requestId++;",
        "input": "state.inputRevision++;",
    }[change] + r"""
release({ok:true,summary:{total_cost_rmb:'200.00'}});await running;
console.log(JSON.stringify({preview:workspace.materialFeeState.preview,renders:workspace.renders}));
""")
    assert result["preview"]["summary"]["total_cost_rmb"] == ("999.00" if change == "batch" else "100.00")
    assert result["renders"] == 0


@pytest.mark.parametrize("failure", ["draft", "material", "api"])
def test_trial_does_not_replace_result_after_invalid_input_or_failed_request(failure):
    setup = {
        "draft": "state.feeDrafts={freight:{amount:'',currency:'RMB',error:'费用金额不能为空。'}};",
        "material": "state.materialSaveErrors={'A:volume_m3':'保存失败'};",
        "api": "workspace.call=async()=>{workspace.calls++;return {ok:false,message:'试算服务失败'}};",
    }[failure]
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + setup + r"""
let error='';try {await workspace.refreshMaterialFeeCostPreview()}catch(e){error=e.message}
console.log(JSON.stringify({error,calls:workspace.calls,preview:state.preview,disabled:button.disabled}));
""")
    assert result["error"]
    assert result["calls"] == (1 if failure == "api" else 0)
    assert result["preview"]["summary"]["total_cost_rmb"] == "100.00"
    assert result["disabled"] is False


def test_unsupported_historical_currency_requires_explicit_selection_in_dialog():
    result = _fee_workspace_result(r"""
const workspace=Object.create(Harness.prototype);workspace.detailState={batchName:'B-1'};workspace.escape=value=>String(value??'');
workspace.materialFeeState={batchName:'B-1',fees:{fees:[{logical_fee_key:'old',amount:100,currency:'EUR'}]},materials:{items:[]}};
let fields;global.frappe.ui={Dialog:class{constructor(options){fields=options.fields;this.$wrapper={addClass(){}}}show(){}}};
workspace.openMaterialFeeDialog('old');console.log(JSON.stringify(fields.find(field=>field.fieldname==='currency')));
""")
    assert result["default"] == ""
    assert [option["value"] for option in result["options"]] == ["", "RMB", "MXN", "USD"]
    assert result["reqd"] == 1


def test_trial_flushes_dirty_fee_before_reading_preview():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + r"""
state.fees={fees:[{logical_fee_key:'fee'}]};state.feeDrafts={fee:{amount:'20',currency:'RMB'}};
const input={attr(){return 'fee'}};global.$=value=>value;const originalFind=workspace.$root.find;
workspace.$root.find=selector=>selector==='[data-mf-fee-amount]'?{each(callback){callback(0,input)}}:originalFind(selector);
const order=[];workspace.saveMaterialFeeInlineAmount=async()=>{order.push('save');delete state.feeDrafts.fee};workspace.call=async()=>{order.push('preview');return {ok:true,summary:{total_cost_rmb:'120.00'}}};
await workspace.refreshMaterialFeeCostPreview();console.log(JSON.stringify({order,total:state.preview.summary.total_cost_rmb}));
""")
    assert result == {"order": ["save", "preview"], "total": "120.00"}


MATERIAL_SAVE_FIXTURE = r"""
const workspace=Object.create(Harness.prototype);workspace.detailState={batchName:'B-1',versionName:'V-1',tab:'documents',header:{modified:'m1'}};
const state=workspace.ensureMaterialFeeState();state.materials={items:[{name:'A',volume_m3:'1'}]};workspace.normalizeErrorMessage=error=>error.message;
workspace.ensureEditSession=async()=>true;workspace.loadMaterialFeeWorkspace=async()=>true;
const cell={addClass(){return this},removeClass(){return this},attr(){return this}};
const data={},input={length:1,value:'2',val(){return this.value},attr(name){return {'data-original-value':'1','data-item-name':'A','data-fieldname':'volume_m3'}[name]},data(name,value){if(arguments.length>1){data[name]=value;return this}return data[name]},prop(){return this},closest(){return cell}};
workspace.call=async()=>({ok:true,batch_modified:'m2'});
"""


def test_material_save_denied_lease_is_not_safe_to_trial():
    result = _fee_workspace_result(MATERIAL_SAVE_FIXTURE + r"""
workspace.ensureEditSession=async()=>false;await workspace.saveMaterialFeeCell(input);
console.log(JSON.stringify({errors:state.materialSaveErrors,pending:state.pendingWrites.size}));
""")
    assert result["errors"].get("A:volume_m3")
    assert result["pending"] == 0


def test_reverting_failed_material_input_to_saved_value_clears_trial_blocker():
    result = _fee_workspace_result(MATERIAL_SAVE_FIXTURE + r"""
state.materialSaveErrors={'A:volume_m3':'failed'};input.value='1';await workspace.saveMaterialFeeCell(input);
console.log(JSON.stringify({errors:state.materialSaveErrors}));
""")
    assert result["errors"] == {}


def test_material_save_response_does_not_update_another_batch():
    result = _fee_workspace_result(MATERIAL_SAVE_FIXTURE + r"""
let release;workspace.call=()=>new Promise(resolve=>{release=resolve});let reloads=0;workspace.loadMaterialFeeWorkspace=async()=>{reloads++;return true};
const saving=workspace.saveMaterialFeeCell(input);await new Promise(resolve=>setImmediate(resolve));workspace.detailState={batchName:'B-2',tab:'documents',expectedModified:'other',header:{modified:'other'}};workspace.materialFeeState={batchName:'B-2'};
release({ok:true,batch_modified:'m2'});await saving;console.log(JSON.stringify({modified:workspace.detailState.expectedModified,reloads}));
""")
    assert result == {"modified": "other", "reloads": 0}


def test_material_grid_rerender_keeps_another_cells_unsaved_value():
    result = _fee_workspace_result(MATERIAL_SAVE_FIXTURE + r"""
workspace.escape=value=>String(value??'');workspace.formatValue=value=>String(value);workspace.materialFeeState.materialDrafts={};
workspace.updateMaterialDraftFromInput(input);
const html=workspace.renderMaterialFeeGridCell({name:'A',volume_m3:'1'}, {field:'volume_m3',label:'体积 m³',numeric:true},new Set(),1);
console.log(JSON.stringify({value:html.includes('value="2"'),original:html.includes('data-original-value="1"'),draft:state.materialDrafts['A:volume_m3']}));
""")
    assert result["value"] is True and result["original"] is True
    assert result["draft"]["value"] == "2"


def test_trial_saves_material_draft_before_reading_cost():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + r"""
state.materialDrafts={'A:volume_m3':{itemName:'A',fieldname:'volume_m3',value:'2'}};
const input={attr(name){return {'data-item-name':'A','data-fieldname':'volume_m3'}[name]}};global.$=value=>value;const originalFind=workspace.$root.find;
workspace.$root.find=selector=>selector==='[data-mf-cell-input]'?{each(callback){callback(0,input)}}:originalFind(selector);
const order=[];workspace.saveMaterialFeeCell=async()=>{order.push('save');delete state.materialDrafts['A:volume_m3']};workspace.call=async()=>{order.push('preview');return {ok:true,summary:{}}};
await workspace.refreshMaterialFeeCostPreview();console.log(JSON.stringify({order}));
""")
    assert result["order"] == ["save", "preview"]


def test_trial_stops_if_another_material_is_edited_while_flushing():
    result = _fee_workspace_result(PREVIEW_WORKSPACE_FIXTURE + r"""
state.materialDrafts={'B:volume_m3':{itemName:'B',fieldname:'volume_m3',value:'2'}};
const input={attr(name){return {'data-item-name':'B','data-fieldname':'volume_m3'}[name]}};global.$=value=>value;const originalFind=workspace.$root.find;
workspace.$root.find=selector=>selector==='[data-mf-cell-input]'?{each(callback){callback(0,input)}}:originalFind(selector);
workspace.saveMaterialFeeCell=async()=>{delete state.materialDrafts['B:volume_m3'];state.materialDrafts['C:volume_m3']={itemName:'C',fieldname:'volume_m3',value:'9'}};
let error='';try{await workspace.refreshMaterialFeeCostPreview()}catch(e){error=e.message}
console.log(JSON.stringify({calls:workspace.calls,error,total:state.preview.summary.total_cost_rmb,draft:state.materialDrafts['C:volume_m3'].value}));
""")
    assert result["calls"] == 0
    assert result["error"]
    assert result["total"] == "100.00"
    assert result["draft"] == "9"
