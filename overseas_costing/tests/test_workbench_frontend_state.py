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
