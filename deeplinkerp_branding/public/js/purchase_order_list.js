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

 const provider = unified?.configure(COLUMNS);
 const defaults=provider?.defaultColumns || ['name','supplier_name','grand_total','order_settled','order_unpaid','per_received','status','receipt_action'];
 const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const t = value => (root.__ || (x=>x))(value);
 const number = (value,quantity=false) => value==null || value==='' || !Number.isFinite(Number(value))?'—':Number(value).toLocaleString(undefined,{minimumFractionDigits:quantity?0:2,maximumFractionDigits:2});
 const money = (value,currency) => value==null?'—':`${number(value)} ${esc(currency || '币种待核对')}`;
 const fields = [['idx','序号'],['item_code','物料编码'],['item_name','物料名称'],['qty','数量'],['rate','单价'],['amount','金额'],['received_qty','已入库数量']];
 const rows = c => c.providerRows;
 const sourceVersion = doc => JSON.stringify([doc.modified || doc.order_progress?.modified || null,doc.source_version || null]);
 function cancelPending(c) {
  c?.root?.DeepLinkERPPurchasePayments?.cancelCrossborderForList?.(c);
  for(const name of c?.purchaseExpansionRequests?.keys() || [])if(c.purchaseExpanded?.get(name)?._loading)c.purchaseExpanded.delete(name);
  c?.purchaseExpansionRequests?.clear();
 }
 function fit(c,active=true) { if(!active)cancelPending(c);return engine.fitViewport(c,{active,root:c?.root,scrollElement:c?.list.$result?.parent?.('.result-container')?.[0],layoutTailElement:c?.list.$frappe_list?.[0],property:'--dlp-purchase-result-max-height',headerSelector:'.dlp-po-grid-header',rowSelector:'.dlp-po-grid-row',observeTargets:[c?.$filters?.[0]?.parentElement,c?.$toolbar?.[0],c?.$summary?.[0],c?.$paging?.[0]]}); }
 function useDetailProgress(doc,detail) {
  const {items,item_fields,_sourceVersion,_readRequestId,_loading,...progress}=detail;
  doc.order_progress={...doc.order_progress,...progress};
 }
 function syncProgress(c) {
  const byName=new Map(rows(c).filter(doc=>doc.row_type==='purchase_order').map(doc=>[doc.name,doc]));
  for(const details of [c.purchaseExpanded,c.purchaseDetailsCache])for(const [name,detail] of details || []) {
   const doc=byName.get(name);
   if(!doc || (detail._sourceVersion ? detail._sourceVersion!==sourceVersion(doc) : doc.modified && doc.modified!==detail.modified) || doc.order_progress?.state==='restricted'){details.delete(name);c.purchaseExpansionRequests?.delete(name);continue;}
   // A page dispatched before this clicked read may arrive afterwards with the same PO.modified.
   if(detail._readRequestId!=null && c.requestId<=detail._readRequestId)useDetailProgress(doc,detail);
   else if(doc.order_progress)Object.assign(detail,doc.order_progress,{_readRequestId:c.requestId});
  }
 }
 function actions(doc) {
  const related=doc.order_progress?.state==='restricted'?'<span class="text-warning">关联进度受限，请核对权限</span>':['internal','logistics'].map((tab,i)=>`<button type="button" class="btn btn-xs btn-default dlp-crossborder-open" data-crossborder-order="${esc(doc.name)}" data-crossborder-tab="${tab}">${t(i?'物流证据':'内部关联')}</button>`).join('');
  return `<span class="dlp-po-group dlp-po-row-actions">${root.DeepLinkERPPurchasePayments?.orderReceiptAction(doc) || ''}${related}</span>`;
 }
 function expanded(c,doc) {
  const detail=c.purchaseExpanded?.get(doc.name);if(!detail)return '';
  if(detail._loading)return `<section class="dlp-sales-expanded dlp-purchase-expanded" role="status">${esc(t('正在读取物料…'))}</section>`;
  const permitted=new Set(detail.item_fields || []),columns=fields.filter(([field])=>permitted.has(field));
  const table=engine.detailTable({columns,items:detail.items,escape:esc,translate:t,wrapperClass:'dlp-sales-items-scroll',tableClass:'dlp-sales-items',format:(field,item)=>['rate','amount'].includes(field)?money(item[field],detail.currency):['qty','received_qty'].includes(field)?`${number(item[field],true)}${permitted.has('uom')?' '+esc(item.uom || ''):''}`:undefined});
  return `<section class="dlp-sales-expanded dlp-purchase-expanded"><strong>${esc(t('订单物料 / 订单进度'))}</strong><p>${esc(t('ERP 已付 / 核销'))} ${money(detail.settled,detail.currency)} · ${esc(t('订单未付'))} ${money(detail.order_unpaid,detail.currency)} · ${esc(t('到货进度'))} ${number(detail.received_percent,true)}%</p>${detail.settlement_notice?`<p class="text-warning">${esc(t(detail.settlement_notice))}</p>`:''}${columns.length?table:`<p>${esc(t('无权查看物料明细'))}</p>`}<p class="text-muted">${esc(t(detail.notice || ''))}</p></section>`;
 }
 function mount(c) {
  const root=c.root;
  c.purchaseExpanded=new Map();
  c.purchaseDetailsCache=new Map();c.purchaseExpansionRequests=new Map();
  // Link/node writes need explicit invalidation: they need not change Purchase Order.modified.
  c.invalidatePurchaseDetails=names=>{
   const targets=names==null?new Set([...c.purchaseExpanded.keys(),...c.purchaseDetailsCache.keys(),...c.purchaseExpansionRequests.keys()]):new Set(Array.isArray(names)?names:[names]);
   for(const name of targets){c.purchaseExpanded.delete(name);c.purchaseDetailsCache.delete(name);c.purchaseExpansionRequests.delete(name);}
   c.list.render_list();c.list.set_rows_as_checked?.();
  };
  c.$purchaseNotice=root.$('<p class="text-muted dlp-purchase-progress-notice"></p>').text(t('点击行首箭头展开物料与订单进度')).insertAfter(c.$filters);
  c.list.$result.on('click.dlpPurchaseExpand','.dlp-purchase-expand',async event=>{
   event.preventDefault();event.stopPropagation();const button=root.$(event.currentTarget),name=button.attr('data-name');
   const render=()=>{c.list.render_list();c.list.set_rows_as_checked?.();};
   if(c.purchaseExpanded.has(name)){c.purchaseExpanded.delete(name);c.purchaseExpansionRequests.delete(name);render();return;}
   const doc=rows(c).find(row=>row.name===name && row.row_type==='purchase_order');if(!doc || doc.order_progress?.state==='restricted')return;
   const version=sourceVersion(doc),cached=c.purchaseDetailsCache.get(name);
   if(cached?._sourceVersion===version){c.purchaseExpanded.set(name,{...cached});render();return;}
   const generation=c.requestId,query=JSON.stringify(c.list.get_args()),token={};
   const current=()=>c.purchaseExpansionRequests.get(name)===token && generation===c.requestId && root.cur_list===c.list && (root.frappe.get_route?.() || [])[0]==='List' && JSON.stringify(c.list.get_args())===query && rows(c).some(row=>row.name===name && row.row_type==='purchase_order' && sourceVersion(row)===version && row.order_progress?.state!=='restricted');
   c.purchaseExpansionRequests.set(name,token);c.purchaseExpanded.set(name,{_loading:true,_sourceVersion:version});render();
   try {
    const response=await root.frappe.call({method:'deeplinkerp_branding.services.purchase_order_progress.get_order_progress',args:{purchase_orders:[name],include_items:1}});
    if(!current())return;
    const detail=response.message?.[name];if(!detail || (doc.order_progress?.modified && detail.modified!==doc.order_progress.modified))return;
    const value={...detail,_sourceVersion:version,_readRequestId:generation};c.purchaseDetailsCache.set(name,value);c.purchaseExpanded.set(name,value);useDetailProgress(rows(c).find(row=>row.name===name && row.row_type==='purchase_order'),value);render();
   } catch (_) {if(current())c.$purchaseNotice.text(t('订单进度读取失败，请刷新或核对权限。'));}
   finally {if(c.purchaseExpansionRequests.get(name)===token){c.purchaseExpansionRequests.delete(name);if(c.purchaseExpanded.get(name)?._loading){c.purchaseExpanded.delete(name);render();}}button.prop('disabled',false);}
  });
 }
 if (provider) {const onPayload=provider.onPayload,renderValue=provider.renderValue;provider.onPayload=c=>{onPayload?.(c);syncProgress(c);};provider.renderValue=(field,doc,...args)=>field==='receipt_action' && doc.row_type==='purchase_order'?actions(doc):renderValue(field,doc,...args);}
 const grid = engine.create({ doctype: "Purchase Order", dismissInitialOnboarding:true, keepColumnHeader:true, columns: COLUMNS, defaultColumns:defaults, provider, providerSelectable:doc=>doc.row_type==='purchase_order', computedFields:['receipt_action','order_settled','order_unpaid'], moneyPrecision:2, renderValue:(field,doc)=>field==='receipt_action' ? root.DeepLinkERPPurchasePayments?.orderReceiptAction(doc) || '—' : ['order_settled','order_unpaid'].includes(field)?money(doc.order_progress?.[field==='order_settled'?'settled':'order_unpaid'],doc.currency):undefined, onRequestStart:cancelPending, mountControls:mount, afterRender:c=>fit(c),onRouteChange:fit, renderSequence:(c,doc,sequence)=>doc.row_type==='oa_request'?sequence:`<button type="button" class="dlp-sales-expand dlp-purchase-expand" data-name="${esc(doc.name)}" aria-expanded="${c.purchaseExpanded?.has(doc.name) || false}" aria-label="${esc(t('展开物料与订单进度'))}">${c.purchaseExpanded?.has(doc.name)?'⌄':'›'}</button><span class="dlp-purchase-sequence">${sequence}</span>`, rowExtra:expanded, controllerKey: "dlpPurchaseOrderGrid", routeClass: "dlp-purchase-order-grid-active", freezeUntil: "supplier_name", moneySummary: true, numbers: ["grand_total", "advance_paid", "per_received", "per_billed"], dates: ["transaction_date", "schedule_date"], quickFields: ["company", "status", "advance_payment_status"], searchFields: ["name", "supplier_name", "project"], extraFields: ["supplier", "party_account_currency", "docstatus"], optionLabels:{progress_phase:{supplier_unpaid:'供应商未付',internal_unsettled:'内部待结算',factory_pending:'工厂待入库'}}, controls: [
 {fieldname:"search",fieldtype:"Data",label:"订单/审批/项目/供应商"},
 {fieldname:"from_date",fieldtype:"Date",label:"订单开始日期",permission_field:"transaction_date"},
 {fieldname:"to_date",fieldtype:"Date",label:"订单结束日期",permission_field:"transaction_date"},
 {fieldname:"company",fieldtype:"Link",options:"Company",label:"采购付款公司"},
 {fieldname:"beneficiary_company",fieldtype:"Link",options:"Company",label:"最终归属公司",permission_field:"company"},
 {fieldname:"progress_phase",fieldtype:"Select",label:"进度阶段",permission_field:"name",options:'\nsupplier_unpaid\ninternal_unsettled\nfactory_pending',emptyLabel:'全部进度'},
 {fieldname:"review_only",fieldtype:"Check",label:"待核对",permission_field:"name"}
 ]});
 if (typeof module === "object" && module.exports) module.exports = grid;
 root.DeepLinkERPPurchaseOrderGrid = grid;
 grid.install(root);
})(typeof globalThis !== "undefined" ? globalThis : this);
