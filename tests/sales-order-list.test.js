const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const grid = require("../deeplinkerp_branding/public/js/sales_order_list.js");

test("sales search uses CRM and ERP identities without treating ODT as a contract", () => {
 const allowed = new Set(["name","custom_crm_order_no","customer_name","custom_odt"]);
 const query = grid.buildQuery({fields:["name"],filters:[],or_filters:[]}, {search:"CRM-001"}, allowed);
 assert.deepEqual(query.or_filters.map(f => f[1]), [...allowed]);
 assert.ok(!query.or_filters.some(f => f[1] === "po_no"));
});

test("mine and finance scopes remain inside native filters and never include cancelled workflow states", () => {
 global.frappe = {session:{user:"finance@example.test"}};
 const base={filters:[["Sales Order","company","=","MX"]]};
 const args=grid.transformQuery(base,{salesView:"finance",allowed:new Set(["custom_process_status"]),quick:{}});
 assert.equal(args.filters[0][3],"MX");
 assert.deepEqual(args.filters[1][3],["Pending Deposit Confirmation","Deposit Confirmation Processing"]);
 assert.deepEqual(args.filters.slice(2),[['Sales Order','docstatus','=',1],['Sales Order','status','not in',['Closed','Cancelled','Stopped','On Hold']]]);
});

test("detail output escapes source text and only renders permission-filtered item fields", () => {
 const html=grid.detailsHTML({header:{name:'SO-1',currency:'MXN',customer_name:'<img src=x onerror=bad()>'},item_fields:["item_code","qty","uom"],items:[{item_code:'<script>bad()</script>',qty:0,uom:'件',rate:98765}],attachments:[{file_url:'javascript:bad()',file_name:'bad'}]});
 assert.ok(html.includes('&lt;img'));
 assert.ok(html.includes('&lt;script&gt;'));
 assert.ok(!html.includes('98765'));
 assert.ok(!html.includes('javascript:bad'));
 assert.ok(html.includes('0 件'));
});

test("multi-item currency and unit summaries are not presented as one price or invented total unit", () => {
 const render=grid.renderValue;
 assert.equal(render("dlp_quantity",{dlp_multiple_units:true},{translate:x=>x}),"多单位明细");
 assert.equal(render("dlp_rate",{dlp_item_count:3,dlp_rate:999,currency:"MXN"},{translate:x=>x}),"多明细");
});

test("sales presets retain an explicit details action and ERP account identity fields", () => {
 for(const columns of Object.values(grid.presets)) assert.ok(columns.includes("dlp_actions"));
 assert.ok(grid.presets.tail.includes("owner"));
 assert.ok(grid.presets.middle.includes("dlp_sales_person"));
 assert.ok(!grid.COLUMNS.some(c=>/deposit_required|deposit_difference/.test(c.fieldname)));
});

test('default finance columns show approval while delivery status stays optional',()=>{
 assert.ok(!grid.presets.main.includes('status'));
 assert.deepEqual(grid.presets.finance,['name','customer_name','custom_process_status','grand_total','dlp_receipts','dlp_last_confirmation','dlp_actions']);
 assert.ok(grid.presets.main.includes('custom_process_status'));
 const query=grid.buildQuery({filters:[['Sales Order','status','=','Closed'],['Sales Order','custom_process_status','=','Pending Production']],or_filters:[]},{},new Set(['status','custom_process_status']));
 assert.deepEqual(query.filters,[['Sales Order','status','=','Closed'],['Sales Order','custom_process_status','=','Pending Production']]);
});

test('old sales column preferences remove delivery status once without discarding order or density',()=>{
 const allowed=new Set(grid.COLUMNS.map(col=>col.fieldname));
 const upgraded=grid.normalizePreferences({version:2,density:'standard',columns:['name','customer_name','custom_process_status','status','grand_total']},allowed);
 assert.deepEqual(upgraded.columns,['name','customer_name','custom_process_status','grand_total']);
 assert.equal(upgraded.density,'standard');
 const hidden=grid.normalizePreferences({...upgraded,columns:['name','customer_name']},allowed);
 assert.deepEqual(hidden.columns,['name','customer_name'],'a deliberate hide after the upgrade remains respected');
});

test('financial grouping uses process state rather than release permission and unknown states show a dash',()=>{
 for(const raw of ['Pending Deposit Confirmation','Deposit Confirmation Processing']) assert.equal(grid.financialLabel(raw),'待财务审核');
 for(const raw of ['Pending Production','Pending Final Payment','Deliverable','Partially Delivered','Completed']) assert.equal(grid.financialLabel(raw),'已放行生产');
 assert.equal(grid.financialLabel('Rejected'),'已驳回');
 for(const raw of ['Pending Confirmation','Draft','Closed','Cancelled',undefined]) assert.equal(grid.financialLabel(raw),'—');
 assert.match(grid.renderValue('custom_process_status',{custom_process_status:'Pending Production',dlp_finance:{can_release:false}},{translate:x=>x}),/已放行生产/);
});

test('sync warnings stay supplemental to approval and permission denial is never a sync failure',()=>{
 const render=(field,doc)=>grid.renderValue(field,doc,{translate:x=>x});
 const processing={custom_process_status:'Deposit Confirmation Processing',dlp_finance:{can_release:false,process_status:'Deposit Confirmation Processing',last_confirmation:{user:'finance',creation:'today',status:'Processing'}}};
 assert.match(render('custom_process_status',processing),/待财务审核/);
 assert.match(render('dlp_last_confirmation',processing),/finance.*today.*CRM\/MES 同步中/s);
 const failed={custom_process_status:'Pending Deposit Confirmation',dlp_finance:{can_release:false,last_confirmation:{user:'finance',creation:'today',status:'Failed'}}};
 assert.match(render('dlp_last_confirmation',failed),/CRM\/MES 同步失败/);
 assert.match(render('dlp_sync',failed),/CRM\/MES 同步失败/);
 const denied={custom_process_status:'Pending Production',dlp_finance:{can_release:false,reason:'no permission'}};
 assert.equal(render('dlp_last_confirmation',denied),'—');assert.equal(render('dlp_sync',denied),'—');
});

test('financial filters preserve raw native filters and missing source permission yields no rows',()=>{
 const native=['Sales Order','company','=','MX'];
 const controller={salesView:'finance',allowed:new Set(['custom_process_status']),quick:{financial_status:'approved'},list:{clear_checked_items(){}},salesExpanded:new Map()};
 const query=grid.transformQuery({filters:[native]},controller);
 assert.equal(controller.salesView,'all');
 assert.deepEqual(query.filters,[native,['Sales Order','custom_process_status','in',['Pending Production','Pending Final Payment','Deliverable','Partially Delivered','Completed']]]);
 const denied=grid.transformQuery({filters:[]},{salesView:'finance',allowed:new Set(),quick:{}});
 assert.deepEqual(denied.filters,[['Sales Order','name','in',[]]]);
});

test('mounted configuration defaults to finance without resetting saved columns',()=>{
 const f=mountedReleaseFixture();
 f.config.mountControls(f.controller);
 assert.equal(f.controller.salesView,'finance');
 assert.deepEqual(Array.from(f.config.defaultColumns),grid.presets.finance);
 assert.equal(f.config.preferenceVersion,3);
 const control=f.config.controls.find(control=>control.fieldname==='financial_status');
 assert.equal(control.permission_field,'custom_process_status');
 assert.deepEqual(JSON.parse(JSON.stringify(f.grid.selectOptions(control,null,x=>x))),[{value:'',label:'全部审核状态'},{value:'pending',label:'待财务审核'},{value:'approved',label:'已放行生产'},{value:'rejected',label:'已驳回'}]);
 assert.ok(!f.config.controls.some(control=>['status','custom_process_status'].includes(control.fieldname)));
 const css=fs.readFileSync(require.resolve('../deeplinkerp_branding/public/css/sales_order_list.css'),'utf8');
 assert.match(css,/body\.dlp-sales-order-grid-active\s+\.dlp-po-filter\[data-fieldname=financial_status\]\{width:220px\}/);
});

test('finance reviews supplement all orders when financial columns are visible and ignore stale reviews',async()=>{
 const f=mountedReleaseFixture();f.controller.salesView='all';f.controller.preferences.columns=['name','dlp_receipts'];
 const pending=f.config.onRows(f.controller);
 f.reads[0].resolve({message:{'SO-A':{dlp_product:'Current product'}}});
 await new Promise(setImmediate);
 assert.match(f.reads[1].request.method,/get_finance_release_review$/);
 f.controller.requestId++;
 f.reads[1].resolve({message:{orders:[{name:'SO-A',process_status:'Deposit Confirmation Processing',last_confirmation:{status:'Failed'},receipts:[{name:'stale'}]}]}});await pending;
 assert.equal(f.list.data[0].dlp_finance,undefined);
 assert.equal(f.grid.renderValue('dlp_last_confirmation',f.list.data[0],{translate:x=>x}),'—');
});

test('departed finance list ignores a late supplemental network error',async()=>{
 const f=mountedReleaseFixture();const notices=[];f.controller.$salesNotice={text:value=>notices.push(value)};
 const pending=f.config.onRows(f.controller);
 f.setRoute(['List','Purchase Order','List']);f.config.onRouteChange(f.controller,false);
 f.reads[0].reject(new Error('late offline'));await pending;
 assert.deepEqual(notices,[]);
});

test('real column changes load missing financial detail once and discard stale enrichment',async()=>{
 const f=mountedReleaseFixture();f.controller.salesView='all';f.list.get_checked_items=()=>[];
 f.controller.preferences.columns=['name'];
 const first=f.controller.setColumns(['name','dlp_receipts']);
 assert.match(f.reads[0].request.method,/get_sales_display_details$/);
 const duplicate=f.controller.setColumns(['name','dlp_receipts','dlp_last_confirmation']);
 assert.equal(f.reads.length,1);
 f.reads[0].resolve({message:{}});await new Promise(setImmediate);
 f.reads[1].resolve({message:{orders:[{name:'SO-A',receipts:[{name:'PAY-1'}],last_confirmation:{user:'finance',creation:'today',status:'Success'}}]}});
 await first;await duplicate;
 assert.equal(f.list.data[0].dlp_finance.receipts[0].name,'PAY-1');
 await f.controller.setColumns(['name','dlp_last_confirmation']);assert.equal(f.reads.length,2);
 delete f.list.data[0].dlp_finance;
 const stale=f.controller.setColumns(['name','dlp_receipts']);
 f.reads[2].resolve({message:{}});await new Promise(setImmediate);
 f.controller.requestId++;
 f.reads[3].resolve({message:{orders:[{name:'SO-A',last_confirmation:{status:'Failed'}}]}});await stale;
 assert.equal(f.list.data[0].dlp_finance,undefined);
});

test('missing source permission keeps selected release actions disabled without sending review requests',async()=>{
 const f=releaseSelectionFixture();f.controller.allowed=new Set(['name']);f.controller.list.data=[{name:'denied'}];
 await grid.updateReleaseSelection(f.controller);
 assert.equal(f.reads.length,0);assert.equal(f.button().disabled,true);assert.match(f.summary().label,/无权/);
});

test('Sales export transforms match the selected order and translate only financial process cells',()=>{
 const f=mountedReleaseFixture();
 const options=f.config.exportOptions({fields:['grand_total','custom_process_status','name']});
 assert.deepEqual(Object.keys(options.columnTransforms),['3']);
 assert.equal(options.columnTransforms[3].header,'财务审核状态');
 assert.equal(options.columnTransforms[3].value('Completed'),'已放行生产');
 assert.equal(options.columnTransforms[3].value('Cancelled'),'—');
 assert.deepEqual(Object.keys(f.config.exportOptions({fields:['name','grand_total']}).columnTransforms),[]);
});

test('native Select options have explicit empty labels and retain raw status values after refresh',()=>{
 assert.equal(typeof grid.selectOptions,'function');
 const options=grid.selectOptions({fieldname:'custom_process_status',emptyLabel:'全部业务状态'},{options:'\nPending Deposit Confirmation\nPending Production'},x=>x);
 assert.deepEqual(options,[{value:'',label:'全部业务状态'},{value:'Pending Deposit Confirmation',label:'待财务放行'},{value:'Pending Production',label:'生产已放行'}]);
 const status=grid.selectOptions({fieldname:'status',emptyLabel:'全部订单状态'},{options:'\nDraft\nTo Deliver and Bill\nClosed'},x=>x);
 assert.deepEqual(status,[{value:'',label:'全部订单状态'},{value:'Draft',label:'草稿'},{value:'To Deliver and Bill',label:'待交付及开票'},{value:'Closed',label:'已关闭'}]);
});

function releaseSelectionFixture() {
 const reads=[],nodes=new Map(),controller={requestId:1,list:{data:[],get_checked_items(){return this.data;}}};
 controller.root={frappe:{get_route:()=>['List','Sales Order','List'],call:request=>new Promise((resolve,reject)=>reads.push({request,resolve,reject}))}};
 controller.$salesViewbar={find(selector){if(!nodes.has(selector))nodes.set(selector,{text(value){this.label=value;return this;},prop(key,value){this[key]=value;return this;}});return nodes.get(selector);}};
 return {controller,reads,button:()=>nodes.get('.dlp-sales-release'),summary:()=>nodes.get('.dlp-sales-selected')};
}

test('release action stays disabled until authoritative review and excludes released or unauthorized rows',async()=>{
 assert.equal(typeof grid.updateReleaseSelection,'function');
 const f=releaseSelectionFixture();f.controller.list.data=[{name:'released'},{name:'pending'},{name:'denied'}];
 const pending=grid.updateReleaseSelection(f.controller);
 assert.equal(f.button().disabled,true);
 assert.equal(f.reads[0].request.method,'crm_integration.crm_integration.finance_release.get_finance_release_review');
 f.reads[0].resolve({message:{orders:[{name:'released',can_release:false,process_status:'Pending Production'},{name:'pending',can_release:true},{name:'denied',can_release:false,reason:'no permission'},{name:'foreign',can_release:true}]}});
 await pending;
 assert.deepEqual(f.controller.salesReleaseNames,['pending']);
 assert.equal(f.button().disabled,false);assert.match(f.button().label,/1单/);assert.match(f.summary().label,/3.*1.*2/);
 await grid.updateReleaseSelection(f.controller);assert.equal(f.reads.length,1,'repeat rendering does not repeat the unchanged review');
});

test('all released and incomplete or failed review responses never enable production',async()=>{
 assert.equal(typeof grid.updateReleaseSelection,'function');
 for(const response of [{message:{orders:[{name:'A',can_release:false,process_status:'Pending Production'}]}},{message:{orders:[]}},new Error('offline')]){
  const f=releaseSelectionFixture();f.controller.list.data=[{name:'A'}];const pending=grid.updateReleaseSelection(f.controller);
  if(response instanceof Error)f.reads[0].reject(response);else f.reads[0].resolve(response);
  await pending;assert.equal(f.button().disabled,true);assert.deepEqual(f.controller.salesReleaseNames,[]);
 }
});

test('an old review cannot enable a changed selection or a refreshed order',async()=>{
 assert.equal(typeof grid.updateReleaseSelection,'function');
 const f=releaseSelectionFixture();f.controller.list.data=[{name:'A',modified:'old'}];const older=grid.updateReleaseSelection(f.controller);
 f.controller.list.data=[{name:'A',modified:'new'}];f.controller.requestId++;const newer=grid.updateReleaseSelection(f.controller);
 f.reads[1].resolve({message:{orders:[{name:'A',can_release:false}]}});await newer;
 f.reads[0].resolve({message:{orders:[{name:'A',can_release:true}]}});await older;
 assert.equal(f.button().disabled,true);assert.deepEqual(f.controller.salesReleaseNames,[]);
 f.controller.list.data=[];await grid.updateReleaseSelection(f.controller);assert.match(f.summary().label,/未选择/);
});

function mountedReleaseFixture() {
 const engine=require('../deeplinkerp_branding/public/js/compact_list.js'),vm=require('node:vm');
 const f=releaseSelectionFixture();let config,route=['List','Sales Order','List'];
 const env={frappe:{...f.controller.root.frappe,get_route:()=>route,model:{std_fields_list:['name','owner','docstatus']},perm:{has_perm:()=>true},session:{user:'qa'},boot:{sitename:'qa'}},DeepLinkERPCompactList:{...engine,create(value){config=value;return engine.create(value);}}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../deeplinkerp_branding/public/js/sales_order_list.js'),'utf8'),env);
 const list={doctype:'Sales Order',view_name:'List',view:'List',page:{},meta:{fields:grid.COLUMNS.map(col=>({fieldname:col.fieldname,permlevel:0}))},fields:[],data:[{name:'SO-A',modified:'old'}],settings:{},get_args:()=>({filters:[],or_filters:[]}),get_call_args(){return {args:this.get_args()};},no_change:()=>false,render_header(){},refresh(){},get_checked_items(){return this.data;},on_row_checked(){}};
 const controller=env.DeepLinkERPSalesWorkspace.mount(list,env);
 controller.$salesViewbar=f.controller.$salesViewbar;controller.salesExpanded=new Map();
 return {...f,controller,list,config,grid:env.DeepLinkERPSalesWorkspace,setRoute(value){route=value;}};
}

test('native dispatch invalidates release eligibility immediately and rejects an earlier response',async()=>{
 const f=mountedReleaseFixture(),older=f.grid.updateReleaseSelection(f.controller);
 f.list.no_change(f.list.get_call_args());
 f.reads[0].resolve({message:{orders:[{name:'SO-A',can_release:true}]}});await older;
 assert.equal(f.button().disabled,true);assert.equal(f.controller.salesReleaseNames.length,0);
 const current=f.grid.updateReleaseSelection(f.controller);
 f.reads[1].resolve({message:{orders:[{name:'SO-A',can_release:true}]}});await current;
 assert.equal(f.button().disabled,false);
 f.list.no_change(f.list.get_call_args());
 assert.equal(f.button().disabled,true,'already eligible selection is disabled at the real dispatch gate');
 assert.equal(f.controller.salesReleaseNames.length,0);
});

test('departed sales list ignores late display details without starting another release review',async()=>{
 const f=mountedReleaseFixture(),details=f.config.onRows(f.controller);
 assert.match(f.reads[0].request.method,/get_sales_display_details$/);
 f.setRoute(['List','Purchase Order','List']);f.config.onRouteChange(f.controller,false);
 f.reads[0].resolve({message:{'SO-A':{dlp_product:'Late product'}}});await details;
 assert.equal(f.reads.length,1,'late details must not render or re-start selection review');
 await f.grid.updateReleaseSelection(f.controller,true);
 assert.equal(f.reads.length,1);assert.equal(f.button().disabled,true);
 assert.equal(f.controller.salesReleaseNames.length,0);
});

test('review response verifies live selection even before the next selection callback runs',async()=>{
 const f=releaseSelectionFixture();f.controller.list.data=[{name:'A',modified:'old'}];
 const pending=grid.updateReleaseSelection(f.controller);f.controller.list.data=[{name:'B'}];
 f.reads[0].resolve({message:{orders:[{name:'A',can_release:true}]}});await pending;
 assert.equal(f.button().disabled,true);assert.deepEqual(f.controller.salesReleaseNames,[]);
});

test('empty and over-limit selections make no release-review request',async()=>{
 assert.equal(typeof grid.updateReleaseSelection,'function');
 const f=releaseSelectionFixture();await grid.updateReleaseSelection(f.controller);
 f.controller.list.data=Array.from({length:101},(_,i)=>({name:`SO-${i}`}));await grid.updateReleaseSelection(f.controller);
 assert.equal(f.reads.length,0);assert.equal(f.button().disabled,true);assert.deepEqual(f.controller.salesReleaseNames,[]);
});

test('native selection still updates bulk actions and select-all while sales field headers remain visible',()=>{
 const surface=()=>({visible:true,checked:false,indeterminate:false,toggle(value){this.visible=value;return this;},show(){this.visible=true;return this;},hide(){this.visible=false;return this;},find(){return this;},prop(key,value){this[key]=value;return this;}});
 const subject=surface(),actions=surface();let selected=0,nativeCalls=0;
 const list={doctype:'Sales Order',view_name:'List',view:'List',meta:{fields:grid.COLUMNS.map(col=>({fieldname:col.fieldname,permlevel:0}))},fields:[],data:[{name:'A'},{name:'B'}],settings:{},
  get_args:()=>({filters:[],or_filters:[]}),get_call_args(){return {args:this.get_args()};},render_header(){},refresh(){},
  on_row_checked(){nativeCalls++;this.$list_head_subject=subject;this.$checkbox_actions=actions;this.$checks={length:selected};subject.toggle(!selected);actions.toggle(Boolean(selected));this.bulkVisible=Boolean(selected);}};
 const root={frappe:{get_route:()=>['List','Sales Order','List'],model:{std_fields_list:['name','owner','docstatus']},perm:{has_perm:()=>true},session:{user:'test'},boot:{sitename:'qa'}}};
 grid.mount(list,root);
 for(selected of [1,2,0]){list.on_row_checked();assert.equal(subject.visible,true);assert.equal(actions.visible,false);assert.equal(list.bulkVisible,Boolean(selected));assert.equal(subject.checked,selected===2);assert.equal(subject.indeterminate,selected===1);}
 assert.equal(nativeCalls,3);
});

test("expanded detail cache expires when an order changes or disappears from the current result", () => {
 const controller={list:{data:[{name:"SO-1",modified:"new"}]},salesExpanded:new Map([["SO-1",{header:{modified:"old"}}],["SO-2",{header:{modified:"old"}}]])};
 grid.invalidateExpandedDetails(controller);
 assert.equal(controller.salesExpanded.size,0);
});

test("initial native onboarding closes once and later deliberate opening remains untouched", () => {
 let callback, button, clicks=0, disconnects=0;
 const previous={document:global.document,MutationObserver:global.MutationObserver,frappe:global.frappe};
 global.document={querySelector:()=>({querySelector:()=>button})};
 global.MutationObserver=class {constructor(fn){callback=fn;} observe(){} disconnect(){disconnects++;}};
 global.frappe={get_route:()=>["List","Sales Order","List"]};
 const controller={};
 try {
  grid.dismissAutomaticOnboarding(controller);
  assert.equal(clicks,0);
  button={click:()=>{clicks++;}}; callback();
  assert.equal(clicks,1); assert.equal(disconnects,1); assert.equal(controller.stopInitialOnboarding,null);
 } finally {Object.assign(global,previous);}
});

test("leaving sales before native onboarding arrives disconnects its scoped observer", () => {
 let callback, disconnects=0, route=["List","Sales Order","List"];
 const previous={document:global.document,MutationObserver:global.MutationObserver,frappe:global.frappe};
 global.document={querySelector:()=>({querySelector:()=>null})};
 global.MutationObserver=class {constructor(fn){callback=fn;} observe(){} disconnect(){disconnects++;}};
 global.frappe={get_route:()=>route};
 const controller={};
 try {
  grid.dismissAutomaticOnboarding(controller); route=["List","Purchase Order","List"]; callback();
  assert.equal(disconnects,1); assert.equal(controller.stopInitialOnboarding,null);
 } finally {Object.assign(global,previous);}
});

function viewportFixture() {
 const state={top:318.18,tail:75.5,header:32,height:720,scroll:0}, frames=new Map(), listeners=new Map(), observers=[];
 const values=new Map(), style={getPropertyValue:key=>values.get(key)||'',setProperty:(key,value)=>values.set(key,value),removeProperty:key=>values.delete(key)};
 const main={scrollTop:0,clientTop:0,get clientHeight(){return state.height;},getBoundingClientRect:()=>({top:0,bottom:state.height}),parentElement:null};
 const tableHeight=()=>Math.min(800,parseFloat(values.get('--dlp-sales-result-max-height'))||400);
 const list={scrollTop:0,parentElement:main,getBoundingClientRect:()=>({top:state.top-state.scroll-43,bottom:state.top-state.scroll+tableHeight()+state.tail})};
 const header={getBoundingClientRect:()=>({height:state.header})}, row={};
 const result={style,scrollTop:0,parentElement:list,get offsetHeight(){return tableHeight();},get clientHeight(){return tableHeight()-17;},getBoundingClientRect:()=>({top:state.top-state.scroll,bottom:state.top-state.scroll+tableHeight()}),querySelector:selector=>selector==='.dlp-po-grid-header'?header:row};
 const root={get innerHeight(){return state.height;},getComputedStyle:node=>({overflowY:node===main?'auto':'visible',minHeight:node===row?'42px':'0px',paddingBottom:'0px',marginBottom:'0px',borderBottomWidth:'0px'}),
  requestAnimationFrame:fn=>{const id=frames.size+1;frames.set(id,fn);return id;},cancelAnimationFrame:id=>frames.delete(id),
  addEventListener:(event,fn)=>listeners.set(event,fn),removeEventListener:(event,fn)=>{if(listeners.get(event)===fn)listeners.delete(event);},
  ResizeObserver:class {constructor(callback){this.callback=callback;this.targets=[];observers.push(this);}observe(node){this.targets.push(node);}disconnect(){this.disconnected=true;}}};
 const controller={root,list:{$result:{parent:()=>[result]},$frappe_list:[list],page:{wrapper:{find:()=>[{}]}}},$toolbar:[{}],$filters:[{parentElement:{}}],$summary:[{}],$paging:[{}],$salesViewbar:[{}],$salesNotice:[{}]};
 return {controller,state,main,result,list,header,row,root,values,frames,listeners,observers,flush(){const callbacks=[...frames.values()];frames.clear();callbacks.forEach(fn=>fn());}};
}

test('sales table reserves its measured footer and recalculates after wrapping, resize and existing outer scroll',()=>{
 const fixture=viewportFixture(),{controller,state,main,values,listeners,observers}=fixture;
 assert.equal(typeof grid.fitViewport,'function');grid.fitViewport(controller,true);fixture.flush();
 assert.equal(values.get('--dlp-sales-result-max-height'),'326px');
 state.scroll=73.5;main.scrollTop=73.5;observers[0].callback();fixture.flush();
 assert.equal(values.get('--dlp-sales-result-max-height'),'326px','outer scrolling must not make the table grow');
 state.height=860;state.top=400;state.tail=95;listeners.get('resize')();fixture.flush();
 assert.equal(values.get('--dlp-sales-result-max-height'),'365px');
 state.height=360;state.top=260;state.header=80;state.tail=75;observers[0].callback();fixture.flush();
 assert.equal(values.get('--dlp-sales-result-max-height'),'139px','short screens keep a header and row, with outer scrolling available');
});

test('sales viewport fitting cleans up on departure and resumes once on a cached route return',()=>{
 const fixture=viewportFixture(),{controller,values,frames,listeners,observers}=fixture;
 assert.equal(typeof grid.fitViewport,'function');grid.fitViewport(controller,true);grid.fitViewport(controller,true);
 assert.equal(observers.length,1);assert.equal(frames.size,1);fixture.flush();
 observers[0].callback();assert.equal(frames.size,1);grid.fitViewport(controller,false);
 assert.equal(frames.size,0);assert.equal(listeners.size,0);assert.equal(observers[0].disconnected,true);assert.equal(values.size,0);
 observers[0].callback();assert.equal(frames.size,0,'a delivered stale observer callback must stay inert');
 grid.fitViewport(controller,true);grid.fitViewport(controller,true);fixture.flush();
 assert.equal(observers.length,2);assert.equal(listeners.size,1);assert.equal(values.get('--dlp-sales-result-max-height'),'326px');
 grid.fitViewport(controller,false);
});

test('all four cached inventory pages share viewport fitting without stale loads reactivating departed owners',async()=>{
 const engine=require('../deeplinkerp_branding/public/js/compact_list.js'),inventory=require('../deeplinkerp_branding/public/js/inventory_detail.bundle.js');
 assert.equal(typeof engine.fitViewport,'function');
 const previous={$:global.$,frappe:global.frappe}, callbacks=[], pending=[], owners=[];let route,current;
 // Replace only native UI/network boundaries; constructor, bootstrap, refresh and fitting remain real.
 class Surface {
  constructor(node){this[0]=node||{};this.length=1;}
  find(selector){return new Surface(selector==='.id-table-wrap'?current.result:undefined);}
  children(){return this;}remove(){return this;}append(){return this;}on(){return this;}html(){return this;}text(){return this;}prop(){return this;}attr(){return this;}addClass(){return this;}removeClass(){return this;}
 }
 global.$=value=>new Surface(typeof value==='string'?current.list:value);
 global.frappe={get_route:()=>[route],router:{on:(event,fn)=>callbacks.push(fn)},defaults:{get_default:()=> 'MX'},call:request=>new Promise(resolve=>pending.push({request,resolve})),
  ui:{make_app_page:({parent})=>({body:parent,wrapper:new Surface(),add_field:df=>({df,value:df.default??'',get_value(){return this.value;},async set_value(value){this.value=value;},refresh(){}}),set_primary_action(){},add_inner_button(){}})}};
 try {
  for(const [category,pageRoute] of [['material','inventory-location-detail'],['semi_finished','semi-finished-inventory-detail'],['finished','finished-goods-inventory-detail'],['mold','mold-inventory-detail']]) {
   route=pageRoute;callbacks.forEach(fn=>fn());current=viewportFixture();
   const fixture=current;fixture.state.top=272;fixture.state.tail=64;fixture.result.querySelector=selector=>selector==='thead'?fixture.header:fixture.row;
   const page=inventory.bootstrap({ownerDocument:{defaultView:fixture.root}},{category,title:category});
   // DOM lookup belongs to this cached owner after other inventories mount.
   page.$root.find=selector=>new Surface(selector==='.id-table-wrap'?fixture.result:undefined);
   await page.fields.keyword.set_value('saved');page.selected.set('A',{item_code:'A'});page.start=200;
   fixture.flush();assert.equal(fixture.values.get('--dlp-inventory-result-max-height'),'384px');assert.equal(fixture.observers.length,1);
   owners.push({page,fixture,pageRoute});
  }
  route='Item';callbacks.forEach(fn=>fn());
  for(const {fixture} of owners) {assert.equal(fixture.values.size,0);assert.equal(fixture.frames.size,0);assert.equal(fixture.listeners.size,0);assert.equal(fixture.observers[0].disconnected,true);}
  for(const {resolve} of pending)resolve({message:{company:'MX',groups:[],total_count:0,page_count:0,snapshot_options:[],item_group_options:[],can_create_stock_entry:false}});
  await new Promise(resolve=>setImmediate(resolve));
  for(const {fixture} of owners) {assert.equal(fixture.observers.length,1);assert.equal(fixture.frames.size,0,'late read/render must not reattach a departed owner');}
  for(const {page,fixture,pageRoute} of owners) {
   route=pageRoute;callbacks.forEach(fn=>fn());callbacks.forEach(fn=>fn());fixture.flush();
   assert.equal(fixture.observers.length,2);assert.equal(fixture.listeners.size,1);assert.equal(fixture.values.get('--dlp-inventory-result-max-height'),'384px');
   fixture.state.top=320;fixture.state.tail=80;fixture.observers[1].callback();fixture.flush();assert.equal(fixture.values.get('--dlp-inventory-result-max-height'),'320px');
   assert.equal(page.selected.size,1);assert.equal(page.fields.keyword.get_value(),'saved');assert.equal(page.start,200);
  }
  assert.equal(callbacks.length,4);assert.equal(pending.length,4,'returning to a cached page does not issue another read');
 } finally {route='Item';callbacks.forEach(fn=>fn());Object.assign(global,previous);}
});
