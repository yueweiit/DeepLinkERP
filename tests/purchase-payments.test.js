const test=require('node:test');const assert=require('node:assert/strict');
const engine=require('../deeplinkerp_branding/public/js/compact_list.js');
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
