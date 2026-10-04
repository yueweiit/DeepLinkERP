const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Isolate only the browser host. Exercise the real adapter's query function.
function receiptConfiguration() {
  let configuration;
  const host = { DeepLinkERPCompactList: { create(value) {
    configuration = value;
    return { install() {} };
  } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,
    "../deeplinkerp_branding/public/js/purchase_receipt_list.js"), "utf8"),
  { globalThis: host });
  return configuration;
}

const decoded = value => typeof value === "string" ? JSON.parse(value) : value;

test("receipt financial view retains native filters, OR filters, sorting and page scope", () => {
  const config = receiptConfiguration();
  const native = {
    filters: [["Purchase Receipt", "owner", "=", "buyer@example.com"]],
    or_filters: [["Purchase Receipt", "status", "=", "Completed"]],
    order_by: "posting_date desc", fields: ["name"],
  };
  const controller = {
    quick: { company: "Company A" }, page: 2, pageSize: 2500,
    providerOrderBy: "posting_date asc", list: { get_args: () => native },
    originals: { get_args: () => native },
    allowed: new Set(["name", "posting_date", "status", "owner", "company"]),
  };
  const request = config.provider.request(controller);
  assert.equal(request.method, "deeplinkerp_branding.services.purchase_payment_service.get_receipt_list");
  assert.deepEqual(decoded(request.args.native_filters), native.filters);
  assert.deepEqual(decoded(request.args.or_filters), native.or_filters);
  assert.equal(request.args.order_by, "posting_date asc");
  assert.equal(request.args.start, 5000);
  assert.equal(request.args.page_length, 2500);
  assert.deepEqual(decoded(request.args.filters), controller.quick);
});
test('receipt export preserves clicked filters and columns across lazy loading, removes only action and page limits', async () => {
  const config=receiptConfiguration(); let resolve, exported;
  const controller={quick:{company:'A'},page:2,pageSize:500,preferences:{columns:['supplier_name','outstanding','name','payment_action']},providerOrderBy:'name asc',list:{},originals:{get_args:()=>({filters:[['Purchase Receipt','owner','=','buyer']],or_filters:[]})},root:{frappe:{require:()=>new Promise(r=>resolve=r)}}};
  const pending=config.provider.exportCurrent(controller);
  controller.quick.company='B';controller.preferences.columns=['name'];
  controller.root.DeepLinkERPPurchaseOrderExport={fetchNativeWorkbook:async(root,args)=>{exported=args;return new Uint8Array();},downloadWorkbook(){}};
  resolve();await pending;
  assert.deepEqual(decoded(exported.filters),{company:'A'});
  assert.deepEqual(decoded(exported.columns),['supplier_name','outstanding','name']);
  assert.equal(exported.start,undefined);assert.equal(exported.page_length,undefined);
});
test('receipt child advanced filters cannot be silently dropped in financial view', () => {
  const config=receiptConfiguration();
  assert.throws(()=>config.provider.request({originals:{get_args:()=>({filters:[['Purchase Receipt Item','item_code','=','A']]})},list:{}}),/原生筛选/);
});
test('receipt data-only scope changes reset paging, invalidate old responses and keep all native predicates', () => {
  const config=receiptConfiguration();
  const shared=require('../deeplinkerp_branding/public/js/compact_list.js').create(config);
  const list={doctype:'Purchase Receipt',view_name:'List',meta:{fields:[{fieldname:'posting_date'},{fieldname:'company'}]},fields:[['name','Purchase Receipt']],data:[],get_args(){return {filters:this.filters || [],or_filters:[],fields:['name'],order_by:'name desc'};},get_call_args(){return {method:'native',args:this.get_args()};},no_change(){return false;},prepare_data(){},reset_defaults(){},render_header(){},render_list(){},refresh(){},get_form_link(){return '/desk/purchase-receipt/name';}};
  const env={frappe:{model:{std_fields_list:['name','docstatus']},perm:{has_perm:()=>true},get_route:()=>['List','Purchase Receipt'],boot:{},session:{}}};
  const c=shared.mount(list,env);c.setProviderScope('all',false);c.quick={company:'A'};c.setPage(2);
  const before=list.get_call_args();list.no_change(before);assert.equal(before.args.start,200);
  list.filters=[['Purchase Receipt','owner','=','new']];
  const now=list.get_args();assert.equal(now.start,0);assert.equal(c.page,0);
  const old={message:{rows:[{name:'stale'}],total_count:9}};
  before.callback(old);list.prepare_data(old);
  assert.equal(c.providerRows.length,0);
});
test('unsupported receipt child query explicitly returns to native scope, preserving the filter and showing why', () => {
  const config=receiptConfiguration();const shared=require('../deeplinkerp_branding/public/js/compact_list.js').create(config);let notice;
  const list={doctype:'Purchase Receipt',view_name:'List',meta:{fields:[]},fields:[['name','Purchase Receipt']],data:[],get_args(){return {filters:[['Purchase Receipt Item','item_code','=','A']],fields:['name'],order_by:'name desc'};},get_call_args(){return {method:'native',args:this.get_args()};},no_change(){return false;},prepare_data(){},reset_defaults(){},render_header(){},render_list(){},refresh(){}};
  const env={frappe:{model:{std_fields_list:['name']},perm:{has_perm:()=>true},get_route:()=>['List','Purchase Receipt'],boot:{},session:{},show_alert:value=>notice=value.message}};
  const c=shared.mount(list,env);c.setProviderScope('all',false);
  const request=list.get_call_args();
  assert.equal(c.providerScope,'orders');assert.equal(request.method,'native');
  assert.deepEqual(request.args.filters,[['Purchase Receipt Item','item_code','=','A']]);assert.match(notice,/原生筛选/);
});
test('visible native PR sort selector is the source for list, count and export order',()=>{
  const config=receiptConfiguration();const c={quick:{},page:0,pageSize:100,providerOrderBy:'posting_date desc',list:{sort_selector:{get_sql_string:()=> '`tabPurchase Receipt`.`grand_total` asc, `tabPurchase Receipt`.`name` asc'}},originals:{get_args:()=>({filters:[],order_by:'name desc'})}};
  assert.equal(config.provider.request(c).args.order_by,'`tabPurchase Receipt`.`grand_total` asc, `tabPurchase Receipt`.`name` asc');
});
test('receipt header sort updates the real native selector and native callback only once',()=>{
  const config=receiptConfiguration();let value,changed=0;const selector={sort_by:'name',sort_order:'asc',set_value:(field,order)=>value=[field,order]};
  assert.equal(typeof config.provider.sortBy,'function');config.provider.sortBy({list:{sort_selector:selector,on_sort_change:()=>changed++},setPage(){}},'name');
  assert.deepEqual(value,['name','desc']);assert.equal(changed,1);
});
test('receipt financial activation restores all valid quick predicates including status',()=>{
  const config=receiptConfiguration();let supplier=0,status=0;config.provider.onActivate({controls:{supplier:{$wrapper:{show:()=>supplier++}},status:{$wrapper:{show:()=>status++}}}});
  assert.equal(supplier,1);assert.equal(status,1);
});
test('receipt money is fixed two display decimals even if boot currency precision is three',()=>{
  const config=receiptConfiguration();const rendered=config.provider.renderValue('grand_total',{grand_total:1.2345,currency:'USD'},{number:()=> '1.235'},String);
  assert.equal(rendered,'1.23 USD');
});
test('complete native receipt rows and child-filter fallback retain two money decimals independently of boot',()=>{
 const config=receiptConfiguration(),grid=require('../deeplinkerp_branding/public/js/compact_list.js').create(config);
 const list={doctype:'Purchase Receipt',view_name:'List',meta:{fields:[{fieldname:'grand_total'},{fieldname:'currency'}]},fields:[['name','Purchase Receipt']],data:[],get_args(){return {fields:['name','grand_total'],filters:[['Purchase Receipt Item','item_code','=','A']]};},get_call_args(){return {method:'native',args:this.get_args()};},no_change(){return false;},prepare_data(){},reset_defaults(){},render_header(){},render_list(){},refresh(){},get_form_link:()=>'/desk/purchase-receipt/PR',get_indicator_html:()=>''};
 const env={frappe:{model:{std_fields_list:['name']},perm:{has_perm:()=>true},get_route:()=>['List','Purchase Receipt'],boot:{sysdefaults:{currency_precision:3}},session:{},show_alert(){}}};
 const c=grid.mount(list,env);const doc={name:'PR',grand_total:12.3456,currency:'USD'};
 assert.match(list.get_list_row_html(doc),/12\.35 USD/);assert.doesNotMatch(list.get_list_row_html(doc),/12\.346/);
 c.setProviderScope('all',false);list.get_call_args();assert.equal(c.providerScope,'orders');assert.match(list.get_list_row_html(doc),/12\.35 USD/);
});
