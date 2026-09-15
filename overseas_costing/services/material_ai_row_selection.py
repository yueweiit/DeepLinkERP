"""Pure row catalog and server-owned projection for selected AI suggestions."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from . import material_ai_fee_policy
from .effective_logistics_source import json_dict
from .logistics_settlement.fee_policy import row_scopes
from .logistics_settlement.model import digest
from .material_value_semantics import is_effectively_missing
from overseas_costing.utils.field_mapper import normalize_unit

POLICY = 'ai-field-review-1'
PHYSICAL = ('gross_weight_kg','net_weight_kg','volume_m3','volume_weight_kg','chargeable_weight_kg','weight_ratio','package_count','packaging_type')
IDENTITY = ('material_code','product_name','spec_model')
FILL_FIELDS = (*PHYSICAL,'actual_shipped_qty','shipped_uom','project_collection','unit_price','purchase_currency','purchase_uom','unit_price_uom','shipment_value_rmb')
MISSING_LABELS = {'material_code':'SKU','actual_shipped_qty':'数量','shipped_uom':'单位','gross_weight_kg':'毛重','volume_m3':'体积'}


def missing(row, field):
    mask = json_dict(row.get('extra_json')).get('settlement_packing_missing') or []
    return (is_effectively_missing(field,row.get(field),row)
            or (field == 'actual_shipped_qty' and 'quantity' in mask))


def _unit(row):
    return normalize_unit(row.get('shipped_uom') or row.get('unit') or row.get('purchase_uom') or '')


def _matches(row, items):
    stable = row.get('stable_line_key')
    exact = [i for i in items if stable and i.get('stable_line_key') == stable]
    if exact:
        return exact
    code = str(row.get('material_code') or '').strip().casefold()
    if code:
        candidates = [i for i in items if str(i.get('material_code') or '').strip().casefold()==code]
        if len(candidates) > 1 and row.get('actual_shipped_qty') not in (None, ''):
            try:
                quantity = Decimal(str(row.get('actual_shipped_qty')))
                narrowed = [item for item in candidates if Decimal(str(
                    item.get('actual_shipped_qty') if item.get('actual_shipped_qty') not in (None, '')
                    else item.get('quantity'))) == quantity]
                if narrowed:
                    candidates = narrowed
            except (InvalidOperation, TypeError, ValueError):
                pass
        return candidates
    name = str(row.get('product_name') or '').strip().casefold()
    return [i for i in items if name and str(i.get('product_name') or '').strip().casefold()==name
            and str(row.get('spec_model') or '').strip().casefold()==str(i.get('spec_model') or '').strip().casefold()
            and _unit(row)==_unit(i)]


def _source_values(row):
    values = {k:deepcopy(row.get(k)) for k in (*IDENTITY,*FILL_FIELDS,'quantity','unit','stable_line_key','actual_shipped_qty_mode')}
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
    valuation = json_dict(row.get('extra_json')).get('shipment_valuation') or {}
    _apply_valuation_values(values, valuation)
    return values


def _apply_valuation_values(values, valuation):
    if (isinstance(valuation, dict) and valuation.get('amount_rmb') is not None
            and not valuation.get('error')):
        values['shipment_value_rmb'] = str(valuation['amount_rmb'])
        values['shipment_valuation_status'] = str(valuation.get('status') or 'automatic')
        values['shipment_valuation_ref'] = digest(
            'shipment-valuation-summary-1', valuation.get('amount_rmb'), valuation.get('unit_price'),
            valuation.get('currency'), valuation.get('quantity'), valuation.get('uom'),
            valuation.get('source_hash'), valuation.get('source_refs') or valuation.get('source'))
        refs = valuation.get('source_refs') or []
        values['shipment_value_source'] = deepcopy(
            valuation.get('source') or (refs[0] if refs else {}))
        if valuation.get('unit_price') is not None:
            values['unit_price'] = valuation.get('unit_price')
        if valuation.get('currency'):
            values['purchase_currency'] = valuation.get('currency')


def _source_groups(catalog_rows, sources):
    from .source_priority_service import rank_material_packing_sources
    ordered=rank_material_packing_sources(sources or [])
    groups=[];by_key={};aliases={}
    for source in ordered:
        source_id=str(source.get('source_id') or '')
        key=str(source.get('parent_source_id') or source.get('logical_source_id') or source_id)
        if not key:continue
        if key not in by_key:
            group={'group_id':digest(POLICY,'source-group',key),'source_id':key,
                   'source_label':str(source.get('source_label') or source.get('file_name') or key),
                   'source_kind':str(source.get('source_kind') or ''),'source_updated_at':str(source.get('source_updated_at') or source.get('occurred_at') or ''),
                   'priority':int(source.get('priority') or len(groups)+1),
                   'priority_reason':str(source.get('priority_reason') or ''),
                   'workflow_stage':str(source.get('workflow_stage') or 'other'),
                   'workflow_rank':int(source.get('workflow_rank') if source.get('workflow_rank') is not None else 3),
                   'evidence_kind':str(source.get('evidence_kind') or 'other'),
                   'evidence_rank':int(source.get('evidence_rank') if source.get('evidence_rank') is not None else 4),
                   'actual_packing_match_status':str(source.get('actual_packing_match_status') or 'none'),
                   'actual_packing_match_id':str(source.get('actual_packing_match_id') or ''),
                   'actual_packing_match_revision':str(source.get('actual_packing_match_revision') or ''),
                   'source_field':str(source.get('source_field') or ''),
                   'workflow_field_id':str(source.get('workflow_field_id') or ''),
                   'dedicated_packing_attachment':bool(source.get('dedicated_packing_attachment')),
                   'row_ids':[],'source_ids':[],'has_conflicts':False}
            by_key[key]=group;groups.append(group)
        group=by_key[key]
        group['source_ids'].append(source_id)
        for alias in (source_id,source.get('resolver_source_id'),source.get('logical_source_id'),source.get('parent_source_id')):
            if str(alias or ''):aliases[str(alias)]=group
    for row in catalog_rows:
        if row.get('origin')!='source':continue
        matched=[]
        for ref in row.get('source_refs') or []:
            group=aliases.get(str(ref.get('source_id') or ''))
            if group and group not in matched:matched.append(group)
        group=min(matched,key=lambda value:value['priority']) if matched else None
        if group:
            row.update(source_group_id=group['group_id'],source_priority=group['priority'],source_label=group['source_label'],
                       workflow_stage=group['workflow_stage'],workflow_rank=group['workflow_rank'],
                       evidence_kind=group['evidence_kind'],evidence_rank=group['evidence_rank'],
                       priority_reason=group['priority_reason'])
            group['row_ids'].append(row['row_id'])
        else:
            row.update(source_group_id='',source_priority=len(groups)+1,source_label='其他识别结果',
                       workflow_stage='other',workflow_rank=3,evidence_kind='other',evidence_rank=4,
                       priority_reason='来源未分类，不作为高优先级默认值。')
        row['conflict_fields']=[]
    targets={str(row.get('target_item_name') or '') for row in catalog_rows if row.get('can_update')}
    for target in targets:
        seen=set()
        candidates=sorted((row for row in catalog_rows if row.get('can_update') and str(row.get('target_item_name') or '')==target),
                          key=lambda row:(int(row.get('source_priority') or 999999),str(row.get('row_id') or '')))
        for row in candidates:
            present={field for field in row.get('fields') or [] if not missing(row.get('values') or {},field)}
            overlap=sorted(present & seen)
            row['meaningful_field_count']=len(present)
            row['conflict_fields']=overlap
            row['lower_priority']=bool(seen) and bool(overlap)
            if overlap:
                group=next((value for value in groups if value['group_id']==row.get('source_group_id')),None)
                if group:group['has_conflicts']=True
            seen.update(present)
            row['default_update_selected']=False
    return groups


def _field_candidates(catalog_rows):
    """Resolve defaults per field while leaving every server-validated option selectable."""

    result=[]
    rows_by_id={str(row.get('row_id') or ''):row for row in catalog_rows}
    for row in catalog_rows:
        if row.get('origin')!='source' or not row.get('can_update'):
            continue
        confidence=float(row.get('confidence') or 0)
        for fieldname in row.get('fields') or []:
            value=(row.get('values') or {}).get(fieldname)
            if missing(row.get('values') or {},fieldname):
                continue
            candidate_id=digest(POLICY,'field-candidate',row.get('row_id'),row.get('target_item_name'),fieldname)
            can_apply=bool(row.get('candidate_can_apply'))
            result.append({
                'candidate_id':candidate_id,'item_name':row.get('target_item_name'),'fieldname':fieldname,
                'suggested_value':deepcopy(value),'row_id':row.get('row_id'),'source_group_id':row.get('source_group_id'),
                'source_label':row.get('source_label'),'source_refs':deepcopy(row.get('source_refs') or []),
                'workflow_stage':row.get('workflow_stage') or 'other','workflow_rank':int(row.get('workflow_rank') or 0),
                'evidence_kind':row.get('evidence_kind') or 'other','evidence_rank':int(row.get('evidence_rank') or 0),
                'priority_reason':row.get('priority_reason') or '','confidence':confidence,
                'default_eligible':fieldname not in set(row.get('existing_value_conflict_fields') or []),
                'can_apply':can_apply,'default_selected':False,'resolution_reason':(
                    '服务端已校验，可手工改选。' if can_apply else '证据置信度不足，仅供核对。'),
            })
    grouped={}
    for candidate in result:
        grouped.setdefault((candidate['item_name'],candidate['fieldname']),[]).append(candidate)
    for candidates in grouped.values():
        eligible=[candidate for candidate in candidates if candidate['can_apply'] and candidate['default_eligible'] and candidate['confidence']>=0.9]
        if not eligible:
            continue
        best_rank=min((candidate['workflow_rank'],candidate['evidence_rank']) for candidate in eligible)
        best=[candidate for candidate in eligible if (candidate['workflow_rank'],candidate['evidence_rank'])==best_rank]
        distinct={_canonical_field_candidate(candidate['fieldname'],candidate['suggested_value']) for candidate in best}
        if len(distinct)>1:
            for candidate in best:
                candidate['resolution_reason']='同级来源存在冲突，服务端不武断选值，请人工选择。'
            continue
        winner=min(best,key=lambda candidate:(-candidate['confidence'],candidate['candidate_id']))
        winner['default_selected']=True
        winner['resolution_reason']=(
            f"{winner['priority_reason'] or '按流程和证据优先级'} 本字段已默认选择。"
        )
        for candidate in candidates:
            if candidate is winner or candidate in best:
                continue
            candidate['resolution_reason']='优先级较低，保留为本字段可改选候选。'
    defaults={candidate['row_id'] for candidate in result if candidate['default_selected']}
    for row_id,row in rows_by_id.items():
        if row.get('origin')!='source':
            continue
        count=sum(1 for candidate in result if candidate['row_id']==row_id and candidate['default_selected'])
        row['default_update_selected']=row_id in defaults
        row['default_selected']=bool(row.get('can_fill') and row_id in defaults)
        row['default_selection_reason']=(
            f'逐字段裁决后，本来源提供 {count} 个已默认选择字段。'
            if count else '本来源未提供默认字段，但合法候选仍可逐字段改选。'
        )
    return result


def _canonical_field_candidate(fieldname,value):
    if fieldname in PHYSICAL or fieldname in {'actual_shipped_qty','unit_price','shipment_value_rmb'}:
        try:return format(Decimal(str(value)).normalize(),'f')
        except (InvalidOperation,TypeError,ValueError):pass
    return str(value or '').strip().casefold()


def catalog(items, proposals, fees, context, *, run_id, sources=None):
    """Do not expose inherited purchase values as newly recognized packing evidence."""
    from .effective_source_values import project_source_values
    items=[project_source_values(i,context) for i in items]
    from .shipment_cost_service import shipment_value
    for item in items:
        current_valuation = shipment_value(item)
        item['shipment_value_rmb'] = current_valuation.get('amount_rmb')
        item['shipment_valuation_status'] = current_valuation.get('status')
        item['shipment_value_source'] = deepcopy((current_valuation.get('source_refs') or [{}])[0])
    original={str(i['name']):i for i in items}
    rows=[];occurrences=Counter();proposal_rows={}
    def add(values, proposal, *, origin='source', target='', stable='', fields=None, price_metadata=None,
            shipment_valuation=None):
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
            if not missing(values,'actual_shipped_qty') and (not Decimal(str(quantity)).is_finite() or Decimal(str(quantity))<0):
                valid=False;reason='数量无效或为负数，请核对来源。'
        except (InvalidOperation,ValueError):valid=False;reason='数量格式无法识别。'
        if proposal.get('blocked'):
            valid=False;reason=proposal.get('reason') or '来源资料待核对。'
        fill_fields=list(fields if fields is not None else FILL_FIELDS)
        if origin=='source' and target and not any(not missing(values,f) and missing(original[target],f) for f in fill_fields):
            fillable=False
            reason=reason or '当前物料已有明确值，本行没有可补的空缺。'
        else:fillable=bool(origin=='source' and valid and len(matches)==1 and target)
        updateable=bool(origin=='source' and valid and len(matches)==1 and target)
        addable=bool(origin=='source' and valid and not matches)
        action=('retain' if origin=='current' else 'update' if updateable else 'add_candidate' if valid and not matches else 'review')
        if origin=='source' and action=='add_candidate':
            reason=reason or '未匹配当前物料；请使用单独确认新增。'
        default_replace_selected=bool(
            origin=='source' and valid and len(matches)<=1
            and proposal.get('default_selected',False) and not proposal.get('conflict')
        )
        rows.append({'row_id':row_id,'origin':origin,'label':'当前已有' if origin=='current' else '本次识别',
                     'values':values,'target_item_name':target,'action':action,
                     'can_fill':fillable,'can_update':updateable,'can_add':addable,'can_replace':valid,
                     'default_selected':bool(origin=='source' and fillable and proposal.get('default_selected',False) and not proposal.get('conflict')),
                     'default_update_selected':bool(updateable and proposal.get('default_selected',False) and not proposal.get('conflict')),
                     'default_replace_selected':default_replace_selected,
                     'meaningful_field_count':sum(not missing(values,field) for field in fill_fields),
                     'default_selection_reason':'',
                     'blocked_reason':reason,'source_refs':deepcopy(proposal.get('source_refs') or []),
                     'confidence':float(proposal.get('confidence') if proposal.get('confidence') is not None else (1 if proposal.get('default_selected') else 0)),
                     'existing_value_conflict_fields':deepcopy(proposal.get('existing_value_conflict_fields') or []),
                     'candidate_can_apply':bool(valid and len(matches)==1 and target and not proposal.get('blocked')),
                     'proposal_id':proposal.get('proposal_id'),'proposal_type':proposal.get('proposal_type'),'fields':fill_fields})
        if price_metadata is not None:
            rows[-1]['_price_metadata']=deepcopy(price_metadata)
        if shipment_valuation is not None:
            rows[-1]['_shipment_valuation']=deepcopy(shipment_valuation)
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
                evidence = evidence_row if evidence_row is not None else row
                values=_source_values(evidence)
                values['actual_shipped_qty_mode']=(evidence.get('actual_shipped_qty_mode')
                                                    or row.get('actual_shipped_qty_mode'))
                values['stable_line_key'] = values.get('stable_line_key') or row.get('stable_line_key')
                shipment_valuation=(json_dict(evidence.get('extra_json')).get('shipment_valuation')
                                    or json_dict(row.get('extra_json')).get('shipment_valuation'))
                _apply_valuation_values(values, shipment_valuation)
                # Reconciliation copied procurement facts from old rows; those are not evidence of a new price.
                reviewed_purchase = row.get('_review_purchase_values')
                if isinstance(reviewed_purchase,dict):
                    values.update({field:deepcopy(reviewed_purchase.get(field)) for field in
                                   ('unit_price','purchase_currency','purchase_uom','unit_price_uom')})
                else:
                    for field in ('unit_price','purchase_currency','purchase_uom','unit_price_uom'):values.pop(field,None)
                add(values,proposal,stable=row.get('stable_line_key') or row.get('name'),
                    price_metadata=row.get('_review_price_metadata'), shipment_valuation=shipment_valuation)
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
            if 'actual_shipped_qty' in fields and proposal.get('result_origin')=='SYSTEM':
                values['actual_shipped_qty_mode']='EXPLICIT_SOURCE'
            add(values,proposal,target=target,fields=list(fields))
    for item in items:
        add(deepcopy(item),{'proposal_id':'current:'+item['name']},origin='current',target=item['name'],stable=item['name'],fields=[])
    source_groups=_source_groups(rows,sources)
    field_candidates=_field_candidates(rows)
    fee_rows=[p for p in material_ai_fee_policy.decorate(proposals,fees,context) if p.get('proposal_type')=='fee_update']
    return {'policy':POLICY,'rows':rows,'fees':fee_rows,'source_groups':source_groups,
            'field_candidates':field_candidates,
            'fingerprint':digest(POLICY,run_id,rows,fee_rows,source_groups,field_candidates)}


def project(items, catalog, row_ids, fee_ids, mode, *, field_choices=None):
    if mode not in ('fill_missing','update_selected','add_selected','replace_all'):raise ValueError('请选择补充空缺、更新所选行、单独新增或替换整票。')
    if not isinstance(row_ids,list) or not isinstance(fee_ids,list):raise ValueError('请选择有效的物料行和费用。')
    if any(not isinstance(i,str) for i in row_ids+fee_ids) or len(row_ids)!=len(set(row_ids)) or len(fee_ids)!=len(set(fee_ids)):
        raise ValueError('选择包含重复或无效行。')
    if mode=='add_selected' and fee_ids:
        raise ValueError('新增物料必须单独确认，不能同时采用费用。')
    rows_by_id={r['row_id']:r for r in catalog['rows']};fees_by_id={r['proposal_id']:r for r in catalog['fees']}
    if set(row_ids)-rows_by_id.keys() or set(fee_ids)-fees_by_id.keys():raise ValueError('所选内容不属于当前草稿，请刷新预览。')
    chosen=[r for r in catalog['rows'] if r['row_id'] in row_ids]
    if mode=='update_selected':
        chosen.sort(key=lambda row:(int(row.get('source_priority') or 999999),str(row.get('row_id') or '')))
    selected_fees=[r for r in catalog['fees'] if r['proposal_id'] in fee_ids]
    selected_field_candidates=[]
    if field_choices is not None:
        if not isinstance(field_choices,dict) or any(not isinstance(key,str) or not isinstance(value,str) for key,value in field_choices.items()):
            raise ValueError('逐字段选择格式不正确。')
        fields_by_id={candidate['candidate_id']:candidate for candidate in catalog.get('field_candidates') or []}
        if set(field_choices.values())-fields_by_id.keys():
            raise ValueError('所选字段候选不属于当前草稿，请刷新预览。')
        for expected_key,candidate_id in field_choices.items():
            candidate=fields_by_id[candidate_id]
            actual_key=f"{candidate['item_name']}:{candidate['fieldname']}"
            if expected_key!=actual_key:
                raise ValueError('逐字段选择与物料不匹配。')
            if not candidate.get('can_apply'):
                raise ValueError(candidate.get('resolution_reason') or '本字段候选不可采用。')
            selected_field_candidates.append(candidate)
    for row in chosen:
        allowed_key=('can_fill' if mode=='fill_missing' else 'can_update' if mode=='update_selected'
                     else 'can_add' if mode=='add_selected' else 'can_replace')
        if not row.get(allowed_key):raise ValueError(row['blocked_reason'] or '本行不可采用。')
    for fee in selected_fees:
        if not fee['can_apply']:raise ValueError(fee['blocked_reason'])
    fee_keys=[str((fee.get('payload') or {}).get('logical_fee_key') or '') for fee in selected_fees]
    fee_groups=[fee['conflict_group'] for fee in selected_fees if fee.get('conflict_group')]
    selected_scopes=[row_scopes(fee.get('payload') or {}) for fee in selected_fees]
    overlapping_scopes=set()
    covered_scopes=set()
    for scopes in selected_scopes:
        overlapping_scopes.update(covered_scopes & scopes)
        covered_scopes.update(scopes)
    if (len(fee_keys)!=len(set(fee_keys)) or len(fee_groups)!=len(set(fee_groups))
            or overlapping_scopes):
        raise ValueError('同一费用有多份报价，请只选择一份；其他报价保留参考。')
    if mode=='replace_all' and not chosen:raise ValueError('至少选择一条物料，不能用空结果清空整票。')
    effective={r['target_item_name']:r['values'] for r in catalog['rows'] if r['origin']=='current'}
    items=[deepcopy(effective.get(i['name'],i)) for i in items]
    result=[{**deepcopy(i),'_row_action':'retain'} for i in items] if mode in ('fill_missing','update_selected','add_selected') else []
    original={i['name']:i for i in items};used=set();used_choices={};changes=[];added=0
    if field_choices is not None and mode in ('fill_missing','update_selected'):
        for candidate in sorted(selected_field_candidates,key=lambda value:(value['item_name'],value['fieldname'],value['candidate_id'])):
            row=next((value for value in result if value.get('name')==candidate['item_name']),None)
            if row is None:raise ValueError('逐字段候选的目标物料已变化，请刷新。')
            field=candidate['fieldname']
            if mode=='fill_missing' and not missing(row,field):
                continue
            before=row.get(field);row[field]=deepcopy(candidate['suggested_value'])
            meta=json_dict(row.get('extra_json'));field_refs=meta.setdefault('ai_row_fields',{})
            field_refs[field]={'candidate_id':candidate['candidate_id'],'row_id':candidate['row_id'],
                               'source_refs':deepcopy(candidate.get('source_refs') or [])}
            mask=set(meta.get('settlement_packing_missing') or []);mask.discard(field)
            if field=='actual_shipped_qty':mask.discard('quantity')
            meta['settlement_packing_missing']=sorted(mask);row['extra_json']=meta;row['_row_action']='source'
            changes.append({'candidate_id':candidate['candidate_id'],'row_id':candidate['row_id'],
                'item_name':candidate['item_name'],'fieldname':field,'previous_value':before,'value':row[field],
                'source_refs':deepcopy(candidate.get('source_refs') or []),'source_group_id':candidate.get('source_group_id'),
                'source_priority':candidate.get('workflow_rank'),'workflow_stage':candidate.get('workflow_stage'),
                'evidence_kind':candidate.get('evidence_kind'),'conflict_override':not candidate.get('default_selected')})
        for index,row in enumerate(result,1):row['row_no']=index
        actual_by_field={(change['item_name'],change['fieldname']):{
            key:deepcopy(change.get(key)) for key in ('item_name','fieldname','candidate_id','row_id','source_refs','source_group_id','source_priority','workflow_stage','evidence_kind','conflict_override')
        } for change in changes}
        missing_fields=sorted({label for row in result for field,label in MISSING_LABELS.items() if missing(row,field)})
        return {'policy':POLICY,'mode':mode,'rows':result,'fees':selected_fees,'changes':changes,
                'selected_row_ids':row_ids,'selected_fee_ids':fee_ids,'selected_field_choices':deepcopy(field_choices),
                'added_count':0,'removed_count':0,'updated_count':len({change['item_name'] for change in changes}),
                'actual_sources':list(actual_by_field.values()),'missing_fields':missing_fields,'unresolved':[],
                'can_apply':bool(changes or selected_fees),'catalog_fingerprint':catalog['fingerprint']}
    for choice in chosen:
        incoming=choice['values'];target=choice['target_item_name'];refs=choice['source_refs']
        duplicate_target=False
        if mode=='replace_all' and target and target in used:
            previous=used_choices[target]
            duplicate_target=(mode=='replace_all' and choice['proposal_type']=='logistics_reconcile' and previous['proposal_id']==choice['proposal_id'])
            if not duplicate_target:raise ValueError('所选多行对应同一现有物料，请仅选择一种来源。')
        if choice['origin']=='current':
            row=deepcopy(original[target]);row.update(_target=target,_row_action='retain');used.add(target);used_choices[target]=choice;result.append(row);continue
        if mode in ('fill_missing','update_selected') and target:
            row=next(r for r in result if r['name']==target)
            fields=[f for f in choice['fields'] if not missing(incoming,f)
                    and (mode=='update_selected' or missing(row,f))]
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
        if mode=='update_selected' and choice.get('_price_metadata') is not None:
            # Keep the trusted purchase lineage server-side so a later source
            # refresh can detect and audit changed prices for the same row.
            row['_price_metadata']=deepcopy(choice['_price_metadata'])
        if ('shipment_value_rmb' in fields and choice.get('_shipment_valuation') is not None):
            row['_shipment_valuation']=deepcopy(choice['_shipment_valuation'])
        for field in fields:
            before=row.get(field)
            row[field]=deepcopy(incoming[field]);field_refs[field]={'row_id':choice['row_id'],'source_refs':refs}
            changes.append({'row_id':choice['row_id'],'item_name':target,'fieldname':field,
                'previous_value':before,'value':row[field],'source_refs':deepcopy(refs),
                'source_group_id':choice.get('source_group_id'),'source_priority':choice.get('source_priority'),
                'conflict_override':field in (choice.get('conflict_fields') or [])})
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
    actual_by_field={}
    for change in changes:
        audit_target=str(change.get('item_name') or change.get('row_id') or '')
        actual_by_field[(audit_target,change['fieldname'])]={
            key:deepcopy(change.get(key)) for key in
            ('item_name','fieldname','row_id','source_refs','source_group_id','source_priority','conflict_override')}
    missing_fields=sorted({label for row in result for field,label in MISSING_LABELS.items() if missing(row,field)})
    return {'policy':POLICY,'mode':mode,'rows':result,'fees':selected_fees,'changes':changes,
            'selected_row_ids':row_ids,'selected_fee_ids':fee_ids,'added_count':added,'removed_count':removed,
            'updated_count':len({c['item_name'] for c in changes if c['item_name']}),
            'actual_sources':list(actual_by_field.values()),
            'missing_fields':missing_fields,'unresolved':(['来源完整性未确认，缺失资料请继续补充。'] if mode=='replace_all' else []),
            'can_apply':bool(chosen or selected_fees),'catalog_fingerprint':catalog['fingerprint']}
