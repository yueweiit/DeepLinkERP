const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Only DOM/transport boundaries are simulated. Numeric parse, validation,
// get_value, native change binding and formatting run the pinned Frappe source.
class Surface {
 constructor(value='', parent=null) { this.value=value; this.parent=parent; this.children=[]; this.events=[]; this.capture=[]; this.textValue=''; this.node={addEventListener:(type,fn)=>this.capture.push({type,fn}),removeEventListener:(type,fn)=>this.capture=this.capture.filter(e=>e.type!==type||e.fn!==fn)};this[0]=this.node; }
 appendTo(parent){this.parent=parent;parent?.children?.push(this);return this;}
 find(selector){this.found??=new Map();if(!this.found.has(selector))this.found.set(selector,new Surface('',this));return this.found.get(selector);}
 html(value){if(value!==undefined)this.textValue=value;return this;}
 text(value){this.textValue=value;return this;}
 on(types,fn){for(const type of types.split(' '))this.events.push({type,fn});return this;}
 off(names){const tokens=names.split(' ');this.events=this.events.filter(e=>!tokens.some(n=>n.startsWith('.')?e.type.includes(n):e.type===n));return this;}
 get(){return this.node;}
 val(value){if(arguments.length)this.value=value;return this.value;}
 trigger(){return this;}toggleClass(){return this;}attr(){return this;}prop(key,value){this.props??={};this.props[key]=value;return this;}remove(){this.removed=true;this.removals=(this.removals||0)+1;return this;}
 async emit(type,value){if(value!==undefined)this.value=value;const event={type,target:this.node};for(const e of this.capture.filter(e=>e.type===type))e.fn(event);for(const e of this.events.filter(e=>e.type.split('.')[0]===type))await e.fn(event);await new Promise(resolve=>setImmediate(resolve));}
}
function projection(doctype='Purchase Invoice') {return {document:{doctype,name:null,docstatus:0,modified:'v1',company:'C',supplier:'S',currency:'USD',payment_type:'Pay',amount:100.1234,items:doctype==='Payment Entry'?[]:[{key:'ITEM',item_code:'I',item_name:'Native',qty:1.234567,rate:9.87654,max_qty:10,uom:'个',warehouse:'W'}],references:[]},editable_fields:doctype==='Payment Entry'?['amount']:[],editable_item_fields:doctype==='Payment Entry'?[]:['qty','rate'],allowed_actions:[]};}
function harness({document=projection(), drafts=[], precision, floatPrecision=3, locale='#.###,##', metadata=()=>Promise.resolve(), missingField,submit=async()=>document,chain={can_create:true,company:'C',supplier:'S',balances:[],invoices:[{name:'PI',can_pay:true,outstanding:100,currency:'USD'}]}}={}) {
 const surfaces=[],controls=[],requests=[],loaded=[],listeners={},confirms=[];
 const $=value=>{const surface=new Surface(value);surfaces.push(surface);return surface;};
 const fields={qty:{fieldname:'qty',fieldtype:'Float',...(precision?{precision}:{})},rate:{fieldname:'rate',fieldtype:'Currency',options:'currency',...(precision?{precision}:{})},paid_amount:{fieldname:'paid_amount',fieldtype:'Currency',options:'paid_from_account_currency',...(precision?{precision}:{})},received_amount:{fieldname:'received_amount',fieldtype:'Currency',options:'paid_to_account_currency'}};
 const host={$,window:null,console,document:{body:new Surface(),addEventListener(){},removeEventListener(){}},crypto:{randomUUID:()=> 'uuid'},locals:{},__:v=>v,cint:(value,fallback=0)=>Number.isNaN(parseInt(value,10))?fallback:parseInt(value,10),replace_all:(value,from,to)=>value.split(from).join(to),is_null:v=>v==null,
  frappe:{ui:{form:{}},provide(){},utils:{debounce:fn=>fn},boot:{sysdefaults:{float_precision:floatPrecision,currency_precision:2,number_format:locale}},defaults:{get_default:key=>key==='float_precision'?floatPrecision:undefined},meta:{get_docfield:(doctype,field)=>field===missingField?undefined:({...fields[field],fieldname:field,parent:doctype,fieldtype:fields[field]?.fieldtype||'Data'}),get_field_currency:(df,doc)=>doc[df.options]},model:{with_doctype:async doctype=>{loaded.push(doctype);await metadata(doctype);},get_value:()=>undefined},router:{on:(type,fn)=>listeners[type]=fn},datetime:{get_today:()=> '2026-10-04'},confirm:(_,fn)=>confirms.push(fn),show_alert(){},run_serially:fns=>{let result;for(const fn of fns)result=fn();return Promise.resolve(result);},call:async request=>{requests.push(request);if(request.method==='frappe.client.get_list')return {message:drafts};if(request.method.endsWith('.get_purchase_chain'))return {message:chain};if(request.method.endsWith('.create_payment_draft'))return {message:{name:'PE'}};if(request.method.endsWith('.submit_document'))return {message:await submit(request.args)};return {message:document};}}
 };
 host.window=host;host.globalThis=host;
 const context=vm.createContext(host);
 for(const file of ['frappe-native-number-format.js','frappe-native-number-controls.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'fixtures',file),'utf8'),context);
 host.frappe.ui.form.make_control=({df})=>{
  const Type=host.frappe.ui.form[`Control${df.fieldtype}`]||host.frappe.ui.form.ControlData;
  const control=Object.create(Type.prototype);Object.assign(control,{df:{...df},doc:{},$input:new Surface(),get_status:()=>df.read_only?'Read':'Write',set_disp_area(){},in_grid:()=>false});
  control.bind_change_event();controls.push(control);return control;
 };
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../deeplinkerp_branding/public/js/purchase_payments.js'),'utf8'),context);
 const click=async selector=>{const button=surfaces.findLast(s=>typeof s.value==='string'&&s.value.includes(` ${selector}`));assert.ok(button,`button ${selector}`);await button.emit('click');};
 const html=()=>{const visit=s=>s.textValue+[...(s.found?.values()||[])].map(visit).join('');return surfaces.map(visit).join('');};
 return {api:host.DeepLinkERPPurchasePayments,host,controls,requests,loaded,surfaces,confirms,click,html,confirm:()=>confirms.shift()(),routeClose:()=>listeners.change()};
}

test('one native parent with multiple PO item joins resumes its unique receipt draft',async()=>{
 const h=harness({document:projection('Purchase Receipt'),drafts:[{name:'PR-ONE',modified:'v2'},{name:'PR-ONE',modified:'v2'}]});
 await h.api.documentDrawer('Purchase Order','PO','Purchase Receipt');
 const previews=h.requests.filter(r=>r.method.endsWith('.preview_document'));
 assert.equal(previews.length,1);assert.equal(previews[0].args.target_name,'PR-ONE');
 assert.equal(h.requests[0].args.distinct,undefined,'do not invent unsupported native get_list options');
 assert.doesNotMatch(h.html(),/已有 2 张/);
});
test('multiple unique native receipt drafts keep sorted unique choices without guessing or previewing',async()=>{
 const h=harness({drafts:[{name:'PR-NEW',modified:'v2'},{name:'PR-NEW',modified:'v2'},{name:'PR-OLD',modified:'v1'}]});
 await h.api.documentDrawer('Purchase Order','PO','Purchase Receipt');
 assert.equal(h.requests.length,1);
 const html=h.html();assert.match(html,/已有 2 张/);assert.equal((html.match(/data-target="PR-NEW"/g)||[]).length,1);assert.ok(html.indexOf('data-target="PR-NEW"')<html.indexOf('data-target="PR-OLD"'));
});
test('native default Float precision3 accepts qty0.004 while drawer display is only2',async()=>{
 const h=harness();await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');
 const qty=h.controls.find(c=>c.df.fieldname==='qty');await qty.$input.emit('change','0,004');
 assert.equal(qty.value,0.004,'native change stores the native precision, not presentation precision');
 assert.equal(qty.$input.val(),'0,00');
 await h.click('dlp-save');
 assert.equal(h.requests.find(r=>r.method.endsWith('.save_document_draft')).args.changes.items[0].qty,0.004);
 assert.deepEqual(h.loaded,['Purchase Invoice']);
});
test('explicit native metadata precision6 preserves changed qty and rate before native change reformats the input',async()=>{
 const document=projection();document.document.items[0].rate=8.1234;
 const h=harness({document,precision:6});await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');
 const qty=h.controls.find(c=>c.df.fieldname==='qty'),rate=h.controls.find(c=>c.df.fieldname==='rate');
 await qty.$input.emit('input','1,234');await qty.$input.emit('change');await rate.$input.emit('change','9,87654');
 assert.equal(qty.value,1.234);assert.equal(rate.value,9.87654);assert.equal(qty.$input.val(),'1,23');assert.equal(rate.$input.val(),'9,88');
 await h.click('dlp-save');
 assert.deepEqual(JSON.parse(JSON.stringify(h.requests.find(r=>r.method.endsWith('.save_document_draft')).args.changes)),{items:[{key:'ITEM',qty:1.234,rate:9.87654}]});
});
test('native default Currency precision2 remains2 for actual payment edits, never upgraded to6',async()=>{
 const h=harness({document:projection('Payment Entry')});await h.api.paymentDrawer('PE');
 const amount=h.controls.find(c=>c.df.fieldname==='amount');await amount.$input.emit('change','9,87654');await h.click('dlp-save');
 assert.equal(h.requests.find(r=>r.method.endsWith('.update_payment_draft')).args.changes.amount,9.88);
});
test('metadata loading is awaited and close invalidates it before any control creation',async()=>{
 let resolve,started;const waiting=new Promise(r=>started=r);const h=harness({metadata:()=>{started();return new Promise(r=>resolve=r);}});
 const pending=h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');await Promise.race([waiting,new Promise(r=>setImmediate(r))]);assert.equal(typeof resolve,'function','native metadata must load before creating controls');h.routeClose();resolve();await pending;
 assert.equal(h.controls.length,0);
});
test('missing native metadata is a visible safe failure, not invented numeric precision',async()=>{
 const h=harness({missingField:'qty'});await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');
 assert.ok(!h.controls.some(c=>c.df.fieldname==='qty'));
 assert.match(h.html(),/元数据/);
});
test('numeric capture listeners belong to the drawer instance and are removed on route close',async()=>{
 const h=harness();await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');const qty=h.controls.find(c=>c.df.fieldname==='qty');
 assert.equal(qty.$input.capture.length,2);h.routeClose();assert.equal(qty.$input.capture.length,0);
});
test('untouched controls never send their rounded native initialization values to document save',async()=>{
 const h=harness();await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');await h.click('dlp-save');
 assert.deepEqual(JSON.parse(JSON.stringify(h.requests.find(r=>r.method.endsWith('.save_document_draft')).args.changes)),{});
});
for(const [precision,expected] of [[undefined,9.88],[6,9.87654]])test(`payment creation keeps captured native amount precision ${precision||'default2'} after native change formatting`,async()=>{
 const h=harness({precision});await h.api.pay('Purchase Receipt','PR');
 const amount=h.controls.find(c=>c.df.fieldname==='amount'),bank=h.controls.find(c=>c.df.fieldname==='bank');
 await amount.$input.emit('change','9,87654');await bank.set_value('Bank');assert.equal(amount.$input.val(),'9,88');await h.click('dlp-create');
 assert.equal(h.requests.find(r=>r.method.endsWith('.create_payment_draft')).args.amount_to_pay,expected);
 assert.deepEqual(h.loaded,['Payment Entry']);assert.equal(amount.$input.capture.length,0,'successful close releases own capture listeners');
});
for(const action of ['pay','paymentDrawer'])test(`${action} cannot create controls after awaited metadata completes on a closed route`,async()=>{
 let resolve;const h=harness({document:projection('Payment Entry'),metadata:()=>new Promise(r=>resolve=r)});
 const pending=h.api[action]('Purchase Receipt','PR');await new Promise(r=>setImmediate(r));assert.equal(typeof resolve,'function');h.routeClose();resolve();await pending;assert.equal(h.controls.length,0);
});
test('metadata load rejection remains visible and creates no controls',async()=>{
 const h=harness({metadata:async()=>{throw new Error('network unavailable');}});await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');assert.equal(h.controls.length,0);assert.match(h.html(),/元数据/);assert.doesNotMatch(h.html(),/network unavailable/);
});
for(const doctype of ['Purchase Invoice','Payment Entry'])for(const dirty of [false,true])test(`${doctype} ${dirty?'confirmed dirty':'unchanged'} refresh metadata rejection is visible and restores buttons without losing the old session`,async()=>{
 let loads=0;const h=harness({document:projection(doctype),metadata:async()=>{if(++loads>1)throw new Error('private network message');}});
 if(doctype==='Payment Entry')await h.api.paymentDrawer('PE');else await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');
 const control=h.controls.find(c=>c.df.fieldname===(doctype==='Payment Entry'?'amount':'qty'));
 if(dirty)await control.$input.emit('change',doctype==='Payment Entry'?'19,87':'1,234');
 await assert.doesNotReject(()=>h.click('dlp-reload'));
 if(dirty)await assert.doesNotReject(()=>h.confirm());
 assert.match(h.html(),/元数据/);assert.doesNotMatch(h.html(),/private network message/);
 assert.equal(h.surfaces[0].find('button').props.disabled,false);
 assert.ok(!h.requests.some(r=>/save_document_draft|update_payment_draft|submit_document/.test(r.method)),'refresh must not write');
 await h.click('dlp-save');const changes=h.requests.find(r=>/save_document_draft|update_payment_draft/.test(r.method)).args.changes;
 assert.deepEqual(JSON.parse(JSON.stringify(changes)),!dirty?{}:doctype==='Payment Entry'?{amount:19.87}:{items:[{key:'ITEM',qty:1.234}]});
});
test('late refresh metadata rejection after close cannot re-enable or append to a removed drawer',async()=>{
 let loads=0,reject;const h=harness({metadata:()=>++loads===1?Promise.resolve():new Promise((_,r)=>reject=r)});
 await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice');const before=h.controls.length;
 const pending=h.click('dlp-reload');await new Promise(r=>setImmediate(r));assert.equal(typeof reject,'function');h.routeClose();const closedHTML=h.html();reject(new Error('network'));
 await assert.doesNotReject(()=>pending);assert.equal(h.controls.length,before);assert.equal(h.surfaces[0].removed,true);assert.equal(h.html(),closedHTML);assert.ok(h.controls.every(c=>c.$input.capture.length===0));
});
for(const doctype of ['Purchase Invoice','Payment Entry'])test(`${doctype} submit success followed by metadata refresh failure reports completed operation, not failed submit`,async()=>{
 let loads=0;const document=projection(doctype);document.document.name='DRAFT';document.allowed_actions=['Submit'];
 const h=harness({document,metadata:async()=>{if(++loads>1)throw new Error('private network failure');}});
 if(doctype==='Payment Entry')await h.api.paymentDrawer('DRAFT');else await h.api.documentDrawer('Purchase Receipt','PR','Purchase Invoice','DRAFT');
 await h.click('dlp-submit');await h.confirm();assert.equal(h.requests.filter(r=>r.method.endsWith('.submit_document')).length,1);
 assert.match(h.html(),/原生操作已完成.*刷新.*失败/);assert.doesNotMatch(h.html(),/提交未完成|private network failure/);
 assert.equal(h.surfaces[0].find('button').props.disabled,false,'refresh and close become usable');
});
test('successful native submit disables stale save/submit handlers until a fresh projection arrives',async()=>{
 let loads=0;const document=projection('Payment Entry');document.document.name='PE';document.allowed_actions=['Submit'];
 const h=harness({document,metadata:async()=>{if(++loads>1)throw new Error('network');}});await h.api.paymentDrawer('PE');
 await h.click('dlp-submit');await h.confirm();await h.click('dlp-submit');if(h.confirms.length)await h.confirm();await h.click('dlp-save');
 assert.equal(h.requests.filter(r=>r.method.endsWith('.submit_document')).length,1);assert.equal(h.requests.filter(r=>r.method.endsWith('.update_payment_draft')).length,0);
 assert.equal(h.surfaces[0].find('footer').find('.dlp-save,.dlp-submit').removals,1,'native write removes the old actionable buttons');
});
test('native submit RPC failure remains visibly not completed and never automatically retries',async()=>{
 const document=projection('Payment Entry');document.document.name='PE';document.allowed_actions=['Submit'];const h=harness({document,submit:async()=>{throw new Error('permission denied');}});await h.api.paymentDrawer('PE');await h.click('dlp-submit');await h.confirm();
 assert.match(h.html(),/提交未完成/);assert.doesNotMatch(h.html(),/原生操作已完成/);assert.equal(h.requests.filter(r=>r.method.endsWith('.submit_document')).length,1);assert.equal(h.loaded.length,1);assert.equal(h.surfaces[0].find('button').props.disabled,false);
});
test('submit success then delayed refresh failure on a closed route cannot append an incorrect result',async()=>{
 let loads=0,reject;const document=projection('Payment Entry');document.document.name='PE';document.allowed_actions=['Submit'];const h=harness({document,metadata:()=>++loads===1?Promise.resolve():new Promise((_,r)=>reject=r)});await h.api.paymentDrawer('PE');await h.click('dlp-submit');const pending=h.confirm();await new Promise(r=>setImmediate(r));h.routeClose();const closedHTML=h.html();reject(new Error('network'));await pending;
 assert.equal(h.html(),closedHTML);assert.equal(h.requests.filter(r=>r.method.endsWith('.submit_document')).length,1);assert.equal(h.surfaces[0].removed,true);
});
