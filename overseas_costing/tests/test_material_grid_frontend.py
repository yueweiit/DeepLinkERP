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
