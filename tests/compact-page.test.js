const test=require('node:test');
const assert=require('node:assert/strict');
const engine=require('../deeplinkerp_branding/public/js/compact_list.js');

// Only jQuery/Frappe host boundaries are replaced. Renderer/controller run intact.
class Surface {
  constructor(){this.value='';this.length=1;}
  find(){return new Surface();} first(){return this;} html(value){if(value===undefined)return this.value;this.value=value;return this;}
  text(value){this.value=value;return this;} append(value){this.value+=value;return this;} appendTo(){return this;} prependTo(){return this;} insertBefore(){return this;} insertAfter(){return this;}
  addClass(){return this;} removeClass(){return this;} toggleClass(){return this;} hide(){return this;} show(){return this;} remove(){return this;} off(){return this;} on(){return this;} attr(){return this;} prop(){return this;} val(){return this;} each(){return this;}
}
function setup(options={}){
  let route=['purchase-payment-records'];const calls=[],classes=new Map(),storage=new Map();
  const root={$:()=>new Surface(),document:{body:{classList:{toggle:(key,value)=>classes.set(key,value)}}},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},frappe:{get_route:()=>route,router:{on(){}},session:{user:'buyer'},boot:{sitename:'qa'},get_meta:()=>options.meta,perm:{has_perm:(doctype,level)=>level!==1},model:{can_export:()=>false},ui:{form:{make_control:()=>({set_value:async()=>{},get_value:()=>''})}},call(request){return new Promise(resolve=>calls.push({request,resolve}));}}};
  const columns=[{fieldname:'name',label:'付款单',width:150},{fieldname:'amount',label:'金额',width:130},{fieldname:'references',label:'引用',width:100}];
  const grid=engine.create({doctype:'Payment Entry',pageRoute:'purchase-payment-records',routeClass:'only-payment-page',columns,numbers:['amount'],pageFieldMap:options.fieldMap,controls:options.controls,provider:{columns,formLink:doc=>`/desk/payment-entry/${encodeURIComponent(doc.name)}`,request:c=>({method:'records',args:{search:c.quick.search,native_filters:JSON.stringify(c.nativeFilters || []),or_filters:JSON.stringify(c.orFilters || []),order_by:c.providerOrderBy,start:c.page*c.pageSize,page_length:c.pageSize}}),renderValue:field=>field==='references'?'引用':undefined,summary:()=>''}});
  let showForm=0;const form=new Surface();
  const controller=grid.mountPage({main:new Surface(),wrapper:new Surface(),...(options.pageForm?{page_form:form,show_form:()=>showForm++}:{})},root);
  return {controller,calls,classes,storage,shown:()=>showForm,leave:()=>route=['List','Item']};
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
