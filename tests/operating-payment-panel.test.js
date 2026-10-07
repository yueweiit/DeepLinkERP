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
 const html = panel.timelineHTML({lookup_status:"found",last_synced_at:"2026-10-07",events:[{id:"1",stage:"经理",operator:"A",time:"2026-10-01",result:"agree"},{id:"2",stage:"财务",operator:"<script>x</script>",time:"2026-10-02",result:"agree",comment:"ok",current:true}]});
 assert.ok(html.indexOf("经理") < html.indexOf("财务"));
 assert.match(html,/2026-10-07/); assert.match(html,/&lt;script&gt;/); assert.doesNotMatch(html,/<script>/);
 assert.match(panel.timelineHTML({lookup_status:"missing",events:[]}),/暂无/);
 assert.match(panel.timelineHTML({lookup_status:"conflict",events:[]}),/冲突/);
});
test("takeover and voucher are separate from registration and payment tabs are explicit", () => {
 const panel = api();
 assert.deepEqual(panel.tabs.map(t=>t[0]),["payments","approvals","request","vouchers"]);
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
 assert.doesNotMatch(api().timelineHTML({current_tasks:[],events:[{stage:"finance",current:true,active:true}]}),/当前节点|is-current/);
});
test("payment policy controls registration independently from an unfinished overall approval", () => {
 const source={application_type:"payment",approvals:{eligibility:"blocked"},payment_eligibility:{can_register_payment:true,notice:"出纳正在办理"},oa_identity:{process_instance_id:"OA-1"}};
 const detail={company:"C",source,erp_payments:{managed:true,balance:{pending_amount:"5.00"}}};
 assert.equal(api().canRegister(detail,true),true);
 assert.equal(api().canTakeover({...detail,erp_payments:{managed:false}},true),true);
 assert.equal(api().canRegister({...detail,source:{...source,approvals:{eligibility:"eligible"},payment_eligibility:{can_register_payment:false,notice:"等待主管"}}},true),false);
 assert.equal(api().canRegister({...detail,source:{...source,payment_eligibility:{}}},true),false);
 assert.equal(api().needsHistoryConfirmation({...detail,erp_payments:{needs_zero_history_confirmation:true}}),true);
 assert.equal(api().needsHistoryConfirmation({...detail,erp_payments:{needs_zero_history_confirmation:false}}),false);
 assert.equal(api().needsHistoryConfirmation({...detail,source:{...source,payments:[]},erp_payments:{}}),true);
});
test("timeline renders authoritative current tasks and collapsed CC without sorting or inventing future nodes", () => {
 const events=[{id:"later",stage:"Later timestamp first",time:"2026-10-05",current:true,result:"AGREE"},{id:"cc",stage:"抄送",type:"CC",operator:"<cc>",comment:"<img src=x>"},{id:"older",stage:"Older timestamp last",time:"2026-10-01",result:"AGREE"}];
 events.sort=()=>assert.fail("source API owns event order");
 const html=api().timelineHTML({events,current_tasks:[{id:"live",stage:"出纳",assignees:[{id:"A",name:"王<出纳>"}],status:"RUNNING",entered_at:"2026-10-07"}],originator:{name:"张三"},source_updated_at:"2026-10-06",last_synced_at:"2026-10-07",original_url:"javascript:alert(1)"});
 assert.match(html,/当前.*出纳.*王&lt;出纳&gt;.*审批中/s);
 assert.match(html,/<details[^>]*class="dlp-operating-cc"/);
 assert.match(html,/后续节点尚未同步/);
 assert.ok(html.indexOf("Later timestamp first")<html.indexOf("Older timestamp last"));
 assert.doesNotMatch(html,/javascript:|<img|后续.*总经理/);
 assert.match(html,/&lt;img src=x&gt;/);
 assert.deepEqual(api().balanceProgress({amount:"1000.00",paid_amount:"300.00"}),{percent:30,label:"30%"});
 assert.equal(api().balanceProgress({amount:null,paid_amount:"0.00"}),null);
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
test("takeover requires a unique cashier root and disables mismatched or unapproved source facts", () => {
 const panel=api(), detail={company:"C",source:{application_type:"payment",approvals:{eligibility:"eligible"},cashier_source_id:"root-1"}};
 assert.equal(panel.canTakeover(detail,true),true);
 assert.equal(panel.canTakeover(detail,false),false);
 assert.equal(panel.canTakeover(null,true),false);
 for(const source of [
  {...detail.source,cashier_source_id:null},
  {...detail.source,approvals:{eligibility:"blocked"}},
  {...detail.source,source_conflict:true},
  {...detail.source,currency_conflict:true},
  {...detail.source,effective_application_type:"unclassified"},
 ]) assert.equal(panel.canTakeover({...detail,source},true),false);
 assert.equal(panel.canTakeover({...detail,company:null},true),false);
 assert.match(panel.takeoverIssue({...detail,source:{...detail.source,cashier_source_id:null}},true),/唯一出纳申请/);
 assert.equal(panel.canTakeover({...detail,source:{...detail.source,cashier_source_id:null,source_system:"cashier-payment-archive",source_id:"1001"}},true),true);
 const registered={...detail,erp_payments:{managed:true,balance:{pending_amount:"5.00"}}};
 assert.equal(panel.canRegister({...registered,source:{...detail.source,source_conflict:true}},true),false);
});
test("real uppercase DingTalk approval results are readable without inventing approval for NONE", () => {
 const html=api().timelineHTML({events:[{stage:"submit",result:"NONE"},{stage:"finance",result:"AGREE"},{stage:"reject",result:"REFUSE"}]});
 assert.match(html,/已同意/);
 assert.match(html,/已拒绝/);
 assert.doesNotMatch(html,/NONE|AGREE|REFUSE/);
 const unknown=api().timelineHTML({events:[{stage:"other",result:"constructor"},{stage:"unknown",result:"<unknown>"},{stage:"trimmed",result:" AgReE "}]});
 assert.match(unknown,/constructor/);
 assert.match(unknown,/&lt;unknown&gt;/);
 assert.match(unknown,/已同意/);
 assert.doesNotMatch(unknown,/<unknown>|function Object/);
});
function panelHost(detail,apiResponses={}) {
 const controls=new Map(),actions=new Map(),requests=[],surfaces=[],errors=[];
 class Surface {
  constructor(markup=""){this.markup=markup;this.props={};this.value="";this.length=1;surfaces.push(this);}
  find(selector){return new Surface(selector);} insertAfter(){return this;} insertBefore(){return this;} appendTo(target){this.parent=target;return this;} prepend(){return this;} append(){return this;}
  on(){return this;} each(){return this;} toggleClass(){return this;} attr(){return this;} prop(key,value){this.props[key]=value;return this;} html(value){this.value=value;return this;} text(value){this.value=value;return this;} first(){return this;}
 }
 const root={$:value=>new Surface(value),crypto:{randomUUID:()=>"request-id"},frappe:{datetime:{get_today:()=>"2026-10-07"},confirm:(_m,yes)=>yes()}};
 const drawer={panel:new Surface(),loadId:1,alive:()=>true,refreshEligibility(){},error:error=>errors.push(error.message)};
 const helpers={sourceId:"source-1",canFinance:()=>true,reload:async()=>{},uiTask:async (_d,fn)=>fn(),request:async (method,args)=>{requests.push({method,args});return apiResponses[method]||[];},makeControl:async (_d,holder,df,value,change,query)=>{const control={df,value,holder,query,change,set_value:async next=>{control.value=next;},get_value:()=>control.value};controls.set(df.fieldname,control);return control;},action:(_d,holder,label,handler,eligible)=>{const button=new Surface(label);actions.set(label,{holder,handler,eligible,button});return button;}};
 return {root,drawer,helpers,controls,actions,requests,surfaces,errors,detail};
}
test("payment form starts folded and same-currency account sends exact amount with native party defaults", async () => {
 const detail={company:"C",mapping:{party_type:"Supplier",party:"SUP-1"},source:{source_id:"source-1",version:"v1",application_type:"payment",currency:"CNY",payee_name:"京东",payment_eligibility:{can_register_payment:true}},erp_payments:{managed:true,balance:{paid_amount:"300.00",pending_amount:"700.00"},payments:[]}};
 const h=panelHost(detail,{get_payment_accounts:[{name:"bank-CNY",label:"公司人民币账户",currency:"CNY"},{name:"bank-USD",label:"公司美元账户",currency:"USD"}],register_payment:{name:"payment-1"}});
 await require(file)(h.root).mount(h.drawer,detail,h.helpers);
 assert.equal(h.drawer.activeOperatingTab,"payments");
 assert.ok(h.actions.has("新增付款"));
 const form=h.surfaces.find(surface=>surface.markup.includes("dlp-operating-payment-form"));
 assert.equal(form.props.hidden,true);
 await h.actions.get("新增付款").handler();
 assert.equal(form.props.hidden,false);
 assert.equal(h.controls.get("bank_account").df.fieldtype,"Select");
 assert.deepEqual(h.controls.get("bank_account").df.options[1],{value:"bank-CNY",label:"公司人民币账户 (CNY)"});
 assert.equal(h.controls.get("bank_account").query,undefined);
 const rates=h.surfaces.find(surface=>surface.markup.includes("dlp-operating-exchange-rates"));
 assert.ok(rates,"Existing accounting exchange-rate fields remain reachable for same-currency foreign advances");
 assert.match(rates.parent.markup,/dlp-operating-advanced/);
 assert.equal(h.controls.get("party").df.fieldtype,"Link");
 assert.equal(h.controls.get("party").df.options,"Supplier");
 assert.equal(h.controls.get("party").value,"SUP-1");
 h.controls.get("amount").change("200.00");
 h.controls.get("bank_account").change("bank-CNY");
 assert.equal(h.actions.get("保存付款记录").eligible(),true);
 assert.ok(h.surfaces.some(surface=>/500\.00 CNY.*500\.00 CNY/.test(surface.value)));
 await h.actions.get("保存付款记录").handler();
 const saved=JSON.parse(h.requests.find(row=>row.method==="register_payment").args.values);
 assert.equal(saved.amount,"200.00");assert.equal(saved.bank_amount,"200.00");assert.equal(saved.party,"SUP-1");
 h.controls.get("bank_account").change("bank-USD");
 assert.equal(h.actions.get("保存付款记录").eligible(),false);
 assert.ok(h.surfaces.some(surface=>/申请币种 CNY.*银行币种 USD/.test(surface.value)));
 assert.match(rates.parent.markup,/dlp-operating-cross-currency/);
 h.controls.get("bank_amount").change("28.00");
 assert.equal(h.actions.get("保存付款记录").eligible(),false,"Cross-currency payment requires both explicit base-currency rates");
 h.controls.get("source_exchange_rate").change("1.000000");
 h.controls.get("bank_exchange_rate").change("7.100000");
 assert.equal(h.actions.get("保存付款记录").eligible(),true);
 h.controls.get("bank_exchange_rate").change("0");
 assert.equal(h.actions.get("保存付款记录").eligible(),false);
});
test("a closed drawer cannot initialize payment controls after scoped account lookup resolves", async () => {
 const detail={company:"C",source:{version:"v1",application_type:"payment",currency:"CNY",payment_eligibility:{can_register_payment:true}},erp_payments:{managed:true,balance:{paid_amount:"0.00",pending_amount:"10.00"}}};
 const h=panelHost(detail);let resolve,alive=true;
 h.drawer.alive=()=>alive;
 h.helpers.request=()=>new Promise(done=>resolve=done);
 const pending=require(file)(h.root).mount(h.drawer,detail,h.helpers);
 alive=false;resolve([{name:"bank",label:"Bank",currency:"CNY"}]);
 await pending;assert.equal(h.controls.size,0);assert.equal(h.actions.size,0);
});
test("proof upload is optional after persisted payment and never passed as saved evidence", async () => {
 const detail={company:"C",mapping:{party_type:"Employee",party:"EMP-1"},source:{source_id:"source-1",version:"v1",application_type:"reimbursement",currency:"CNY",payment_eligibility:{can_register_payment:true}},erp_payments:{managed:true,balance:{paid_amount:"0.00",pending_amount:"10.00"}}};
 const h=panelHost(detail,{get_payment_accounts:[{name:"bank",label:"Bank",currency:"CNY"}],register_payment:{payment_id:"payment-1"}});let uploader;
 h.root.frappe.ui={FileUploader:class{constructor(options){uploader=options;}}};
 await require(file)(h.root).mount(h.drawer,detail,h.helpers);
 await h.actions.get("新增付款").handler();h.controls.get("amount").change("5.00");h.controls.get("bank_account").change("bank");h.controls.get("upload_proof").change(1);
 await h.actions.get("保存付款记录").handler();
 assert.equal(uploader.docname,"payment-1");assert.equal(uploader.allow_toggle_private,false);
 assert.equal(JSON.parse(h.requests.find(row=>row.method==="register_payment").args.values).upload_proof,undefined);
});
test("unknown OA-only history requires deliberate confirmation before authoritative takeover preview", async () => {
 const detail={company:"C",source:{version:"v1",application_type:"payment",currency:"CNY",oa_identity:{corp_id:"corp",process_instance_id:"OA-1"},payment_eligibility:{can_register_payment:true},payments:[]},erp_payments:{managed:false,needs_zero_history_confirmation:true}};
 const h=panelHost(detail,{preview_takeover:{history_count:0,needs_zero_history_confirmation:true,source_version:"v1",history_version:"h1",balance:{pending_amount:"100.00"},currency:"CNY"},claim_takeover:{}});
 await require(file)(h.root).mount(h.drawer,detail,h.helpers);
 const takeover=h.actions.get("核对历史付款");assert.ok(takeover);
 assert.equal(takeover.eligible(),false);assert.equal(h.requests.length,0);
 h.controls.get("zero_history_confirmed").change(1);
 assert.equal(takeover.eligible(),true);
 await takeover.handler();
 assert.deepEqual(h.requests.map(row=>row.method),["preview_takeover","claim_takeover"]);
 assert.equal(h.requests[0].args.zero_history_confirmed,true);
 assert.equal(h.requests[1].args.expected_history_version,"h1");
});
