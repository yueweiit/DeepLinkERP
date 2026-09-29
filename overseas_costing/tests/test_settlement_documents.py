from io import BytesIO
import hashlib
from overseas_costing.tests.test_logistics_settlement import store, source


def workbook(title, rows):
    from openpyxl import Workbook
    book=Workbook(); sheet=book.active; sheet.title=title
    for row in rows: sheet.append(row)
    output=BytesIO(); book.save(output)
    return output.getvalue()


def test_full_original_sheet_has_complete_rows_but_partial_sheet_does_not():
    from overseas_costing.services.logistics_settlement.documents import parse_document
    rows=[['物料编码','数量','单位'],['A',2,'件'],['A',3,'箱']]
    assert parse_document(workbook('完整货物明细',rows),'cargo.xlsx')['tables'][0]['complete']
    assert not parse_document(workbook('货物片段',rows),'cargo.xlsx')['tables'][0]['complete']


def test_generic_packing_template_is_recognized_as_packing_table():
    """通用装箱单模板（核算系统）.xlsx 的数量/金额列是「总个数」「总价(人民币)」，
    旧锚点集合只认 数量/cantidad/金额/importe，导致该模板 tables=[] 被判
    「未识别出可核对的明细表」而打入仅审计 + Other。必须能识别为 packing 表。"""

    from overseas_costing.services.logistics_settlement.documents import parse_document
    rows=[
        ['对应钉钉采购订单号','品目编码Item code','中文品名','单价(人民币)','总个数','总净重(kg)','总价(人民币)'],
        ['202609221705000543719','FL004116','笔式万用表',25,50,12.35,1250],
        ['202607090338000050291','FL000817','文件夹',0.62,210,6.5,130.2],
    ]
    result=parse_document(workbook('装箱单主表',rows),'通用装箱单模板（核算系统）.xlsx')

    assert result['tables'], result['issues']
    assert result['issues']==[]
    first=result['tables'][0]
    assert first['kind']=='packing'
    assert len(first['rows'])==2
    labels={cell['name'] for cell in first['rows'][0]['rowValue']}
    assert '总个数' in labels and '总价(人民币)' in labels


def test_cached_attachment_is_not_redownloaded_or_reparsed(store):
    from overseas_costing.services.logistics_settlement.documents import enrich_raw
    data=workbook('完整货物明细',[['物料编码','数量','单位'],['A',2,'件']])
    row=source('E'); row['attachments']=[{'file_id':'f','file_name':'cargo.xlsx','bucket':'other-bucket','object_key':'immutable-key','archive_status':'archived','sha256':hashlib.sha256(data).hexdigest(),'actual_size':len(data),'archive_quality':'original'}]
    seen=[]
    def reader(manifest):
        seen.append((manifest['bucket'],manifest['object_key']));return data
    first=enrich_raw(store,row,reader=reader)
    second=enrich_raw(store,row,reader=reader)
    assert len(seen)==1 and first==second
    from overseas_costing.services.logistics_settlement.model import parse_source
    assert parse_source(first,logistics_codes={'logistics'})['goods_complete']


def test_preview_archive_cannot_claim_complete_goods(store):
    from overseas_costing.services.logistics_settlement.documents import enrich_raw
    from overseas_costing.services.logistics_settlement.model import parse_source
    data=workbook('完整货物明细',[['物料编码','数量','单位'],['A',2,'件']])
    row=source('E');row['attachments']=[{'file_id':'f','file_name':'cargo.xlsx','archive_status':'archived','archive_quality':'preview','sha256':'h'}]
    result=parse_source(enrich_raw(store,row,reader=lambda m:data),logistics_codes={'logistics'})
    assert not result['goods_complete'] and result['documents'][0]['tables']


def test_service_billing_quantity_does_not_turn_fee_table_into_goods(store):
    from overseas_costing.services.logistics_settlement.documents import enrich_raw
    from overseas_costing.services.logistics_settlement.model import parse_source
    from overseas_costing.services.logistics_settlement.application import plan_application
    data=workbook('完整费用明细',[['费用名称','数量','单位','金额'],['清关费',1,'票',100]])
    raw=source('E',amount='100');raw['attachments']=[{'file_id':'f','file_name':'bill.xlsx','archive_status':'archived','content_quality':'original','sha256':'h'}]
    parsed=parse_source(enrich_raw(store,raw,reader=lambda _:data),logistics_codes={'logistics'})
    assert parsed['documents'][0]['tables'][0]['kind']=='fee'
    assert not parsed['goods'] and parsed['coverage']=='unknown'
    assert not plan_application(parsed,[],[{'name':'c','rule_code':'customs_fee','amount':20}],binding_id='b')['ready']


def test_private_file_size_limit_keeps_parsed_source_and_records_cache_gap(store):
    from overseas_costing.services.logistics_settlement.documents import enrich_raw
    data=workbook('完整货物明细',[['物料编码','数量','单位'],['A',2,'件']])
    row=source('E');row['attachments']=[{'file_id':'f','file_name':'cargo.xlsx','archive_status':'archived','archive_quality':'original','sha256':'large'}]
    class MaxFileSizeReachedError(Exception):
        pass
    def cache_file(*_):
        raise MaxFileSizeReachedError('File size exceeded the maximum allowed size of 10.0 MB')
    result=enrich_raw(store,row,reader=lambda _:data,cache_file=cache_file)
    doc=result['settlement_documents'][0]
    assert doc['tables'] and not doc.get('file_url') and doc['cache_issues']
    assert store.count('document')==1
