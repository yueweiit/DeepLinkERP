import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


FIELDNAME = "custom_enable_mes_integration"
RECEIPT_WAREHOUSE_FIELD = "custom_mes_receipt_warehouse"
DELIVERY_WAREHOUSE_FIELD = "custom_mes_delivery_warehouse"
MANUFACTURING_WAREHOUSE_FIELD = "custom_mes_manufacturing_warehouse"


def execute():
	field_existed = frappe.db.has_column("Company", FIELDNAME)
	create_company_integration_switches()
	enable_existing_companies(field_existed)


def create_company_integration_switches():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": FIELDNAME,
					"fieldtype": "Check",
					"insert_after": "parent_company",
					"label": "启用 MES 集成",
					"default": "0",
				},
				{
					"fieldname": RECEIPT_WAREHOUSE_FIELD,
					"fieldtype": "Link",
					"insert_after": FIELDNAME,
					"label": "MES 默认入库仓",
					"options": "Warehouse",
					"depends_on": f"eval:doc.{FIELDNAME}",
					"description": "MES 入库请求未传目标仓且物料未设置默认仓库时使用。",
				},
				{
					"fieldname": DELIVERY_WAREHOUSE_FIELD,
					"fieldtype": "Link",
					"insert_after": RECEIPT_WAREHOUSE_FIELD,
					"label": "MES 默认出库仓",
					"options": "Warehouse",
					"depends_on": f"eval:doc.{FIELDNAME}",
					"description": "MES 销售出库请求未传仓库且物料未设置默认仓库时使用。",
				},
				{
					"fieldname": MANUFACTURING_WAREHOUSE_FIELD,
					"fieldtype": "Link",
					"insert_after": DELIVERY_WAREHOUSE_FIELD,
					"label": "MES 生产转移目标仓",
					"options": "Warehouse",
					"depends_on": f"eval:doc.{FIELDNAME}",
					"description": "MES 生产转移物料移动需要统一目标仓时使用；留空则保留 ERP 映射结果。",
				},
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Company")


def enable_existing_companies(field_existed):
	if not frappe.db.has_column("Company", FIELDNAME):
		return

	where_clause = f"WHERE `{FIELDNAME}` IS NULL" if field_existed else ""
	frappe.db.sql(f"UPDATE `tabCompany` SET `{FIELDNAME}` = 1 {where_clause}")
