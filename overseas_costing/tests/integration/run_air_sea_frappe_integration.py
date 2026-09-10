"""Transactional synthetic checks on the existing isolated test database only."""
import json
import uuid
from decimal import Decimal
import frappe


def check_denied(action):
    try:
        action()
    except frappe.PermissionError:
        return
    raise AssertionError("Expected permission denial")


def batch_checks(tag, users):
    from overseas_costing.services import air_sea_records as records, air_sea_batch
    frappe.set_user("Administrator")
    batches = []
    for suffix in ("SOURCE", "ALLOWED"):
        batch = frappe.get_doc({"doctype": "Overseas Cost Batch", "batch_no": f"AIR-SEA-{tag}-{suffix}", "status": "Draft"}).insert()
        version = frappe.get_doc({"doctype": "Overseas Cost Version", "batch": batch.name, "version_code": "V1", "status": "Active", "is_current": 1}).insert()
        frappe.db.set_value("Overseas Cost Batch", batch.name, "current_version", version.name)
        batches.append((batch.name, version.name))
    batch, version = batches[0]
    for index in range(205):
        frappe.get_doc({"doctype": "Overseas Cost Item", "batch": batch, "version": version,
            "row_no": index + 1, "material_code": "SAME-SKU", "product_name": "共享箱测试",
            "quantity": 20, "actual_shipped_qty": 3, "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
            "shipped_uom": "套", "unit": "套", "customs_declared_value_mxn": 200,
            "unit_price": 999, "goods_value": 19980, "gross_weight_kg": 10}).insert()
    snapshot = frappe.get_doc({"doctype": "Overseas Packing Snapshot", "batch": batch, "cost_version": version,
        "version": 1, "idempotency_key": tag, "source_kind": "manual_attachment", "source_id": tag,
        "source_revision": tag, "source_label": "共享整票", "source_hash": "a" * 64,
        "status": "Confirmed", "is_current": 1, "total_gross_weight_kg": 50, "total_volume_m3": 2}).insert()
    before = frappe.get_doc("Overseas Cost Batch", batch).as_dict()
    frappe.set_user(users[0])
    preview = air_sea_batch.preview_batch(batch)
    assert len(preview["payload"]["rows"]) == 205
    assert Decimal(preview["payload"]["rows"][0][20]) == 3
    assert Decimal(preview["payload"]["totals_override"]["grossWeight"]) == 50
    assert preview["payload"]["rows"][0][25] == "" and Decimal(preview["payload"]["rows"][0][26]) == 200
    original_payload = json.loads(json.dumps(preview["payload"]))
    preview["payload"]["totals_override"]["grossWeight"] = "60"
    saved = records.save_record("批次测试 " + tag, json.dumps(preview["payload"]), request_id=str(uuid.uuid4()))["record"]
    assert Decimal(saved["result"]["v"]["grossWeight"]) == 60
    assert frappe.get_doc("Overseas Cost Batch", batch).as_dict() == before
    assert frappe.db.get_value("Overseas Packing Snapshot", snapshot.name, "total_gross_weight_kg") == 50
    assert not records.get_record(saved["name"])["source_changed"]
    frappe.set_user("Administrator")
    item_name = frappe.db.get_value("Overseas Cost Item", {"batch": batch}, "name")
    frappe.db.set_value("Overseas Cost Item", item_name, "actual_shipped_qty", 4)
    assert records.get_record(saved["name"])["source_changed"]
    forged = json.loads(json.dumps(original_payload))
    forged["source"]["batch"] = batches[1][0]
    try:
        records.save_record("伪造来源", json.dumps(forged), request_id=str(uuid.uuid4()))
    except ValueError:
        pass
    else:
        raise AssertionError("Forged source accepted")
    permission = frappe.get_doc({"doctype": "User Permission", "user": users[1], "allow": "Overseas Cost Batch",
        "for_value": batches[1][0], "apply_to_all_doctypes": 1}).insert()
    frappe.clear_cache(user=users[1])
    frappe.set_user(users[1])
    check_denied(lambda: air_sea_batch.preview_batch(batch))
    check_denied(lambda: records.get_record(saved["name"]))
    assert records.list_records(keyword=tag)["total"] == 0
    # Matches frappe.api.v1.update_doc: update body before Document.save permission check.
    def forged_rest_write():
        doc = frappe.get_doc(records.DOCTYPE, saved["name"])
        doc.update({"source_batch": "", "source_version": "", "source_packing_snapshot": "", "payload_json": '{"rows":[]}'})
        doc.save()
    check_denied(forged_rest_write)
    frappe.set_user("Administrator")
    records.delete_record(saved["name"], records.get_record(saved["name"])["record"]["modified"])
    frappe.delete_doc("User Permission", permission.name)


def run():
    frappe.init(site="settlement-test.local")
    assert frappe.conf.db_host == "oc-settlement-test-db", "Refuse non-test database"
    frappe.connect()
    frappe.set_user("Administrator")
    frappe.reload_doc("overseas_costing", "doctype", "overseas_air_sea_comparison", force=True)
    frappe.clear_cache()
    from overseas_costing.services import air_sea_records as records, air_sea_batch
    from overseas_costing import install
    install.ensure_access_role()
    tag = uuid.uuid4().hex[:10]
    users = [f"air-sea-{tag}-{suffix}@example.invalid" for suffix in ("a", "b", "outsider")]
    for user in users:
        doc = frappe.get_doc({"doctype": "User", "email": user, "first_name": "Comparison test", "send_welcome_email": 0})
        doc.flags.no_welcome_mail = True
        doc.insert(ignore_permissions=True)
        if user != users[-1]:
            doc.add_roles("海外成本核算用户")
    row = [""] * 30
    for index, value in {1: "SAMPLE", 4: "PZ", 20: "50400", 23: "515.2", 24: "1.0805676", 25: "1.0449"}.items():
        row[index] = value
    payload = {"rows": [row]}
    frappe.set_user(users[0])
    request_id = str(uuid.uuid4())
    created = records.save_record("集成测试 " + tag, json.dumps(payload), request_id=request_id)["record"]
    assert Decimal(created["result"]["airTotal"]) == Decimal("92973.8233928448")
    replay = records.save_record(created["title"], json.dumps(payload), request_id=request_id)
    assert replay["record"]["name"] == created["name"] and replay["idempotent"]
    assert records.list_records(keyword=tag)["total"] == 1
    frappe.set_user(users[1])
    current = records.get_record(created["name"])["record"]
    assert current["owner"] == users[0]
    saved = records.save_record("同事已更新 " + tag, json.dumps(payload), name=current["name"], modified=current["modified"], request_id=str(uuid.uuid4()))["record"]
    assert saved["modified_by"] == users[1]
    frappe.set_user(users[0])
    try:
        records.save_record(created["title"], json.dumps(payload), request_id=request_id)
    except ValueError as exc:
        assert "其他成员" in str(exc)
    else:
        raise AssertionError("Create replay adopted another member's newer version")
    frappe.set_user(users[1])
    try:
        records.save_record("过期覆盖", json.dumps(payload), name=current["name"], modified=current["modified"], request_id=str(uuid.uuid4()))
    except ValueError as exc:
        assert "其他成员" in str(exc)
    else:
        raise AssertionError("Stale save succeeded")
    frappe.set_user(users[-1])
    check_denied(lambda: records.get_record(created["name"]))
    check_denied(lambda: records.list_records(keyword=tag))
    check_denied(lambda: records.save_record("越权", json.dumps(payload), request_id=str(uuid.uuid4())))
    check_denied(lambda: records.delete_record(created["name"], saved["modified"]))
    assert not frappe.has_permission(records.DOCTYPE, "read", doc=created["name"])
    frappe.set_user(users[1])
    # Ordinary Frappe writes run the same authoritative calculation.
    doc = frappe.get_doc(records.DOCTYPE, created["name"])
    doc.result_json = '{"airTotal": 1}'
    doc.save()
    assert Decimal(json.loads(doc.result_json)["airTotal"]) == Decimal("92973.8233928448")
    draft = records.save_record("空白草稿 " + tag, '{"rows":[]}', request_id=str(uuid.uuid4()))["record"]
    assert draft["result"]["status"] == "Draft"
    for index in range(9):
        records.save_record(f"分页 {index} {tag}", '{"rows":[]}', request_id=str(uuid.uuid4()))
    listed = records.list_records(keyword=tag, page_length=10)
    second_page = records.list_records(keyword=tag, page=2, page_length=10)
    assert listed["total"] == 11 and len(listed["items"]) == 10
    assert len(second_page["items"]) == 1
    for record in records.list_records(keyword=tag, page_length=100)["items"]:
        records.delete_record(record["name"], record["modified"])
    assert records.list_records(keyword=tag)["total"] == 0
    batch_checks(tag, users)
    frappe.set_user("Administrator")
    for user in users:
        frappe.delete_doc("User", user, ignore_permissions=True)
    frappe.db.rollback()
    print(json.dumps({"ok": True, "checks": ["two-user shared CRUD", "request replay", "stale update rejection", "outsider RPC and DocType denial", "server formula on direct write", "draft", "search and pagination", "delete"]}))
    frappe.destroy()


if __name__ == "__main__":
    try:
        run()
    finally:
        if getattr(frappe.local, "db", None):
            frappe.db.rollback()
            frappe.destroy()
