(function(root) {
 'use strict';
 if(root.__dlpProcurementActionsInstalled && root.DeepLinkERPPurchasePayments)return;
 const frappe=root.frappe, $=root.$;
 const API='deeplinkerp_branding.services.purchase_payment_service.';
 const ACTIONS='deeplinkerp_branding.services.purchase_document_actions.';
 const esc=value=>String(value ?? '').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const slug=type=>({'Purchase Order':'purchase-order','Purchase Receipt':'purchase-receipt','Purchase Invoice':'purchase-invoice','Payment Entry':'payment-entry','China Accounting Voucher':'china-accounting-voucher','China Voucher Sync Issue':'china-voucher-sync-issue','Supplier':'supplier'}[type]);
 const link=(type,name,label=name)=>name && slug(type)?`<a href="/desk/${slug(type)}/${encodeURIComponent(name)}">${esc(label)}</a>`:'—';
 const money=(value,currency)=>value==null?'—':`${Number(value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}${currency?` ${esc(currency)}`:''}`;
 const quantity=value=>value==null?'—':Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
 const call=async(method,args,namespace=API)=>(await frappe.call({method:namespace+method,args})).message;
 const state=value=>({Posted:'已记账',Reversed:'已冲销',Cancelled:'已取消',Draft:'草稿',Pending:'待同步'}[value] || value || '—');
 const balanceHTML=chain=>`${chain.shared_payable || (chain.invoices || []).some(invoice=>invoice.shared)?'<p class="text-warning">共享应付整单余额，不是本张入库的已付金额</p>':''}${(chain.balances || []).map(b=>`<span>应付 ${money(b.total,b.currency)}　已付/核销 ${money(b.settled,b.currency)}　<b>未付 ${money(b.outstanding,b.currency)}</b></span>`).join('<br>') || '尚未形成应付 / 余额不可见'}`;
 const vouchersHTML=rows=>(rows || []).map(v=>`<button type="button" class="btn btn-link btn-xs dlp-voucher-preview" data-name="${esc(v.name)}">${esc(v.statutory_number || v.name)} · ${esc(state(v.status))} · ${esc(v.source_event==='Posting'?'记账':v.source_event==='Cancellation'?'冲销':v.source_event)}</button>`).join(' · ') || '—';
 const referencesHTML=refs=>(refs || []).map(ref=>`${link(ref.doctype,ref.name)} · 分配 ${money(ref.allocated,ref.currency)} ${(ref.orders || []).map(name=>link('Purchase Order',name)).join(' · ')} ${(ref.receipts || []).map(name=>link('Purchase Receipt',name)).join(' · ')}`).join('；') || '—';
 const paymentSummary=payload=>`${esc(payload.totals_label || '整张付款单银行币种金额')}：${(payload.totals || []).map(row=>`${row.payment_type==='Receive'?'退款':'付款'} / ${{0:'草稿',1:'已提交',2:'已取消'}[row.docstatus]} ${money(row.amount,row.currency)}`).join(' · ') || '—'}（不是采购核销合计）`;

 // Raw projections stay immutable; only actual input events enter this edit set.
 function editSession(projection) {
  let header={},items=new Map();
  const session={document:projection.document,
   touch(field,value){header[field]=['amount','qty','rate'].includes(field)?Number(value):value;},
   touchItem(key,field,value){const row=items.get(key) || {key};row[field]=['qty','rate'].includes(field)?Number(value):value;items.set(key,row);},
   changes(){return {...header,...(items.size?{items:[...items.values()]}:{})};},
   reset(next){this.document=next.document;header={};items=new Map();},
   dirty(){return Object.keys(header).length>0 || items.size>0;},
  }; return session;
 }
 function retryToken(uuid) {
  let token=null,signature=null;
  return {forPayload(payload){const next=JSON.stringify(payload);if(signature!==null && next!==signature)throw new Error('上次响应不确定，内容已改变。请先核对记录并刷新，不要重复建单。');if(!token){token=uuid();signature=next;}return token;},succeeded(){token=null;signature=null;}};
 }
 function operationGate(){let generation=0;return {begin:()=>++generation,cancel:()=>++generation,current:id=>id===generation};}
 const gate=operationGate();let activeDrawer=null,recordsController=null;
 function refreshSurface(){if(recordsController && frappe.get_route?.()[0]==='purchase-payment-records')recordsController.refresh();else root.cur_list?.refresh?.();}
 function recordsRoute(chain){frappe.route_options={[chain.source_doctype==='Purchase Receipt'?'purchase_receipt':'purchase_order']:chain.name};frappe.set_route('purchase-payment-records');}
 function orderReceiptAction(doc){
  if(frappe.model?.can_create?.('Purchase Receipt')===false || doc.row_type==='oa_request' || doc.docstatus!==1 || doc.per_received==null || !Number.isFinite(Number(doc.per_received)) || Number(doc.per_received)>=100 || ['Closed','Cancelled','On Hold','Completed'].includes(doc.status))return '';
  return `<button type="button" class="btn btn-xs btn-default dlp-order-receipt" data-name="${esc(doc.name)}">剩余入库草稿</button>`;
 }
 async function receiptDrafts(sourceName){
  const rows=(await frappe.call({method:'frappe.client.get_list',args:{doctype:'Purchase Receipt',fields:['name','modified'],filters:[['Purchase Receipt','docstatus','=',0],['Purchase Receipt Item','purchase_order','=',sourceName]],order_by:'modified desc',limit_page_length:0}})).message || [];
  // The permission-checked native child join may repeat a parent for each item.
  const seen=new Set();return rows.filter(row=>{if(seen.has(row.name))return false;seen.add(row.name);return true;});
 }
 function newDrawer(title,wide=false){
  if(activeDrawer)return null;
  const id=gate.begin(),opener=root.document.activeElement;
  const panel=$(`<div class="dlp-payment-overlay"><section class="dlp-payment-drawer${wide?' dlp-document-drawer':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><h3>${esc(title)}</h3><button type="button" class="btn btn-default dlp-close" aria-label="关闭">×</button></header><div class="dlp-payment-body"><p role="status">正在读取…</p></div><footer><button type="button" class="btn btn-default dlp-cancel">取消</button></footer></section></div>`).appendTo(root.document.body);
  const drawer={id,panel,controls:[],busy:false,loadId:0,alive:()=>activeDrawer===drawer && gate.current(id),
   close(force=false){if(this.busy && !force)return;gate.cancel();disposeControls(this.controls);panel.remove();root.document.removeEventListener('keydown',keys);if(activeDrawer===this)activeDrawer=null;if(!force)opener?.focus?.();},
   error(error){panel.find('.dlp-error').text(error?.message || '操作失败，请核对系统提示。');},
   setBusy(value){this.busy=value;panel.find('.dlp-payment-drawer').toggleClass('dlp-busy',value);panel.find('.dlp-payment-body').attr('aria-busy',String(value));panel.find('button').prop('disabled',value);},
  };
  const keys=e=>{if(e.target.closest?.('.modal'))return;if(e.key==='Escape'){e.preventDefault();drawer.close();}if(e.key==='Tab'){const elements=panel.find('button,input,select,textarea,summary,a[href]').filter(':visible:not(:disabled)').toArray();if(!elements.length)return;const first=elements[0],last=elements[elements.length-1];if(e.shiftKey && root.document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey && root.document.activeElement===last){e.preventDefault();first.focus();}}};
  activeDrawer=drawer;root.document.addEventListener('keydown',keys);panel.find('.dlp-close,.dlp-cancel').on('click.dlpDrawer',()=>drawer.close());panel.find('.dlp-close').trigger('focus');return drawer;
 }
 const destroyedDatepickers=new WeakSet();
 function disposeControls(controls){for(const control of controls.splice(0)){control.dlpDisposeInput?.();delete control.dlpDisposeInput;control.$input?.off('.dlpDrawer .dlpInvoice');const picker=control.datepicker;if(picker?.destroy && !destroyedDatepickers.has(picker)){destroyedDatepickers.add(picker);picker.destroy();}}}
 function body(drawer,html){disposeControls(drawer.controls);drawer.panel.find('.dlp-payment-body').html(`${html}<div class="dlp-error text-danger" role="alert"></div>`);}
 function advancedHTML(projection,type,name,sourceType,sourceName){return `<details${projection.advanced_reason?' open':''}><summary>高级处理 / 原生单据</summary><p>${esc(projection.advanced_reason || '复杂税费、共享来源、跨币种、退款和付款计划沿用原生单据；此处不改变业务规则。')}</p>${name?link(type,name,'打开原生单据'):link(sourceType,sourceName,'打开来源单据')} ${sourceName?link(sourceType,sourceName,'查看来源'):''}</details>`;}
 function metadataError(){const error=new Error('单据字段元数据读取失败，请刷新或在原生单据核对。');error.dlpMetadata=true;return error;}
 async function loadMetadata(doctype){try{await frappe.model.with_doctype(doctype);}catch(error){throw metadataError();}}
 async function input(drawer,holder,df,value,onTouched){
  if(!drawer.alive())throw new Error('抽屉已关闭');
  const {native_doctype,native_fieldname,currency_context,...presentation}=df;
  const native=frappe.meta.get_docfield(native_doctype,native_fieldname || df.fieldname);if(!native)throw metadataError();
  const numeric=['Currency','Float'].includes(native.fieldtype);
  // Native metadata/defaults remain the sole business parse precision. Labels,
  // aliases and display density belong only to this drawer control instance.
  const overrides=Object.fromEntries(Object.entries(presentation).filter(([key,val])=>key!=='precision' && val!==undefined));
  const control=frappe.ui.form.make_control({parent:holder,df:{...native,...overrides,...(numeric?{fieldtype:native.fieldtype}:{})},render_input:true});
  drawer.controls.push(control);
  if(!drawer.alive()){disposeControls(drawer.controls);throw new Error('抽屉已关闭');}
  if(currency_context)control.get_doc=()=>currency_context;
  if(numeric){const nativeFormat=control.format_for_input,display=Object.create(control);display.get_precision=()=>2;control.format_for_input=value=>nativeFormat.call(display,value);}
  await control.set_value(value ?? '');
  if(!drawer.alive()){disposeControls(drawer.controls.includes(control)?drawer.controls:[control]);throw new Error('抽屉已关闭');}
  if(onTouched && numeric){
   // Capture before the native change handler formats input back to two display
   // decimals. Never read that rounded presentation into the write projection.
   const node=control.$input?.get(0);if(!node?.addEventListener)throw new Error('输入控件不可用，请在原生单据核对。');
   const touched=()=>{if(drawer.alive())onTouched(control.get_value());};
   for(const event of ['input','change'])node.addEventListener(event,touched,true);
   control.dlpDisposeInput=()=>{for(const event of ['input','change'])node.removeEventListener(event,touched,true);};
  }else if(onTouched)control.$input?.on('input.dlpDrawer change.dlpDrawer',()=>onTouched(control.get_value()));
  return control;
 }
 function actionButtons(drawer,projection,session,onSave,onReload){
  const footer=drawer.panel.find('footer');let writeCompleted=false;footer.find('.dlp-save,.dlp-submit,.dlp-reload').remove();
  if(!projection.advanced_reason && projection.document.docstatus===0 && (projection.editable_fields?.length || projection.editable_item_fields?.length))$('<button type="button" class="btn btn-primary dlp-save">保存草稿</button>').appendTo(footer).on('click.dlpDrawer',()=>{if(drawer.alive() && !writeCompleted)return onSave();});
  for(const action of projection.allowed_actions || []){
   const label=action==='Submit'?'提交并记账':action;
   $(`<button type="button" class="btn btn-default dlp-submit">${esc(label)}</button>`).appendTo(footer).on('click.dlpDrawer',()=>{
    if(!drawer.alive() || writeCompleted)return;
    if(session.dirty()){drawer.error(new Error('请先明确保存草稿，再提交。'));return;}
    frappe.confirm(`确认对 ${esc(projection.document.name)} 执行“${esc(label)}”？此操作沿用原生权限及工作流，提交后会记账。`,async()=>{
     if(!drawer.alive() || drawer.busy || writeCompleted)return;drawer.setBusy(true);
     try{
      await call('submit_document',{doctype:projection.document.doctype,name:projection.document.name,expected_modified:projection.document.modified,...(action==='Submit'?{}:{workflow_action:action})},ACTIONS);
      // Acknowledged native write is distinct from the subsequent display read.
      // This old projection must never offer another save/submit after success.
      writeCompleted=true;
      if(drawer.alive()){footer.find('.dlp-save,.dlp-submit').remove();for(const control of drawer.controls)control.$input?.prop('disabled',true);refreshSurface();await onReload();if(drawer.alive())frappe.show_alert({message:'原生操作已完成',indicator:'green'});}
     }
     catch(error){if(drawer.alive())drawer.error(new Error(writeCompleted?'原生操作已完成，但页面刷新失败。请刷新抽屉或核对原生单据，不要重复提交。':'提交未完成：请核对系统提示；版本改变时先刷新抽屉。'));}
     finally{if(drawer.alive())drawer.setBusy(false);}
    });
   });
  }
  const reload=async()=>{
   if(!drawer.alive() || drawer.busy)return;drawer.setBusy(true);
   try{await onReload();}
   catch(error){if(drawer.alive())drawer.error(new Error(error.dlpMetadata?error.message:'刷新未完成，请核对权限或原生单据后重试。'));}
   finally{if(drawer.alive())drawer.setBusy(false);}
  };
  $('<button type="button" class="btn btn-default dlp-reload">刷新抽屉</button>').appendTo(footer).on('click.dlpDrawer',async()=>{
   if(!drawer.alive() || drawer.busy)return;
   if(session.dirty()){frappe.confirm('刷新会丢弃尚未保存的输入，继续？',reload);}else await reload();
  });
 }
 async function documentDrawer(sourceType,sourceName,targetType,targetName=null){
  const drawer=newDrawer(targetType==='Purchase Receipt'?'采购订单 → 剩余入库草稿':'采购入库 → 确认应付',true);if(!drawer)return;
  const token=retryToken(()=>root.crypto.randomUUID());let projection,session;
  const context={source_doctype:sourceType,source_name:sourceName,target_doctype:targetType};
  async function load(){
   const generation=++drawer.loadId;
   const result=await call('preview_document',{...context,...(targetName?{target_name:targetName}:{})},ACTIONS);if(!drawer.alive() || generation!==drawer.loadId)return;
   await loadMetadata(targetType);if(!drawer.alive() || generation!==drawer.loadId)return;
   targetName=result.document.name || null;
   projection=result;session=editSession(result);await render();
  }
  async function render(){
   if(!drawer.alive())return;const doc=projection.document;
   body(drawer,`<p>${link(sourceType,sourceName)} ${doc.name?`→ ${link(targetType,doc.name)}`:''}</p><div class="dlp-document-info"><span>供应商 ${esc(doc.supplier)}</span><span>公司 ${esc(doc.company)}</span><span>币种 ${esc(doc.currency)}</span><span>${doc.docstatus===0?'草稿 · 未记账':'已提交'}</span></div><p class="text-muted">${targetType==='Purchase Receipt'?'这里只保存入库草稿；核对并提交入库仍在原生单据，避免误动库存。':'先核对数量与金额并保存草稿，再明确提交确认应付；不会自动付款。'}</p><div class="dlp-document-fields"></div><div class="dlp-document-items"><table class="table table-bordered"><thead><tr><th>物料</th><th>数量 / 当前剩余</th><th>单位</th><th>单价</th><th>仓库</th></tr></thead><tbody>${(doc.items || []).map((row,index)=>`<tr data-row="${index}"><td title="${esc(row.item_name)}">${esc(row.item_code)}<br>${esc(row.item_name)}</td><td data-edit="qty"></td><td>${esc(row.uom)}</td><td data-edit="rate"></td><td data-edit="warehouse"></td></tr>`).join('')}</tbody></table></div><p>不含税 ${money(doc.net_total,doc.currency)}　<b>总金额 ${money(doc.grand_total,doc.currency)}</b>（保存后由原生规则重算）</p><details><summary>税费（原生计算，只读）</summary><table class="table table-bordered"><tbody>${(doc.taxes || []).map(row=>`<tr><td>${esc(row.description || row.account_head)}</td><td>${quantity(row.rate)}%</td><td>${money(row.tax_amount,doc.currency)}</td></tr>`).join('') || '<tr><td>无税费</td></tr>'}</tbody></table></details>${advancedHTML(projection,targetType,doc.name,sourceType,sourceName)}`);
   drawer.setBusy(true);const tasks=[];
   for(const [field,type,label] of [['posting_date','Date','单据日期'],['bill_no','Data','供应商票据号'],['bill_date','Date','票据日期'],['remarks','Small Text','备注']]){
    if(!(field in doc))continue;
    const holder=$('<div></div>').appendTo(drawer.panel.find('.dlp-document-fields'));
    tasks.push(input(drawer,holder,{native_doctype:targetType,fieldname:field,fieldtype:type,label,read_only:!projection.editable_fields.includes(field)},doc[field],projection.editable_fields.includes(field)?value=>session.touch(field,value):null));
   }
   for(const [index,row] of (doc.items || []).entries())for(const field of ['qty','rate','warehouse']){
    const holder=drawer.panel.find(`[data-row="${index}"] [data-edit="${field}"]`),editable=projection.editable_item_fields.includes(field);
    if(!editable){holder.html(esc(field==='warehouse'?(row[field] || '—'):field==='rate'?money(row[field]):quantity(row[field])));}
    else tasks.push(input(drawer,holder,{native_doctype:targetType+' Item',currency_context:doc,fieldname:field,fieldtype:field==='warehouse'?'Link':field==='rate'?'Currency':'Float',options:field==='warehouse'?'Warehouse':undefined,label:field==='qty'?'数量':field==='rate'?'单价':'仓库'},row[field],value=>session.touchItem(row.key,field,value)).then(control=>{if(field==='warehouse')control.get_query=()=>({filters:{company:doc.company,is_group:0}});}));
    if(field==='qty')$(`<small class="text-muted">最多 ${quantity(row.max_qty)}</small>`).appendTo(holder);
   }
   await Promise.all(tasks);if(!drawer.alive())return;
   if(targetType==='Purchase Receipt' && doc.name){
    $('<button type="button" class="btn btn-default dlp-explicit-new">明确新建另一张剩余入库草稿</button>').appendTo(drawer.panel.find('.dlp-payment-body')).on('click.dlpDrawer',()=>frappe.confirm('已有草稿。仍要明确新建另一张入库草稿？请确认不是重复收货。',async()=>{if(!drawer.alive() || drawer.busy)return;targetName=null;try{await load();}catch(error){if(drawer.alive())drawer.error(error);}}));
   }
   actionButtons(drawer,projection,session,save,load);drawer.setBusy(false);
  }
  async function save(){
   if(drawer.busy)return;drawer.setBusy(true);
   try{
    const args={...context,changes:session.changes(),...(targetName?{target_name:targetName,expected_modified:session.document.modified}:{})};
    const result=await call('save_document_draft',{...args,request_id:token.forPayload(args)},ACTIONS);
    token.succeeded();if(!drawer.alive())return;
    targetName=result.document.name;projection=result;session.reset(result);await render();refreshSurface();frappe.show_alert({message:`已保存草稿 ${link(targetType,targetName)}`,indicator:'green'});
   }catch(error){if(drawer.alive())drawer.error(new Error(error.message || '保存失败：相同内容可重试；若响应不确定请核对记录。版本改变时刷新抽屉。'));}
   finally{if(drawer.alive())drawer.setBusy(false);}
  }
  try{
   if(sourceType==='Purchase Order' && !targetName){
    const drafts=await receiptDrafts(sourceName);if(!drawer.alive())return;
    if(drafts.length===1)targetName=drafts[0].name;
    if(drafts.length>1){
     body(drawer,`<p>${link(sourceType,sourceName)} 已有 ${drafts.length} 张可见入库草稿。请明确选择继续编辑，避免重复建单。</p><div class="dlp-draft-choices">${drafts.map(draft=>`<p><button type="button" class="btn btn-default dlp-draft-choice" data-target="${esc(draft.name)}">继续 ${esc(draft.name)}</button> ${link('Purchase Receipt',draft.name,'原生详情')}</p>`).join('')}</div><button type="button" class="btn btn-default dlp-explicit-new">明确新建另一张剩余入库草稿</button>`);
     drawer.panel.find('.dlp-draft-choice').on('click.dlpDrawer',async e=>{targetName=e.currentTarget.dataset.target;try{await load();}catch(error){if(drawer.alive())drawer.error(error);}});
     drawer.panel.find('.dlp-explicit-new').on('click.dlpDrawer',()=>frappe.confirm('已有草稿未提交。仍要明确新建另一张入库草稿？请先确认不是重复收货。',async()=>{if(!drawer.alive())return;try{await load();}catch(error){if(drawer.alive())drawer.error(error);}}));
     return;
    }
   }
   await load();
  }catch(error){if(drawer.alive()){body(drawer,`<p class="text-danger">${error.dlpMetadata?esc(error.message):'无法预览，请核对权限、剩余数量或关联单据。已有草稿请在列表继续编辑。'}</p>${link(sourceType,sourceName,'打开来源单据')}`);drawer.setBusy(false);}}
 }
 async function pay(sourceType,sourceName){
  const drawer=newDrawer('采购付款');if(!drawer)return;
  try{
   const chain=await call('get_purchase_chain',{source_doctype:sourceType,source_name:sourceName});if(!drawer.alive())return;
   if(!chain.can_create){body(drawer,`<p>${esc(chain.reason)}</p>${link(sourceType,sourceName,'打开原生来源')}`);return;}
   const eligible=chain.invoices.filter(invoice=>invoice.can_pay),controls={},token=retryToken(()=>root.crypto.randomUUID());let amountTouched=false,amountInput,invoiceGeneration=0;
   if(!eligible.length){body(drawer,'<p>当前没有可快捷付款的应付余额，请打开原生应付单处理。</p>');return;}
   await loadMetadata('Payment Entry');if(!drawer.alive())return;
   body(drawer,`<p>${link(sourceType,sourceName)} · ${esc(chain.supplier)}</p><div class="dlp-payment-balances">${balanceHTML(chain)}</div>${(chain.warnings || []).map(w=>`<p class="text-warning">${esc(w)}</p>`).join('')}<p class="text-muted">可部分付款。这里只创建草稿，提交后才计已付；保存后仍留在列表。</p><div class="dlp-fields"></div><details><summary>高级处理</summary><p>共享、跨币种、退款、扣款及复杂付款计划沿用原生应付单。</p>${eligible.map(i=>link('Purchase Invoice',i.name)).join(' · ')}</details>`);
   drawer.setBusy(true);
   const currencyContext={currency:eligible[0].currency,paid_from_account_currency:eligible[0].currency};
   const add=async(df,value,touched)=>controls[df.fieldname]=await input(drawer,$('<div></div>').appendTo(drawer.panel.find('.dlp-fields')),{native_doctype:'Payment Entry',...df},value,touched);
   await add({native_doctype:'Payment Entry Reference',native_fieldname:'reference_name',fieldname:'invoice',fieldtype:'Select',label:'关联采购应付单',options:eligible.map(i=>i.name).join('\n'),reqd:1},eligible[0].name);
   await add({native_fieldname:'paid_amount',currency_context:currencyContext,fieldname:'amount',fieldtype:'Currency',label:'本次付款金额（应付账户币种）',reqd:1},eligible[0].outstanding,value=>{amountTouched=true;amountInput=value;});
   await add({native_fieldname:'paid_from',fieldname:'bank',fieldtype:'Link',options:'Account',label:'银行 / 现金记账账户',reqd:1},'');
   controls.bank.get_query=()=>({filters:{company:chain.company,is_group:0,disabled:0,account_type:['in',['Bank','Cash']],account_currency:eligible.find(i=>i.name===controls.invoice.get_value())?.currency}});
   await add({native_fieldname:'posting_date',fieldname:'date',fieldtype:'Date',label:'付款日期',reqd:1},frappe.datetime.get_today());
   await add({native_fieldname:'reference_no',fieldname:'reference',fieldtype:'Data',label:'银行参考号（银行必填，现金可空）'},'');
   await add({fieldname:'remarks',fieldtype:'Small Text',label:'备注'},'');
   controls.invoice.$input?.on('change.dlpInvoice',async()=>{const generation=++invoiceGeneration,chosen=eligible.find(i=>i.name===controls.invoice.get_value());if(chosen && drawer.alive()){currencyContext.currency=currencyContext.paid_from_account_currency=chosen.currency;await controls.amount.set_value(chosen.outstanding);if(drawer.alive() && generation===invoiceGeneration)amountTouched=false;}});
   if(!drawer.alive())return;
   $('<button type="button" class="btn btn-primary dlp-create">创建付款草稿</button>').appendTo(drawer.panel.find('footer')).on('click.dlpDrawer',async()=>{
    if(drawer.busy)return;const chosen=eligible.find(i=>i.name===controls.invoice.get_value()),amount=amountTouched?amountInput:chosen?.outstanding;
    if(!chosen || !Number.isFinite(Number(amount)) || Number(amount)<=0 || Number(amount)>Number(chosen.outstanding) || !controls.bank.get_value() || !controls.date.get_value()){drawer.error(new Error('请填写账户、日期，以及不超过未付余额的正数金额。'));return;}
    drawer.setBusy(true);
    try{
     const args={source_doctype:sourceType,source_name:sourceName,purchase_invoice:chosen.name,amount_to_pay:amount,bank_account:controls.bank.get_value(),posting_date:controls.date.get_value(),reference_no:controls.reference.get_value(),remarks:controls.remarks.get_value()};
     const result=await call('create_payment_draft',{...args,request_id:token.forPayload(args)});token.succeeded();if(!drawer.alive())return;
     drawer.busy=false;drawer.close();refreshSurface();frappe.show_alert({message:`已创建付款草稿 ${link('Payment Entry',result.name)}；可在采购付款记录核对并提交`,indicator:'green'});
    }catch(error){if(drawer.alive())drawer.error(new Error(error.message || '创建失败：相同内容可重试；响应不确定时先检查付款记录，勿改内容重复创建。'));}
    finally{if(drawer.alive())drawer.setBusy(false);}
   });drawer.setBusy(false);
  }catch(error){if(drawer.alive()){body(drawer,`<p class="text-danger">${error.dlpMetadata?esc(error.message):'无法读取付款信息，请核对系统提示。'}</p>${link(sourceType,sourceName,'打开原生来源')}`);drawer.setBusy(false);}}
 }
 async function paymentDrawer(name){
  const drawer=newDrawer('采购付款单预览 / 草稿编辑');if(!drawer)return;let projection,session;
  async function load(){const generation=++drawer.loadId,result=await call('preview_payment',{name},ACTIONS);if(!drawer.alive() || generation!==drawer.loadId)return;await loadMetadata('Payment Entry');if(!drawer.alive() || generation!==drawer.loadId)return;projection=result;session=editSession(result);await render();}
  async function render(){
   const doc=projection.document;body(drawer,`<p>${link('Payment Entry',name)} · ${esc(doc.supplier)}</p><p>整单银行金额 ${money(doc.amount,doc.currency)} · ${{0:'草稿 · 未计已付',1:'已提交',2:'已取消 · 未计已付'}[doc.docstatus]}</p><p>${esc(doc.company)}</p><div class="dlp-fields"></div><details open><summary>采购核销引用（各引用币种）</summary>${referencesHTML(doc.references)}</details>${advancedHTML(projection,'Payment Entry',name)}`);
   drawer.setBusy(true);
   for(const [field,type,label] of [['posting_date','Date','付款日期'],['amount','Currency','整单金额（银行币种）'],['bank_account','Link','银行 / 现金记账账户'],['reference_no','Data','银行参考号'],['remarks','Small Text','备注']]){
    const nativeField=field==='amount'?(doc.payment_type==='Receive'?'received_amount':'paid_amount'):field==='bank_account'?(doc.payment_type==='Receive'?'paid_to':'paid_from'):field;
    const editable=projection.editable_fields.includes(field),control=await input(drawer,$('<div></div>').appendTo(drawer.panel.find('.dlp-fields')),{native_doctype:'Payment Entry',native_fieldname:nativeField,currency_context:{...doc,paid_from_account_currency:doc.currency,paid_to_account_currency:doc.currency},fieldname:field,fieldtype:type,options:field==='bank_account'?'Account':undefined,label,read_only:!editable},doc[field],editable?value=>session.touch(field,value):null);
    if(field==='bank_account')control.get_query=()=>({filters:{company:doc.company,is_group:0,disabled:0,account_type:['in',['Bank','Cash']],account_currency:doc.currency}});
   }
   if(!drawer.alive())return;actionButtons(drawer,projection,session,save,load);drawer.setBusy(false);
  }
  async function save(){if(drawer.busy)return;drawer.setBusy(true);try{const result=await call('update_payment_draft',{name,changes:session.changes(),expected_modified:session.document.modified},ACTIONS);if(!drawer.alive())return;projection=result;session.reset(result);await render();refreshSurface();frappe.show_alert({message:'付款草稿已保存',indicator:'green'});}catch(error){if(drawer.alive())drawer.error(new Error('保存未完成，请核对系统提示。版本改变时刷新抽屉，勿重复修改。'));}finally{if(drawer.alive())drawer.setBusy(false);}}
  try{await load();}catch(error){if(drawer.alive()){body(drawer,`<p class="text-danger">${error.dlpMetadata?esc(error.message):'账户或单据不可用 / 无权读取，请在原生单据核对。'}</p>${link('Payment Entry',name,'打开原生付款单')}`);drawer.setBusy(false);}}
 }
 async function voucherDrawer(name){
  const drawer=newDrawer('财务凭证（只读）',true);if(!drawer)return;
  try{const doc=await call('get_voucher_detail',{name},ACTIONS);if(!drawer.alive())return;body(drawer,`<p>${link('China Accounting Voucher',name)} · ${esc(doc.statutory_number || '—')} · ${esc(state(doc.status))} · ${esc(doc.source_event==='Cancellation'?'冲销':'记账')}</p><p>${esc(doc.company)} · ${esc(doc.posting_date)}</p><p>来源 ${link(doc.source_doctype,doc.source_name)} ${doc.reversal_of?`原凭证 ${link('China Accounting Voucher',doc.reversal_of)}`:''} ${doc.reversed_by?`冲销凭证 ${link('China Accounting Voucher',doc.reversed_by)}`:''}</p><div class="dlp-document-items"><table class="table table-bordered"><thead><tr><th>科目</th><th>借方</th><th>贷方</th><th>摘要</th></tr></thead><tbody>${(doc.entries || []).map(row=>`<tr><td>${esc(row.account_name || row.account)}</td><td class="text-right">${money(row.debit,doc.currency)}</td><td class="text-right">${money(row.credit,doc.currency)}</td><td>${esc(row.remarks)}</td></tr>`).join('')}</tbody></table></div><p>借方 ${money(doc.total_debit,doc.currency)}\u3000贷方 ${money(doc.total_credit,doc.currency)}</p>${(doc.warnings || []).map(w=>`<p class="text-warning">${esc(w)}</p>`).join('')}`);}catch(error){if(drawer.alive())body(drawer,'<p class="text-danger">无权读取或凭证不可用，请核对系统提示。</p>');}
 }
 async function formRefresh(frm){
  frm.$wrapper.find('.dlp-purchase-chain').remove();if(frm.is_new())return;
  const current=frm.doc.name,generation=frm.dlpChainGeneration=(frm.dlpChainGeneration || 0)+1;
  try{const chain=await call('get_purchase_chain',{source_doctype:frm.doctype,source_name:current});if(frm.doc.name!==current || frm.dlpChainGeneration!==generation)return;
   const progress=(chain.order_progress || []).map(order=>`<p>${link('Purchase Order',order.name)} · 订单 ${money(order.grand_total,order.currency)} · ${(order.units || []).map(unit=>`已入 ${quantity(unit.received)} / 待入 ${quantity(unit.pending)} ${esc(unit.uom)}`).join('；')} · 待入货品金额 ${money(order.pending_net_amount,order.currency)}（不含税）</p>`).join('');
   const receiptSource=frm.doctype==='Purchase Receipt' && chain.source_doctype==='Purchase Receipt';
   const invoiceActions=receiptSource?`${(chain.draft_invoices || []).map(i=>`<button class="btn btn-default btn-sm dlp-receipt-invoice" data-name="${esc(current)}" data-target="${esc(i.name || i)}">继续应付草稿</button>`).join(' ')} ${chain.can_create_invoice?`<button class="btn btn-default btn-sm dlp-receipt-invoice" data-name="${esc(current)}">确认应付</button>`:''}`:'';
   const box=$(`<section class="dlp-purchase-chain"><strong>采购关联与付款</strong><p>${chain.orders.map(n=>link('Purchase Order',n)).join(' · ')}</p>${progress}<div>${balanceHTML(chain)}</div>${(chain.warnings || []).map(w=>`<p class="text-warning">${esc(w)}</p>`).join('')}<p>${chain.invoices.map(i=>`${link('Purchase Invoice',i.name)} ${i.docstatus===0?'草稿':i.docstatus===2?'已取消':''}`).join(' · ') || esc(chain.reason)}</p><div><button type="button" class="btn btn-default btn-sm dlp-records">采购付款记录</button> ${invoiceActions} ${chain.can_create?'<button class="btn btn-primary btn-sm dlp-pay">付款 / 继续付款</button>':''}</div>${chain.payments.length?`<details><summary>关联付款与凭证（最多 100 条）</summary>${chain.payments.map(row=>`<p>${link('Payment Entry',row.name)} · ${esc(row.state)} · ${money(row.amount,row.currency)}<br>${referencesHTML(row.references)}<br>${vouchersHTML(row.vouchers)}</p>`).join('')}</details>`:''}</section>`).prependTo(frm.layout.wrapper);
   box.find('.dlp-pay').on('click.dlpForm',()=>pay(frm.doctype,current));
   box.find('.dlp-records').on('click.dlpForm',()=>recordsRoute(chain));
  }catch(error){/* Native form remains available without finance read permissions. */}
 }
 const recordColumns=[['posting_date','付款日期',96],['name','付款单号',165],['supplier','供应商',165],['company','公司',140],['payment_type','类型',65],['amount','整单金额',140],['bank_account','记账账户',165],['state','付款状态',155],['references','采购关联 / 分配币种',290],['vouchers','财务凭证 / 状态',240],['sync_issues','同步提示',145],['action','操作',100]].map(([fieldname,label,width])=>({fieldname,label,width}));
 function recordsRequest(c){const sort=c.providerOrderBy.replace(/^supplier\b/,'party').replace(/^state\b/,'docstatus');return {method:API+'get_payment_records',args:{...c.quick,native_filters:JSON.stringify(c.nativeFilterGroup?.get_filters() || []),or_filters:JSON.stringify(c.orFilterGroup?.get_filters() || []),start:c.page*c.pageSize,page_length:c.pageSize,order_by:sort}};}
 function mountRecordsFilters(c){
  const change=()=>{if(c.resetting)return;c.setPage(0);c.refresh();};
  for(const [key,label] of [['nativeFilterGroup','全部条件（AND）'],['orFilterGroup','任一条件（OR）']]){
   const button=$(`<button type="button" class="btn btn-default btn-sm filter-box" aria-expanded="false"><span class="filter-icon"></span>${esc(label)} <span class="button-label"></span></button>`).appendTo(c.$toolbar);
   const parent=$(`<section class="dlp-payment-native-filters" aria-label="${esc(label)}"></section>`).insertAfter(c.$filters).hide();
   const group=new frappe.ui.FilterGroup({doctype:'Payment Entry',parent,on_change:change});
   // Native inline FilterGroup avoids its single global popover assumption and
   // document handlers. Only the reveal/close shell is page-scoped.
   group.filter_button=button;
   group.hide_popover=()=>{parent.hide();button.attr('aria-expanded','false');group.update_filters();};
   button.on('click.dlpRecords',()=>{if(parent.is(':visible'))group.hide_popover();else{parent.show();button.attr('aria-expanded','true');if(!group.filters.length)group.add_filter('Payment Entry','name');}});
   const validate=group.validate_args.bind(group),push=group._push_new_filter.bind(group);
   // Native metadata/permlevel selection stays authoritative. The service only
   // supports parent PE fields; do not offer child fields it would reject.
   group.validate_args=(doctype,field)=>{if(doctype!=='Payment Entry' || !c.nativeAllowed.has(field)){frappe.msgprint({message:'此字段不在当前付款记录的可读筛选范围内。',indicator:'orange'});return false;}return validate(doctype,field);};
   group._push_new_filter=(...args)=>{const filter=push(...args),select=filter?.fieldselect;if(select){select.options=select.options.filter(option=>option.doctype==='Payment Entry' && c.nativeAllowed.has(option.fieldname));select.awesomplete.list=select.options;}return filter;};
   c[key]=group;
  }
  c.resetAdvancedFilters=()=>{c.nativeFilterGroup.clear_filters();c.orFilterGroup.clear_filters();};
 }
 async function recordsExport(c){const args={...recordsRequest(c).args,export_format:'xlsx',columns:JSON.stringify(c.preferences.columns.filter(field=>field!=='action'))};delete args.start;delete args.page_length;if(!root.DeepLinkERPPurchaseOrderExport?.downloadWorkbook)await frappe.require('/assets/deeplinkerp_branding/js/purchase_order_export.js');const exporter=root.DeepLinkERPPurchaseOrderExport;if(!exporter)throw new Error('导出组件加载失败，请刷新。');exporter.downloadWorkbook(root,await exporter.fetchNativeWorkbook(root,args,API+'get_payment_records'),'采购付款记录');}
 function recordsPage(wrapper){
  const page=frappe.ui.make_app_page({parent:wrapper,title:'采购付款记录',single_column:true});
  const provider={columns:recordColumns,defaultColumns:recordColumns.map(c=>c.fieldname),freezeUntil:'supplier',formLink:doc=>`/desk/payment-entry/${encodeURIComponent(doc.name)}`,request:recordsRequest,exportCurrent:recordsExport,summary:c=>paymentSummary(c.providerPayload || {}),sortFields:['posting_date','name','company','supplier','payment_type','state'],
   renderValue:(field,doc)=>{if(field==='supplier')return link('Supplier',doc.supplier);if(field==='amount')return money(doc.amount,doc.currency);if(field==='payment_type')return doc.payment_type==='Receive'?'退款':'付款';if(field==='references')return referencesHTML(doc.references);if(field==='vouchers')return vouchersHTML(doc.vouchers);if(field==='state')return `${esc(doc.state)}${(doc.warnings || []).length?` <span title="${esc(doc.warnings.join('；'))}">⚠</span>`:''}`;if(field==='sync_issues')return(doc.sync_issues || []).map(issue=>`${link('China Voucher Sync Issue',issue.name,'凭证待同步')} · ${esc(state(issue.status))}`).join('；') || '—';if(field==='action')return `<button type="button" class="btn btn-default btn-xs dlp-payment-preview" data-name="${esc(doc.name)}">${doc.can_edit?'编辑草稿':doc.allowed_actions?.length?'预览 / 提交':'预览'}</button>`;},
   mountControls:c=>{mountRecordsFilters(c);c.list.$result.on('click.dlpRecords','[data-provider-sort]',e=>{const field=e.currentTarget.dataset.providerSort,parts=c.providerOrderBy.split(' ');c.providerOrderBy=`${field} ${parts[0]===field && parts[1]==='asc'?'desc':'asc'}`;c.setPage(0);c.refresh();});$('<button type="button" class="btn btn-default btn-sm">清空筛选</button>').appendTo(c.$toolbar).on('click.dlpRecords',()=>c.clearQuickFilters());},
   onPayload:c=>{c.$providerNotice?.remove();c.$providerNotice=$('<p class="text-muted dlp-po-provider-notice"></p>').text(c.providerPayload.notice || '').insertAfter(c.$filters);},
  };
  const fieldMap={supplier:'party',state:'docstatus',amount:'paid_amount',bank_account:'paid_from',references:'references',purchase_order:'references',purchase_receipt:'references',from_date:'posting_date',to_date:'posting_date',status:'docstatus'};
  const grid=root.DeepLinkERPCompactList.create({doctype:'Payment Entry',dismissInitialOnboarding:true,pageRoute:'purchase-payment-records',routeClass:'dlp-purchase-payment-grid-active',columns:recordColumns,provider,pageFieldMap:fieldMap,numbers:['amount'],dates:['posting_date'],controls:[['search','Data',null,'付款单号 / 供应商'],['company','Link','Company','公司'],['supplier','Link','Supplier','供应商'],['purchase_order','Link','Purchase Order','采购订单'],['purchase_receipt','Link','Purchase Receipt','采购入库'],['from_date','Date',null,'付款开始日期'],['to_date','Date',null,'付款结束日期'],['status','Select','\nDraft\nSubmitted\nCancelled','单据状态']].map(([fieldname,fieldtype,options,label])=>({fieldname,fieldtype,options,label,permission_field:fieldMap[fieldname]})),optionLabels:{status:{Draft:'草稿',Submitted:'已提交',Cancelled:'已取消'}}});
  const ready=frappe.model.with_doctype('Payment Entry').then(()=>{const c=grid.mountPage(page,root);recordsController=c;wrapper.dlpRecordsController=c;return c;});
  ready.catch(()=>page.main.append('<p class="text-danger">付款元数据读取失败，请刷新或核对权限。</p>'));
  wrapper.dlpLoad=async()=>{const c=await ready;c.activate();if((frappe.get_route?.() || [])[0]!=='purchase-payment-records')return;const options=frappe.route_options || {};frappe.route_options=null;if(Object.keys(options).length){c.resetting=true;await Promise.all(Object.entries(c.controls).map(([field,control])=>control.set_value(options[field] || '')));c.quick={...options};c.resetting=false;c.setPage(0);}return c.refresh();};
  page.set_secondary_action('刷新',async()=>{const c=await ready;return c.refresh();});
 }
 // Exactly one delegated click handler per loaded resource; cached pages reuse it.
 if(root.document && !root.__dlpProcurementActionsInstalled){
  root.__dlpProcurementActionsInstalled=true;
  root.document.addEventListener('click',event=>{const button=event.target.closest?.('.dlp-receipt-pay,.dlp-receipt-invoice,.dlp-order-receipt,.dlp-payment-preview,.dlp-voucher-preview');if(!button)return;event.preventDefault();event.stopPropagation();const name=button.dataset.name;if(button.classList.contains('dlp-receipt-pay'))pay('Purchase Receipt',name);else if(button.classList.contains('dlp-receipt-invoice'))documentDrawer('Purchase Receipt',name,'Purchase Invoice',button.dataset.target || null);else if(button.classList.contains('dlp-order-receipt'))documentDrawer('Purchase Order',name,'Purchase Receipt');else if(button.classList.contains('dlp-payment-preview'))paymentDrawer(name);else voucherDrawer(name);},true);
  frappe.router?.on('change',()=>{gate.cancel();activeDrawer?.close(true);});
 }
 root.DeepLinkERPPurchasePayments={pay,formRefresh,recordsPage,balanceHTML,documentDrawer,paymentDrawer,voucherDrawer,orderReceiptAction,vouchersHTML,paymentSummary,editSession,retryToken,operationGate,recordsRequest,recordsExport,receiptDrafts,mountRecordsFilters,disposeControls};
})(typeof globalThis!=='undefined'?globalThis:this);
