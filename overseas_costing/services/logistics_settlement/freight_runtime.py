"""Local RPC projections and background integration for shipment freight."""
from . import freight_adoption as adoption, freight_matching as matching, freight_packing as packing
from .model import digest,dumps
from .application import row_meta
from .ai_matching import save


def candidate_view(store,candidate):
    from .runtime import source_summary
    source=store.get('source',candidate['expense_id'])
    lines=[]
    for lid in candidate['line_ids']:
        line=store.get('freight_line',lid)
        if not line:continue
        occupied=store.find('freight_claim',charge_key=line['charge_key'])
        lines.append({**line,'available':source['approved'] and not source['invalid'] and not line.get('ambiguous') and line['scope']=='freight'
            and not any(c['logistics_id']!=candidate['logistics_id'] for c in occupied),
            'adopted':any(c['logistics_id']==candidate['logistics_id'] and c['line_id']==lid for c in occupied)})
    return {**candidate,'expense':source_summary(source),'lines':lines,
            'packing_available':any(l.get('cargo_text') for l in lines) or bool(source.get('goods')) or any(d.get('tables') for d in source.get('documents') or [])}


def batch_status(store,ledger,batch_name,version_name=None):
    from .runtime import source_summary
    from overseas_costing.services.effective_logistics_source import resolve_source_context
    batch=ledger.get('batch',batch_name) or {};vname=version_name or batch.get('current_version')
    version=ledger.get('version',vname) or {}
    if version.get('batch')!=batch_name:raise ValueError('版本不属于当前批次')
    historical=vname!=batch.get('current_version')
    maps=store.find('batch_map',batch=batch_name)
    base={'ok':True,'freight_mode':True,'mapped':bool(maps),'historical':historical,'viewed_version':vname,'binding':None,'candidates':[],
          'matching':{'status':'not_started'},'sync':store.get('state','sync') or {},'health':store.get('state','health') or {}}
    if not maps:return base
    logistics=store.get('source',maps[0]['source_id'])
    base.update(logistics=source_summary(logistics),matching=matching.status(store,logistics['id']) if not historical else {'status':'historical'},
        candidates=[candidate_view(store,c) for c in matching.candidates(store,logistics['id']) if c['status']!='rejected'] if not historical else [],
        freight=adoption.context(store,ledger,batch_name,vname),source_context=resolve_source_context(batch_name,vname,store=store,ledger=ledger))
    ctx=base['source_context'];review=store.get('packing_review',base['freight'].get('packing_review_id') or '')
    base['packing']={'status':'adopted' if review else 'unverified','message':'已独立采用装箱变更；原始资料保留在操作记录' if review else '装箱沿用当前资料；尚未确认是否有变更',
        'review_id':(review or {}).get('id'),'source_context':ctx.get('packing') or ctx}
    base['packing_checks']=[{**{k:i.get(k) for k in ('name','material_code','product_name','quantity','unit','gross_weight_kg','volume_m3')},'revision':packing.item_fingerprint([i])} for i in ledger.rows('item',batch=batch_name,version=vname) if row_meta(i).get('settlement_packing_review')]
    base['blocking_reasons']=adoption.blockers(store,ledger,batch_name,vname)
    if review and not ctx.get('available'):base['blocking_reasons'].append('已采用装箱来源更新或失效，请重新核对')
    base['audit']=store.find('audit',binding_id=batch_name,limit=50)
    legacy=store.find('binding',logistics_id=logistics['id'])
    if legacy and not row_meta(version).get('freight_settlement'):
        base['legacy_binding']={**legacy[0],'expense':source_summary(store.get('source',legacy[0]['expense_id']))}
        base['message']='已有整单关联保留历史，请按本票费用明细核对后迁移；旧金额不会自动扩大到其他票。'
    return base


def manual_candidate(store,ledger,batch_name,expense_id,reason):
    maps=store.find('batch_map',batch=batch_name)
    if not maps:raise ValueError('请先开始本票匹配')
    logistics=store.get('source',maps[0]['source_id']);expense=store.get('source',expense_id)
    if not expense or expense['corp']!=logistics['corp'] or expense['invalid'] or expense['kind']!='expense':raise ValueError('来源企业、类型或状态不符')
    from .freight_lines import matching_lines
    lines=matching.current_lines(store,expense);own=matching_lines(logistics,lines)
    # Manual relation still cannot expose an explicitly different shipment as an adoptable line.
    own += [r for r in lines if not r.get('waybill') and not r.get('approval_no')]
    return candidate_view(store,matching.save_candidate(store,logistics,expense,own,'manual',reason))


def resume(store,ledger):
    # Durable per-request outcomes; no repeated source reads or automatic candidate confirmation.
    for record in store.find('state'):
        if record.get('status')!='queued' or record.get('kind') not in ('freight_apply','packing_apply','freight_refresh'):continue
        try:
            if record['kind']=='freight_refresh':
                result=adoption.source_updated(store,ledger,record['source_id'])
            else:
                call=adoption.confirm if record['kind']=='freight_apply' else packing.confirm
                result=call(store,ledger,**record['request'])
            if result['status']=='queued':continue
            record.update(status='completed',result=result);save(store,record)
        except Exception as exc:
            record.update(status='failed',error=str(exc)[:500]);save(store,record)


def history_status(store,job_id=None):
    from .runtime import source_summary
    job=store.get('job',job_id or (store.get('state','latest_job') or {}).get('job_id',''))
    logistics=[s for s in store.find('source',kind='logistics') if not s['invalid']]
    rows=[];counts={'pending':0,'conflict':0,'confirmed':0,'rejected':0,'unmatched':0}
    matched=set();adopted=set()
    for source in logistics:
        cs=matching.candidates(store,source['id']);active=[c for c in cs if c['status']!='rejected']
        for c in cs:counts[c['status']]+=1
        if active:matched.add(source['id'])
        if store.find('freight_claim',logistics_id=source['id']):adopted.add(source['id'])
        if active:
            mapping=store.find('batch_map',source_id=source['id'])
            rows.append({'logistics':source_summary(source),'batch':mapping[0]['batch'] if len(mapping)==1 else None,
                         'candidate_count':len(active),'status':'conflict' if any(c['status']=='conflict' for c in active) else 'pending'})
    counts.update(confirmed=len(adopted),unmatched=len(logistics)-len(matched))
    coverage=[]
    groups={}
    for source in store.find('source',kind='expense'):
        key=(source['corp'],source['process_code'])
        group=groups.setdefault(key,{'template_name':source.get('title') or source['process_code'],'local_sources':0,'qualified':0,'matched_shipments':set(),'missing_attachments':0})
        group['local_sources']+=1
        if source['invalid']:continue
        group['qualified']+=1
        group['matched_shipments'].update(c['logistics_id'] for c in store.find('freight_candidate',expense_id=source['id']) if c['logistics_id'] in matched and c['status']!='rejected')
        group['missing_attachments']+=sum(1 for a in source.get('attachments') or [] if a.get('archive_status')!='archived' and not a.get('retired_at'))
    for group in groups.values():coverage.append({**group,'matched_shipments':len(group['matched_shipments'])})
    return {'ok':True,'freight_mode':True,'job':job,'counts':counts,'shipments':rows,'coverage':coverage,
            'sync':store.get('state','sync') or {},'health':store.get('state','health') or {},
            'failures':store.find('job_item',job_id=job['id'],status='failed',limit=50) if job else [],
            'pending_failure_count':store.count('job_item',status='failed')}


def line_evidence(store,ledger,batch_name,version_name,line_id):
    """Only a shipment-owned archived row; no upstream or full-statement disclosure."""
    batch=ledger.get('batch',batch_name) or {};version=ledger.get('version',version_name) or {}
    if version.get('batch')!=batch_name:raise ValueError('版本不属于本票')
    claims=(row_meta(version).get('freight_settlement') or {}).get('claims') or []
    allowed={c['line_id'] for c in claims}
    mappings=store.find('batch_map',batch=batch_name)
    if version_name==batch.get('current_version') and mappings:
        for candidate in matching.candidates(store,mappings[0]['source_id']):
            if candidate['status']!='rejected':allowed.update(candidate['line_ids'])
    if line_id not in allowed:raise ValueError('此账单行不属于本票可查看的证据')
    line=store.get('freight_line',line_id)
    if not line:raise ValueError('本地证据行不存在，请核对归档状态')
    from .runtime import source_summary
    source=store.get('snapshot',line['snapshot']) or {}
    return {**{k:line.get(k) for k in ('amount','currency','waybill','approval_no','label','billing_weight','cargo_text','evidence')},
            'source':source_summary(source),'source_snapshot':line['snapshot']}
