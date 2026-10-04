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
 assert.equal(args.filters.length,2);
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
