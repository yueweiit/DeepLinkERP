import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Material Request": [
				{
					"fieldname": "custom_request_source",
					"fieldtype": "Select",
					"insert_after": "custom_material_request_no",
					"label": "需求来源",
					"options": "\nMES\n手动创建",
					"read_only": 1,
					"in_list_view": 1,
				},
			]
		}
	)

	if not frappe.db.has_column("Material Request", "custom_request_source"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabMaterial Request`
		SET custom_request_source = 'MES'
		WHERE IFNULL(custom_request_source, '') = ''
		  AND name LIKE 'MAT-MR-MES-%'
		"""
	)
