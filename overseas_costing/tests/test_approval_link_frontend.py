import json
from pathlib import Path
import subprocess

PARTS = Path(__file__).resolve().parents[1] / 'page/overseas_cost_workbench/parts'


def render(script):
    loader = "const fs=require('fs');const source=['78-material-fee-workspace.js','79-material-import-grid.js','82-detail-page.js'].map(n=>fs.readFileSync("+json.dumps(str(PARTS))+"+'/'+n,'utf8')).join('');const Harness=Function('return class Harness {'+source+'}')();"
    setup = """
const h=new Harness();
h.escape=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
h.formatValue=v=>String(v??'');h.detailState={batchName:'B',versionName:'V'};
"""
    result = subprocess.run(['node', '-e', loader+setup+script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def test_material_source_marker_is_readonly_and_does_not_become_calculation_missing():
    html = render("""
console.log(JSON.stringify(h.renderMaterialFeeGridRow({name:'I',source_doc_no:'A',
approval_link:{status:'unresolved',label:'采购审批待核实',reason:'尚未同步',approval_no:'A'},requirements:{missing_fields:[]}},
[{field:'source_doc_no',label:'采购审批号',readonly:true}],0)));
""")
    assert '采购审批待核实' in html and '尚未同步' in html
    assert 'ocw-approval-row' in html and '<details' in html
    assert 'data-mf-cell-input' not in html and 'is-missing' not in html


def test_linked_approval_has_no_warning_and_marker_escapes_source_text():
    result = render("""
console.log(JSON.stringify({normal:h.renderApprovalLinkMarker({status:'linked',label:'已关联'}),
warning:h.renderApprovalLinkMarker({status:'unlinked',label:'未关联采购审批',reason:'<script>bad()</script>',approval_no:'" onclick="bad()'})}));
""")
    assert result['normal'] == ''
    assert '<script>' not in result['warning']
    assert '&lt;script&gt;' in result['warning']


def test_source_grid_marks_unmatched_rows_without_changing_excel_coordinates():
    html = render("""
console.log(JSON.stringify(h.renderPackingSourceGrid({header_row:1,
cells:[[{display_value:'物料'}],[{display_value:'SKU-A'}],[{display_value:'SKU-B'}]],
row_states:[{source_row:2,state:'outside',match_status:'unmatched',match_label:'未匹配本批采购明细'},
{source_row:3,state:'choice_required',match_status:'choice_required',match_label:'采购明细匹配不唯一'}]})));
""")
    assert '未匹配本批采购明细' in html and '采购明细匹配不唯一' in html
    assert 'data-pg-cell="2:1"' in html and 'data-pg-cell="3:1"' in html
    assert 'data-pg-source-row="2"' in html and '来源状态' in html
    assert '钉钉审批不存在' not in html


def test_sku_approval_column_is_never_editable():
    html = render("""
console.log(JSON.stringify(h.renderSkuPageCell({name:'I',approval_link:{status:'error',label:'来源核验失败，请重试',reason:'请刷新资料'}},
{fieldname:'approval_link',label:'采购审批来源'},4)));
""")
    assert '来源核验失败，请重试' in html
    assert 'data-editable-cell="0"' in html
    assert '[object Object]' not in html


def test_import_result_keeps_source_rows_and_displays_approval_marker():
    html = render("""
console.log(JSON.stringify(h.renderPackingResultGrid({rows:[{source_row:2,source_rows:[2,4],
incoming:{material_code:'SKU'},target:{source_doc_no:'A'},physical_status:'complete',
approval_link:{status:'unresolved',label:'采购审批待核实',reason:'尚未同步'}}]})));
""")
    assert '采购审批待核实' in html and 'data-pg-locate="2"' in html
    assert '2、4' in html and '可导入' in html
