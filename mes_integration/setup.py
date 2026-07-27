"""Idempotent schema synchronization for MES integration fields."""

import frappe


def sync_custom_fields():
	# MES can run without CRM, but when both apps are installed, make the
	# optional CRM schema available before MES backfills delivery status.
	if "crm_integration" in frappe.get_installed_apps():
		from crm_integration.setup import sync_custom_fields as sync_crm_custom_fields

		sync_crm_custom_fields()

	from mes_integration.patches.v1_0.add_company_integration_switches import execute as add_company_fields
	from mes_integration.patches.v1_0.add_delivery_note_readiness_status import execute as add_delivery_status
	from mes_integration.patches.v1_0.add_material_request_item_detail_button import execute as add_detail_button
	from mes_integration.patches.v1_0.add_material_request_item_details import execute as add_request_details
	from mes_integration.patches.v1_0.add_material_request_item_transferred_qty import execute as add_transferred_qty
	from mes_integration.patches.v1_0.add_mes_custom_fields import execute as add_mes_fields

	add_request_details()
	add_transferred_qty()
	add_detail_button()
	add_delivery_status()
	add_company_fields()
	add_mes_fields()


def after_install():
	sync_custom_fields()


def after_migrate():
	sync_custom_fields()
