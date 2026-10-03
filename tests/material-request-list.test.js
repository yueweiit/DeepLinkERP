const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const base = '../deeplinkerp_branding/public/js/';
const mr = fs.existsSync(require('node:path').join(__dirname, base, 'material_request_list.js')) ? require(base + 'material_request_list.js') : {};
test('MR columns start with ODT and category and keep native identifiers', () => {
 assert.deepEqual(mr.COLUMNS?.slice(0, 3).map(c => c.fieldname), ['custom_odt', 'custom_mes_issue_category', 'name']);
});
test('MR categories use only explicit source and otherwise translated original type', () => {
 assert.equal(typeof mr.renderValue, 'function');
 assert.equal(mr.renderValue('custom_mes_issue_category', {custom_mes_issue_category:'raw_material'}), '原料申请');
 assert.equal(mr.renderValue('custom_mes_issue_category', {custom_mes_issue_category:'unknown', material_request_type:'Material Issue', custom_odt:'ODT'} , {translate: x => x === 'Material Issue' ? '发料' : x}), '发料');
 assert.equal(mr.renderValue('custom_odt', {}), '');
});
test('MR query count and export share filters without quantity or money summary', () => {
 assert.equal(typeof mr.buildQuery, 'function');
 const allowed = new Set(['name','owner','custom_odt','custom_mes_issue_category','custom_material_request_no']);
 const q = mr.buildQuery({fields:['name','missing'], filters:[], or_filters:[]}, {custom_odt:'ODT-1', custom_mes_issue_category:'consumable', search:'MES-1'}, allowed);
 const requests = mr.buildRequests(q, ['name','owner'], allowed);
 assert.equal(requests.summary, null);
 assert.deepEqual(requests.export.filters, requests.count.filters);
 assert.deepEqual(requests.export.or_filters, requests.count.or_filters);
 assert.deepEqual(q.fields,['name']);
 assert.equal(q.or_filters.length,2);
 assert.equal(requests.export.doctype,'Material Request');
});
test('preferences are isolated by doctype while preserving the PO key', () => {
 assert.equal(typeof mr.preferenceKey,'function');
 const po = require(base + 'purchase_order_list.js');
 assert.notEqual(mr.preferenceKey('site','user'),po.preferenceKey('site','user'));
});
test('readonly form summary escapes values and respects field permissions', () => {
 const p = require('node:path').join(__dirname,base,'material_request_form.js');
 const form = fs.existsSync(p) ? require(p) : {};
 assert.equal(typeof form.summaryHTML,'function');
 const doc = {custom_odt:'<script>',custom_mes_issue_category:'raw_material',custom_material_request_no:'MES<&'};
 const html = form.summaryHTML(doc,new Set(Object.keys(doc)));
 assert.match(html,/&lt;script&gt;/);
 assert.match(html,/原料申请/);
 assert.match(html,/MES&lt;&amp;/);
 assert.doesNotMatch(form.summaryHTML(doc,new Set()),/script|MES|原料申请/);
});
test('shared engine installs MR once while chaining MES callbacks and preserving native actions', async () => {
 let loads=0, refreshes=0, count=0;
 const indicator=()=>['Draft','red'], bulk=()=>{};
 const settings={onload(){loads++;},refresh(){refreshes++;},get_indicator:indicator,bulk_handler:bulk};
 const classes=new Set(),listeners=[];
 let route=['List','Material Request','List'];
 const env={frappe:{listview_settings:{'Material Request':settings},get_route:()=>route,router:{on(e,cb){listeners.push(cb);}},model:{std_fields_list:['name','owner']},perm:{has_perm:()=>true},boot:{},call:async call=>{count++; assert.match(call.method,/get_count$/); return {message:10};}},document:{body:{classList:{toggle(c,on){on ? classes.add(c) : classes.delete(c);}}}}};
 const list={doctype:'Material Request',view_name:'List',meta:{fields:mr.COLUMNS.map(c=>({fieldname:c.fieldname})).concat([{fieldname:'material_request_type'}])},fields:[['name','Material Request']],data:[],get_args(){return {filters:[],or_filters:[],fields:this.fields,order_by:'name asc'};},render_header(){},refresh(){},get_form_link(doc){return '/desk/material-request/'+doc.name;},get_indicator_html(){return 'native';}};
 env.cur_list=list;
 mr.install(env); mr.install(env); settings.onload(list); settings.refresh(list);
 assert.equal(loads,1); assert.equal(refreshes,1); assert.equal(settings.get_indicator,indicator); assert.equal(settings.bulk_handler,bulk); assert.equal(listeners.length,1);
 const controller=list.dlpMaterialRequestGrid;
 controller.quick.custom_odt='ODT'; list.get_args(); controller.setPage(3); controller.quick.custom_odt='ODT-2'; assert.equal(list.get_args().start,0);
 await list.render_count(); assert.equal(count,1); assert.deepEqual(controller.summary,[]);
 route=['Form','Material Request','MR-1']; listeners[0](); assert.equal(classes.has('dlp-material-request-grid-active'),false);
});
test('form refresh mounts one readonly first-content summary and never dirties the document', () => {
 const vm=require('node:vm');
 const source=fs.readFileSync(require('node:path').join(__dirname,base,'material_request_form.js'),'utf8');
 let mounts=0, installs=0, html='', handler;
 const wrapper={prependTo(target){assert.equal(target,'first-content'); mounts++;return this;},html(value){html=value;return this;}};
 const context={ $:()=>wrapper,frappe:{ui:{form:{on(doctype,events){assert.equal(doctype,'Material Request');installs++;handler=events.refresh;}}},perm:{has_perm:(doctype,level)=>level===0}}};
 vm.runInNewContext(source,context);
 context.DeepLinkERPMaterialRequestSummary.install();
 const doc={custom_odt:'ODT<1',custom_mes_issue_category:'semi_finished',custom_material_request_no:'secret',__unsaved:0};
 const frm={doc,meta:{fields:[{fieldname:'custom_odt'},{fieldname:'custom_mes_issue_category'},{fieldname:'custom_material_request_no',permlevel:1}]},layout:{wrapper:'first-content'},set_value(){throw Error('summary must never write');},dirty(){throw Error('summary must never dirty');},save(){throw Error('summary must never save');}};
 handler(frm); handler(frm);
 assert.equal(mounts,1);assert.equal(installs,1);assert.equal(doc.__unsaved,0);
 assert.match(html,/ODT&lt;1/);assert.match(html,/半成品申请/);assert.doesNotMatch(html,/secret/);
});
test('missing optional metadata cannot become invalid MR query or export fields', () => {
 const allowed=mr.allowedFields({fields:[{fieldname:'status'}]},()=>true,['name','owner']);
 const q=mr.buildQuery({fields:['`tabMaterial Request`.`name`','custom_odt'],filters:[],or_filters:[]},{custom_odt:'absent',custom_mes_issue_category:'absent',search:'id'},allowed);
 assert.deepEqual(q.fields,['`tabMaterial Request`.`name`']);assert.deepEqual(q.filters,[]);
 assert.deepEqual(q.or_filters,[['Material Request','name','like','%id%']]);
 assert.deepEqual(mr.buildRequests(q,['custom_odt','name'],allowed).export.fields,['name']);
});
test('legacy list retains blank ODT and category fallback as display-only columns', () => {
 const notices=[];
 const env={frappe:{model:{std_fields_list:['name','owner']},perm:{has_perm:()=>true},boot:{},get_route:()=>['List','Material Request','List'],show_alert:notice=>notices.push(notice)}};
 const list={doctype:'Material Request',view_name:'List',meta:{fields:[{fieldname:'material_request_type'}]},fields:[['name','Material Request']],data:[],get_args(){return {fields:this.fields,filters:[],or_filters:[]};},render_header(){},get_form_link(){return '/desk/material-request/MR';},get_indicator_html(){return ''}};
 const controller=mr.mount(list,env);
 assert.deepEqual(controller.preferences.columns.slice(0,2),['custom_odt','custom_mes_issue_category']);
 const header=list.get_header_html();
 assert.doesNotMatch(header,/data-sort-by="custom_odt"|data-sort-by="custom_mes_issue_category"/);
 assert.match(header,/data-sort-by="name"/);
 const html=list.get_list_row_html({name:'MR',material_request_type:'Material Issue',custom_odt:'must not expose'});
 assert.match(html,/data-fieldname="custom_odt"/);assert.match(html,/Material Issue/);assert.doesNotMatch(html,/must not expose/);
 assert.deepEqual(list.get_args().fields,[['name','Material Request'],['owner','Material Request'],['material_request_type','Material Request']]);
 assert.deepEqual(mr.buildRequests(list.get_args(),controller.preferences.columns,controller.allowed).export.fields,['name','owner']);
 mr.mount(list,env);assert.equal(notices.length,1);
});
test('legacy stored sorting cannot query missing display-only fields', () => {
 const allowed=new Set(['name','owner']);
 for(const order_by of ['custom_odt asc','`tabMaterial Request`.`custom_mes_issue_category` desc']) {
  const q=mr.buildQuery({fields:['name'],filters:[],or_filters:[],order_by},{},allowed);
  assert.equal(q.order_by,'name desc');
  assert.equal(mr.buildRequests(q,['name'],allowed).export.order_by,'name desc');
 }
 const q=mr.buildQuery({fields:['name'],filters:[],or_filters:[],order_by:'custom_odt asc, name asc'},{},allowed);
 assert.equal(q.order_by,'name asc');
 const installed=mr.buildQuery({fields:['name'],filters:[],or_filters:[],order_by:'custom_odt asc'},{},new Set(['name','custom_odt']));
 assert.equal(installed.order_by,'custom_odt asc');
});
