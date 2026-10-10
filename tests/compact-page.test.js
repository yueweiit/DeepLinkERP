const test=require('node:test');
const assert=require('node:assert/strict');
const engine=require('../deeplinkerp_branding/public/js/compact_list.js');

// Only jQuery/Frappe host boundaries are replaced. Renderer/controller run intact.
class Surface {
  constructor(){this.value='';this.length=1;}
  find(){return new Surface();} first(){return this;} html(value){if(value===undefined)return this.value;this.value=value;return this;}
  text(value){this.value=value;return this;} append(value){this.value+=value;return this;} appendTo(parent){this.parent=parent;return this;} prependTo(){return this;} insertBefore(){return this;} insertAfter(){return this;}
  addClass(){return this;} removeClass(){return this;} toggleClass(){return this;} hide(){return this;} show(){return this;} remove(){return this;} off(){return this;} on(){return this;} attr(){return this;} prop(){return this;} val(){return this;} each(){return this;}
}
function setup(options={}){
  let route=['purchase-payment-records'];const calls=[],classes=new Map(),storage=new Map(),routes=[];
  const root={$:()=>new Surface(),document:{body:{classList:{toggle:(key,value)=>classes.set(key,value)}}},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},frappe:{get_route:()=>route,router:{on:(_,callback)=>routes.push(callback)},session:{user:'buyer'},boot:{sitename:'qa'},get_meta:()=>options.meta,perm:{has_perm:(doctype,level)=>level!==1},model:{can_export:()=>false},ui:{form:{make_control:()=>({set_value:async()=>{},get_value:()=>''})}},call(request){return new Promise(resolve=>calls.push({request,resolve}));}}};
  const columns=[{fieldname:'name',label:'付款单',width:150},{fieldname:'amount',label:'金额',width:130},{fieldname:'references',label:'引用',width:100}];
  const grid=engine.create({doctype:'Payment Entry',purchaseChrome:options.purchaseChrome,mainFilterFields:[],pageRoute:'purchase-payment-records',routeClass:'only-payment-page',columns,numbers:['amount'],pageFieldMap:options.fieldMap,controls:options.controls,provider:{columns,formLink:doc=>`/desk/payment-entry/${encodeURIComponent(doc.name)}`,request:c=>({method:'records',args:{search:c.quick.search,native_filters:JSON.stringify(c.nativeFilters || []),or_filters:JSON.stringify(c.orFilters || []),order_by:c.providerOrderBy,start:c.page*c.pageSize,page_length:c.pageSize}}),renderValue:field=>field==='references'?'引用':undefined,summary:()=>''}});
  let showForm=0;const form=new Surface();
  const controller=grid.mountPage({main:new Surface(),wrapper:new Surface(),...(options.pageForm?{page_form:form,show_form:()=>showForm++}:{})},root);
  return {controller,calls,classes,storage,shown:()=>showForm,leave:()=>route=['List','Item'],navigate:value=>{route=value;routes.forEach(callback=>callback());}};
}
test('real page renderer shares column/density preferences and fixed pagination without native ListView data',async()=>{
  const {controller:c,calls,storage}=setup();c.setPage(2);c.pageSize=500;
  const loading=c.refresh();assert.equal(calls[0].request.args.start,1000);
  calls[0].resolve({message:{rows:[{name:'PE<&',amount:1.2345,currency:'USD'}],total_count:1200}});await loading;
  assert.match(c.list.$result.value,/1\.23 USD/);assert.match(c.list.$result.value,/PE&lt;&amp;/);assert.match(c.list.$result.value,/1001/);
  assert.deepEqual(c.list.data,[]);c.preferences.density='standard';c.setColumns(['amount','name']);
  assert.match([...storage.values()][0],/standard/);assert.ok(c.list.$result.value.indexOf('data-fieldname="amount"')<c.list.$result.value.indexOf('data-fieldname="name"'));
});
test('page response becomes stale as soon as filters change, even before delayed new dispatch',async()=>{
  const {controller:c,calls}=setup();const loading=c.refresh();c.quick.search='new';
  calls[0].resolve({message:{rows:[{name:'old'}],total_count:1}});await loading;
  assert.deepEqual(c.providerRows,[]);
});
test('leaving page invalidates its pending load and no route class leaks onto other lists',async()=>{
  const {controller:c,calls,classes,leave}=setup();const loading=c.refresh();leave();c.activate();
  calls[0].resolve({message:{rows:[{name:'old'}],total_count:1}});await loading;
  assert.deepEqual(c.providerRows,[]);assert.equal(classes.get('only-payment-page'),false);
});
test('standalone native Page exposes its hidden page_form before mounting quick controls',()=>{
  const {shown}=setup({pageForm:true});assert.equal(shown(),1);
});
test('readonly provider collection cells never expose object coercion as hover labels',async()=>{
  const {controller:c,calls}=setup();const loading=c.refresh();calls[0].resolve({message:{rows:[{name:'PE',references:[{name:'PI'}]}],total_count:1}});await loading;
  assert.doesNotMatch(c.list.$result.value,/title="\[object Object\]"/);
});
test('shared onboarding helper closes only delayed automatic overlay and cleans up on leaving route',()=>{
 let observer,disconnected=0,clicks=0,wrapper,route=['List','Purchase Order'];
 const root={document:{body:{},querySelector:()=>wrapper},MutationObserver:class{constructor(callback){observer=callback;}observe(){}disconnect(){disconnected++;}},frappe:{get_route:()=>route}};
 const grid=engine.create({doctype:'Purchase Order',columns:[]});const c={};
 assert.equal(typeof grid.dismissAutomaticOnboarding,'function');grid.dismissAutomaticOnboarding(c,root);
 wrapper={querySelector:()=>({click:()=>clicks++})};observer();assert.equal(clicks,1);assert.equal(disconnected,1);assert.equal(c.stopInitialOnboarding,null);
 grid.dismissAutomaticOnboarding(c,root);assert.equal(clicks,1,'deliberate later reopening is preserved');
 const next={};wrapper=null;grid.dismissAutomaticOnboarding(next,root);route=['List','Item'];observer();assert.equal(disconnected,2);
});
test('page metadata and native read permissions govern alias fields and quick controls',()=>{
 const {controller:c}=setup({meta:{fields:[{fieldname:'paid_amount',permlevel:1},{fieldname:'company',permlevel:0}]},fieldMap:{amount:'paid_amount'},controls:[{fieldname:'company',fieldtype:'Link'},{fieldname:'amount',permission_field:'paid_amount',fieldtype:'Currency'}]});
 assert.equal(c.nativeAllowed.has('paid_amount'),false);assert.equal(c.allowed.has('amount'),false);assert.equal(c.controls.amount,undefined);assert.ok(c.controls.company);
});
test('AND or OR changes reset standalone page scope and reject pending responses before redispatch',async()=>{
 const {controller:c,calls}=setup();c.setPage(2);const pending=c.refresh();assert.equal(calls[0].request.args.start,200);
 c.orFilters=[['Payment Entry','name','like','NEW%']];calls[0].resolve({message:{rows:[{name:'old'}],total_count:1}});await pending;assert.deepEqual(c.providerRows,[]);
 const fresh=c.refresh();assert.equal(calls[1].request.args.start,0);assert.equal(c.page,0);calls[1].resolve({message:{rows:[{name:'new'}],total_count:1}});await fresh;assert.equal(c.providerRows[0].name,'new');
});
test('first manual onboarding launch is preserved and empty initial watching expires',()=>{
 let callback,timer,manual,wrapper,clicks=0,removed=0,disconnected=0;
 const root={setTimeout:fn=>{timer=fn;return 1;},clearTimeout(){},document:{body:{},querySelector:()=>wrapper,addEventListener:(type,fn)=>manual=fn,removeEventListener:()=>removed++},MutationObserver:class{constructor(fn){callback=fn;}observe(){}disconnect(){disconnected++;}},frappe:{get_route:()=>['List','Purchase Order']}};
 const grid=engine.create({doctype:'Purchase Order',columns:[]}),c={};grid.dismissAutomaticOnboarding(c,root);
 manual?.({target:{closest:()=>({})}});wrapper={querySelector:()=>({click:()=>clicks++})};callback();assert.equal(clicks,0);assert.equal(disconnected,1);assert.equal(removed,1);
 wrapper=null;const fresh={};grid.dismissAutomaticOnboarding(fresh,root);timer?.();wrapper={querySelector:()=>({click:()=>clicks++})};callback();assert.equal(clicks,0);assert.equal(fresh.stopInitialOnboarding,null);
});

test('expanded details invalidate using one row index rather than rescanning every row',()=>{
 const rows=Array.from({length:1000},(_,index)=>({name:`PO-${index}`,modified:'new'}));
 rows.find=()=>assert.fail('expanded rows must not rescan the full page');
 const expanded=new Map([['PO-2',{header:{modified:'new'}}],['PO-900',{header:{modified:'old'}}],['removed',{header:{modified:'new'}}]]);
 engine.invalidateExpandedDetails(expanded,rows);
 assert.deepEqual([...expanded.keys()],['PO-2']);
});

test('shared row details cache one version and discard late page, collapsed or changed-version reads',async()=>{
 const reads=[];let renders=0;const owner={providerRows:[{name:'PR',modified:'v1'}],requestId:1,list:{render_list:()=>renders++,set_rows_as_checked(){}},root:{frappe:{get_route:()=>['List','Purchase Receipt']}},detailActive:()=>true};
 assert.equal(typeof engine.mountRowDetails,'function');
 engine.mountRowDetails(owner,{rows:()=>owner.providerRows,load:doc=>new Promise(resolve=>reads.push({doc,resolve}))});
 const first=owner.toggleRowDetails('PR');assert.equal(reads.length,1);
 await owner.toggleRowDetails('PR');reads[0].resolve({header:{modified:'v1'},items:[{item_code:'old'}]});await first;
 assert.equal(owner.expandedDetails.has('PR'),false);assert.equal(owner.detailCache.has('PR'),false);
 const next=owner.toggleRowDetails('PR');reads[1].resolve({header:{modified:'v1'},items:[{item_code:'visible'}]});await next;
 await owner.toggleRowDetails('PR');await owner.toggleRowDetails('PR');assert.equal(reads.length,2);assert.equal(owner.detailCache.get('PR').items[0].item_code,'visible');
 owner.providerRows=[{name:'PR',modified:'v2'}];owner.reconcileRowDetails();assert.equal(owner.detailCache.size,0);assert.equal(owner.expandedDetails.size,0);
 const newer=owner.toggleRowDetails('PR');owner.requestId++;reads[2].resolve({header:{modified:'v2'},items:[{item_code:'late'}]});await newer;assert.equal(owner.detailCache.size,0);
 assert.ok(renders>0);
});
test('failed details can retry and newer server versions show an explicit refresh notice',async()=>{
 let attempts=0;const owner={providerRows:[{name:'PR',modified:'v1'}],requestId:1,list:{render_list(){}},root:{}};
 engine.mountRowDetails(owner,{rows:()=>owner.providerRows,load:async()=>{if(++attempts===1)throw new Error('读取失败');return {header:{modified:'v2'},items:[{item_code:'stale'}]};}});
 await owner.toggleRowDetails('PR');assert.match(owner.detailCache.get('PR').error,/读取失败/);
 await owner.toggleRowDetails('PR');await owner.toggleRowDetails('PR');assert.equal(attempts,2);
 assert.match(owner.detailCache.get('PR').error,/已更新|刷新/);assert.equal(owner.detailCache.get('PR').items,undefined);
});
test('detail caches survive a replacement row with the same version and invalidate an in-place version change',async()=>{
 const owner={providerRows:[{name:'PR',modified:'v1'}],requestId:1,list:{render_list(){}},root:{}};let reads=0;
 engine.mountRowDetails(owner,{rows:()=>owner.providerRows,load:async()=>{reads++;return {header:{modified:'v1'},items:[]};}});
 await owner.toggleRowDetails('PR');owner.providerRows=[{name:'PR',modified:'v1'}];owner.reconcileRowDetails();
 assert.equal(owner.detailCache.size,1);assert.equal(owner.expandedDetails.size,1);
 owner.providerRows[0].modified='v2';owner.reconcileRowDetails();assert.equal(owner.detailCache.size,0);assert.equal(owner.expandedDetails.size,0);assert.equal(reads,1);
});
test('standalone route departure invalidates a pending detail even when returning before it resolves',async()=>{
 const {controller:c,navigate}=setup();let resolve;
 c.providerRows=[{name:'PR',modified:'v1'}];
 engine.mountRowDetails(c,{rows:()=>c.providerRows,load:()=>new Promise(done=>resolve=done)});
 const pending=c.toggleRowDetails('PR');navigate(['List','Item']);navigate(['purchase-payment-records']);
 resolve({header:{modified:'v1'},items:[{item_code:'OLD'}]});await pending;
 assert.equal(c.detailCache.has('PR'),false);assert.equal(c.expandedDetails.has('PR'),false);
});
test('native page-form restriction section moves into the active advanced disclosure on existing render lifecycle',()=>{
 const {controller:c}=setup({purchaseChrome:true}),section=new Surface();
 c.list.page.wrapper.find=selector=>selector==='.page-form > .filter-section'?section:new Surface();
 c.list.render_list();assert.equal(section.parent,c.$advancedFilters);
 section.parent=c.list.page.wrapper;c.list.render_list();assert.equal(section.parent,c.$advancedFilters,'native reattachment stays accessible in the same advanced container');
});
