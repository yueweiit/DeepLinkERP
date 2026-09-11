"""Pure row catalog and server-owned projection for selected AI suggestions."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from . import material_ai_fee_policy
from .effective_logistics_source import json_dict
from .logistics_settlement.model import digest
from overseas_costing.utils.field_mapper import normalize_unit

POLICY = 'ai-row-review-1'
PHYSICAL = ('gross_weight_kg','net_weight_kg','volume_m3','volume_weight_kg','chargeable_weight_kg','weight_ratio','package_count','packaging_type')
IDENTITY = ('material_code','product_name','spec_model')
FILL_FIELDS = (*PHYSICAL,'actual_shipped_qty','shipped_uom','project_collection','unit_price','purchase_currency','purchase_uom','unit_price_uom')
MISSING_LABELS = {'material_code':'SKU','actual_shipped_qty':'数量','shipped_uom':'单位','gross_weight_kg':'毛重','volume_m3':'体积'}


def missing(row, field):
    value = row.get(field)
    if value is None or (isinstance(value,str) and not value.strip()):
        return True
    mask = json_dict(row.get('extra_json')).get('settlement_packing_missing') or []
    return field in mask or (field == 'actual_shipped_qty' and 'quantity' in mask)


def _unit(row):
    return normalize_unit(row.get('shipped_uom') or row.get('unit') or row.get('purchase_uom') or '')


def _matches(row, items):
    stable = row.get('stable_line_key')
    exact = [i for i in items if stable and i.get('stable_line_key') == stable
             and str(i.get('material_code') or '').casefold()==str(row.get('material_code') or '').casefold()
             and str(i.get('spec_model') or '').casefold()==str(row.get('spec_model') or '').casefold() and _unit(i)==_unit(row)]
    if exact:
        return exact
    code = str(row.get('material_code') or '').strip().casefold()
    name = str(row.get('product_name') or '').strip().casefold()
    return [i for i in items if ((code and str(i.get('material_code') or '').strip().casefold()==code)
            or (not code and name and str(i.get('product_name') or '').strip().casefold()==name))
            and str(row.get('spec_model') or '').strip().casefold()==str(i.get('spec_model') or '').strip().casefold()
            and _unit(row)==_unit(i)]


def _source_values(row):
    values = {k:deepcopy(row.get(k)) for k in (*IDENTITY,*FILL_FIELDS,'quantity','unit','stable_line_key')}
    code = str(values.get('material_code') or '')
    if re.search(r'[/／、,，+＋;；]',code):
        values['material_code']=''
        values['unverified_material_code']=code
    if values.get('actual_shipped_qty') is None:
        values['actual_shipped_qty']=values.get('quantity')
    if values.get('quantity') is None:
        values['quantity']=values.get('actual_shipped_qty')
    values['shipped_uom']=values.get('shipped_uom') or values.get('unit') or row.get('purchase_uom')
    values['unit']=values.get('unit') or values['shipped_uom']
    for field in PHYSICAL:
        if missing(row,field):values[field]=None
    return values


def catalog(items, proposals, fees, context, *, run_id):
    """Do not expose inherited purchase values as newly recognized packing evidence."""
    from .effective_source_values import project_source_values
    items=[project_source_values(i,context) for i in items]
    original={str(i['name']):i for i in items}
    rows=[];occurrences=Counter();proposal_rows={}
    def add(values, proposal, *, origin='source', target='', stable='', fields=None, price_metadata=None):
        values=deepcopy(values)
        matches=_matches(values,items) if origin=='source' else []
        if target and target in original and (origin=='current' or proposal.get('proposal_type')=='item_update'):
            matches=[original[target]]
        target=matches[0]['name'] if len(matches)==1 else (target if origin=='current' else '')
        base=digest(run_id,proposal.get('proposal_id'),origin,stable or {k:values.get(k) for k in (*IDENTITY,'unit')})
        occurrences[base]+=1
        row_id=digest(POLICY,base,occurrences[base])
        valid=bool(values.get('material_code') or values.get('product_name'))
        reason='物料对应多条现有明细，不能确定要补充哪一行。' if len(matches)>1 else ''
        try:
            quantity=values.get('actual_shipped_qty')
            if quantity is not None and (not Decimal(str(quantity)).is_finite() or Decimal(str(quantity))<0):
                valid=False;reason='数量无效或为负数，请核对来源。'
        except (InvalidOperation,ValueError):valid=False;reason='数量格式无法识别。'
        if proposal.get('blocked'):
            valid=False;reason=proposal.get('reason') or '来源资料待核对。'
        fill_fields=list(fields if fields is not None else FILL_FIELDS)
        if origin=='source' and target and not any(not missing(values,f) and missing(original[target],f) for f in fill_fields):
            fillable=False
            reason=reason or '当前物料已有明确值，本行没有可补的空缺。'
        else:fillable=origin=='source' and valid and len(matches)<=1
        default_replace_selected=bool(
            origin=='source' and valid and len(matches)<=1
            and proposal.get('default_selected',False) and not proposal.get('conflict')
        )
        rows.append({'row_id':row_id,'origin':origin,'label':'当前已有' if origin=='current' else '本次识别',
                     'values':values,'target_item_name':target,'can_fill':fillable,'can_replace':valid,
                     'default_selected':bool(origin=='source' and fillable and proposal.get('default_selected',False) and not proposal.get('conflict')),
                     'default_replace_selected':default_replace_selected,
                     'blocked_reason':reason,'source_refs':deepcopy(proposal.get('source_refs') or []),
                     'proposal_id':proposal.get('proposal_id'),'proposal_type':proposal.get('proposal_type'),'fields':fill_fields})
        if price_metadata is not None:
            rows[-1]['_price_metadata']=deepcopy(price_metadata)
        if stable:proposal_rows[stable]=rows[-1]
    for proposal in proposals:
        kind=proposal.get('proposal_type');payload=proposal.get('payload') or {}
        if kind=='logistics_reconcile':
            for row in payload.get('rows') or []:
                meta=json_dict(row.get('extra_json')).get('logistics_row') or {}
                origin=row.get('_review_origin') or ('source' if meta.get('source_id') or not row.get('_existing_name') else 'current')
                if origin=='current':continue
                evidence_row=row.get('_review_source_values')
                if evidence_row is None and '_review_origin' not in row:
                    # Older reconciliation rows contained copied/apportioned historical weights.
                    evidence_row={**row,**{field:None for field in PHYSICAL}}
                values=_source_values(evidence_row if evidence_row is not None else row)
                # Reconciliation copied procurement facts from old rows; those are not evidence of a new price.
                reviewed_purchase = row.get('_review_purchase_values')
                if isinstance(reviewed_purchase,dict):
                    values.update({field:deepcopy(reviewed_purchase.get(field)) for field in
                                   ('unit_price','purchase_currency','purchase_uom','unit_price_uom')})
                else:
                    for field in ('unit_price','purchase_currency','purchase_uom','unit_price_uom'):values.pop(field,None)
                add(values,proposal,stable=row.get('stable_line_key') or row.get('name'),
                    price_metadata=row.get('_review_price_metadata'))
        elif kind=='material_replace':
            for row in payload.get('replacement_rows') or []:
                values=_source_values(row);values['material_code']=''
                add(values,proposal)
        elif kind=='item_update':
            target=str(proposal.get('target_item_name') or payload.get('item_name') or '')
            fields={k:v for k,v in (payload.get('fields') or {}).items() if k in FILL_FIELDS}
            if not fields:continue
            existing=original.get(target)
            if not existing:continue
            values={k:existing.get(k) for k in (*IDENTITY,'unit','shipped_uom','stable_line_key')}
            values.update(fields)
            add(values,proposal,target=target,fields=list(fields))
    for item in items:
        add(deepcopy(item),{'proposal_id':'current:'+item['name']},origin='current',target=item['name'],stable=item['name'],fields=[])
    fee_rows=[p for p in material_ai_fee_policy.decorate(proposals,fees,context) if p.get('proposal_type')=='fee_update']
    return {'policy':POLICY,'rows':rows,'fees':fee_rows,'fingerprint':digest(POLICY,run_id,rows,fee_rows)}


def project(items, catalog, row_ids, fee_ids, mode):
    if mode not in ('fill_missing','replace_all'):raise ValueError('请选择填充空缺或替换整票。')
    if not isinstance(row_ids,list) or not isinstance(fee_ids,list):raise ValueError('请选择有效的物料行和费用。')
    if any(not isinstance(i,str) for i in row_ids+fee_ids) or len(row_ids)!=len(set(row_ids)) or len(fee_ids)!=len(set(fee_ids)):
        raise ValueError('选择包含重复或无效行。')
    rows_by_id={r['row_id']:r for r in catalog['rows']};fees_by_id={r['proposal_id']:r for r in catalog['fees']}
    if set(row_ids)-rows_by_id.keys() or set(fee_ids)-fees_by_id.keys():raise ValueError('所选内容不属于当前草稿，请刷新预览。')
    chosen=[r for r in catalog['rows'] if r['row_id'] in row_ids]
    selected_fees=[r for r in catalog['fees'] if r['proposal_id'] in fee_ids]
    for row in chosen:
        if not row['can_fill' if mode=='fill_missing' else 'can_replace']:raise ValueError(row['blocked_reason'] or '本行不可采用。')
    for fee in selected_fees:
        if not fee['can_apply']:raise ValueError(fee['blocked_reason'])
    fee_keys=[str((fee.get('payload') or {}).get('logical_fee_key') or '') for fee in selected_fees]
    fee_groups=[fee['conflict_group'] for fee in selected_fees if fee.get('conflict_group')]
    if len(fee_keys)!=len(set(fee_keys)) or len(fee_groups)!=len(set(fee_groups)):
        raise ValueError('同一费用有多份报价，请只选择一份；其他报价保留参考。')
    if mode=='replace_all' and not chosen:raise ValueError('至少选择一条物料，不能用空结果清空整票。')
    effective={r['target_item_name']:r['values'] for r in catalog['rows'] if r['origin']=='current'}
    items=[deepcopy(effective.get(i['name'],i)) for i in items]
    result=[{**deepcopy(i),'_row_action':'retain'} for i in items] if mode=='fill_missing' else []
    original={i['name']:i for i in items};used=set();used_choices={};changes=[];added=0
    for choice in chosen:
        incoming=choice['values'];target=choice['target_item_name'];refs=choice['source_refs']
        duplicate_target=False
        if mode=='replace_all' and target and target in used:
            previous=used_choices[target]
            duplicate_target=(choice['proposal_type']=='logistics_reconcile' and previous['proposal_id']==choice['proposal_id'])
            if not duplicate_target:raise ValueError('所选多行对应同一现有物料，请仅选择一种来源。')
        if choice['origin']=='current':
            row=deepcopy(original[target]);row.update(_target=target,_row_action='retain');used.add(target);used_choices[target]=choice;result.append(row);continue
        if mode=='fill_missing' and target:
            row=next(r for r in result if r['name']==target)
            fields=[f for f in choice['fields'] if not missing(incoming,f) and missing(row,f)]
        else:
            row={k:deepcopy(incoming.get(k)) for k in (*IDENTITY,*FILL_FIELDS,'quantity','unit','unverified_material_code')}
            row['_target']=target;row['stable_line_key']=((original.get(target) or {}).get('stable_line_key') if not duplicate_target else None) or choice['row_id']
            fields=[f for f in choice['fields'] if not missing(incoming,f)]
            if (target
                    and str(incoming.get('material_code') or '').strip().casefold() == str(original[target].get('material_code') or '').strip().casefold()
                    and str(incoming.get('spec_model') or '').strip().casefold() == str(original[target].get('spec_model') or '').strip().casefold()
                    and _unit(incoming) == _unit(original[target])):
                old=original[target]
                # Preserve price only for a verified identity/unit mapping, independent of packing facts.
                for f in ('unit_price','purchase_currency','purchase_uom','unit_price_uom','source_doc_no','supplier'):
                    if missing(row,f):row[f]=deepcopy(old.get(f))
                row['_price_metadata']=deepcopy(choice.get('_price_metadata') or json_dict(old.get('extra_json')))
                row['_verified_prior_item']=deepcopy(old)
            else:added+=1
            result.append(row)
        meta=json_dict(row.get('extra_json'));field_refs=meta.setdefault('ai_row_fields',{})
        for field in fields:
            before=row.get(field)
            row[field]=deepcopy(incoming[field]);field_refs[field]={'row_id':choice['row_id'],'source_refs':refs}
            changes.append({'row_id':choice['row_id'],'item_name':target,'fieldname':field,'previous_value':before,'value':row[field]})
        mask=set(meta.get('settlement_packing_missing') or [])
        for field in fields:mask.discard(field)
        if 'actual_shipped_qty' in fields:mask.discard('quantity')
        meta['settlement_packing_missing']=sorted(mask)
        meta['ai_row_selection']={'row_id':choice['row_id'],'source_refs':refs,'origin':'source'}
        row['extra_json']=meta;row['_target']='' if duplicate_target else target
        row['_row_action']='source'
        if duplicate_target:added+=1
        if target:used.add(target);used_choices[target]=choice
    for index,row in enumerate(result,1):row['row_no']=index
    removed=len(items)-len(used) if mode=='replace_all' else 0
    missing_fields=sorted({label for row in result for field,label in MISSING_LABELS.items() if missing(row,field)})
    return {'policy':POLICY,'mode':mode,'rows':result,'fees':selected_fees,'changes':changes,
            'selected_row_ids':row_ids,'selected_fee_ids':fee_ids,'added_count':added,'removed_count':removed,
            'updated_count':len({c['item_name'] for c in changes if c['item_name']}),
            'missing_fields':missing_fields,'unresolved':(['来源完整性未确认，缺失资料请继续补充。'] if mode=='replace_all' else []),
            'can_apply':bool(chosen or selected_fees),'catalog_fingerprint':catalog['fingerprint']}
