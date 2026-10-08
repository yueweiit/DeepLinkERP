const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require.resolve("../deeplinkerp_branding/public/js/purchase_payment_form.js"), "utf8");

function host() {
 let filter, counter = 0;
 const calls = [];
 const root = {crypto: {randomUUID: () => `00000000-0000-0000-0000-${String(++counter).padStart(12, "0")}`}, URLSearchParams, URL,
  location: {href: "http://po-grid-qa.localhost/app/purchase-order", origin: "http://po-grid-qa.localhost"},
  $: {ajaxPrefilter: fn => {filter = fn;}}, DeepLinkERPPurchasePayments: {formRefresh() {}},
  frappe: {ui: {form: {on() {}, save(frm, action, callback) {
   const endpoint = action === "cancel" ? "cancel" : "savedocs";
   const data = endpoint === "cancel" ? {doctype: frm.doc.doctype, name: frm.doc.name} : {doc: JSON.stringify(frm.doc), action};
   const options = {url: root.requestUrl || `/api/method/frappe.desk.form.save.${endpoint}`, data: new URLSearchParams(data).toString()};
   filter?.(options); calls.push(options); frm.reply = callback;
   return "native-return";
  }}}}};
 const context = {globalThis: root, window: root, ...root};
 vm.runInNewContext(source, context);
 return {root, calls, filter: (...args) => filter?.(...args), install: () => vm.runInNewContext(source, context)};
}
const form = (name = "new-purchase-order-a", doctype = "Purchase Order") => ({doc: {doctype, name, __islocal: 1,
 items: [{qty: 2, rate: 3, account: "A"}], taxes: [{rate: 10}]}});
const args = options => Object.fromEntries(new URLSearchParams(options.data));

test("native transport preserves key for a lost response and rotates for business changes or confirmed success", () => {
 const h = host(), frm = form(); h.root.cur_frm = frm;
 assert.equal(h.root.frappe.ui.form.save(frm, "Save", () => {}), "native-return");
 const first = args(h.calls[0]).request_id; assert.ok(first);
 frm.reply({status: 0}); // no successful native docs; outcome is unknown
 h.root.frappe.ui.form.save(frm, "Save", () => {}); assert.equal(args(h.calls[1]).request_id, first);
 frm.doc.items[0].rate = 4;
 h.root.frappe.ui.form.save(frm, "Save", () => {}); assert.notEqual(args(h.calls[2]).request_id, first);
 const second = args(h.calls[2]).request_id;
 frm.reply({docs: [{doctype: "Purchase Order", name: "PO-1"}]});
 h.root.frappe.ui.form.save(frm, "Save", () => {}); assert.notEqual(args(h.calls[3]).request_id, second);
});

test("independent local form identities and native cancel each carry their own complete snapshot", () => {
 const h = host(), a = form(), b = form("new-purchase-order-b");
 h.root.cur_frm = a; h.root.frappe.ui.form.save(a, "Save", () => {});
 h.root.cur_frm = b; h.root.frappe.ui.form.save(b, "Save", () => {});
 assert.notEqual(args(h.calls[0]).request_id, args(h.calls[1]).request_id);
 b.doc.name = "PO-1"; b.doc.docstatus = 1;
 h.root.frappe.ui.form.save(b, "cancel", () => {});
 assert.deepEqual(JSON.parse(args(h.calls[2]).doc), b.doc);
 assert.ok(args(h.calls[2]).request_id);
});

test("bridge installation is single and unrelated or background requests are unmodified", () => {
 const h = host(); h.install();
 const other = form("SO-1", "Sales Order"); h.root.cur_frm = other;
 h.root.frappe.ui.form.save(other, "Save", () => {}); assert.equal(args(h.calls[0]).request_id, undefined);
 const frm = form(); h.root.cur_frm = other;
 h.root.frappe.ui.form.save(frm, "Save", () => {}); assert.equal(args(h.calls[1]).request_id, undefined);
 const options = {url: "/api/method/frappe.desk.form.save.savedocs", data: new URLSearchParams({doc: JSON.stringify(frm.doc), action: "Save", request_id: "already-explicit"}).toString()};
 h.filter(options); assert.equal(args(options).request_id, "already-explicit");
});

test("same endpoint names at an external origin never receive a procurement key or cancel snapshot", () => {
 const h = host(), frm = form(); h.root.cur_frm = frm;
 for (const action of ["Save", "cancel"]) {
  h.root.requestUrl = `https://other.example/api/method/frappe.desk.form.save.${action === "cancel" ? "cancel" : "savedocs"}`;
  h.root.frappe.ui.form.save(frm, action, () => {});
  assert.equal(args(h.calls.at(-1)).request_id, undefined);
  if (action === "cancel") assert.equal(args(h.calls.at(-1)).doc, undefined);
 }
 h.root.requestUrl = "http://po-grid-qa.localhost/api/method/frappe.desk.form.save.savedocs";
 h.root.frappe.ui.form.save(frm, "Save", () => {});
 assert.ok(args(h.calls.at(-1)).request_id);
});
