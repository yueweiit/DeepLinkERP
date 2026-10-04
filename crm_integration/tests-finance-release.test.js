const assert = require("node:assert/strict");
const test = require("node:test");
const finance=require("./public/js/finance_release.js");

test("only explicitly eligible orders reach the manual confirmation",()=>{
 assert.deepEqual(finance.eligibleNames([{name:"A",can_release:true},{name:"B",can_release:false},{name:"C"}]),["A"]);
});
test("partial batches retry only failed orders, never pending or uncertain responses",()=>{
 assert.deepEqual(finance.retryNames([{name:"A",state:"processing"},{name:"B",state:"failed"},{name:"C",state:"unknown"}]),["B"]);
});
test("processing and successful synchronization have distinct labels",()=>{
 assert.match(finance.stateLabel({process_status:"Deposit Confirmation Processing"}),/处理中/);
 assert.match(finance.stateLabel({process_status:"Pending Production"}),/已完成/);
});
test("each receipt shows its own allocation and account currency, including drafts and cancellations",()=>{
 const html=finance.rowsHTML([{name:"SO-1",can_release:true,receipts:[{name:"PE-1",docstatus:0,payment_type:"Receive",allocated_amount:12,currency:"MXN"},{name:"PE-2",docstatus:2,payment_type:"Receive",allocated_amount:1,currency:"USD"}]}]);
 assert.match(html,/12\.00 MXN/); assert.match(html,/1\.00 USD/); assert.match(html,/草稿/); assert.match(html,/已取消/);
});
test("malicious source names cannot inject markup into financial records",()=>{
 const html=finance.rowsHTML([{name:'<script>x</script>',reason:'<img onerror=x>',can_release:false}]);
 assert.ok(!html.includes('<script>')); assert.match(html,/&lt;img/);
});
test("button wording identifies production and displays the selected count",()=>{
 assert.equal(finance.buttonLabel(1),"允许生产（1单）"); assert.equal(finance.buttonLabel(5),"允许生产（5单）");
});
