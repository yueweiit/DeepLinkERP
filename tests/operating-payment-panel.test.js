const test = require("node:test"), assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const file = path.join(__dirname, "../deeplinkerp_branding/public/js/operating_payment_panel.js");
const api = () => { assert.ok(fs.existsSync(file), "Payment panel exists"); return require(file)({}); };
test("partial payment preview uses exact cents and preserves distinct bank amount", () => {
 const panel = api();
 assert.deepEqual(panel.paymentPreview({paid_amount:"30",pending_amount:"70"},"20.01"), {amount:"20.01",paid_amount:"50.01",pending_amount:"49.99"});
 for (const amount of ["0","-1","70.01","1.001","NaN",1.2]) assert.throws(() => panel.paymentPreview({paid_amount:"30",pending_amount:"70"},amount));
 assert.throws(() => panel.paymentPreview({paid_amount:null,pending_amount:null},"1"));
});
test("approval timeline contains only real nodes, safely escapes source text and exposes sync stamp", () => {
 const panel = api();
 const html = panel.timelineHTML({lookup_status:"found",last_synced_at:"2026-10-07",events:[{id:"2",stage:"财务",operator:"<script>x</script>",time:"2026-10-02",result:"agree",comment:"ok",current:true},{id:"1",stage:"经理",operator:"A",time:"2026-10-01",result:"agree"}]});
 assert.ok(html.indexOf("经理") < html.indexOf("财务"));
 assert.match(html,/2026-10-07/); assert.match(html,/&lt;script&gt;/); assert.doesNotMatch(html,/<script>/);
 assert.match(panel.timelineHTML({lookup_status:"missing",events:[]}),/暂无/);
 assert.match(panel.timelineHTML({lookup_status:"conflict",events:[]}),/冲突/);
});
test("takeover and voucher are separate from registration and payment tabs are explicit", () => {
 const panel = api();
 assert.deepEqual(panel.tabs.map(t=>t[0]),["request","approvals","payments","vouchers"]);
 assert.equal(panel.canRegister({company:"C",source:{application_type:"payment",approvals:{eligibility:"eligible"}},erp_payments:{managed:true,balance:{pending_amount:"5.00"}}},true),true);
 assert.equal(panel.canRegister({company:"C",source:{approvals:{eligibility:"eligible"}},erp_payments:{managed:false,balance:null}},true),false);
 assert.equal(panel.canRegister({company:"C",source:{approvals:{eligibility:"eligible"}},erp_payments:{managed:true,balance:{pending_amount:"0"}}},true),false);
});
test("unclassified requests cannot expose a registration form with an assumed supplier", () => {
 const detail={company:"C",source:{application_type:"payment",effective_application_type:"unclassified",approvals:{eligibility:"eligible"}},erp_payments:{managed:true,balance:{pending_amount:"5.00"}}};
 assert.equal(api().canRegister(detail,true),false);
 detail.source.effective_application_type="reimbursement";
 assert.equal(api().canRegister(detail,true),true);
 assert.equal(api().canRegister(detail,false),false);
});
test("long timelines are summarized with all real nodes available and image counts retained", () => {
 const html=api().timelineHTML({events:Array.from({length:8},(_,i)=>({id:String(i),stage:`node-${i}`,time:`2026-10-0${i+1}`,images:i===3?[{id:"image-1"}]:[],current:i===3}))});
 assert.match(html,/展开全部审批节点/);
 assert.match(html,/节点图片/);
 assert.match(html,/node-7/);
 assert.match(html,/node-3/);
});
test("inactive cached nodes retain history without claiming to be the current approver", () => {
 const html=api().timelineHTML({events:[{stage:"historical-finance",current:true,active:false,result:"agree"}]});
 assert.match(html,/historical-finance/);
 assert.doesNotMatch(html,/当前节点|is-current/);
 assert.match(api().timelineHTML({events:[{stage:"finance",current:true,active:true}]}),/当前节点/);
});
test("private proof uploader uses the authorized service without granting editable payment access", () => {
 const options=api().proofUploaderOptions("payment-1",()=>{});
 assert.equal(options.doctype,undefined);
 assert.equal(options.docname,"payment-1");
 assert.match(options.method,/operating_payment_service\.upload_payment_proof$/);
 assert.equal(options.allow_toggle_private,false);
 assert.equal(options.allow_web_link,false);
 assert.equal(options.allow_google_drive,false);
 assert.equal(options.disable_file_browser,true);
});
