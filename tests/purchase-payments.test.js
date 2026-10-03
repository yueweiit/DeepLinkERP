const test=require('node:test');const assert=require('node:assert/strict');
const engine=require('../deeplinkerp_branding/public/js/compact_list.js');
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
