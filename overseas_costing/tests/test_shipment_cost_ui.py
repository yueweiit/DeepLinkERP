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


def test_saved_trial_rows_show_comparable_unit_price_and_comprehensive_unit_price():
    html = _frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
h.detailState.header={status:'Calculated',summary_snapshot:{comprehensive_cost:{summary:{is_complete:true,total_cost_rmb:'4795.57'},items:[{
  material_code:'CW000214',product_name:'狗牌Dog tag',goods_value_rmb:'2067.00',direct_fees_rmb:'0.00',
  allocated_fees_rmb:'2728.57',total_cost_rmb:'4795.57',
  shipping_unit_price:{amount_rmb:'1.215882',uom:'个'},
  shipping_unit_cost:{amount_rmb:'2.820924',uom:'个'},
  purchase_pricing_unit_cost:{amount_rmb:'999.000000',uom:'箱'}
}]}}};
console.log(JSON.stringify(h.renderMaterialFeeCostTable()));
""")

    assert "单价（RMB）" in html
    assert "综合单价（RMB）" in html
    assert "1.22 / 个" in html
    assert "2.82 / 个" in html
    assert "1.215882" not in html
    assert "2.820924" not in html
    assert "999.000000" not in html
    assert "每发货单位" not in html
    assert "每采购计价单位" not in html


def test_saved_trial_rows_explain_missing_unit_price_inputs():
    html = _frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
h.detailState.header={status:'Calculated',summary_snapshot:{comprehensive_cost:{summary:{is_complete:false,total_cost_rmb:'50.00'},items:[
  {material_code:'MISSING-VALUE',product_name:'货值待补',goods_value_rmb:'0.00',direct_fees_rmb:'0.00',allocated_fees_rmb:'50.00',total_cost_rmb:'50.00',
   valuation_source:{error:'GOODS_VALUE_MISSING'},shipping_unit_price:null,shipping_unit_cost:{amount_rmb:'10.000000',uom:'个'}},
  {material_code:'MISSING-QUANTITY',product_name:'数量待补',goods_value_rmb:'20.00',direct_fees_rmb:'0.00',allocated_fees_rmb:'0.00',total_cost_rmb:'20.00',
   shipping_unit_price:null,shipping_unit_cost:null},
  {material_code:'LEGACY-SNAPSHOT',product_name:'旧试算',goods_value_rmb:'30.00',direct_fees_rmb:'0.00',allocated_fees_rmb:'15.00',total_cost_rmb:'45.00',
   valuation_source:{error:''},shipping_unit_cost:{amount_rmb:'15.000000',uom:'个'}}
]}}};
console.log(JSON.stringify(h.renderMaterialFeeCostTable()));
""")

    assert "货值待补" in html
    assert html.count("待补发货数量/单位") == 2
    assert "10.00 / 个" in html
    assert "重新试算后显示" in html


def test_derived_purchase_price_is_readonly_and_names_its_source():
    html = _frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
const item={name:'I1',unit_price:'1.22',adopted_price:{value:'1.22',currency:'RMB',unit:'pieza',source_type:'purchase_total_derived',error:''}};
console.log(JSON.stringify(h.renderMaterialFeeGridCell(item,{field:'unit_price',label:'采购单价',numeric:true},new Set(),0)));
""")

    assert "1.22" in html
    assert "按总货值÷采购数量计算" in html
    assert "data-mf-cell-input" not in html


def test_material_fee_workspace_has_no_second_trial_entry_and_keeps_status_guidance() -> None:
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={header:{status:'Dirty'}};
const state=w.ensureMaterialFeeState();state.materials={packing_groups:[{
  group_id:'G-OLD',status:'confirmed',blocking:true,member_keys:['OLD-1','OLD-2']}],items:[]};
state.fees={summary:{}};state.preview={summary:{is_complete:false},items:[],incomplete_reasons:[]};
w.escape=value=>String(value??'');w.materialFeeSavedCostPreview=()=>null;
const html=w.renderMaterialFeeCostTable();
console.log(JSON.stringify({html,blocked:w.hasBlockingPackingGroups(state)}));
""")

    assert result["blocked"] is True
    assert 'data-action="mf-preview-cost"' not in result["html"]
    assert "请使用页头开始试算" in result["html"]
    assert "请先重新确认装箱组" in result["html"]


def test_material_fee_workspace_with_preview_keeps_adjustment_but_no_trial_entry() -> None:
    html = _frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
h.detailState.header={status:'Calculated',summary_snapshot:{comprehensive_cost:{summary:{is_complete:true,total_cost_rmb:'100.00'},items:[]}}};
console.log(JSON.stringify(h.renderMaterialFeeCostTable()));
""")
    assert 'data-action="mf-adjust-cost"' in html
    assert 'data-action="mf-preview-cost"' not in html


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
    assert '>10560<' in result and '自动估值' in result
    assert 'data-action="mf-correct-purchase"' in result and '<input' not in result


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
    assert 'data-mf-cell-input="1"' not in result["automatic"] and "自动估值" in result["automatic"]
    assert 'data-action="mf-correct-purchase"' in result["automatic"]
    assert '>0<' in result["manual"] and "人工确认" in result["manual"]
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


MATERIAL_CELL_QUEUE_FIXTURE = r"""
const w=Object.create(Harness.prototype);w.detailState={batchName:'B',versionName:'V',tab:'documents',editToken:'T',expectedModified:'M1'};
const state=w.ensureMaterialFeeState();state.materials={items:[{name:'I',shipment_value_rmb:'40'}]};
w.normalizeErrorMessage=error=>error.message;w.ensureMaterialFeeEditSession=async()=>true;w.loadMaterialFeeWorkspace=async()=>true;
const calls=[];const releases=[];let active=0,maxActive=0;
w.call=async(method,args)=>{calls.push({method,args});active+=1;maxActive=Math.max(maxActive,active);
  const result=await new Promise(resolve=>releases.push(resolve));active-=1;return result};
const data={};const classes=new Set();const cell={addClass(name){classes.add(name);return this},removeClass(name){classes.delete(name);return this},attr(){return this},
  find(selector){return selector==='[data-mf-cell-input]'?{first(){return input}}:{length:0}}};
const input={length:1,value:'40',val(next){if(arguments.length){this.value=String(next);return this}return this.value},
  attr(name){return {'data-original-value':'40','data-item-name':'I','data-fieldname':'shipment_value_rmb'}[name]},
  data(name,next){if(arguments.length>1){data[name]=next;return this}return data[name]},prop(){return this},closest(){return cell}};
const button=value=>({attr:name=>name==='data-value'?String(value):'',closest:()=>cell});global.$=value=>value;
"""


def test_two_fast_shipment_shortcuts_serialize_and_save_latest_value():
    result = _fee_workspace_result(MATERIAL_CELL_QUEUE_FIXTURE + r"""
const first=w.adoptShipmentValuationCandidate(button(60));await new Promise(resolve=>setImmediate(resolve));
const second=w.adoptShipmentValuationCandidate(button(70));await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(calls.map(call=>call.args.value),['60']);
releases.shift()({ok:true,batch_modified:'M2'});await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(calls.map(call=>call.args.value),['60','70']);
releases.shift()({ok:true,batch_modified:'M3'});await Promise.all([first,second]);
console.log(JSON.stringify({values:calls.map(call=>call.args.value),modified:calls.map(call=>call.args.expected_modified),
  maxActive,pending:state.pendingWrites.size,drafts:state.materialDrafts,errors:state.materialSaveErrors}));
""")
    assert result == {
        "values": ["60", "70"],
        "modified": ["M1", "M2"],
        "maxActive": 1,
        "pending": 0,
        "drafts": {},
        "errors": {},
    }


def test_queued_shipment_save_failure_preserves_latest_draft_and_error():
    result = _fee_workspace_result(MATERIAL_CELL_QUEUE_FIXTURE + r"""
const first=w.adoptShipmentValuationCandidate(button(60));await new Promise(resolve=>setImmediate(resolve));
const second=w.adoptShipmentValuationCandidate(button(70));
releases.shift()({ok:true,batch_modified:'M2'});await new Promise(resolve=>setImmediate(resolve));
releases.shift()({ok:false,message:'并发保存失败'});await Promise.all([first,second]);
console.log(JSON.stringify({values:calls.map(call=>call.args.value),maxActive,pending:state.pendingWrites.size,
  draft:state.materialDrafts['I:shipment_value_rmb'],error:state.materialSaveErrors['I:shipment_value_rmb']}));
""")
    assert result["values"] == ["60", "70"] and result["maxActive"] == 1
    assert result["pending"] == 0
    assert result["draft"]["value"] == "70"
    assert result["draft"]["error"] == "并发保存失败"
    assert result["error"] == "并发保存失败"


def test_fast_regular_input_returning_to_saved_value_is_serialized_and_clears_draft():
    result = _fee_workspace_result(MATERIAL_CELL_QUEUE_FIXTURE + r"""
input.value='60';const first=w.saveMaterialFeeCell(input);await new Promise(resolve=>setImmediate(resolve));
input.value='40';const second=w.saveMaterialFeeCell(input);
releases.shift()({ok:true,batch_modified:'M2'});await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(calls.map(call=>call.args.value),['60','40']);
releases.shift()({ok:true,batch_modified:'M3'});await Promise.all([first,second]);
console.log(JSON.stringify({values:calls.map(call=>call.args.value),modified:calls.map(call=>call.args.expected_modified),
  maxActive,pending:state.pendingWrites.size,drafts:state.materialDrafts,errors:state.materialSaveErrors}));
""")
    assert result == {
        "values": ["60", "40"],
        "modified": ["M1", "M2"],
        "maxActive": 1,
        "pending": 0,
        "drafts": {},
        "errors": {},
    }


def test_queued_failure_marks_rerendered_live_cell_and_live_retry_succeeds():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={batchName:'B',versionName:'V',tab:'documents',editToken:'T',expectedModified:'M1'};
const state=w.ensureMaterialFeeState();state.materials={items:[{name:'I',shipment_value_rmb:'40'}]};
w.normalizeErrorMessage=error=>error.message;w.ensureMaterialFeeEditSession=async()=>true;
function makeInput(value,original){const data={};const classes=new Set();const attrs={title:''};const cell={classes,attrs,
  addClass(name){classes.add(name);return this},removeClass(name){name.split(/\s+/).forEach(value=>classes.delete(value));return this},
  attr(name,next){if(arguments.length>1){attrs[name]=next;return this}return attrs[name]}};
  const input={length:1,value,cell,val(next){if(arguments.length){this.value=String(next);return this}return this.value},
    attr(name){return {'data-original-value':original,'data-item-name':'I','data-fieldname':'shipment_value_rmb'}[name]},
    data(name,next){if(arguments.length>1){data[name]=next;return this}return data[name]},prop(){return this},closest(){return cell}};
  return input}
const oldInput=makeInput('60','40');const liveInput=makeInput('70','60');let currentInput=oldInput;let reloads=0;
global.$=value=>value;w.$root={find(selector){return selector==='[data-mf-cell-input]'?{each(callback){callback(0,currentInput)}}:{each(){}}}};
w.loadMaterialFeeWorkspace=async()=>{reloads+=1;if(reloads===1){state.materials.items[0].shipment_value_rmb='60';currentInput=liveInput}return true};
const calls=[];const releases=[];let active=0,maxActive=0;w.call=async(method,args)=>{calls.push({method,args});active+=1;maxActive=Math.max(maxActive,active);
  const result=await new Promise(resolve=>releases.push(resolve));active-=1;return result};
const first=w.saveMaterialFeeCell(oldInput);await new Promise(resolve=>setImmediate(resolve));
oldInput.value='70';const second=w.saveMaterialFeeCell(oldInput);
releases.shift()({ok:true,batch_modified:'M2'});await new Promise(resolve=>setImmediate(resolve));
releases.shift()({ok:false,message:'第二次失败'});await Promise.all([first,second]);
const afterFailure={liveError:liveInput.cell.classes.has('is-save-error'),liveTitle:liveInput.cell.attrs.title,
  oldError:oldInput.cell.classes.has('is-save-error'),draft:state.materialDrafts['I:shipment_value_rmb'],pending:state.pendingWrites.size};
const retry=w.saveMaterialFeeCell(liveInput);await new Promise(resolve=>setImmediate(resolve));
releases.shift()({ok:true,batch_modified:'M3'});await retry;
console.log(JSON.stringify({afterFailure,values:calls.map(call=>call.args.value),modified:calls.map(call=>call.args.expected_modified),
  maxActive,pending:state.pendingWrites.size,drafts:state.materialDrafts,errors:state.materialSaveErrors,
  liveError:liveInput.cell.classes.has('is-save-error'),liveTitle:liveInput.cell.attrs.title}));
""")
    assert result["afterFailure"]["liveError"] is True
    assert "第二次失败" in result["afterFailure"]["liveTitle"]
    assert result["afterFailure"]["oldError"] is False
    assert result["afterFailure"]["draft"]["value"] == "70"
    assert result["afterFailure"]["draft"]["error"] == "第二次失败"
    assert result["afterFailure"]["pending"] == 0
    assert result["values"] == ["60", "70", "70"]
    assert result["modified"] == ["M1", "M2", "M2"]
    assert result["maxActive"] == 1
    assert result["pending"] == 0 and result["drafts"] == {} and result["errors"] == {}
    assert result["liveError"] is False and result["liveTitle"] == ""


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


def test_material_grid_starts_with_selection_and_row_number_without_actions_column():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={};w.ensureMaterialFeeState();
const columns=w.materialFeeGridColumns();
console.log(JSON.stringify({fields:columns.map(column=>column.field)}));
""")
    assert result["fields"][:4] == ["__group_select", "row_no", "material_code", "product_name"]
    assert "__actions" not in result["fields"]


def test_packing_group_renders_true_rowspan_without_per_row_actions():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={};const state=w.ensureMaterialFeeState();
w.escape=v=>String(v??'');w.formatValue=v=>String(v??'');w.materialAICell=()=>null;
const group={group_id:'G1',member_keys:['L1','L2','L3'],package_count:'21',net_weight_kg:'389',
 gross_weight_kg:'397.7',volume_m3:'0.40884',rowspan:3};
const first={name:'I1',stable_line_key:'L1',packing_group_id:'G1',packing_group_position:0,packing_group_size:3,packing_group:group};
const second={name:'I2',stable_line_key:'L2',packing_group_id:'G1',packing_group_position:1,packing_group_size:3,packing_group:{...group,rowspan:0}};
const columns=w.materialFeeGridColumns();const physical=columns.filter(c=>['package_count','net_weight_kg','gross_weight_kg','volume_m3'].includes(c.field));
const rendered=physical.map((column,index)=>w.renderMaterialFeeGridCell(first,column,new Set(),index)).join('');
const hidden=physical.map((column,index)=>w.renderMaterialFeeGridCell(second,column,new Set(),index)).join('');
console.log(JSON.stringify({rendered,hidden,fields:physical.map(c=>c.field)}));
""")
    assert result["fields"] == ["package_count", "net_weight_kg", "gross_weight_kg", "volume_m3"]
    assert result["rendered"].count('rowspan="3"') == 4
    assert all(value in result["rendered"] for value in ["21", "389", "397.7", "0.40884"])
    assert result["hidden"] == ""


def test_historical_material_grid_disables_packing_group_edits():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={readOnly:true};const state=w.ensureMaterialFeeState();
state.materials={packing_group_editable:false};w.escape=v=>String(v??'');w.formatValue=v=>String(v??'');
const item={name:'I1',stable_line_key:'L1',packing_group_id:'G1',packing_group_position:0,packing_group_size:2,packing_group:{group_id:'G1'}};
const columns=w.materialFeeGridColumns();
const select=w.renderMaterialFeeGridCell(item,columns.find(c=>c.field==='__group_select'),new Set(),3);
console.log(JSON.stringify({select,fields:columns.map(column=>column.field)}));
""")
    assert 'disabled' in result['select']
    assert '__actions' not in result['fields']


def test_material_selection_expands_whole_group_and_toolbar_enforces_action_matrix():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={readOnly:false};const state=w.ensureMaterialFeeState();
state.materials={packing_group_editable:true,items:[
  {stable_line_key:'L1',row_no:1,packing_group_id:'G1'},
  {stable_line_key:'L2',row_no:2,packing_group_id:'G1'},
  {stable_line_key:'L3',row_no:3},{stable_line_key:'L4',row_no:4}],
  packing_groups:[{group_id:'G1',member_keys:['L1','L2','LX'],status:'confirmed'}]};
state.packingGroupSelections=new Set();
w.toggleMaterialSelection('L1',true);
const group=w.materialSelectionContext();
w.toggleMaterialSelection('L2',false);
const cleared=[...state.packingGroupSelections];
state.packingGroupSelections=new Set(['L3','L4']);
const merge=w.materialSelectionContext();
state.packingGroupSelections=new Set(['L1','L2','LX','L3']);
const mixed=w.materialSelectionContext();
console.log(JSON.stringify({group:{selected:[...group.selectedKeys],cross:group.crossPageCount,
  edit:group.actions.edit.enabled,unmerge:group.actions.unmerge.enabled,merge:group.actions.merge.enabled},
  cleared,merge:merge.actions.merge,mixed:{edit:mixed.actions.edit,unmerge:mixed.actions.unmerge,
  remove:mixed.actions.remove}}));
""")
    assert result['group']['selected'] == ['L1', 'L2', 'LX']
    assert result['group']['cross'] == 1
    assert result['group']['edit'] is True and result['group']['unmerge'] is True
    assert result['group']['merge'] is False
    assert result['cleared'] == []
    assert result['merge']['enabled'] is True
    assert result['mixed']['edit']['enabled'] is False
    assert result['mixed']['unmerge']['enabled'] is False
    assert result['mixed']['remove']['enabled'] is True


def test_material_page_checkbox_is_tristate_and_toolbar_is_always_rendered():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={readOnly:false};const state=w.ensureMaterialFeeState();
w.escape=v=>String(v??'');
state.materials={packing_group_editable:true,items:[
  {stable_line_key:'L1',row_no:1},{stable_line_key:'L2',row_no:2}],packing_groups:[]};
state.packingGroupSelections=new Set(['L1']);
const partial=w.materialPageSelectionState();
const toolbar=w.renderMaterialSelectionToolbar();
w.toggleMaterialPageSelection(true);
const all=w.materialPageSelectionState();
w.toggleMaterialPageSelection(false);
const none=w.materialPageSelectionState();
console.log(JSON.stringify({partial,all,none,toolbar}));
""")
    assert result['partial']['indeterminate'] is True and result['partial']['checked'] is False
    assert result['all']['checked'] is True and result['all']['indeterminate'] is False
    assert result['none']['checked'] is False and result['none']['indeterminate'] is False
    for label in ['已选 1 行', '新增物料', '合并装箱组', '编辑装箱组', '解除合并', '删除所选', '清除选择']:
        assert label in result['toolbar']


def test_top_toolbar_uses_atomic_batch_endpoints_and_clears_only_after_success():
    result = _fee_workspace_result(r"""
const w=Object.create(Harness.prototype);w.detailState={batchName:'B',versionName:'V',expectedModified:'M'};
const state=w.ensureMaterialFeeState();state.materials={packing_group_editable:true,items:[
  {name:'I1',stable_line_key:'L1',packing_group_id:'G1'},
  {name:'I2',stable_line_key:'L2',packing_group_id:'G1'}],
  packing_groups:[{group_id:'G1',member_keys:['L1','L2'],status:'confirmed'}]};
state.fees={};state.preview={};state.packingGroupSelections=new Set(['L1','L2']);
const calls=[];w.ensureEditSession=async()=>true;w.updateMaterialFeeExpectedModified=()=>{};
w.loadMaterialFeeWorkspace=async()=>true;w.showError=()=>{};
frappe.confirm=(message,yes)=>yes();
w.call=async(method,args)=>{calls.push({method,args});
  if(method.endsWith('preview_material_packing_group_batch')) return {ok:true,preview_id:'P',revision:'R',affected_member_keys:['L1','L2']};
  return {ok:true,removed_group_ids:['G1'],excluded_count:2,batch_modified:'M2'};};
await w.removeSelectedPackingGroups();
const afterUnmerge=state.packingGroupSelections.size;
state.packingGroupSelections=new Set(['L1','L2']);
await w.excludeSelectedMaterials();
const afterDelete=state.packingGroupSelections.size;
state.packingGroupSelections=new Set(['L1','L2']);
w.call=async()=>({ok:false,message:'network failed'});
await w.excludeSelectedMaterials();
console.log(JSON.stringify({methods:calls.map(call=>call.method),afterUnmerge,afterDelete,
  afterFailure:[...state.packingGroupSelections]}));
""")
    assert result['methods'] == [
        'overseas_costing.api.materials.preview_material_packing_group_batch',
        'overseas_costing.api.materials.confirm_material_packing_group_batch',
        'overseas_costing.api.materials.exclude_material_items',
    ]
    assert result['afterUnmerge'] == 0 and result['afterDelete'] == 0
    assert result['afterFailure'] == ['L1', 'L2']


def test_nonblocking_purchase_and_manual_notes_are_folded():
    html=_frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
console.log(JSON.stringify(h.renderMaterialAIAutofillPreview({selections:new Set(),draft:{autofill_preview:{
items:[],notes:[{message:'采购待关联；发货货值 10560 已取得，不影响试算。'}]}}})));
""")
    assert '<details class="ocw-mf-ai-review-notes">' in html
    assert '10560' in html and '仍需补充 / 核对' not in html
