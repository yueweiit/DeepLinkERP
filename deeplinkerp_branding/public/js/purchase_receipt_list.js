(function(root) {
 'use strict';
 const native = [['posting_date','入库日期',94],['name','采购入库单号',158],['supplier_name','供应商名称',160],['company','公司',130],['currency','币种',60],['grand_total','入库金额',120],['status','入库状态',88]].map(([fieldname,label,width])=>({fieldname,label,width}));
 const columns = [...native, ...[['orders','采购订单',158],['payment_state','付款状态',130],['settled','已付 / 核销',128],['outstanding','未付',128],['payment_action','操作',230]].map(([fieldname,label,width])=>({fieldname,label,width}))];
 const service = 'deeplinkerp_branding.services.purchase_payment_service.get_receipt_list';
 function request(c) {
  const args = c.originals.get_args.call(c.list);
  for (const filter of [...(args.filters || []), ...(args.or_filters || [])]) {
   if (Array.isArray(filter) && filter.length >= 4 && filter[0] !== 'Purchase Receipt') throw new Error('此高级关联筛选请切换“原生筛选 / 批量操作”；当前条件不会被丢弃。');
  }
  return {method:service,args:{filters:JSON.stringify(c.quick),native_filters:JSON.stringify(args.filters || []),or_filters:JSON.stringify(args.or_filters || []),order_by:c.list.sort_selector?.get_sql_string() || c.providerOrderBy || args.order_by,start:c.page*c.pageSize,page_length:c.pageSize}};
 }
 function sortBy(c,field) {
  const selector=c.list.sort_selector;
  const [oldField,oldOrder]=(c.providerOrderBy || '').split(' ');
  const order=(selector?.sort_by || oldField)===field && (selector?.sort_order || oldOrder)==='asc'?'desc':'asc';
  c.setPage(0);
  if(selector){selector.set_value(field,order);c.list.on_sort_change(field,order);}
  else{c.providerOrderBy=`${field} ${order}`;c.refresh();}
 }
 function showPredicates(c){for(const field of ['supplier','status'])c.controls[field]?.$wrapper?.show();}
 async function exportCurrent(c) {
  const { root } = c;
  const args = {...request(c).args,export_format:'xlsx',columns:JSON.stringify(c.preferences.columns.filter(field=>field!=='payment_action'))};
  delete args.start; delete args.page_length;
  if (!root.DeepLinkERPPurchaseOrderExport?.downloadWorkbook) await root.frappe.require('/assets/deeplinkerp_branding/js/purchase_order_export.js');
  const exporter = root.DeepLinkERPPurchaseOrderExport;
  if (!exporter) throw new Error('导出组件加载失败，请刷新重试。');
  exporter.downloadWorkbook(root,await exporter.fetchNativeWorkbook(root,args,service),'采购入库明细');
 }
 const provider = {columns,defaultColumns:columns.map(c=>c.fieldname),virtualFields:['orders','payment_state','settled','outstanding','payment_action'],freezeUntil:'supplier_name',sortFields:native.map(c=>c.fieldname),sortBy,formLink:doc=>`/desk/purchase-receipt/${encodeURIComponent(doc.name)}`,request,exportCurrent,
  onQueryError:(c,error)=>{if(!String(error.message).includes('高级关联筛选'))return false;c.setProviderScope('orders',false);c.root.frappe.show_alert?.({message:error.message,indicator:'orange'});return true;},
  summary:(c,escape)=>escape(`入库金额：${(c.providerPayload?.totals || []).map(row=>`${Number(row.grand_total).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})} ${row.currency}`).join(' · ') || '—'} ｜ 余额按关联应付币种；共享整单余额不作入库合计`),
  renderValue:(field,doc,format,escape)=>{
   if(field==='grand_total') return doc.grand_total===null || doc.grand_total===undefined?'—':`${escape(Number(doc.grand_total).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}))} ${escape(doc.currency || '')}`.trim();
   if(field==='status') return escape(doc.docstatus===0?'草稿':doc.docstatus===2?'已取消':doc.is_return?'退货入库':'已入库');
   if(field==='orders') return(doc.orders || []).map(name=>`<a href="/desk/purchase-order/${encodeURIComponent(name)}">${escape(name)}</a>`).join(' · ') || '—';
   if(field==='payment_state') return `<span title="${escape((doc.warnings || []).join('；'))}">${escape(doc.settlement_state || doc.payment_state || '—')}${doc.shared_payable?' · 共享整单':''}</span>`;
   if(['settled','outstanding'].includes(field)) return(doc.balances || []).map(b=>`<span title="${doc.shared_payable?'共享应付整单余额':'关联应付余额'}">${escape(Number(b[field]).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}))} ${escape(b.currency)}</span>`).join(' · ') || '—';
   if(field==='payment_action') {
    const button=(cls,label,target='')=>`<button type="button" class="btn btn-xs btn-default ${cls}" data-name="${escape(doc.name)}"${target?` data-target="${escape(target)}"`:''}>${label}</button>`;
    return [(doc.draft_invoices || []).map(invoice=>button('dlp-receipt-invoice','继续应付草稿',typeof invoice==='string'?invoice:invoice.name)).join(' '), doc.can_create_invoice?button('dlp-receipt-invoice','确认应付'):'',doc.can_create?button('dlp-receipt-pay','付款 / 继续付款'):''].filter(Boolean).join(' ') || `<span title="${escape(doc.reason || '')}">—</span>`;
   }
  },
  mountControls:c=>{
   const $=c.root.$;
   const select=$('<select class="form-control input-xs" aria-label="入库视图"><option value="all">关联付款视图</option><option value="orders">原生筛选 / 批量操作</option></select>').appendTo($('<label>视图 </label>').appendTo(c.$toolbar));
   c.$providerScope=select;
   select.on('change.dlpReceipt',()=>c.setProviderScope(select.val()));
   $('<a class="btn btn-default btn-sm" href="/desk/purchase-payment-records">采购付款记录</a>').appendTo(c.$toolbar);
   c.list.$result.on('click.dlpReceipt','[data-provider-sort]',e=>sortBy(c,e.currentTarget.dataset.providerSort));
   c.setProviderScope('all',false);
  },
  onActivate:showPredicates,
  onPayload:c=>{ showPredicates(c); c.$providerNotice?.remove(); c.$providerNotice=c.root.$('<p class="text-muted dlp-po-provider-notice"></p>').text('入库 → 确认应付 → 部分 / 全额付款。提交付款才计已付；高级关联筛选和批量操作可切换原生视图。').insertAfter(c.$filters); }
 };
 const grid=root.DeepLinkERPCompactList.create({doctype:'Purchase Receipt',moneyPrecision:2,dismissInitialOnboarding:true,columns:native,provider,controllerKey:'dlpReceiptGrid',routeClass:'dlp-purchase-receipt-grid-active',freezeUntil:'supplier_name',dateField:'posting_date',numbers:['grand_total'],dates:['posting_date'],quickFields:['company','supplier','status'],searchFields:['name','supplier_name'],extraFields:['supplier'],controls:[{fieldname:'search',fieldtype:'Data',label:'入库单号 / 供应商名称'},{fieldname:'company',fieldtype:'Link',options:'Company',label:'公司'},{fieldname:'supplier',fieldtype:'Link',options:'Supplier',label:'供应商'},{fieldname:'status',fieldtype:'Select',label:'入库状态'},{fieldname:'from_date',fieldtype:'Date',label:'入库开始日期',permission_field:'posting_date'},{fieldname:'to_date',fieldtype:'Date',label:'入库结束日期',permission_field:'posting_date'}]});
 root.DeepLinkERPReceiptGrid=grid; grid.install(root);
})(globalThis);
