"""Keep future analysis inside the explicitly adopted set of material rows."""
from copy import deepcopy
from .logistics_settlement.model import digest, dumps
from .material_ai_source_dependencies import capture_dependencies, dependency_issues


def apply_scope(bundle, adoption, *, historical=False, store=None, ledger=None, batch_name=''):
    before=adoption['source_context'];current=bundle['context']
    original=before.get('packing') or before
    now=current.get('packing') or current
    unchanged=all(original.get(k)==now.get(k) for k in ('root_source_id','source_snapshot','binding_id','binding_revision'))
    issues=[] if historical else dependency_issues(adoption,store=store,ledger=ledger,
        batch_name=batch_name or current.get('batch') or (bundle.get('batch') or {}).get('name',''))
    available=historical or bool(unchanged and not issues and now.get('available') and not now.get('invalid') and (now.get('root_kind')!='expense' or now.get('approved')))
    packing=deepcopy(original if historical else now)
    selected={'id':adoption['id'],'revision':adoption['revision'],'source_kind':'approval_form',
              'source_label':'已确认的所选物料行','approval_no':(bundle.get('source') or {}).get('approval_no',''),
              'row_ids':adoption['selected_row_ids'],'evidence':{'selection_id':adoption['id']}}
    packing.update(selected_source=selected,available=available,approved=available,completeness='unconfirmed',cost_version=current.get('cost_version'),dependency_issues=issues)
    packing['fingerprint']=digest(packing)
    goods=deepcopy(adoption['goods'])
    source={k:v for k,v in (bundle.get('source') or {}).items() if k in ('id','corp','instance','snapshot','status','approval_result','title','kind','approval_no')}
    source.update(goods=goods,goods_complete=False,selected_source=selected,scoped_text=dumps(goods),available=available,approved=available,
        documents=[],attachments=[],fields={'本次明确采用行':goods},raw={'formComponentValues':[],'comments':[]})
    result=deepcopy(current);result.update(packing);result['packing']=packing
    result['freight']=current.get('freight') or {};result['separate_adoption']=True;result['policy_version']='shipment-sources-3'
    result['fingerprint']=digest(result)
    return {**bundle,'context':result,'source':source}
