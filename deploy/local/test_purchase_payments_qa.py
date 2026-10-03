"""Real native procurement transactions on the allowlisted synthetic QA site; always rollback."""
import json
import uuid
import frappe
from frappe.utils import nowdate, add_days
from deeplinkerp_branding.services import purchase_payment_service as service
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice, make_purchase_return
from china_finance.services import voucher

SITE='po-grid-qa.localhost'
COMPANY='QA Second Company'
def execute():
 if frappe.local.site != SITE: raise RuntimeError('Synthetic QA site only')
 frappe.set_user('Administrator');frappe.flags.in_test=True;frappe.flags.mute_emails=True
 before={d:frappe.db.count(d) for d in ['Purchase Order','Purchase Receipt','Purchase Invoice','Payment Entry','GL Entry','China Accounting Voucher']}
 results=[]
 try:
  settings=frappe.db.get_value('China Finance Settings',{'company':COMPANY},'name')
  if settings: s=frappe.get_doc('China Finance Settings',settings)
  else:s=frappe.new_doc('China Finance Settings');s.company=COMPANY
  s.enabled=1;s.activation_date=nowdate();s.auto_submit_purchase_invoice=0;s.enforce_role_separation=0;s.save()
  frappe.clear_document_cache('China Finance Settings',s.name)
  supplier='QA Test Supplier';item='QA-PO-ITEM'
  po=frappe.get_doc({'doctype':'Purchase Order','company':COMPANY,'supplier':supplier,'currency':'CNY','schedule_date':add_days(nowdate(),1),'items':[{'item_code':item,'qty':10,'rate':1000,'schedule_date':add_days(nowdate(),1)}]}).insert();po.submit()
  pr=make_purchase_receipt(po.name);pr.items[0].qty=4;pr.insert();pr.submit()
  assert frappe.db.get_value('Purchase Order',po.name,'per_received')==40
  initial=service.get_purchase_chain('Purchase Receipt',pr.name)
  assert not initial['can_create'] and initial['can_create_invoice']
  pi=make_purchase_invoice(pr.name);pi.insert();assert '草稿' in service.get_purchase_chain('Purchase Receipt',pr.name)['reason'];pi.submit();assert pi.grand_total==4000
  chain=service.get_purchase_chain('Purchase Receipt',pr.name);assert chain['balances'][0]['outstanding']==4000;results.append('partial receipt 40%, payable 4000, no automatic duplicate invoice')
  args=dict(source_doctype='Purchase Receipt',source_name=pr.name,purchase_invoice=pi.name,amount_to_pay=3000,bank_account='Cash - QAB',request_id=str(uuid.uuid4()))
  for bad in [0,-1,4001]:
   try:service.create_payment_draft(**dict(args,amount_to_pay=bad,request_id=str(uuid.uuid4())))
   except (frappe.ValidationError,ValueError):pass
   else:raise AssertionError('invalid payment accepted')
  try:service.create_payment_draft(**dict(args,bank_account='100201 - 基本存款账户 - Y',request_id=str(uuid.uuid4())))
  except frappe.ValidationError:pass
  else:raise AssertionError('cross-company account accepted')
  bank=frappe.get_doc({'doctype':'Account','account_name':'QA Payment Bank','company':COMPANY,'account_type':'Bank','account_currency':'CNY','parent_account':frappe.db.get_value('Account',{'company':COMPANY,'is_group':1,'root_type':'Asset'},'name')}).insert()
  try:service.create_payment_draft(**dict(args,bank_account=bank.name,request_id=str(uuid.uuid4())))
  except frappe.ValidationError:pass
  else:raise AssertionError('native bank reference requirement bypassed')
  bank_draft=service.create_payment_draft(**dict(args,bank_account=bank.name,reference_no='QA-BANK-REFERENCE-ONLY',remarks='QA synthetic remark',request_id=str(uuid.uuid4())))
  bank_pe=frappe.get_doc('Payment Entry',bank_draft['name']);assert bank_pe.reference_no=='QA-BANK-REFERENCE-ONLY' and bank_pe.remarks=='QA synthetic remark' and bank_pe.docstatus==0
  results.append('bank draft requires real reference input and preserves reference date / remarks; no fake bank transaction')
  first=service.create_payment_draft(**args);retry=service.create_payment_draft(**args);assert first['name']==retry['name'] and retry['reused']
  try:service.create_payment_draft(**dict(args,amount_to_pay=2000))
  except frappe.ValidationError:pass
  else:raise AssertionError('changed idempotency payload accepted')
  assert frappe.db.get_value('Payment Entry',first['name'],'docstatus')==0
  assert frappe.db.get_value('Purchase Invoice',pi.name,'outstanding_amount')==4000
  assert not frappe.db.count('GL Entry',{'voucher_type':'Payment Entry','voucher_no':first['name']})
  results.append('duplicate click returns same draft; draft has no GL and no settlement')
  payment=frappe.get_doc('Payment Entry',first['name']);payment.submit()
  assert frappe.db.get_value('Purchase Invoice',pi.name,'outstanding_amount')==1000
  assert frappe.db.count('GL Entry',{'voucher_type':'Payment Entry','voucher_no':payment.name})==2
  records=service.get_payment_records(purchase_receipt=pr.name)['rows'];assert any(r['name']==payment.name for r in records)
  snapshots=frappe.get_all('China Accounting Voucher',filters={'source_doctype':'Payment Entry','source_name':payment.name,'source_event':'Posting'},pluck='name')
  assert len(snapshots)==1
  voucher.on_gl_source_submit(payment)
  assert frappe.db.count('China Accounting Voucher',{'source_doctype':'Payment Entry','source_name':payment.name,'source_event':'Posting'})==1
  assert frappe.db.count('GL Entry',{'voucher_type':'Payment Entry','voucher_no':payment.name})==2
  results.append('3000 submitted, outstanding 1000; one GL pair and one idempotent voucher snapshot')
  args.update(amount_to_pay=1000,request_id=str(uuid.uuid4()));second=service.create_payment_draft(**args);p2=frappe.get_doc('Payment Entry',second['name']);p2.submit()
  assert service.get_purchase_chain('Purchase Receipt',pr.name)['balances'][0]['outstanding']==0
  try:service.create_payment_draft(**dict(args,amount_to_pay=1,request_id=str(uuid.uuid4())))
  except frappe.ValidationError:pass
  else:raise AssertionError('overpayment accepted')
  results.append('second instalment 1000 settles exactly; stale/overpay request rejected')
  p2.cancel();assert frappe.db.get_value('Purchase Invoice',pi.name,'outstanding_amount')==1000
  payment.cancel();assert frappe.db.get_value('Purchase Invoice',pi.name,'outstanding_amount')==4000
  results.append('payment cancellation restores native invoice balance')
  frappe.set_user('qa-po-reader@example.invalid')
  try:service.get_purchase_chain('Purchase Receipt',pr.name)
  except frappe.PermissionError:pass
  else:raise AssertionError('cross-company receipt leaked')
  frappe.set_user('Administrator');results.append('company-restricted user cannot read other company receipt')
  # Create a normal purchase return after cancelling invoices; native links and negative amounts remain native.
  pi.reload();pi.cancel();ret=make_purchase_return(pr.name);ret.items[0].qty=-1;ret.insert();ret.submit()
  assert not service.get_purchase_chain('Purchase Receipt',ret.name)['can_create']
  results.append('return receipt cannot launch positive payment')
  # Two receipts share one native payable: both must say whole-invoice scope, never invented allocation.
  po2=frappe.copy_doc(po);po2.docstatus=0;po2.items[0].qty=4;po2.insert();po2.submit()
  receipts=[]
  for _ in range(2):
   r=make_purchase_receipt(po2.name);r.items[0].qty=1;r.insert();r.submit();receipts.append(r)
  shared=make_purchase_invoice(receipts[0].name);shared=make_purchase_invoice(receipts[1].name,target_doc=shared);shared.insert();shared.submit()
  for r in receipts:
   c=service.get_purchase_chain('Purchase Receipt',r.name)
   assert c['invoices'][0]['shared'] and c['warnings'] and c['balances'][0]['outstanding']==2000
  results.append('shared payable is labelled whole-invoice scope for both receipts; no fictitious receipt allocation')
  listing=service.get_receipt_list(filters={'company':COMPANY})
  assert any(row['payment_state']=='共享应付' for row in listing['rows'])
  results.append('list balance and shared-payable state use permission-aware invoice ledger balance')
  from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
  advance=get_payment_entry('Purchase Order',po2.name,bank_account='Cash - QAB',bank_amount=500)
  advance.paid_amount=advance.received_amount=500
  advance.references[0].allocated_amount=500
  advance.insert();advance.submit()
  assert any(row['name']==advance.name for row in service.get_payment_records(purchase_receipt=receipts[0].name)['rows'])
  assert service.get_purchase_chain('Purchase Receipt',receipts[0].name)['balances'][0]['outstanding']==2000
  results.append('order advance traces from receipt; unallocated advance never falsely reduces receipt payable')
  shared_draft=service.create_payment_draft(source_doctype='Purchase Receipt',source_name=receipts[0].name,purchase_invoice=shared.name,amount_to_pay=1,bank_account='Cash - QAB',request_id=str(uuid.uuid4()))
  shared_pe=frappe.get_doc('Payment Entry',shared_draft['name'])
  # Dirty links are created only inside savepoints in this allowlisted synthetic site.
  def dirty_case(label, mutate, check):
   frappe.db.savepoint('dirty_links')
   try:
    mutate();check()
   finally:
    frappe.db.rollback(save_point='dirty_links')
   results.append(label)
  def blocked_receipt():
   c=service.get_purchase_chain('Purchase Receipt',receipts[0].name)
   assert c['incomplete_links'] and not c['can_create'] and not c['can_create_invoice'] and not c['balances']
   assert 'QA-MISSING' not in json.dumps(c,default=str)
   listing=service.get_receipt_list(filters={'company':COMPANY,'search':receipts[0].name},page_length=1)
   assert len(listing['rows'])==1 and listing['rows'][0]['incomplete_links'] and not listing['rows'][0]['can_create']
   try:service.create_payment_draft(source_doctype='Purchase Receipt',source_name=receipts[0].name,purchase_invoice=shared.name,amount_to_pay=1,bank_account='Cash - QAB',request_id=str(uuid.uuid4()))
   except frappe.ValidationError:pass
   else:raise AssertionError('dirty linked source accepted a payment draft')
  dirty_case('missing PO does not break receipt list; balances hidden and draft/invoice actions blocked',
   lambda:frappe.db.set_value('Purchase Receipt Item',receipts[0].items[0].name,'purchase_order','QA-MISSING-PO'),blocked_receipt)
  dirty_case('orphan PI children do not pretend no payable exists or allow duplicate invoice',
   lambda:frappe.db.delete('Purchase Invoice',{'name':shared.name}),blocked_receipt)
  def missing_receipt_records():
   c=service.get_purchase_chain('Purchase Receipt',receipts[0].name)
   assert c['incomplete_links'] and not c['can_create'] and not c['balances']
   records=service.get_payment_records(purchase_order=po2.name,page_length=1)
   assert records['rows'] and records['total_count']>=1
   matching=[r for r in service.get_payment_records(purchase_order=po2.name)['rows'] if r['name']==shared_pe.name]
   assert matching and matching[0]['warnings']
   assert 'QA-MISSING' not in json.dumps(records,default=str)
  dirty_case('missing PR in invoice cannot break payment records or leak a dead link',
   lambda:frappe.db.set_value('Purchase Invoice Item',shared.items[1].name,'purchase_receipt','QA-MISSING-PR'),missing_receipt_records)
  def unavailable_payment_ref():
   records=service.get_payment_records(purchase_order=po2.name,page_length=1)
   assert all(r['name']!=advance.name for r in records['rows']) and 'QA-MISSING' not in json.dumps(records,default=str)
  dirty_case('missing direct PO payment reference is safely omitted from procurement records',
   lambda:frappe.db.set_value('Payment Entry Reference',advance.references[0].name,'reference_name','QA-MISSING-PO'),unavailable_payment_ref)
  def assert_no_missing_payment():
   records=service.get_payment_records(purchase_order=po2.name)
   assert all(r['name']!=shared_pe.name for r in records['rows']) and 'QA-MISSING' not in json.dumps(records,default=str)
  dirty_case('missing PI payment reference is safely omitted without leaking the missing target',
   lambda:frappe.db.set_value('Payment Entry Reference',shared_pe.references[0].name,'reference_name','QA-MISSING-PI'),
   lambda:assert_no_missing_payment())
  from unittest.mock import patch
  def denied_read(doctype,name,fields=()):
   if doctype=='Purchase Order' and name==po2.name:raise frappe.PermissionError
   return real_read(doctype,name,fields)
  real_read=service._read
  with patch.object(service,'_read',side_effect=denied_read):
   c=service.get_purchase_chain('Purchase Receipt',receipts[0].name,include_payments=False)
   assert c['incomplete_links'] and not c['orders'] and not c['order_progress'] and not c['balances'] and not c['can_create']
   assert po2.name not in json.dumps(c,default=str)
  results.append('unreadable linked PO exposes neither name nor amount and disables quick payment')
  foreign_order=frappe.get_list('Purchase Order',filters={'company':['!=',COMPANY]},pluck='name',limit_page_length=1)
  assert foreign_order, 'QA must include another synthetic company order'
  dirty_case('cross-company linked PO is treated as unavailable without exposing target',
   lambda:frappe.db.set_value('Purchase Receipt Item',receipts[0].items[0].name,'purchase_order',foreign_order[0]),blocked_receipt)
  # Verify pagination still counts the permission-filtered procurement rows, with no overlapping pages.
  one=service.get_payment_records(page_length=1);two=service.get_payment_records(start=1,page_length=1)
  assert one['total_count']==two['total_count'] and (not one['rows'] or not two['rows'] or one['rows'][0]['name']!=two['rows'][0]['name'])
  assert service.get_purchase_chain('Purchase Receipt',receipts[0].name)['balances'][0]['outstanding']==2000
  results.append('normal balances and payment pagination remain exact after dirty-link rollback')
  stock_item=frappe.get_doc({'doctype':'Item','item_code':'QA-PAYMENT-STOCK','item_name':'QA Synthetic Stock Payment Item','item_group':'Services','stock_uom':'Nos','is_stock_item':1}).insert()
  warehouse=frappe.get_doc({'doctype':'Warehouse','warehouse_name':'QA Payment Stock','company':COMPANY,'parent_warehouse':frappe.db.get_value('Warehouse',{'company':COMPANY,'is_group':1},'name')}).insert()
  stock_po=frappe.get_doc({'doctype':'Purchase Order','company':COMPANY,'supplier':supplier,'currency':'CNY','schedule_date':add_days(nowdate(),1),'items':[{'item_code':stock_item.name,'qty':10,'rate':1000,'warehouse':warehouse.name,'schedule_date':add_days(nowdate(),1)}]}).insert();stock_po.submit()
  stock_pr=make_purchase_receipt(stock_po.name);stock_pr.items[0].qty=4;stock_pr.insert();stock_pr.submit()
  stock_pi=make_purchase_invoice(stock_pr.name);stock_pi.insert();stock_pi.submit()
  payable=frappe.db.get_value('Company',COMPANY,'default_payable_account')
  net=frappe.db.sql('select sum(credit-debit) from `tabGL Entry` where company=%s and account=%s and voucher_no in (%s,%s)',(COMPANY,payable,stock_pr.name,stock_pi.name))[0][0]
  assert float(net)==4000
  stock_args=dict(source_doctype='Purchase Receipt',source_name=stock_pr.name,purchase_invoice=stock_pi.name,amount_to_pay=3000,bank_account='Cash - QAB',request_id=str(uuid.uuid4()))
  pe=frappe.get_doc('Payment Entry',service.create_payment_draft(**stock_args)['name']);pe.submit()
  assert service.get_purchase_chain('Purchase Receipt',stock_pr.name)['balances'][0]['outstanding']==1000
  pe.cancel();stock_pi.reload();stock_pi.cancel()
  stock_return=make_purchase_return(stock_pr.name);stock_return.items[0].qty=-1;stock_return.insert();stock_return.submit()
  assert frappe.db.get_value('Bin',{'item_code':stock_item.name,'warehouse':warehouse.name},'actual_qty')==3
  assert not service.get_purchase_chain('Purchase Receipt',stock_return.name)['can_create']
  results.append('stock receipt + invoice produces payable only once; partial payment and stock return preserve native GL/quantity')
  print(json.dumps({'site':SITE,'tests':results,'status':'passed'},ensure_ascii=False))
 finally:
  frappe.db.rollback();frappe.clear_document_cache('China Finance Settings',COMPANY)
  after={d:frappe.db.count(d) for d in before};assert before==after,(before,after)
  print(json.dumps({'rollback_counts_unchanged':True,'counts':after}))
if __name__=='__main__':
 frappe.init(site=SITE,sites_path='/home/frappe/frappe-bench/sites');frappe.connect()
 try:execute()
 finally:frappe.destroy()
