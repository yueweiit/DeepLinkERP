(function (root, factory) {
 if (typeof module === "object" && module.exports) module.exports = factory;
 root.DeepLinkERPOperatingPaymentPanel = factory(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
 "use strict";
 const t = value => (root.__ || (text => text))(value);
 const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const tabs = [["request","申请信息"],["approvals","审批流"],["payments","付款记录"],["vouchers","凭证"]];
 function cents(value) {
  if (typeof value !== "string" || !/^\d{1,14}(?:\.\d{1,2})?$/.test(value)) throw new Error(t("金额须明确且最多两位小数"));
  const [whole, fraction=""] = value.split(".");
  return BigInt(whole)*100n+BigInt(fraction.padEnd(2,"0"));
 }
 const decimal = value => `${value/100n}.${String(value%100n).padStart(2,"0")}`;
 const classified = source => ["payment","reimbursement"].includes(source.effective_application_type||source.application_type);
 function proofUploaderOptions(paymentId,onSuccess) {
  // Native upload checks write access before invoking a custom method. Managed
  // payment records must stay read-only; the service authorizes this parent.
  return {method:"deeplinkerp_branding.services.operating_payment_service.upload_payment_proof",docname:paymentId,allow_multiple:false,allow_toggle_private:false,allow_web_link:false,allow_google_drive:false,allow_take_photo:false,disable_file_browser:true,restrictions:{allowed_file_types:[".pdf",".png",".jpg",".jpeg"],max_file_size:10*1024*1024},on_success:onSuccess};
 }
 function paymentPreview(balance, value) {
  const amount=cents(value), paid=cents(balance?.paid_amount), pending=cents(balance?.pending_amount);
  if (amount <= 0n || amount > pending) throw new Error(t("本次抵扣金额须大于零且不超过待付金额"));
  return {amount:decimal(amount),paid_amount:decimal(paid+amount),pending_amount:decimal(pending-amount)};
 }
 function canRegister(detail, finance) {
  try { return Boolean(finance && detail.company && classified(detail.source) && detail.source.approvals?.eligibility === "eligible" && detail.erp_payments?.managed && cents(detail.erp_payments.balance?.pending_amount)>0n); }
  catch (_) { return false; }
 }
 function timelineHTML(row) {
  if (row.lookup_status === "conflict") return `<p class="text-warning">${esc(t("审批身份冲突，请在钉钉原单核对"))}</p>`;
  if (!Array.isArray(row.events) || !row.events.length) return `<p class="text-muted">${esc(t("暂无可核对的审批节点，请查看钉钉原单"))}</p>`;
  const events=row.events.map((event,index)=>({...event,current:Boolean(event.current&&event.active!==false),index})).sort((a,b)=>String(a.time||"9999").localeCompare(String(b.time||"9999"))||a.index-b.index);
  const results={agree:"已同意",approved:"已同意",refuse:"已拒绝",rejected:"已拒绝",pending:"待处理"};
  const node=event=>`<li class="${event.current?"is-current":""}"><strong>${esc(event.stage||"—")}</strong> <span>${esc(event.operator||"—")}</span><small>${esc(event.time||"—")} · ${esc(t(results[event.result]||event.result||"—"))}${event.current?" · "+esc(t("当前节点")):""}</small>${event.comment?`<p>${esc(event.comment)}</p>`:""}${[ ["attachments","节点附件"],["images","节点图片"] ].map(([key,label])=>Array.isArray(event[key])&&event[key].length?`<span class="text-muted">${esc(t(label))} · ${event[key].length} · ${esc(t("请查看钉钉原单"))}</span>`:"").join(" ")}</li>`;
  const list=items=>`<ol class="dlp-operating-timeline">${items.map(node).join("")}</ol>`;
  const summary=events.length>5?events.filter((event,index)=>index===0||index>=events.length-2||event.current):events;
  return `<p class="text-muted">${esc(t("缓存同步时间"))} · ${esc(row.last_synced_at||"—")}</p>${list(summary)}${events.length>5?`<details><summary>${esc(t("展开全部审批节点"))} (${events.length})</summary>${list(events)}</details>`:""}`;
 }
 const confirm = message => new Promise(resolve => root.frappe.confirm(message,()=>resolve(true),()=>resolve(false)));
 async function mount(drawer, detail, helpers) {
  const {makeControl,action,uiTask,request,reload,canFinance,sourceId}=helpers;
  const body=drawer.panel.find(".dlp-payment-body"), source=detail.source;
  const tabsHolder=root.$(`<nav class="dlp-operating-tabs" role="tablist">${tabs.map(([key,label])=>`<button type="button" role="tab" data-operating-tab="${key}">${esc(t(label))}</button>`).join("")}</nav>`).insertAfter(body.find(".dlp-operating-hero"));
  const panes=body.find("[data-operating-pane]");
  let timelineLoaded=false;
  async function selectTab(tab) {
   drawer.activeOperatingTab=tab;
   tabsHolder.find("button").each((_i,node)=>{const active=node.dataset.operatingTab===tab; root.$(node).toggleClass("active",active).attr("aria-selected",String(active));});
   panes.each((_i,node)=>root.$(node).prop("hidden",node.dataset.operatingPane!==tab));
   if (tab!=="approvals" || timelineLoaded) return;
   timelineLoaded=true;
   const target=body.find(".dlp-operating-timeline-holder"), load=drawer.loadId;
   target.text(t("读取审批缓存…"));
   try {
    const row=await request("get_approval_timeline",{source_id:sourceId});
    if (drawer.alive() && load===drawer.loadId) target.html(timelineHTML(row));
   } catch(error) { if(drawer.alive() && load===drawer.loadId){target.text(error.message);timelineLoaded=false;} }
  }
  tabsHolder.on("click.dlpDrawer","button",event=>selectTab(event.currentTarget.dataset.operatingTab));
  body.find(".dlp-operating-start-payment").on("click.dlpDrawer",()=>selectTab("payments"));
  const holder=body.find(".dlp-operating-register"), actions=root.$('<div class="dlp-operating-actions"></div>').appendTo(holder);
  if(!classified(source)) holder.prepend(`<p class="text-warning">${esc(t("请先在财务映射中明确付款申请或费用报销，不能默认按供应商付款。"))}</p>`);
  if (!detail.erp_payments?.managed) {
   let zeroConfirmed=false;
   const needsZeroConfirmation=Array.isArray(source.payments)&&source.payments.length===0;
   if(needsZeroConfirmation) await makeControl(drawer,root.$('<div></div>').insertBefore(actions),{fieldname:"zero_history_confirmed",fieldtype:"Check",label:t("已核对完整历史，确认这笔申请此前没有实际付款")},0,value=>{zeroConfirmed=Boolean(value);drawer.refreshEligibility();});
   holder.prepend(`<p class="text-muted">${esc(t("核对并接管对应申请的历史付款后，新付款只在 ERP 登记；不会停用请款网站其他申请。"))}</p>`);
   action(drawer,actions,"核对历史并启用 ERP 付款",async()=>{
    const preview=await uiTask(drawer,()=>request("preview_takeover",{source_id:sourceId,zero_history_confirmed:zeroConfirmed}));
    if (!drawer.alive() || !preview) return;
    if (!preview.existing && !(await confirm(`${esc(t("已核对历史"))} ${preview.history_count} ${esc(t("笔，待付"))} ${esc(preview.balance.pending_amount)} ${esc(preview.currency)}。${esc(t("启用后，对应申请在请款网站不能再登记付款。确认接管？"))}`))) return;
    if (!drawer.alive()) return;
    if (!preview.existing) await uiTask(drawer,()=>request("claim_takeover",{source_id:sourceId,expected_source_version:preview.source_version,expected_history_version:preview.history_version,request_id:root.crypto.randomUUID(),zero_history_confirmed:zeroConfirmed}));
    if (drawer.alive()) await reload();
   },()=>Boolean(canFinance() && detail.company && classified(source) && source.approvals?.eligibility==="eligible" && (!needsZeroConfirmation||zeroConfirmed)));
  } else if (canRegister(detail,canFinance())) {
   const values={payment_date:root.frappe.datetime.get_today(),amount:"",bank_amount:"",bank_account:"",party_type:detail.mapping?.party_type||((source.effective_application_type||source.application_type)==="reimbursement"?"Employee":"Supplier"),party:detail.mapping?.party||"",bank_reference:"",remark:""};
   const requestId=root.crypto.randomUUID(), fields=root.$('<div class="dlp-operating-fields"></div>').insertBefore(actions), preview=root.$('<p class="dlp-operating-payment-preview" role="status"></p>').insertBefore(actions);
   function update() { try { const next=paymentPreview(detail.erp_payments.balance,values.amount); preview.text(`${t("登记后累计已付")} ${next.paid_amount} ${source.currency} · ${t("剩余待付")} ${next.pending_amount} ${source.currency}`); } catch(error){preview.text(error.message);} drawer.refreshEligibility(); }
   const definitions=[["payment_date","Date",null,"实际付款日期"],["amount","Data",null,`抵扣申请金额 (${source.currency||"—"})`],["bank_account","Link","Account","付款银行 / 现金科目"],["bank_amount","Data",null,"银行实际付款金额（银行科目币种）"],["party","Link",values.party_type,"收款往来方"],["bank_reference","Data",null,"银行流水号"],["remark","Small Text",null,"付款备注"]];
   for (const [fieldname,fieldtype,options,label] of definitions) {
    const query=fieldname==="bank_account"?()=>({filters:{company:detail.company,is_group:0,disabled:0,account_type:["in",["Bank","Cash"]]}}):fieldname==="party"&&values.party_type==="Employee"?()=>({filters:{company:detail.company}}):null;
    await makeControl(drawer,root.$("<div></div>").appendTo(fields),{fieldname,fieldtype,options,label,reqd:["payment_date","amount","bank_account","bank_amount","party"].includes(fieldname)},values[fieldname],value=>{values[fieldname]=String(value??"");update();},query);
   }
   const advanced=root.$(`<details class="dlp-operating-advanced"><summary>${esc(t("预付款、跨币种及辅助核算"))}</summary><p class="text-muted">${esc(t("费用尚未发生：明确填写预付／往来科目及汇率，仅生成预付款草稿，不确认费用。"))}</p><div class="dlp-operating-fields"></div></details>`).insertBefore(actions);
   for (const [fieldname,fieldtype,options,label] of [["advance_account","Link","Account","预付款 / 往来科目（费用尚未发生时填写）"],["source_exchange_rate","Data",null,"申请币种兑本位币汇率"],["bank_exchange_rate","Data",null,"银行币种兑本位币汇率"],["exchange_difference_account","Link","Account","汇兑损益科目"],["cost_center","Link","Cost Center","成本中心"],["project","Link","Project","项目"]]) await makeControl(drawer,root.$("<div></div>").appendTo(advanced.find(".dlp-operating-fields")),{fieldname,fieldtype,options,label},"",value=>{if(value) values[fieldname]=String(value);else delete values[fieldname];update();},options?()=>({filters:{company:detail.company}}):null);
   const ready=()=>{try {paymentPreview(detail.erp_payments.balance,values.amount);return cents(values.bank_amount)>0n&&Boolean(values.bank_account&&values.party&&values.payment_date);}catch(_){return false;}};
   action(drawer,actions,"登记实际付款",async()=>{
    if (!(await confirm(esc(t("确认已经实际支付并登记本笔付款？此操作不向银行转账，不自动记账。"))))) return;
    if (!drawer.alive()) return;
    await uiTask(drawer,()=>request("register_payment",{source_id:sourceId,values:JSON.stringify(values),expected_source_version:source.version,request_id:requestId}));
    if (drawer.alive()) await reload();
   },ready,true);
   holder.prepend(`<p class="text-muted">${esc(t("支持部分付款。付款记录与凭证分开；登记后可补传回单，再预览凭证草稿。"))}</p>`);
  } else holder.prepend(`<p class="text-muted">${esc(detail.erp_payments?.notice||t("已付清或当前审批／权限待核对，不能登记新付款。"))}</p>`);
  const local=body.find(".dlp-operating-local-payments");
  for (const payment of detail.erp_payments?.payments||[]) {
   const section=root.$(`<article class="dlp-operating-payment-card"><strong>${esc(payment.payment_date)} · ${esc(t("抵扣"))} ${esc(payment.amount)} ${esc(payment.currency)}</strong><p>${esc(t("银行实际支付"))} ${esc(payment.bank_amount)} ${esc(payment.bank_currency)} · ${esc(payment.bank_account)} · ${esc(payment.bank_reference||"—")}</p><p>${esc(payment.remark||"")}</p><small>${esc(t(payment.status==="Reversed"?"已撤销":"ERP 登记"))} · ${esc(payment.registered_by)} ${esc(payment.reversal_reason||"")}</small><div class="dlp-operating-actions"></div></article>`).appendTo(local);
   action(drawer,section.find(".dlp-operating-actions"),"补传回单",()=>{
    new root.frappe.ui.FileUploader(proofUploaderOptions(payment.name,()=>{if(drawer.alive())reload();}));
   },()=>canFinance()&&payment.status==="Registered");
   section.append(`<p class="text-muted">${esc(t(payment.proof_status||"回单待补"))}</p>`);
   for(const file of payment.proofs||[]) root.$(`<a class="btn btn-link" target="_blank" rel="noopener noreferrer" href="/api/method/deeplinkerp_branding.services.operating_payment_service.download_payment_proof?source_id=${encodeURIComponent(sourceId)}&payment_id=${encodeURIComponent(payment.name)}&file_id=${encodeURIComponent(file.name)}">${esc(file.filename)}</a>`).appendTo(section);
   if(payment.status==="Registered") action(drawer,section.find(".dlp-operating-actions"),"撤销登记",async()=>{
    root.frappe.prompt({fieldname:"reason",fieldtype:"Small Text",label:t("撤销原因"),reqd:1},async values=>{
     if(!drawer.alive())return;
     const draft=(detail.events||[]).some(event=>event.payment_source_id==="erp-payment:"+payment.name&&event.docstatus===0);
     if(draft&&!(await confirm(esc(t("此付款有未记账凭证草稿。确认弃用该草稿并撤销付款登记？草稿保留恢复记录和事件审计，不会提交、记账或转账。")))))return;
     if(!drawer.alive())return;
     try {await uiTask(drawer,()=>request("reverse_payment",{source_id:sourceId,payment_id:payment.name,reason:values.reason,request_id:root.crypto.randomUUID(),discard_drafts:draft}));if(drawer.alive())await reload();} catch(error){if(drawer.alive())drawer.error(error);}
    },t("撤销付款登记"));
   },()=>canFinance());
   if(payment.advance_configured && payment.status==="Registered") {
    const card=root.$(`<article class="dlp-operating-payment-card"><strong>${esc(t("预付款"))} · ${esc(payment.amount)} ${esc(payment.currency)}</strong><p class="text-muted">${esc(t("仅预付／往来，不确认费用；凭证保持草稿，未核销。"))}</p><div class="dlp-operating-actions"></div><div class="dlp-operating-payment-voucher-preview"></div></article>`).appendTo(body.find('[data-operating-pane="vouchers"]').first());
    let voucher=null;
    const association=(detail.events||[]).find(event=>event.payment_source_id==="erp-payment:"+payment.name);
    if(association) card.append(`<p>${esc(t("对应凭证"))} · ${esc(association.journal_entry||association.issue||"—")}</p>`);
    action(drawer,card.find(".dlp-operating-actions"),"预览预付款凭证",async()=>{
     voucher=await uiTask(drawer,()=>helpers.voucherRequest("preview_voucher",{source_id:sourceId,payment_source_id:"erp-payment:"+payment.name}));
     if(drawer.alive()&&voucher) card.find(".dlp-operating-payment-voucher-preview").html(helpers.previewHTML(voucher));
    },()=>canFinance()&&!association);
    action(drawer,card.find(".dlp-operating-actions"),"保存预付款凭证草稿",async()=>{
     if(!(await confirm(esc(t("确认保存预付款凭证草稿？不确认费用、不自动记账。")))))return;
     if(!drawer.alive())return;
     await uiTask(drawer,()=>helpers.voucherRequest("create_voucher_draft",{source_id:sourceId,payment_source_id:"erp-payment:"+payment.name,expected_fingerprint:voucher.fingerprint}));
     if(drawer.alive())await reload();
    },()=>canFinance()&&Boolean(voucher)&&!association);
   }
  }
  await selectTab(drawer.activeOperatingTab||"request");
 }
 return {tabs,paymentPreview,timelineHTML,canRegister,proofUploaderOptions,mount};
});
