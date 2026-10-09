(function (root) {
 const engine = typeof module === "object" && module.exports ? require("./compact_list.js") : root.DeepLinkERPCompactList;
 const unified = typeof module === "object" && module.exports ? require("./unified_purchase_list.js") : root.DeepLinkERPUnifiedPurchase;
 const COLUMNS = [
  ["transaction_date", "订单日期", 96], ["name", "采购订单号", 166], ["supplier_name", "供应商名称", 150], ["status", "订单状态", 104],
  ["schedule_date", "需求日期", 96], ["company", "公司", 90], ["currency", "币种", 56], ["grand_total", "订单金额", 140],
  ["advance_paid", "已预付", 140], ["advance_payment_status", "预付款状态", 94], ["order_settled", "已付 / 核销", 140], ["order_unpaid", "订单未付", 140],
  ["per_received", "已收货%", 70], ["per_billed", "已开票%", 70], ["project", "项目", 96], ["owner", "创建人", 86], ["receipt_action", "操作", 176],
 ].map(([fieldname, label, width]) => ({ fieldname, label, width }));
 const provider = unified.configure(COLUMNS);
 const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const t = value => (root.__ || (x=>x))(value);
 const numeric = value => value==null || value==='' || typeof value==='boolean' || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
 const itemFields = new Set(['warehouse','item_code','item_name','qty','uom','rate','amount','received_qty']);
 const payments = c => c?.root?.DeepLinkERPPurchasePayments || root.DeepLinkERPPurchasePayments;
 const isOA = c => c.providerScope==='oa';
 function cancelPending(c) { payments(c)?.cancelCrossborderForList?.(c); }
 function fit(c,active) {
  if(!c)return;
  if(active!==undefined)c._setPurchaseSelectionActive?.(active);
  active ??= true;
  if(!active)cancelPending(c);
  return engine.fitViewport(c,{active,root:c.root,scrollElement:c.list.$result?.parent?.('.result-container')?.[0],layoutTailElement:c.list.$frappe_list?.[0],property:'--dlp-purchase-result-max-height',headerSelector:'.dlp-po-grid-header',rowSelector:'.dlp-po-grid-row',observeTargets:[c.$filters?.[0]?.parentElement,c.$toolbar?.[0],c.$summary?.[0],c.$paging?.[0]]});
 }
 function columns(c) {
  const selected=c.preferences.columns.map(field=>provider.columns.find(col=>col.fieldname===field)).filter(Boolean);
  const visible=isOA(c)?selected.filter(col=>!itemFields.has(col.fieldname)):selected;
  const frozenThrough=visible.findIndex(col=>col.fieldname==='supplier_name');let left=76;
  return visible.map((col,index)=>{const value={...col,left,frozen:index<=frozenThrough};left+=col.width;return value;});
 }
 function cell(tag,field,value,span=1,width=null,extra='') {
  const col=typeof width==='object'?width:{width,frozen:['_select','_sequence'].includes(field),left:field==='_sequence'?36:0};
  const classes=[col.frozen?'dlp-purchase-frozen':'',field==='name'?'list-subject':'',field==='_select'?'select-like':''].filter(Boolean).join(' ');
  return `<${tag} data-fieldname="${field}"${span>1?` rowspan="${span}"`:''}${classes?` class="${classes}"`:''}${col.width?` style="width:${col.width}px;min-width:${col.width}px;max-width:${col.width}px;--dlp-purchase-left:${col.left}px"`:''}${extra}>${value}</${tag}>`;
 }
 function header(c) {
  const check=isOA(c)?'':`<input class="list-header-checkbox list-check-all" type="checkbox" title="${esc(c.translate('选择当前页全部订单'))}">`;
  return `<thead><tr class="list-header-subject dlp-po-grid-header">${cell('th','_select',check,1,36)}${cell('th','_sequence','#',1,40)}${columns(c).map(col=>cell('th',col.fieldname,esc(c.translate(col.label)),1,col,provider.sortFields.includes(col.fieldname)?` data-provider-sort="${col.fieldname}"`:'' )).join('')}</tr></thead>`;
 }
 function orderValue(c,doc,field) {
  if(field==='name') {
   if(doc.row_type==='oa_request')return `<button type="button" class="btn btn-link btn-xs" data-purchase-source="${esc(doc.oa_name || doc.name)}">${esc(`待完善 · ${doc.oa_number || doc.name}`)}</button>`;
   const refs=(doc.oa_references || []).map(ref=>`<a class="dlp-po-provenance" href="/desk/oa-purchase-request/${encodeURIComponent(ref.name)}">${esc(`钉钉 · ${ref.number || ref.name}`)}</a>`).join('');
   return `<a href="${esc(unified.formLink(doc))}" data-name="${esc(doc.name)}">${esc(doc.name)}</a>${refs || (doc.source==='OA'?'<span class="dlp-po-provenance">钉钉</span>':'')}`;
  }
  if(field==='supplier_name')return doc.supplier?`<a href="/desk/supplier/${encodeURIComponent(doc.supplier)}">${esc(doc.supplier_name || '—')}</a>`:esc(doc.supplier_name || '供应商待核对');
  if(field==='status')return doc.row_type==='purchase_order'?(c.list.get_indicator_html?.(doc,Boolean(c.list.workflow_state_fieldname)) || esc(c.translate(doc.status || '—'))):esc(doc.status || '来源待完善');
  if(field==='receipt_action') {
   if(doc.row_type==='oa_request')return provider.renderValue(field,doc,{},esc);
   const related=doc.order_progress?.state==='restricted'?'<span class="text-warning">关联进度受限，请核对权限</span>':['internal','logistics'].map((tab,i)=>`<button type="button" class="btn btn-xs btn-default dlp-crossborder-open" data-crossborder-order="${esc(doc.name)}" data-crossborder-tab="${tab}">${t(i?'物流证据':'内部关联')}</button>`).join('');
   return `<span class="dlp-po-row-actions">${payments(c)?.orderReceiptAction(doc) || ''}${related}</span>`;
  }
  return provider.renderValue(field,doc,{},esc) ?? grid.renderValue(field,doc,{allowed:c.allowed,translate:c.translate,number:(value,field)=>grid.formatNumber(c.root,value,field),date:value=>c.root.frappe.datetime?.str_to_user?.(value) || value});
 }
 function row(c,doc) {
  const detail=doc.order_progress || {}, permitted=new Set(detail.item_fields || []);
  const items=doc.row_type==='purchase_order' && detail.state!=='restricted' && permitted.has('name') ? (detail.items || []).filter(item=>item.name) : [];
  const physical=items.length?items:[null],span=physical.length,cols=columns(c);
  const selectable=doc.row_type==='purchase_order' && !isOA(c);
  const check=selectable?`<input type="checkbox" class="list-row-checkbox" data-doctype="Purchase Order" data-name="${esc(doc.name)}">`:'';
  return `<tbody class="list-row-container dlp-purchase-order-body" data-order-name="${esc(doc.name)}" tabindex="0">${physical.map((item,index)=>`<tr class="${index===0 && selectable?'level list-row ':''}dlp-po-grid-row" data-order-name="${esc(doc.name)}"${item?` data-item-name="${esc(item.name)}"`:''}>${index===0?cell('td','_select',check,span,36)+cell('td','_sequence',c.page*c.pageSize+(doc._idx || 0)+1,span,40):''}${cols.map(col=> {
   if(!itemFields.has(col.fieldname))return index===0?cell('td',col.fieldname,orderValue(c,doc,col.fieldname),span,col):'';
   const value=item && permitted.has(col.fieldname)?item[col.fieldname]:null;
   const shown=['qty','received_qty'].includes(col.fieldname)?numeric(value):['rate','amount'].includes(col.fieldname)?grid.renderValue('grand_total',{grand_total:value,currency:detail.currency || doc.currency}):esc(value ?? '—');
   return cell('td',col.fieldname,shown,1,col);
  }).join('')}</tr>`).join('')}</tbody>`;
 }
 function table(c,rows) { return `<div class="list-row-container dlp-purchase-table-wrap"><table class="dlp-purchase-table">${header(c)}${rows.map(doc=>row(c,doc)).join('')}</table><div class="checkbox-actions" style="display:none"></div></div>`; }
 function selectionChanged(c) {
  if(!c.getSelectedPurchaseOrders)return;
  const selected=c.getSelectedPurchaseOrders(),names=new Set(selected.map(row=>row.name));
  const allowed=c.providerRows.filter(row=>names.has(row.name)).map(doc=>payments(c)?.orderReceiptAction(doc) || '');
  c.$purchaseActions?.find('.dlp-purchase-selected-count').text(c.translate(`已选 ${selected.length} 张订单`));
  for(const [action,marker] of [['receipt','dlp-order-receipt'],['payment','dlp-order-pay']])c.$purchaseActions?.find(`[data-purchase-action="${action}"]`).prop('disabled',!selected.length || !allowed.every(value=>value.includes(marker)));
  c.$purchaseActions?.find('.dlp-purchase-action-notice').text(selected.length>1?c.translate('入库可逐单或合并；合并付款按实际应付核销。'):'');
 }
 function clearSelection(c) {
  c.list.clear_checked_items?.();
  c.list.$checkbox_cursor=null;
  selectionChanged(c);
 }
 function scopeChanged(c) {
  c.$purchaseTabs?.find('[data-purchase-scope]').removeClass('active').attr('aria-selected','false');
  c.$purchaseTabs?.find(`[data-purchase-scope="${c.providerScope}"]`).addClass('active').attr('aria-selected','true');
  c.$purchaseActions?.toggle(!isOA(c));
 }
 function mount(c) {
  const result=c.list.$result?.[0];let listening=false;
  // Set page rows before native forwarding/on_row_checked rewrites the sole header.
  const selectPage=event=>{
   if(isOA(c) || !event.target?.matches?.('.dlp-purchase-table .list-header-subject .list-check-all'))return;
   c.list.$result.find('.list-row-checkbox').prop('checked',event.target.checked);
  };
  c._setPurchaseSelectionActive=active=>{
   if(!result?.addEventListener || listening===active)return;
   result[active?'addEventListener':'removeEventListener']('change',selectPage,true);listening=active;
  };
  c._setPurchaseSelectionActive(true);
  // Stable whole-order selection projection for the later batch-operation task.
  c.getSelectedPurchaseOrders=()=> {
   if(isOA(c))return [];
   const names=new Set((c.list.get_checked_items?.(true) || []).map(doc=>typeof doc==='string'?doc:doc.name));
   return c.providerRows.filter(doc=>doc.row_type==='purchase_order' && names.has(doc.name)).map(doc=>({name:doc.name,modified:doc.modified}));
  };
  c.runPurchaseAction=async action=> {
   const selected=c.getSelectedPurchaseOrders();
   if(!selected.length)return;
   if(selected.length>1){
    if(action==='receipt')return payments(c).batchDocumentDrawer('Purchase Order',selected,'Purchase Receipt');
    if(action==='payment')return payments(c).batchPay('Purchase Order',selected);
    return;
   }
   const doc=c.providerRows.find(row=>row.name===selected[0].name),native=payments(c)?.orderReceiptAction(doc) || '';
   if(action==='receipt' && native.includes('dlp-order-receipt'))return payments(c).documentDrawer('Purchase Order',doc.name,'Purchase Receipt');
   if(action==='payment' && native.includes('dlp-order-pay'))return payments(c).pay('Purchase Order',doc.name);
  };
  // Crossborder drawer saves call this public hook before the shared page refresh.
  c.invalidatePurchaseDetails=names=> {
   c.requestId++;c.list.last_args=null;
   const targets=names==null?null:new Set(Array.isArray(names)?names:[names]);
   for(const doc of c.providerRows)if(doc.row_type==='purchase_order' && (!targets || targets.has(doc.name)) && doc.order_progress){delete doc.order_progress.items;delete doc.order_progress.item_fields;}
   c.list.render_list();c.list.set_rows_as_checked?.();
  };
  c.$purchaseTabs=c.root.$('<nav class="dlp-procurement-tabs dlp-purchase-scope-tabs" role="tablist" aria-label="采购单据"><button type="button" role="tab" data-purchase-scope="orders">采购订单</button><button type="button" role="tab" data-purchase-scope="oa">钉钉待完善</button></nav>').insertAfter(c.$filters);
  c.$purchaseTabs.on('click.dlpPurchaseScope','[data-purchase-scope]',event=>c.setProviderScope(event.currentTarget.dataset.purchaseScope));
  c.$purchaseActions=c.root.$('<div class="dlp-purchase-selection-actions"><span class="dlp-purchase-selected-count" aria-live="polite"></span><button type="button" class="btn btn-primary btn-sm" data-purchase-action="receipt" disabled>入库</button><button type="button" class="btn btn-default btn-sm" data-purchase-action="payment" disabled>付款</button><span class="text-muted dlp-purchase-action-notice" aria-live="polite"></span></div>').insertAfter(c.$toolbar);
  c.$purchaseActions.on('click.dlpPurchaseAction','[data-purchase-action]',event=>c.runPurchaseAction(event.currentTarget.dataset.purchaseAction));
  scopeChanged(c);selectionChanged(c);
 }
 const onPayload=provider.onPayload;
 provider.onPayload=c=>{onPayload?.(c);selectionChanged(c);};
 const grid = engine.create({doctype:'Purchase Order',dismissInitialOnboarding:true,keepColumnHeader:true,columns:COLUMNS,defaultColumns:provider.defaultColumns,provider,providerSelectable:doc=>doc.row_type==='purchase_order',computedFields:['receipt_action','order_settled','order_unpaid'],moneyPrecision:2,
  onRequestStart:cancelPending,onPageChange:clearSelection,onScopeChange:scopeChanged,onSelectionChange:selectionChanged,mountControls:mount,renderHeader:c=>`<table class="dlp-purchase-table">${header(c)}</table>`,renderRow:row,renderTable:table,
  afterRender:c=>{selectionChanged(c);fit(c);},onRouteChange:fit,controllerKey:'dlpPurchaseOrderGrid',routeClass:'dlp-purchase-order-grid-active',freezeUntil:'supplier_name',moneySummary:true,
  numbers:['grand_total','advance_paid','per_received','per_billed'],dates:['transaction_date','schedule_date'],quickFields:['company','status','advance_payment_status'],searchFields:['name','supplier_name','project'],extraFields:['supplier','party_account_currency','docstatus'],optionLabels:{progress_phase:{supplier_unpaid:'供应商未付',internal_unsettled:'内部待结算',factory_pending:'工厂待入库'}},controls:[
   {fieldname:'search',fieldtype:'Data',label:'订单/审批/项目/供应商'},
   {fieldname:'from_date',fieldtype:'Date',label:'订单开始日期',permission_field:'transaction_date'},
   {fieldname:'to_date',fieldtype:'Date',label:'订单结束日期',permission_field:'transaction_date'},
   {fieldname:'company',fieldtype:'Link',options:'Company',label:'采购付款公司'},
   {fieldname:'beneficiary_company',fieldtype:'Link',options:'Company',label:'最终归属公司',permission_field:'company'},
   {fieldname:'progress_phase',fieldtype:'Select',label:'进度阶段',permission_field:'name',options:'\nsupplier_unpaid\ninternal_unsettled\nfactory_pending',emptyLabel:'全部进度'},
   {fieldname:'review_only',fieldtype:'Check',label:'待核对',permission_field:'name'},
  ]});
 if(typeof module==='object' && module.exports)module.exports=grid;
 root.DeepLinkERPPurchaseOrderGrid=grid;
 grid.install(root);
})(typeof globalThis!=='undefined'?globalThis:this);
