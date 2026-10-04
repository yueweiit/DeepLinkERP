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
