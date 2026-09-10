"""Authenticated RPC for independent air/sea comparison records."""
import frappe
from overseas_costing.services import air_sea_records, air_sea_batch
from overseas_costing.services.access_control import require_overseas_cost_access


@frappe.whitelist()
def search_batches(keyword="", page=1, page_length=20):
    require_overseas_cost_access()
    return air_sea_batch.search_batches(keyword, page, page_length)


@frappe.whitelist()
def preview_batch(batch_name):
    require_overseas_cost_access()
    return air_sea_batch.preview_batch(batch_name)


@frappe.whitelist()
def list_records(keyword="", page=1, page_length=20):
    return air_sea_records.list_records(keyword, page, page_length)


@frappe.whitelist()
def get_record(name):
    return air_sea_records.get_record(name)


@frappe.whitelist(methods=["POST"])
def save_record(title, payload_json, name=None, modified=None, request_id=None):
    return air_sea_records.save_record(title, payload_json, name, modified, request_id)


@frappe.whitelist(methods=["POST"])
def delete_record(name, modified=None):
    return air_sea_records.delete_record(name, modified)
