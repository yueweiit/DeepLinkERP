"""Native File/payment contracts on task-5 synthetic QA only."""
import json
from io import BytesIO
from pathlib import Path
import uuid
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry

from deeplinkerp_branding.services import purchase_document_actions as actions
from deeplinkerp_branding.services import purchase_payment_attachments as files
from test_purchase_payment_completion_qa import seed

FINANCE='qa5-finance@example.invalid'
BUYER='qa5-buyer@example.invalid'
DRAFT='ACC-PAY-2026-00016'
TYPES=('Purchase Order','Purchase Receipt','Purchase Invoice','Payment Entry','GL Entry','Payment Ledger Entry','China Accounting Voucher','File','User','User Permission')


def counts():
    return {dt:frappe.db.count(dt) for dt in TYPES}


def content_of(doc):
    return Path(doc.get_full_path()).read_bytes()


def session(doctype,name):
    token=str(uuid.uuid4());files.begin_upload(doctype,name,token);return token


def upload(token,label='receipt'):
    from pypdf import PdfWriter
    buffer=BytesIO();writer=PdfWriter();writer.add_blank_page(width=180,height=100)
    writer.add_metadata({'/Title':'Synthetic QA '+str(uuid.uuid4())});writer.write(buffer);content=buffer.getvalue()
    name='SYNTHETIC-QA-'+label+'.pdf'
    frappe.local.form_dict=frappe._dict(fieldname=token)
    frappe.local.uploaded_file=content;frappe.local.uploaded_filename=name
    doc=files.upload_file()
    assert doc.owner==FINANCE and doc.is_private and not doc.attached_to_name
    assert content_of(doc)==content
    return doc,content


def direct():
    frappe.set_user('Administrator');_,pr,pi,args=seed();frappe.set_user(FINANCE)
    token=session('Purchase Receipt',pr.name);first,content=upload(token);second,_=upload(token,'voucher')
    # Exact upload retry returns the same native File, not another row or blob.
    frappe.local.uploaded_file=content;frappe.local.uploaded_filename='SYNTHETIC-QA-receipt.pdf'
    assert files.upload_file().name==first.name
    args.update(attachment_session=token,attachments=[first.name,second.name])
    result=actions.record_payment(**args)
    assert not result.get('failed'),result
    pe=result['document']['name'];assert result['document']['docstatus']==1
    attached=files.list_attachments(pe);assert len(attached)==2
    assert all(row.is_private for row in attached)
    assert content_of(frappe.get_doc('File',attached[0].name))==content
    assert frappe.db.count('GL Entry',{'voucher_type':'Payment Entry','voucher_no':pe})==2
    assert frappe.db.get_value('Purchase Invoice',pi.name,'outstanding_amount')==1000
    assert actions.record_payment(**args)['document']['name']==pe
    assert len(files.list_attachments(pe))==2
    assert files.discard(token,cancel=1)==[]
    assert content_of(first)==content
    return 'private multi-file upload + native direct posting + exact upload/payment retries + committed cancel protection'


def existing():
    frappe.set_user('Administrator');_,pr,_,args=seed()
    draft=actions.record_payment(**dict(args,confirm=0))['document'];frappe.set_user(FINANCE)
    token=session('Purchase Receipt',pr.name);doc,_=upload(token)
    review=actions.record_payment(**dict(args,request_id=str(uuid.uuid4()),attachment_session=token,attachments=[doc.name]))
    assert review['needs_review'] and review['document']['name']==draft['name']
    assert not files.list_attachments(draft['name']),'Never attach to a merely discovered draft'
    request=dict(name=draft['name'],changes={},expected_modified=draft['modified'],request_id=str(uuid.uuid4()),attachment_session=token,attachments=[doc.name])
    result=actions.complete_payment(**request);assert not result.get('failed'),result
    assert result['document']['docstatus']==1 and len(files.list_attachments(draft['name']))==1
    assert actions.complete_payment(**request)['document']['name']==draft['name']
    return 'discovered business draft remains untouched until explicit confirmation; same request resumes once'


def cleanup():
    frappe.set_user(FINANCE);token=session('Payment Entry',DRAFT);first,_=upload(token);second,_=upload(token,'second')
    assert files.discard(token,attachments=[first.name])==[first.name]
    assert not frappe.db.exists('File',first.name) and frappe.db.exists('File',second.name)
    assert files.discard(token,cancel=1)==[second.name]
    assert not frappe.db.exists('File',second.name)
    assert frappe.db.get_value('Payment Entry',DRAFT,'docstatus')==0
    return 'explicit single-file removal and session cancellation delete only owned temporary Files; original PE retained'


def rejection(kind):
    frappe.set_user(FINANCE);token=session('Payment Entry',DRAFT);intent=files._intent(token)
    if kind=='another-session':
        other=session('Payment Entry',DRAFT);doc,_=upload(other)
    else:
        frappe.set_user('Administrator')
        doc=frappe.get_doc(dict(doctype='File',file_name='SYNTHETIC-'+str(uuid.uuid4())+'.txt',content=b'Synthetic attachment scope '+str(uuid.uuid4()).encode(),is_private=0 if kind=='public' else 1,owner='Administrator' if kind=='other-owner' else FINANCE,
                              **({'attached_to_doctype':'Payment Entry','attached_to_name':DRAFT} if kind=='already-attached' else {}))).save()
        frappe.set_user(FINANCE);intent['files'].append(doc.name);files._put(token,intent)
    if kind=='other-company':
        other=frappe.get_all('Purchase Order',filters={'company':['!=','QA Second Company']},pluck='name',limit=1)[0]
        intent['context']=['Purchase Order',other];files._put(token,intent)
    try:files.bind(frappe.get_doc('Payment Entry',DRAFT),token,[doc.name])
    except frappe.PermissionError:pass
    else:raise AssertionError(kind+' file accepted')
    return kind+' File/session rejected before native attachment write'


def buyer():
    frappe.set_user(BUYER)
    try:files.begin_upload('Payment Entry',DRAFT,str(uuid.uuid4()))
    except frappe.PermissionError:pass
    else:raise AssertionError('Buyer upload capability expanded')
    try:files.list_attachments(DRAFT)
    except frappe.PermissionError:pass
    else:raise AssertionError('Buyer attachment listing expanded')
    return 'procurement cannot begin financial uploads or read PE attachments'


def failure():
    # Commit only a synthetic private upload to model the separate upload request.
    frappe.set_user(FINANCE);token=session('Payment Entry',DRAFT);doc,content=upload(token);frappe.db.commit()
    before=counts();entry=frappe.get_doc('Payment Entry',DRAFT);modified=str(entry.modified)
    request=dict(name=DRAFT,changes={},expected_modified=modified,request_id=str(uuid.uuid4()),attachment_session=token,attachments=[doc.name])
    original=PaymentEntry.on_submit
    def fail(entry):
        original(entry)
        raise frappe.ValidationError('Synthetic failure after native ledger posting')
    try:
        with patch.object(PaymentEntry,'on_submit',fail):
            result=actions.complete_payment(**request)
        assert result['failed'],result
        assert counts()==before and frappe.db.get_value('Payment Entry',DRAFT,'docstatus')==0
        assert str(frappe.db.get_value('Payment Entry',DRAFT,'modified'))==modified
        assert content_of(frappe.get_doc('File',doc.name))==content
        assert not files._intent(token).get('bound') and not files.list_attachments(DRAFT)
        retry=actions.complete_payment(**request);assert retry['document']['docstatus']==1,retry
        assert len(files.list_attachments(DRAFT))==1
        assert actions.complete_payment(**request)['document']['name']==DRAFT
    finally:
        frappe.db.rollback();frappe.set_user(FINANCE)
        files.discard(token,cancel=1);frappe.db.commit()
    return 'post-ledger native failure rolls back PE/File links/ledger; committed private upload survives and original token retries once'


def execute():
    if frappe.local.site!='po-grid-qa.localhost' or frappe.conf.db_name!='qa_procurement_5':
        raise RuntimeError('Task-5 dedicated synthetic QA only')
    frappe.flags.in_test=True;frappe.flags.mute_emails=True
    frappe.set_user('Administrator');before=counts();results=[]
    cases=[direct,existing,cleanup,buyer]+[lambda kind=kind:rejection(kind) for kind in ('other-owner','public','already-attached','another-session','other-company')]
    try:
        for case in cases:
            try:results.append(case())
            finally:frappe.db.rollback();frappe.set_user('Administrator');frappe.clear_cache()
            assert counts()==before,counts()
        results.append(failure())
        assert counts()==before,counts()
        print(json.dumps({'status':'passed','scenarios':results,'restored_counts':before},ensure_ascii=False))
    finally:
        frappe.db.rollback();frappe.set_user('Administrator')
