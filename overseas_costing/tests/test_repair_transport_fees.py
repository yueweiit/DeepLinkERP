"""The production repair is preview-first, scoped, repeatable and atomic."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import gzip
from types import SimpleNamespace

import pytest


def service():
    return importlib.import_module('overseas_costing.scripts.repair_transport_fees')


def snapshot(mode='AIR'):
    return {
        'batch': dict(name='B', batch_no='B-NO', current_version='V', transport_mode=mode,
                      status='Calculated', confirm_status='Pending', is_locked=0,
                      modified='2026-09-08 12:00:00', source_approval_status='COMPLETED', extra_json='{}'),
        'version': dict(name='V', batch='B', status='Active', modified='2026-09-08 12:00:00'),
        'items': [dict(name='I', quantity=10, goods_value=100, raw_excel_json='original')],
        'rules': [dict(name='R', batch='B', version='V', rule_code='oa_logistics_freight',
                       logical_fee_key=None, expense_category='国际物流费用', amount='1416.565',
                       currency='RMB', amount_status='MISSING', allocation_basis='goods_value',
                       is_enabled=1, is_active=1, remark='OA source original', modified='M1')],
    }


@pytest.mark.parametrize('mode,key,label', [('AIR','international_air_freight','国际空运费'),
    ('SEA','international_sea_freight','国际海运费'), ('EXPRESS','international_express_fee','国际快递费')])
def test_plan_only_changes_legacy_identity_and_status(mode,key,label):
    data=snapshot(mode)
    before=deepcopy(data)
    plan=service().plan_batch_repair(data)
    assert plan['status']=='ready'
    assert plan['changes']==[{'rule_name':'R','kind':'normalize_oa_freight','values':{
        'logical_fee_key':key,'expense_category':label,'amount_status':'ESTIMATED'}}]
    assert data==before
    assert plan['snapshot_hash']==service().snapshot_hash(data)


@pytest.mark.parametrize('section,field,value,code', [
    ('batch','is_locked',1,'FROZEN'), ('batch','confirm_status','Confirmed','FROZEN'),
    ('batch','status','Written Back','FROZEN'), ('version','status','Archived','FROZEN'),
    ('version','status','Confirmed','FROZEN'), ('batch','current_version','OTHER','VERSION_CHANGED'),
    ('batch','transport_mode','UNKNOWN','UNKNOWN_TRANSPORT'),
    ('batch','source_approval_status','TERMINATED','INVALID_APPROVAL'),
    ('batch','edit_lock_expires_at',(datetime.now()+timedelta(hours=1)).isoformat(),'EDIT_IN_PROGRESS'),
])
def test_protected_batches_are_skipped(section,field,value,code):
    data=snapshot(); data[section][field]=value
    result=service().plan_batch_repair(data)
    assert result['status']=='skipped' and result['reason_code']==code
    assert not result['changes']


def test_duplicate_primary_skips_entire_batch():
    data=snapshot()
    data['rules'].append(dict(data['rules'][0],name='MANUAL',rule_code='international_air_freight',
        logical_fee_key='international_air_freight',amount_status='ACTUAL',amount=7000))
    result=service().plan_batch_repair(data)
    assert result['reason_code']=='PRIMARY_FREIGHT_CONFLICT'
    assert not result['changes']


def test_duplicate_is_detected_after_proposed_legacy_identity_normalization():
    data=snapshot()
    data['rules'][0]['expense_category']='国际海运费'
    data['rules'].append(dict(name='MANUAL',rule_code='international_air_freight',
        logical_fee_key='international_air_freight',amount_status='ACTUAL',amount=7000,is_enabled=1))
    result=service().plan_batch_repair(data)
    assert result['reason_code']=='PRIMARY_FREIGHT_CONFLICT' and not result['changes']


@pytest.mark.parametrize('rule_state',[{'is_enabled':0},{'amount_status':'ACTUAL'},
    {'amount_status':'NOT_INCURRED'},{'amount_status':'INCLUDED'}])
def test_protected_rule_status_is_never_promoted(rule_state):
    data=snapshot(); data['rules'][0].update(rule_state)
    for change in service().plan_batch_repair(data)['changes']:
        assert change['values'].get('amount_status') != 'ESTIMATED'
        assert 'is_enabled' not in change['values']


def retirement_snapshot(mode='AIR'):
    spec=service().RETIREMENTS['kr2rgs4kp1' if mode=='AIR' else 'urp34dkllu']
    data=snapshot(mode)
    data['batch'].update(name=spec['batch'],batch_no=spec['batch_no'],current_version=spec['version'])
    data['version'].update(name=spec['version'],batch=spec['batch'])
    data['rules']=[dict(name=spec['primary_rule'],batch=spec['batch'],version=spec['version'],
        logical_fee_key='international_air_freight' if mode=='AIR' else 'international_sea_freight',
        rule_code='manual',amount=spec['primary_amount'],currency='RMB',amount_status='ACTUAL',is_enabled=1),
        dict(name=spec['rule'],batch=spec['batch'],version=spec['version'],rule_code=spec['logical_fee_key'],
        logical_fee_key=spec['logical_fee_key'],amount=spec['amount'],currency='RMB',amount_status='ACTUAL',
        is_enabled=1,is_active=1,remark='preserve')]
    return data


@pytest.mark.parametrize('mode',['AIR','SEA'])
def test_only_authorized_surcharge_is_retired_and_repeat_is_noop(mode):
    data=retirement_snapshot(mode)
    result=service().plan_batch_repair(data)
    assert len(result['changes'])==1
    change=result['changes'][0]
    assert change['kind']=='retire_authorized_surcharge'
    assert change['values']['is_enabled']==0 and change['values']['is_active']==0
    assert 'amount' not in change['values'] and 'currency' not in change['values']
    data['rules'][1].update(change['values'])
    assert service().plan_batch_repair(data)['status']=='unchanged'


@pytest.mark.parametrize('index,field,value',[(1,'amount','5001'),(1,'currency','MXN'),
    (0,'amount','7001'),(1,'logical_fee_key','other')])
def test_retirement_requires_exact_authorized_money_and_identity(index,field,value):
    data=retirement_snapshot(); data['rules'][index][field]=value
    result=service().plan_batch_repair(data)
    assert result['reason_code']=='RETIREMENT_TARGET_CHANGED' and not result['changes']


class Repository:
    def __init__(self):
        self.data={'B':snapshot()}; self.original=deepcopy(self.data)
        self.saved=[]; self.commits=0; self.rollbacks=0; self.lock_count=0
        self.authorized=True; self.backup_valid=True; self.fail_save=False; self.drift=False
    def assert_operator(self):
        if not self.authorized: raise PermissionError('System Manager required')
    def candidates(self): return list(self.data)
    def load(self,batch,*,lock=False):
        self.lock_count+=int(lock)
        data=deepcopy(self.data[batch])
        if lock and self.drift: data['rules'][0]['amount']='2000'
        return data
    def validate_backup(self,path):
        if not self.backup_valid: raise ValueError('backup required')
        return {'path':path,'sha256':'backup-digest'}
    def save(self,before,plan):
        batch=before['batch']['name']; self.transaction=deepcopy(self.data[batch])
        for change in plan['changes']:
            next(r for r in self.data[batch]['rules'] if r['name']==change['rule_name']).update(change['values'])
        self.data[batch]['batch']['status']='Dirty'
        if self.fail_save: raise RuntimeError('audit failed')
        self.saved.append(deepcopy(plan))
        return 'AUDIT-1'
    def commit(self): self.commits+=1; self.transaction=None
    def rollback(self):
        self.rollbacks+=1
        if getattr(self,'transaction',None): self.data['B']=self.transaction; self.transaction=None


def test_run_default_preview_does_not_lock_or_write():
    repo=Repository(); result=service().run(repository=repo)
    assert result['ready_count']==1 and result['applied_count']==0
    assert result['manifest']['B']==service().snapshot_hash(repo.original['B'])
    assert not repo.saved and not repo.lock_count and not repo.commits
    assert repo.data==repo.original


def test_apply_requires_manifest_backup_and_operator():
    repo=Repository()
    with pytest.raises(ValueError): service().run(apply=True,repository=repo)
    manifest=service().run(repository=repo)['manifest']
    repo.backup_valid=False
    with pytest.raises(ValueError): service().run(apply=True,manifest=manifest,backup_path='backup',repository=repo)
    repo.authorized=False
    with pytest.raises(PermissionError): service().run(repository=repo)
    assert not repo.saved


def test_apply_is_idempotent_and_preserves_other_data():
    repo=Repository(); manifest=service().run(repository=repo)['manifest']
    result=service().run(apply=True,manifest=manifest,backup_path='backup',repository=repo)
    assert result['applied_count']==1 and repo.commits==1 and repo.lock_count==1
    assert repo.data['B']['items']==repo.original['B']['items']
    assert repo.data['B']['version']==repo.original['B']['version']
    assert repo.data['B']['rules'][0]['amount']=='1416.565'
    assert repo.data['B']['rules'][0]['remark']=='OA source original'
    assert repo.data['B']['batch']['status']=='Dirty'
    assert service().run(repository=repo)['ready_count']==0


@pytest.mark.parametrize('failure,reason',[('drift','SOURCE_CHANGED'),('fail_save','TRANSACTION_FAILED')])
def test_apply_detects_drift_and_rolls_back_partial_failure(failure,reason):
    repo=Repository(); manifest=service().run(repository=repo)['manifest']
    setattr(repo,failure,True)
    result=service().run(apply=True,manifest=manifest,backup_path='backup',repository=repo)
    assert result['applied_count']==0 and result['results'][0]['reason_code']==reason
    assert repo.data==repo.original and repo.commits==0


def test_database_backup_must_pass_full_gzip_integrity_check(tmp_path):
    directory=tmp_path / 'private' / 'backups'; directory.mkdir(parents=True)
    path=directory / '20260908-site-database.sql.gz'
    compressed=gzip.compress(b'-- SQL backup\n'+bytes(range(256))*200)
    path.write_bytes(compressed)
    repo=service().FrappeRepairRepository.__new__(service().FrappeRepairRepository)
    repo.frappe=SimpleNamespace(get_site_path=lambda *parts:str(tmp_path.joinpath(*parts)))
    assert repo.validate_backup(str(path))['sha256']
    path.write_bytes(compressed[:-8])
    with pytest.raises((ValueError,EOFError,gzip.BadGzipFile)):
        repo.validate_backup(str(path))


def test_authorized_retirements_are_reported_even_if_current_version_is_empty():
    repo=service().FrappeRepairRepository.__new__(service().FrappeRepairRepository)
    repo.frappe=SimpleNamespace(db=SimpleNamespace(sql=lambda *args,**kwargs:[]))
    assert set(repo.candidates())=={'sjgde0rgc3','vunn2lvq4k'}


def real_save_repository(data, *, pollution=None, audit_failure=False):
    """Exercise production save/invariant checks with only DB I/O replaced."""
    repo=service().FrappeRepairRepository.__new__(service().FrappeRepairRepository)
    state=deepcopy(data); audits=[]
    def set_value(doctype,name,values,*args,**kwargs):
        target=state['batch'] if doctype=='Overseas Cost Batch' else next(r for r in state['rules'] if r['name']==name)
        target.update(values if isinstance(values,dict) else {values:args[0]})
        target['modified']='AFTER'
        if doctype=='Overseas Cost Batch' and pollution:
            pollution(state)
    def get_doc(payload):
        def insert(**kwargs):
            if audit_failure: raise RuntimeError('audit unavailable')
            audits.append(payload)
            return SimpleNamespace(name='AUDIT-REAL-SAVE')
        return SimpleNamespace(insert=insert)
    repo.frappe=SimpleNamespace(db=SimpleNamespace(set_value=set_value),
        session=SimpleNamespace(user='Administrator'),get_doc=get_doc)
    repo.load=lambda *args,**kwargs:deepcopy(state)
    return repo,state,audits


def test_real_save_preserves_money_items_version_and_records_before_after_audit():
    data=snapshot(); repo,state,audits=real_save_repository(data)
    assert repo.save(data,service().plan_batch_repair(data))=='AUDIT-REAL-SAVE'
    assert state['items']==data['items'] and state['version']==data['version']
    assert state['rules'][0]['amount']=='1416.565' and state['rules'][0]['currency']=='RMB'
    assert state['rules'][0]['amount_revision'].startswith('oa:repair:')
    assert state['batch']['status']=='Dirty'
    assert len(audits)==1 and audits[0]['operator_name']=='Administrator'
    import json
    old=json.loads(audits[0]['old_value']); new=json.loads(audits[0]['new_value'])
    assert old['rules'][0]['amount_status']=='MISSING' and new['rules'][0]['amount_status']=='ESTIMATED'
    assert old['items_sha256']==new['items_sha256'] and old['version_sha256']==new['version_sha256']


@pytest.mark.parametrize('pollution',[
    lambda s:s['rules'][0].update(amount='9999'),
    lambda s:s['rules'][0].update(currency='USD'),
    lambda s:s['items'][0].update(quantity=999),
    lambda s:s['version'].update(status='Confirmed'),
    lambda s:s['rules'].append(dict(name='UNAPPROVED')),
    lambda s:s['rules'].clear(),
    lambda s:s['batch'].update(confirm_status='Confirmed'),
])
def test_real_save_rejects_any_unapproved_side_effect_before_audit(pollution):
    data=snapshot(); repo,state,audits=real_save_repository(data,pollution=pollution)
    with pytest.raises(RuntimeError): repo.save(data,service().plan_batch_repair(data))
    assert not audits


def test_real_save_does_not_swallow_audit_failure():
    data=snapshot(); repo,_,_=real_save_repository(data,audit_failure=True)
    with pytest.raises(RuntimeError,match='audit unavailable'):
        repo.save(data,service().plan_batch_repair(data))


@pytest.mark.parametrize('mode',['AIR','SEA'])
def test_real_retirement_save_preserves_primary_and_retired_money(mode):
    data=retirement_snapshot(mode); repo,state,audits=real_save_repository(data)
    repo.save(data,service().plan_batch_repair(data))
    assert state['rules'][0]==data['rules'][0]
    for field in ('amount','currency','amount_status'):
        assert state['rules'][1][field]==data['rules'][1][field]
    assert state['rules'][1]['is_enabled']==0 and state['rules'][1]['is_active']==0
    assert len(audits)==1


def test_locked_load_uses_current_reads_instead_of_repeatable_read_snapshot(monkeypatch):
    data=snapshot(); data['rules'][0]['amount']='LATEST-MANUAL-VALUE'
    queries=[]
    def forbidden(*args,**kwargs):
        raise AssertionError('ordinary reads can retain a pre-lock REPEATABLE-READ snapshot')
    def sql(query,parameters,**kwargs):
        queries.append(query)
        assert 'FOR UPDATE' in query.upper()
        for doctype,section in [('Overseas Cost Batch','batch'),('Overseas Cost Version','version'),
                                ('Overseas Cost Item','items'),('Overseas Cost Allocation Rule','rules')]:
            if f'`tab{doctype}`' in query:
                value=data[section]
                return deepcopy(value if isinstance(value,list) else [value])
        raise AssertionError(query)
    repo=service().FrappeRepairRepository.__new__(service().FrappeRepairRepository)
    repo.frappe=SimpleNamespace(db=SimpleNamespace(sql=sql,get_value=forbidden),get_all=forbidden)
    monkeypatch.setattr(service().edit_session_service,'_lock_row',lambda *args:None)
    assert repo.load('B',lock=True)==data
    assert len(queries)==4


def test_real_save_rechecks_invariants_with_current_reads():
    data=snapshot(); repo,state,_=real_save_repository(data)
    load_calls=[]
    def load(name,*,lock=False):
        load_calls.append(lock)
        return deepcopy(state)
    repo.load=load
    repo.save(data,service().plan_batch_repair(data))
    assert load_calls==[True]
