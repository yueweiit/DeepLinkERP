import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_migrate():
	"""Create custom fields owned by custom_filters (idempotent)."""
	create_custom_fields(
		{
			"User": [
				{
					"fieldname": "custom_eims_app_user_id",
					"fieldtype": "Data",
					"length": 20,
					"label": "EIMS App User ID",
					"description": "Must match the app_user_id returned by EIMS OAuth userinfo.",
					"insert_after": "username",
					"unique": 1,
					"in_list_view": 1,
				}
			],
			"Buying Settings": [
				{
					"fieldname": "custom_supplier_quotation_warehouse",
					"fieldtype": "Link",
					"label": "Default Supplier Quotation Warehouse",
					"options": "Warehouse",
					"insert_after": "supplier_group",
				}
			],
			"Supplier Quotation": [
				{
					"fieldname": "custom_tier_sync_status",
					"fieldtype": "Select",
					"label": "Tier Price Sync Status",
					"options": "\nSynced\nSync Failed",
					"read_only": 1,
					"in_list_view": 1,
					"insert_after": "supplier",
				}
			]
		},
		update=True,
	)
	# 同步状态用于替换列表状态指示器，不单独占用一列；显式回写兼容
	# 已由旧版本创建且 in_list_view=1 的站点。
	if frappe.db.exists("Custom Field", {"dt": "Supplier Quotation", "fieldname": "custom_tier_sync_status"}):
		frappe.db.set_value(
			"Custom Field",
			{"dt": "Supplier Quotation", "fieldname": "custom_tier_sync_status"},
			"in_list_view",
			0,
			update_modified=False,
		)
	frappe.clear_cache(doctype="Supplier Quotation")
	_keep_production_plan_transfer_qty_last()
	_backfill_unsynced_quotations()


def _keep_production_plan_transfer_qty_last():
	"""Keep the transfer quantity column at the end of the child table.

	ERPNext can add or reorder fields during an upgrade.  Re-applying the
	``insert_after`` position after every migrate makes the custom column
	deterministic and avoids users having to move it manually again.
	"""
	doctype = "Material Request Plan Item"
	fieldname = "custom_transfer_qty"
	custom_field = frappe.db.get_value(
		"Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
	)
	if not custom_field:
		return

	fields = [field for field in frappe.get_meta(doctype).fields if field.fieldname != fieldname]
	if not fields:
		return
	last_fieldname = fields[-1].fieldname
	current_insert_after = frappe.db.get_value("Custom Field", custom_field, "insert_after")
	current_hidden, current_in_list_view = frappe.db.get_value(
		"Custom Field", custom_field, ["hidden", "in_list_view"]
	)
	updates = {}
	if current_insert_after != last_fieldname:
		updates["insert_after"] = last_fieldname
	if current_hidden:
		updates["hidden"] = 0
	if not current_in_list_view:
		updates["in_list_view"] = 1
	if updates:
		frappe.db.set_value(
			"Custom Field",
			custom_field,
			updates,
			update_modified=False,
		)
		frappe.clear_cache(doctype=doctype)
	_update_saved_production_plan_grid_columns()


def _update_saved_production_plan_grid_columns():
	"""Append the custom column to existing per-user grid layouts.

	Users who opened the column settings before the field was introduced have
	a saved whitelist of columns; metadata changes alone do not add new fields
	to that whitelist. Update those layouts idempotently so the field is visible
	without requiring every user to reset their preferences manually.
	"""
	rows = frappe.db.sql(
		"select user, data from `__UserSettings` where doctype=%s",
		("Production Plan",),
		as_dict=True,
	)
	for row in rows:
		try:
			settings = frappe.parse_json(row.data or "{}")
		except Exception:
			continue
		grid_view = settings.get("GridView") or {}
		columns = grid_view.get("Material Request Plan Item")
		if not isinstance(columns, list) or any(
			item.get("fieldname") == "custom_transfer_qty" for item in columns if isinstance(item, dict)
		):
			continue
		columns.append({"fieldname": "custom_transfer_qty", "columns": 2, "sticky": 0})
		frappe.db.sql(
			"update `__UserSettings` set data=%s where user=%s and doctype=%s",
			(frappe.as_json(settings), row.user, "Production Plan"),
		)
		frappe.cache.hset("_user_settings", f"Production Plan::{row.user}", None)


def _backfill_unsynced_quotations():
	"""Idempotently populate sync status for quotations created before migration."""
	if not frappe.db.exists("Custom Field", {"dt": "Supplier Quotation", "fieldname": "custom_tier_sync_status"}):
		return
	from custom_filters import quote_pricing

	# Frappe stores an empty Select as either NULL or an empty string depending
	# on the database/version.  Query both forms so existing quotations are
	# backfilled reliably and the hook remains idempotent.
	for name in frappe.db.sql(
		"""select name from `tabSupplier Quotation`
		where docstatus = 1 and coalesce(custom_tier_sync_status, '') = ''""",
		pluck="name",
	):
		doc = frappe.get_doc("Supplier Quotation", name)
		try:
			quote_pricing.sync_quotation_tiers(doc)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Supplier quotation status backfill failed: {name}")
			frappe.db.set_value("Supplier Quotation", name, "custom_tier_sync_status", "Sync Failed", update_modified=False)
