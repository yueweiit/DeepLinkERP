from __future__ import annotations

import json
import subprocess
from pathlib import Path


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
    stylesheet = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    documents_block = detail_page.split("async renderDocumentsDetailTab()", 1)[1].split(
        "async renderVoucherDetailTab()", 1
    )[0]

    assert "loadMaterialFeeWorkspace" in documents_block
    assert "renderManualDocumentPanel" not in documents_block
    for label in (
        "费用与凭证",
        "预览综合单价",
        "物料与装箱数据",
        "只看缺项",
        "展开辅助列",
        "导入 Excel 补资料",
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
    assert "本次未识别出金额，可手工补录" in workspace
    assert "writeback" not in workspace.lower()
    assert "recalculate" not in workspace.lower()
    assert ".ocw-mf-workspace" in stylesheet
    assert ".ocw-mf-cell.is-missing" in stylesheet
    assert ".ocw-mf-cell.is-default" in stylesheet
    assert ".ocw-mf-cell.is-save-error" in stylesheet


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
