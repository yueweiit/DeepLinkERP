from overseas_costing.tests.test_saved_trial_regressions import _frontend_result, FRONTEND_SETUP
from overseas_costing.tests.test_workbench_frontend_state import _fee_workspace_result


def test_stale_cost_is_collapsed_history_not_complete_badge():
    html=_frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
h.detailState.header={status:'Dirty',summary_snapshot:{comprehensive_cost:{summary:{is_complete:true,total_cost_rmb:'88404.00'},items:[]}}};
console.log(JSON.stringify(h.renderMaterialFeeCostTable()));
""")
    assert '待重新试算' in html
    assert '<details class="ocw-mf-cost-history">' in html
    assert '完整成本' not in html


def test_autofill_renders_shipment_value_and_project_summary():
    html=_frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
const fill={selections:new Set(),draft:{autofill_preview:{items:[{material_code:'CW000191',shipment_value_rmb:'10560',project_collection:'TK宠物用品项目'}],
project_summary:[{project_collection:'TK宠物用品项目',goods_value_rmb:'10560.00',gross_weight_kg:'130',allocated_fees_rmb:'1151.43',total_cost_rmb:'11711.43'}]}}};
console.log(JSON.stringify(h.renderMaterialAIAutofillPreview(fill)));
""")
    assert '本次发货货值 RMB' in html
    assert '10560' in html and 'TK宠物用品项目' in html and '1151.43' in html


def test_edited_preview_does_not_display_obsolete_project_summary():
    result=_frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
const fill={selections:new Set(),manualUpdates:{weight:{item_name:'I',fieldname:'gross_weight_kg',value:20}},
draft:{autofill_preview:{items:[{name:'I'}],project_summary:[{project_collection:'P',allocated_fees_rmb:'1151.43'}]}}};
console.log(JSON.stringify(h.renderMaterialAIAutofillPreview(fill)));
""")
    assert '1151.43' not in result
    assert '重新试算' in result


def test_primary_value_distinguishes_valued_shipment_from_unmatched_purchase():
    result=_frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');h.formatValue=x=>String(x);h.materialAICell=()=>null;
console.log(JSON.stringify(h.renderMaterialFeeGridCell({name:'I',shipment_value_rmb:'10560',
shipment_valuation:{method:'packing_row_total',status:'automatic',error:''}}, {field:'shipment_value_rmb',label:'本次发货货值 RMB',numeric:true,readonly:false},new Set(),0)));
""")
    assert 'value="10560"' in result and '自动估值' in result


def test_shipment_value_is_editable_and_renders_all_escaped_valuation_states():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={};
w.materialFeeState={batchName:'',materialDrafts:{}};
w.escape=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
w.formatValue=v=>String(v??'');w.materialAICell=()=>null;
const column=w.materialFeeGridColumns().find(row=>row.field==='shipment_value_rmb');
const make=(status,value,extra={})=>w.renderMaterialFeeGridCell({name:`I-${status}`,shipment_value_rmb:value,
  shipment_valuation:{status,...extra}},column,new Set(),3);
console.log(JSON.stringify({column,automatic:make('automatic','12.5'),manual:make('manual',0),
  conflict:make('conflict','40',{prior_amount_rmb:'<旧值>',calculated_amount_rmb:'60&新值'}),
  missing:make('missing',''),stale:make('stale',null,{prior_amount_rmb:'25'})}));
""")
    assert result["column"]["readonly"] is False
    assert 'data-mf-cell-input="1"' in result["automatic"] and "自动估值" in result["automatic"]
    assert 'value="0"' in result["manual"] and "人工确认" in result["manual"]
    assert "待确认" in result["conflict"]
    assert "采用旧值" in result["conflict"] and "采用计算值" in result["conflict"]
    assert "&lt;旧值&gt;" in result["conflict"] and "60&amp;新值" in result["conflict"]
    assert "<旧值>" not in result["conflict"] and "60&新值" not in result["conflict"]
    assert 'value=""' in result["missing"] and "待补" in result["missing"]
    assert "数量或单位已变化" in result["stale"]


def test_shipment_value_zero_and_blank_use_existing_single_cell_save_contract():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={batchName:'B',versionName:'V',tab:'documents',editToken:'T',expectedModified:'M'};
const state=w.ensureMaterialFeeState();state.materials={items:[{name:'ZERO',shipment_value_rmb:'9'},{name:'CLEAR',shipment_value_rmb:'5'}]};
w.normalizeErrorMessage=e=>e.message;w.ensureMaterialFeeEditSession=async()=>true;w.loadMaterialFeeWorkspace=async()=>true;
const calls=[];w.call=async(method,args)=>{calls.push({method,args});return {ok:true,batch_modified:`M${calls.length}`}};
function input(item,value,original){const data={};const cell={addClass(){return this},removeClass(){return this},attr(){return this}};return {length:1,
 value,val(){return this.value},attr(name){return {'data-original-value':original,'data-item-name':item,'data-fieldname':'shipment_value_rmb'}[name]},
 data(name,next){if(arguments.length>1){data[name]=next;return this}return data[name]},prop(){return this},closest(){return cell}}}
await w.saveMaterialFeeCell(input('ZERO','0','9'));await w.saveMaterialFeeCell(input('CLEAR','','5'));
console.log(JSON.stringify({calls,pending:state.pendingWrites.size,drafts:state.materialDrafts}));
""")
    assert [call["args"]["value"] for call in result["calls"]] == ["0", ""]
    assert all(call["args"]["fieldname"] == "shipment_value_rmb" for call in result["calls"])
    assert all(call["args"]["edit_token"] == "T" for call in result["calls"])
    assert result["calls"][0]["args"]["expected_modified"] == "M"
    assert result["calls"][1]["args"]["expected_modified"] == "M1"
    assert result["pending"] == 0 and result["drafts"] == {}


def test_shipment_conflict_shortcut_writes_input_and_calls_real_save_method():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);let saved=null,updated=null;
const input={length:1,value:'40',val(next){if(arguments.length){this.value=next;return this}return this.value}};
const cell={find(selector){return selector==='[data-mf-cell-input]'?{...input,first(){return input}}:{length:0}}};
const button={attr:name=>name==='data-value'?'60':'',closest:()=>cell};global.$=value=>value;
w.updateMaterialDraftFromInput=value=>{updated=value.val()};w.saveMaterialFeeCell=async value=>{saved=value.val()};
await w.adoptShipmentValuationCandidate(button);
console.log(JSON.stringify({value:input.value,updated,saved}));
""")
    assert result == {"value": "60", "updated": "60", "saved": "60"}


def test_shipment_value_is_in_bulk_paste_columns_and_goods_value_is_audit_only():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={};w.materialFeeState={batchName:'',showAuxiliary:true};
const columns=w.materialFeeGridColumns();
console.log(JSON.stringify({editable:columns.filter(column=>!column.readonly).map(column=>column.field),
  goods:columns.find(column=>column.field==='goods_value')}));
""")
    assert "shipment_value_rmb" in result["editable"]
    assert "goods_value" not in result["editable"]
    assert result["goods"]["readonly"] is True
    assert result["goods"]["label"] == "货值兼容值 RMB"


def test_nonblocking_purchase_and_manual_notes_are_folded():
    html=_frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
console.log(JSON.stringify(h.renderMaterialAIAutofillPreview({selections:new Set(),draft:{autofill_preview:{
items:[],notes:[{message:'采购待关联；发货货值 10560 已取得，不影响试算。'}]}}})));
""")
    assert '<details class="ocw-mf-ai-review-notes">' in html
    assert '10560' in html and '仍需补充 / 核对' not in html
