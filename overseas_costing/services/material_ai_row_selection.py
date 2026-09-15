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

POLICY = 'ai-field-review-3'
PHYSICAL = ('gross_weight_kg','net_weight_kg','volume_m3','volume_weight_kg','chargeable_weight_kg','weight_ratio','package_count','packaging_type')
IDENTITY = ('material_code','product_name','spec_model')
FILL_FIELDS = (*PHYSICAL,'actual_shipped_qty','shipped_uom','project_collection','unit_price','purchase_currency','purchase_uom','unit_price_uom','shipment_value_rmb')
MISSING_LABELS = {'material_code':'SKU','actual_shipped_qty':'数量','shipped_uom':'单位','gross_weight_kg':'毛重','volume_m3':'体积'}
STAGE_SPECS = (
    ('payment', 0, '支付申请'),
    ('international_logistics', 1, '国际物流'),
    ('purchase', 2, '采购支出'),
)
FEE_STAGE_SPECS = STAGE_SPECS[:2]
DEFAULT_WORKFLOW_STAGES = frozenset(stage for stage,_rank,_label in STAGE_SPECS)
EXPLICIT_CORRECTION_MARKERS = ('更正', '改为', '以此为准', '原值错误')
CORRECTION_FIELD_MARKERS = {
    'gross_weight_kg': ('毛重', 'gross weight'),
    'net_weight_kg': ('净重', 'net weight'),
    'volume_m3': ('体积', '方数', 'cbm', 'm3'),
    'volume_weight_kg': ('体积重', 'volume weight'),
    'chargeable_weight_kg': ('计费重', 'chargeable weight'),
    'weight_ratio': ('重量占比', '占比'),
    'package_count': ('箱数', '件数', 'package count'),
    'packaging_type': ('包装', '箱型', 'packaging'),
    'actual_shipped_qty': ('实发数量', '发货数量', '数量'),
    'shipped_uom': ('发货单位', '单位'),
    'project_collection': ('项目归属', '归属'),
    'unit_price': ('采购单价', '单价'),
    'purchase_currency': ('采购币种', '币种'),
    'purchase_uom': ('采购单位',),
    'unit_price_uom': ('单价单位',),
    'shipment_value_rmb': ('本次发货货值', '货值'),
}
_FIELD_MARKER_TO_FIELDS = {}
for _field_name, _field_markers in CORRECTION_FIELD_MARKERS.items():
    for _field_marker in _field_markers:
        _FIELD_MARKER_TO_FIELDS.setdefault(str(_field_marker).casefold(), []).append(_field_name)
_FIELD_MARKER_PATTERN = re.compile('|'.join(
    re.escape(marker)
    for marker in sorted(_FIELD_MARKER_TO_FIELDS, key=lambda value: (-len(value), value))
))
DIRECTIONAL_ARROW_PATTERN = re.compile(
    r'(?<![\d.])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:→|->|=>)\s*[-+]?\d[\d,]*(?:\.\d+)?'
)
READABLE_SOURCE_STATUSES = frozenset({'READ', 'PARSED', 'COMPLETED', 'PARTIAL', 'AVAILABLE'})
UNREADABLE_SOURCE_STATUSES = frozenset({'FAILED', 'SKIPPED', 'UNREADABLE'})


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


def _stage_snapshot_id(stage):
    return digest(POLICY, 'stage-snapshot', stage)


def _process_instance_id(source):
    source=source or {}
    return str(
        source.get('process_instance_id')
        or source.get('approval_instance_id')
        or source.get('source_instance_id')
        or source.get('parent_source_id')
        or source.get('logical_source_id')
        or source.get('source_id')
        or ''
    )


def _source_status(source):
    return str((source or {}).get('read_status') or (source or {}).get('status') or '').strip().upper()


def _evidence_record(source):
    source=source or {}
    return {
        'evidence_id':str(source.get('source_id') or ''),
        'evidence_kind':str(source.get('evidence_kind') or 'other'),
        'source_label':str(source.get('source_label') or source.get('file_name') or source.get('source_id') or ''),
        'occurred_at':str(source.get('occurred_at') or source.get('source_updated_at') or ''),
        'read_status':_source_status(source) or 'NO_RESULT',
    }


def _correction_text(source):
    source=source or {}
    if str(source.get('evidence_kind') or '') != 'comment':
        return ''
    return '\n'.join(str(source.get(key) or '') for key in (
        'comment_text','remark','text','content','text_excerpt',
    ))


def _is_explicit_correction(source):
    text=_correction_text(source)
    return bool(text and (
        any(marker in text for marker in EXPLICIT_CORRECTION_MARKERS)
        or _has_directional_arrow_correction(text)
    ))


def _has_directional_arrow_correction(text):
    text=str(text or '').casefold()
    return bool(
        DIRECTIONAL_ARROW_PATTERN.search(text)
        and any(
            str(field_marker).casefold() in text
            for field_markers in CORRECTION_FIELD_MARKERS.values()
            for field_marker in field_markers
        )
    )


def _explicit_correction_clauses(text, identifiers=()):
    identifier_index = identifiers if isinstance(identifiers, dict) else None
    parts=[
        value.strip().casefold()
        for value in re.split(
            r'[\r\n；;。！!？?]+|(?<!\d)[,，]|[,，](?!\d)',str(text or ''))
        if value.strip()
    ]
    clauses=[]
    for index,part in enumerate(parts):
        markers=[marker for marker in EXPLICIT_CORRECTION_MARKERS if marker in part]
        directional_arrow=_has_directional_arrow_correction(part)
        if not markers and not directional_arrow:
            continue
        marker_end=(max(part.rfind(marker)+len(marker) for marker in markers)
                    if markers else 0)
        suffix=(part[marker_end:].strip().lstrip(':：').strip()
                if markers else part)
        has_field=any(
            str(field_marker).casefold() in part
            for field_markers in CORRECTION_FIELD_MARKERS.values()
            for field_marker in field_markers
        )
        has_identifier=(
            bool(_indexed_identifier_matches(part, identifier_index))
            if identifier_index is not None
            else any(_identifier_spans(identifier,part) for identifier in identifiers)
        )
        clause_parts=[]
        if not has_field and not has_identifier and index>0:
            clause_parts.append(parts[index-1])
        clause_parts.append(part)
        if (not has_field or not suffix) and index+1<len(parts):
            clause_parts.append(parts[index+1])
        clauses.append(' '.join(clause_parts))
    return clauses


def _identifier_spans(identifier, clause):
    identifier=str(identifier or '').strip().casefold()
    if not identifier:
        return []
    if identifier.isascii() and re.search(r'[a-z0-9]',identifier):
        return [match.span() for match in re.finditer(
            rf'(?<![a-z0-9]){re.escape(identifier)}(?![a-z0-9])',clause,
        )]
    return [match.span() for match in re.finditer(re.escape(identifier),clause)]


def _longest_identifier_matches(clause, identifiers):
    matches=[
        (identifier,start,end)
        for identifier in identifiers
        for start,end in _identifier_spans(identifier,clause)
    ]
    return {
        identifier for identifier,start,end in matches
        if not any(
            other_start<=start and end<=other_end and len(other)>len(identifier)
            for other,other_start,other_end in matches
        )
    }


def _identifier_index(identifiers):
    """Build one bounded matcher for the material identifiers in this catalog."""

    normalized=sorted(
        {str(identifier or '').strip().casefold() for identifier in identifiers if str(identifier or '').strip()},
        key=lambda value:(-len(value),value),
    )
    alternatives=[]
    for identifier in normalized:
        escaped=re.escape(identifier)
        if identifier.isascii() and re.search(r'[a-z0-9]',identifier):
            escaped=rf'(?<![a-z0-9]){escaped}(?![a-z0-9])'
        alternatives.append(escaped)
    return {
        'pattern':re.compile('|'.join(alternatives)) if alternatives else None,
        'identifiers':frozenset(normalized),
    }


def _indexed_identifier_matches(clause, identifier_index):
    pattern=(identifier_index or {}).get('pattern')
    if pattern is None:
        return set()
    return {
        match.group(0).casefold()
        for match in pattern.finditer(str(clause or '').casefold())
    }


def _field_marker_matches(clause):
    """Return only the longest field marker at each text position."""

    result={}
    for match in _FIELD_MARKER_PATTERN.finditer(str(clause or '').casefold()):
        marker=match.group(0).casefold()
        for fieldname in _FIELD_MARKER_TO_FIELDS.get(marker,()):
            result.setdefault(fieldname,[]).append((match.start(),match.end(),marker))
    return result


def _correction_value_in_clause(clause, fieldname, value, field_matches=None):
    matches=(field_matches if field_matches is not None else _field_marker_matches(clause)).get(fieldname,())
    for position,end,_marker in matches:
        field_tail=clause[end:]
        direction=re.search(
            r'(?:更正为|改为|改成|调整为|变更为|以此为准)\s*[:：]?|(?:→|->|=>)',
            field_tail,
        )
        if direction:
            value_text=field_tail[direction.end():]
        elif any(correction_marker in clause[:position]
                 for correction_marker in ('更正','以此为准')):
            value_text=field_tail
        else:
            continue
        try:
            expected=Decimal(str(value).replace(',','')).normalize()
        except (InvalidOperation,TypeError,ValueError):
            expected=None
        if expected is not None:
            tokens=re.findall(r'(?<![\d.])[-+]?\d[\d,]*(?:\.\d+)?(?![\d.])',value_text)
            if not tokens:
                continue
            try:
                if Decimal(tokens[0].replace(',','')).normalize()==expected:
                    return True
            except InvalidOperation:
                continue
        else:
            normalized=str(value or '').strip().casefold()
            if normalized and normalized in value_text:
                return True
    return False


def _material_identifier_counts(catalog_rows):
    counts=Counter()
    for row in catalog_rows:
        if row.get('origin')!='current':
            continue
        values=row.get('values') or {}
        identifiers={
            str(values.get(key) or '').strip().casefold()
            for key in ('stable_line_key','material_code','product_name','spec_model')
            if len(str(values.get(key) or '').strip()) >= 2
        }
        counts.update(identifiers)
    return counts


def _correction_clause_cache(catalog_rows, identifier_counts):
    """Parse each comment once for this catalog; never retain business text globally."""

    identifiers=_identifier_index(identifier_counts)
    parsed={}
    for row in catalog_rows:
        for evidence in row.get('_review_correction_evidence') or []:
            key=(str(evidence.get('source_id') or ''),str(evidence.get('occurred_at') or ''),
                 str(evidence.get('text') or ''))
            if key in parsed:
                continue
            parsed[key]=[
                {
                    'text':clause,
                    'identifiers':_indexed_identifier_matches(clause,identifiers),
                    'fields':_field_marker_matches(clause),
                }
                for clause in _explicit_correction_clauses(evidence.get('text'),identifiers)
            ]
    return parsed


def _matching_correction_evidence(row, fieldname, value, identifier_counts, clause_cache):
    values=row.get('values') or {}
    identifiers={
        str(values.get(key) or '').strip().casefold()
        for key in ('stable_line_key','material_code','product_name','spec_model')
        if len(str(values.get(key) or '').strip()) >= 2
    }
    matches=[]
    field_mismatch=False
    for evidence in row.get('_review_correction_evidence') or []:
        key=(str(evidence.get('source_id') or ''),str(evidence.get('occurred_at') or ''),
             str(evidence.get('text') or ''))
        for parsed in clause_cache.get(key,()):
            clause=parsed['text']
            longest_matches=parsed['identifiers']
            unique_target=any(
                identifier_counts.get(identifier)==1
                and identifier in longest_matches
                for identifier in identifiers
            )
            if unique_target and _correction_value_in_clause(
                    clause,fieldname,value,parsed['fields']):
                matches.append(evidence)
                break
            if unique_target and fieldname not in parsed['fields'] and any(
                    _correction_value_in_clause(clause,other_field,value,parsed['fields'])
                    for other_field in parsed['fields']):
                field_mismatch=True
    match=max(matches,key=lambda evidence:(
        str(evidence.get('occurred_at') or ''),str(evidence.get('source_id') or ''),
    )) if matches else None
    return match,field_mismatch


def _source_groups(catalog_rows, sources):
    from .source_priority_service import rank_material_packing_sources
    ordered=rank_material_packing_sources(sources or [])
    explicit_correction_by_source={
        id(source):_is_explicit_correction(source) for source in ordered
    }
    groups=[];by_key={};aliases={};sources_by_alias={}
    for source in ordered:
        source_id=str(source.get('source_id') or '')
        key=str(source.get('parent_source_id') or source.get('logical_source_id') or source_id)
        if not key:continue
        if key not in by_key:
            group={'group_id':digest(POLICY,'source-group',key),'source_id':key,
                   'process_instance_id':_process_instance_id(source),
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
        for alias in (source_id,source.get('resolver_source_id'),source.get('logical_source_id'),
                      source.get('parent_source_id'),source.get('process_instance_id'),
                      source.get('approval_instance_id'),source.get('source_instance_id')):
            if str(alias or ''):
                alias=str(alias)
                aliases[alias]=group
                sources_by_alias.setdefault(alias,[]).append(source)
    for row in catalog_rows:
        if row.get('origin')!='source':continue
        matched=[];matched_sources=[]
        for ref in row.get('source_refs') or []:
            ref_id=str(ref.get('source_id') or '')
            group=aliases.get(ref_id)
            if group and group not in matched:matched.append(group)
            for source in sources_by_alias.get(ref_id,[]):
                if source not in matched_sources:matched_sources.append(source)
        group=min(matched,key=lambda value:value['priority']) if matched else None
        if group:
            evidence=min(matched_sources,key=lambda value:(
                int(value.get('workflow_rank') if value.get('workflow_rank') is not None else 3),
                int(value.get('priority') or 999999),
                str(value.get('source_id') or ''),
            )) if matched_sources else group
            evidence_chain=[_evidence_record(value) for value in sorted(matched_sources,key=lambda value:(
                int(value.get('workflow_rank') if value.get('workflow_rank') is not None else 3),
                _process_instance_id(value),str(value.get('occurred_at') or value.get('source_updated_at') or ''),
                str(value.get('source_id') or ''),
            ))]
            correction_sources=[
                value for value in matched_sources
                if explicit_correction_by_source.get(id(value),False)
            ]
            correction_source=max(correction_sources,key=lambda value:(
                str(value.get('occurred_at') or value.get('source_updated_at') or ''),
                str(value.get('source_id') or ''),
            )) if correction_sources else None
            process_targets=sorted({
                (str(value.get('workflow_stage') or 'other'),_process_instance_id(value))
                for value in matched_sources
                if value.get('workflow_stage') in DEFAULT_WORKFLOW_STAGES
                and _process_instance_id(value)
            })
            process_ids=sorted({process_id for _stage,process_id in process_targets})
            process_conflict=len(process_targets)>1
            process_conflict_ids=process_ids if process_conflict else []
            row.update(source_group_id=group['group_id'],source_priority=group['priority'],source_label=group['source_label'],
                       workflow_stage=evidence['workflow_stage'],workflow_rank=evidence['workflow_rank'],
                       evidence_kind=evidence['evidence_kind'],evidence_rank=evidence['evidence_rank'],
                       priority_reason=(
                           '候选同时引用多个流程，无法安全确定字段归属。'
                           if process_conflict_ids else evidence['priority_reason']),
                       stage_snapshot_id=(
                           _stage_snapshot_id(evidence['workflow_stage'])
                           if evidence['workflow_stage'] in DEFAULT_WORKFLOW_STAGES
                           and not process_conflict
                           else ''),
                       process_instance_id=('' if process_conflict else _process_instance_id(evidence)),
                       _review_process_conflict_ids=process_conflict_ids,
                       _review_process_conflict=process_conflict,
                       _review_process_targets=[
                           {'workflow_stage':stage,'process_instance_id':process_id}
                           for stage,process_id in process_targets
                       ],
                       _review_evidence_chain=evidence_chain,
                       _review_correction_explicit=bool(correction_source),
                       _review_correction_text=_correction_text(correction_source),
                       _review_correction_evidence=[{
                           'source_id':str(value.get('source_id') or ''),
                           'occurred_at':str(value.get('occurred_at') or value.get('source_updated_at') or ''),
                           'text':_correction_text(value),
                       } for value in correction_sources],
                       _review_occurred_at=str(evidence.get('occurred_at')
                                               or evidence.get('source_updated_at') or ''),
                       _review_primary_source_id=str(evidence.get('source_id') or ''))
            group['row_ids'].append(row['row_id'])
        else:
            row.update(source_group_id='',source_priority=len(groups)+1,source_label='其他识别结果',
                       workflow_stage='other',workflow_rank=3,evidence_kind='other',evidence_rank=4,
                       priority_reason='来源未分类，不作为高优先级默认值。',
                       stage_snapshot_id='',process_instance_id='',
                       _review_process_conflict_ids=[],
                       _review_process_conflict=False,_review_process_targets=[],
                       _review_evidence_chain=[],_review_correction_explicit=False,
                       _review_correction_text='',_review_correction_evidence=[],
                       _review_occurred_at='',_review_primary_source_id='')
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
    """Resolve fields inside each process, then fall through business stages."""

    result=[]
    rows_by_id={str(row.get('row_id') or ''):row for row in catalog_rows}
    identifier_counts=_material_identifier_counts(catalog_rows)
    correction_clause_cache=_correction_clause_cache(catalog_rows,identifier_counts)
    default_stages=DEFAULT_WORKFLOW_STAGES
    for row in catalog_rows:
        if row.get('origin')!='source' or not row.get('can_update'):
            continue
        confidence=float(row.get('confidence') or 0)
        for fieldname in row.get('fields') or []:
            value=(row.get('values') or {}).get(fieldname)
            if missing(row.get('values') or {},fieldname):
                continue
            correction_evidence,field_mismatch=_matching_correction_evidence(
                row,fieldname,value,identifier_counts,correction_clause_cache)
            process_conflict_ids=sorted(set(row.get('_review_process_conflict_ids') or []))
            process_conflict=bool(row.get('_review_process_conflict') or process_conflict_ids)
            candidate_id=digest(POLICY,'field-candidate',row.get('row_id'),row.get('target_item_name'),fieldname)
            can_apply=bool(row.get('candidate_can_apply'))
            result.append({
                'candidate_id':candidate_id,'item_name':row.get('target_item_name'),'fieldname':fieldname,
                'suggested_value':deepcopy(value),'row_id':row.get('row_id'),'source_group_id':row.get('source_group_id'),
                'source_label':row.get('source_label'),'source_refs':deepcopy(row.get('source_refs') or []),
                'source_priority':int(row.get('source_priority') or 999999),
                'workflow_stage':row.get('workflow_stage') or 'other','workflow_rank':int(row.get('workflow_rank') or 0),
                'evidence_kind':('comment' if correction_evidence else row.get('evidence_kind') or 'other'),
                'evidence_rank':(3 if correction_evidence else int(row.get('evidence_rank') or 0)),
                'priority_reason':row.get('priority_reason') or '','confidence':confidence,
                'default_eligible':(
                    not process_conflict
                    and not field_mismatch
                    and fieldname not in set(row.get('existing_value_conflict_fields') or [])),
                'stage_snapshot_id':(
                    (row.get('stage_snapshot_id') or _stage_snapshot_id(row.get('workflow_stage')))
                    if row.get('workflow_stage') in default_stages else ''),
                'process_instance_id':row.get('process_instance_id') or '',
                'process_instance_ids':(
                    process_conflict_ids or ([row.get('process_instance_id')]
                                             if row.get('process_instance_id') else [])),
                'process_conflict':process_conflict,
                'evidence_chain':deepcopy(row.get('_review_evidence_chain') or []),
                'value_evidence_id':str(
                    (correction_evidence or {}).get('source_id')
                    or (row.get('_review_primary_source_id')
                        if len(row.get('_review_evidence_chain') or [])==1 else '') or ''),
                'correction_kind':('explicit' if correction_evidence else 'none'),
                'supersedes_candidate_id':'','effective_in_stage':False,
                'can_apply':can_apply,'default_selected':False,'resolution_reason':(
                    '候选同时引用多个流程，保留手工核对但不作为默认值。'
                    if process_conflict else
                    '更正评论指向其他字段，本候选不作为默认值。'
                    if field_mismatch else
                    '服务端已校验，可手工改选。' if can_apply else '证据置信度不足，仅供核对。'),
                '_review_field_mismatch':field_mismatch,
                '_review_occurred_at':str(
                    (correction_evidence or {}).get('occurred_at')
                    or row.get('_review_occurred_at') or ''),
                '_review_primary_source_id':str(
                    (correction_evidence or {}).get('source_id')
                    or row.get('_review_primary_source_id') or ''),
            })
    correction_counts=Counter(
        (candidate['process_instance_id'],candidate['item_name'],candidate['fieldname'],
         candidate['_review_primary_source_id'])
        for candidate in result if candidate['correction_kind']=='explicit'
    )
    for candidate in result:
        key=(candidate['process_instance_id'],candidate['item_name'],candidate['fieldname'],
             candidate['_review_primary_source_id'])
        if candidate['correction_kind']=='explicit' and correction_counts[key]!=1:
            candidate['correction_kind']='none'
            candidate['resolution_reason']='更正内容未能唯一定位到一个物料字段，保留为人工候选。'
    grouped={}
    for candidate in result:
        grouped.setdefault((candidate['item_name'],candidate['fieldname']),[]).append(candidate)
    for candidates in grouped.values():
        processable=[candidate for candidate in candidates
                     if candidate['workflow_stage'] in default_stages
                     and candidate['can_apply'] and candidate['default_eligible']]
        if not processable:
            continue
        by_process={}
        for candidate in processable:
            process_key=(candidate['workflow_rank'],candidate['workflow_stage'],
                         candidate['process_instance_id'] or candidate['row_id'])
            by_process.setdefault(process_key,[]).append(candidate)
        for process_candidates in by_process.values():
            stream=sorted(process_candidates,key=lambda candidate:(
                1 if candidate['evidence_kind']=='comment' else 0,
                candidate['_review_occurred_at'],candidate['_review_primary_source_id'],
                1 if candidate['correction_kind']=='explicit' else 0,
                candidate['candidate_id'],
            ))
            effective=[]
            for candidate in stream:
                if candidate['correction_kind']=='explicit':
                    if effective:
                        candidate['supersedes_candidate_id']=effective[-1]['candidate_id']
                    for superseded in effective:
                        superseded['effective_in_stage']=False
                        superseded['resolution_reason']='同一流程后续评论已明确更正该字段，原值仅供追溯。'
                    effective=[candidate]
                else:
                    effective.append(candidate)
                candidate['effective_in_stage']=True
        eligible=[candidate for candidate in processable if candidate['confidence']>=0.9]
        winner=None
        conflicted_rank=None
        for stage_rank in sorted({candidate['workflow_rank'] for candidate in eligible}):
            stage=[candidate for candidate in eligible
                   if candidate['workflow_rank']==stage_rank and candidate['effective_in_stage']]
            if not stage:
                continue
            distinct={_canonical_field_candidate(candidate['fieldname'],candidate['suggested_value'])
                      for candidate in stage}
            if len(distinct)>1:
                conflicted_rank=stage_rank if conflicted_rank is None else conflicted_rank
                for candidate in stage:
                    candidate['resolution_reason']='同级来源存在冲突，服务端不武断选值，继续检查下一优先级。'
                continue
            winner=min(stage,key=lambda candidate:(
                candidate['source_priority'],-candidate['confidence'],candidate['candidate_id']))
            break
        if winner:
            winner['default_selected']=True
            winner['resolution_reason']=(
                ('高优先级来源冲突或缺少有效值，已按流程顺序回落；' if conflicted_rank is not None else '')
                + f"{winner['priority_reason'] or '按流程优先级'} 本字段已默认选择。"
            )
        for candidate in candidates:
            if candidate is winner or '明确更正' in candidate['resolution_reason'] or '同级来源存在冲突' in candidate['resolution_reason']:
                continue
            if not candidate['can_apply']:
                continue
            if candidate.get('process_conflict'):
                candidate['resolution_reason']='候选同时引用多个流程，无法安全归属；保留手工核对但不作为默认值。'
            elif candidate.get('_review_field_mismatch'):
                candidate['resolution_reason']='更正评论明确指向其他字段，本候选仅供人工核对。'
            elif not candidate['default_eligible']:
                candidate['resolution_reason']='当前已有受保护的明确值，本候选仅可人工核对。'
            elif candidate['confidence']<0.9:
                candidate['resolution_reason']='证据置信度不足，不作为默认值；仍可人工改选。'
            else:
                candidate['resolution_reason']=(
                    '来源未分类，仅保留为审计候选，不参与默认裁决。'
                    if candidate['workflow_stage'] not in default_stages else
                    '未作为默认值，保留为本字段可改选候选。')
    defaults={candidate['row_id'] for candidate in result if candidate['default_selected']}
    for row_id,row in rows_by_id.items():
        if row.get('origin')!='source':
            continue
        if (row.get('workflow_stage') not in default_stages
                or row.get('_review_process_conflict')
                or row.get('_review_process_conflict_ids')):
            row['default_replace_selected']=False
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


def _stage_row_material_key(row):
    values=row.get('values') or {}
    stable=str(values.get('stable_line_key') or '').strip()
    if stable:
        return f'stable:{stable}'
    target=str(row.get('target_item_name') or '').strip()
    if target:
        return f'target:{target}'
    return 'identity:'+digest(
        POLICY,'stage-material',*(str(values.get(field) or '').strip().casefold()
                                  for field in (*IDENTITY,'unit')))


def _availability_status(evidence, *, has_rows=False):
    statuses={str(row.get('read_status') or '').upper() for row in evidence}
    has_partial='PARTIAL' in statuses
    has_unreadable=bool(statuses & UNREADABLE_SOURCE_STATUSES)
    has_success=bool(statuses & READABLE_SOURCE_STATUSES) or bool(has_rows)
    if has_partial or (has_unreadable and has_success):
        return 'PARTIAL'
    if has_success:
        return 'AVAILABLE'
    return 'UNAVAILABLE'


def _stage_snapshots(catalog_rows, field_candidates, sources):
    """Return the fixed business-stage directory used by the review UI."""

    from .source_priority_service import rank_material_packing_sources
    ordered=rank_material_packing_sources(sources or [])
    candidates_by_row={}
    for candidate in field_candidates:
        candidates_by_row.setdefault(str(candidate.get('row_id') or ''),[]).append(candidate)
    snapshots=[]
    for stage,stage_rank,stage_label in STAGE_SPECS:
        stage_sources=[source for source in ordered if source.get('workflow_stage')==stage]
        stage_rows=sorted(
            (row for row in catalog_rows
             if row.get('origin')=='source' and (
                 row.get('workflow_stage')==stage
                 or any(target.get('workflow_stage')==stage
                        for target in row.get('_review_process_targets') or [])
             )),
            key=lambda row:(str(row.get('process_instance_id') or ''),str(row.get('row_id') or '')),
        )
        process_map={}
        for source in stage_sources:
            process_id=_process_instance_id(source)
            if not process_id:
                continue
            process=process_map.setdefault(process_id,{
                'process_instance_id':process_id,
                'label':str(source.get('approval_title') or source.get('process_title')
                            or source.get('process_name') or source.get('source_label')
                            or source.get('file_name') or process_id),
                'approval_no':str(source.get('approval_no') or ''),
                'source_ids':[],'evidence':[],'row_ids':[],'status':'UNAVAILABLE',
                'has_conflicts':False,'warnings':[],
            })
            source_id=str(source.get('source_id') or '')
            if source_id and source_id not in process['source_ids']:
                process['source_ids'].append(source_id)
            record=_evidence_record(source)
            if record not in process['evidence']:
                process['evidence'].append(record)
        aggregated_rows={}
        process_conflict_warnings=[]
        for row in stage_rows:
            row_candidates=sorted(candidates_by_row.get(str(row.get('row_id') or ''),[]),
                                  key=lambda candidate:(candidate['fieldname'],candidate['candidate_id']))
            material_key=_stage_row_material_key(row)
            values=row.get('values') or {}
            process_targets=row.get('_review_process_targets') or []
            all_process_ids=(sorted(set(row.get('_review_process_conflict_ids') or []))
                             or [str(row.get('process_instance_id') or '')])
            process_ids=sorted({
                str(target.get('process_instance_id') or '')
                for target in process_targets
                if target.get('workflow_stage')==stage
                and str(target.get('process_instance_id') or '')
            }) or ([str(row.get('process_instance_id') or '')]
                   if row.get('workflow_stage')==stage else [])
            process_conflict=bool(
                row.get('_review_process_conflict') or len(all_process_ids)>1)
            warning=(
                f"{row.get('target_item_name') or values.get('material_code') or '该物料'} "
                "候选同时引用多个流程，无法确定字段归属，已取消默认。"
                if process_conflict else '')
            if warning and warning not in process_conflict_warnings:
                process_conflict_warnings.append(warning)
            for process_id in process_ids:
                aggregate_key=(process_id,material_key)
                snapshot_row=aggregated_rows.setdefault(aggregate_key,{
                    'row_id':digest(POLICY,'stage-row',stage,process_id,material_key),
                    'process_instance_id':process_id,'material_stable_key':material_key,
                    'item_name':row.get('target_item_name') or '',
                    'material_code':values.get('material_code') or '',
                    'product_name':values.get('product_name') or '',
                    'spec_model':values.get('spec_model') or '',
                    'process_instance_ids':all_process_ids,'process_conflict':process_conflict,
                    'source_row_ids':[],'field_candidates':{},'evidence_chain':[],
                })
                snapshot_row['process_conflict']=bool(
                    snapshot_row['process_conflict'] or process_conflict)
                snapshot_row['process_instance_ids']=sorted(set(
                    snapshot_row['process_instance_ids']+all_process_ids))
                source_row_id=str(row.get('row_id') or '')
                if source_row_id and source_row_id not in snapshot_row['source_row_ids']:
                    snapshot_row['source_row_ids'].append(source_row_id)
                for candidate in row_candidates:
                    candidate_ids=snapshot_row['field_candidates'].setdefault(candidate['fieldname'],[])
                    if candidate['candidate_id'] not in candidate_ids:
                        candidate_ids.append(candidate['candidate_id'])
                    for evidence in candidate.get('evidence_chain') or []:
                        if evidence not in snapshot_row['evidence_chain']:
                            snapshot_row['evidence_chain'].append(deepcopy(evidence))
                process=process_map.setdefault(process_id,{
                    'process_instance_id':process_id,'label':process_id,'approval_no':'',
                    'source_ids':[],'evidence':[],'row_ids':[],'status':'UNAVAILABLE',
                    'has_conflicts':False,'warnings':[],
                })
                if warning:
                    process['has_conflicts']=True
                    if warning not in process['warnings']:
                        process['warnings'].append(warning)
        snapshot_rows=[]
        for aggregate_key,snapshot_row in sorted(aggregated_rows.items()):
            snapshot_row['source_row_ids'].sort()
            snapshot_row['field_candidates']={
                fieldname:sorted(candidate_ids)
                for fieldname,candidate_ids in sorted(snapshot_row['field_candidates'].items())
            }
            snapshot_row['evidence_chain'].sort(key=lambda evidence:(
                evidence.get('occurred_at') or '',evidence.get('evidence_id') or '',
            ))
            snapshot_rows.append(snapshot_row)
            process_id=aggregate_key[0]
            process=process_map.setdefault(process_id,{
                'process_instance_id':process_id,'label':process_id,'approval_no':'',
                'source_ids':[],'evidence':[],'row_ids':[],'status':'UNAVAILABLE',
                'has_conflicts':False,'warnings':[],
            })
            if snapshot_row['row_id'] not in process['row_ids']:
                process['row_ids'].append(snapshot_row['row_id'])
        candidate_source_ids={
            str(evidence.get('evidence_id') or '')
            for row in stage_rows
            for candidate in candidates_by_row.get(str(row.get('row_id') or ''),[])
            for evidence in candidate.get('evidence_chain') or []
        }
        unreadable=[source for source in stage_sources
                    if _source_status(source) in UNREADABLE_SOURCE_STATUSES]
        readable=[source for source in stage_sources
                  if (_source_status(source) in READABLE_SOURCE_STATUSES
                      or str(source.get('source_id') or '') in candidate_source_ids)]
        warnings=list(process_conflict_warnings)
        for source in stage_sources:
            status=_source_status(source)
            error=str(source.get('error') or source.get('analysis_reason') or '').strip()
            if status in UNREADABLE_SOURCE_STATUSES or (status=='PARTIAL' and error):
                label=str(source.get('source_label') or source.get('file_name') or source.get('source_id') or '资料')
                warnings.append(f"{label}：{error or '未能读取，已跳过。'}")
        stage_evidence=[_evidence_record(source) for source in stage_sources]
        status=_availability_status(stage_evidence,has_rows=bool(snapshot_rows))
        for process in process_map.values():
            process['source_ids'].sort()
            process['evidence'].sort(key=lambda evidence:(
                evidence['occurred_at'],evidence['evidence_id'],
            ))
            process['row_ids'].sort()
            process['warnings'].sort()
            process['status']=_availability_status(
                process['evidence'],has_rows=bool(process['row_ids']))
        by_kind=Counter(str(source.get('evidence_kind') or 'other') for source in stage_sources)
        fallback_reason=(
            '部分资料不可读，已跳过并继续使用本阶段可用候选。'
            if status=='PARTIAL' else
            '本阶段未找到有效资料，默认值将从下一优先级阶段补充。'
            if status=='UNAVAILABLE' and stage_rank < STAGE_SPECS[-1][1] else
            '本阶段未找到有效资料。'
            if status=='UNAVAILABLE' else ''
        )
        snapshots.append({
            'stage_snapshot_id':_stage_snapshot_id(stage),
            'stage':stage,'stage_rank':stage_rank,'rank':stage_rank,
            'stage_label':stage_label,'status':status,
            'processes':sorted(process_map.values(),key=lambda process:process['process_instance_id']),
            'rows':snapshot_rows,
            'evidence_summary':{
                'total':len(stage_sources),'readable':len(readable),'unreadable':len(unreadable),
                'candidate_count':sum(len(candidates_by_row.get(str(row.get('row_id') or ''),[])) for row in stage_rows),
                'by_kind':dict(sorted(by_kind.items())),
            },
            'fallback_reason':fallback_reason,'warnings':warnings,
        })
    return snapshots


def _fee_stage_snapshots(fees, sources):
    """Return fixed, safe fee summaries for payment and logistics stages."""

    from .source_priority_service import rank_material_packing_sources

    ordered = rank_material_packing_sources(sources or [])
    snapshots = []
    for stage, stage_rank, stage_label in FEE_STAGE_SPECS:
        stage_sources = [source for source in ordered if source.get('workflow_stage') == stage]
        stage_fees = [fee for fee in fees if fee.get('workflow_stage') == stage]
        process_map = {}
        for source in stage_sources:
            process_id = _process_instance_id(source)
            if not process_id:
                continue
            process = process_map.setdefault(process_id, {
                'process_instance_id': process_id,
                'label': str(source.get('approval_title') or source.get('process_title')
                             or source.get('process_name') or source.get('source_label')
                             or source.get('file_name') or process_id),
                'approval_no': str(source.get('approval_no') or ''),
                'source_ids': [], 'evidence': [], 'fee_ids': [],
                'status': 'UNAVAILABLE', 'has_conflicts': False, 'warnings': [],
            })
            source_id = str(source.get('source_id') or '')
            if source_id and source_id not in process['source_ids']:
                process['source_ids'].append(source_id)
            evidence = _evidence_record(source)
            if evidence not in process['evidence']:
                process['evidence'].append(evidence)

        fee_summaries = []
        for fee in sorted(stage_fees, key=lambda row: str(row.get('proposal_id') or '')):
            payload = fee.get('payload') or {}
            process_ids = sorted({
                str(ref.get('process_instance_id') or '')
                for ref in fee.get('source_refs') or []
                if isinstance(ref, dict)
                and ref.get('workflow_stage') == stage
                and str(ref.get('process_instance_id') or '')
            })
            process_conflict = bool(fee.get('source_stage_conflict') or len(process_ids) > 1)
            summary = {
                'proposal_id': str(fee.get('proposal_id') or ''),
                'process_instance_id': process_ids[0] if len(process_ids) == 1 else '',
                'process_instance_ids': process_ids,
                'process_conflict': process_conflict,
                'logical_fee_key': str(payload.get('logical_fee_key') or ''),
                'expense_category': str(payload.get('expense_category') or ''),
                'amount': payload.get('amount'),
                'currency': str(payload.get('currency') or ''),
                'amount_status': str(payload.get('amount_status') or ''),
                'selection_role': str(fee.get('selection_role') or 'ambiguous'),
                'parent_proposal_id': str(fee.get('parent_proposal_id') or ''),
                'can_apply': bool(fee.get('can_apply')),
                'default_selected': bool(fee.get('default_selected')),
                'conflict': bool(fee.get('conflict') or process_conflict),
                'confidence': float(fee.get('confidence') or 0),
                'resolution_reason': str(fee.get('resolution_reason') or ''),
                'blocked_reason': str(fee.get('blocked_reason') or ''),
            }
            fee_summaries.append(summary)
            for process_id in process_ids:
                process = process_map.setdefault(process_id, {
                    'process_instance_id': process_id, 'label': process_id,
                    'approval_no': '', 'source_ids': [], 'evidence': [],
                    'fee_ids': [], 'status': 'UNAVAILABLE',
                    'has_conflicts': False, 'warnings': [],
                })
                if summary['proposal_id'] not in process['fee_ids']:
                    process['fee_ids'].append(summary['proposal_id'])
                if process_conflict or fee.get('conflict'):
                    process['has_conflicts'] = True

        warnings = []
        unreadable = []
        readable = []
        fee_source_ids = {
            str(ref.get('source_id') or '')
            for fee in stage_fees
            for ref in fee.get('source_refs') or []
            if isinstance(ref, dict)
        }
        for source in stage_sources:
            status = _source_status(source)
            if status in UNREADABLE_SOURCE_STATUSES:
                unreadable.append(source)
            if (status in READABLE_SOURCE_STATUSES
                    or str(source.get('source_id') or '') in fee_source_ids):
                readable.append(source)
            error = str(source.get('error') or source.get('analysis_reason') or '').strip()
            if status in UNREADABLE_SOURCE_STATUSES or (status == 'PARTIAL' and error):
                label = str(source.get('source_label') or source.get('file_name')
                            or source.get('source_id') or '资料')
                warnings.append(f"{label}：{error or '未能读取，已跳过。'}")
        evidence = [_evidence_record(source) for source in stage_sources]
        status = _availability_status(evidence, has_rows=bool(fee_summaries))
        for process in process_map.values():
            process['source_ids'].sort()
            process['evidence'].sort(key=lambda row: (
                row.get('occurred_at') or '', row.get('evidence_id') or '',
            ))
            process['fee_ids'].sort()
            process['status'] = _availability_status(
                process['evidence'], has_rows=bool(process['fee_ids']))
        by_kind = Counter(str(source.get('evidence_kind') or 'other')
                          for source in stage_sources)
        fallback_reason = (
            '部分资料不可读，已跳过并继续使用本阶段可用候选。'
            if status == 'PARTIAL' else
            '本阶段未找到有效费用资料，默认值将从下一优先级阶段补充。'
            if status == 'UNAVAILABLE' and stage_rank < FEE_STAGE_SPECS[-1][1] else
            '本阶段未找到有效费用资料。'
            if status == 'UNAVAILABLE' else ''
        )
        snapshots.append({
            'stage_snapshot_id': digest(POLICY, 'fee-stage-snapshot', stage),
            'stage': stage, 'stage_rank': stage_rank, 'rank': stage_rank,
            'stage_label': stage_label, 'status': status,
            'processes': sorted(process_map.values(),
                                key=lambda row: row['process_instance_id']),
            'fees': fee_summaries,
            'evidence_summary': {
                'total': len(stage_sources), 'readable': len(readable),
                'unreadable': len(unreadable), 'candidate_count': len(fee_summaries),
                'by_kind': dict(sorted(by_kind.items())),
            },
            'fallback_reason': fallback_reason, 'warnings': warnings,
        })
    return snapshots


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
    stage_snapshots=_stage_snapshots(rows,field_candidates,sources)
    fee_rows=[p for p in material_ai_fee_policy.decorate(proposals,fees,context) if p.get('proposal_type')=='fee_update']
    fee_stage_snapshots=_fee_stage_snapshots(fee_rows,sources or [])
    return {'policy':POLICY,'rows':rows,'fees':fee_rows,'source_groups':source_groups,
            'field_candidates':field_candidates,'stage_snapshots':stage_snapshots,
            'fee_stage_snapshots':fee_stage_snapshots,
            'fingerprint':digest(POLICY,run_id,rows,fee_rows,source_groups,field_candidates,
                                 stage_snapshots,fee_stage_snapshots)}


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
