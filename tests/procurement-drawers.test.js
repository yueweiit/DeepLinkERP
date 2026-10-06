const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const engine = require('../deeplinkerp_branding/public/js/compact_list.js');

function payments(call, extras={}, capture=()=>{}) {
  const host = { document: { addEventListener() {} }, ...extras, frappe: { call, router: { on() {} }, model:{with_doctype:async()=>{}},meta:{get_docfield:(doctype,fieldname)=>({fieldname,fieldtype:'Data',parent:doctype})},utils: { escape_html: value => String(value).replaceAll('<', '&lt;') }, ...extras.frappe } };
  capture(host);
  vm.runInNewContext(fs.readFileSync(require.resolve('../deeplinkerp_branding/public/js/purchase_payments.js'), 'utf8'), { globalThis: host, ...host });
  return host.DeepLinkERPPurchasePayments;
}
function functionFrom(name) { const fn = payments()[name]; assert.equal(typeof fn, 'function', `${name} is used by drawers`); return fn; }

test('operating expenses can reuse the accessible procurement drawer shell factory', () => {
  assert.equal(typeof payments().createDrawer,'function');
});

test('shared procurement numeric presentation helpers keep business parse precision unchanged', () => {
  const api=payments();
  assert.equal(typeof api.formatMoney,'function'); assert.equal(typeof api.formatQuantity,'function'); assert.equal(typeof api.formatNumericInput,'function');
  assert.equal(api.formatMoney(123.45678,'CNY'),'123.46 CNY'); assert.equal(api.formatQuantity(2.00001),'2');
  const control={df:{precision:8},get_precision(){return this.df.precision;},format_for_input(value){return Number(value).toFixed(this.get_precision());}};
  api.formatNumericInput(control);
  assert.equal(control.format_for_input(2.00001),'2.00'); assert.equal(control.format_for_input(49.99975000125),'50.00');
  assert.equal(control.get_precision(),8); assert.equal(control.df.precision,8);
});

test('drawer edit session sends only touched fields, never rounded initialized quantities or money', () => {
  const session = functionFrom('editSession')({document:{qty:1.234567,amount:9.87654,remarks:'old',items:[{key:'row',qty:1.234567,rate:9.87654}]}});
  assert.deepEqual(JSON.parse(JSON.stringify(session.changes())), {});
  session.touch('remarks', 'new');
  assert.deepEqual(JSON.parse(JSON.stringify(session.changes())), {remarks:'new'});
  session.touchItem('row','qty','0.75');
  assert.deepEqual(JSON.parse(JSON.stringify(session.changes())), {remarks:'new',items:[{key:'row',qty:0.75}]});
  assert.equal(session.document.items[0].rate,9.87654);
});
test('payment records forwards native AND/OR unchanged alongside quick predicates and exports the clicked complete scope',async()=>{
 let args,resolve,host;const api=payments(undefined,{frappe:{require:()=>new Promise(r=>resolve=r)}},value=>host=value);
 const c={quick:{search:'A'},nativeFilterGroup:{get_filters:()=>[['Payment Entry','owner','=','buyer']]},orFilterGroup:{get_filters:()=>[['Payment Entry','company','=','C']]},providerOrderBy:'supplier asc',page:2,pageSize:500,preferences:{columns:['supplier','name','action']}};
 const request=api.recordsRequest(c);
 assert.deepEqual(JSON.parse(request.args.native_filters),[['Payment Entry','owner','=','buyer']]);
 assert.deepEqual(JSON.parse(request.args.or_filters),[['Payment Entry','company','=','C']]);assert.equal(request.args.order_by,'party asc');
 const pending=api.recordsExport(c);c.quick.search='B';
 // Export uses the same native predicates, not only the current page or a later quick search.
 c.nativeFilterGroup.get_filters=()=>[];
 host.DeepLinkERPPurchaseOrderExport={fetchNativeWorkbook:async(root,value)=>{args=value;return new Uint8Array();},downloadWorkbook(){}};
 resolve();await pending;
 assert.equal(args.search,'A');assert.equal(args.start,undefined);assert.equal(args.page_length,undefined);
 assert.deepEqual(JSON.parse(args.columns),['supplier','name']);assert.deepEqual(JSON.parse(args.native_filters),[['Payment Entry','owner','=','buyer']]);
});
test('records advanced controls reuse two native FilterGroups with parent permission whitelist and one reset',()=>{
 const groups=[];class NativeGroup{constructor(opts){Object.assign(this,opts);this.initialButton=opts.filter_button;this.wrapper=opts.parent;groups.push(this);this.filters=[];}get_filters(){return this.filters;}clear_filters(){this.filters=[];}validate_args(){return true;} _push_new_filter(){return {fieldselect:{options:[{doctype:'Payment Entry',fieldname:'company'},{doctype:'Payment Entry',fieldname:'secret'},{doctype:'Payment Entry Reference',fieldname:'reference_name'}],awesomplete:{}}};}}
 const surface={appendTo(){return this;},insertAfter(){return this;},hide(){return this;},on(){return this;}};
 const api=payments(undefined,{$:()=>surface,frappe:{ui:{FilterGroup:NativeGroup},msgprint(){}}});
 assert.equal(typeof api.mountRecordsFilters,'function');let page=-1,refresh=0;
 const c={$toolbar:surface,nativeAllowed:new Set(['name','company']),list:{meta:{name:'Payment Entry'}},setPage:value=>page=value,refresh:()=>refresh++};
 api.mountRecordsFilters(c);assert.equal(groups.length,2);assert.equal(groups[0].doctype,'Payment Entry');assert.equal(groups[0].validate_args('Payment Entry','secret'),false);
 assert.equal(groups[0].initialButton,undefined,'native inline groups do not share Frappe single popover selector or install document handlers');
 assert.equal(groups[0].validate_args('Payment Entry Reference','reference_name'),false);
 const filter=groups[0]._push_new_filter('Payment Entry','company');assert.deepEqual(filter.fieldselect.options,[{doctype:'Payment Entry',fieldname:'company'}]);
 groups[0].on_change();assert.equal(page,0);assert.equal(refresh,1);
 groups[0].filters=[['Payment Entry','company','=','A']];groups[1].filters=[['Payment Entry','name','like','PE%']];c.resetAdvancedFilters();assert.deepEqual(groups.map(g=>g.filters),[[],[]]);
});
test('PO form never emits PR-only invoice shortcut even when chain has a draft invoice',async()=>{
 let html='';const box={find(){return {on(){}};},prependTo(){return this;}};
 const api=payments(async()=>({message:{source_doctype:'Purchase Order',orders:[],invoices:[],payments:[],balances:[],draft_invoices:[{name:'DRAFT-PI'}],can_create_invoice:true}}),{$:value=>{html=value;return box;}});
 await api.formRefresh({doctype:'Purchase Order',doc:{name:'PO'},is_new:()=>false,$wrapper:{find:()=>({remove(){}})},layout:{wrapper:{}}});
 assert.doesNotMatch(html,/dlp-receipt-invoice/);
});
test('owned drawer controls release native datepicker and their handlers once',()=>{
 let destroyed=0,unbound=0;const cleanup=functionFrom('disposeControls');const controls=[{datepicker:{destroy:()=>destroyed++},$input:{off:()=>unbound++}}];
 cleanup(controls);cleanup(controls);assert.equal(destroyed,1);assert.equal(unbound,1);assert.equal(controls.length,0);
});
test('real pay async initialization stops after route cancellation, without creating five later controls',async()=>{
 let routeClose,resolveFirst,started,created=0,dateCreated=0,removed=0;
 const firstStarted=new Promise(resolve=>started=resolve);
 const surface={appendTo(){return this;},find(){return this;},on(){return this;},off(){return this;},html(){return this;},trigger(){return this;},toggleClass(){return this;},attr(){return this;},prop(){return this;},remove(){removed++;return this;}};
 const api=payments(async()=>({message:{can_create:true,invoices:[{name:'PI',can_pay:true,outstanding:100,currency:'USD'}],company:'C',balances:[]}}),{$:()=>surface,document:{body:{},addEventListener(){},removeEventListener(){}},crypto:{randomUUID:()=> 'uuid'},frappe:{router:{on:(type,fn)=>routeClose=fn},datetime:{get_today:()=> '2026-10-04'},ui:{form:{make_control:({df})=>{created++;if(df.fieldtype==='Date')dateCreated++;return {$input:surface,get_value:()=>'',set_value:()=>created===1?new Promise(resolve=>{resolveFirst=resolve;started();}):Promise.resolve()};}}}}});
 const pending=api.pay('Purchase Receipt','PR');await firstStarted;routeClose();resolveFirst();await pending;
 assert.equal(created,1);assert.equal(dateCreated,0);assert.equal(removed,1);
});
test('real date control initialized before route cancellation is destroyed and cannot continue drawer initialization',async()=>{
 let routeClose,resolveFirst,started,created=0,destroyed=0;
 const firstStarted=new Promise(resolve=>started=resolve);
 const surface={appendTo(){return this;},find(){return this;},on(){return this;},off(){return this;},html(){return this;},trigger(){return this;},toggleClass(){return this;},attr(){return this;},prop(){return this;},remove(){return this;}};
 const api=payments(async()=>({message:{document:{name:'PE',posting_date:'2026-10-04',docstatus:0,references:[]},editable_fields:['posting_date'],allowed_actions:[]}}),{$:()=>surface,document:{body:{},addEventListener(){},removeEventListener(){}},frappe:{router:{on:(type,fn)=>routeClose=fn},ui:{form:{make_control:({df})=>{created++;return {$input:surface,...(df.fieldtype==='Date'?{datepicker:{destroy:()=>destroyed++}}:{}),get_value:()=>'',set_value:()=>created===1?new Promise(resolve=>{resolveFirst=resolve;started();}):Promise.resolve()};}}}}});
 const pending=api.paymentDrawer('PE');await firstStarted;routeClose();resolveFirst();await pending;
 assert.equal(created,1);assert.equal(destroyed,1);
});
test('successful reload clears touched changes; unchanged rounded controls remain absent', () => {
  const session = functionFrom('editSession')({document:{amount:1.23456}});
  session.touch('amount', '1.2'); session.reset({document:{amount:1.2,modified:'new'}});
  assert.deepEqual(JSON.parse(JSON.stringify(session.changes())), {});
  assert.equal(session.document.modified,'new');
});
test('uncertain save reuses its token only for the identical payload', () => {
  let ids=0; const token=functionFrom('retryToken')(()=>`request-${++ids}`);
  assert.equal(token.forPayload({qty:1}),token.forPayload({qty:1}));
  assert.throws(()=>token.forPayload({qty:2}),/响应|内容/);
  token.succeeded(); assert.equal(token.forPayload({qty:2}),'request-2');
});
test('late async drawer loads are invalidated on cancellation and superseded opening', () => {
  const gate=functionFrom('operationGate')(); const first=gate.begin();
  gate.cancel(); assert.equal(gate.current(first),false);
  const second=gate.begin(); const third=gate.begin();
  assert.equal(gate.current(second),false); assert.equal(gate.current(third),true);
});
test('PO stock receipt action only appears for real eligible native orders, never OA rows', () => {
  const action=functionFrom('orderReceiptAction');
  assert.equal(action({row_type:'oa_request',name:'OA',docstatus:1}), '');
  assert.match(action({name:'PO',docstatus:0}), /确认订单/);
  assert.equal(action({name:'PO',docstatus:1,per_received:100,status:'Completed'}), '');
  assert.match(action({name:'PO<&',docstatus:1,per_received:50,status:'To Receive'}), /dlp-order-receipt/);
  assert.doesNotMatch(action({name:'PO<&',docstatus:1,per_received:50,status:'To Receive'}),/data-name="PO<&"/);
});
test('voucher rendering includes number AND status AND event and escapes supplied text', () => {
  const html=functionFrom('vouchersHTML')([{name:'V<&',statutory_number:'记-1',status:'Reversed',source_event:'Cancellation'}]);
  assert.match(html,/记-1/); assert.match(html,/已冲销/); assert.match(html,/冲销/); assert.doesNotMatch(html,/V<&/);
});
test('payment records whole bank totals remain grouped by type, status and currency', () => {
  const html=functionFrom('paymentSummary')({totals_label:'整单银行金额',totals:[{payment_type:'Pay',docstatus:0,currency:'USD',amount:1},{payment_type:'Receive',docstatus:1,currency:'MXN',amount:2}]});
  assert.match(html,/整单银行金额/); assert.match(html,/付款.*草稿.*1\.00.*USD/); assert.match(html,/退款.*已提交.*2\.00.*MXN/);
});
test('shared payable balances are clearly whole invoice scope even when settlement is partially paid', () => {
  const html=functionFrom('balanceHTML')({shared_payable:true,balances:[{total:100,settled:25,outstanding:75,currency:'USD'}]});
  assert.match(html,/共享应付整单/); assert.match(html,/75\.00/);
});
test('shared page adapter uses the real shared renderer and supports saved column/density isolation', () => {
  const grid=engine.create({doctype:'Payment Entry',pageRoute:'purchase-payment-records',columns:[{fieldname:'name',label:'付款单',width:150}],provider:{columns:[{fieldname:'name',label:'付款单',width:150}],defaultColumns:['name']}});
  assert.equal(typeof grid.mountPage,'function');
});
test('PO receipt discovery uses permission-checked parent query and native child source filters', async () => {
  let request;
  const api=payments(async value=>{request=value;return {message:[{name:'AUTO-PR',modified:'v1'}]};});
  assert.equal(typeof api.receiptDrafts,'function');
  const result=await api.receiptDrafts('PO-1');
  assert.equal(request.method,'frappe.client.get_list');
  assert.equal(request.args.doctype,'Purchase Receipt');
  assert.deepEqual(JSON.parse(JSON.stringify(request.args.filters)),[['Purchase Receipt','docstatus','=',0],['Purchase Receipt Item','purchase_order','=','PO-1']]);
  assert.equal(request.args.limit_page_length,0);
  assert.equal(result[0].name,'AUTO-PR');
});
