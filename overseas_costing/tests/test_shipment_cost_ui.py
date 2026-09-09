from overseas_costing.tests.test_saved_trial_regressions import _frontend_result, FRONTEND_SETUP


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
shipment_valuation:{method:'packing_row_total',error:''}}, {field:'shipment_value_rmb',readonly:true},new Set(),0)));
""")
    assert '10560' in result and '装箱货值已取得' in result


def test_nonblocking_purchase_and_manual_notes_are_folded():
    html=_frontend_result(FRONTEND_SETUP + """
h.escape=x=>String(x ?? '');
console.log(JSON.stringify(h.renderMaterialAIAutofillPreview({selections:new Set(),draft:{autofill_preview:{
items:[],notes:[{message:'采购待关联；发货货值 10560 已取得，不影响试算。'}]}}})));
""")
    assert '<details class="ocw-mf-ai-review-notes">' in html
    assert '10560' in html and '仍需补充 / 核对' not in html
