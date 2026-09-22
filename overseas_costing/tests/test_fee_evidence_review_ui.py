"""费用凭证审核前端契约。"""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "page" / "overseas_cost_workbench" / "parts" / "78-material-fee-workspace.js"
MATRIX_PART = ROOT / "page" / "overseas_cost_workbench" / "parts" / "78-fee-evidence-review-matrix.js"
CSS = ROOT / "page" / "overseas_cost_workbench" / "parts" / "48-material-fee-workspace.css"
MATRIX_CSS = ROOT / "page" / "overseas_cost_workbench" / "parts" / "48-fee-evidence-review-matrix.css"
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
    matrix_source = MATRIX_PART.read_text(encoding="utf-8")
    css = MATRIX_CSS.read_text(encoding="utf-8")
    for endpoint in (
        "start_fee_evidence_review",
        "get_fee_evidence_review_status",
        "apply_fee_evidence_review",
        "discard_fee_evidence_review",
    ):
        assert endpoint in source
    for label in ("凭证总额", "费用拆分", "物料 / SKU", "清关服务费", "物料合计", "核对状态"):
        assert label in matrix_source
    assert "ocw-mf-evidence-review-dialog" in source
    assert 'data-fieldname="item"' not in source + matrix_source
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


def test_embedded_voucher_real_start_failure_returns_not_started_and_keeps_visible_error() -> None:
    result = _voucher_click_result(
        VOUCHER_CLICK_FIXTURE
        + r"""
const node={empty(){return this},removeData(){return this}};
let dialogShows=0;const progress=[];const errors=[];
frappe.ui={Dialog:class{
  constructor(){this.$wrapper={length:1,addClass(){return this},on(){return this},find(){return node}}}
  show(){dialogShows++}
}};
const state={feeEvidenceReviewStartPromise:null,feeEvidenceReviewDialog:null};
workspace.ensureMaterialFeeState=()=>state;
workspace.materialFeeState=state;
workspace.ensureMaterialFeeEditSession=async()=>true;
workspace.getDetailBatch=()=>({current_version:'VERSION-1'});
workspace.findMaterialFee=()=>({required_evidence_role:'tax_certificate'});
workspace.renderFeeEvidenceReviewProgressShell=()=>'<div></div>';
workspace.updateFeeEvidenceReviewProgress=()=>progress.push({status:state.feeEvidenceReview?.status,error:state.feeEvidenceReview?.error_message});
workspace.materialAIErrorMessage=(error,fallback)=>error?.message||fallback;
workspace.call=async(endpoint)=>{if(endpoint.endsWith('start_fee_evidence_review'))throw new Error('启动接口不可用');throw new Error(endpoint)};
workspace.showError=(error)=>errors.push(error.message);
const handler=handlers["click[data-action='ai-review-voucher']"];
const started=await handler({preventDefault(){},currentTarget:button});
console.log(JSON.stringify({started,dialogShows,review:state.feeEvidenceReview,progress,errors,button:{disabled:button.disabled,label:button.label}}));
"""
    )

    assert result["started"] is False
    assert result["dialogShows"] == 1
    assert result["review"]["status"] == "FAILED"
    assert result["review"]["error_message"] == "启动接口不可用"
    assert result["errors"] == []
    assert result["button"] == {"disabled": False, "label": "AI 解析并分摊到 SKU"}


def test_voucher_record_dialog_closes_once_only_after_real_review_start() -> None:
    result = _voucher_click_result(
        r"""
const passive={empty(){return this},removeData(){return this},addClass(){return this},on(){return this},find(){return this}};
const dialogs=[];
frappe.ui={Dialog:class{
  constructor(){
    this.handlers={};this.hideCalls=0;this.showCalls=0;
    this.$wrapper={length:1,addClass:()=>this.$wrapper,on:(event,selector,handler)=>{this.handlers[`${event}${selector}`]=handler;return this.$wrapper},find:()=>passive};
    dialogs.push(this);
  }
  show(){this.showCalls++}
  hide(){this.hideCalls++}
}};
const button={attrs:{'data-batch-name':'BATCH-3','data-version-name':'VERSION-3','data-attachment-name':'ATTACHMENT-3'},disabled:false,label:'AI 解析并分摊到 SKU'};
const buttonQuery={
  attr(name){return button.attrs[name]||''},
  prop(name,value){if(value===undefined)return button[name];button[name]=value;return this},
  text(value){if(value===undefined)return button.label;button.label=value;return this},
};
dollar=(value)=>value===button?buttonQuery:passive;
const workspace=Object.create(Harness.prototype);
workspace.detailState={batchName:'BATCH-3',versionName:'VERSION-3'};
const state={feeEvidenceReviewStartPromise:null,feeEvidenceReviewDialog:null};
workspace.ensureMaterialFeeState=()=>state;
workspace.materialFeeState=state;
workspace.ensureMaterialFeeEditSession=async()=>true;
workspace.getDetailBatch=()=>({current_version:'VERSION-3'});
workspace.findMaterialFee=()=>({required_evidence_role:'tax_certificate'});
workspace.renderTaxCertificateRecordDetail=()=>'<div></div>';
workspace.renderFeeEvidenceReviewProgressShell=()=>'<div></div>';
workspace.updateFeeEvidenceReviewProgress=()=>{};
workspace.pollFeeEvidenceReview=async()=>{};
workspace.showError=()=>{};
let startCalls=0;
workspace.call=async(endpoint)=>{
  if(endpoint.endsWith('get_tax_certificate_parse_record'))return {ok:true,record_summary:{batch:{name:'BATCH-3'},version:'VERSION-3'}};
  if(endpoint.endsWith('start_fee_evidence_review')){startCalls++;return {ok:true,run_id:'RUN-3',status:'QUEUED'}};
  throw new Error(endpoint);
};
await workspace.openTaxCertificateRecordDialog('ATTACHMENT-3');
const detail=dialogs[0];
const handler=detail.handlers["click[data-action='ai-review-voucher']"];
const event={preventDefault(){},currentTarget:button};
const first=handler(event);const duplicate=handler(event);
await Promise.all([first,duplicate]);
console.log(JSON.stringify({startCalls,hideCalls:detail.hideCalls,reviewDialogs:dialogs.length-1,button:{disabled:button.disabled,label:button.label}}));
"""
    )

    assert result == {
        "startCalls": 1,
        "hideCalls": 1,
        "reviewDialogs": 1,
        "button": {"disabled": False, "label": "AI 解析并分摊到 SKU"},
    }


def test_voucher_record_dialog_stays_open_when_real_start_fails_or_edit_session_is_missing() -> None:
    result = _voucher_click_result(
        r"""
async function run(mode){
  const passive={empty(){return this},removeData(){return this},addClass(){return this},on(){return this},find(){return this}};
  const dialogs=[];
  frappe.ui={Dialog:class{
    constructor(){
      this.handlers={};this.hideCalls=0;
      this.$wrapper={length:1,addClass:()=>this.$wrapper,on:(event,selector,handler)=>{this.handlers[`${event}${selector}`]=handler;return this.$wrapper},find:()=>passive};
      dialogs.push(this);
    }
    show(){}
    hide(){this.hideCalls++}
  }};
  const button={attrs:{'data-batch-name':'BATCH-4','data-version-name':'VERSION-4','data-attachment-name':'ATTACHMENT-4'},disabled:false,label:'AI 解析并分摊到 SKU'};
  const buttonQuery={attr:(name)=>button.attrs[name]||'',prop(name,value){if(value===undefined)return button[name];button[name]=value;return this},text(value){if(value===undefined)return button.label;button.label=value;return this}};
  dollar=(value)=>value===button?buttonQuery:passive;
  const workspace=Object.create(Harness.prototype);
  workspace.detailState={batchName:'BATCH-4',versionName:'VERSION-4'};
  const state={feeEvidenceReviewStartPromise:null,feeEvidenceReviewDialog:null};
  workspace.ensureMaterialFeeState=()=>state;
  workspace.materialFeeState=state;
  workspace.ensureMaterialFeeEditSession=async()=>mode!=='edit-missing';
  workspace.getDetailBatch=()=>({current_version:'VERSION-4'});
  workspace.findMaterialFee=()=>({required_evidence_role:'tax_certificate'});
  workspace.renderTaxCertificateRecordDetail=()=>'<div></div>';
  workspace.renderFeeEvidenceReviewProgressShell=()=>'<div></div>';
  workspace.updateFeeEvidenceReviewProgress=()=>{};
  workspace.materialAIErrorMessage=(error,fallback)=>error?.message||fallback;
  workspace.showError=()=>{};
  workspace.call=async(endpoint)=>{
    if(endpoint.endsWith('get_tax_certificate_parse_record'))return {ok:true,record_summary:{batch:{name:'BATCH-4'},version:'VERSION-4'}};
    if(endpoint.endsWith('start_fee_evidence_review'))throw new Error('启动接口不可用');
    throw new Error(endpoint);
  };
  await workspace.openTaxCertificateRecordDialog('ATTACHMENT-4');
  const detail=dialogs[0];
  const started=await detail.handlers["click[data-action='ai-review-voucher']"]({preventDefault(){},currentTarget:button});
  return {started,hideCalls:detail.hideCalls,dialogCount:dialogs.length,reviewStatus:state.feeEvidenceReview?.status||'',button:{disabled:button.disabled,label:button.label}};
}
console.log(JSON.stringify({apiFailure:await run('api-failure'),editMissing:await run('edit-missing')}));
"""
    )

    assert result["apiFailure"] == {
        "started": False,
        "hideCalls": 0,
        "dialogCount": 2,
        "reviewStatus": "FAILED",
        "button": {"disabled": False, "label": "AI 解析并分摊到 SKU"},
    }
    assert result["editMissing"] == {
        "started": False,
        "hideCalls": 0,
        "dialogCount": 1,
        "reviewStatus": "",
        "button": {"disabled": False, "label": "AI 解析并分摊到 SKU"},
    }


def test_voucher_start_returns_before_delayed_poll_and_background_failure_does_not_change_result() -> None:
    result = _voucher_click_result(
        r"""
const passive={empty(){return this},removeData(){return this},addClass(){return this},on(){return this},find(){return this}};
const dialogs=[];
frappe.ui={Dialog:class{
  constructor(){
    this.handlers={};this.hideCalls=0;
    this.$wrapper={length:1,addClass:()=>this.$wrapper,on:(event,selector,handler)=>{this.handlers[`${event}${selector}`]=handler;return this.$wrapper},find:()=>passive};
    dialogs.push(this);
  }
  show(){}
  hide(){this.hideCalls++}
}};
const button={attrs:{'data-batch-name':'BATCH-5','data-version-name':'VERSION-5','data-attachment-name':'ATTACHMENT-5'},disabled:false,label:'AI 解析并分摊到 SKU'};
const buttonQuery={attr:(name)=>button.attrs[name]||'',prop(name,value){if(value===undefined)return button[name];button[name]=value;return this},text(value){if(value===undefined)return button.label;button.label=value;return this}};
dollar=(value)=>value===button?buttonQuery:passive;
const workspace=Object.create(Harness.prototype);
workspace.detailState={batchName:'BATCH-5',versionName:'VERSION-5'};
const state={feeEvidenceReviewStartPromise:null,feeEvidenceReviewDialog:null};
workspace.ensureMaterialFeeState=()=>state;
workspace.materialFeeState=state;
workspace.ensureMaterialFeeEditSession=async()=>true;
workspace.getDetailBatch=()=>({current_version:'VERSION-5'});
workspace.findMaterialFee=()=>({required_evidence_role:'tax_certificate'});
workspace.renderTaxCertificateRecordDetail=()=>'<div></div>';
workspace.renderFeeEvidenceReviewProgressShell=()=>'<div></div>';
workspace.updateFeeEvidenceReviewProgress=()=>{};
workspace.materialAIErrorMessage=(error,fallback)=>error?.message||fallback;
workspace.showError=()=>{};
workspace.call=async(endpoint)=>{
  if(endpoint.endsWith('get_tax_certificate_parse_record'))return {ok:true,record_summary:{batch:{name:'BATCH-5'},version:'VERSION-5'}};
  if(endpoint.endsWith('start_fee_evidence_review'))return {ok:true,run_id:'RUN-5',status:'QUEUED'};
  throw new Error(endpoint);
};
let finishPoll;
workspace.pollFeeEvidenceReview=()=>new Promise((resolve,reject)=>{finishPoll=()=>reject(new Error('后台分析失败'))});
await workspace.openTaxCertificateRecordDialog('ATTACHMENT-5');
const detail=dialogs[0];
let settled=false;let started;
const click=detail.handlers["click[data-action='ai-review-voucher']"]({preventDefault(){},currentTarget:button}).then(value=>{settled=true;started=value});
await new Promise(resolve=>setImmediate(resolve));
const beforePoll={settled,hideCalls:detail.hideCalls,button:{disabled:button.disabled,label:button.label}};
finishPoll();await click;await new Promise(resolve=>setImmediate(resolve));
console.log(JSON.stringify({started,beforePoll,afterPoll:{hideCalls:detail.hideCalls,status:state.feeEvidenceReview.status,error:state.feeEvidenceReview.error_message}}));
"""
    )

    assert result == {
        "started": True,
        "beforePoll": {
            "settled": True,
            "hideCalls": 1,
            "button": {"disabled": False, "label": "AI 解析并分摊到 SKU"},
        },
        "afterPoll": {"hideCalls": 1, "status": "FAILED", "error": "后台分析失败"},
    }


def test_different_voucher_request_is_rejected_while_edit_lease_is_pending() -> None:
    result = _voucher_click_result(
        r"""
const passive={empty(){return this},removeData(){return this},addClass(){return this},on(){return this},find(){return this}};
frappe.ui={Dialog:class{constructor(){this.$wrapper={length:1,addClass(){return this},on(){return this},find(){return passive}}}show(){}}};
const alerts=[];frappe.show_alert=(value)=>alerts.push(value);
const workspace=Object.create(Harness.prototype);
workspace.detailState={batchName:'BATCH-6',versionName:'VERSION-6'};
const state={feeEvidenceReviewStartPromise:null,feeEvidenceReviewDialog:null};
workspace.ensureMaterialFeeState=()=>state;
workspace.materialFeeState=state;
let releaseLease;let leaseCalls=0;const leasePromise=new Promise(resolve=>{releaseLease=resolve});
workspace.ensureMaterialFeeEditSession=()=>{leaseCalls++;return leasePromise};
workspace.findMaterialFee=()=>({required_evidence_role:'tax_certificate'});
workspace.renderFeeEvidenceReviewProgressShell=()=>'<div></div>';
workspace.updateFeeEvidenceReviewProgress=()=>{};
workspace.pollFeeEvidenceReview=async()=>{};
let startCalls=0;workspace.call=async()=>{startCalls++;return {ok:true,run_id:`RUN-${startCalls}`,status:'QUEUED'}};
const first=workspace.openFeeEvidenceReviewDialog('import_tax','ATTACHMENT-A',{batchName:'BATCH-6',versionName:'VERSION-6',evidenceRole:'tax_certificate'});
let secondSettled=false;let secondValue;
const second=workspace.openFeeEvidenceReviewDialog('import_tax','ATTACHMENT-B',{batchName:'BATCH-6',versionName:'VERSION-6',evidenceRole:'tax_certificate'}).then(value=>{secondSettled=true;secondValue=value});
await new Promise(resolve=>setImmediate(resolve));
const pending={leaseCalls,secondSettled,secondValue,alerts};
releaseLease(true);const firstValue=await first;await second;
console.log(JSON.stringify({pending,firstValue,secondValue,leaseCalls,startCalls,attachment:state.feeEvidenceReview?.attachment}));
"""
    )

    assert result["pending"]["leaseCalls"] == 1
    assert result["pending"]["secondSettled"] is True
    assert result["pending"]["secondValue"] is False
    assert "已有凭证正在启动/分析" in result["pending"]["alerts"][0]["message"]
    assert result["firstValue"] is True
    assert result["leaseCalls"] == 1
    assert result["startCalls"] == 1
    assert result["attachment"] == "ATTACHMENT-A"


def test_same_voucher_request_reuses_pending_start_without_duplicate_lease_or_api() -> None:
    result = _voucher_click_result(
        r"""
const passive={empty(){return this},removeData(){return this},addClass(){return this},on(){return this},find(){return this}};
frappe.ui={Dialog:class{constructor(){this.$wrapper={length:1,addClass(){return this},on(){return this},find(){return passive}}}show(){}}};
const workspace=Object.create(Harness.prototype);
workspace.detailState={batchName:'BATCH-7',versionName:'VERSION-7'};
const state={feeEvidenceReviewStartPromise:null,feeEvidenceReviewDialog:null};
workspace.ensureMaterialFeeState=()=>state;
workspace.materialFeeState=state;
let releaseLease;let leaseCalls=0;const leasePromise=new Promise(resolve=>{releaseLease=resolve});
workspace.ensureMaterialFeeEditSession=()=>{leaseCalls++;return leasePromise};
workspace.findMaterialFee=()=>({required_evidence_role:'tax_certificate'});
workspace.renderFeeEvidenceReviewProgressShell=()=>'<div></div>';
workspace.updateFeeEvidenceReviewProgress=()=>{};
workspace.pollFeeEvidenceReview=async()=>{};
let startCalls=0;workspace.call=async()=>{startCalls++;return {ok:true,run_id:'RUN-7',status:'QUEUED'}};
const options={batchName:'BATCH-7',versionName:'VERSION-7',evidenceRole:'tax_certificate'};
const first=workspace.openFeeEvidenceReviewDialog('import_tax','ATTACHMENT-7',options);
const duplicate=workspace.openFeeEvidenceReviewDialog('import_tax','ATTACHMENT-7',options);
await new Promise(resolve=>setImmediate(resolve));
const pending={leaseCalls,startCalls};
releaseLease(true);const values=await Promise.all([first,duplicate]);
console.log(JSON.stringify({pending,values,leaseCalls,startCalls}));
"""
    )

    assert result == {
        "pending": {"leaseCalls": 1, "startCalls": 0},
        "values": [True, True],
        "leaseCalls": 1,
        "startCalls": 1,
    }


def test_review_marks_conflicts_and_missing_fx_in_default_preview() -> None:
    source = MATRIX_PART.read_text(encoding="utf-8")
    css = MATRIX_CSS.read_text(encoding="utf-8")

    assert "has_conflict" in source and "needs_review" in source
    assert "ocw-mf-review-warning" in source
    assert ".ocw-mf-review-warning" in css
    assert "缺汇率：可保存原币事实" in source


def test_matrix_css_keeps_two_identity_columns_and_actions_usable_on_narrow_screens() -> None:
    css = MATRIX_CSS.read_text(encoding="utf-8")

    assert "position: sticky" in css
    assert ":is(th,td):first-child" in css
    assert ":is(th,td):nth-child(2)" in css
    assert "overflow: auto" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 560px)" in css
    assert "min-height: 44px" in css
    assert ".ocw-mf-matrix-totals { position: static" not in css


def test_review_shows_precise_source_locator_and_refund_parent() -> None:
    source = MATRIX_PART.read_text(encoding="utf-8")

    for token in (
        "ref.page",
        "ref.text_line",
        "ref.cell",
        "ref.region",
        'data-fieldname="related_evidence"',
    ):
        assert token in source


def test_review_matrix_is_extracted_and_only_submits_sparse_allowed_fields() -> None:
    source = PART.read_text(encoding="utf-8")
    matrix_source = MATRIX_PART.read_text(encoding="utf-8")

    assert "renderFeeEvidenceReviewDraft(draft" not in source
    assert "renderFeeEvidenceReviewDraft(draft" in matrix_source
    assert "component_matrix_json" in source
    assert "validateFeeEvidenceMatrix" in source
    assert "serializeFeeEvidenceMatrix" in matrix_source
    assert "amount_rmb" not in matrix_source.split("serializeFeeEvidenceMatrix", 1)[1].split("feeEvidenceFeeTotals", 1)[0]
    assert "hs_code" not in matrix_source.split("serializeFeeEvidenceMatrix", 1)[1].split("feeEvidenceFeeTotals", 1)[0]


def test_review_task_actions_do_not_calculate_confirm_or_push_erp() -> None:
    source = PART.read_text(encoding="utf-8")
    review_source = source.split("async openFeeEvidenceReviewDialog", 1)[1].split(
        "async setMaterialFeeEvidenceStatus", 1
    )[0]

    assert "calculate_comprehensive_cost" not in review_source
    assert "confirm_" not in review_source
    assert "erp" not in review_source.lower()


def test_evidence_picker_groups_the_three_pullable_processes() -> None:
    """费用申请、国际物流、采购三类资料都必须出现在关联凭证弹窗中。"""

    source = PART.read_text(encoding="utf-8")
    picker = source.split("renderMaterialFeeEvidencePicker(candidates, linked)", 1)[1].split(
        "evidenceSourceGroups(candidates)", 1
    )[0]
    groups = source.split("evidenceSourceGroups(candidates)", 1)[1].split("async linkSelectedMaterialFeeEvidence", 1)[0]

    # 三类来源在服务端判定的 workflow_stage 上分组，前端不私造流程顺序。
    for stage in ("payment", "international_logistics", "purchase"):
        assert f'"{stage}"' in groups
    assert "workflow_stage" in groups
    # 分组标签面向业务，而不是直接展示英文阶段名。
    for label in ("费用申请", "国际物流", "采购"):
        assert label in groups
    # 三流程分组标题恒定展示：即使某流程当前 0 份也要出现，否则用户无法区分
    # “这条流程没有资料”和“这条流程没被支持”。
    assert "alwaysVisible" in groups
    for stage in ("payment", "international_logistics", "purchase"):
        assert f'alwaysVisible = ["payment", "international_logistics", "purchase"]' in groups
    # 空分组给出空态提示，而不是整组消失。
    assert "ocw-mf-evidence-source-empty" in picker
    assert "该流程暂无可关联资料" in picker
    # 弹窗仍提供上传兜底。
    assert "mf-upload-evidence" in picker
    assert "上传新凭证并解析" in picker


def test_evidence_picker_keeps_scope_warning_instead_of_hiding_candidates() -> None:
    """不在当前采购支出范围的候选只做提示，不再被隐藏或整体降级。"""

    source = PART.read_text(encoding="utf-8")
    picker = source.split("renderMaterialFeeEvidencePicker(candidates, linked)", 1)[1].split(
        "evidenceSourceGroups(candidates)", 1
    )[0]

    assert "in_current_source" in picker
    assert "stage_selectable" in picker
    assert "不在当前采购支出范围" in picker
    assert "audit_only" not in picker


def test_evidence_picker_always_renders_the_three_process_group_titles() -> None:
    """采购、费用申请、国际物流三组标题必须恒定出现，某组 0 份时显示空态。

    只渲染“有数据的组”会让用户无法区分“这条流程没有资料”和“这条流程没被
    支持”，因此分组标题集合与候选数据无关。
    """

    source = PART.read_text(encoding="utf-8")
    groups = source.split("evidenceSourceGroups(candidates)", 1)[1].split(
        "async linkSelectedMaterialFeeEvidence", 1
    )[0]

    # 固定顺序：三流程在前，其他资料垫底。
    assert 'const order = ["payment", "international_logistics", "purchase", "other"]' in groups
    # 恒定展示的集合只含三流程，不含“其他资料”。
    assert 'const alwaysVisible = ["payment", "international_logistics", "purchase"]' in groups
    assert "alwaysVisible.includes(group.stage)" in groups
    # 空分组仍然产出分组对象（rows 为空），不是被 filter 掉。
    assert "group.rows.length || alwaysVisible.includes(group.stage)" in groups

    # 渲染层为空分组提供空态文案。
    picker = source.split("renderMaterialFeeEvidencePicker(candidates, linked)", 1)[1].split(
        "evidenceSourceGroups(candidates)", 1
    )[0]
    assert "ocw-mf-evidence-source-empty" in picker
    assert "该流程暂无可关联资料，可上传新凭证。" in picker


def test_evidence_picker_highlights_voucher_file_names() -> None:
    """文件名含“凭证”的候选要高亮；判定读服务端标记，前端不自己匹配关键词。"""

    source = PART.read_text(encoding="utf-8")
    picker = source.split("renderMaterialFeeEvidencePicker(candidates, linked)", 1)[1].split(
        "evidenceSourceGroups(candidates)", 1
    )[0]

    # 高亮只由服务端 is_voucher_name 驱动。
    assert "candidate.is_voucher_name" in picker
    assert "is-voucher" in picker
    assert "ocw-mf-evidence-voucher-tag" in picker
    # 前端不得复制服务端的关键词判定。
    assert '"凭证"' not in picker and "'凭证'" not in picker

    css = CSS.read_text(encoding="utf-8")
    assert ".ocw-mf-evidence-option.is-voucher" in css
    assert ".ocw-mf-evidence-voucher-tag" in css


def test_evidence_picker_renders_the_server_summary_and_never_recomputes_it() -> None:
    """摘要必须是服务端既有解析结果的投影，前端只做展示与截断。"""

    source = PART.read_text(encoding="utf-8")
    renderer = source.split("materialFeeEvidenceSummaryHtml(candidate)", 1)[1].split(
        "evidenceSourceGroups(candidates)", 1
    )[0]

    assert "candidate?.summary" in renderer
    assert "ocw-mf-evidence-summary" in renderer
    # 键值对上限与后端一致，避免超长摘要撑破弹窗。
    assert ".slice(0, 8)" in renderer
    # 前端不参与任何金额或业务判定。
    assert "amount" not in renderer.lower()

    css = CSS.read_text(encoding="utf-8")
    assert ".ocw-mf-evidence-summary" in css
