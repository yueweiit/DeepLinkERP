"""Existing QA account, native permissions and database reads; always roll back fixtures."""
import json
from unittest.mock import patch

import frappe
from crm_integration.crm_integration import finance_release as release
from crm_integration.crm_integration import sales_order as flow
from deeplinkerp_branding.services import compact_sales_service as sales


def execute():
	if frappe.local.site != 'po-grid-qa.localhost':
		raise RuntimeError('Synthetic local QA site only')
	user = 'qa-po-reader@example.invalid'
	frappe.set_user('Administrator'); frappe.flags.mute_emails = True
	doctypes = ['Sales Order', 'Payment Entry', 'GL Entry', 'CRM Integration Log', 'Custom DocPerm', 'Has Role']
	before = {dt: frappe.db.count(dt) for dt in doctypes}
	checks = []
	try:
		from frappe.permissions import setup_custom_perms
		setup_custom_perms('Sales Order')
		read_permission = frappe.get_doc({'doctype':'Custom DocPerm','parent':'Sales Order','role':'Purchase User','permlevel':0,'read':1}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype='Sales Order')
		template = frappe.get_doc('Sales Order', frappe.db.get_value('Sales Order', {}, 'name'))
		doc = frappe.copy_doc(template); doc.docstatus = 0; doc.company = 'Yuewei'; doc.cost_center = None; doc.taxes_and_charges = None; doc.set('taxes', [])
		for item in doc.items:
			for field in ['warehouse','cost_center','income_account','expense_account']: item.set(field, None)
		doc.transaction_date = '2026-10-04'; doc.delivery_date = '2026-10-20'; doc.custom_crm_order_no = None
		doc.custom_process_status = "Pending Confirmation"; doc.insert()
		frappe.db.set_value('Sales Order', doc.name, {'docstatus':1,'status':'To Deliver and Bill','custom_process_status':release.PENDING})
		frappe.db.set_value('Company', 'Yuewei', 'custom_enable_crm_integration', 1)
		frappe.set_user(user)
		assert frappe.has_permission('Sales Order','read',doc=doc)
		assert not frappe.has_permission('Sales Order','write',doc=doc)
		assert not release.has_release_permission()
		assert not release.get_finance_release_review([doc.name])['orders'][0]['can_release']
		checks.append('ordinary order read/edit roles do not imply release permission')
		frappe.set_user('Administrator')
		permission = frappe.get_doc({'doctype':'Custom DocPerm','parent':release.CAPABILITY,'role':'Purchase User','permlevel':0,'read':1}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=release.CAPABILITY)
		frappe.set_user(user)
		assert release.has_release_permission()
		assert not frappe.has_permission('Sales Order','write',doc=doc)
		assert release.get_finance_release_review([doc.name])['orders'][0]['can_release']
		checks.append('native configurable capability authorizes release without any order write permission or deposit input')
		hidden = release.get_finance_release_review([template.name])['orders'][0]
		assert not hidden['can_release'] and 'company' not in hidden
		checks.append('existing company restriction hides foreign-company order details')
		detail = sales.get_sales_order_details(doc.name)
		assert detail['header']['name'] == doc.name and detail['items']
		enrichment = sales.get_sales_display_details([doc.name])
		assert doc.name in enrichment
		checks.append('real parent/child metadata and permission-aware bulk reader serve details and enrichment')
		with patch.object(flow,'validate_mes_sync_available'), patch.object(flow,'enqueue_confirm_deposit_and_push_to_mes') as enqueue:
			result = flow.confirm_deposit_and_push_to_mes(doc.name)
			assert result['process_status'] == release.PROCESSING and result['queued']
			replay = flow.confirm_deposit_and_push_to_mes(doc.name)
			assert replay['idempotent_replay'] and enqueue.call_count == 1
		checks.append('confirmation records processing state; duplicate click creates no second audit or job')
		audits = frappe.get_all('CRM Integration Log',filters={'event':release.AUDIT_EVENT,'reference_name':doc.name},fields=['name','user','creation','status'])
		assert len(audits)==1 and audits[0].user==user and audits[0].status=='Pending'
		checks.append('each order audit stores actual confirmer/time, while async sync stays pending')
		assert not frappe.has_permission('CRM Integration Log', 'read')
		assert release.get_finance_release_review([doc.name])['orders'][0]['last_confirmation'] is None
		checks.append('release capability does not disclose confirmation history without native audit read permission')
		try: release.assert_production_released(doc.name,'Yuewei')
		except frappe.ValidationError: pass
		else: raise AssertionError('processing order entered production')
		checks.append('actual production gate blocks processing order')
		frappe.set_user('Administrator'); read_permission.db_set({'write':1,'submit':1}); frappe.clear_cache(doctype='Sales Order'); frappe.set_user(user)
		from frappe.client import set_value
		try: set_value('Sales Order', doc.name, 'custom_process_status', 'Pending Production')
		except frappe.ValidationError: pass
		else: raise AssertionError('native REST write bypassed production authorization')
		assert frappe.db.get_value('Sales Order', doc.name, 'custom_process_status') == release.PROCESSING
		frappe.set_user('Administrator'); read_permission.db_set({'write':0,'submit':0}); frappe.clear_cache(doctype='Sales Order'); frappe.set_user(user)
		checks.append('native submitted-order writes cannot forge released state even with order write permission')
		release.update_finance_audit(audits[0].name,doc.name,'Success','Pending Production')
		assert frappe.db.get_value('CRM Integration Log',audits[0].name,'status')=='Success'
		frappe.set_user('Administrator'); frappe.delete_doc('Custom DocPerm',permission.name,ignore_permissions=True)
		frappe.clear_cache(doctype=release.CAPABILITY); frappe.set_user(user)
		assert not release.has_release_permission()
		assert frappe.db.get_value('CRM Integration Log',audits[0].name,'user')==user
		checks.append('removing configured permission revokes future actions without changing historical confirmer')
	finally:
		frappe.set_user('Administrator'); frappe.db.rollback()
		for dt in ['Sales Order','Sales Production Release Permission']: frappe.clear_cache(doctype=dt)
		after = {dt: frappe.db.count(dt) for dt in doctypes}
		assert before == after, {'before':before,'after':after}
	print(json.dumps({'checks':checks,'rollback_counts_unchanged':True,'no_external_crm_mes_calls':True},ensure_ascii=False))
