"""Real independent database connections; only synthetic isolated-site records."""
import json
import subprocess
import sys
import uuid
import frappe


def connect():
    frappe.init(site="settlement-test.local")
    assert frappe.conf.db_host == "oc-settlement-test-db", "Refuse non-test database"
    frappe.connect()
    # Exercise classic MySQL repeatable-read semantics, also supported by MariaDB.
    # MariaDB 11's extra snapshot-isolation mode would abort with 1020 before CAS.
    frappe.db.sql("SET SESSION innodb_snapshot_isolation=OFF")


def worker():
    connect()
    from overseas_costing.services import air_sea_records as records
    job = json.load(sys.stdin)
    frappe.set_user(job.pop("user"))
    try:
        response = records.save_record(**job)
        frappe.db.commit()
        print(json.dumps({"ok": True, "record": response["record"]}))
    except ValueError as exc:
        frappe.db.rollback()
        print(json.dumps({"ok": False, "error": str(exc)}))
    finally:
        frappe.destroy()


def launch(job):
    process = subprocess.Popen([sys.executable, __file__, "worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    process.stdin.write(json.dumps(job))
    process.stdin.close()
    process.stdin = None
    return process


def finish(process):
    stdout, stderr = process.communicate(timeout=45)
    assert process.returncode == 0, stderr
    return json.loads(stdout.strip().splitlines()[-1])


def run():
    connect()
    from overseas_costing.services import air_sea_records as records
    tag = "parallel-" + uuid.uuid4().hex[:10]
    users = [f"{tag}-{suffix}@example.invalid" for suffix in ("a", "b")]
    frappe.set_user("Administrator")
    try:
        frappe.reload_doc("overseas_costing", "doctype", "overseas_air_sea_comparison", force=True)
        frappe.clear_cache()
        for user in users:
            doc = frappe.get_doc({"doctype": "User", "email": user, "first_name": "Comparison concurrency", "send_welcome_email": 0}).insert()
            doc.add_roles("海外成本核算用户")
        frappe.db.commit()
        frappe.set_user(users[0])
        first = records.save_record(tag, '{"rows":[]}', request_id=str(uuid.uuid4()))["record"]
        frappe.db.commit()
        # Establish an old repeatable-read snapshot before another connection commits.
        assert str(frappe.db.get_value(records.DOCTYPE, first["name"], "modified")) == first["modified"]
        updated = finish(launch({"user": users[1], "title": tag + " updated", "payload_json": '{"rows":[]}',
            "name": first["name"], "modified": first["modified"], "request_id": str(uuid.uuid4())}))
        assert updated["ok"]
        try:
            records.delete_record(first["name"], first["modified"])
        except ValueError as exc:
            assert "其他成员" in str(exc)
        else:
            raise AssertionError("Stale snapshot deleted a newer committed record")
        frappe.db.rollback()
        assert records.get_record(first["name"])["record"]["title"] == tag + " updated"
        frappe.db.rollback()

        # Two simultaneous creates with the same logical request create one document.
        job = {"user": users[0], "title": tag + " create", "payload_json": '{"rows":[]}', "request_id": str(uuid.uuid4())}
        results = [finish(process) for process in [launch(job), launch(job)]]
        assert all(result["ok"] for result in results), results
        assert results[0]["record"]["name"] == results[1]["record"]["name"]
        assert frappe.db.count(records.DOCTYPE, {"title": job["title"]}) == 1
        frappe.db.rollback()

        # Two users writing the same modified version: exactly one wins.
        current = results[0]["record"]
        jobs = [{"user": user, "title": tag + " winner " + str(index), "payload_json": '{"rows":[]}',
            "name": current["name"], "modified": current["modified"], "request_id": str(uuid.uuid4())}
            for index, user in enumerate(users)]
        results = [finish(process) for process in [launch(job) for job in jobs]]
        assert sum(result["ok"] for result in results) == 1, results
        assert "其他成员" in next(result["error"] for result in results if not result["ok"])
        print(json.dumps({"ok": True, "checks": ["repeatable-read stale delete rejected", "parallel create idempotency", "two-user simultaneous save conflict"]}))
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")
        for name in frappe.get_all(records.DOCTYPE, filters={"title": ["like", tag + "%"]}, pluck="name"):
            frappe.delete_doc(records.DOCTYPE, name, ignore_permissions=True)
        for user in users:
            if frappe.db.exists("User", user):
                frappe.delete_doc("User", user, ignore_permissions=True)
        frappe.db.commit()
        frappe.destroy()


if __name__ == "__main__":
    worker() if len(sys.argv) > 1 else run()
