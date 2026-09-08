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
