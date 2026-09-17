"""费用凭证审核前端契约。"""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "page" / "overseas_cost_workbench" / "parts" / "78-material-fee-workspace.js"
CSS = ROOT / "page" / "overseas_cost_workbench" / "parts" / "48-material-fee-workspace.css"
WORKBENCH = ROOT / "page" / "overseas_cost_workbench" / "overseas_cost_workbench.js"


def _voucher_click_result(script: str) -> dict:
    completed = subprocess.run(
        [
            "node",
            "-e",
            (
                "const fs=require('fs');"
                f"const source=fs.readFileSync({json.dumps(str(WORKBENCH))},'utf8');"
                "global.document={};global.window={};"
                "const frappe={pages:{'overseas-cost-workbench':{}},boot:{desktop_icons:[]}};"
                "let dollar=()=>({});const $=(value)=>dollar(value);"
                "const Harness=Function('frappe','$','requestAnimationFrame',"
                "source+'; return OverseasCostWorkbench;')(frappe,$,()=>{});"
                f"(async()=>{{{script}}})().catch((error)=>{{console.error(error);process.exit(1)}});"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


VOUCHER_CLICK_FIXTURE = r"""
const handlers={};
const passive={off(){return this},on(){return this}};
const root={
  on(event,selector,handler){handlers[`${event}${selector}`]=handler;return this},
  find(){return passive},
};
const button={
  attrs:{'data-batch-name':'BATCH-1','data-version-name':'VERSION-1','data-attachment-name':'ATTACHMENT-1'},
  disabled:false,
  label:'AI 解析并分摊到 SKU',
};
const buttonQuery={
  attr(name){return button.attrs[name]||''},
  prop(name,value){if(value===undefined)return button[name];button[name]=value;return this},
  text(value){if(value===undefined)return button.label;button.label=value;return this},
};
dollar=(value)=>value===button?buttonQuery:passive;
const workspace=Object.create(Harness.prototype);
workspace.$root=root;
workspace.detailState={batchName:'BATCH-1',versionName:'VERSION-1'};
workspace.bindRedesignEvents();
"""


def test_fee_row_has_independent_status_and_voucher_first_action() -> None:
    source = PART.read_text(encoding="utf-8")
    renderer = source.split("renderMaterialFeeRow(fee)", 1)[1].split("materialFeeGridColumns", 1)[0]

    assert 'data-mf-fee-status="1"' in renderer
    assert "待补" in renderer and "暂估" in renderer and "实际" in renderer
    assert "未发生" in renderer and "已包含" in renderer
    assert "关联并解析凭证" in renderer
    assert "请先编辑并保存这笔费用" not in source
    assert "default_status_for_amount_entry" not in source
    assert 'amount_status: amountStatus === "MISSING" ? "ESTIMATED" : amountStatus' in source


def test_fee_evidence_review_uses_wide_incremental_ai_dialog_and_new_apis() -> None:
    source = PART.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for endpoint in (
        "start_fee_evidence_review",
        "get_fee_evidence_review_status",
        "apply_fee_evidence_review",
        "discard_fee_evidence_review",
    ):
        assert endpoint in source
    for label in ("凭证总额", "费用拆分", "税种", "HS / SKU 匹配", "待归类差额", "来源证据"):
        assert label in source
    assert "ocw-mf-evidence-review-dialog" in source
    assert 'data-fieldname="item"' in source
    assert ".ocw-mf-evidence-review-modal .modal-dialog" in css
    assert "replaceWith" not in source.split("updateFeeEvidenceReviewProgress", 1)[1].split("renderFeeEvidenceReviewDraft", 1)[0]


def test_voucher_page_exposes_shared_ai_review_entry() -> None:
    source = (PARTS := ROOT / "page" / "overseas_cost_workbench" / "parts" / "40-vouchers.js").read_text(encoding="utf-8")
    assert "AI 解析并分摊到 SKU" in source
    assert "openFeeEvidenceReviewDialog" in source


def test_embedded_voucher_ai_click_is_single_flight_and_restores_after_failure() -> None:
    result = _voucher_click_result(
        VOUCHER_CLICK_FIXTURE
        + r"""
const handler=handlers["click[data-action='ai-review-voucher']"];
if(!handler){
  console.log(JSON.stringify({bound:false}));
  return;
}
const calls=[];const errors=[];
let release;
workspace.openVoucherFeeEvidenceReview=(payload)=>{calls.push(payload);return new Promise(resolve=>{release=resolve})};
workspace.showError=(error)=>errors.push(error.message);
const event={preventDefault(){},currentTarget:button};
const first=handler(event);
const during={disabled:button.disabled,label:button.label};
const duplicate=handler(event);
release();
await Promise.all([first,duplicate]);
const afterSuccess={disabled:button.disabled,label:button.label};
workspace.openVoucherFeeEvidenceReview=async(payload)=>{calls.push(payload);throw new Error('启动失败')};
const failed=handler(event);
const duringFailure={disabled:button.disabled,label:button.label};
await failed;
console.log(JSON.stringify({bound:true,calls,errors,during,afterSuccess,duringFailure,afterFailure:{disabled:button.disabled,label:button.label}}));
"""
    )

    assert result == {
        "bound": True,
        "calls": [
            {"batchName": "BATCH-1", "versionName": "VERSION-1", "attachment": "ATTACHMENT-1"},
            {"batchName": "BATCH-1", "versionName": "VERSION-1", "attachment": "ATTACHMENT-1"},
        ],
        "errors": ["启动失败"],
        "during": {"disabled": True, "label": "正在启动 AI…"},
        "afterSuccess": {"disabled": False, "label": "AI 解析并分摊到 SKU"},
        "duringFailure": {"disabled": True, "label": "正在启动 AI…"},
        "afterFailure": {"disabled": False, "label": "AI 解析并分摊到 SKU"},
    }


def test_existing_voucher_dialog_ai_click_uses_the_same_single_flight_guard() -> None:
    result = _voucher_click_result(
        r"""
const handlers={};
const passive={on(){return this},addClass(){return this},removeClass(){return this},trigger(){return this},text(){return this},get(){return []}};
const data={'ocw-voucher-batch-name':'FALLBACK-BATCH'};
const wrapper={
  on(event,selector,handler){handlers[`${event}${selector}`]=handler;return this},
  find(){return passive},
  data(name,value){if(value===undefined)return data[name];data[name]=value;return this},
  removeData(name){delete data[name];return this},
};
const button={attrs:{'data-batch-name':'BATCH-2','data-version-name':'VERSION-2','data-attachment-name':'ATTACHMENT-2'},disabled:false,label:'AI 解析并分摊到 SKU'};
const buttonQuery={
  attr(name){return button.attrs[name]||''},
  prop(name,value){if(value===undefined)return button[name];button[name]=value;return this},
  text(value){if(value===undefined)return button.label;button.label=value;return this},
};
dollar=(value)=>value===button?buttonQuery:passive;
const workspace=Object.create(Harness.prototype);
workspace.bindVoucherDropzone({$wrapper:wrapper});
const handler=handlers["click[data-action='ai-review-voucher']"];
let release;const calls=[];workspace.showError=()=>{};
workspace.openVoucherFeeEvidenceReview=(payload)=>{calls.push(payload);return new Promise(resolve=>{release=resolve})};
const event={preventDefault(){},currentTarget:button};
const first=handler(event);const duplicate=handler(event);
const during={disabled:button.disabled,label:button.label};
release();await Promise.all([first,duplicate]);
console.log(JSON.stringify({calls,during,after:{disabled:button.disabled,label:button.label}}));
"""
    )

    assert result == {
        "calls": [{"batchName": "BATCH-2", "versionName": "VERSION-2", "attachment": "ATTACHMENT-2"}],
        "during": {"disabled": True, "label": "正在启动 AI…"},
        "after": {"disabled": False, "label": "AI 解析并分摊到 SKU"},
    }


def test_review_marks_conflicts_and_missing_fx_without_default_selection() -> None:
    source = PART.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "has_conflict" in source and "needs_review" in source
    assert "ocw-mf-review-warning" in source
    assert ".ocw-mf-review-warning" in css
    assert "缺汇率：可保存原币事实，本次试算不会计入" in source


def test_review_shows_precise_source_locator_and_refund_parent() -> None:
    source = PART.read_text(encoding="utf-8")

    for token in (
        "ref.page",
        "ref.text_line",
        "ref.cell",
        "ref.region",
        'data-fieldname="related_evidence"',
    ):
        assert token in source


def test_review_task_actions_do_not_calculate_confirm_or_push_erp() -> None:
    source = PART.read_text(encoding="utf-8")
    review_source = source.split("async openFeeEvidenceReviewDialog", 1)[1].split(
        "async setMaterialFeeEvidenceStatus", 1
    )[0]

    assert "calculate_comprehensive_cost" not in review_source
    assert "confirm_" not in review_source
    assert "erp" not in review_source.lower()
