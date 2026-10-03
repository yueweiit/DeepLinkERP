"""Permission-checked native sales display enrichment; preserve CRM's product naming."""
import json
import frappe
from frappe.model import get_permitted_fields
from deeplinkerp_branding.services.purchase_payment_service import _read, _require_fields

@frappe.whitelist()
def get_sales_display_details(sales_orders):
 names=json.loads(sales_orders) if isinstance(sales_orders,str) else sales_orders
 if not isinstance(names,list) or len(names)>2500:frappe.throw('最多读取2500张订单')
 result={}
 try:
  from crm_integration.crm_integration.sales_order import set_first_product, set_first_sales_person
 except ModuleNotFoundError:
  set_first_product = set_first_sales_person = None
 for name in dict.fromkeys(names):
  if not isinstance(name,str) or not frappe.has_permission('Sales Order','read',doc=name):continue
  doc=_read('Sales Order',name,{'company'})
  row={};result[name]=row
  try:_require_fields('Sales Order',{'items'})
  except frappe.PermissionError:continue
  fields=set(get_permitted_fields('Sales Order Item',parenttype='Sales Order',permission_type='read'))
  details={name:{'product':'','sales_person':''}}
  if 'custom_product' in fields and set_first_product:
   set_first_product(details,[name]);row['dlp_product']=details[name]['product']
  if not row.get('dlp_product') and 'item_name' in fields:
   row['dlp_product']=doc.items[0].item_name if doc.items else ''
  if row.get('dlp_product') and len(doc.items)>1:row['dlp_product']+=f' 等{len(doc.items)}项'
  if {'qty','uom'}<=fields:
   units={i.uom for i in doc.items};row['dlp_quantity']=f'{sum(i.qty for i in doc.items):g} {next(iter(units))}' if len(units)==1 else '多单位明细'
  if 'rate' in fields:
   row['dlp_rate']=doc.items[0].rate if len(doc.items)==1 else '多明细'
  try:
   _require_fields('Sales Order',{'sales_team'});_require_fields('Sales Team',{'sales_person'},'Sales Order')
   if set_first_sales_person:
    set_first_sales_person(details,[name]);row['dlp_sales_person']=details[name]['sales_person']
  except frappe.PermissionError:pass
 return result
