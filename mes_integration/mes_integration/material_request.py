import hashlib
import time
from contextlib import contextmanager
from copy import deepcopy
from math import ceil

import frappe
from frappe import _

from frappe.model.document import bulk_insert
from frappe.model.mapper import get_mapped_doc
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, get_datetime, now, now_datetime, time_diff_in_seconds
from mes_integration.mes_integration.settings import is_mes_integration_enabled, throw_mes_integration_disabled


CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES = (
    "Material Issue",
    "Material Transfer for Manufacture",
    "Injection Molding Issuance",
)
MES_ITEM_DETAILS_FIELD = "custom_item_details"
MES_ITEM_DETAIL_DOCTYPE = "MES Material Request Item Detail"
MES_INTEGRATION_REQUEST_FLAG = "mes_integration_request"
MES_INWARD_MATERIAL_REQUEST_TYPES = (
	"Purchase",
	"Manufacture",
	"Customer Provided",
	"Material Transfer",
)
MES_CREATE_MAX_ATTEMPTS = 5
MES_CREATE_RETRY_DELAYS = (0.1, 0.25, 0.5, 1.0)
MES_IDEMPOTENCY_KEY_FIELDS = ("custom_material_request_no", "request_id", "idempotency_key")
MES_BIN_LOCK_TIMEOUT_SECONDS = 180
MES_DETAIL_BULK_CHUNK_SIZE = 2000
MES_ITEM_DETAILS_VALIDATED_FLAG = "mes_item_details_validated"
MES_MATERIAL_REQUEST_TASK_DOCTYPE = "MES Material Request Task"
MES_TASK_QUEUE = "long"
MES_TASK_TIMEOUT = 1500
MES_TASK_STALE_SECONDS = 1800
MES_TASK_RECOVERY_BATCH_SIZE = 100


class MESMaterialRequestPerformanceMixin:
    """Defer stock-demand synchronization for Material Requests created by MES."""

    def update_child_table(self, fieldname, df=None):
        if self.flags.get(MES_INTEGRATION_REQUEST_FLAG) and fieldname == MES_ITEM_DETAILS_FIELD:
            return

        return super().update_child_table(fieldname, df)

    def update_requested_qty(self, mr_item_rows=None):
        if not self.flags.get(MES_INTEGRATION_REQUEST_FLAG):
            return super().update_requested_qty(mr_item_rows)

        return enqueue_mes_material_request_bin_sync(self, mr_item_rows)


@frappe.whitelist()
def create_and_submit_material_request_from_mes(data=None, material_request=None):
    """Accept a Material Request from MES and process it asynchronously."""
    from mes_integration.mes_integration.stock_entry import validate_mes_api_user

    payload = get_mes_material_request_payload(data=data, material_request=material_request)

    if not isinstance(payload, dict):
        frappe.throw(_("缺少请求数据或数据格式不正确"))

    validate_mes_api_user()
    queue_material_request_task(payload)


def queue_material_request_task(payload):
    """Persist an MES payload and enqueue only its task id.

    The payload stays in MariaDB until the worker finishes, so a large request
    does not have to be serialized into every Redis job argument.
    """
    material_request_data = extract_material_request_data(payload)
    validate_mes_material_request_payload(material_request_data)

    if not is_mes_integration_enabled(material_request_data.get("company")):
        throw_mes_integration_disabled(material_request_data.get("company"))

    material_request_data = material_request_data.copy()
    material_request_data["doctype"] = "Material Request"
    request_key = get_mes_idempotency_key(payload, material_request_data)
    task_payload = material_request_data.copy()
    if request_key and frappe.db.has_column("Material Request", "custom_material_request_no"):
        task_payload["custom_material_request_no"] = request_key
    task_name = build_material_request_task_name(
        material_request_data.get("company"), request_key
    )

    existing_task = frappe.db.exists(MES_MATERIAL_REQUEST_TASK_DOCTYPE, task_name)
    if existing_task:
        task = frappe.get_doc(MES_MATERIAL_REQUEST_TASK_DOCTYPE, task_name)
        validate_material_request_task_access(task)

        if task.status == "Failed":
            frappe.db.set_value(
                MES_MATERIAL_REQUEST_TASK_DOCTYPE,
                task.name,
                {
                    "status": "Queued",
                    "material_request": None,
                    "request_payload": frappe.as_json(task_payload),
                    "item_count": len(material_request_data.get("items") or []),
                    "detail_count": len(
                        material_request_data.get(MES_ITEM_DETAILS_FIELD) or []
                    ),
                    "error_message": None,
                    "started_at": None,
                    "finished_at": None,
                },
                update_modified=True,
            )
            task.reload()
        elif task.status == "Processing" and is_stale_material_request_task(task):
            frappe.db.set_value(
                MES_MATERIAL_REQUEST_TASK_DOCTYPE,
                task.name,
                {
                    "status": "Queued",
                    "error_message": None,
                    "started_at": None,
                    "finished_at": None,
                },
                update_modified=True,
            )
            task.reload()

        if task.status == "Queued":
            schedule_material_request_task(task.name)

        set_material_request_task_response(task, reused=True)
        return

    existing_material_request = get_existing_material_request_name(
        material_request_data.get("company"), request_key
    )
    task = frappe.get_doc(
        {
            "doctype": MES_MATERIAL_REQUEST_TASK_DOCTYPE,
            "name": task_name,
            "request_key": request_key,
            "company": material_request_data.get("company"),
            "status": "Success" if existing_material_request else "Queued",
            "submitted_by": frappe.session.user,
            "material_request": existing_material_request,
            "request_payload": None
            if existing_material_request
            else frappe.as_json(task_payload),
            "item_count": len(material_request_data.get("items") or []),
            "detail_count": len(material_request_data.get(MES_ITEM_DETAILS_FIELD) or []),
        }
    )

    try:
        task.insert(ignore_permissions=True, set_name=task_name)
    except frappe.DuplicateEntryError:
        # Another request with the same company/key won the race. Do not create
        # a second job; return the already persisted task instead.
        frappe.db.rollback()
        task = frappe.get_doc(MES_MATERIAL_REQUEST_TASK_DOCTYPE, task_name)
        validate_material_request_task_access(task)
        set_material_request_task_response(task, reused=True)
        return

    if task.status == "Queued":
        schedule_material_request_task(task.name)

    set_material_request_task_response(task)


@frappe.whitelist()
def get_material_request_task_status(task_id=None, request_id=None):
    """Return the current status of an asynchronously created Material Request."""
    from mes_integration.mes_integration.stock_entry import validate_mes_api_user

    validate_mes_api_user()
    task_id = (task_id or "").strip()
    request_id = (request_id or "").strip()

    if task_id:
        task_name = task_id
    elif request_id:
        task_name = frappe.db.get_value(
            MES_MATERIAL_REQUEST_TASK_DOCTYPE,
            {"request_key": request_id, "submitted_by": frappe.session.user},
            "name",
            order_by="creation desc",
        )
    else:
        frappe.throw(_("缺少 task_id 或 request_id"))

    if not task_name or not frappe.db.exists(MES_MATERIAL_REQUEST_TASK_DOCTYPE, task_name):
        frappe.throw(
            _("未找到物料需求异步任务 {0}").format(task_id or request_id),
            frappe.DoesNotExistError,
        )

    task = frappe.get_doc(MES_MATERIAL_REQUEST_TASK_DOCTYPE, task_name)
    validate_material_request_task_access(task)
    set_material_request_task_response(task)


def create_and_submit_material_request_payload(payload):
    """Synchronously create and submit a validated payload inside a worker."""
    material_request_data = extract_material_request_data(payload)

    if not isinstance(material_request_data, dict):
        frappe.throw(_("缺少 Material Request 数据或数据格式不正确"))

    validate_mes_material_request_payload(material_request_data)
    validate_mes_material_request_permissions()

    if not is_mes_integration_enabled(material_request_data.get("company")):
        throw_mes_integration_disabled(material_request_data.get("company"))

    material_request_data = material_request_data.copy()
    material_request_data["doctype"] = "Material Request"
    request_key = get_mes_idempotency_key(payload, material_request_data)
    material_request_data.pop("request_id", None)
    material_request_data.pop("idempotency_key", None)

    if request_key and frappe.db.has_column("Material Request", "custom_material_request_no"):
        material_request_data["custom_material_request_no"] = request_key

    existing_name = get_existing_material_request_name(
        material_request_data.get("company"), request_key
    )
    if existing_name:
        existing_doc = frappe.get_doc("Material Request", existing_name)
        if existing_doc.docstatus != 1:
            frappe.throw(
                _("MES 请求号 {0} 已存在，但对应物料需求尚未提交。请稍后重试。").format(
                    request_key
                )
            )
        set_material_request_response(existing_doc, reused=True)
        return existing_doc

    for attempt in range(MES_CREATE_MAX_ATTEMPTS):
        try:
            material_request_doc = create_material_request_attempt(
                material_request_data,
                request_key,
                isolate_payload=attempt > 0,
            )
        except frappe.DuplicateEntryError:
            if not request_key:
                raise

            # A concurrent request with the same key may have committed first.
            frappe.db.rollback()
            existing_name = get_existing_material_request_name(
                material_request_data.get("company"), request_key
            )
            if not existing_name:
                raise

            existing_doc = frappe.get_doc("Material Request", existing_name)
            if existing_doc.docstatus != 1:
                raise
            set_material_request_response(existing_doc, reused=True)
            return existing_doc
        except frappe.QueryDeadlockError:
            frappe.db.rollback()
            if attempt >= MES_CREATE_MAX_ATTEMPTS - 1:
                raise
            time.sleep(MES_CREATE_RETRY_DELAYS[attempt])
            continue

        set_material_request_response(material_request_doc)
        return material_request_doc


def validate_mes_material_request_payload(material_request_data):
    """Perform cheap validation before storing a task; full validation runs in the worker."""
    if not isinstance(material_request_data, dict):
        frappe.throw(_("缺少 Material Request 数据或数据格式不正确"))

    if material_request_data.get("doctype") not in (None, "Material Request"):
        frappe.throw(_("只能通过此接口创建 Material Request"))

    if material_request_data.get("docstatus") not in (None, 0, "0"):
        frappe.throw(_("MES 传入的物料需求必须是草稿状态"))

    if not material_request_data.get("material_request_type"):
        frappe.throw(_("缺少物料需求类型 material_request_type"))

    if not material_request_data.get("company"):
        frappe.throw(_("缺少物料需求公司"))

    items = material_request_data.get("items") or []
    if not isinstance(items, (list, tuple)) or not items:
        frappe.throw(_("物料需求至少需要一行明细"))

    for idx, row in enumerate(items, start=1):
        if not isinstance(row, dict):
            frappe.throw(_("第 {0} 行物料需求格式不正确").format(idx))

        if not row.get("item_code"):
            frappe.throw(_("第 {0} 行缺少物料号").format(row.get("idx") or idx))

        if flt(row.get("qty")) <= 0:
            frappe.throw(_("第 {0} 行数量必须大于 0").format(row.get("idx") or idx))


def build_material_request_task_name(company, request_key=None):
    seed = f"{company or ''}\0{request_key or frappe.generate_hash(length=32)}"
    suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"MES-MRT-{suffix}"


def is_stale_material_request_task(task):
    if not task.started_at:
        return False

    return (
        time_diff_in_seconds(now_datetime(), get_datetime(task.started_at))
        > MES_TASK_STALE_SECONDS
    )


def recover_material_request_tasks():
    """Requeue tasks left behind by a crashed request process or worker."""
    tasks = frappe.get_all(
        MES_MATERIAL_REQUEST_TASK_DOCTYPE,
        filters={"status": ["in", ["Queued", "Processing"]]},
        fields=["name", "status", "started_at"],
        order_by="modified asc",
        limit=MES_TASK_RECOVERY_BATCH_SIZE,
    )

    for task in tasks:
        if task.status == "Processing":
            if not is_stale_material_request_task(task):
                continue

            frappe.db.set_value(
                MES_MATERIAL_REQUEST_TASK_DOCTYPE,
                task.name,
                {
                    "status": "Queued",
                    "error_message": "任务超过最大处理时间，已自动重新排队。",
                    "started_at": None,
                    "finished_at": None,
                },
                update_modified=True,
            )
            frappe.db.commit()

        enqueue_material_request_task_job(task.name)


def schedule_material_request_task(task_name):
    """Enqueue after the task row is committed, passing only the task name."""
    callback = lambda: enqueue_material_request_task_job(task_name)
    request = getattr(frappe.local, "request", None)
    if request and hasattr(request, "after_response"):
        request.after_response.add(callback)
    else:
        frappe.db.after_commit.add(callback)


def enqueue_material_request_task_job(task_name):
    try:
        frappe.enqueue(
            "mes_integration.mes_integration.material_request.process_material_request_task",
            queue=MES_TASK_QUEUE,
            timeout=MES_TASK_TIMEOUT,
            job_id=f"mes-material-request-task:{task_name}",
            deduplicate=True,
            task_name=task_name,
        )
    except Exception:
        error_message = frappe.get_traceback()
        try:
            frappe.db.set_value(
                MES_MATERIAL_REQUEST_TASK_DOCTYPE,
                task_name,
                {"status": "Failed", "error_message": error_message, "finished_at": now()},
                update_modified=True,
            )
            frappe.db.commit()
        except Exception:
            error_message += "\nFailed to update async task:\n" + frappe.get_traceback()

        frappe.log_error(
            title="Failed to enqueue MES Material Request task",
            message=error_message,
        )


def process_material_request_task(task_name):
    """Create and submit one persisted MES task in a background worker."""
    task = frappe.get_doc(MES_MATERIAL_REQUEST_TASK_DOCTYPE, task_name)
    if task.status == "Success":
        return

    # A scheduler recovery job may be enqueued by Administrator. Preserve the
    # original MES user's permissions and audit identity while processing it.
    if task.submitted_by and task.submitted_by != frappe.session.user:
        frappe.set_user(task.submitted_by)

    if not task.request_payload:
        mark_material_request_task_failed(task_name, "异步任务缺少原始请求数据")
        return

    attempts = cint(task.attempts) + 1
    frappe.db.set_value(
        MES_MATERIAL_REQUEST_TASK_DOCTYPE,
        task_name,
        {
            "status": "Processing",
            "attempts": attempts,
            "started_at": now(),
            "error_message": None,
        },
        update_modified=True,
    )
    frappe.db.commit()

    try:
        payload = frappe.parse_json(task.request_payload)
        material_request_doc = create_and_submit_material_request_payload(payload)
    except (frappe.QueryDeadlockError, frappe.RetryBackgroundJobError) as exc:
        frappe.db.rollback()
        frappe.db.set_value(
            MES_MATERIAL_REQUEST_TASK_DOCTYPE,
            task_name,
            {"status": "Queued", "error_message": str(exc)},
            update_modified=True,
        )
        frappe.db.commit()
        raise
    except Exception:
        error_message = frappe.get_traceback()
        frappe.db.rollback()
        mark_material_request_task_failed(task_name, error_message)
        return

    frappe.db.set_value(
        MES_MATERIAL_REQUEST_TASK_DOCTYPE,
        task_name,
        {
            "status": "Success",
            "material_request": material_request_doc.name,
            "request_payload": None,
            "error_message": None,
            "finished_at": now(),
        },
        update_modified=True,
    )
    frappe.db.commit()


def mark_material_request_task_failed(task_name, error_message):
    frappe.db.set_value(
        MES_MATERIAL_REQUEST_TASK_DOCTYPE,
        task_name,
        {"status": "Failed", "error_message": error_message, "finished_at": now()},
        update_modified=True,
    )
    frappe.db.commit()


def validate_material_request_task_access(task):
    if task.submitted_by == frappe.session.user or "System Manager" in frappe.get_roles():
        return

    frappe.throw(_("无权访问该物料需求异步任务"), frappe.PermissionError)


def set_material_request_task_response(task, reused=False):
    status = (task.status or "Queued").lower()
    response = {
        "status": status,
        "task_status": task.status,
        "task_id": task.name,
        "message": {
            "queued": "物料需求已进入异步处理队列。",
            "processing": "物料需求正在后台处理中。",
            "success": "物料需求已创建并提交。",
            "failed": "物料需求异步处理失败。",
        }.get(status, "物料需求异步任务状态已更新。"),
        "material_request": task.material_request,
        "material_request_docstatus": 1 if status == "success" else None,
        "idempotent_reuse": reused,
        "timestamp": now(),
    }
    if status == "failed":
        response["error_message"] = task.error_message

    frappe.response["data"] = response
    frappe.response["http_status_code"] = 202 if status in ("queued", "processing") else 200


@contextmanager
def lock_mes_material_request_bins(material_request_data):
    """Lock affected Bin rows while a background reconciliation runs.

    The lock is acquired in a stable order so concurrent reconciliations of the
    same Item-Warehouse pair wait instead of overwriting each other's result.
    """
    item_warehouse_pairs = get_mes_material_request_item_warehouse_pairs(material_request_data)

    if not item_warehouse_pairs:
        yield
        return

    from erpnext.stock.utils import get_bin

    lock_names = [
        "mes_mr_bin_"
        + hashlib.sha256(
            "|".join(
                str(value)
                for value in (
                    getattr(frappe.local, "site", ""),
                    material_request_data.get("company") or "",
                    item_code,
                    warehouse,
                )
            ).encode("utf-8")
        ).hexdigest()
        for item_code, warehouse in item_warehouse_pairs
    ]
    acquired_lock_names = []

    try:
        # The advisory lock coordinates concurrent MES reconciliation jobs.
        # The row lock below also coordinates with standard ERPNext Bin writes.
        if getattr(frappe.db, "db_type", None) == "mariadb":
            for lock_name in lock_names:
                result = frappe.db.sql(
                    "SELECT GET_LOCK(%s, %s)",
                    (lock_name, MES_BIN_LOCK_TIMEOUT_SECONDS),
                )
                if not result or result[0][0] != 1:
                    raise frappe.QueryDeadlockError(
                        "Timed out waiting for MES Material Request inventory lock"
                    )
                acquired_lock_names.append(lock_name)

        for item_code, warehouse in item_warehouse_pairs:
            # get_bin handles the first request that creates an Item-Warehouse row.
            get_bin(item_code, warehouse)
            if getattr(frappe.db, "db_type", None) != "sqlite":
                frappe.db.sql(
                    """
                    SELECT name
                    FROM `tabBin`
                    WHERE item_code = %s AND warehouse = %s
                    FOR UPDATE
                    """,
                    (item_code, warehouse),
                )

        yield
    finally:
        if getattr(frappe.db, "db_type", None) == "mariadb":
            release_lock_names = tuple(reversed(acquired_lock_names))
            if release_lock_names:
                release_locks = lambda: release_mes_material_request_locks(release_lock_names)
                # Release only after the request transaction has committed or
                # rolled back. Releasing here would let another request enter
                # while this transaction is still uncommitted.
                frappe.db.after_commit.add(release_locks)
                frappe.db.after_rollback.add(release_locks)


def release_mes_material_request_locks(lock_names):
    for lock_name in lock_names:
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))


def get_mes_material_request_item_warehouse_pairs(material_request_data, mr_item_rows=None):
    requested_item_rows = set(mr_item_rows or [])
    item_warehouse_pairs = {
        (row.get("item_code"), row.get("warehouse"))
        for row in material_request_data.get("items") or []
        if (not mr_item_rows or row.name in requested_item_rows)
        and row.get("item_code")
        and row.get("warehouse")
    }
    return sorted(item_warehouse_pairs)


def enqueue_mes_material_request_bin_sync(material_request, mr_item_rows=None):
    """Schedule an idempotent Bin reconciliation after the MES request commits."""
    if not material_request.name:
        return

    item_warehouse_pairs = get_mes_material_request_item_warehouse_pairs(
        material_request, mr_item_rows
    )
    if not item_warehouse_pairs:
        return

    callback = lambda: enqueue_mes_material_request_bin_sync_job(
        material_request_name=material_request.name,
        item_warehouse_pairs=item_warehouse_pairs,
    )
    request = getattr(frappe.local, "request", None)
    if request and hasattr(request, "after_response"):
        # The parent transaction is committed before after_response callbacks run.
        request.after_response.add(callback)
    else:
        frappe.db.after_commit.add(callback)


def enqueue_mes_material_request_bin_sync_job(
    material_request_name, item_warehouse_pairs=None
):
    """Queue Bin reconciliation, with a synchronous fallback if Redis is unavailable."""
    kwargs = {
        "material_request_name": material_request_name,
        "item_warehouse_pairs": item_warehouse_pairs,
    }
    try:
        frappe.enqueue(
            "mes_integration.mes_integration.material_request.sync_material_request_bins",
            queue="short",
            timeout=300,
            job_id=f"mes-material-request-bin-sync:{material_request_name}",
            deduplicate=True,
            **kwargs,
        )
    except Exception:
        enqueue_error = frappe.get_traceback()
        try:
            sync_material_request_bins(**kwargs)
            # This callback runs after the API transaction has committed. Commit
            # the fallback's own transaction so the successful API is not left
            # with a stale Bin value when Redis is unavailable.
            frappe.db.commit()
        except Exception:
            enqueue_error += "\nFallback Bin sync failed:\n" + frappe.get_traceback()

        frappe.log_error(
            title="Failed to enqueue MES Material Request Bin sync",
            message=enqueue_error,
        )


def sync_material_request_bins(material_request_name, item_warehouse_pairs=None):
    """Recalculate Bin demand for a submitted MES request, safely repeatable."""
    if not material_request_name:
        return

    item_warehouse_pairs = normalize_mes_item_warehouse_pairs(item_warehouse_pairs)
    if not item_warehouse_pairs:
        rows = frappe.get_all(
            "Material Request Item",
            filters={"parent": material_request_name},
            fields=["item_code", "warehouse"],
            limit_page_length=0,
        )
        item_warehouse_pairs = get_mes_material_request_item_warehouse_pairs(
            {"items": rows}
        )

    item_warehouse_pairs = get_stock_item_warehouse_pairs(item_warehouse_pairs)
    if not item_warehouse_pairs:
        return

    company = frappe.db.get_value("Material Request", material_request_name, "company") or ""
    lock_data = {
        "company": company,
        "items": [
            {"item_code": item_code, "warehouse": warehouse}
            for item_code, warehouse in item_warehouse_pairs
        ],
    }

    try:
        with lock_mes_material_request_bins(lock_data):
            indented_qty_map = get_mes_indented_qty_map(item_warehouse_pairs)
            from erpnext.stock.stock_balance import update_bin_qty

            for item_code, warehouse in item_warehouse_pairs:
                update_bin_qty(
                    item_code,
                    warehouse,
                    {"indented_qty": indented_qty_map.get((item_code, warehouse), 0)},
                )
    except frappe.QueryDeadlockError as exc:
        raise frappe.RetryBackgroundJobError(
            "MES Material Request Bin sync encountered a deadlock"
        ) from exc


def normalize_mes_item_warehouse_pairs(item_warehouse_pairs):
    return sorted(
        {
            (pair[0], pair[1])
            for pair in item_warehouse_pairs or []
            if isinstance(pair, (list, tuple))
            and len(pair) == 2
            and pair[0]
            and pair[1]
        }
    )


def get_stock_item_warehouse_pairs(item_warehouse_pairs):
    item_codes = {item_code for item_code, _ in item_warehouse_pairs}
    if not item_codes:
        return []

    stock_item_codes = set(
        frappe.get_all(
            "Item",
            filters={"name": ["in", list(item_codes)], "is_stock_item": 1},
            pluck="name",
            limit_page_length=0,
        )
    )
    return [
        pair for pair in item_warehouse_pairs if pair[0] in stock_item_codes
    ]


def create_material_request_attempt(material_request_data, request_key=None, isolate_payload=False):
    # A failed insert/submit may mutate child document objects before the
    # transaction is rolled back. Isolate only retry attempts; the normal
    # success path avoids copying the complete large payload.
    document_data = deepcopy(material_request_data) if isolate_payload else material_request_data
    material_request_doc = frappe.get_doc(document_data)
    validate_mes_material_request_data(material_request_doc)
    material_request_doc.flags[MES_INTEGRATION_REQUEST_FLAG] = True

    mes_item_details = detach_mes_item_details(material_request_doc)
    material_request_doc.insert(
        set_name=build_mes_material_request_name(
            request_key=request_key,
            company=material_request_data.get("company"),
        )
    )
    validate_and_prepare_mes_item_details(material_request_doc, mes_item_details)
    insert_mes_item_details(mes_item_details)
    material_request_doc.set(MES_ITEM_DETAILS_FIELD, mes_item_details)
    material_request_doc.submit()
    return material_request_doc


def get_mes_idempotency_key(payload, material_request_data):
    request = getattr(frappe.local, "request", None)
    request_header = request.headers.get("X-Idempotency-Key") if request else None
    candidates = [request_header]
    candidates.extend(material_request_data.get(fieldname) for fieldname in MES_IDEMPOTENCY_KEY_FIELDS)
    if isinstance(payload, dict):
        candidates.extend(payload.get(fieldname) for fieldname in MES_IDEMPOTENCY_KEY_FIELDS)

    for candidate in candidates:
        if candidate is None:
            continue
        candidate = str(candidate).strip()
        if candidate:
            if len(candidate) > 140:
                frappe.throw(_("MES 幂等请求号长度不能超过 140 个字符。"))
            return candidate

    return None


def get_existing_material_request_name(company, request_key):
    if not company or not request_key:
        return None
    if not frappe.db.has_column("Material Request", "custom_material_request_no"):
        return None

    return frappe.db.get_value(
        "Material Request",
        {"company": company, "custom_material_request_no": request_key},
        "name",
        order_by="creation desc",
    )


def build_mes_material_request_name(request_key=None, company=None):
    if request_key:
        seed = f"{company or ''}\0{request_key}"
        suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    else:
        suffix = frappe.generate_hash(length=24)

    return f"MAT-MR-MES-{suffix}"


def set_material_request_response(material_request, reused=False):
    frappe.response["data"] = {
        "status": "success",
        "message": _("物料需求已存在并返回原单据。") if reused else _("物料需求已创建并提交。"),
        "material_request": material_request.name,
        "material_request_type": material_request.material_request_type,
        "material_request_docstatus": material_request.docstatus,
        "material_request_url": frappe.utils.get_url_to_form(
            "Material Request", material_request.name
        ),
        "idempotent_reuse": reused,
        "timestamp": now(),
    }


def detach_mes_item_details(material_request):
    """Keep MES detail validation, but postpone child-row inserts until after parent insert."""
    details = list(material_request.get(MES_ITEM_DETAILS_FIELD) or [])
    if details:
        material_request.flags.mes_item_detail_count = len(details)
        material_request.set(MES_ITEM_DETAILS_FIELD, [])

    return details


def validate_and_prepare_mes_item_details(material_request, details):
    """Validate MES detail rows and prepare them for a bulk insert."""
    if not details:
        return

    # The custom validation needs the submitted MR item names generated by insert().
    material_request.set(MES_ITEM_DETAILS_FIELD, details)
    validate_item_details(material_request)
    material_request._action = "save"

    for idx, detail in enumerate(details, start=1):
        detail.parent = material_request.name
        detail.parenttype = material_request.doctype
        detail.parentfield = MES_ITEM_DETAILS_FIELD
        detail.idx = idx
        detail.docstatus = 1
        detail.set("__islocal", True)
        detail.set_new_name()
        detail._action = "save"

    # The parent Item links were already validated by insert(). Detail Item
    # links are restricted to those parent rows, and UOM links are validated in
    # one query by validate_item_details(). Let the parent validate its child
    # rows in one pass; its child loop performs the same data/length checks as
    # detail._validate() without repeating parent-level setup 5000 times.
    material_request.set(MES_ITEM_DETAILS_FIELD, details)
    material_request._validate()
    material_request.set(MES_ITEM_DETAILS_FIELD, [])

    material_request.flags[MES_ITEM_DETAILS_VALIDATED_FLAG] = True
    material_request.set(MES_ITEM_DETAILS_FIELD, [])


def insert_mes_item_details(details):
    """Insert validated MES detail rows in batches before the MR is submitted.

    The child DocType has no hooks or controller logic. Validation is performed
    in validate_and_prepare_mes_item_details before using Frappe's bulk insert.
    """
    if details:
        bulk_insert(
            MES_ITEM_DETAIL_DOCTYPE,
            details,
            chunk_size=MES_DETAIL_BULK_CHUNK_SIZE,
        )
        for detail in details:
            if hasattr(detail, "__islocal"):
                delattr(detail, "__islocal")


def get_mes_indented_qty_map(item_warehouse_pairs):
    """Return the same indented quantities as get_indented_qty, in one query."""
    item_codes = {item_code for item_code, _ in item_warehouse_pairs}
    warehouses = {warehouse for _, warehouse in item_warehouse_pairs}
    request_item = frappe.qb.DocType("Material Request Item")
    material_request = frappe.qb.DocType("Material Request")
    outstanding_qty = request_item.stock_qty - request_item.ordered_qty
    material_request_types = (*MES_INWARD_MATERIAL_REQUEST_TYPES, "Material Issue")

    query = (
        frappe.qb.from_(request_item)
        .join(material_request)
        .on(request_item.parent == material_request.name)
        .select(
            request_item.item_code,
            request_item.warehouse,
            Sum(
                Case()
                .when(
                    material_request.material_request_type.isin(MES_INWARD_MATERIAL_REQUEST_TYPES),
                    outstanding_qty,
                )
                .else_(0)
            ).as_("inward_qty"),
            Sum(
                Case()
                .when(material_request.material_request_type == "Material Issue", outstanding_qty)
                .else_(0)
            ).as_("outward_qty"),
        )
        .where(
            (request_item.item_code.isin(item_codes))
            & (request_item.warehouse.isin(warehouses))
            & (material_request.material_request_type.isin(material_request_types))
            & (request_item.stock_qty > request_item.ordered_qty)
            & (material_request.status != "Stopped")
            & (material_request.docstatus == 1)
        )
        .groupby(request_item.item_code, request_item.warehouse)
    )

    requested_pairs = set(item_warehouse_pairs)
    return {
        (row.item_code, row.warehouse): flt(row.inward_qty) - flt(row.outward_qty)
        for row in query.run(as_dict=True)
        if (row.item_code, row.warehouse) in requested_pairs
    }


def get_mes_material_request_payload(data=None, material_request=None):
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    payload = parse_json_if_needed(data if data is not None else material_request)
    if isinstance(payload, dict):
        return payload

    if getattr(frappe, "request", None) and frappe.request.is_json:
        request_json = frappe.request.get_json(silent=True) or {}
        if isinstance(request_json, dict):
            if request_json.get("data") is not None:
                return parse_json_if_needed(request_json.get("data"))
            return request_json

    form_dict = getattr(frappe, "form_dict", None) or {}
    for fieldname in ("data", "material_request"):
        if form_dict.get(fieldname) is not None:
            return parse_json_if_needed(form_dict.get(fieldname))

    return {
        key: value
        for key, value in dict(form_dict).items()
        if key not in ("cmd", "method") and not key.startswith("_")
    }


def extract_material_request_data(payload):
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    if not isinstance(payload, dict):
        return payload

    if payload.get("material_request") is not None:
        return parse_json_if_needed(payload.get("material_request"))

    if payload.get("data") is not None:
        nested_payload = parse_json_if_needed(payload.get("data"))
        return extract_material_request_data(nested_payload)

    return payload


def validate_mes_material_request_permissions():
    for permission_type in ("create", "submit"):
        if not frappe.has_permission("Material Request", permission_type):
            frappe.throw(
                _("当前用户缺少 {0} 的 {1} 权限").format(
                    "Material Request", permission_type
                ),
                frappe.PermissionError,
            )


def validate_mes_material_request_data(material_request):
    if material_request.doctype != "Material Request":
        frappe.throw(_("只能通过此接口创建 Material Request"))

    if material_request.docstatus != 0:
        frappe.throw(_("MES 传入的物料需求必须是草稿状态"))

    if not material_request.get("material_request_type"):
        frappe.throw(_("缺少物料需求类型 material_request_type"))

    if not material_request.get("company"):
        frappe.throw(_("缺少物料需求公司"))

    if not material_request.get("items"):
        frappe.throw(_("物料需求至少需要一行明细"))

    for row in material_request.get("items"):
        if not row.get("item_code"):
            frappe.throw(_("第 {0} 行缺少物料号").format(row.idx))

        if flt(row.get("qty")) <= 0:
            frappe.throw(_("第 {0} 行数量必须大于 0").format(row.idx))


@frappe.whitelist()
def make_stock_entry_from_material_request(source_name, target_doc=None):
    material_request_type = frappe.db.get_value("Material Request", source_name, "material_request_type")

    if material_request_type in CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES:
        return make_issue_stock_entry(source_name, target_doc)

    from erpnext.stock.doctype.material_request.material_request import make_stock_entry

    return make_stock_entry(source_name, target_doc)


@frappe.whitelist()
def make_issue_stock_entry(source_name, target_doc=None):
    def update_item(source, target, source_parent):
        qty = (
            flt(flt(source.stock_qty) - flt(source.ordered_qty)) / target.conversion_factor
            if flt(source.stock_qty) > flt(source.ordered_qty)
            else 0
        )
        stock_entry_purpose = get_stock_entry_purpose(source_parent)
        target.qty = qty
        target.transfer_qty = qty * source.conversion_factor
        target.conversion_factor = source.conversion_factor

        if stock_entry_purpose == "Material Issue":
            target.s_warehouse = source.get("warehouse") or source_parent.get("set_warehouse")
        else:
            target.s_warehouse = source.get("from_warehouse") or source_parent.get("set_from_warehouse")
            target.t_warehouse = source_parent.get("set_warehouse") or source.get("warehouse")

    def set_missing_values(source, target):
        stock_entry_purpose = get_stock_entry_purpose(source)
        target.purpose = stock_entry_purpose
        target.stock_entry_type = get_stock_entry_type(source)
        if stock_entry_purpose == "Material Issue":
            target.from_warehouse = (
                source.get("set_warehouse")
                or get_single_material_request_item_source_warehouse(source)
            )
        else:
            target.from_warehouse = source.get("set_from_warehouse")
            target.to_warehouse = source.get("set_warehouse")
        target.set_transfer_qty()
        target.set_actual_qty()
        target.calculate_rate_and_amount(raise_error_if_no_rate=False)
        target.set_job_card_data()

    return get_mapped_doc(
        "Material Request",
        source_name,
        {
            "Material Request": {
                "doctype": "Stock Entry",
                "validation": {
                    "docstatus": ["=", 1],
                    "material_request_type": ["in", CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES],
                },
            },
            "Material Request Item": {
                "doctype": "Stock Entry Detail",
                "field_map": {
                    "name": "material_request_item",
                    "parent": "material_request",
                    "uom": "stock_uom",
                    "job_card_item": "job_card_item",
                },
                "field_no_map": ["expense_account"],
                "postprocess": update_item,
                "condition": lambda doc: (
                    flt(doc.ordered_qty, doc.precision("ordered_qty"))
                    < flt(doc.stock_qty, doc.precision("ordered_qty"))
                ),
            },
        },
        target_doc,
        set_missing_values,
    )


def get_stock_entry_purpose(material_request):
    if material_request.material_request_type in ("Material Issue", "Injection Molding Issuance"):
        return "Material Issue"

    return "Material Transfer for Manufacture"


def get_stock_entry_type(material_request):
    if material_request.material_request_type == "Injection Molding Issuance":
        return "Injection Molding Issuance"

    return get_stock_entry_purpose(material_request)


def get_single_material_request_item_source_warehouse(material_request):
    warehouses = {
        row.get("from_warehouse") or row.get("warehouse")
        for row in material_request.get("items", [])
        if row.get("from_warehouse") or row.get("warehouse")
    }

    return warehouses.pop() if len(warehouses) == 1 else None


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def issue_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
    filters = filters or {}
    item_code = filters.get("item_code")
    company = filters.get("company")

    if not item_code:
        return []

    from frappe.desk.reportview import get_match_cond

    return frappe.db.sql(
        """
        SELECT
            warehouse.name,
            CONCAT_WS(' : ', 'Actual Qty', IFNULL(ROUND(bin.actual_qty, 2), 0)) AS actual_qty
        FROM `tabWarehouse` warehouse
        LEFT JOIN `tabBin` bin
            ON bin.warehouse = warehouse.name
            AND bin.item_code = %(item_code)s
        WHERE warehouse.is_group = 0
            AND IFNULL(warehouse.disabled, 0) = 0
            AND (%(company)s IS NULL OR %(company)s = '' OR IFNULL(warehouse.company, '') IN ('', %(company)s))
            AND warehouse.name LIKE %(txt)s
            {mcond}
        ORDER BY IFNULL(bin.actual_qty, 0) DESC, warehouse.name ASC
        LIMIT %(page_len)s OFFSET %(start)s
        """.format(mcond=get_match_cond("Warehouse")),
        {
            "item_code": item_code,
            "company": company,
            "txt": f"%{txt}%",
            "page_len": page_len,
            "start": start,
        },
    )


@frappe.whitelist()
def get_item_warehouse_actual_qty(item_code, warehouse):
    if not item_code or not warehouse:
        return 0

    return flt(
        frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "actual_qty",
        )
    )


@frappe.whitelist()
def get_issue_dialog_default_uoms(item_codes=None):
    """Return configured MES default issue UOMs for the Material Request issue dialog."""
    from erpnext.stock.get_item_details import get_conversion_factor
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    if not frappe.db.has_column("Item", "custom_mes_issue_uom"):
        return {"default_uoms": {}, "warnings": []}

    item_codes = parse_json_if_needed(item_codes)
    if not isinstance(item_codes, list):
        return {"default_uoms": {}, "warnings": []}

    item_codes = list(dict.fromkeys(item_code for item_code in item_codes if item_code))
    if not item_codes:
        return {"default_uoms": {}, "warnings": []}

    items = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "custom_mes_issue_uom"],
    )

    default_uoms = {}
    warnings = []
    for item in items:
        uom = item.get("custom_mes_issue_uom")
        if not uom:
            continue

        conversion_factor = 0
        try:
            conversion_factor = flt(get_conversion_factor(item.name, uom).get("conversion_factor"))
        except Exception:
            conversion_factor = 0

        if conversion_factor:
            default_uoms[item.name] = {
                "uom": uom,
                "conversion_factor": conversion_factor,
            }
        else:
            warnings.append(
                _("物料 {0} 的 MES 默认发料单位 {1} 缺少有效换算设置，已使用物料需求单位。").format(
                    item.name,
                    uom,
                )
            )

    return {"default_uoms": default_uoms, "warnings": warnings}


@frappe.whitelist()
def issue_and_push_to_dlm_from_dialog(material_request_name, items=None):
    """Create, submit and push a Stock Entry from editable Material Request issue rows."""
    from mes_integration.mes_integration.stock_entry import push_to_mes

    lock_material_request_for_issue(material_request_name)

    mr = frappe.get_doc("Material Request", material_request_name)
    if not is_mes_integration_enabled(mr.get("company")):
        throw_mes_integration_disabled(mr.get("company"))
    validate_material_request_can_issue_to_dlm(mr)

    issue_rows = get_issue_dialog_rows(items)
    stock_entry = build_stock_entry_from_material_request_issue_rows(mr, issue_rows)
    stock_entry.insert()
    stock_entry.submit()

    try:
        push_result = push_to_mes(stock_entry.name)
    except Exception:
        frappe.log_error(title="DLM 推送失败（弹窗发料并推送）", message=frappe.get_traceback())
        return {
            "status": "partial",
            "message": _("物料移动 {0} 已创建并提交，但推送至 DLM 失败，请手动推送。").format(
                stock_entry.name
            ),
            "material_request": mr.name,
            "stock_entry": stock_entry.name,
        }

    return {
        "status": "success",
        "message": _("物料移动 {0} 已创建、提交并推送至 DLM。").format(stock_entry.name),
        "material_request": mr.name,
        "stock_entry": stock_entry.name,
        "push_result": push_result,
    }


def lock_material_request_for_issue(material_request_name):
    frappe.db.sql(
        "SELECT name FROM `tabMaterial Request` WHERE name = %s FOR UPDATE",
        material_request_name,
    )
    frappe.db.sql(
        "SELECT name FROM `tabMaterial Request Item` WHERE parent = %s FOR UPDATE",
        material_request_name,
    )


def validate_material_request_can_issue_to_dlm(mr):
    if mr.docstatus != 1:
        frappe.throw(_("物料需求必须已提交"))

    if mr.status in ("Stopped", "Cancelled"):
        frappe.throw(_("已停止或已取消的物料需求不能发料"))

    if mr.material_request_type not in CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES:
        frappe.throw(_("只有物料发料、工单发料、注塑发料可以发料并推送至 DLM"))


def get_issue_dialog_rows(items):
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    rows = parse_json_if_needed(items)
    if not isinstance(rows, list):
        frappe.throw(_("缺少发料明细或发料明细格式不正确"))

    return [row for row in rows if isinstance(row, dict) and flt(row.get("qty")) > 0]


def build_stock_entry_from_material_request_issue_rows(mr, issue_rows):
    if not issue_rows:
        frappe.throw(_("没有可发料的明细"))

    mr_items = {row.name: row for row in mr.get("items", [])}
    real_time_issued_stock_qty = get_realtime_issued_stock_qty_by_mr_item(mr_items.keys())
    validate_issue_dialog_rows_not_duplicated(issue_rows)
    validate_issue_dialog_stock_availability(issue_rows, mr_items)

    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.company = mr.company
    stock_entry.stock_entry_type = get_stock_entry_type(mr)
    stock_entry.purpose = get_stock_entry_purpose(mr)
    stock_entry.custom_stock_entry_no = mr.get("custom_stock_entry_no")
    stock_entry.from_warehouse = get_stock_entry_source_warehouse(mr, issue_rows, mr_items)
    if stock_entry.purpose != "Material Issue":
        stock_entry.to_warehouse = get_stock_entry_target_warehouse(mr, issue_rows, mr_items)

    for index, issue_row in enumerate(issue_rows, start=1):
        mr_item = validate_issue_dialog_row(mr, mr_items, issue_row, index, real_time_issued_stock_qty)
        qty = flt(issue_row.get("qty"))
        uom = get_issue_dialog_row_uom(issue_row, mr_item)
        conversion_factor = get_issue_dialog_row_conversion_factor(mr_item, uom)
        stock_entry.append(
            "items",
            {
                "item_code": mr_item.item_code,
                "item_name": mr_item.get("item_name"),
                "description": mr_item.get("description"),
                "qty": qty,
                "transfer_qty": qty * conversion_factor,
                "uom": uom,
                "stock_uom": mr_item.get("stock_uom"),
                "conversion_factor": conversion_factor,
                "s_warehouse": issue_row.get("s_warehouse"),
                "t_warehouse": issue_row.get("t_warehouse") if stock_entry.purpose != "Material Issue" else None,
                "material_request": mr.name,
                "material_request_item": mr_item.name,
                "allow_zero_valuation_rate": 1,
            },
        )

    stock_entry.set_transfer_qty()
    stock_entry.set_actual_qty()
    stock_entry.calculate_rate_and_amount(raise_error_if_no_rate=False)
    stock_entry.set_job_card_data()
    return stock_entry


def validate_issue_dialog_row(mr, mr_items, issue_row, index, real_time_issued_stock_qty=None):
    mr_item_name = issue_row.get("material_request_item")
    if not mr_item_name or mr_item_name not in mr_items:
        frappe.throw(_("第 {0} 行物料需求明细不存在或不属于当前物料需求").format(index))

    mr_item = mr_items[mr_item_name]
    if issue_row.get("item_code") and issue_row.get("item_code") != mr_item.item_code:
        frappe.throw(_("第 {0} 行物料编码与物料需求明细不一致").format(index))

    qty = flt(issue_row.get("qty"))
    if qty <= 0:
        frappe.throw(_("第 {0} 行本次发料数量必须大于 0").format(index))

    uom = get_issue_dialog_row_uom(issue_row, mr_item)
    conversion_factor = get_issue_dialog_row_conversion_factor(mr_item, uom)
    remaining_stock_qty = get_material_request_item_remaining_stock_qty(
        mr_item,
        real_time_issued_stock_qty,
    )
    issue_stock_qty = qty * conversion_factor
    max_issue_stock_qty = get_issue_dialog_max_issue_stock_qty(remaining_stock_qty, conversion_factor)
    if issue_stock_qty > max_issue_stock_qty:
        remaining_qty = flt(max_issue_stock_qty / conversion_factor)
        frappe.throw(
            _("第 {0} 行本次发料数量 {1} 超过剩余数量 {2}").format(
                index,
                qty,
                remaining_qty,
            )
        )

    if not issue_row.get("s_warehouse"):
        frappe.throw(_("第 {0} 行缺少发料仓").format(index))

    if get_stock_entry_purpose(mr) != "Material Issue" and not issue_row.get("t_warehouse"):
        frappe.throw(_("第 {0} 行缺少目标仓库").format(index))

    return mr_item


def validate_issue_dialog_rows_not_duplicated(issue_rows):
    seen = set()
    for row in issue_rows:
        mr_item_name = row.get("material_request_item")
        if not mr_item_name:
            continue

        if mr_item_name in seen:
            frappe.throw(_("物料需求明细 {0} 在本次发料中重复").format(mr_item_name))

        seen.add(mr_item_name)


def validate_issue_dialog_stock_availability(issue_rows, mr_items):
    requested_stock_qty_by_item_warehouse = {}
    row_indexes_by_item_warehouse = {}

    for index, row in enumerate(issue_rows, start=1):
        mr_item = mr_items.get(row.get("material_request_item"))
        if not mr_item or not row.get("s_warehouse"):
            continue

        uom = get_issue_dialog_row_uom(row, mr_item)
        conversion_factor = get_issue_dialog_row_conversion_factor(mr_item, uom)
        key = (mr_item.item_code, row.get("s_warehouse"))
        requested_stock_qty_by_item_warehouse[key] = flt(
            requested_stock_qty_by_item_warehouse.get(key)
        ) + flt(row.get("qty")) * conversion_factor
        row_indexes_by_item_warehouse.setdefault(key, []).append(index)

    for (item_code, warehouse), requested_stock_qty in requested_stock_qty_by_item_warehouse.items():
        actual_qty = get_item_warehouse_actual_qty(item_code, warehouse)
        if requested_stock_qty > actual_qty:
            frappe.throw(
                _("第 {0} 行物料 {1} 发料数量 {2} 超过仓库 {3} 实际数量 {4}").format(
                    ", ".join(str(row_index) for row_index in row_indexes_by_item_warehouse[(item_code, warehouse)]),
                    item_code,
                    flt(requested_stock_qty),
                    warehouse,
                    flt(actual_qty),
                )
            )


def get_realtime_issued_stock_qty_by_mr_item(mr_item_names):
    mr_item_names = tuple(mr_item_names or [])
    if not mr_item_names:
        return {}

    placeholders = ", ".join(["%s"] * len(mr_item_names))
    rows = frappe.db.sql(
        f"""
        SELECT
            sed.material_request_item,
            SUM(
                CASE
                    WHEN IFNULL(se.is_return, 0) = 1 THEN -IFNULL(sed.transfer_qty, 0)
                    ELSE IFNULL(sed.transfer_qty, 0)
                END
            ) AS issued_stock_qty
        FROM `tabStock Entry Detail` sed
        INNER JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE sed.material_request_item IN ({placeholders})
            AND sed.docstatus = 1
            AND se.docstatus = 1
            AND IFNULL(sed.s_warehouse, '') != ''
        GROUP BY sed.material_request_item
        """,
        mr_item_names,
        as_dict=True,
    )

    return {row.material_request_item: flt(row.issued_stock_qty) for row in rows}


def get_material_request_item_remaining_qty(
    mr_item,
    real_time_issued_stock_qty=None,
    conversion_factor=None,
):
    conversion_factor = flt(conversion_factor) or flt(mr_item.get("conversion_factor")) or 1
    remaining_stock_qty = get_material_request_item_remaining_stock_qty(
        mr_item,
        real_time_issued_stock_qty,
    )
    return flt(remaining_stock_qty / conversion_factor)


def get_material_request_item_remaining_stock_qty(mr_item, real_time_issued_stock_qty=None):
    conversion_factor = flt(mr_item.get("conversion_factor")) or 1
    requested_stock_qty = flt(mr_item.get("stock_qty")) or flt(mr_item.get("qty")) * conversion_factor

    if real_time_issued_stock_qty is not None:
        issued_stock_qty = flt(real_time_issued_stock_qty.get(mr_item.name))
    else:
        issued_stock_qty = flt(mr_item.get("custom_transferred_qty") or mr_item.get("ordered_qty"))

    return max(requested_stock_qty - issued_stock_qty, 0)


def get_issue_dialog_max_issue_stock_qty(remaining_stock_qty, conversion_factor):
    remaining_stock_qty = flt(remaining_stock_qty)
    conversion_factor = flt(conversion_factor) or 1
    if remaining_stock_qty <= 0:
        return 0

    return ceil(remaining_stock_qty / conversion_factor) * conversion_factor


def get_issue_dialog_row_uom(issue_row, mr_item):
    return issue_row.get("uom") or mr_item.get("uom") or mr_item.get("stock_uom")


def get_issue_dialog_row_conversion_factor(mr_item, uom):
    from erpnext.stock.get_item_details import get_conversion_factor

    conversion_factor = flt(get_conversion_factor(mr_item.item_code, uom).get("conversion_factor"))
    if not conversion_factor:
        frappe.throw(
            _("物料 {0} 缺少单位 {1} 的换算设置").format(mr_item.item_code, uom)
        )

    return conversion_factor


def get_stock_entry_source_warehouse(mr, issue_rows, mr_items):
    warehouses = {
        row.get("s_warehouse")
        for row in issue_rows
        if row.get("s_warehouse") and row.get("material_request_item") in mr_items
    }
    return next(iter(warehouses)) if len(warehouses) == 1 else None


def get_stock_entry_target_warehouse(mr, issue_rows, mr_items):
    warehouses = {
        row.get("t_warehouse")
        for row in issue_rows
        if row.get("t_warehouse") and row.get("material_request_item") in mr_items
    }
    if len(warehouses) == 1:
        return next(iter(warehouses))

    return mr.get("set_warehouse")


@frappe.whitelist()
def submit_issue_and_push_to_dlm(material_request_name):
    """
    一键操作：提交物料需求 → 发料出库 → 提交出库单 → 推送至 DLM。

    步骤 1-3 在同一事务中，任一失败则全部回滚。
    步骤 4 (push_to_mes) 内部会独立 commit，推送失败时 Stock Entry 仍已提交，
    返回 partial 状态提示用户手动推送。
    """
    mr = frappe.get_doc("Material Request", material_request_name)
    if not is_mes_integration_enabled(mr.get("company")):
        throw_mes_integration_disabled(mr.get("company"))

    if mr.docstatus != 0:
        frappe.throw(_("物料需求必须是草稿状态"))

    # Step 1: 提交物料需求
    mr.submit()

    # Step 2: 创建发料出库单（基于已提交的物料需求映射）
    stock_entry = make_issue_stock_entry(mr.name)
    stock_entry.insert()

    # Step 3: 提交出库单
    stock_entry.submit()

    # Step 4: 推送至 DLM
    # push_to_mes 内部在 HTTP 失败时会 frappe.db.commit() 再 raise，
    # 因此捕获异常，将推送失败视为非致命错误（出库单已提交但未推送）。
    from mes_integration.mes_integration.stock_entry import push_to_mes

    try:
        push_result = push_to_mes(stock_entry.name)
    except Exception:
        frappe.log_error(title="DLM 推送失败（发料并推送）", message=frappe.get_traceback())
        return {
            "status": "partial",
            "message": _("物料需求已提交，出库单 {0} 已创建并提交，但推送至 DLM 失败，请手动推送。").format(
                stock_entry.name
            ),
            "material_request": mr.name,
            "stock_entry": stock_entry.name,
        }

    return {
        "status": "success",
        "message": _("物料需求已提交，出库单 {0} 已创建、提交并推送至 DLM。").format(stock_entry.name),
        "material_request": mr.name,
        "stock_entry": stock_entry.name,
        "push_result": push_result,
    }


@frappe.whitelist()
def batch_issue_and_push_to_dlm(material_requests=None, items=None):
    """Issue and push submitted, partially unissued Material Requests one by one."""
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    names = parse_json_if_needed(material_requests)
    grouped_items = parse_json_if_needed(items) if items else {}
    if not isinstance(names, list) or not names:
        frappe.throw(_("请选择至少一个物料需求。"))

    results = []
    for index, name in enumerate(dict.fromkeys(names), start=1):
        savepoint = f"batch_material_request_{index}"
        try:
            frappe.db.savepoint(savepoint)
            mr = frappe.get_doc("Material Request", name)
            validate_batch_issue_material_request(mr)
            issue_rows = grouped_items.get(mr.name) if isinstance(grouped_items, dict) else None
            result = issue_and_push_to_dlm_from_dialog(mr.name, issue_rows or build_batch_issue_rows(mr))
            results.append({"material_request": mr.name, **result})
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            results.append(
                {
                    "material_request": name,
                    "status": "failed",
                    "message": frappe.get_exception_message(),
                }
            )

    return {
        "status": "success" if all(row["status"] == "success" for row in results) else "partial",
        "results": results,
    }


def validate_batch_issue_material_request(mr):
    if mr.docstatus != 1:
        frappe.throw(_("物料需求 {0} 必须已提交。").format(mr.name))
    if mr.per_ordered >= 100:
        frappe.throw(_("物料需求 {0} 已发料完成。").format(mr.name))


def build_batch_issue_rows(mr):
    issue_rows = []
    for row in mr.items:
        conversion_factor = flt(row.conversion_factor) or 1
        remaining_stock_qty = max(flt(row.stock_qty) - flt(row.ordered_qty), 0)
        if remaining_stock_qty <= 0:
            continue

        issue_rows.append(
            {
                "material_request_item": row.name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "uom": row.uom or row.stock_uom,
                "request_uom": row.uom or row.stock_uom,
                "stock_uom": row.stock_uom or row.uom,
                "conversion_factor": conversion_factor,
                "qty": remaining_stock_qty / conversion_factor,
                "s_warehouse": row.from_warehouse or row.warehouse or mr.set_from_warehouse or mr.set_warehouse,
                "t_warehouse": row.warehouse or mr.set_warehouse,
            }
        )

    if not issue_rows:
        frappe.throw(_("物料需求 {0} 没有可发料的明细。").format(mr.name))
    return issue_rows


def validate_item_details(doc, method=None):
    if not is_mes_integration_enabled(doc.get("company")):
        return

    if doc.flags.get(MES_ITEM_DETAILS_VALIDATED_FLAG):
        return

    details = doc.get("custom_item_details") or []
    if not details:
        return

    item_rows_by_idx = {cint(row.idx): row for row in doc.get("items") if row.idx}
    item_rows_by_code = {row.item_code: row for row in doc.get("items") if row.item_code}
    item_codes = {row.item_code for row in doc.get("items") if row.item_code}
    detail_uom_by_item = {
        row.item_code: row.get("stock_uom")
        for row in item_rows_by_code.values()
        if row.get("stock_uom")
    }
    missing_item_uoms = {
        detail.item_code
        for detail in details
        if detail.item_code in item_codes
        and not detail.material_request_item_idx
        and not detail.get("uom")
        and detail.item_code not in detail_uom_by_item
    }
    if missing_item_uoms:
        detail_uom_by_item.update(get_detail_uom_by_item(details, missing_item_uoms))

    for detail in details:
        if flt(detail.order_qty) < 0:
            frappe.throw(_("Row {0}: Order Qty cannot be negative").format(detail.idx))

        if flt(detail.issue_qty) < 0:
            frappe.throw(_("Row {0}: Issue Qty cannot be negative").format(detail.idx))

        if detail.material_request_item_idx:
            item_row = item_rows_by_idx.get(cint(detail.material_request_item_idx))

            if not item_row:
                frappe.throw(
                    _("Row {0}: Material Request Item Row {1} does not exist").format(
                        detail.idx, detail.material_request_item_idx
                    )
                )

            if detail.item_code and detail.item_code != item_row.item_code:
                frappe.throw(
                    _("Row {0}: Item Code must match Material Request Item Row {1}").format(
                        detail.idx, detail.material_request_item_idx
                    )
                )

            detail.item_code = item_row.item_code
            detail.item_name = item_row.item_name
            detail.uom = detail.get("uom") or item_row.get("uom") or item_row.get("stock_uom")
            detail.material_request_item = item_row.name
        elif detail.item_code not in item_codes:
            frappe.throw(
                _("Row {0}: Item Code {1} is not in this Material Request").format(
                    detail.idx, detail.item_code
                )
            )
        else:
            item_row = item_rows_by_code.get(detail.item_code)
            if item_row:
                detail.item_name = item_row.item_name
            if not detail.get("uom") and detail.item_code:
                detail.uom = detail_uom_by_item.get(detail.item_code) or (
                    item_row.get("stock_uom") if item_row else None
                )

    validate_mes_item_detail_uoms(details)


def validate_mes_item_detail_uoms(details):
    uoms = {detail.get("uom") for detail in details if detail.get("uom")}
    if not uoms:
        return

    valid_uoms = set(
        frappe.get_all(
            "UOM",
            filters={"name": ["in", list(uoms)]},
            pluck="name",
            limit_page_length=0,
        )
    )
    for detail in details:
        if detail.get("uom") and detail.uom not in valid_uoms:
            frappe.throw(
                _("Could not find UOM {0} in row {1}").format(detail.uom, detail.idx),
                frappe.LinkValidationError,
            )


def get_detail_uom_by_item(details, item_codes):
    item_codes_requiring_uom = {
        detail.item_code
        for detail in details
        if detail.item_code in item_codes
        and not detail.material_request_item_idx
        and not detail.get("uom")
    }
    if not item_codes_requiring_uom:
        return {}

    return {
        row.name: row.stock_uom
        for row in frappe.get_all(
            "Item",
            filters={"name": ["in", list(item_codes_requiring_uom)]},
            fields=["name", "stock_uom"],
            limit_page_length=0,
        )
    }
