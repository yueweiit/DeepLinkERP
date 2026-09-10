"""Native comparison page calculation, paste and asynchronous save regressions."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / 'overseas_costing/page/air_sea_cost_comparison'
JS = PAGE / 'air_sea_cost_comparison.js'


def run_js(body):
    assert JS.exists(), 'Native air/sea page calculator has not been implemented'
    source = f'''const vm = require('vm');const fs = require('fs');
const ctx={{console,crypto:require('crypto').webcrypto}};vm.createContext(ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(JS))},'utf8'),ctx);
const C=ctx.OverseasAirSeaCalculator;
const row=(patch={{}})=>Object.assign(Array(30).fill(''),{{1:'SKU',4:'PZ',20:'100',23:'10',25:'2'}},patch);
const payload=(patch={{}})=>({{rows:[row()],parameters:{{}},currencies:{{}},source:null,...patch}});
(async()=>{{{body}}})().catch(e=>{{console.error(e);process.exit(1)}});'''
    result = subprocess.run(['node', '-e', source], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_original_formula_and_zero_price_are_preserved():
    result = run_js('const r=C.calculate(payload());const zero=C.calculate(payload({rows:[row({25:"0",26:"999"})]}));console.log(JSON.stringify({r,zero}));')
    r = result['r']
    assert r['status'] == 'Ready' and r['unit'] == '件'
    assert r['oceanDeclared'] == pytest.approx(1402)
    assert r['airTransport'] == 2400
    assert r['oceanDta'] == pytest.approx((3482.575 + 1402) * .0008)
    assert r['oceanTotal'] == pytest.approx(3482.575 + (3482.575+1402)*.1608 + 7500 + 600)
    assert result['zero']['oceanDeclared'] == 0


@pytest.mark.parametrize('patch', [
    '{rows:[]}', '{rows:[row({20:""})]}', '{rows:[row({20:"-1"})]}',
    '{rows:[row({23:""})]}', '{rows:[row({25:"",26:""})]}',
    '{parameters:{airFixedFee:""}}', '{parameters:{oceanRate:"0"}}',
    '{rows:[row({25:"garbage 2"})]}', '{rows:[row({25:"1e-3foo"})]}',
    '{rows:[row({24:"-1"})]}', '{parameters:{deliveryFee:"-1"}}',
])
def test_incomplete_or_invalid_values_are_drafts(patch):
    r = run_js(f'console.log(JSON.stringify(C.calculate(payload({patch}))));')
    assert r['status'] == 'Draft' and r['issues']
    assert r['oceanTotal'] is None and r['airTotal'] is None and r['oceanAvg'] is None


def test_currency_validation_only_requires_used_rates():
    result = run_js('console.log(JSON.stringify(C.calculate(payload({parameters:{oceanRate:"",airRateFx:"",mxnToCny:""},currencies:{declaredCurrency:"CNY",clearanceCurrency:"CNY"}}))));')
    assert result['status'] == 'Ready'
    assert result['oceanDeclared'] == 200


def test_totals_overrides_and_mixed_units_keep_cost_but_omit_average():
    r = run_js('console.log(JSON.stringify(C.calculate(payload({rows:[row({23:"",4:"件"}),row({23:"",4:"kg"})],totals_override:{grossWeight:"30",volume:"4"}}))));')
    assert r['status'] == 'Ready' and r['mixedUnits'] is True
    assert r['v']['grossWeight'] == 30 and r['v']['volume'] == 4
    assert r['airTransport'] == 3200 and r['airAvg'] is None


def test_total_price_fallback_and_numeric_currency_tokens():
    r = run_js('console.log(JSON.stringify(C.calculate(payload({rows:[row({20:"1,000 件",23:"10 kg",25:"",26:"USD 1,234.50"})]}))));')
    assert r['status'] == 'Ready'
    assert r['v']['declaredValue'] == 1234.5


def test_strict_number_preserves_exponent_and_rejects_partial_tokens():
    values = run_js('console.log(JSON.stringify(["1e-3","-3","USD 1,000.20","￥12.5","abc12","1,2","1.2.3","1e-3oops"].map(C.parseNumber)));')
    assert values == [.001, -3, 1000.2, 12.5, None, None, None, None]


def test_paste_aliases_quotes_crlf_and_cell_patch_preserve_other_cells():
    r = run_js(r'''const a=C.parsePaste('物料编码\t總數量\t總毛重(kg)\t單價\r\nSKU\t100\t12\t2');
const b=C.pastedRows('"line 1\nline 2"\t"a""b"\r\n');
const c=C.applyPaste([row()], '5\t20', '',0,20);
console.log(JSON.stringify({a,b,c}));''')
    assert r['a']['rows'][0][1] == 'SKU'
    assert r['a']['rows'][0][20] == '100'
    assert r['a']['rows'][0][23] == '12'
    assert r['a']['rows'][0][25] == '2'
    assert r['b'] == [['line 1\nline 2', 'a"b']]
    assert r['c']['rows'][0][1] == 'SKU'
    assert r['c']['rows'][0][20] == '5' and r['c']['rows'][0][23] == '20'


def test_save_retry_uses_stable_request_id_double_click_and_keeps_late_edits():
    r = run_js('''let calls=[],release;const s=new C.RecordSession();s.payload=payload();s.title='Test';s.touch();
const api=async(method,args)=>{calls.push(args);return await new Promise((res,rej)=>release={res,rej})};
const first=s.save(api);await s.save(api);release.rej(new Error('offline'));try{await first}catch(e){}
const retry=s.save(api);s.payload.rows[0][20]='200';s.touch();release.res({ok:true,record:{name:'REC',modified:'m1',payload:payload(),result:{status:'Ready'}}});await retry;
console.log(JSON.stringify({calls,same:calls[0].request_id===calls[1].request_id,dirty:s.dirty,name:s.name,qty:s.payload.rows[0][20],busy:s.saving}));''')
    assert len(r['calls']) == 2 and r['same'] is True
    assert r['dirty'] is True and r['name'] == 'REC' and r['qty'] == '200' and r['busy'] is False


def test_native_assets_are_scoped_mirrored_and_repeatable():
    assert JS.exists(), 'Native page missing'
    content = JS.read_text()
    assert 'make_app_page' in content and 'air-sea-cost-comparison' in content
    assert 'localStorage' not in content and '<iframe' not in content
    assert 'beforeunload' in content and 'source_changed' in content
    css = (PAGE / 'air_sea_cost_comparison.css').read_text()
    assert '.air-sea-cost-comparison' in css
    assert '\nbody ' not in css and '\n    body ' not in css
    mirror = ROOT / 'overseas_costing/overseas_costing/page/air_sea_cost_comparison'
    for extension in ['js','css','json']:
        assert (PAGE / f'air_sea_cost_comparison.{extension}').read_bytes() == (mirror / f'air_sea_cost_comparison.{extension}').read_bytes()


def test_numeric_range_inactive_units_and_explicit_total_zero():
    r = run_js('''console.log(JSON.stringify({large:C.parseNumber('1e16'),zero:C.calculate(payload({rows:[row({23:'0',16:'10'})]})),unit:C.calculate(payload({rows:[row({4:'pieces'}),row({20:'0',4:'kg',23:'',25:''})]}))}));''')
    assert r['large'] is None
    assert r['zero']['status'] == 'Draft'
    assert r['unit']['unit'] == '件' and r['unit']['mixedUnits'] is False


def test_source_survives_edits_save_and_new_request_id_after_content_change():
    r = run_js('''const s=new C.RecordSession();s.apply({payload:payload({source:{batch:'B',token:'SIGNED'}}),title:'Test'},true);
let calls=[];const call=async(method,args)=>{calls.push(args);return {ok:true,record:{name:'REC',modified:'m'+calls.length,result:C.calculate(s.payload)}}};
await s.save(call);s.payload.rows[0][20]='101';s.touch();await s.save(call);
console.log(JSON.stringify({source:s.payload.source,ids:calls.map(x=>x.request_id),dirty:s.dirty,modified:s.modified}));''')
    assert r['source'] == {'batch':'B','token':'SIGNED'}
    assert r['ids'][0] != r['ids'][1] and r['dirty'] is False and r['modified'] == 'm2'


def test_server_failure_keeps_record_and_modified_for_retry():
    r = run_js('''const s=new C.RecordSession();s.apply({name:'REC',modified:'m1',title:'T',payload:payload()},true);
try{await s.save(async()=>{throw new Error('conflict')})}catch(e){}
console.log(JSON.stringify({name:s.name,modified:s.modified,dirty:s.dirty,busy:s.saving,qty:s.payload.rows[0][20]}));''')
    assert r == {'name':'REC','modified':'m1','dirty':True,'busy':False,'qty':'100'}


def test_stale_batch_preview_is_ignored_after_cancel():
    r = run_js('''const page=Object.create(C.AirSeaComparisonPage.prototype);let release;page.previewToken=0;page.active=true;page.notice=()=>{};page.call=async()=>await new Promise(r=>release=r);
const pending=page.previewBatch('B');page.previewToken++;release({ok:true,payload:payload()});await pending;
console.log(JSON.stringify({preview:page.preview||null}));''')
    assert r['preview'] is None


def test_render_uses_current_currency_formulas_and_both_cost_directions():
    r = run_js('''const page=Object.create(C.AirSeaComparisonPage.prototype),nodes={};page.session=new C.RecordSession();page.session.payload=payload({parameters:{airKgRate:'0',airFixedFee:'0'},currencies:{declaredCurrency:'CNY',clearanceCurrency:'USD',deliveryFeeCurrency:'MXN'}});
page.$=name=>nodes[name]||(nodes[name]={textContent:'',dataset:{},classList:{add(){}},closest(){return {querySelector:()=>this}},setAttribute(){}});
page.renderSaveState=()=>{};page.alignRows=()=>{};page.render();
console.log(JSON.stringify({sea:page.$('oceanBadge').textContent,air:page.$('airBadge').textContent,delivery:page.$('airDelivery').dataset.tip,clearance:page.$('oceanClearance').dataset.tip,diff:page.$('diffTotal').textContent}));''')
    assert r['air'] == '费用较低' and r['sea'] == '费用较高'
    assert '（MXN）÷ 比索汇率' in r['delivery'] and '（USD）× 海运美元汇率' in r['clearance']
    assert '比海运低' in r['diff']


@pytest.mark.parametrize('changes', [
    {}, {'rows':[]}, {'row':{20:''}}, {'row':{20:'0'}}, {'row':{23:''}},
    {'row':{25:'',26:'USD 123.50'}}, {'row':{25:'0',26:'99'}},
    {'row':{23:'',16:'0.25',24:'',17:'0.001'}},
    {'row':{23:'0',16:'2'}}, {'row':{12:'-1'}}, {'row':{25:'1e-3'}},
    {'row':{23:'',24:''},'totals_override':{'grossWeight':'25','volume':'0.4'}},
    {'parameters':{'oceanRate':'0'}}, {'parameters':{'airFixedFee':''}},
    {'parameters':{'oceanRate':'','airRateFx':'','mxnToCny':''},'currencies':{'declaredCurrency':'CNY','clearanceCurrency':'CNY'}},
    {'currencies':{'declaredCurrency':'MXN','clearanceCurrency':'USD','deliveryFeeCurrency':'USD','airKgRateCurrency':'USD'}},
    {'mixed':True}, {'row':{20:'1,000 件',23:'10 kg',25:'USD 2'}},
])
def test_frontend_backend_calculation_parity(changes):
    from overseas_costing.services.air_sea_calculation import calculate, RESULT_FIELDS
    row = [''] * 30
    row[1],row[4],row[20],row[23],row[25] = 'SKU','PCS','100','10','2'
    for column,value in changes.get('row',{}).items():
        row[column]=value
    payload = {'rows':changes.get('rows',[row]),'parameters':changes.get('parameters',{}),'currencies':changes.get('currencies',{}),'source':None}
    if 'totals_override' in changes:
        payload['totals_override']=changes['totals_override']
    if changes.get('mixed'):
        other=row.copy();other[4]='kg';payload['rows'].append(other)
    front = run_js(f'console.log(JSON.stringify(C.calculate({json.dumps(payload)})));')
    back = calculate(payload)
    assert front['status'] == back['status']
    assert front['mixedUnits'] == back['mixedUnits'] and front['unit'] == back['unit']
    for key in RESULT_FIELDS:
        if back[key] is None:
            assert front[key] is None, key
        else:
            assert front[key] == pytest.approx(float(back[key]),rel=1e-12), key
    for key in ['quantity','grossWeight','volume','declaredValue','declaredUnitPrice']:
        if back['v'][key] is None:
            assert front['v'][key] is None, key
        else:
            assert front['v'][key] == pytest.approx(float(back['v'][key]),rel=1e-12), key


def test_template_has_no_fixed_cost_formula_or_unlabelled_reference_speed():
    template=(PAGE/'parts/40-template.html').read_text()
    assert '40 × 总毛重 + 2000' not in template
    assert 'data-field="airFootnote"' in template
    assert '30–40 天（参考）' in template


def test_declared_currency_changes_display_headers_without_replacing_inputs():
    r=run_js('''const page=Object.create(C.AirSeaComparisonPage.prototype);page.session=new C.RecordSession();page.session.payload.currencies.declaredCurrency='MXN';const headers={innerHTML:''};page.$=()=>headers;page.renderHeaders();console.log(JSON.stringify({html:headers.innerHTML}));''')
    assert '申报单价（MXN）' in r['html'] and '申报总价（MXN）' in r['html']
    assert '总价（RMB)' not in r['html']


@pytest.mark.parametrize('quantity,expected',[('0.5','0.5'),('50400','50400'),('0.1234567','0.123457'),('2.340000','2.34')])
def test_quantity_summary_and_batch_preview_preserve_fractional_units(quantity,expected):
    result=run_js('''const page=Object.create(C.AirSeaComparisonPage.prototype),nodes={};page.session=new C.RecordSession();
page.session.payload=payload({rows:[row({20:QUANTITY,4:'kg'})]});
page.$=name=>nodes[name]||(nodes[name]={textContent:'',innerHTML:'',dataset:{},classList:{add(){}},closest(){return {querySelector:()=>this}},setAttribute(){},scrollIntoView(){}});
page.renderSaveState=()=>{};page.alignRows=()=>{};page.notice=()=>{};page.render();page.previewToken=0;page.active=true;
page.call=async()=>({ok:true,payload:page.session.payload,warnings:[]});await page.previewBatch('B');
console.log(JSON.stringify({summary:page.$('summaryQuantity').textContent,preview:page.$('previewPanel').innerHTML}));'''.replace('QUANTITY',json.dumps(quantity)))
    assert result['summary'] == f'{expected} kg'
    assert f'总数量 {expected} kg' in result['preview']


def test_mismatched_save_acknowledgement_does_not_pair_server_result_with_local_payload():
    result=run_js('''const s=new C.RecordSession();s.apply({name:'REC',modified:'m1',title:'Test',payload:payload()},true);
const different=payload({rows:[row({20:'999'})]});let error;
try{await s.save(async()=>({ok:true,record:{name:'REC',modified:'m2',title:'Test',payload:different,result:C.calculate(different)}}))}catch(e){error=e.message}
console.log(JSON.stringify({error,qty:s.payload.rows[0][20],modified:s.modified,dirty:s.dirty,result:s.result,busy:s.saving}));''')
    assert result.get('error') and '不一致' in result['error']
    assert result['qty']=='100' and result['modified']=='m1'
    assert result['dirty'] is True and result['result'] is None and result['busy'] is False


def test_save_acknowledgement_accepts_removed_blank_rows_and_default_normalization():
    result=run_js('''const s=new C.RecordSession();s.apply({title:'Test',payload:payload({source:{batch:'B',token:'SIGNED'}})},true);
const normalized=payload({source:{token:'SIGNED',batch:'B'}});await s.save(async()=>({ok:true,record:{name:'REC',modified:'m1',title:'Test',payload:normalized,result:C.calculate(normalized)}}));
console.log(JSON.stringify({rows:s.payload.rows.length,dirty:s.dirty,total:s.result.airTotal,name:s.name}));''')
    assert result['rows']==2 and result['dirty'] is False and result['total']>0 and result['name']=='REC'


@pytest.mark.parametrize('start_column,text,expected',[
    (1,'NEW-SKU',{1:'NEW-SKU'}),
    (1,'NEW-SKU\t新名称',{1:'NEW-SKU',6:'新名称'}),
    (1,'NEW-SKU\t',{1:'NEW-SKU',6:''}),
    (0,'PO-42',{0:'PO-42'}),
    (0,'PO-42\tNEW-SKU',{0:'PO-42',1:'NEW-SKU'}),
])
def test_short_paste_only_updates_cells_in_its_actual_footprint(start_column,text,expected):
    result=run_js('''const original=row({0:'ORIGINAL-PO',6:'原名称',11:'原规格',24:'1',26:'200'});
const result=C.applyPaste([original],TEXT,'',0,START);
console.log(JSON.stringify({original,row:result.rows[0]}));'''.replace('TEXT',json.dumps(text)).replace('START',str(start_column)))
    target=result['original'].copy()
    for column,value in expected.items():
        target[column]=value
    assert result['row']==target


def test_ragged_paste_rows_preserve_each_rows_untouched_trailing_cells():
    result=run_js(r'''const original=[row({1:'A',6:'旧一',11:'S1'}),row({1:'B',6:'旧二',11:'S2'})];const result=C.applyPaste(original,'NEW-A\t新一\nNEW-B','',0,1);console.log(JSON.stringify(result.rows));''')
    assert result[0][1:2]==['NEW-A'] and result[0][6]=='新一' and result[0][11]=='S1'
    assert result[1][1:2]==['NEW-B'] and result[1][6]=='旧二' and result[1][11]=='S2'


@pytest.mark.parametrize('value,expected',[
    ('1e-1000000',None),('1e-31',None),('1e-30',1e-30),('0e31',None),
    ('0.123456789012345678901234567890',None),
    ('0.12345678901234567890123456789',.12345678901234567890123456789),
    ('1e'+'0'*126+'1',None),('1e15',1e15),('1e16',None),('USD 1,234.50',1234.5),
])
def test_numeric_limits_match_backend_without_silent_underflow(value,expected):
    from overseas_costing.services.air_sea_calculation import number
    result=run_js(f'console.log(JSON.stringify(C.parseNumber({json.dumps(value)})));')
    assert result==expected
    backend=number(value)
    assert (None if backend is None else float(backend))==expected
