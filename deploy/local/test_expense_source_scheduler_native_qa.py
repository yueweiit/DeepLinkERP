"""Real native scheduler/transaction checks, restricted to the existing synthetic site.

External source reads are patched. Native document counts must stay unchanged.
Only this helper's token-named logs/cache rows are removed after verification.
"""

import json
import os
import signal
import time
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import frappe
from deeplinkerp_branding.services import dedicated_source_sync as runner
from deeplinkerp_branding.services import operating_expenses as operating
from deeplinkerp_branding.services import purchase_source_service as purchase

QA_SITE = "operating-expenses-qa.localhost"
NATIVE = ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "Journal Entry", "GL Entry",
          "Company", "Supplier", "Customer", "Employee", "Item", "Account")
STATE_FIELDS = ("enabled", "changed_since", "until", "cursor", "last_sync_at", "last_error", "preview_fingerprint")


class NativeSourceSchedulerQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if frappe.local.site != QA_SITE or frappe.conf.db_host != "db":
            raise RuntimeError("Existing isolated synthetic QA site only")
        if frappe.db.get_single_value("System Settings", "enable_scheduler"):
            raise RuntimeError("QA requires the global scheduler already disabled")
        frappe.set_user("Administrator")
        from frappe.core.doctype.scheduled_job_type.scheduled_job_type import insert_single_event
        for method in runner.TASKS.values():
            if not frappe.db.exists("Scheduled Job Type", {"method": method}):
                insert_single_event("Cron", method, "*/15 * * * *")
        frappe.db.commit()
        cls.logging_before = runner.logging_snapshot()
        cls.all_jobs_before = frappe.get_all("Scheduled Job Type", fields=["*"], order_by="name", limit=0)
        cls.original_last_execution = {row["name"]: frappe.db.get_value("Scheduled Job Type", row["name"], "last_execution")
                                       for row in cls.logging_before["jobs"]}
        runner.set_logging(cls.logging_before)
        cls.counts = {doctype: frappe.db.count(doctype) for doctype in NATIVE}
        cls.original_settings = {key: operating._settings().get(key) for key in STATE_FIELDS}
        cls.logs, cls.sources = [], []

    @classmethod
    def tearDownClass(cls):
        frappe.db.rollback()
        if hasattr(cls, "original_settings"):
            settings = operating._settings()
            settings.update(cls.original_settings)
            operating._save(settings)
            # Exact synthetic identities only, created by this helper.
            for name in cls.sources:
                frappe.db.delete(operating.SOURCE, {"name": name})
            for name in cls.logs:
                frappe.db.delete("Scheduled Job Log", {"name": name})
            for name, value in cls.original_last_execution.items():
                frappe.db.set_value("Scheduled Job Type", name, "last_execution", value, update_modified=False)
            frappe.db.commit()
            runner.set_logging(cls.logging_before, restore=True)

    def setUp(self):
        frappe.db.rollback()
        settings = operating._settings()
        settings.update({"enabled": 1, "changed_since": None, "until": None, "cursor": None, "last_error": None})
        operating._save(settings)
        frappe.db.commit()
        self.snapshot = datetime.now(timezone.utc).isoformat()

    def tearDown(self):
        frappe.db.rollback()
        self.assertEqual({doctype: frappe.db.count(doctype) for doctype in NATIVE}, self.counts)

    def run_task(self, task="operating", timeout=300):
        run_id = str(uuid.uuid4())
        name = runner.log_name(task, run_id)
        self.logs.append(name)
        return runner.execute_task(task, run_id, timeout=timeout), name

    def source(self):
        name = "QA-SCHED-" + uuid.uuid4().hex
        self.sources.append(name)
        return {"source_id": name, "source_system": "cashier-payment-archive", "version": uuid.uuid4().hex,
                "source_company": "QA Operating China", "source_sheet": "QA scheduler", "application_type": "payment",
                "application_type_raw": "付款申请", "applicant": "QA applicant", "payee_name": "QA supplier",
                "summary": "Synthetic scheduler checkpoint", "request_date": "2026-10-06", "currency": "CNY",
                "amount": "100", "paid_amount": "0", "pending_amount": "100", "source_status": "未付款",
                "approvals": {"eligibility": "eligible", "raw": {}}, "payments": [], "attachments": [], "updated_at": self.snapshot}

    def page(self, item=None, end=True, cursor=None):
        return {"items": [item] if item else [], "end": end, "next_cursor": cursor, "until": self.snapshot}

    @contextmanager
    def temporary_site_config(self):
        # Only the isolated QA site's real config; preserve its exact bytes.
        target = Path(frappe.local.site_path) / "site_config.json"
        original = target.read_bytes()
        config = json.loads(original)
        def change(**values):
            target.write_text(json.dumps({**config, **values}))
        try:
            yield change
        finally:
            target.write_bytes(original)

    def test_native_start_complete_and_all_pages_have_persisted_timestamps(self):
        starts = []
        items = [self.source(), self.source()]
        pages = iter([self.page(items[0], end=False, cursor="QA-page-1"), self.page(items[1])])
        def read(params):
            started = frappe.get_all("Scheduled Job Log", filters={"name": ["in", self.logs], "status": "Start"},
                                     fields=["name", "creation", "modified"])
            starts.extend(started)
            return next(pages)
        with patch.object(operating, "_source_page", side_effect=read), patch.object(operating, "_source_mode", return_value="cashier"):
            outcome, name = self.run_task()
        self.assertEqual(outcome, "Complete")
        self.assertTrue(starts)
        log = frappe.get_doc("Scheduled Job Log", name)
        self.assertGreaterEqual(log.modified, log.creation)
        self.assertEqual(log.status, "Complete")
        self.assertIsNotNone(frappe.db.get_value("Scheduled Job Type", log.scheduled_job_type, "last_execution"))
        self.assertTrue(all(frappe.db.exists(operating.SOURCE, item["source_id"]) for item in items))
        self.assertIsNone(operating._settings().cursor)

    def test_failed_second_page_retains_first_cache_and_cursor_then_resumes(self):
        first, unfinished = self.source(), self.source()
        def fail(params):
            if not params.get("cursor"):
                return self.page(first, end=False, cursor="QA-committed-page")
            operating._upsert(unfinished, operating._maps(operating._settings()))
            raise ValueError("SECRET source payload must never appear in scheduler details")
        with patch.object(operating, "_source_page", side_effect=fail):
            outcome, name = self.run_task()
        self.assertEqual(outcome, "Failed")
        self.assertTrue(frappe.db.exists(operating.SOURCE, first["source_id"]))
        self.assertFalse(frappe.db.exists(operating.SOURCE, unfinished["source_id"]))
        self.assertEqual(operating._settings().cursor, "QA-committed-page")
        self.assertEqual(operating._settings().last_error, "同步失败，请管理员重试")
        self.assertEqual(frappe.get_doc("Scheduled Job Log", name).details, runner.SAFE_FAILURE)
        with patch.object(operating, "_source_page", return_value=self.page(unfinished)) as read, \
             patch.object(operating, "_source_mode", return_value="cashier"):
            resumed, _ = self.run_task()
        self.assertEqual(resumed, "Complete")
        self.assertEqual(read.call_args.args[0]["cursor"], "QA-committed-page")
        self.assertTrue(frappe.db.exists(operating.SOURCE, unfinished["source_id"]))

    def test_real_timeout_is_failed_and_next_native_task_still_completes(self):
        with patch.object(operating, "_source_page", side_effect=lambda params: time.sleep(5)):
            failed, name = self.run_task(timeout=1)
        self.assertEqual(failed, "Failed")
        self.assertEqual(frappe.get_doc("Scheduled Job Log", name).details, runner.SAFE_FAILURE)
        with patch.dict(frappe.conf, purchase_source_sync_enabled=True), patch.object(purchase, "sync_purchase_sources") as sync:
            completed, _ = self.run_task("purchase")
        self.assertEqual(completed, "Complete")
        sync.assert_called_once_with()
        self.assertEqual(signal.alarm(0), 0)

    def test_native_hard_interruption_repair_targets_only_exact_started_log(self):
        run_id = str(uuid.uuid4())
        name = runner.log_name("purchase", run_id)
        job = runner._job("purchase")
        frappe.get_doc(doctype="Scheduled Job Log", scheduled_job_type=job.name).insert(ignore_permissions=True, set_name=name)
        frappe.db.set_value("Scheduled Job Log", name, "status", "Start")
        frappe.db.commit()
        self.logs.append(name)
        self.assertEqual(runner.finalize_task("purchase", run_id), "Failed")
        self.assertEqual(frappe.get_doc("Scheduled Job Log", name).details, runner.SAFE_FAILURE)

    def test_metadata_is_idempotent_and_no_unrelated_job_is_changed(self):
        before = frappe.get_all("Scheduled Job Type", fields=["name", "method", "create_log", "stopped", "frequency", "cron_format"], order_by="name", limit_page_length=0)
        snapshot = runner.logging_snapshot()
        runner.set_logging(snapshot)
        runner.set_logging(snapshot)
        after = frappe.get_all("Scheduled Job Type", fields=["name", "method", "create_log", "stopped", "frequency", "cron_format"], order_by="name", limit_page_length=0)
        self.assertEqual(before, after)
        exact = {row["name"] for row in self.logging_before["jobs"]}
        unrelated_before = [row for row in self.all_jobs_before if row.name not in exact]
        unrelated_after = [row for row in frappe.get_all("Scheduled Job Type", fields=["*"], order_by="name", limit=0) if row.name not in exact]
        self.assertEqual(unrelated_before, unrelated_after)

    def test_maintenance_switch_between_pages_keeps_completed_checkpoint(self):
        item = self.source()
        with self.temporary_site_config() as configure:
            def read(params):
                configure(maintenance_mode=1)
                return self.page(item, end=False, cursor="QA-before-maintenance")
            with patch.dict(frappe.conf, maintenance_mode=0), patch.object(operating, "_source_page", side_effect=read) as source:
                outcome, _ = self.run_task()
        self.assertEqual(outcome, "Failed")
        source.assert_called_once()
        self.assertTrue(frappe.db.exists(operating.SOURCE, item["source_id"]))
        self.assertEqual(operating._settings().cursor, "QA-before-maintenance")

    def test_global_and_maintenance_gate_never_starts_native_logs(self):
        count = frappe.db.count("Scheduled Job Log")
        original = frappe.db.get_single_value
        with patch.object(frappe.db, "get_single_value", side_effect=lambda doctype, field, **kwargs: 1 if (doctype, field) == ("System Settings", "enable_scheduler") else original(doctype, field, **kwargs)):
            with self.assertRaises(runner.SourceSyncRefused):
                self.run_task()
        with self.temporary_site_config() as configure:
            for field in ("maintenance_mode", "scheduler_disabled"):
                configure(**{field: 1})
                with self.subTest(field=field), self.assertRaises(runner.SourceSyncRefused):
                    self.run_task()
        self.assertEqual(frappe.db.count("Scheduled Job Log"), count)


if __name__ == "__main__":
    os.chdir("/home/frappe/frappe-bench/sites")
    frappe.init(site=QA_SITE, sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    try:
        unittest.main()
    finally:
        frappe.destroy()
