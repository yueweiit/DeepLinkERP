"""Native procurement integration contracts on task-5 synthetic QA, rollback by default."""
import json
import uuid

import frappe
from frappe.utils import add_days, nowdate
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt, make_purchase_invoice
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice as receipt_invoice
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

from deeplinkerp_branding.services import purchase_payment_service as payments
from deeplinkerp_branding.services import purchase_order_progress as progress

COMPANY = 'QA Second Company'
BUYER = 'qa5-buyer@example.invalid'
FINANCE = 'qa5-finance@example.invalid'


def guard():
    if frappe.local.site != 'po-grid-qa.localhost' or frappe.conf.db_name != 'qa_procurement_5':
        raise RuntimeError('Dedicated synthetic procurement QA only')
    frappe.set_user('Administrator')
    frappe.flags.in_test = True
    frappe.flags.mute_emails = True


def fixture():
    items=[]
    for index, letter in enumerate('ABC'):
        code='QA5-MAT-'+letter
        if not frappe.db.exists('Item', code):
            item=frappe.copy_doc(frappe.get_doc('Item','QA-PO-ITEM'))
            item.item_code=code; item.item_name='QA5 Material '+letter; item.insert()
        items.append(dict(item_code=code, qty=4 if index==0 else 3, rate=1000, schedule_date=add_days(nowdate(),1)))
    po=frappe.get_doc(dict(doctype='Purchase Order',company=COMPANY,supplier='QA Test Supplier',currency='CNY',schedule_date=add_days(nowdate(),1),items=items)).insert()
    po.submit()
    advance=get_payment_entry('Purchase Order',po.name,bank_account='Cash - QAB',bank_amount=1000)
    advance.paid_amount=advance.received_amount=1000; advance.references[0].allocated_amount=1000
    advance.insert();advance.submit()
    pr=make_purchase_receipt(po.name);pr.items=[pr.items[0]];pr.insert();pr.submit()
    pi=receipt_invoice(pr.name);pi.allocate_advances_automatically=1;pi.set_advances();pi.insert();pi.submit()
    assert sum(row.allocated_amount for row in pi.advances)==1000
    entry=payments.create_payment_draft(source_doctype='Purchase Receipt',source_name=pr.name,purchase_invoice=pi.name,amount_to_pay=2000,bank_account='Cash - QAB',request_id=str(uuid.uuid4()))
    pe=frappe.get_doc('Payment Entry',entry['name']);pe.submit()
    for email, roles in ((BUYER,['Purchase User','Purchase Manager']), (FINANCE,['Purchase User','Accounts User','Accounts Manager'])):
        if not frappe.db.exists('User',email):
            user=frappe.get_doc(dict(doctype='User',email=email,first_name='QA5 Buyer' if email==BUYER else 'QA5 Finance',send_welcome_email=0,roles=[dict(role=role) for role in roles]));user.insert()
            from frappe.utils.password import update_password
            update_password(email,'SyntheticUser5!')
            frappe.get_doc(dict(doctype='User Permission',user=email,allow='Company',for_value=COMPANY,apply_to_all_doctypes=1)).insert()
    return po,pr,pi,pe


def execute():
    guard()
    types=['Purchase Order','Purchase Receipt','Purchase Invoice','Payment Entry','GL Entry','Payment Ledger Entry','User','User Permission']
    before={dt:frappe.db.count(dt) for dt in types};results=[]
    try:
        po,pr,pi,pe=fixture()
        row=progress.get_order_progress([po.name],include_items=True)[po.name]
        assert (row['grand_total'],row['settled'],row['order_unpaid'],row['received_percent'])==(10000,3000,7000,40),row
        assert len(row['items'])==3 and row['items'][0]['received_qty']==4
        results.append('1000 reconciled advance + 2000 direct PI payment counted once; PO 3000 paid / 7000 unpaid / 40% received')
        frappe.set_user(BUYER)
        buyer=progress.get_order_progress([po.name],include_items=True)[po.name]
        assert buyer==row
        assert not any(word in json.dumps(buyer) for word in (pi.name,pe.name,'Cash - QAB','bank_account','account_currency'))
        for dt in ('Purchase Invoice','Payment Entry'):
            for action in ('create','write','submit','cancel','delete'):
                assert not frappe.has_permission(dt,action), (dt,action)
        # Exercise native RPC mutation paths, not just role flags or hidden buttons.
        from frappe.client import save, cancel
        for document in (pi, pe):
            for operation in (lambda: save(document.as_json()),
                              lambda: cancel(document.doctype, document.name)):
                try: operation()
                except frappe.PermissionError: pass
                else: raise AssertionError('Buyer native mutation API accepted')
        results.append('pure procurement user sees fixed PO summary without financial identifiers; native PI/PE mutation permissions all denied')
        for function in (lambda:payments.get_purchase_payables(),lambda:payments.create_payment_draft(source_doctype='Purchase Receipt',source_name=pr.name,purchase_invoice=pi.name,amount_to_pay=1,bank_account='Cash - QAB',request_id=str(uuid.uuid4()))):
            try:function()
            except frappe.PermissionError:pass
            else:raise AssertionError('Buyer financial API accepted')
        results.append('financial payables API and direct payment-create API reject procurement user')
        other=frappe.get_all('Purchase Order',filters={'company':['!=',COMPANY]},pluck='name',limit=1)
        if other:
            try:progress.get_order_progress(other)
            except frappe.PermissionError:pass
            else:raise AssertionError('Cross-company summary leaked')
            results.append('source/company permissions reject another company PO before private accounting reads')
        frappe.set_user(FINANCE)
        assert frappe.has_permission('Payment Entry','create') and frappe.has_permission('Purchase Invoice','write')
        scope=payments.get_purchase_payables(search=pi.name)
        assert scope['total_count']==1 and scope['rows'][0]['outstanding']==1000
        results.append('mixed procurement + finance roles retain normal finance capability and exact native PI balance')
        frappe.set_user('Administrator');frappe.db.savepoint('mixed')
        mixed=make_purchase_invoice(po.name);mixed.items=[mixed.items[0]];mixed.items[0].qty=1
        mixed.append('items',dict(item_code='QA-PO-ITEM',qty=1,rate=100))
        mixed.insert();mixed.submit()
        scope=payments.get_purchase_payables(search=mixed.name)
        assert scope['total_count']==1 and scope['rows'][0]['shared'] and scope['rows'][0]['grand_total']==mixed.grand_total
        assert progress.get_order_progress([po.name])[po.name]['settled'] is None
        results.append('mixed procurement + operating PI listed once with whole-invoice total; no invented PO allocation')
        frappe.db.rollback(save_point='mixed')
        frappe.db.savepoint('orphan');frappe.db.delete('Purchase Invoice',{'name':pi.name})
        assert progress.get_order_progress([po.name])[po.name]['settled'] is None
        frappe.db.rollback(save_point='orphan')
        results.append('orphan PI links hide uncertain order settlement rather than claiming zero paid')
        print(json.dumps(dict(status='passed',tests=results),ensure_ascii=False))
    finally:
        frappe.set_user('Administrator');frappe.db.rollback()
        after={dt:frappe.db.count(dt) for dt in types}
        assert before==after,(before,after)
        print(json.dumps(dict(rollback_counts_unchanged=True,counts=after)))


def seed_ui():
    guard();po,pr,pi,pe=fixture();frappe.db.commit()
    print(json.dumps(dict(purchase_order=po.name,purchase_receipt=pr.name,purchase_invoice=pi.name,payment_entry=pe.name,buyer=BUYER,finance=FINANCE)))
