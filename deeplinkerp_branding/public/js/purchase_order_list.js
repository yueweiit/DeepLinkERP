(function (root) {
 const engine = typeof module === "object" && module.exports ? require("./compact_list.js") : root.DeepLinkERPCompactList;
 const unified = typeof module === "object" && module.exports ? require("./unified_purchase_list.js") : root.DeepLinkERPUnifiedPurchase;
	const COLUMNS = [
		["transaction_date", "订单日期", 96], ["name", "采购订单号", 166],
		["supplier_name", "供应商名称", 190], ["status", "订单状态", 120],
		["schedule_date", "需求日期", 96], ["company", "公司", 90],
		["currency", "币种", 56], ["grand_total", "订单金额", 140],
		["advance_paid", "已预付", 140], ["advance_payment_status", "预付款状态", 94],
		["order_settled", "已付 / 核销", 140], ["order_unpaid", "订单未付", 140],
		["per_received", "已收货%", 70], ["per_billed", "已开票%", 70],
		["project", "项目", 96], ["owner", "创建人", 86], ["receipt_action", "操作", 176],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));

 const defaults=['name','supplier_name','grand_total','order_settled','order_unpaid','per_received','status','receipt_action'];
 const provider = unified?.configure(COLUMNS);
 if(provider) {provider.defaultColumns=defaults;const mount=provider.mountControls;provider.mountControls=c=>{mount(c);c.setProviderScope('orders',false);};}
 const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const t = value => (root.__ || (x=>x))(value);
 const money = (value,currency) => value==null?'—':`${Number(value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})} ${esc(currency || '')}`;
 const fields = [['idx','序号'],['item_code','物料编码'],['item_name','物料名称'],['qty','数量'],['rate','单价'],['amount','金额'],['received_qty','已入库数量']];
 const rows = c => c.providerScope==='orders'?c.list.data:c.providerRows;
 function fit(c,active=true) { return engine.fitViewport(c,{active,root:c?.root,scrollElement:c?.list.$result?.parent?.('.result-container')?.[0],layoutTailElement:c?.list.$frappe_list?.[0],property:'--dlp-purchase-result-max-height',headerSelector:'.dlp-po-grid-header',rowSelector:'.dlp-po-grid-row',observeTargets:[c?.$filters?.[0]?.parentElement,c?.$toolbar?.[0],c?.$summary?.[0],c?.$paging?.[0]]}); }
 async function readProgress(c) {
  const root=c.root, docs=rows(c).filter(doc=>doc.row_type!=='oa_request'), names=docs.map(doc=>doc.name), generation=c.requestId;
  engine.invalidateExpandedDetails(c.purchaseExpanded,docs,detail=>detail.modified);
  if(!names.length)return;
  try {
   const response={message:{}};
   for(let start=0;start<names.length;start+=100){const batch=await root.frappe.call({method:'deeplinkerp_branding.services.purchase_order_progress.get_order_progress',args:{purchase_orders:names.slice(start,start+100)}});if(generation!==c.requestId || root.cur_list!==c.list)return;Object.assign(response.message,batch.message || {});}
   if(generation!==c.requestId || root.cur_list!==c.list)return;
   if(!docs.some(doc=>response.message?.[doc.name]))return;
   docs.forEach(doc=>{
    const progress=response.message?.[doc.name];doc.order_progress=progress;
    if(progress && c.purchaseExpanded?.has(doc.name))Object.assign(c.purchaseExpanded.get(doc.name),progress);
   });c.list.render_list();c.list.set_rows_as_checked?.();
  } catch (_) { if(generation===c.requestId)c.$purchaseNotice?.text(t('订单进度读取失败，请刷新或核对权限。')); }
 }
 function expanded(c,doc) {
  const detail=c.purchaseExpanded?.get(doc.name);if(!detail)return '';
  const permitted=new Set(detail.item_fields || []),columns=fields.filter(([field])=>permitted.has(field));
  const table=engine.detailTable({columns,items:detail.items,escape:esc,translate:t,wrapperClass:'dlp-sales-items-scroll',tableClass:'dlp-sales-items',format:(field,item)=>['rate','amount'].includes(field)?money(item[field],detail.currency):['qty','received_qty'].includes(field)?`${esc(item[field] ?? '—')}${permitted.has('uom')?' '+esc(item.uom):''}`:undefined});
  return `<section class="dlp-sales-expanded dlp-purchase-expanded"><strong>${esc(t('订单物料 / 订单进度'))}</strong><p>${esc(t('已付 / 核销'))} ${money(detail.settled,detail.currency)} · ${esc(t('订单未付'))} ${money(detail.order_unpaid,detail.currency)} · ${esc(t('到货进度'))} ${esc(detail.received_percent ?? '—')}%</p>${detail.settlement_notice?`<p class="text-warning">${esc(t(detail.settlement_notice))}</p>`:''}${columns.length?table:`<p>${esc(t('无权查看物料明细'))}</p>`}<p class="text-muted">${esc(t(detail.notice))}</p></section>`;
 }
 function mount(c) {
  const root=c.root;
  c.purchaseExpanded=new Map();
  c.$purchaseNotice=root.$('<p class="text-muted dlp-purchase-progress-notice"></p>').text(t('点击行首箭头展开物料与订单进度')).insertAfter(c.$filters);
  c.list.$result.on('click.dlpPurchaseExpand','.dlp-purchase-expand',async event=>{
   event.preventDefault();event.stopPropagation();const button=root.$(event.currentTarget),name=button.attr('data-name');
   if(c.purchaseExpanded.has(name)){c.purchaseExpanded.delete(name);c.list.render_list();c.list.set_rows_as_checked?.();return;}
   const generation=c.requestId;button.prop('disabled',true);
   try {const response=await root.frappe.call({method:'deeplinkerp_branding.services.purchase_order_progress.get_order_progress',args:{purchase_orders:[name],include_items:1}});if(generation!==c.requestId || root.cur_list!==c.list)return;c.purchaseExpanded.set(name,response.message[name]);c.list.render_list();c.list.set_rows_as_checked?.();}
   catch (_) {c.$purchaseNotice.text(t('订单进度读取失败，请刷新或核对权限。'));}finally{button.prop('disabled',false);}
  });
 }
 if (provider) { provider.virtualFields.push('receipt_action','order_settled','order_unpaid'); const onPayload=provider.onPayload;provider.onPayload=c=>{onPayload?.(c);readProgress(c);}; }
 const grid = engine.create({ doctype: "Purchase Order", dismissInitialOnboarding:true, columns: COLUMNS, defaultColumns:defaults, provider, computedFields:['receipt_action','order_settled','order_unpaid'], renderValue:(field,doc)=>field==='receipt_action' ? root.DeepLinkERPPurchasePayments?.orderReceiptAction(doc) || '—' : ['order_settled','order_unpaid'].includes(field)?money(doc.order_progress?.[field==='order_settled'?'settled':'order_unpaid'],doc.currency):undefined, onRows:readProgress, mountControls:mount, afterRender:c=>fit(c),onRouteChange:fit, renderSequence:(c,doc,sequence)=>doc.row_type==='oa_request'?sequence:`<button type="button" class="dlp-sales-expand dlp-purchase-expand" data-name="${esc(doc.name)}" aria-expanded="${c.purchaseExpanded?.has(doc.name) || false}" aria-label="${esc(t('展开物料与订单进度'))}">${c.purchaseExpanded?.has(doc.name)?'⌄':'›'}</button>`, rowExtra:expanded, controllerKey: "dlpPurchaseOrderGrid", routeClass: "dlp-purchase-order-grid-active", freezeUntil: "supplier_name", moneySummary: true, numbers: ["grand_total", "advance_paid", "per_received", "per_billed"], dates: ["transaction_date", "schedule_date"], quickFields: ["company", "status", "advance_payment_status"], searchFields: ["name", "supplier_name"], extraFields: ["supplier", "party_account_currency", "docstatus"], controls: [
 {fieldname:"search",fieldtype:"Data",label:"采购订单号 / 供应商名称"},
 {fieldname:"from_date",fieldtype:"Date",label:"订单开始日期",permission_field:"transaction_date"},
 {fieldname:"to_date",fieldtype:"Date",label:"订单结束日期",permission_field:"transaction_date"},
 {fieldname:"company",fieldtype:"Link",options:"Company",label:"公司"},
 {fieldname:"status",fieldtype:"Select",label:"订单状态"},
 {fieldname:"advance_payment_status",fieldtype:"Select",label:"预付款状态"}
 ]});
 if (typeof module === "object" && module.exports) module.exports = grid;
 root.DeepLinkERPPurchaseOrderGrid = grid;
 grid.install(root);
})(typeof globalThis !== "undefined" ? globalThis : this);
