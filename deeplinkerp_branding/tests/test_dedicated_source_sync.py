"""Fixed source-job runner, using the installed native execute implementation."""

import importlib
import io
import json
import signal
import subprocess
import tempfile
import time
import unittest
import uuid
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

import frappe
from frappe.core.doctype.scheduled_job_type.scheduled_job_type import ScheduledJobType


class Log:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.status = "Scheduled"
        self.details = None
        self.debug_log = None
    def insert(self, ignore_permissions=False, set_name=None):
        self.name = set_name or "native-log"
        return self
    def db_set(self, key, value):
        setattr(self, key, value)


class Job:
    execute = ScheduledJobType.execute
    log_status = ScheduledJobType.log_status
    update_scheduler_log = ScheduledJobType.update_scheduler_log
    def __init__(self, method):
        self.name = method.rsplit(".", 2)[1] + ".scheduled_sync"
        self.method = method
        self.create_log = 1
        self.stopped = 0
        self.server_script = None
        self.frequency = "Cron"
        self.cron_format = "*/15 * * * *"
        self.scheduler_log = None
        self.last_execution = None
    def db_set(self, key, value, **kwargs):
        setattr(self, key, value)
    def is_job_in_queue(self):
        return False


class DedicatedSourceSyncTests(unittest.TestCase):
    def setUp(self):
        try:
            self.runner = importlib.import_module("deeplinkerp_branding.services.dedicated_source_sync")
        except ImportError:
            self.fail("Dedicated allowlisted source runner is missing")
        self.db = Mock()
        self.db.get_single_value.return_value = 0
        self.conf = frappe._dict(maintenance_mode=0, scheduler_disabled=0)
        self.configuration = tempfile.TemporaryDirectory()
        self.addCleanup(self.configuration.cleanup)
        self.sites_path = Path(self.configuration.name)
        self.site_path = self.sites_path / "source-test"
        self.site_path.mkdir()
        self.common_file = self.sites_path / "common_site_config.json"
        self.site_file = self.site_path / "site_config.json"
        self.common_file.write_text("{}")
        self.site_file.write_text("{}")
        self.jobs = {key: Job(method) for key, method in self.runner.TASKS.items()}
        self.logs = {}
        self.method = Mock()
        def get_doc(doctype=None, name=None, **values):
            if doctype == "Scheduled Job Type":
                return next(job for job in self.jobs.values() if job.name == name)
            log = Log(**values)
            old_insert = log.insert
            def insert(**kwargs):
                old_insert(**kwargs)
                self.logs[log.name] = log
                return log
            log.insert = insert
            return log
        def get_all(doctype, filters, **kwargs):
            return [frappe._dict(name=job.name) for job in self.jobs.values() if job.method == filters["method"]]
        def get_value(doctype, name, field):
            log = self.logs.get(name)
            return getattr(log, field, None) if log else None
        self.db.get_value.side_effect = get_value
        self.db.exists.side_effect = lambda doctype, name: name in self.logs
        for item in [patch.object(frappe, "db", self.db), patch.object(frappe, "conf", self.conf),
                     patch.object(frappe, "local", SimpleNamespace(site="source-test", sites_path=str(self.sites_path),
                         site_path=str(self.site_path), flags=frappe._dict(new_site=False))),
                     patch.object(frappe, "flags", frappe._dict()), patch.object(frappe, "job", None),
                     patch.object(frappe, "get_system_settings", return_value="UTC"),
                     patch.object(frappe, "debug_log", []), patch.object(frappe, "logger", return_value=Mock()),
                     patch.object(frappe, "get_all", side_effect=get_all), patch.object(frappe, "get_doc", side_effect=get_doc),
                     patch.object(frappe, "get_attr", return_value=self.method)]:
            item.start()
            self.addCleanup(item.stop)
        self.run_id = "11111111-1111-4111-8111-111111111111"

    def test_exact_allowlist_and_unknown_task_refused_before_database(self):
        self.assertEqual(set(self.runner.TASKS.values()), {
            "deeplinkerp_branding.services.operating_expenses.scheduled_sync",
            "deeplinkerp_branding.services.purchase_source_service.scheduled_sync",
            "deeplinkerp_branding.services.purchase_reversal_progress.recover"})
        with self.assertRaises(ValueError):
            self.runner.execute_task("frappe.email.send", self.run_id)
        self.db.get_single_value.assert_not_called()

    def test_native_complete_uses_one_exact_run_log_and_timestamps(self):
        self.assertEqual(self.runner.execute_task("operating", self.run_id), "Complete")
        log = self.jobs["operating"].scheduler_log
        self.assertEqual(log.name, self.runner.log_name("operating", self.run_id))
        self.assertEqual(log.status, "Complete")
        self.assertIsNotNone(self.jobs["operating"].last_execution)
        self.assertEqual(len(self.logs), 1)
        self.method.assert_called_once_with()

    def test_reversal_runs_with_scheduler_off_without_changing_original_logging_flags(self):
        self.assertIn("reversal", self.jobs)
        job = self.jobs["reversal"]
        job.create_log = 0
        before = self.runner.logging_snapshot()
        self.assertEqual(len(before["jobs"]), 2)
        self.assertEqual(self.runner.execute_task("reversal", self.run_id), "Complete")
        self.assertEqual(job.create_log, 0)
        self.assertEqual(job.scheduler_log.status, "Complete")
        self.assertEqual(job.scheduler_log.name, self.runner.log_name("reversal", self.run_id))
        self.assertEqual(self.runner.logging_snapshot(), before)
        self.db.set_value.assert_not_called()

    def test_swallowed_native_failure_returns_failed_without_sensitive_context(self):
        self.method.side_effect = ValueError("Bearer secret-token; raw approval payload")
        self.assertEqual(self.runner.execute_task("operating", self.run_id), "Failed")
        log = self.jobs["operating"].scheduler_log
        self.assertEqual(log.status, "Failed")
        self.assertNotIn("secret", log.details)
        self.assertNotIn("payload", log.details)
        self.db.rollback.assert_called()

    def test_timeout_interrupts_actual_python_task_and_native_records_failed(self):
        def native_consumes_timeout(signum=None):
            try:
                if signum is None:
                    time.sleep(5)
                else:
                    signal.raise_signal(signum)
            except TimeoutError:
                return  # Native valuation records its failed RIV, then returns.

        for task, method in (("purchase", lambda: time.sleep(5)), ("reversal", native_consumes_timeout),
                             ("operating", lambda: native_consumes_timeout(signal.SIGTERM))):
            with self.subTest(task=task):
                self.method.side_effect = method
                started = time.monotonic()
                self.assertEqual(self.runner.execute_task(task, self.run_id, timeout=0.1), "Failed")
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(signal.alarm(0), 0)
                self.assertIsNone(self.runner._deadline.get())

    def test_global_scheduler_and_maintenance_guards_create_no_logs(self):
        for field in ("enable_scheduler", "maintenance_mode", "scheduler_disabled"):
            with self.subTest(field=field):
                self.db.get_single_value.return_value = int(field == "enable_scheduler")
                self.site_file.write_text(json.dumps({field: 1}) if field != "enable_scheduler" else "{}")
                with self.assertRaises(RuntimeError):
                    self.runner.execute_task("operating", self.run_id)
        self.method.assert_not_called()
        self.assertEqual(self.logs, {})

    def test_unlogged_stopped_or_script_jobs_are_refused(self):
        job = self.jobs["operating"]
        for field, value in (("create_log", 0), ("stopped", 1), ("server_script", "unsafe"), ("cron_format", "* * * * *")):
            old = getattr(job, field)
            setattr(job, field, value)
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.runner.execute_task("operating", self.run_id)
            setattr(job, field, old)
        self.method.assert_not_called()

    def test_metadata_apply_and_rollback_only_touch_two_original_logging_flags(self):
        self.jobs["operating"].create_log = 0
        before = self.runner.logging_snapshot()
        self.runner.set_logging(before)
        self.assertEqual(self.db.set_value.call_count, 1)
        self.assertEqual(self.db.set_value.call_args.args[:2], ("Scheduled Job Type", self.jobs["operating"].name))
        self.jobs["operating"].create_log = 1
        self.db.set_value.reset_mock()
        self.runner.set_logging(before)
        self.db.set_value.assert_not_called()
        self.runner.set_logging(before, restore=True)
        self.assertEqual(self.db.set_value.call_args.args[2:], ("create_log", 0))

    def test_metadata_rejects_foreign_job_or_changed_original_evidence(self):
        before = self.runner.logging_snapshot()
        before["jobs"][0]["method"] = "frappe.email.send"
        with self.assertRaises(ValueError):
            self.runner.set_logging(before)
        self.db.set_value.assert_not_called()

    def test_failed_first_task_cannot_leak_transaction_to_second_in_same_process(self):
        self.method.side_effect = [ValueError("source failure"), None]
        self.assertEqual(self.runner.execute_task("operating", self.run_id), "Failed")
        self.assertEqual(self.runner.execute_task("purchase", self.run_id), "Complete")
        self.assertEqual([self.jobs[task].scheduler_log.status for task in ("operating", "purchase")], ["Failed", "Complete"])
        self.assertEqual(frappe.flags.get("dedicated_source_sync"), None)

    def test_cli_deadline_covers_initialization_and_returns_only_safe_json(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(self.runner, "BENCH", Path(temporary)), \
             patch.object(self.runner, "_connect"), patch.object(frappe, "destroy"), \
             patch.object(self.runner, "execute_task", return_value="Complete") as execute, \
             patch.object(self.runner.sys, "stdout", io.StringIO()) as output:
            self.assertEqual(self.runner.main(["run", "--task", "operating", "--run-id", self.run_id,
                                               "--deadline", str(time.time() + 20)]), 0)
            self.assertLessEqual(execute.call_args.kwargs["timeout"], 20)
            self.assertEqual(json.loads(output.getvalue()), {"outcome": "Complete"})

    def test_expired_deadline_never_connects_or_runs_a_source_job(self):
        with patch.object(self.runner, "_connect") as connect, patch.object(self.runner.sys, "stdout", io.StringIO()):
            self.assertEqual(self.runner.main(["run", "--task", "operating", "--run-id", self.run_id,
                                               "--deadline", str(time.time() - 1)]), 2)
        connect.assert_not_called()

    def test_container_cancel_terminates_real_child_and_emits_confirmed_result(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(child.kill)
        with tempfile.TemporaryDirectory() as temporary, patch.object(self.runner, "BENCH", Path(temporary)):
            marker = self.runner._marker_path("operating", self.run_id)
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({"task": "operating", "run_id": self.run_id,
                "log_name": self.runner.log_name("operating", self.run_id), "pid": child.pid,
                "pid_start": self.runner._process_identity(child.pid)}))
            with patch.object(self.runner.sys, "stdout", io.StringIO()) as output:
                self.assertEqual(self.runner.main(["cancel", "--task", "operating", "--run-id", self.run_id]), 0)
            self.assertEqual(json.loads(output.getvalue()), {"outcome": "Cancelled"})
        child.wait(timeout=2)
        self.assertEqual(child.returncode, -signal.SIGTERM)

    def test_pid_reuse_cannot_signal_an_unrelated_container_process(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(self.runner, "BENCH", Path(temporary)):
            marker = self.runner._marker_path("operating", self.run_id)
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({"task": "operating", "run_id": self.run_id,
                "log_name": self.runner.log_name("operating", self.run_id), "pid": 123, "pid_start": "old"}))
            with patch.object(self.runner, "_process_identity", return_value="new"), patch.object(self.runner.os, "kill") as kill:
                self.runner.cancel_task("operating", self.run_id)
            kill.assert_not_called()

    def test_native_connection_uses_sites_directory_for_frappe_file_logs(self):
        with patch.object(self.runner.os, "chdir") as chdir, patch.object(frappe, "init"), \
             patch.object(frappe, "connect"), patch.object(frappe, "set_user"):
            self.runner._connect()
        chdir.assert_called_once_with(self.runner.BENCH / "sites")

    def test_fresh_native_config_observes_common_and_site_file_switches(self):
        self.runner.ensure_allowed()
        for target in (self.common_file, self.site_file):
            for field in ("maintenance_mode", "scheduler_disabled"):
                with self.subTest(file=target.name, field=field):
                    target.write_text(json.dumps({field: 1}))
                    # The initialized frappe.conf deliberately remains unchanged.
                    self.assertEqual(self.conf.get(field), 0)
                    with self.assertRaises(self.runner.SourceSyncRefused):
                        self.runner.ensure_allowed()
                    target.write_text("{}")
                    self.runner.ensure_allowed()

    def test_invalid_config_is_refused_without_native_error_or_config_output(self):
        for target in (self.common_file, self.site_file):
            with self.subTest(file=target.name):
                target.write_text('{"db_password":"SYNTHETIC-PRIVATE",')
                with patch.object(self.runner.sys, "stdout", io.StringIO()) as output, \
                     patch.object(self.runner.sys, "stderr", io.StringIO()) as error:
                    with self.assertRaisesRegex(self.runner.SourceSyncRefused, "configuration"):
                        self.runner.ensure_allowed()
                    self.assertEqual(output.getvalue(), "")
                    self.assertEqual(error.getvalue(), "")
                target.write_text("{}")

    def test_either_native_job_queued_or_started_refuses_logging_before_mutation(self):
        from frappe.utils import background_jobs
        from rq.job import JobStatus
        before = self.runner.logging_snapshot()
        self.jobs["operating"].create_log = 0
        self.jobs["purchase"].create_log = 0
        for task, job in self.jobs.items():
            for state in (JobStatus.QUEUED, JobStatus.STARTED):
                with self.subTest(task=task, state=state):
                    with patch.object(job, "is_job_in_queue", side_effect=lambda: background_jobs.is_job_enqueued("synthetic-native")), \
                         patch.object(background_jobs, "get_job", return_value=Mock(get_status=Mock(return_value=state))):
                        with self.assertRaises(self.runner.SourceSyncRefused):
                            self.runner.logging_snapshot()
                        with self.assertRaises(self.runner.SourceSyncRefused):
                            self.runner.set_logging(before)
        self.db.set_value.assert_not_called()
        self.method.assert_not_called()

    def test_other_native_job_queued_or_started_refuses_current_task_before_start(self):
        from frappe.utils import background_jobs
        from rq.job import JobStatus
        for blocked in self.jobs:
            current = "purchase" if blocked == "operating" else "operating"
            for state in (JobStatus.QUEUED, JobStatus.STARTED):
                with self.subTest(blocked=blocked, current=current, state=state):
                    job = self.jobs[blocked]
                    with patch.object(job, "is_job_in_queue", side_effect=lambda: background_jobs.is_job_enqueued("synthetic-native")), \
                         patch.object(background_jobs, "get_job", return_value=Mock(get_status=Mock(return_value=state))):
                        with self.assertRaises(self.runner.SourceSyncRefused):
                            self.runner.execute_task(current, str(uuid.uuid4()))
        self.assertEqual(self.logs, {})
        self.method.assert_not_called()
