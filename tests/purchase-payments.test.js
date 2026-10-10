const test=require('node:test');const assert=require('node:assert/strict');
const engine=require('../deeplinkerp_branding/public/js/compact_list.js');
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
function financePageConfiguration(file,route){
 let config;const page={main:{append(){}},set_secondary_action(){}};
 const host={DeepLinkERPCompactList:{...engine,create:value=>{if(value.pageRoute)config=value;return engine.create(value);}},frappe:{pages:{[route]:{}},ui:{make_app_page:()=>page},model:{with_doctype:()=>new Promise(()=>{})}},DeepLinkERPPurchasePayments:{}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,file),'utf8'),{globalThis:host});
 if(route==='purchase-payment-records')host.DeepLinkERPPurchasePayments.recordsPage({});else host.frappe.pages[route].on_page_load({});
 return config;
}
test('order procurement actions expose receipt only using server eligibility',()=>{
 global.frappe={model:{can_create:()=>true,can_read:()=>true}};
 require('../deeplinkerp_branding/public/js/purchase_payments.js');
 const actions=global.DeepLinkERPPurchasePayments.orderReceiptAction;
 const doc={name:'PO',docstatus:1,status:'To Receive and Bill',per_received:0,per_billed:0,receipt_eligibility:{allowed:true,reason:''}};
 assert.match(actions(doc),/dlp-order-receipt/);
 assert.doesNotMatch(actions(doc),/dlp-order-pay|dlp-order-invoice/);
 assert.doesNotMatch(actions({...doc,receipt_eligibility:{allowed:false,reason:'已关闭'}}),/dlp-order-receipt/);
});
test('compact default columns hide optional fields while retaining user choices',()=>{
 const grid=engine.create({doctype:'Sales Order',columns:['name','customer_name','company','owner'].map(fieldname=>({fieldname})),defaultColumns:['name','customer_name']});
 const allowed=new Set(['name','customer_name','company']);
 assert.deepEqual(grid.normalizePreferences(null,allowed).columns,['name','customer_name']);
 assert.deepEqual(grid.normalizePreferences({columns:['name','company','owner']},allowed).columns,['name','company']);
});
test('receipt dates use posting_date and inaccessible fields cannot enter native requests',()=>{
 const grid=engine.create({doctype:'Purchase Receipt',columns:[],dateField:'posting_date',quickFields:['company']});
 const query=grid.buildQuery({filters:[],fields:['name','grand_total']},{from_date:'2026-10-01',to_date:'2026-10-03',company:'Denied'},new Set(['name','posting_date']));
 assert.deepEqual(query.fields,['name']);assert.deepEqual(query.filters,[['Purchase Receipt','posting_date','>=','2026-10-01'],['Purchase Receipt','posting_date','<=','2026-10-03']]);
});
test('payment record main view keeps compact bank payment columns and existing reference/voucher detail columns available',()=>{
 const config=financePageConfiguration('../deeplinkerp_branding/public/js/purchase_payments.js','purchase-payment-records');
 assert.equal(config.purchaseChrome,true);
 assert.ok(config.provider.defaultColumns.includes('amount'));assert.ok(!config.provider.defaultColumns.includes('references'));
 for(const field of ['references','vouchers','sync_issues'])assert.ok(config.provider.columns.some(col=>col.fieldname===field));
 assert.deepEqual(Array.from(config.mainFilterFields),['search','company','status','from_date','to_date']);
});
test('payable main amounts use authoritative account currency totals and paid balance with full filtered summary',()=>{
 const config=financePageConfiguration('../deeplinkerp_branding/deeplinkerp_branding/page/purchase_payables/purchase_payables.js','purchase-payables');
 assert.equal(config.purchaseChrome,true);
 for(const field of ['total','settled','outstanding'])assert.ok(config.provider.defaultColumns.includes(field));
 const doc={grand_total:100,invoice_currency:'USD',total:600,settled:450,outstanding:150,currency:'CNY'};
 assert.equal(config.provider.renderValue('total',doc),'600.00 CNY');assert.equal(config.provider.renderValue('settled',doc),'450.00 CNY');
 assert.match(config.provider.summary({providerPayload:{totals:[{currency:'CNY',total:1200,settled:900,outstanding:300}]}}),/1,200\.00 CNY/);
 assert.equal(config.provider.renderValue('settled',{...doc,settled:null}),'—');
 const draft={grand_total:100,invoice_currency:'USD',docstatus:0};
 assert.equal(config.provider.renderValue('total',draft),'—','unknown account totals cannot switch to invoice currency under the same heading');
 assert.equal(config.provider.renderValue('grand_total',draft),'100.00 USD');
});
test('both finance pages upgrade v4 defaults once and keep density and subsequent custom columns',()=>{
 for(const [file,route] of [['../deeplinkerp_branding/public/js/purchase_payments.js','purchase-payment-records'],['../deeplinkerp_branding/deeplinkerp_branding/page/purchase_payables/purchase_payables.js','purchase-payables']]){
  const config=financePageConfiguration(file,route),grid=engine.create(config),allowed=new Set(config.columns.map(col=>col.fieldname));
  const previous={density:'standard',columns:['name','company'],version:3};
  const next=grid.normalizePreferences(previous,allowed,config.provider.columns);
  assert.equal(config.backupMigratedPreferences,true);assert.equal(next.version,4);assert.equal(next.density,'standard');assert.deepEqual(next.columns,Array.from(config.provider.defaultColumns));
  assert.deepEqual(grid.normalizePreferences({...next,columns:['name','company']},allowed,config.provider.columns).columns,['name','company']);
 }
});
test('payable export freezes all authorized filters and selected columns before lazy loading and removes page bounds',async()=>{
 const config=financePageConfiguration('../deeplinkerp_branding/deeplinkerp_branding/page/purchase_payables/purchase_payables.js','purchase-payables');
 assert.equal(typeof config.provider.exportCurrent,'function');let resolve,exported;
 const c={quick:{company:'C',search:'PI'},page:3,pageSize:100,preferences:{columns:['name','total','settled','outstanding','action']},root:{frappe:{require:()=>new Promise(done=>resolve=done)}}};
 const loading=config.provider.exportCurrent(c);c.quick.search='changed';c.preferences.columns=['name'];
 c.root.DeepLinkERPPurchaseOrderExport={downloadWorkbook(){},fetchNativeWorkbook:async(_root,args,method)=>{exported={args,method};return new Uint8Array();}};resolve();await loading;
 assert.equal(exported.args.company,'C');assert.equal(exported.args.search,'PI');assert.deepEqual(JSON.parse(exported.args.columns),['name','total','settled','outstanding']);assert.equal(exported.args.start,undefined);assert.equal(exported.args.page_length,undefined);assert.equal(exported.args.export_format,'xlsx');assert.match(exported.method,/get_purchase_payables$/);
});
