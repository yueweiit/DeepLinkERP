"""Internal fixed source-job runner. No HTTP endpoint or arbitrary-method CLI."""

from __future__ import annotations

import argparse
import io
import json
import os
import signal
import sys
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import frappe

TASKS = {
    "operating": "deeplinkerp_branding.services.operating_expenses.scheduled_sync",
    "purchase": "deeplinkerp_branding.services.purchase_source_service.scheduled_sync",
}
TASK_TIMEOUT = 300
SAFE_FAILURE = "Source synchronization failed or was interrupted."
SITE = "deeplinkerp.com"
BENCH = Path("/home/frappe/frappe-bench")


class SourceSyncRefused(RuntimeError):
    """A refusal before native Start; no interrupted job needs recovery."""


def log_name(task, run_id):
    if task not in TASKS or str(uuid.UUID(run_id)) != run_id:
        raise ValueError("Invalid source task or run identity")
    return "source-sync-" + task + "-" + run_id


def ensure_allowed():
    # frappe.conf is an init-time snapshot. Re-read native common/site config
    # and the database setting at every entry and operating page boundary.
    try:
        # Native config errors may print values before raising. Keep them private.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            config = frappe.get_site_config(cached=False)
    except Exception:
        raise SourceSyncRefused("Dedicated source sync configuration is invalid") from None
    switches = [config.get(key) for key in ("maintenance_mode", "scheduler_disabled")]
    if any(value is not None and (type(value) not in (bool, int) or value not in (0, 1)) for value in switches):
        raise SourceSyncRefused("Dedicated source sync configuration is invalid")
    if any(switches) or frappe.db.get_single_value("System Settings", "enable_scheduler", cache=False):
        raise SourceSyncRefused("Dedicated source sync requires maintenance off and global scheduler disabled")


def _job(task, require_logging=True):
    if task not in TASKS:
        raise ValueError("Source task is not allowlisted")
    rows = frappe.get_all("Scheduled Job Type", filters={"method": TASKS[task]}, fields=["name"], limit=2)
    if len(rows) != 1:
        raise SourceSyncRefused("Exactly one existing source Scheduled Job Type is required")
    job = frappe.get_doc("Scheduled Job Type", rows[0].name)
    if (job.method != TASKS[task] or job.server_script or job.stopped or job.frequency != "Cron"
            or job.cron_format != "*/15 * * * *" or (require_logging and not job.create_log)):
        raise SourceSyncRefused("Source Scheduled Job Type differs from the dedicated contract")
    return job


def _idle_jobs():
    jobs = [_job(task, require_logging=False) for task in TASKS]
    if any(job.is_job_in_queue() for job in jobs):
        raise SourceSyncRefused("A fixed native source job is queued or running")
    return jobs


def execute_task(task, run_id, timeout=TASK_TIMEOUT):
    """Run one existing native job, and inspect its swallowed-exception outcome."""
    deadline = time.monotonic() + timeout
    name = log_name(task, run_id)
    frappe.db.rollback()  # A reused process cannot carry a prior task's transaction.
    ensure_allowed()
    _idle_jobs()
    job = _job(task)
    if job.is_job_in_queue() or frappe.db.exists("Scheduled Job Log", name):
        raise SourceSyncRefused("Source task is already queued or this run identity was used")
    original_status = job.log_status
    original_traceback, original_debug = frappe.get_traceback, frappe.debug_log
    original_flag = frappe.flags.get("dedicated_source_sync")
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}

    def interrupted(signum, frame):
        raise TimeoutError("Source sync time limit or cancellation")

    def status(value):
        if value == "Start":
            ensure_allowed()
        # Choose an exact durable identity before native Start commits. This
        # lets a separate recovery process repair this run even after SIGKILL.
        if not job.scheduler_log:
            job.scheduler_log = frappe.get_doc(
                doctype="Scheduled Job Log", scheduled_job_type=job.name,
            ).insert(ignore_permissions=True, set_name=name)
        frappe.debug_log = []
        original_status(value)

    try:
        job.log_status = status
        frappe.get_traceback = lambda *args, **kwargs: SAFE_FAILURE
        frappe.debug_log = []
        frappe.flags.dedicated_source_sync = True
        for sig in previous_handlers:
            signal.signal(sig, interrupted)
        signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.monotonic()))
        job.execute()  # Native Start/Complete/Failed and creation/modified timestamps.
    except Exception:
        frappe.db.rollback()
        finalize_task(task, run_id)
    finally:
        signal.alarm(0)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        job.log_status = original_status
        frappe.get_traceback, frappe.debug_log = original_traceback, original_debug
        frappe.flags.dedicated_source_sync = original_flag
        frappe.db.rollback()
    outcome = frappe.db.get_value("Scheduled Job Log", name, "status")
    if outcome not in {"Complete", "Failed"}:
        return finalize_task(task, run_id)
    return outcome


def finalize_task(task, run_id):
    """Repair only the exact interrupted run after its container child is dead."""
    name = log_name(task, run_id)
    job = _job(task, require_logging=False)
    frappe.db.rollback()
    if frappe.db.exists("Scheduled Job Log", name):
        if frappe.db.get_value("Scheduled Job Log", name, "scheduled_job_type") != job.name:
            raise RuntimeError("Run log belongs to another scheduled job")
        if frappe.db.get_value("Scheduled Job Log", name, "status") == "Complete":
            return "Complete"
        frappe.db.set_value("Scheduled Job Log", name, {"status": "Failed", "details": SAFE_FAILURE, "debug_log": None})
    else:
        frappe.get_doc(doctype="Scheduled Job Log", scheduled_job_type=job.name,
                       status="Failed", details=SAFE_FAILURE).insert(ignore_permissions=True, set_name=name)
    if task == "operating":
        from .operating_expenses import SETTINGS
        if frappe.db.exists("DocType", SETTINGS):
            frappe.db.set_single_value(SETTINGS, "last_error", "同步失败，请管理员重试")
    frappe.db.commit()
    return "Failed"


def logging_snapshot():
    """Read-only evidence; intentionally internal and non-whitelisted."""
    ensure_allowed()
    jobs = _idle_jobs()
    return {"version": 1, "jobs": [{"name": job.name, "method": job.method,
                                     "create_log": int(job.create_log)} for job in jobs]}


def set_logging(before, restore=False):
    """Idempotently apply/restore only the two evidenced create_log values."""
    ensure_allowed()
    current = logging_snapshot()
    if (not isinstance(before, dict) or set(before) != {"version", "jobs"} or before["version"] != 1
            or not isinstance(before["jobs"], list) or len(before["jobs"]) != 2):
        raise ValueError("Invalid logging evidence")
    for original, actual in zip(before["jobs"], current["jobs"]):
        if (set(original) != {"name", "method", "create_log"}
                or original["name"] != actual["name"] or original["method"] != actual["method"]
                or type(original["create_log"]) is not int or original["create_log"] not in (0, 1)
                or actual["create_log"] not in (original["create_log"], 1)):
            raise ValueError("Logging evidence or current job identity differs")
    for original, actual in zip(before["jobs"], current["jobs"]):
        value = original["create_log"] if restore else 1
        if actual["create_log"] != value:
            frappe.db.set_value("Scheduled Job Type", actual["name"], "create_log", value, update_modified=False)
    frappe.db.commit()
    return logging_snapshot()


def _marker_path(task, run_id):
    log_name(task, run_id)
    return BENCH / "sites" / SITE / "private" / "source-sync-runs" / (task + "-" + run_id + ".json")


def _process_identity(pid):
    try:
        # PID reuse must never let cancellation signal an unrelated process.
        fields = Path("/proc", str(pid), "stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except FileNotFoundError:
        return None


def cancel_task(task, run_id):
    marker = _marker_path(task, run_id)
    if not marker.exists():
        raise RuntimeError("Missing container run marker; cancellation is unconfirmed")
    state = json.loads(marker.read_text())
    if state["task"] != task or state["run_id"] != run_id or state["log_name"] != log_name(task, run_id):
        raise RuntimeError("Container run identity differs")
    pid = state["pid"]
    if type(pid) is not int or pid < 2:
        raise RuntimeError("Invalid child identity")
    if _process_identity(pid) != state["pid_start"]:
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while _process_identity(pid) == state["pid_start"] and time.monotonic() < deadline:
        time.sleep(0.1)
    if _process_identity(pid) == state["pid_start"]:
        os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while _process_identity(pid) == state["pid_start"] and time.monotonic() < deadline:
        time.sleep(0.1)
    if _process_identity(pid) == state["pid_start"]:
        raise RuntimeError("Container child termination is unconfirmed")


def _connect():
    os.chdir(BENCH / "sites")
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "cancel", "finalize", "logging-snapshot", "logging-apply", "logging-restore"))
    parser.add_argument("--task", choices=tuple(TASKS))
    parser.add_argument("--run-id")
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args(argv)
    if args.action in {"run", "cancel", "finalize"}:
        parser.error("Task and run identity required") if not args.task or not args.run_id else log_name(args.task, args.run_id)
    if args.action in {"cancel", "finalize"}:
        try:
            cancel_task(args.task, args.run_id)
        except Exception:
            print(json.dumps({"outcome": "Refused", "recover": True}))
            return 2
        if args.action == "cancel":
            print(json.dumps({"outcome": "Cancelled"}))
            return 0
    deadline = args.deadline if args.deadline is not None else time.time() + TASK_TIMEOUT
    if args.action == "run" and not 0 < deadline - time.time() <= TASK_TIMEOUT:
        print(json.dumps({"outcome": "Refused", "recover": False}))
        return 2
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    if args.action == "run":
        marker = _marker_path(args.task, args.run_id)
        marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with marker.open("x") as output:
            os.chmod(marker, 0o600)
            json.dump({"task": args.task, "run_id": args.run_id, "log_name": log_name(args.task, args.run_id),
                       "pid": os.getpid(), "pid_start": _process_identity(os.getpid())}, output)
            output.flush()
            os.fsync(output.fileno())
    try:
        if args.action == "run":
            def interrupted(signum, frame):
                raise TimeoutError("Source initialization time limit or cancellation")
            for sig in handlers:
                signal.signal(sig, interrupted)
            signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.time()))
        _connect()
        if args.action == "run":
            remaining = int(deadline - time.time())
            if remaining < 1:
                raise TimeoutError("Source initialization exceeded the deadline")
            outcome = execute_task(args.task, args.run_id, timeout=remaining)
        elif args.action == "finalize":
            outcome = finalize_task(args.task, args.run_id)
        elif args.action == "logging-snapshot":
            outcome = logging_snapshot()
        else:
            outcome = set_logging(json.load(sys.stdin), restore=args.action == "logging-restore")
        print(json.dumps({"outcome": outcome}, sort_keys=True))
        return int(outcome == "Failed")
    except SourceSyncRefused:
        print(json.dumps({"outcome": "Refused", "recover": False}))
        return 2
    except Exception:
        # Never print exception messages, source bodies, credentials or locals.
        print(json.dumps({"outcome": "Refused", "recover": args.action == "run"}))
        return 2
    finally:
        if args.action == "run":
            signal.setitimer(signal.ITIMER_REAL, 0)
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
        frappe.destroy()


if __name__ == "__main__":
    sys.exit(main())
