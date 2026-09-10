"""Parse immutable archived content once. Partial/OCR data remain review candidates."""
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path
import csv
import tempfile

from .model import PARSER_VERSION, digest, dumps, norm, number, pick

COMPLETE_GOODS = {'完整货物明细', '全部货物明细', '完整货物清单', 'listacompletademercancias'}
COMPLETE_FEES = {'完整费用明细', '费用结算明细', 'desglosetotaldegastos'}
PACKING_LABELS = ('装箱', 'packing', 'empaque')


def parse_document(content, file_name):
    suffix = Path(file_name).suffix.lower()
    sheets = []
    if suffix == '.xlsx':
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(content), read_only=True, data_only=True)
        try:
            sheets = [(sheet.title, list(sheet.values)) for sheet in book.worksheets]
        finally:
            book.close()
    elif suffix == '.xls':
        import xlrd
        book = xlrd.open_workbook(file_contents=content)
        sheets = [(sheet.name, [sheet.row_values(i) for i in range(sheet.nrows)]) for sheet in book.sheets()]
    elif suffix == '.csv':
        sheets = [(Path(file_name).stem, list(csv.reader(StringIO(content.decode('utf-8-sig')))))]
    else:
        # Text/OCR can assist review, but never proves a complete cargo or fee table.
        from overseas_costing.services.attachment_parse_service import preview_source_document
        with tempfile.TemporaryDirectory(prefix='oc-settlement-') as directory:
            path = Path(directory) / ('source' + suffix)
            path.write_bytes(content)
            try:
                preview = preview_source_document(source_name=file_name, file_path=str(path))
            except ValueError as exc:
                return {'status': 'review', 'tables': [], 'issues': [str(exc)]}
        return {'status': 'review', 'tables': [], 'preview': {k: preview.get(k) for k in ('classification','field_candidates','purchase_order','text_excerpt','extraction_method')}, 'issues': ['附件文字仅作候选，需核对完整明细']}
    tables = []
    for title, rows in sheets:
        nonempty = [(i, list(r)) for i, r in enumerate(rows, 1) if any(v is not None and str(v).strip() for v in r)]
        header_pos = next((i for i, (_, values) in enumerate(nonempty[:30]) if any(norm(v) in {'数量','cantidad','数量cantidad','金额','importe','monto','金额importe'} for v in values)), None)
        if header_pos is None:
            continue
        header = [str(v or '').strip() for v in nonempty[header_pos][1]]
        parsed_rows = []
        for position, values in nonempty[header_pos+1:]:
            fields = {label: values[i] if i < len(values) else None for i, label in enumerate(header) if label}
            row_id = pick(fields, '行ID', 'Row ID', '明细ID')
            parsed_rows.append({'rowId': str(row_id) if row_id not in (None, '') else None, 'rowValue': [{'name': k, 'value': v} for k,v in fields.items()], 'position': position})
        packing = any(label in norm(title + file_name) for label in PACKING_LABELS)
        fee = any(pick({key: 'present' for key in header}, alias) for alias in ('金额','Monto','Importe'))
        fee_heading = any(norm(label) in norm(title) for label in ('费用','付款','账单','gastos','cargos')) or any(norm(v) in {'费用名称','费用项目','concepto','费用名称concepto','费用项目concepto'} for v in header)
        kind = 'fee' if fee_heading else 'packing' if packing else 'fee' if fee and not any(norm(v) in {'数量','cantidad','数量cantidad'} for v in header) else 'goods'
        complete = norm(title) in (COMPLETE_FEES if kind == 'fee' else COMPLETE_GOODS) and bool(parsed_rows)
        tables.append({'title': title, 'kind': kind, 'complete': complete, 'rows': parsed_rows, 'header_position': nonempty[header_pos][0]})
    return {'status': 'parsed' if tables else 'review', 'tables': tables, 'issues': [] if tables else ['未识别出可核对的明细表']}


def enrich_raw(store, raw, *, reader, cache_file=None):
    row = deepcopy(raw)
    documents, synthetic, fee_pending = [], [], []
    for manifest in row.get('attachments') or []:
        if manifest.get('retired_at'):
            continue
        identity = digest(row.get('corp_id'), row.get('process_instance_id'), manifest.get('file_id'),
                          manifest.get('sha256'), manifest.get('bucket'), manifest.get('object_key'), PARSER_VERSION)
        cached = store.get('document', identity)
        if not cached:
            if manifest.get('archive_status') != 'archived':
                parsed = {'status': 'pending', 'tables': [], 'issues': ['上游附件尚未归档：' + str(manifest.get('last_error') or manifest.get('archive_status'))]}
            else:
                # Archive integrity/download errors propagate into the durable per-item retry list.
                content = reader(manifest)
                parsed = parse_document(content, str(manifest.get('file_name') or 'attachment'))
                if cache_file:
                    try:
                        parsed['file_url'] = cache_file(content, str(manifest.get('file_name') or 'attachment'))
                    except Exception as exc:
                        if type(exc).__name__ != 'MaxFileSizeReached':
                            raise
                        # The immutable archive is still available. A private File
                        # cache size limit must not discard the entire approval.
                        parsed['cache_issues'] = ['附件超过本地预览大小限制；原始归档保留，预览待处理']
                        parsed['issues'] = list(parsed.get('issues') or []) + parsed['cache_issues']
            cached = {'id': identity, 'source_id': digest(row.get('corp_id'), row.get('process_instance_id')),
                      'fingerprint': identity, 'status': parsed['status'], 'file_id': manifest.get('file_id'),
                      'file_name': manifest.get('file_name'), 'manifest': manifest, **parsed}
            # A pending archive is retried on later inventory, without pinning a negative cache.
            if manifest.get('archive_status') == 'archived':
                store.insert('document', {k: cached[k] for k in ('id','source_id','fingerprint','status')} | {'data': dumps(cached)})
        document = dict(cached)
        document['manifest'] = manifest
        documents.append(document)
    return with_cached_documents(row, documents)


def with_cached_documents(raw, documents):
    """Reclassify persisted tables after a policy upgrade, without fetching files."""
    row = deepcopy(raw)
    synthetic, fee_pending = [], []
    for document in documents:
        manifest = document.get('manifest') or {}
        identity = document['id']
        if manifest.get('retired_at') or document.get('retired_at'):
            continue
        quality = str(manifest.get('archive_quality') or manifest.get('content_quality') or '')
        for table in document.get('tables') or []:
            eligible = table['complete'] and quality in {'original','original_complete'}
            if eligible:
                name = ('货物明细' if table['kind'] == 'goods' else '费用明细') + ':' + str(manifest.get('file_id')) + ':' + table['title']
                if table['kind'] in {'goods','fee'}:
                    synthetic.append({'name': name, 'componentType': 'TableField', 'value': table['rows'], 'attachment_id': identity})
            if table['kind'] == 'fee' and not eligible:
                fee_pending.append('费用附件明细完整性待核对：' + str(manifest.get('file_name')))
        if not document.get('tables') and any(token in norm(manifest.get('file_name')) for token in ('运费','结算','账单','freight','invoice')):
            fee_pending.append('费用附件尚未完整识别：' + str(manifest.get('file_name')))
    # An approval fee table and a separate bill may be the same costs. Never add both pools.
    original = (row.get('raw_payload') or {}).get('formComponentValues') or []
    original_has_fee = any(c.get('componentType') == 'TableField' and any(label in norm(c.get('name')) for label in ('费用明细','付款明细','物流费用','desglosedegastos','支出明细')) for c in original)
    fee_tables = [t for t in synthetic if t['name'].startswith('费用明细:')]
    if original_has_fee or len(fee_tables) > 1:
        if fee_tables:
            fee_pending.append('正文与附件或多份附件存在费用明细，需核对重叠范围')
        synthetic = [t for t in synthetic if not t['name'].startswith('费用明细:')]
    row['settlement_documents'] = documents
    row['settlement_attachment_components'] = synthetic
    row['settlement_fee_issues'] = fee_pending
    return row
