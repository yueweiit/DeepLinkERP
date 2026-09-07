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


def test_material_grid_default_quantity_has_explicit_source_label() -> None:
    result = _state_result(
        "console.log(JSON.stringify(s.materialQuantityView({"
        "quantity:'34',purchase_uom:'桶',actual_shipped_qty:'',"
        "actual_shipped_qty_mode:'DEFAULT_PURCHASE',shipped_uom:'桶'})));"
    )

    assert result == {
        "value": "34",
        "uom": "桶",
        "mode": "DEFAULT_PURCHASE",
        "sourceLabel": "采购数量默认",
        "isDefault": True,
    }


def test_material_grid_counts_only_server_supplied_requirements() -> None:
    result = _state_result(
        "console.log(JSON.stringify(s.summarizeMaterialRequirements(["
        "{cell_requirements:{goods_value:{severity:'blocking',gate:'calculation'},project_collection:{severity:'blocking',gate:'erp_push'}}},"
        "{cell_requirements:{gross_weight_kg:{severity:'optional',gate:'none'},project_collection:{severity:'blocking',gate:'erp_push'}}}"
        "])));"
    )

    assert result == {"calculation": 1, "erpPush": 2, "warnings": 0}


def test_material_grid_tab_moves_to_next_editable_cell() -> None:
    result = _state_result(
        "const cells=[{fieldname:'stable_line_key',editable:false},{fieldname:'quantity',editable:true},{fieldname:'total_cost_rmb',editable:false},{fieldname:'actual_shipped_qty',editable:true}];"
        "console.log(JSON.stringify({forward:s.nextMaterialEditableCell(cells,1,false),backward:s.nextMaterialEditableCell(cells,3,true)}));"
    )

    assert result == {"forward": 3, "backward": 1}


def test_material_grid_paste_cannot_modify_stable_line_id() -> None:
    result = _state_result(
        "console.log(JSON.stringify(s.buildMaterialPasteUpdates("
        "[{fieldname:'stable_line_key',editable:true},{fieldname:'actual_shipped_qty',editable:true},{fieldname:'total_cost_rmb',editable:false}],"
        "['attacker-key','32','999']"
        ")));"
    )

    assert result == [{"fieldname": "actual_shipped_qty", "value": "32"}]


def test_material_import_requires_sheet_mapping_and_conflict_decisions() -> None:
    result = _state_result(
        "const preview={sheet:{selected:'2026海运'},mapping:[{source:'品目编码',target:'material_code'}],rows:[{source_row:2,match_status:'matched',changes:[{field:'quantity',conflict:true}]}]};"
        "const missing=s.materialImportCanApply(preview,{mappingConfirmed:false,choices:{fields:{}}});"
        "const ready=s.materialImportCanApply(preview,{mappingConfirmed:true,choices:{fields:{'2':{quantity:'use_source'}}}});"
        "console.log(JSON.stringify({missing,ready}));"
    )

    assert result == {"missing": False, "ready": True}


def test_material_import_allows_non_workbook_oa_source_without_sheet() -> None:
    result = _state_result(
        "const preview={source:{kind:'approval_comment'},sheet:{selected:'',available:[]},mapping:[{source:'actual_shipped_qty',target:'actual_shipped_qty'}],rows:[{source_row:1,match_status:'matched',changes:[{field:'actual_shipped_qty',conflict:false}]}]};"
        "console.log(JSON.stringify({ready:s.materialImportCanApply(preview,{mappingConfirmed:true,choices:{matches:{},fields:{}}})}));"
    )

    assert result == {"ready": True}


def test_material_grid_static_ui_keeps_oa_manual_fallback_without_packing_plan() -> None:
    grid = (PARTS / "77-material-grid.js").read_text(encoding="utf-8")
    detail = (PARTS / "82-detail-page.js").read_text(encoding="utf-8")
    stylesheet = (PARTS / "48-material-grid.css").read_text(encoding="utf-8")

    for label in (
        "费用与凭证",
        "物料与装箱",
        "成本结果",
        "采购数量默认",
        "推送前补",
        "从 Excel 补充",
        "第 1 步：选择资料和 Sheet",
        "第 2 步：确认列映射和行匹配",
        "第 3 步：确认差异和冲突",
        "没有装箱计划也可以继续",
        "从 OA 附件补充",
        "人工补填",
    ):
        assert label in grid
    assert detail.index('["documents", "费用与凭证"]') < detail.index('["items", "物料与装箱"]')
    assert "overseas_costing.api.materials.get_material_grid" in grid
    assert "overseas_costing.api.materials.preview_material_import" in grid
    assert "overseas_costing.api.materials.apply_material_import" in grid
    assert "stable_line_key" in grid
    assert ".ocw-material-cell.is-calculation-blocking" in stylesheet
    assert ".ocw-material-cell.is-erp-blocking" in stylesheet


def test_packing_plan_is_contextual_input_not_globally_required_document() -> None:
    documents = (PARTS / "65-manual-documents.js").read_text(encoding="utf-8")

    for code in ("sea_packing_list", "air_packing_list", "express_goods_list"):
        definition = documents.split(f'code: "{code}"', 1)[1].split("}", 1)[0]
        assert "required: false" in definition
        assert "有则导入" in definition


def test_fee_task_and_fee_issue_have_stable_url_state() -> None:
    result = _state_result(
        "const parsed=s.parseWorkbenchState('http://localhost/app?screen=detail&batch=B-1&task=fees&tab=documents&issue=fee%3ATAX');"
        "console.log(JSON.stringify({task:parsed.task,tab:parsed.tab,focus:s.feeFocusFromIssue(parsed.issue),action:s.primaryActionForIssue('fees_incomplete'),actionTab:s.detailTabForAction('fees')}));"
    )

    assert result == {
        "task": "fees",
        "tab": "documents",
        "focus": "TAX",
        "action": {"action": "fees", "label": "处理费用"},
        "actionTab": "documents",
    }


def test_fee_work_summary_counts_fees_and_todos_separately() -> None:
    result = _state_result(
        "const work={items:[{logical_fee_key:'TAX',todos:[{code:'AMOUNT_REQUIRED'},{code:'ALLOCATION_REQUIRED'},{code:'EVIDENCE_REQUIRED'}]}],summary:{erp_status:'Success'}};"
        "console.log(JSON.stringify(s.summarizeFeeWork(work)));"
    )

    assert result == {"affectedFeeCount": 1, "todoCount": 3, "isComplete": False}


def test_fee_todo_labels_are_distinct_and_actionable() -> None:
    result = _state_result(
        "console.log(JSON.stringify(['AMOUNT_REQUIRED','ALLOCATION_REQUIRED','ACTUAL_AMOUNT_REQUIRED','EVIDENCE_REQUIRED','RECALCULATE_REQUIRED'].map((code)=>s.feeTodoPresentation(code))));"
    )

    assert [item["label"] for item in result] == ["金额待补", "待分摊", "暂估待实际", "凭证待补", "待重算"]
    assert all(item["action"] for item in result)


def test_erp_success_does_not_hide_fee_todos() -> None:
    result = _state_result(
        "console.log(JSON.stringify(s.summarizeFeeWork({summary:{erp_status:'Success'},items:[{logical_fee_key:'FREIGHT',todos:[{code:'ACTUAL_AMOUNT_REQUIRED'}]}]})));"
    )

    assert result == {"affectedFeeCount": 1, "todoCount": 1, "isComplete": False}


def test_fee_worklist_is_first_and_exposes_visible_states() -> None:
    fee_worklist = (PARTS / "78-fee-worklist.js").read_text(encoding="utf-8")
    detail = (PARTS / "82-detail-page.js").read_text(encoding="utf-8")
    view = (PARTS / "35-workbench-view.js").read_text(encoding="utf-8")
    vouchers = (PARTS / "40-vouchers.js").read_text(encoding="utf-8")
    stylesheet = (PARTS / "49-fee-worklist.css").read_text(encoding="utf-8")

    assert detail.index('data-area="fee-worklist"') < detail.index('data-area="manual-documents"')
    assert "renderFeeWorklist" in detail
    assert "成本处理" in detail
    assert "ERP 同步" in detail
    assert "fees_incomplete" in view
    for label in ("只看待办", "全部费用"):
        assert label in fee_worklist
    assert "overseas_costing.api.fees.get_fee_worklist" in fee_worklist
    assert "overseas_costing.api.fees.save_fee" in fee_worklist
    assert "overseas_costing.api.fees.link_fee_evidence" in fee_worklist
    assert "overseas_costing.api.fees.confirm_all_fees_complete" in fee_worklist
    assert "refreshFeeWorkAfterVoucherChange" in vouchers
    assert ".ocw-fee-row.is-error" in stylesheet
    assert ".ocw-fee-row.is-warning" in stylesheet
