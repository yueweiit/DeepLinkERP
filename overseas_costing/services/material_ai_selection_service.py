"""Prepare and confirm immutable, server-held AI row selections."""
from copy import deepcopy

from . import material_ai_row_selection as rows, material_ai_fee_policy as fees
from .logistics_settlement.model import digest


RECEIPT_POLICY = 'ai-field-preview-receipt-2'


def material_fingerprint(items,sources,context):
    """Fee-only amendments do not consume reusable material recognition results."""
    from . import material_ai_fill_service as ai
    from .effective_logistics_source import json_dict
    def packing(ctx):
        ctx=ctx or {};part=deepcopy(ctx.get('packing') or ctx)
        for key in ('fingerprint','freight','cost_version'):part.pop(key,None)
        return part
    clean_items=[]
    for item in items:
        row=ai._fingerprint_item(deepcopy(item));meta=json_dict(row.get('extra_json'))
        meta.pop('effective_logistics_source',None)
        if meta.get('settlement_physical'):meta['settlement_physical'].pop('source_context_fingerprint',None)
        row['extra_json']=meta;clean_items.append(row)
    clean_sources=[]
    for source in sources:
        if not bool(source.get('selected',True)):
            continue
        row=ai._fingerprint_source(source);row['source_context']=packing(row.get('source_context'));clean_sources.append(row)
    return digest('ai-material-input-1',clean_items,clean_sources,packing(context.get('effective_source')),
        context.get('fx_rates'),context.get('clarification_revision'))


def _inputs(repo, batch, run, *, locked=False):
    from . import material_ai_fill_service as ai
    ai._assert_run_batch(run,batch)
    draft=ai._load_json(ai._record_value(run,'draft_json'),{})
    if int(ai._record_value(run,'proposal_version',0) or 0) > 0 and draft.get('row_review_policy') != rows.POLICY:
        raise ValueError('AI 预览规则已升级，请重新分析资料。')
    context=ai._review_context(repo,batch,str(ai._record_value(run,'version')),
        original_sources=ai._run_uses_original_sources(run))
    ai.effective_source.require_readable(context.get('effective_source') or {})
    if ai._clarification_changed(repo,batch,run,locked=locked):raise ValueError('说明已变化，请按新说明重新分析。')
    items=repo.get_items(batch,context['version'])
    sources=ai._reload_review_manifest(repo,batch,context['version'],run)
    fingerprint=ai._source_review_fingerprint(batch,context['version'],items,sources,str(ai._record_value(run,'clarification_text') or ''),context=context)
    saved_material=draft.get('material_input_fingerprint')
    if fingerprint!=ai._record_value(run,'input_fingerprint') and (not saved_material or saved_material!=material_fingerprint(items,sources,context)):
        raise ValueError('来源、物料或版本已变化，请重新分析资料。')
    baseline=(draft.get('review_input') or {}).get('source_dependencies')
    if baseline is not None and callable(getattr(repo,'assert_row_dependencies',None)):
        repo.assert_row_dependencies(batch,baseline,lock=locked)
    current_fees=repo.get_fees(batch,context['version'])
    proposals=ai._load_json(ai._record_value(run,'candidates_json'),[])
    result=rows.catalog(items,proposals,current_fees,context.get('effective_source') or {},
                        run_id=ai._record_value(run,'name'),sources=sources)
    return context,items,sources,current_fees,result


def review_catalog(repo,batch,run):
    return public_catalog(_inputs(repo,batch,run)[-1])


def _source_ref_sheet(ref):
    return str(
        ref.get('sheet_name') or ref.get('sheet') or ref.get('worksheet') or ''
    ).strip().casefold()


def _merged_amount_group_matches_change(group, change):
    """Return whether an unverified amount control governs an adopted value."""
    if change.get('fieldname') != 'shipment_value_rmb':
        return False
    item_name = str(change.get('item_name') or '').strip()
    members = {
        str(value or '').strip()
        for value in group.get('member_item_names') or []
        if str(value or '').strip()
    }
    if members and item_name not in members:
        return False

    group_source = str(group.get('source_id') or '').strip()
    group_sheet = str(group.get('sheet_name') or group.get('sheet') or '').strip().casefold()
    refs = [ref for ref in change.get('source_refs') or [] if isinstance(ref, dict)]
    if group_source or group_sheet:
        for ref in refs:
            if group_source and str(ref.get('source_id') or '').strip() != group_source:
                continue
            if group_sheet and _source_ref_sheet(ref) != group_sheet:
                continue
            return True
        # Older proposals may lack source refs. Preserve the safety fence only
        # when the group can still be tied to the adopted material explicitly.
        return not refs and bool(members and item_name in members)
    return bool(members and item_name in members)


def _blocking_merged_amount_groups(groups, changes):
    return [
        deepcopy(group)
        for group in groups or []
        if group.get('status') != 'verified'
        and any(_merged_amount_group_matches_change(group, change) for change in changes or [])
    ]


def _attach_control_metadata(projection, merged_amount_groups, packing_group_candidates):
    merged_amount_groups=deepcopy(merged_amount_groups or [])
    packing_group_candidates=deepcopy(packing_group_candidates or [])
    blocking=_blocking_merged_amount_groups(
        merged_amount_groups,projection.get('changes') or [])
    projection['merged_amount_groups']=merged_amount_groups
    projection['blocking_merged_amount_groups']=blocking
    projection['packing_group_candidates']=packing_group_candidates
    projection['merged_amount_blocking']=bool(blocking)
    if blocking:
        projection['can_apply']=False
        projection.setdefault('unresolved',[]).append({
            'code':'MERGED_AMOUNT_ALLOCATION_REQUIRED',
            'message':'合并金额组缺少独立单价或合计不一致，请完成人工分摊后重新预览。',
        })
    if not blocking and any(candidate.get('default_selected') and candidate.get('can_apply')
                            for candidate in packing_group_candidates):
        projection['can_apply']=True
    return projection


def _preview_revision(context,items,sources,current_fees,catalog,selection,dependencies):
    return digest(
        rows.POLICY,context,items,sources,current_fees,catalog['fingerprint'],
        selection['selected_row_ids'],selection['selected_fee_ids'],selection.get('selected_field_choices'),selection['mode'],dependencies,
        selection.get('merged_amount_groups') or [],selection.get('selected_packing_group_ids') or [],
    )


def _preview_receipt(preview):
    """Persist only the inputs needed to authenticate and reconstruct a preview."""
    keys=(
        'id','revision','run_id','batch','version','mode','selected_row_ids','selected_fee_ids',
        'selected_field_choices',
        'dependencies','input_fingerprint','fee_fingerprint','catalog_fingerprint',
        'selected_packing_group_ids',
    )
    return {'receipt_policy':RECEIPT_POLICY,
            **{key:deepcopy(preview.get(key)) for key in keys}}


def _clean_preview_draft(draft):
    cleaned=dict(draft)
    cleaned.pop('row_previews',None)
    cleaned.pop('current_row_preview',None)
    return cleaned


def _selected_packing_groups(items, candidates, selected_ids):
    candidates=deepcopy(candidates or [])
    by_id={str(candidate.get('candidate_id') or ''):candidate for candidate in candidates}
    if any(not candidate_id for candidate_id in by_id) or len(by_id)!=len(candidates):
        raise ValueError('装箱组候选标识无效，请重新分析。')
    if selected_ids is None:
        selected_ids=[candidate_id for candidate_id,candidate in by_id.items() if (
            candidate.get('default_selected') and candidate.get('can_apply')
            or any(str(evidence.get('kind') or '') == 'xlsx_merge'
                   for evidence in candidate.get('evidence') or [])
        )]
    if (not isinstance(selected_ids,list) or any(not isinstance(value,str) for value in selected_ids)
            or len(selected_ids)!=len(set(selected_ids))):
        raise ValueError('装箱组选择格式不正确。')
    if set(selected_ids)-by_id.keys():
        raise ValueError('所选装箱组不属于当前草稿，请刷新预览。')
    ordered_items=sorted(
        [item for item in items or [] if not int(item.get('is_excluded') or 0)],
        key=lambda item:(int(item.get('row_no') or 0),str(item.get('name') or '')),
    )
    # Legacy material rows predate the persisted stable_line_key column.  The
    # rest of the material import/review pipeline exposes their immutable
    # document name as ``legacy:<name>``; use the same identity here so one
    # unrelated legacy row cannot invalidate an otherwise verified XLSX group.
    stable_keys=[str(item.get('stable_line_key') or (
        f"legacy:{item.get('name')}" if item.get('name') else '')) for item in ordered_items]
    if selected_ids and (any(not key for key in stable_keys) or len(stable_keys)!=len(set(stable_keys))):
        raise ValueError('装箱组物料身份不稳定，请刷新后重新分析。')
    occupied=set();selected=[]
    for candidate_id in selected_ids:
        candidate=by_id[candidate_id]
        xlsx_merge=any(str(evidence.get('kind') or '') == 'xlsx_merge'
                       for evidence in candidate.get('evidence') or [])
        if not xlsx_merge and not candidate.get('can_apply'):
            raise ValueError(candidate.get('resolution_reason') or '该装箱组成员尚未确认，不能采用。')
        members=[str(value or '') for value in candidate.get('member_keys') or []]
        if len(members)<2 or len(members)!=len(set(members)) or any(member not in stable_keys for member in members):
            raise ValueError('装箱组物料已变化，请刷新后重新选择。')
        positions=sorted(stable_keys.index(member) for member in members)
        if positions!=list(range(min(positions),max(positions)+1)) or occupied.intersection(members):
            raise ValueError('装箱组只能覆盖连续且互不重复的物料行。')
        occupied.update(members);selected.append(candidate)
    return selected,sorted(selected_ids)


def prepare(batch_name,run_id,row_ids,fee_ids,mode,expected_version,*,field_choices=None,
            packing_group_ids=None,repository=None):
    from . import material_ai_fill_service as ai
    if mode == 'replace_all':
        raise ValueError('整表替换仅能在独立的整源采纳流程中执行。')
    repo=repository or ai.FrappeMaterialAIFillRepository()
    initial=repo.get_run(run_id);ai._assert_run_batch(initial,batch_name)
    repo.lock_review_scope(batch_name)
    run=repo.lock_run(run_id)
    if ai._record_value(run,'status')!='READY':raise ValueError('此分析已经处理或过期，请重新读取草稿。')
    context,items,sources,current_fees,catalog=_inputs(repo,batch_name,run,locked=True)
    if expected_version!=context['version']:raise ValueError('当前成本版本已变化，请刷新。')
    draft=ai._load_json(ai._record_value(run,'draft_json'),{})
    saved_dependencies=(draft.get('review_input') or {}).get('source_dependencies')
    if saved_dependencies is not None:
        dependencies=deepcopy(saved_dependencies)
    else:
        dependencies=repo.capture_row_dependencies(sources,context) if callable(getattr(repo,'capture_row_dependencies',None)) else []
    # Re-read under the newly held evidence locks before saving any preview.
    if dependencies:
        context,items,sources,current_fees,catalog=_inputs(repo,batch_name,run,locked=True)
    selected_packing_groups,selected_packing_group_ids=_selected_packing_groups(
        items,draft.get('packing_group_candidates') or [],packing_group_ids)
    projection=_attach_control_metadata(
        rows.project(items,catalog,row_ids,fee_ids,mode,field_choices=field_choices),
        draft.get('merged_amount_groups') or [],selected_packing_groups)
    projection['selected_packing_group_ids']=selected_packing_group_ids
    revision=_preview_revision(context,items,sources,current_fees,catalog,projection,dependencies)
    preview={**projection,'id':digest(run_id,revision),'revision':revision,'run_id':run_id,'batch':batch_name,
             'version':context['version'],'source_context':context.get('effective_source') or {},
             'original_source_reanalysis':ai._run_uses_original_sources(run),
             'input_fingerprint':ai._record_value(run,'input_fingerprint'),
             'fee_fingerprint':digest(current_fees),'sources':deepcopy(sources),'dependencies':dependencies}
    # A receipt authenticates the selection while the material projection is
    # reconstructed under confirmation locks. Superseded previews are useless.
    draft['row_previews']={preview['id']:_preview_receipt(preview)}
    draft['current_row_preview']=preview['id']
    repo.save_row_review_draft(run,draft)
    return {'ok':True,'preview':public_preview(preview),'row_review':public_catalog(catalog)}


def public_catalog(catalog):
    from .material_ai_fill_service import _public_ai_payload
    return _public_ai_payload(catalog)


def public_preview(preview):
    from .material_ai_fill_service import _public_ai_payload
    return _public_ai_payload({k:v for k,v in preview.items()
                               if k not in ('sources','input_fingerprint','source_context','fee_fingerprint','dependencies')})


def confirm(batch_name,run_id,preview_id,preview_revision,edit_token,expected_modified,*,repository=None):
    from . import material_ai_fill_service as ai
    repo=repository or ai.FrappeMaterialAIFillRepository()
    initial=repo.get_run(run_id);ai._assert_run_batch(initial,batch_name)
    repo.lock_review_scope(batch_name)
    run=repo.lock_run(run_id)
    ai._assert_run_batch(run,batch_name)
    draft=ai._load_json(ai._record_value(run,'draft_json'),{})
    applied=draft.get('row_application') or {}
    if ai._record_value(run,'status')=='APPLIED':
        if applied.get('preview_id')!=preview_id:raise ValueError('此分析已按其他选择采用，不能重复确认。')
        return {**applied,'ok':True,'idempotent':True}
    receipt=(draft.get('row_previews') or {}).get(preview_id)
    if not receipt or receipt.get('revision')!=preview_revision:
        raise ValueError('所选预览已变化，请刷新预览并使用最新预览后确认。')
    if receipt.get('mode') == 'replace_all':
        raise ValueError('整表替换仅能在独立的整源采纳流程中执行。')
    if ai._record_value(run,'status')!='READY' or draft.get('current_row_preview')!=preview_id:
        raise ValueError('草稿或选择已变化，请使用最新预览。')
    if (receipt.get('id')!=preview_id or receipt.get('run_id')!=run_id
            or receipt.get('batch')!=batch_name):
        raise ValueError('所选预览与当前分析不一致，请刷新预览后确认。')
    repo.assert_write(batch_name,edit_token,expected_modified)
    repo.lock_review_inputs(batch_name,receipt['version'])
    dependencies=deepcopy(receipt.get('dependencies') or [])
    if callable(getattr(repo,'assert_row_dependencies',None)):
        repo.assert_row_dependencies(batch_name,dependencies,lock=True)
    context,items,sources,current_fees,catalog=_inputs(repo,batch_name,run,locked=True)
    selected_group_ids=set(receipt.get('selected_packing_group_ids') or [])
    if not selected_group_ids and receipt.get('packing_group_candidates'):
        selected_group_ids={str(candidate.get('candidate_id') or '') for candidate in receipt.get('packing_group_candidates') or []}
    selected_packing_groups,validated_group_ids=_selected_packing_groups(
        items,draft.get('packing_group_candidates') or [],sorted(selected_group_ids))
    current=_attach_control_metadata(
        rows.project(items,catalog,receipt['selected_row_ids'],receipt['selected_fee_ids'],receipt['mode'],
                     field_choices=receipt.get('selected_field_choices')),
        draft.get('merged_amount_groups') or receipt.get('merged_amount_groups') or [],selected_packing_groups)
    current['selected_packing_group_ids']=validated_group_ids
    revision=_preview_revision(context,items,sources,current_fees,catalog,current,dependencies)
    if revision!=preview_revision:
        raise ValueError('来源、费用或物料已变化，请刷新预览；本次未保存。')
    if current.get('merged_amount_blocking'):
        raise ValueError('合并金额组尚未完成人工分摊或合计校验，本次未保存。')
    selected_fee_ids=current.get('selected_fee_ids') or []
    selected_fees=current.get('fees') or []
    estimate_only=bool(selected_fee_ids) and len(selected_fees)==len(selected_fee_ids) and all(
        str((fee.get('payload') or {}).get('amount_status') or '').upper()=='ESTIMATED'
        for fee in selected_fees)
    if selected_fee_ids and not estimate_only and callable(getattr(repo,'assert_adoption_dependencies',None)):
        repo.assert_adoption_dependencies(batch_name,dependencies,lock=True)
    elif callable(getattr(repo,'assert_row_dependencies',None)):
        repo.assert_row_dependencies(batch_name,dependencies,lock=True,purpose='estimate')
    if not current['can_apply']:raise ValueError('请选择需要填充的物料或费用。')
    fees.assert_allowed(current['fees'],current_fees,context.get('effective_source') or {})
    verified={**current,'id':preview_id,'revision':revision,'run_id':run_id,'batch':batch_name,
              'version':context['version'],'source_context':context.get('effective_source') or {},
              'original_source_reanalysis':ai._run_uses_original_sources(run),
              'input_fingerprint':ai._record_value(run,'input_fingerprint'),
              'fee_fingerprint':digest(current_fees),'sources':deepcopy(sources),
              'dependencies':dependencies}
    cleaned_draft=_clean_preview_draft(draft)
    try:
        return repo.apply_row_selection(run,verified,cleaned_draft,context)
    except Exception:
        repo.rollback()
        raise
