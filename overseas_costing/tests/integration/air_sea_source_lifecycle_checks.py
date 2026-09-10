"""Standalone synthetic source-reference checks on the isolated Frappe site."""
import json
import uuid

import frappe


def check_source_lifecycle():
    """Run with an existing connection; never target a non-test database."""
    assert frappe.local.site == "settlement-test.local"
    assert frappe.conf.db_host == "oc-settlement-test-db"
    from overseas_costing.services import air_sea_batch, air_sea_records, calculate_service

    tag = "LOCAL-AIR-SEA-LIFECYCLE-" + uuid.uuid4().hex[:12]
    original_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        batch = frappe.get_doc({"doctype": "Overseas Cost Batch", "batch_no": tag, "status": "Draft"}).insert()
        version = frappe.get_doc({"doctype": "Overseas Cost Version", "batch": batch.name,
            "version_code": "V1", "status": "Active", "is_current": 1}).insert()
        frappe.db.set_value("Overseas Cost Batch", batch.name, "current_version", version.name)
        source = {"batch": batch.name, "batch_no": tag, "version": version.name,
            "packing_snapshot": None, "revision": tag, "imported_at": str(frappe.utils.now_datetime())}
        source["token"] = air_sea_batch._signature(source)
        row = [""] * 30
        row[1], row[4], row[20], row[23], row[25] = "LOCAL-SKU", "件", "10", "5", "2"
        saved = air_sea_records.save_record(tag, json.dumps({"rows": [row], "source": source}),
            request_id=str(uuid.uuid4()))["record"]
        before = frappe.get_doc("Overseas Cost Batch", batch.name).as_dict()
        outcome = calculate_service.delete_batch(batch.name)
        assert not outcome["ok"] and "测算" in outcome["message"]
        assert frappe.get_doc("Overseas Cost Batch", batch.name).as_dict() == before
        assert frappe.db.exists("Overseas Cost Version", version.name)
        current = air_sea_records.get_record(saved["name"])["record"]
        assert current["payload"]["source"]["batch"] == batch.name
        assert current["result"]["status"] == "Ready"
        air_sea_records.delete_record(saved["name"], current["modified"])
        assert calculate_service.delete_batch(batch.name)["ok"]
        assert not frappe.db.exists("Overseas Cost Batch", batch.name)
        assert not frappe.db.exists("Overseas Cost Version", version.name)
        try:
            air_sea_batch.validate_source(source, for_update=True)
        except (ValueError, frappe.DoesNotExistError):
            pass
        else:
            raise AssertionError("Deleted source was accepted")
        return {"ok": True, "checks": ["referenced batch deletion rejected",
            "snapshot remains readable", "unreferenced batch deletion succeeds", "deleted source rejected"]}
    finally:
        frappe.set_user(original_user)


if __name__ == "__main__":
    frappe.init(site="settlement-test.local")
    assert frappe.conf.db_host == "oc-settlement-test-db"
    frappe.connect()
    try:
        print(json.dumps(check_source_lifecycle()))
    finally:
        frappe.db.rollback()
        frappe.destroy()
