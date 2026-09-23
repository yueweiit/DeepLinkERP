from overseas_costing.tests.test_workbench_frontend_state import _fee_workspace_result, PARTS


def test_grid_renderer_preserves_source_blanks_and_separates_results():
    result = _fee_workspace_result('''
    const w = Object.create(Harness.prototype);
    w.escape = v => String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
    w.formatDateTimeMinute = v => v || '';
    w.formatValue = v => String(v ?? '');
    const preview = {source:{kind:'wiki_sheet',label:'<script>bad</script>'},
      source_grid:{header_row:1,cells:[
        [{display_value:'物料'},{display_value:'数量'}],
        [{display_value:'FL000429'},{raw_value:96000,display_value:'96,000'}],
        [{display_value:''},{raw_value:4000,display_value:'4,000'}]],
        merge_ranges:[],candidate_regions:[{start_row:2,end_row:3,start_column:1,end_column:1,reason:'编码待核对'}]},
      rows:[{source_row:2,source_rows:[2,3],incoming:{material_code:'FL000429',actual_shipped_qty:'100000'},physical_status:'incomplete',changes:[]}],
      out_of_batch_groups:[{group_id:'package-9'}]};
    const html=w.renderWikiMaterialImportPreview(preview);
    console.log(JSON.stringify({html}));
    ''')
    html = result['html']
    assert 'data-pg-tab="source"' in html and 'aria-selected="true"' in html
    assert 'data-pg-panel="result"' in html and 'hidden' in html
    assert 'data-pg-cell="3:1"' in html and 'rowspan=' not in html
    assert '96,000' in html and '100000' in html
    assert '净重 kg</th>' in html and '毛重 kg</th>' in html and '体积 m³</th>' in html
    assert '<script>' not in html
    assert 'package-9' not in html
    assert '确认写入物料表' in html and 'class="pg-primary"' in html


def test_grid_real_merge_and_copy_keep_display_and_formula():
    result = _fee_workspace_result('''
    const w=Object.create(Harness.prototype);w.escape=v=>String(v??'');w.formatDateTimeMinute=v=>v;
    const grid={header_row:1,cells:[[{display_value:'物料'}],[{raw_value:'SKU',display_value:'SKU',formula:'=A1'}],[{display_value:''}]],
      merge_ranges:[{start_row:2,end_row:3,start_column:1,end_column:1,evidence_kind:'xlsx_merge'}]};
    const html=w.renderWikiMaterialImportPreview({source:{},source_grid:grid,rows:[]});
    console.log(JSON.stringify({html, text:w.packingSelectionText(grid,{start_row:2,end_row:3,start_column:1,end_column:1}), range:w.parsePackingRange('AA2:AB4')}));
    ''')
    assert 'rowspan="2"' in result['html']
    assert 'data-pg-cell="3:1"' not in result['html']
    assert result['text'] == 'SKU\n'
    assert result['range'] == dict(start_row=2,end_row=4,start_column=27,end_column=28)


def test_grid_blocker_requires_coordinate_reviews_without_internal_ids():
    result = _fee_workspace_result('''
    const w=Object.create(Harness.prototype);
    const preview={source_grid:{cells:[[]]},confirmation_groups:[{group_id:'package-9',row_numbers:[4,5]}]};
    const issue=w.validateWikiMaterialAllocations(preview,{group_confirmations:{'package-9':true}});
    console.log(JSON.stringify({issue}));
    ''')
    assert '4' in result['issue'] and '5' in result['issue']
    assert '原表' in result['issue'] and 'package-9' not in result['issue']


def test_grid_dialog_has_scoped_visible_buttons_and_internal_scroll():
    css_path = PARTS / '49-material-import-grid.css'
    css = css_path.read_text() if css_path.exists() else ''
    assert '.pg-dialog .pg-primary' in css
    assert 'background: #087ef5' in css
    assert 'color: #fff' in css
    assert '.pg-footer' in css and 'flex-shrink: 0' in css
    assert '.pg-grid-scroll' in css and 'overflow: auto' in css
    assert 'position: sticky' in css


def test_grid_constrains_real_frappe_anonymous_body_wrapper_and_native_form():
    css = (PARTS / '49-material-import-grid.css').read_text()
    assert '.pg-dialog .modal-body > div' in css
    assert '.pg-dialog .form-column > form' in css
    assert 'min-width: 0' in css and 'min-height: 0' in css


def test_material_toolbar_wraps_without_clipping_actions():
    css = (PARTS / '48-material-fee-workspace.css').read_text()
    actions = css.split('.ocw-mf-material-toolrow {', 1)[1].split('}', 1)[0]
    groups = css.split('.ocw-mf-material-toolgroup {', 1)[1].split('}', 1)[0]
    title = css.split('.ocw-mf-material-title > div:first-child {', 1)[1].split('}', 1)[0]
    responsive = css.split('@media (max-width: 700px) {', 1)[1].split('.ocw-mf-selection-toolbar', 1)[0]
    assert 'flex-wrap: wrap' in actions
    assert 'justify-content: space-between' in actions
    assert 'overflow: hidden' not in actions and 'flex-wrap: nowrap' not in actions
    assert 'flex-wrap: wrap' in groups and 'min-width: 0' in groups
    assert 'min-width: 0' in title
    assert '.ocw-mf-material-toolrow' in responsive and 'flex-direction: column' in responsive
    assert '.ocw-mf-material-toolgroup.is-data' in responsive
    assert 'width: 100%' in responsive and 'justify-content: flex-start' in responsive


def test_uploaded_xlsx_with_true_grid_uses_same_two_tab_dialog():
    result = _fee_workspace_result('''
    const w=Object.create(Harness.prototype);let configured=0,options;
    w.renderWikiMaterialImportPreview=()=>'<div>GRID</div>';
    w.setupPackingSpreadsheetDialog=()=>configured++;
    global.frappe.ui={Dialog:class {constructor(o){options=o;this.$wrapper={addClass(){return this},on(){return this}}}show(){}}};
    w.openMaterialImportPreviewDialog({source:{kind:'manual_xlsx'},source_grid:{cells:[[]]},rows:[]});
    console.log(JSON.stringify({configured,html:options.fields[0].options,nativePrimary:!!options.primary_action}));
    ''')
    assert result == {'configured':1,'html':'<div>GRID</div>','nativePrimary':False}


def test_range_adjustment_replaces_selected_review_and_undo_is_chronological():
    result = _fee_workspace_result('''
    const w=Object.create(Harness.prototype);let range='B2:B4',requests=[];
    const selection={start_row:2,end_row:3,start_column:2,end_column:2,evidence_kind:'manual_confirmed'};
    const old=[{...selection,action:'confirm'},{start_row:10,end_row:11,start_column:4,end_column:4,action:'separate'}];
    delete old[0].evidence_kind;
    const nodes={val:()=>range,prop(){return this},text(){return this}};
    const preview={source:{kind:'wiki_sheet',id:'WB:S',source_hash:'HASH'},rows:[]};
    const dialog={_ocwMaterialPreview:preview,_pg:{reviews:old,selection,reviewHistory:[],busy:false,closed:false},$wrapper:{find:()=>nodes},fields_dict:{preview:{$wrapper:{html(){}}}}};
    w.detailState={batchName:'B'};w.updatePackingPreviewBlocker=()=>{};w.switchPackingPreviewTab=()=>{};w.renderWikiMaterialImportPreview=()=>'';
    w.call=async(method,args)=>{requests.push(JSON.parse(args.merge_reviews_json).ranges);return {ok:true,...preview,merge_reviews:{ranges:requests.at(-1)}}};
    await w.reviewPackingGridRange(dialog,'confirm');await w.reviewPackingGridRange(dialog,'undo');
    console.log(JSON.stringify({requests,old}));
    ''')
    assert len(result['requests'][0]) == 2
    assert any(r['start_row']==2 and r['end_row']==4 for r in result['requests'][0])
    assert result['requests'][1] == result['old']


def test_range_preview_cancel_ignores_late_result_and_suppresses_double_click():
    result = _fee_workspace_result('''
    const w=Object.create(Harness.prototype);let calls=0,renders=0,release;
    const nodes={val:()=>'B2:B3',prop(){return this},text(){return this}};
    const preview={source:{kind:'wiki_sheet',id:'WB:S',source_hash:'HASH'},rows:[]};
    const dialog={_ocwMaterialPreview:preview,_pg:{reviews:[],reviewHistory:[],busy:false,closed:false},$wrapper:{find:()=>nodes},fields_dict:{preview:{$wrapper:{html(){renders++}}}}};
    w.detailState={batchName:'B'};w.updatePackingPreviewBlocker=()=>{};
    w.call=async()=>{calls++;return await new Promise(r=>release=r)};
    const first=w.reviewPackingGridRange(dialog,'confirm');await w.reviewPackingGridRange(dialog,'confirm');
    dialog._pg.closed=true;release({ok:true,...preview});await first;
    console.log(JSON.stringify({calls,renders,reviews:dialog._pg.reviews,busy:dialog._pg.busy}));
    ''')
    assert result == {'calls':1,'renders':0,'reviews':[],'busy':False}


def test_writing_blocks_modal_close_and_duplicate_submit_then_recovers_on_error():
    result = _fee_workspace_result('''
    const w=Object.create(Harness.prototype);let hide,calls=0,release,prevented=false,disabled=[];
    global.document={};global.$=()=>({off(){}});
    const node={prop(name,value){disabled.push(value);return this},text(){return this}};
    const wrapper={addClass(){return this},on(event,...args){if(event==='hide.bs.modal.pg')hide=args[0];return this},find(){return node}};
    const dialog={$wrapper:wrapper};w.switchPackingPreviewTab=()=>{};w.updatePackingPreviewBlocker=()=>{};
    w.setupPackingSpreadsheetDialog(dialog,{rows:[]});
    w.applyMaterialImport=async()=>{calls++;await new Promise((resolve,reject)=>release=reject)};
    const first=w.confirmPackingSpreadsheet(dialog);await w.confirmPackingSpreadsheet(dialog);
    hide({preventDefault(){prevented=true}});const closed=dialog._pg.closed;
    release(new Error('事务失败'));await first;
    console.log(JSON.stringify({calls,prevented,closed,writing:dialog._pg.writing,busy:dialog._pg.busy,disabled}));
    ''')
    assert result['calls'] == 1 and result['prevented'] is True and result['closed'] is False
    assert result['writing'] is False and result['busy'] is False
    assert result['disabled'][0] is True and result['disabled'][-1] is False


def test_conflicting_real_merges_require_source_correction_not_unavailable_checkbox():
    result = _fee_workspace_result('''
    const w=Object.create(Harness.prototype);
    console.log(JSON.stringify({issue:w.validateWikiMaterialAllocations({source_grid:{cells:[[]]},
      confirmation_groups:[{group_id:'hidden',row_numbers:[2,3,4],source_correction_required:true}]},{})}));
    ''')
    assert '修正原表' in result['issue'] and '2、3、4' in result['issue']


def test_project_and_supplier_cells_use_list_pickers_in_the_main_grid():
    result = _fee_workspace_result(r'''
    const w=new Harness();w.escape=value=>String(value??'');w.formatValue=value=>String(value??'--');
    w.detailState={batchName:'B-1',versionName:'V-1',tab:'documents'};
    const state=w.ensureMaterialFeeState();state.materials={items:[]};
    const columns=w.materialFeeGridColumns();
    const project=w.renderMaterialFeeGridCell({name:'I-1',project_collection:'',requirements:{}},columns.find(row=>row.field==='project_collection'),new Set(),1);
    const invalid=w.renderMaterialFeeGridCell({name:'I-2',project_collection:'YW ODM',requirements:{}},columns.find(row=>row.field==='project_collection'),new Set(),1);
    const supplier=w.renderMaterialFeeGridCell({name:'I-3',supplier:'SUP-001',requirements:{}},columns.find(row=>row.field==='supplier'),new Set(),1);
    console.log(JSON.stringify({fields:columns.map(row=>row.field),project,invalid,supplier}));
    ''')
    assert "supplier" in result["fields"]
    assert result["fields"].index("supplier") < result["fields"].index("project_collection")
    assert 'data-action="mf-open-project-picker"' in result["project"]
    assert '选择项目归属' in result["project"]
    assert '修正' in result["invalid"] and 'YW ODM' in result["invalid"]
    assert 'data-action="mf-open-supplier-picker"' in result["supplier"]
    assert 'data-mf-cell-input' not in result["project"] + result["invalid"] + result["supplier"]


def test_project_picker_groups_candidates_filters_and_keeps_invalid_current_read_only():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.escape=value=>String(value??'');
    const optionsResult={ok:true,route_revision:'R-1',conflicts:[],options:[
      {project_collection:'LatinGo拉丁购',subsidiary_code:'拉丁购国际电子商务（东莞）有限公司',is_approval_candidate:true},
      {project_collection:'YW MOLDES MX模具',subsidiary_code:'YW MOLDES MX模具',is_approval_candidate:false}
    ]};
    const model=w.buildProjectPickerModel([{name:'I-1',project_collection:'YW ODM'}],optionsResult,'');
    const all=w.renderProjectPickerOptions(model);
    const filtered=w.renderProjectPickerOptions({...model,search:'moldes'});
    console.log(JSON.stringify({model,all,filtered}));
    ''')
    assert result["model"]["invalidCurrent"] == ["YW ODM"]
    assert '当前值：YW ODM' in result["all"]
    assert '无有效 ERP 路由' in result["all"]
    assert '本审批候选' in result["all"] and '其他可选项目' in result["all"]
    assert '拉丁购国际电子商务' in result["all"]
    assert 'value="YW ODM"' not in result["all"]
    assert 'YW MOLDES MX模具' in result["filtered"]
    assert 'LatinGo拉丁购' not in result["filtered"]


def test_project_route_options_are_cached_per_batch_and_refresh_on_revision_or_save():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.detailState={batchName:'B-1'};w.ensureMaterialFeeState();
    let calls=0;w.call=async()=>({ok:true,route_revision:`R-${++calls}`,options:[{project_collection:`P-${calls}`,subsidiary_code:'C'}]});
    const first=await w.loadProjectRouteOptions();
    const cached=await w.loadProjectRouteOptions();
    const revised=await w.loadProjectRouteOptions({expectedRevision:'different'});
    w.invalidateProjectRouteOptions();
    const afterSave=await w.loadProjectRouteOptions();
    console.log(JSON.stringify({calls,first:first.route_revision,cached:cached.route_revision,revised:revised.route_revision,afterSave:afterSave.route_revision}));
    ''')
    assert result == {"calls": 3, "first": "R-1", "cached": "R-1", "revised": "R-2", "afterSave": "R-3"}


def test_project_selection_needs_no_reason_keeps_exact_rows_and_ai_draft_non_mutating():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.detailState={batchName:'B-1',versionName:'V-1',editToken:'T',expectedModified:'M'};
    const state=w.ensureMaterialFeeState();state.materials={items:[]};
    w.isMaterialAIReadyStatus=status=>status==='READY';w.renderMaterialFeeWorkspacePreservingPosition=()=>{};
    const blank={name:'A',stable_line_key:'L-A',material_code:'A',project_collection:''};
    const existing={name:'B',stable_line_key:'L-B',material_code:'B',project_collection:'YW ODM'};
    state.aiFill={status:'READY',draftVisible:true,review_mode:true,updates:{},manualUpdates:{},proposals:[],selections:new Set()};
    let writes=0;w.call=async()=>{writes++;return {ok:true}};
    await w.applyProjectCollectionSelection([existing],'LatinGo拉丁购',{aiDraft:true,allowedValues:new Set(['LatinGo拉丁购'])});
    const draft={...state.aiFill.manualUpdates['B:project_collection']};
    state.aiFill=null;w.ensureEditSession=async()=>true;w.updateMaterialFeeExpectedModified=()=>{};w.loadMaterialFeeWorkspace=async()=>true;w.loadProjectRouteOptions=async()=>({ok:true});
    let payload=null;w.call=async(endpoint,args)=>{writes++;payload={endpoint,args};return {ok:true,changed_count:2}};
    await w.applyProjectCollectionSelection([blank,existing],'LatinGo拉丁购',{allowedValues:new Set(['LatinGo拉丁购'])});
    console.log(JSON.stringify({writes,draft,updates:JSON.parse(payload.args.updates)}));
    ''')
    assert result["draft"] == {
        "item_name": "B",
        "fieldname": "project_collection",
        "value": "LatinGo拉丁购",
    }
    assert result["writes"] == 1
    assert [row["item_name"] for row in result["updates"]] == ["A", "B"]
    assert all(row["remark"] == "设置 ERP 项目归属" for row in result["updates"])


def test_project_single_bulk_and_correction_entries_share_one_picker():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.detailState={batchName:'B'};const state=w.ensureMaterialFeeState();
    state.materials={packing_group_editable:true,packing_groups:[],items:[
      {name:'A',stable_line_key:'L-A',project_collection:''},{name:'B',stable_line_key:'L-B',project_collection:'YW ODM'}
    ]};state.packingGroupSelections=new Set(['L-A']);
    const calls=[];w.openProjectCollectionPicker=async request=>{calls.push({source:request.source,names:request.items.map(row=>row.name),suggestedValue:request.suggestedValue||''})};
    await w.openProjectCollectionForItem('A');await w.openProjectCollectionForItem('B');await w.openProjectCollectionDialog();
    state.aiFill={status:'READY',draftVisible:true,updates:{'A:project_collection':{value:'LatinGo拉丁购'}},manualUpdates:{}};
    await w.openProjectCollectionForItem('A');
    console.log(JSON.stringify({calls}));
    ''')
    assert result["calls"] == [
        {"source": "cell", "names": ["A"], "suggestedValue": ""},
        {"source": "cell", "names": ["B"], "suggestedValue": ""},
        {"source": "bulk", "names": ["A"], "suggestedValue": ""},
        {"source": "cell", "names": ["A"], "suggestedValue": "LatinGo拉丁购"},
    ]


def test_supplier_picker_offers_existing_and_create_without_reason_and_targets_exact_rows():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.escape=value=>String(value??'');w.detailState={batchName:'B-1',versionName:'V',editToken:'T',expectedModified:'M'};
    const state=w.ensureMaterialFeeState();state.materials={items:[]};
    let queries=[];w.call=async(endpoint,args)=>{queries.push({endpoint,args});return {raw_value:args.raw_value,status:'SUGGESTED',canonical_supplier:'',candidates:[
      {name:'SUP-001',supplier_name:'Alpha Trading',score:0.94,high_confidence:true},
      {name:'SUP-002',supplier_name:'Alpha Tools',score:0.78,high_confidence:false}
    ]}};
    const model=await w.loadSupplierResolution('Alpha Tradng');const html=w.renderSupplierPickerOptions(model,{kind:'create',value:'Alpha Tradng'});
    const rows=[{name:'A',stable_line_key:'L-A',material_code:'A',supplier:''},{name:'C',stable_line_key:'L-C',material_code:'C',supplier:'SUP-OLD'}];
    w.ensureEditSession=async()=>true;w.updateMaterialFeeExpectedModified=()=>{};w.loadMaterialFeeWorkspace=async()=>true;
    let saved=null;w.call=async(endpoint,args)=>{saved={endpoint,args};return {ok:true,changed_count:2}};
    await w.applySupplierSelection(rows,'SUP-001',{allowedValues:new Set(model.options.map(row=>row.name))});
    console.log(JSON.stringify({queries,model,html,updates:JSON.parse(saved.args.updates)}));
    ''')
    assert [row["name"] for row in result["model"]["options"]] == ["SUP-001", "SUP-002"]
    assert '高置信候选' in result["html"] and 'Alpha Trading' in result["html"]
    assert '新建供应商：Alpha Tradng' in result["html"]
    assert '这是不同供应商' in result["html"]
    assert [row["item_name"] for row in result["updates"]] == ["A", "C"]
    assert all(row["fieldname"] == "supplier" for row in result["updates"])
    assert all(row["remark"] == "设置 ERP 供应商" for row in result["updates"])


def test_supplier_exact_match_becomes_a_selectable_canonical_option():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.detailState={batchName:'B-1'};w.ensureMaterialFeeState();
    w.call=async()=>({raw_value:'Alpha Trading',status:'EXACT',canonical_supplier:'SUP-001',candidates:[]});
    const model=await w.loadSupplierResolution('Alpha Trading');
    console.log(JSON.stringify({model}));
    ''')
    assert result["model"]["options"] == [{
        "name": "SUP-001",
        "supplier_name": "SUP-001",
        "score": 1,
        "exact": True,
    }]
    assert result["model"]["canCreate"] is False


def test_supplier_creation_uses_post_then_existing_batch_update_and_invalidates_cache():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.detailState={batchName:'B-1',versionName:'V',editToken:'T',expectedModified:'M'};
    const state=w.ensureMaterialFeeState();state.materials={items:[]};state.supplierOptionsCache.set('old',{ok:true});
    w.ensureEditSession=async()=>true;w.updateMaterialFeeExpectedModified=()=>{};w.loadMaterialFeeWorkspace=async()=>true;
    const calls=[];w.call=async(endpoint,args,_freeze,request)=>{calls.push({endpoint,args,request});if(endpoint.endsWith('create_supplier_from_workbench'))return {ok:true,created:true,supplier:'SUP-NEW',supplier_name:'New Supplier'};return {ok:true,changed_count:1};};
    const rows=[{name:'A',stable_line_key:'L-A',supplier:''}];
    const response=await w.createSupplierAndApply(rows,' New Supplier ',false);
    console.log(JSON.stringify({response,calls,cacheSize:state.supplierOptionsCache.size,updates:JSON.parse(calls[1].args.updates)}));
    ''')
    assert result["calls"][0]["endpoint"].endswith("create_supplier_from_workbench")
    assert result["calls"][0]["request"] == {"type": "POST"}
    assert result["calls"][0]["args"]["supplier_name"] == "New Supplier"
    assert result["calls"][1]["endpoint"].endswith("batch_update_items")
    assert result["updates"] == [{
        "item_name": "A",
        "fieldname": "supplier",
        "value": "SUP-NEW",
        "remark": "新建 ERP 供应商并设置物料",
    }]
    assert result["cacheSize"] == 0


def test_ai_final_material_preview_has_supplier_before_project_and_escapes_blank():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.escape=value=>String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
    w.materialAIReviewHasStageSnapshots=()=>true;
    w.ensureMaterialAIRowSelection=()=>({previewKey:'KEY',preview:{rows:[
      {material_code:'A',product_name:'One',supplier:'SUP-OK',project_collection:'LatinGo拉丁购'},
      {material_code:'B',product_name:'Two',supplier:'',project_collection:'<script>bad</script>'}
    ],missing_fields:[]},mode:'fill_missing',rows:new Set(),fields:new Set(),fees:new Set(),packingAssignments:new Map(),loading:false,error:''});
    w.materialAIRowSelectionKey=()=> 'KEY';w.materialAIFeeSelectionPolicy=()=>({fees:[],mainFees:[]});w.renderMaterialAIFeeStages=()=>'';w.materialReplacementRows=()=>[];w.renderMaterialAIReviewSources=()=>'';w.canConfirmMaterialAIRowSelection=()=>false;
    const fill={row_review:{fee_stage_snapshots:[],rows:[]},draft:{},proposals:[],updates:{},manualUpdates:{}};
    const html=w.renderMaterialAIRowReview(fill);
    console.log(JSON.stringify({html}));
    ''')
    html = result["html"]
    assert html.index("<th>供应商</th>") < html.index("<th>项目归属</th>")
    assert "SUP-OK" in html and ">—</td>" in html
    assert "<script>" not in html and "&lt;script>bad&lt;/script>" in html


def test_project_and_supplier_picker_dialogs_have_no_reason_field_or_reason_helper():
    source = (PARTS / "78-material-fee-workspace.js").read_text(encoding="utf-8")
    picker_segment = source.split("async openProjectCollectionPicker", 1)[1].split("async openMaterialPackingGroupDialog", 1)[0]
    assert 'fieldname:"reason"' not in picker_segment
    assert "referenceSelectionRequiresReason" not in source


def test_material_toolbar_exposes_supplier_bulk_action():
    result = _fee_workspace_result(r'''
    const w=Object.create(Harness.prototype);w.escape=value=>String(value??'');w.detailState={batchName:'B'};
    const state=w.ensureMaterialFeeState();state.materials={packing_group_editable:true,packing_groups:[],items:[{name:'A',stable_line_key:'L-A'}]};state.packingGroupSelections=new Set(['L-A']);
    console.log(JSON.stringify({html:w.renderMaterialSelectionToolbar(),actions:w.materialSelectionContext().actions}));
    ''')
    assert 'data-action="mf-set-supplier"' in result["html"]
    assert '批量设置供应商' in result["html"]
    assert result["actions"]["supplier"]["enabled"] is True


def test_reference_picker_layout_is_compact_scrollable_and_responsive():
    css = (PARTS / "48-material-fee-workspace.css").read_text(encoding="utf-8")
    assert ".ocw-mf-reference-picker-dialog" in css
    assert ".ocw-mf-reference-group" in css
    assert "max-height:" in css and "overflow-y: auto" in css
    assert ".ocw-mf-reference-option" in css
    responsive = css.split("@media (max-width: 700px)", 1)[1]
    assert ".ocw-mf-reference-option" in responsive
    assert "grid-template-columns: minmax(0, 1fr)" in responsive
