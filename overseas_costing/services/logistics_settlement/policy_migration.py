"""Bounded, local-only adoption upgrade. Never initialize history or push ERP."""
from .model import dumps, parse_source
from .jobs import utcnow
from .application import row_meta
from .writer import apply_binding
from .documents import with_cached_documents
from overseas_costing.services.effective_logistics_source import POLICY_VERSION

KEY = 'policy-upgrade:' + POLICY_VERSION


def register(store, ledger):
    existing = store.get('state',KEY)
    if existing:
        return existing
    ids, after = [], None
    while True:
        rows = store.find('binding',limit=200,after=after)
        for binding in rows:
            if binding.get('application_status') == 'rolled_back':
                continue
            mapping = store.find('batch_map',source_id=binding['logistics_id'],limit=1)
            batch = ledger.get('batch',mapping[0]['batch']) if mapping else None
            version = ledger.get('version',batch['current_version']) if batch else {}
            context = row_meta(version or {}).get('effective_logistics_source') or {}
            if context.get('policy_version') != POLICY_VERSION:
                ids.append(binding['id'])
        if len(rows)<200:
            break
        after = rows[-1]['id']
    state = {'id':KEY,'binding_ids':ids,'cursor':0,'failed':{},'status':'queued' if ids else 'completed'}
    save(store,state)
    return state


def save(store,state):
    store.put('state',{'id':KEY,'updated_at':utcnow(),'data':dumps(state)})


def run_step(store, ledger, *, limit=50):
    with store.atomic():
        state = store.get('state',KEY,lock=True)
        if not state or state.get('status') == 'completed':
            return state
        ids = state['binding_ids'][state['cursor']:state['cursor']+limit]
        for binding_id in ids:
            try:
                with store.atomic():
                    store.get('state','match_lock',lock=True)
                    binding = store.get('binding',binding_id,lock=True)
                    if binding and binding.get('application_status') != 'rolled_back':
                        source = store.get('source',binding['expense_id'],lock=True)
                        if source:
                            raw = {'corp_id':source['corp'],'process_instance_id':source['instance'],
                                   'process_code':source['process_code'],'business_id':source.get('approval_no'),
                                   'status':source['status'],'result':source.get('approval_result'),
                                   'deleted_at':source.get('deleted_at'),'updated_at':source['source_updated_at'],
                                   'raw_payload':source['raw'],'attachments':source.get('attachments') or []}
                            parsed = parse_source(with_cached_documents(raw,source.get('documents') or []),logistics_codes=set())
                            store.ingest(parsed)
                        apply_binding(store,ledger,binding_id,'source-policy-upgrade')
                state['failed'].pop(binding_id,None)
            except Exception as exc:
                state['failed'][binding_id] = str(exc)
            state['cursor'] += 1
            save(store,state)
        state['status'] = ('partial' if state['failed'] else 'completed') if state['cursor'] == len(state['binding_ids']) else 'running'
        save(store,state)
        return state


def retry_failed(store):
    with store.atomic():
        state = store.get('state',KEY,lock=True)
        if state and state.get('failed'):
            state['binding_ids'] += sorted(state['failed'])
            state['failed'] = {}
            state['status'] = 'queued'
            save(store,state)
        return state


def register_after_migrate():
    import frappe
    from .store import Store
    from .ledger import FrappeLedger
    state = register(Store.frappe(),FrappeLedger())
    if state['status'] in {'queued','running'}:
        frappe.enqueue('overseas_costing.services.logistics_settlement.policy_migration.run',queue='long',
                       timeout=900,enqueue_after_commit=True)


def run():
    import frappe
    from .store import Store
    from .ledger import FrappeLedger
    store = Store.frappe()
    state = run_step(store,FrappeLedger())
    store.commit()
    if state and state['status'] in {'queued','running'}:
        frappe.enqueue('overseas_costing.services.logistics_settlement.policy_migration.run',queue='long',
                       timeout=900,enqueue_after_commit=True)
