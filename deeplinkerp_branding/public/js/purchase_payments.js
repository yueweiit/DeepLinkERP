(function(root) {
 "use strict";
 const API="deeplinkerp_branding.services.purchase_payment_service.";
 const esc=value=>frappe.utils.escape_html(String(value ?? ""));
 const link=(type,name)=>`<a href="/desk/${frappe.router.slug(type)}/${encodeURIComponent(name)}">${esc(name)}</a>`;
 const money=(value,currency)=>`${Number(value||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})} ${esc(currency)}`;
 const call=async(method,args)=> (await frappe.call({method:API+method,args})).message;
 const balanceHTML=chain=>chain.balances.map(b=>`<span>应付 ${money(b.total,b.currency)}　已付/核销 ${money(b.settled,b.currency)}　<b>未付 ${money(b.outstanding,b.currency)}</b></span>`).join("<br>") || "尚未形成应付 / 余额不可见";
 const rowsHTML=rows=>rows.map(row=>`<tr><td>${link("Payment Entry",row.name)}</td><td>${esc(row.posting_date)}</td><td>${esc(row.state)}${row.references.every(r=>r.doctype==="Purchase Order")?" · 订单预付款":""}${row.payment_type==="Receive"?" · 退款":""}</td><td>${money(row.amount,row.currency)}</td><td>${row.references.map(ref=>`${link(ref.doctype,ref.name)} · 分配 ${money(ref.allocated,ref.currency)}<br>${ref.orders.map(n=>link("Purchase Order",n)).join(" · ")} ${ref.receipts.map(n=>link("Purchase Receipt",n)).join(" · ")}`).join("<hr>")}</td><td>${row.vouchers.map(v=>`${link("China Accounting Voucher",v.name)} ${esc(v.statutory_number||v.status)} ${esc(v.source_event==="Posting"?"记账":v.source_event==="Cancellation"?"冲销":v.source_event)}`).join("<br>")||"—"}</td></tr>`).join("");
 function recordsRoute(chain) { frappe.route_options={[chain.source_doctype==="Purchase Receipt"?"purchase_receipt":"purchase_order"]:chain.name};frappe.set_route("purchase-payment-records"); }
 let activeDrawer=null,opening=false,disposeDrawer=null;
 document.addEventListener("click",event=>{const button=event.target.closest(".dlp-receipt-pay");if(button){event.preventDefault();event.stopPropagation();pay("Purchase Receipt",button.dataset.name);}},true);
 async function pay(sourceType,sourceName) {
  if(activeDrawer||opening) return;
  opening=true;let chain;try{chain=await call("get_purchase_chain",{source_doctype:sourceType,source_name:sourceName});}finally{opening=false;}
  if(!chain.can_create){frappe.msgprint(esc(chain.reason));return;}
  const eligible=chain.invoices.filter(i=>i.can_pay);
  const opener=document.activeElement;
  const panel=$(`<div class="dlp-payment-overlay"><section class="dlp-payment-drawer" role="dialog" aria-modal="true" aria-label="采购付款"><header><h3>采购付款</h3><button class="btn btn-default dlp-close" aria-label="关闭">×</button></header><div class="dlp-payment-body"><p>${link(sourceType,sourceName)} · ${esc(chain.supplier)}</p><div class="dlp-payment-balances">${balanceHTML(chain)}</div>${chain.warnings.map(w=>`<p class="text-warning">${esc(w)}</p>`).join("")}<p class="text-muted">创建付款草稿后，按现有流程核对并提交；提交后才计已付。</p><div class="dlp-fields"></div><details><summary>高级处理 / 关联单据</summary><p>跨币种、退款、扣款及复杂付款计划请打开原生应付单创建付款。</p>${eligible.map(i=>link("Purchase Invoice",i.name)).join(" · ")}</details><div class="dlp-error text-danger" role="alert"></div></div><footer><button class="btn btn-default dlp-cancel">取消</button><button class="btn btn-primary dlp-create">创建付款草稿</button></footer></section></div>`).appendTo(document.body);
  activeDrawer=panel;let busy=false,token=root.crypto.randomUUID();const controls={};
  const close=()=>{if(busy)return;panel.remove();activeDrawer=null;document.removeEventListener("keydown",keys);disposeDrawer=null;opener?.focus();};
  const keys=e=>{if(e.key==="Escape")close();if(e.key==="Tab"){const elements=panel.find("button,input,select,textarea,summary,a[href]").filter(":visible:not(:disabled)").toArray();if(!elements.length)return;const first=elements[0],last=elements[elements.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}};
  disposeDrawer=()=>{document.removeEventListener("keydown",keys);panel.remove();activeDrawer=null;disposeDrawer=null;};
  document.addEventListener("keydown",keys);panel.find(".dlp-close,.dlp-cancel").on("click",close);
  const add=df=>{const holder=$("<div></div>").appendTo(panel.find(".dlp-fields"));const c=frappe.ui.form.make_control({parent:holder,df,render_input:true});controls[df.fieldname]=c;return c;};
  const invoice=add({fieldname:"invoice",fieldtype:"Select",label:"关联应付单",options:eligible.map(i=>i.name).join("\n"),reqd:1,change:()=>{const chosen=eligible.find(i=>i.name===controls.invoice.get_value());if(chosen)controls.amount.set_value(chosen.outstanding);}});
  add({fieldname:"amount",fieldtype:"Currency",label:"本次付款金额（应付账户币种）",reqd:1});
  const bank=add({fieldname:"bank",fieldtype:"Link",options:"Account",label:"银行 / 现金记账账户",reqd:1});bank.get_query=()=>({filters:{company:chain.company,is_group:0,account_type:["in",["Bank","Cash"]],account_currency:eligible.find(i=>i.name===invoice.get_value())?.currency}});
  add({fieldname:"reference",fieldtype:"Data",label:"银行参考号 / 付款申请编号（银行必填）",description:"银行账户原生必填；现金账户可留空。参考日期沿用付款日期。"});
  add({fieldname:"date",fieldtype:"Date",label:"付款日期",reqd:1}).set_value(frappe.datetime.get_today());
  add({fieldname:"remarks",fieldtype:"Small Text",label:"备注"});invoice.set_value(eligible[0].name);controls.amount.set_value(eligible[0].outstanding);
  panel.find(".dlp-create").on("click",async()=>{
   if(busy)return;const chosen=eligible.find(i=>i.name===invoice.get_value());const value=Number(controls.amount.get_value());
   if(!chosen||!Number.isFinite(value)||value<=0||value>chosen.outstanding||!bank.get_value()||!controls.date.get_value()){panel.find(".dlp-error").text("请填写账户、日期，以及不超过未付余额的正数金额。");return;}
   busy=true;panel.find("button").prop("disabled",true);panel.find(".dlp-error").text("");
   try {const result=await call("create_payment_draft",{source_doctype:sourceType,source_name:sourceName,purchase_invoice:chosen.name,amount_to_pay:value,bank_account:bank.get_value(),posting_date:controls.date.get_value(),remarks:controls.remarks.get_value(),request_id:token,reference_no:controls.reference.get_value()});busy=false;close();frappe.set_route("Form","Payment Entry",result.name);}
   catch(error){panel.find(".dlp-error").text("创建失败：请核对系统提示。相同内容重试使用同一请求标识；修改内容请重新打开。若响应不确定，请先检查付款记录。");}
   finally{busy=false;panel.find("button").prop("disabled",false);}
  });panel.find(".dlp-close").trigger("focus");
 }
 async function formRefresh(frm){
  frm.$wrapper.find(".dlp-purchase-chain").remove();if(frm.is_new())return;
  const current=frm.doc.name,generation=frm.dlpChainGeneration=(frm.dlpChainGeneration||0)+1;
  try {const chain=await call("get_purchase_chain",{source_doctype:frm.doctype,source_name:current});if(frm.doc.name!==current||frm.dlpChainGeneration!==generation)return;
   const box=$(`<section class="dlp-purchase-chain"><strong>采购关联与付款</strong><p>收货状态：${esc(chain.source_doctype==="Purchase Receipt"?(chain.docstatus===0?"草稿":chain.docstatus===2?"已取消":"已入库"):chain.status)}　${chain.orders.map(n=>link("Purchase Order",n)).join(" · ")}</p><div>${(chain.order_progress||[]).map(o=>`<p>${link("Purchase Order",o.name)} · 订单 ${money(o.grand_total,o.currency)} · ${o.units.map(u=>`已入 ${u.received} / 待入 ${u.pending} ${esc(u.uom)}`).join("；")} · 待入货品金额 ${money(o.pending_net_amount,o.currency)}（不含税）</p>`).join("")}</div><div>${balanceHTML(chain)}</div>${chain.warnings.map(w=>`<p class="text-warning">${esc(w)}</p>`).join("")}<p>${chain.invoices.map(i=>`${link("Purchase Invoice",i.name)} ${i.docstatus===0?"草稿":i.docstatus===2?"已取消":""}${i.is_return?"退货":""}`).join(" · ")||esc(chain.reason)}</p><div><button class="btn btn-default btn-sm dlp-records">采购付款记录</button> ${chain.can_create_invoice?'<button class="btn btn-default btn-sm dlp-invoice">确认应付</button>':""} ${chain.can_create?'<button class="btn btn-primary btn-sm dlp-pay">付款 / 继续付款</button>':""}</div>${chain.payments.length?`<details><summary>关联付款与凭证（最多100条）</summary><table class="table table-bordered"><thead><tr><th>付款单</th><th>日期</th><th>状态</th><th>整单金额</th><th>采购关联</th><th>财务凭证</th></tr></thead><tbody>${rowsHTML(chain.payments)}</tbody></table></details>`:""}</section>`);
   box.prependTo(frm.layout.wrapper);const mounted=frm.$wrapper.find(".dlp-purchase-chain");mounted.find(".dlp-invoice").on("click",()=>frappe.model.open_mapped_doc({method:"erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",frm}));mounted.find(".dlp-records").on("click",()=>recordsRoute(chain));mounted.find(".dlp-pay").on("click",()=>pay(frm.doctype,current));
  }catch(error){/* Native form remains available if financial permissions are absent. */}
 }
 function recordsPage(wrapper){
  const page=frappe.ui.make_app_page({parent:wrapper,title:"采购付款记录",single_column:true});const filters={};let start=0,sequence=0,resetting=true;const body=$("<div class='dlp-purchase-records'><p class='text-muted dlp-notice'></p><div class='dlp-records-table'></div><div class='dlp-records-paging'></div></div>").appendTo(page.main);
  for(const [field,type,options,label]of [["company","Link","Company","公司"],["supplier","Link","Supplier","供应商"],["purchase_order","Link","Purchase Order","采购订单"],["purchase_receipt","Link","Purchase Receipt","采购入库"],["search","Data",null,"付款单号 / 供应商"]]){filters[field]=page.add_field({fieldname:field,fieldtype:type,options,label,placeholder:label,change:()=>{if(!resetting){start=0;load();}}});filters[field].$input?.attr({"aria-label":label,placeholder:label});}
  resetting=false;
  async function load(){const id=++sequence;body.find(".dlp-notice").text("正在读取…");try{const args={start,page_length:50};for(const[field,control]of Object.entries(filters))if(control.get_value())args[field]=control.get_value();const result=await call("get_payment_records",args);if(id!==sequence)return;body.find(".dlp-notice").text(result.notice);body.find(".dlp-records-table").html(`<table class="table table-bordered"><thead><tr><th>付款单</th><th>日期</th><th>付款状态</th><th>整单金额</th><th>订单 / 入库 / 应付</th><th>财务凭证</th></tr></thead><tbody>${rowsHTML(result.rows)||'<tr><td colspan="6">没有匹配的采购付款记录</td></tr>'}</tbody></table>`);body.find(".dlp-records-paging").html(`<button class="btn btn-default dlp-prev" ${start===0?"disabled":""}>上一页</button> ${start+1}–${start+result.rows.length} / ${result.total_count} <button class="btn btn-default dlp-next" ${start+50>=result.total_count?"disabled":""}>下一页</button>`).find("button").on("click",e=>{start+=e.target.classList.contains("dlp-next")?50:-50;load();});}catch(error){if(id===sequence)body.find(".dlp-notice").text("无权读取或加载失败，请查看系统提示。");}}
  wrapper.dlpLoad=async()=>{const options=frappe.route_options||{};frappe.route_options=null;resetting=true;await Promise.all(Object.entries(filters).map(([field,control])=>control.set_value(options[field]||"")));resetting=false;start=0;load();};page.set_secondary_action("刷新",load);
 }
 root.DeepLinkERPPurchasePayments={pay,formRefresh,recordsPage,balanceHTML};
 frappe.router?.on("change",()=>{if(disposeDrawer)disposeDrawer();});
})(typeof globalThis!=="undefined"?globalThis:this);
