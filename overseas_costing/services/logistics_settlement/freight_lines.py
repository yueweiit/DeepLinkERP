"""Shipment-scoped statement evidence. A relation is not an amount allocation."""
import re
from collections import Counter
from decimal import Decimal

from .model import decoded, digest, dumps, fields_of, norm, number, currency, pick

POLICY = 'shipment-freight-1'
WAYBILL_LABELS = ('运单号','快递单号','提单号','waybill','awb','trackingnumber','numerodeguia','guia')
APPROVAL_LABELS = ('钉钉流程','国际物流审批号','物流审批号','审批编号','approvalnumber')
AMOUNT_LABELS = ('运费金额','运费','快递费','费用金额','金额','importe','monto','freightamount','shippingcost')
OTHER_SCOPES = ('清关','关税','税费','进口税','提货','末端','派送','内陆','aduana','despacho','arancel','impuesto','inland','lastmile','fletelocal')


def identifiers_in(value):
    text = dumps(value) if not isinstance(value,str) else value
    tokens = {('waybill',v.upper()) for v in re.findall(r'(?<![A-Z0-9])MXT\d{4,}(?![A-Z0-9])',text.upper())}
    # Only labeled tracking numbers; bank accounts/amounts/dates are not identifiers.
    labels = r'(?:DHL\s*(?:单号|运单|tracking)?|快递单号|运单号|提单号|waybill|tracking(?:\s*(?:number|code))?|c[oó]digo\s*de\s*rastreo|gu[ií]a)'
    for match in re.finditer(labels+r'[\s:：#"\\n-]*((?:\d[ ]*){8,20}|[A-Z]{2,4}\d{6,16})',text,re.I):
        token=re.sub(r'\s+','',match.group(1)).upper()
        if token: tokens.add(('waybill',token))
    return tokens


def financial_candidate(row, fields):
    title=str(row.get('process_name') or row.get('template_name') or row.get('title') or (row.get('raw_payload') or {}).get('title') or '')
    text=norm(title+' '+dumps(fields))
    financial=any(x in norm(title) for x in ('采购支出','运营支出','费用支出','月结付款','报销','付款','支付','gastos','pago','reembolso')) or bool(re.search(r'\bbu\b',title,re.I))
    transport=any(norm(x) in text for x in ('物流','运费','运输','快递','freight','transporte','envio','dhl','fedex','ups','paqueteria','运单','提单','国际物流'))
    return financial and transport


def label_value(fields, aliases):
    for alias in aliases:
        for key,value in fields.items():
            k=norm(key)
            if k==norm(alias) or k in {norm(alias+c) for c in ('RMB','CNY','USD','MXN','人民币','Moneda','Cantidad')}:
                return key,value
    return '',None


def statement_tables(sheets):
    result=[]
    for title,rows in sheets:
        for index,row in enumerate(rows[:30]):
            fields={str(v or '').strip():True for v in row if str(v or '').strip()}
            if not label_value(fields,WAYBILL_LABELS+APPROVAL_LABELS)[0] or not label_value(fields,AMOUNT_LABELS)[0]:
                continue
            header=[str(v or '').strip() for v in row]
            result.append({'title':title,'header_position':index+1,'rows':[
                {'position':pos,'fields':{label:values[col] if col<len(values) else None for col,label in enumerate(header) if label}}
                for pos,values in enumerate(rows[index+1:],index+2) if any(v not in (None,'') for v in values)]})
            break
    return result


def fee_scope(label):
    text=norm(label)
    if any(norm(t) in text for t in ('双清','包税','ddp')): return 'review'
    if any(norm(t) in text for t in OTHER_SCOPES): return 'excluded'
    return 'freight' if any(norm(t) in text for t in ('运费','物流','海运','空运','快递','freight','flete','transporte','dhl','fedex','燃油','附加','surcharge','冲抵','折扣','credit')) else 'review'


def row_line(source, fields, *, document_id='', document_hash='', file_id='', file_name='', sheet='', position=None, native_id=None):
    _,waybill=label_value(fields,WAYBILL_LABELS); _,approval=label_value(fields,APPROVAL_LABELS)
    amount_label,amount_raw=label_value(fields,AMOUNT_LABELS)
    amount=number(amount_raw)
    if amount is None or (not waybill and not approval): return None
    if any(norm(t) in norm(str(waybill)+str(approval)) for t in ('合计','总计','小计','subtotal','total')): return None
    waybill=str(waybill or '').strip().replace(' ','')
    if waybill.endswith('.0'): waybill=waybill[:-2]
    approval=str(approval or '').strip()
    # Excel numeric long approval IDs may already have lost precision; never repair by guessing.
    if 'e+' in approval.lower() or approval.endswith('.0'): approval=''
    label=str(pick(fields,'费用名称','费用项目','Concepto') or amount_label)
    if any(token in norm(str(pick(fields,'费用名称','费用项目','Concepto') or '')) for token in ('小计','合计','总计','subtotal','total')):return None
    cur=currency(pick(fields,'币种','Moneda') or next((c for c in ('RMB','CNY','USD','MXN') if c in amount_label.upper()),'') or source.get('currency'))
    project=pick(fields,'所属项目','项目','Proyecto') or ''
    if any(t in norm(str(project)) for t in ('小计','合计','总计','subtotal','total')):return None
    key=digest(file_id or 'form',sheet,native_id or [waybill,approval,label,project])
    cargo=pick(fields,'发货明细','货物明细','物料明细','装箱明细','Cargo','Mercancía') or ''
    return {'id':digest(source['id'],key),'line_key':key,'source_id':source['id'],'source_snapshot':source.get('snapshot') or '',
        'waybill':waybill.upper(),'approval_no':approval,'amount':amount,'currency':cur,'label':label,'scope':fee_scope(label),
        'project':str(project),'cargo_text':str(cargo),'billing_weight':number(pick(fields,'重量','计费重量','Peso')),
        'evidence':{'document_hash':document_hash,'document_id':document_id,'file_id':file_id,'file_name':file_name,'sheet':sheet,'row':position,'amount_field':amount_label},
        'charge_key':digest('economic-charge',source.get('corp'),waybill,approval,norm(label),str(project),amount,cur,norm(cargo)),
        'revision':digest(source.get('snapshot') or source.get('fingerprint'),key,fields),'fields':fields}


def lines_for_source(source):
    rows=[]
    for document in source.get('documents') or []:
        manifest=document.get('manifest') or {}
        if manifest.get('retired_at') or document.get('retired_at'): continue
        if manifest.get('archive_quality') not in ('original','original_complete'):
            continue
        for table in document.get('freight_tables') or []:
            for row in table['rows']:
                line=row_line(source,row['fields'],document_id=document['id'],file_id=document.get('file_id') or manifest.get('file_id'),
                    document_hash=manifest.get('sha256'),file_name=document.get('file_name'),sheet=table['title'],position=row['position'])
                if line: rows.append(line)
    # Native form rows use the same extraction; repeated attachment/form evidence stays a conflict.
    from .model import components
    for c in components(source.get('raw') or {}):
        if c.get('componentType')!='TableField': continue
        table=decoded(c.get('value'))
        for pos,row in enumerate(table if isinstance(table,list) else [],1):
            line=row_line(source,fields_of(row),sheet=c.get('name') or '',position=pos,native_id=row.get('rowId') if isinstance(row,dict) else None)
            if line: rows.append(line)
    seen={}; distinct=[]
    for line in rows:
        duplicate=(line['charge_key'],line['amount'],line['currency'])
        if duplicate in seen and line['evidence'].get('document_hash') and line['evidence'].get('document_hash')==seen[duplicate]['evidence'].get('document_hash') and line['evidence']['document_id']!=seen[duplicate]['evidence']['document_id']:
            continue
        seen[duplicate]=line; distinct.append(line)
    counts=Counter(r['line_key'] for r in distinct)
    economic=lambda r:(r['waybill'],r['approval_no'],r['amount'],r['currency'],norm(r['project']),norm(r.get('cargo_text')))
    duplicate_evidence={economic(r) for r in distinct if len({(other['evidence'].get('file_id') or 'form') for other in distinct if economic(other)==economic(r)})>1}
    for line in distinct:
        line['ambiguous']=counts[line['line_key']]>1 or economic(line) in duplicate_evidence
        if line['ambiguous']: line['id']=digest(line['id'],line['evidence']['row'])
    if distinct: return distinct
    aggregate=any(t in norm(dumps(source.get('fields'))+' '+str(source.get('title'))) for t in ('月结','账单','monthly','mensual'))
    if source.get('amount') is None or aggregate or len(source.get('related') or [])>1 or source.get('documents') or source.get('fee_issues'):
        return []
    # A single-shipment approval may have an explicit total. Its attribution is still reviewed.
    fees=source.get('fees') or [{'line_key':'total','label':'运费','amount':source['amount'],'currency':source.get('currency')}]
    for fee in fees:
        line={**fee,'id':digest(source['id'],fee['line_key']),'source_id':source['id'],'source_snapshot':source.get('snapshot') or '',
            'waybill':'','approval_no':'','cargo_text':'','scope':fee_scope(str(fee.get('label') or '')+' '+dumps(source.get('fields') or {})),
            'charge_key':digest(source['id'],fee['line_key']),'ambiguous':False,
            'evidence':{'sheet':fee.get('source_table') or '审批正文','row':fee.get('source_position'),'document_id':''},
            'revision':digest(source.get('snapshot') or source.get('fingerprint'),fee)}
        rows.append(line)
    return rows


def matching_lines(logistics, lines):
    tokens={str(t[1]).upper() for t in logistics.get('identifiers') or [] if t[0] in ('waybill','approval')}
    result=[]
    for row in lines:
        if not any(row.get(k) in tokens for k in ('waybill','approval_no')):continue
        conflict=any(row.get(k) and row[k] not in tokens and any(t[0]==kind for t in logistics.get('identifiers') or []) for k,kind in [('waybill','waybill'),('approval_no','approval')])
        result.append({**row,'identifier_conflict':conflict})
    return result
