"""Audited ERP payment registration, never a transfer or accounting submission.

The cashier owns history until it atomically freezes a logical application root.
Thereafter history is immutable and local records are summed once under a source
row lock. Batch list overlay is O(N + P), with no upstream requests per row.
"""
import json
import os
from collections import defaultdict

import frappe
from frappe.utils import now_datetime

from . import operating_expenses as expenses
from .operating_expense_contract import digest, expense_facts, payment_facts, identifier, money
from .operating_payment_contract import balance, registration
from .purchase_payment_service import _require_fields

TAKEOVER = "Operating Expense Takeover"
PAYMENT = "Operating Expense Payment"
PAYMENT_FIELDS = ["name", "source", "company", "status", "payment_date", "currency", "amount", "bank_currency", "bank_amount", "bank_account", "party_type", "party", "bank_reference", "remark", "registered_by", "reversal_reason", "reversed_by", "reversed_at"]
CLAIM_PATH = "/api/integrations/erp/operating-expenses/"


def _checked(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (ValueError, TypeError, KeyError) as error:
        frappe.throw(str(error))


def _takeover(doc, for_update=False):
    if not frappe.db.get_value(TAKEOVER, doc.name, "name", for_update=for_update):
        return None
    record = expenses._read(TAKEOVER, doc.name, {"source", "company"}, for_update=for_update)
    if record.source != doc.name or record.company != doc.company:
        frappe.throw("付款接管公司或申请关联不符，请管理员核查")
    return record


def _records(doc, for_update=False):
    _require_fields(PAYMENT, set(PAYMENT_FIELDS))
    filters={"source":doc.name}
    if for_update:
        # The source lock serializes writers, but a pre-lock REPEATABLE-READ
        # snapshot can still hide another writer's commit. Use current reads
        # without dropping native list/party/company/field permissions.
        rows=frappe.get_list(PAYMENT,filters=filters,fields=PAYMENT_FIELDS,order_by="creation asc, name asc",limit_page_length=0,run=False).for_update().run(as_dict=True)
        total=len(frappe.get_all(PAYMENT,filters=filters,fields=["name"],limit_page_length=0,run=False).for_update().run(pluck=True))
    else:
        rows=frappe.get_list(PAYMENT,filters=filters,fields=PAYMENT_FIELDS,order_by="creation asc, name asc",limit_page_length=0)
        total=frappe.db.count(PAYMENT,filters)
    rows=[dict(row) for row in rows]
    if len(rows) != total or any(row["company"] != doc.company for row in rows):
        raise ValueError("本申请存在不可读取或公司不符的付款，余额待核对，不能登记新付款")
    return rows


def _history(record):
    return json.loads(record.history_json)


def payment_context(doc, item=None, for_update=False):
    """Load one authorized source's immutable history and local records once."""
    record = _takeover(doc,for_update=for_update)
    if not record:
        return {"record": None, "records": [], "history": None, "balance": None,
                "notice": "历史付款尚未接管，新付款登记未开放"}
    context = {"record": record, "records": [], "history": None, "balance": None}
    try:
        records = _records(doc,for_update=for_update)
        context["records"] = records
        history = _history(record)
        context["history"] = history
        if record.expense_fingerprint != digest(expense_facts(item if item is not None else json.loads(doc.source_json))):
            raise ValueError("接管后的申请财务事实已变化，请管理员复核；既有付款不会删除")
        context["balance"] = balance(history, records)
    except (ValueError, TypeError, KeyError) as error:
        context["notice"] = str(error)
    return context


def payment_detail(doc, context=None, for_update=False):
    context = context if context is not None else payment_context(doc,for_update=for_update)
    record = context["record"]
    if not record:
        return {"managed": False, "balance": None, "payments": [], "notice": context["notice"]}
    records = context["records"]
    proofs = defaultdict(list)
    advances = set()
    if records:
        _require_fields("File", {"name", "file_name", "is_private", "attached_to_doctype", "attached_to_name"})
        for file in frappe.get_all("File", filters={"attached_to_doctype": PAYMENT, "attached_to_name": ["in", [row["name"] for row in records]], "is_private": 1}, fields=["name", "file_name", "attached_to_name"]):
            proofs[file.attached_to_name].append({"name": file.name, "filename": file.file_name})
        for row in frappe.get_all(PAYMENT, filters={"name": ["in", [row["name"] for row in records]], "source": doc.name}, fields=["name", "terms_json"]):
            try:
                if json.loads(row.terms_json).get("advance_account"):
                    advances.add(row.name)
            except (ValueError, TypeError):
                pass
    for row in records:
        row["proofs"] = proofs[row["name"]]
        row["proof_status"] = "回单已上传" if row["proofs"] else "回单待补"
        row["advance_configured"] = row["name"] in advances
    return {"managed": True, "balance": context["balance"], "payments": records, "notice": context.get("notice"),
            "claimed_at": str(record.claimed_at or ""), "claimed_by": record.claimed_by}


def merge_source(doc, item, context=None):
    """Apply local payments without changing source expense/approval facts."""
    context = context if context is not None else payment_context(doc, item)
    if not context["record"]:
        return item
    history, records = context["history"], context["records"]
    item = dict(item)
    item.update(context["balance"] or {"paid_amount": None, "pending_amount": None, "source_status": "付款待核对"})
    item["payment_evidence_status"] = "recorded" if context["balance"] else "unknown"
    item["payments"] = list(history.get("payments", [])) if isinstance(history, dict) and isinstance(history.get("payments"), list) else []
    item["payments"] += [
        {"source_id": "erp-payment:" + row["name"], "amount": row["amount"], "currency": row["currency"], "payment_date": str(row["payment_date"]),
         "payment_account": row["bank_account"], "bank_reference": row["bank_reference"], "remark": row["remark"], "payer": row["registered_by"],
         "evidence_status": "recorded", "source_type": "erp", "version": row["name"]}
        for row in records if row["status"] == "Registered"
    ]
    return item


def overlay_rows(rows):
    """Company/field-scoped batch lookup before filtering, totals and pagination."""
    if not rows or not frappe.db.exists("DocType", TAKEOVER):
        return
    names = [row["name"] for row in rows]
    _require_fields(TAKEOVER, {"source", "company"})
    _require_fields(PAYMENT, {"source", "company", "name", "amount", "status"})
    claims = {row.source: row for row in frappe.get_list(TAKEOVER, filters={"source": ["in", names]}, fields=["source", "company", "name"], limit_page_length=0)}
    if not claims:
        return
    # Only hydrate hidden history for authorized parent projections.
    histories = {row.name: row for row in frappe.get_all(TAKEOVER, filters={"name": ["in", list(claims)]}, fields=["name", "history_json", "expense_fingerprint"], limit_page_length=0)}
    facts = {row.name: row.source_json for row in frappe.get_all(expenses.SOURCE, filters={"name": ["in", list(claims)]}, fields=["name", "source_json"], limit_page_length=0)}
    payments = defaultdict(list)
    all_counts = defaultdict(int)
    for row in frappe.get_all(PAYMENT, filters={"source": ["in", list(claims)]}, fields=["source"]):
        all_counts[row.source] += 1
    for row in frappe.get_list(PAYMENT, filters={"source": ["in", list(claims)]}, fields=["source", "company", "name", "amount", "status"], limit_page_length=0):
        if row.company == claims[row.source].company:
            payments[row.source].append(dict(row))
    for row in rows:
        claim = claims.get(row["name"])
        if not claim or claim.company != row["company"]:
            continue
        row["erp_payment_managed"] = True
        try:
            history = histories[row["name"]]
            if len(payments[row["name"]]) != all_counts[row["name"]]:
                raise ValueError("存在不可读取的付款")
            if history.expense_fingerprint != digest(expense_facts(json.loads(facts[row["name"]]))):
                raise ValueError("申请事实已变化")
            row.update(balance(json.loads(history.history_json), payments[row["name"]]))
        except (ValueError, TypeError, KeyError):
            row.update(paid_amount=None, pending_amount=None, source_status="付款待核对")


def _fresh_base(doc):
    item = expenses._fresh(doc, include_payments=False)
    # Approval withdrawal always stops new registration; posted payments remain.
    if not doc.company or item.get("approvals", {}).get("eligibility") != "eligible" or item.get("source_conflict") or item.get("currency_conflict"):
        frappe.throw("申请审批、公司或来源事实待核对，不能登记付款")
    issues = expenses._issues(item,{"application_type":doc.effective_application_type})
    if issues:
        frappe.throw("；".join(issues))
    return item


def _root(item):
    root = item.get("cashier_source_id") or (item.get("source_id") if item.get("source_system") == "cashier-payment-archive" else None)
    if not root:
        frappe.throw("尚未找到唯一出纳申请及完整付款历史，请先同步并核对")
    return identifier(root)


def _source_match(item, history, root):
    if (history.get("source_id") != root or history.get("currency") != item.get("currency")
            or money(history.get("amount")) != money(item.get("amount"))):
        frappe.throw("出纳历史与本申请身份、币种或金额不一致，请先核对")
    _checked(balance, history, [])


def _confirmation(value):
    if value not in (True, False, 1, 0, "true", "false", "1", "0"):
        frappe.throw("确认值无效")
    return value in (True, 1, "true", "1")


@frappe.whitelist(methods=["POST"])
def preview_takeover(source_id, zero_history_confirmed=False):
    expenses._finance()
    doc = expenses._source(source_id)
    existing = _takeover(doc)
    if existing:
        return {"existing": True, **payment_detail(doc)}
    item = _fresh_base(doc)
    root = _root(item)
    confirmed = _confirmation(zero_history_confirmed)
    response = expenses._request(CLAIM_PATH + "takeover-preview", data={"source_id": root, "zero_history_confirmed": confirmed, "confirmed_by": frappe.session.user if confirmed else None})
    if len(response["items"]) != 1:
        frappe.throw("付款历史返回不唯一")
    history = response["items"][0]
    _source_match(item, history, root)
    return {"existing": False, "source_version": item["version"], "history_version": history["version"],
            "balance": _checked(balance, history, []), "history_count": len(history["payments"]), "currency": item["currency"]}


@frappe.whitelist(methods=["POST"])
def claim_takeover(source_id, expected_source_version, expected_history_version, request_id, zero_history_confirmed=False):
    expenses._finance()
    doc = expenses._source(source_id, write=True)
    if _takeover(doc,for_update=True):
        return {"existing": True, **payment_detail(doc,for_update=True)}
    item = _fresh_base(doc)
    if item["version"] != expected_source_version:
        frappe.throw("申请事实已变化，请重新预览")
    root = _root(item)
    identifier(request_id)
    # Stable identity lets a retry recover a successful upstream lock even if our
    # transaction failed after the HTTP response. Never automatically unlock.
    claim_request = digest([frappe.local.site, doc.name, "cashier-takeover"])
    confirmed = _confirmation(zero_history_confirmed)
    response = expenses._request(CLAIM_PATH + "takeover-claim", data={"source_id": root, "expected_version": expected_history_version, "request_id": claim_request,
                                  "zero_history_confirmed": confirmed, "confirmed_by": frappe.session.user if confirmed else None})
    if len(response["items"]) != 1:
        frappe.throw("接管返回不唯一；对应出纳申请可能已锁定，请管理员核查")
    history = response["items"][0]
    claim = history.get("takeover", {})
    _source_match(item, history, root)
    if claim.get("owner") != "deeplinkerp" or not claim.get("claim_token") or not claim.get("history_fingerprint"):
        frappe.throw("来源未确认付款锁定，ERP 登记仍关闭")
    with expenses.managed_write():
        frappe.get_doc({"doctype": TAKEOVER, "source": doc.name, "company": doc.company, "cashier_root": root,
                        "history_json": json.dumps(history, ensure_ascii=False), "claim_token": claim["claim_token"],
                        "history_fingerprint": claim["history_fingerprint"], "expense_fingerprint": digest(expense_facts(item)),
                        "claimed_by": frappe.session.user, "claimed_at": now_datetime()}).insert(ignore_permissions=True)
    return {"existing": False, **payment_detail(doc)}


def _values(doc, item, values):
    values = frappe.parse_json(values) if isinstance(values, str) else values
    allowed = {"amount", "bank_amount", "payment_date", "bank_account", "party_type", "party", "bank_reference", "remark", "bank_exchange_rate", "source_exchange_rate", "exchange_difference_account", "cost_center", "project", "advance_account"}
    if not isinstance(values, dict) or set(values) - allowed:
        frappe.throw("付款字段格式无效")
    bank = expenses._account(values.get("bank_account"), doc.company, {"Bank", "Cash"})
    expenses._party(item, {**values, "company": doc.company, "application_type": doc.effective_application_type})
    for field, maximum in (("bank_reference", 140), ("remark", 1000)):
        if not isinstance(values.get(field) or "", str) or len(values.get(field) or "") > maximum:
            frappe.throw("付款备注或流水号过长")
    # Validate configured references now, not after financial information leaks.
    base = expenses._read("Company",doc.company,{"default_currency"}).default_currency
    if values.get("exchange_difference_account"):
        fx=expenses._account(values["exchange_difference_account"],doc.company)
        if fx.account_currency!=base or fx.root_type not in {"Income","Expense"}:
            frappe.throw("汇兑差额科目必须为本位币损益科目")
    for field, doctype in (("cost_center", "Cost Center"), ("project", "Project")):
        if values.get(field):
            ref = expenses._read(doctype, values[field], {"company","is_group"} if doctype=="Cost Center" else {"company"})
            if (ref.company and ref.company != doc.company) or (doctype=="Cost Center" and ref.is_group):
                frappe.throw("辅助核算公司不一致")
    for field in ("source_exchange_rate", "bank_exchange_rate"):
        if values.get(field) is not None:
            rate=_checked(money,values[field],precision=9,positive=True)
            rate_currency=item["currency"] if field=="source_exchange_rate" else bank.account_currency
            if rate_currency==base and rate!=1:
                frappe.throw("本位币汇率必须为 1")
    if bank.account_currency != item["currency"] and (not values.get("bank_exchange_rate") or not values.get("source_exchange_rate")):
        frappe.throw("跨币种付款必须明确银行实付金额及两种币种的本位币汇率")
    if values.get("advance_account"):
        advance = expenses._account(values["advance_account"], doc.company)
        if advance.root_type not in {"Asset", "Liability"} or advance.account_currency != item["currency"] or advance.account_type in {"Bank","Cash"}:
            frappe.throw("预付款科目须为同申请币种的资产／往来科目，不能使用费用或付款银行科目")
        if not values.get("source_exchange_rate") or not values.get("bank_exchange_rate"):
            frappe.throw("生成预付款草稿前须明确申请币种及银行币种的本位币汇率")
    return values, bank


def _register_payment(source_id, values, expected_source_version, request_id):
    expenses._finance()
    doc = expenses._source(source_id, write=True)
    item = _fresh_base(doc)
    values, bank = _values(doc, item, values)
    takeover = _takeover(doc,for_update=True)
    if not takeover:
        frappe.throw("请先核对并接管完整历史付款，不能按零历史登记")
    if takeover.expense_fingerprint != digest(expense_facts(item)):
        frappe.throw("接管后的申请财务事实已变化，请管理员复核；既有付款不会删除")
    key = digest([frappe.local.site, doc.name, frappe.session.user, identifier(request_id)])
    fingerprint = digest(values)
    existing = frappe.db.get_value(PAYMENT, key, ["request_fingerprint", "source"], as_dict=True,for_update=True)
    if existing:
        if existing.source != doc.name or existing.request_fingerprint != fingerprint:
            frappe.throw("相同付款请求不能变更金额或字段")
        return {"payment_id": key, "existing": True, **payment_detail(doc,for_update=True)}
    cached_intent=(expected_source_version==doc.source_version and
                   digest(expense_facts(json.loads(doc.source_json)))==takeover.expense_fingerprint)
    # Ownership changes the transport version, not the frozen financial intent.
    # Accept only the exact displayed cache version with identical current facts;
    # changed amounts/approval/attachments still fail the fingerprint above.
    if item["version"] != expected_source_version and not cached_intent:
        frappe.throw("申请事实已变化，请刷新后重新确认付款")
    detail = payment_detail(doc,for_update=True)
    if not detail.get("balance"):
        frappe.throw(detail.get("notice") or "付款历史待核对")
    normalized = _checked(registration, values, detail["balance"]["pending_amount"], same_currency=bank.account_currency == item["currency"])
    with expenses.managed_write():
        frappe.get_doc({"doctype": PAYMENT, "payment_key": key, "source": doc.name, "company": doc.company, "status": "Registered", **normalized,
                        "currency": item["currency"], "bank_currency": bank.account_currency, "bank_account": bank.name,
                        "party_type": values["party_type"], "party": values["party"], "bank_reference": values.get("bank_reference"), "remark": values.get("remark"),
                        "registered_by": frappe.session.user, "request_fingerprint": fingerprint, "source_version": item["version"], "terms_json": json.dumps(values, ensure_ascii=False)}).insert(ignore_permissions=True)
    return {"payment_id": key, "existing": False, **payment_detail(doc,for_update=True)}


@frappe.whitelist(methods=["POST"])
def register_payment(source_id, values, expected_source_version, request_id):
    # Like native voucher creation, a MariaDB changed-record/deadlock must
    # restart this isolated RPC and repeat authorization/freshness/balance.
    # Never commit here or retry a business validation error.
    for attempt in range(3):
        try:
            return _register_payment(source_id,values,expected_source_version,request_id)
        except frappe.QueryDeadlockError:
            frappe.db.rollback()
            if attempt==2:
                frappe.throw("同期财务操作发生冲突，请刷新后重试")


@frappe.whitelist(methods=["POST"])
def reverse_payment(source_id, payment_id, reason, request_id, discard_drafts=False):
    expenses._finance()
    doc = expenses._source(source_id, write=True)
    payment = expenses._read(PAYMENT, identifier(payment_id), set(PAYMENT_FIELDS), for_update=True)
    if payment.source != doc.name or payment.company != doc.company:
        frappe.throw("付款不属于本申请")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        frappe.throw("必须填写撤销原因")
    key = digest([frappe.session.user, identifier(request_id)])
    fingerprint = digest([payment.name, reason.strip()])
    if payment.status == "Reversed":
        if payment.reversal_key != key or payment.reversal_fingerprint != fingerprint:
            frappe.throw("付款已撤销，请刷新；不能更改原撤销原因")
        return payment_detail(doc,for_update=True)
    discard_drafts = _confirmation(discard_drafts)
    events = frappe.get_all(expenses.EVENT, filters={"source": doc.name, "payment_source_id": "erp-payment:" + payment.name}, fields=["name", "journal_entry"],limit_page_length=0,run=False).for_update().run(as_dict=True)
    for row in events:
        event = expenses._read(expenses.EVENT, row.name, {"company", "source"}, for_update=True)
        journal = expenses._read("Journal Entry", row.journal_entry, {"company", "docstatus"}, for_update=True)
        if journal.company != doc.company:
            frappe.throw("关联凭证公司不符，请核查")
        if journal.docstatus == 2:
            continue
        if journal.docstatus != 0:
            frappe.throw("已有记账凭证，请先在原生凭证流程取消；本页不会自动冲账")
        if not discard_drafts:
            frappe.throw("关联凭证尚为草稿，请明确确认弃用草稿再撤销登记；不需要提交或记账")
        journal.check_permission("delete")
        if journal.get("custom_operating_event_key") != event.name or journal.get("custom_operating_source") != doc.name:
            frappe.throw("只能弃用本申请对应付款生成的原生草稿")
        provenance=json.loads(event.provenance_json or "{}")
        provenance["voided_draft"]={"journal_entry":journal.name,"document":journal.as_dict(),"reason":reason.strip(),"by":frappe.session.user,"at":str(now_datetime())}
        event.journal_entry=None
        event.provenance_json=json.dumps(provenance,default=str,ensure_ascii=False)
        expenses._save(event)
        # Native recoverable deletion retains Deleted Document. Do not force
        # links: any other dependency must block and roll back this transaction.
        frappe.delete_doc("Journal Entry",journal.name,ignore_missing=False)
    payment.update({"status": "Reversed", "reversal_reason": reason.strip(), "reversed_by": frappe.session.user, "reversed_at": now_datetime(), "reversal_key": key, "reversal_fingerprint": fingerprint})
    expenses._save(payment)
    return payment_detail(doc,for_update=True)


@frappe.whitelist()
def get_approval_timeline(source_id):
    doc = expenses._source(source_id)
    raw = json.loads(doc.source_json)
    root = raw.get("cashier_source_id") or (raw.get("source_id") if raw.get("source_system") == "cashier-payment-archive" else None)
    if not root:
        return {"lookup_status": "missing", "events": [], "last_synced_at": None, "notice": "暂无唯一审批缓存，可在钉钉原单核对"}
    response = expenses._request(CLAIM_PATH + "workflow", params={"source_id": identifier(root)})
    if len(response["items"]) != 1 or response["items"][0].get("source_id") != root:
        frappe.throw("审批缓存身份不唯一，请核对钉钉原单")
    row = response["items"][0]
    events = row.get("events")
    if not isinstance(events, list) or len(events) > 5000:
        frappe.throw("审批缓存格式无效")
    fields = {"id", "stage", "operator", "time", "result", "comment", "current", "active", "attachments", "images"}
    return {"lookup_status": row.get("lookup_status"), "last_synced_at": row.get("last_synced_at"), "events": [{key: event.get(key) for key in fields} for event in events if isinstance(event, dict)]}


def _save_proof(filename, content, payment_id):
    from pypdf.errors import PdfReadError
    with expenses.managed_write():
        try:
            # Native File validates content before writing it. The legacy helper
            # writes once first, then asks File to parse/write it again, leaving
            # an orphan if a malformed PDF is rejected by the second pass.
            return frappe.get_doc({"doctype":"File","file_name":filename,"content":content,
                                   "attached_to_doctype":PAYMENT,"attached_to_name":payment_id,
                                   "is_private":1}).insert(ignore_permissions=True)
        except PdfReadError:
            frappe.throw("回单文件已损坏或无法读取，请重新上传有效 PDF")


@frappe.whitelist(methods=["POST"])
def upload_payment_proof(source_id=None, payment_id=None):
    expenses._finance()
    # Native FileUploader calls method() and passes identity through docname.
    # Omit its generic doctype-write gate: controlled payment rows are read-only.
    # This endpoint authorizes the finance role and native parent/company reads
    # before saving anything, and never accepts a different parent type.
    if payment_id is None:
        if frappe.form_dict.doctype not in (None, PAYMENT):
            frappe.throw("回单父记录类型无效")
        payment_id = frappe.form_dict.docname
    payment = expenses._read(PAYMENT, identifier(payment_id), {"source", "company", "status"})
    doc = expenses._source(source_id or payment.source, write=True)
    payment = expenses._read(PAYMENT, payment.name, {"source", "company", "status"}, for_update=True)
    if payment.source != doc.name or payment.company != doc.company or payment.status != "Registered":
        frappe.throw("付款不属于本申请或已撤销")
    content = getattr(frappe.local, "uploaded_file", None)
    filename = getattr(frappe.local, "uploaded_filename", None)
    remote = getattr(frappe.local, "uploaded_file_url", None)
    if remote or not isinstance(content, bytes) or not 1 <= len(content) <= 10 * 1024 * 1024 or not isinstance(filename, str):
        frappe.throw("仅支持上传不超过 10 MB 的本地 PDF 或图片回单")
    filename = os.path.basename(filename.replace("\\", "/"))
    extension = os.path.splitext(filename)[1].lower()
    signatures = {".pdf": b"%PDF-", ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
    if len(filename) > 140 or extension not in signatures or not content.startswith(signatures[extension]):
        frappe.throw("回单格式与文件内容不符，仅支持 PDF、PNG、JPG")
    file = _save_proof(filename, content, payment.name)
    return {"name": file.name, "file_name": file.file_name, "is_private": 1}


def validate_payment_file(file, method=None):
    old_parent = frappe.db.get_value("File", file.name, "attached_to_doctype") if not file.is_new() else None
    if file.attached_to_doctype == PAYMENT or old_parent == PAYMENT:
        expenses.validate_managed_document(file)
        if not file.is_private or file.attached_to_doctype != PAYMENT or not str(file.file_url or "").startswith("/private/files/"):
            frappe.throw("ERP 付款回单必须保留私有附件关联")


@frappe.whitelist()
def download_payment_proof(source_id, payment_id, file_id):
    doc = expenses._source(source_id)
    payment = expenses._read(PAYMENT, identifier(payment_id), {"source", "company"})
    file = expenses._read("File", identifier(file_id), {"is_private", "attached_to_doctype", "attached_to_name", "file_name", "file_url"})
    if (payment.source != doc.name or payment.company != doc.company or not file.is_private or file.attached_to_doctype != PAYMENT
            or file.attached_to_name != payment.name or not str(file.file_url or "").startswith("/private/files/")):
        frappe.throw("回单不存在或无权读取", frappe.PermissionError)
    # PDF/image bytes must not enter File's text-encoding guessing loop.
    frappe.response.update(filename=file.file_name, filecontent=file.get_content(encodings=[]), type="download")


def voucher_mapping(doc, payment_id=None, for_update=False):
    if payment_id and payment_id.startswith("erp-payment:"):
        payment = expenses._read(PAYMENT, identifier(payment_id.removeprefix("erp-payment:")), set(PAYMENT_FIELDS), for_update=for_update)
        if payment.source != doc.name or payment.company != doc.company or payment.status != "Registered":
            frappe.throw("ERP 付款记录无效或已撤销")
        values = json.loads(payment.terms_json)
        bank = expenses._account(payment.bank_account, doc.company, {"Bank", "Cash"})
        if bank.account_currency != payment.bank_currency:
            frappe.throw("实际付款银行币种已变化，请核对；不会重新解释原付款金额")
        if values.get("advance_account"):
            return {"advance": True}
        mapping = expenses._mapping(doc, for_update=for_update)
        if (mapping.get("party_type"), mapping.get("party")) != (payment.party_type, payment.party):
            frappe.throw("费用应付往来方与实际付款不一致，请核对；不会改换付款对象")
        base = expenses._read("Company", doc.company, {"default_currency"}).default_currency
        bank_rate = values.get("bank_exchange_rate") or ("1" if payment.bank_currency == base else None)
        if not bank_rate:
            frappe.throw("实际付款的银行币种汇率未明确，请先核对")
        # Actual bank facts are immutable. The payable debit uses the original
        # recognized book rate, not a later spot rate or an editable duplicate.
        accounting=mapping.get("payments",{}).get(payment_id,{})
        terms = {"bank_account": payment.bank_account, "bank_amount": payment.bank_amount,
                 "bank_exchange_rate": bank_rate, "payable_exchange_rate": mapping["payable_exchange_rate"],
                 "exchange_difference_account": values.get("exchange_difference_account") or accounting.get("exchange_difference_account"),
                 "cost_center":values.get("cost_center") or accounting.get("cost_center")}
        return {**mapping, "payments": {**mapping.get("payments", {}), payment_id: terms}}
    return expenses._mapping(doc, for_update=for_update)


def advance_preview(doc, item, payment_id):
    """Use the same native draft/event pipeline, but never recognize an expense."""
    if not isinstance(payment_id, str) or not payment_id.startswith("erp-payment:"):
        frappe.throw("预付款仅使用本申请的 ERP 实际付款记录")
    payment = expenses._read(PAYMENT, identifier(payment_id.removeprefix("erp-payment:")), set(PAYMENT_FIELDS))
    if payment.source != doc.name or payment.company != doc.company or payment.status != "Registered":
        frappe.throw("ERP 付款记录无效或已撤销")
    claim = _takeover(doc)
    if not claim or claim.expense_fingerprint != digest(expense_facts(item)):
        frappe.throw("接管后的来源财务事实变化，不能生成预付款凭证")
    values, bank = _values(doc, item, json.loads(payment.terms_json))
    if not values.get("advance_account"):
        frappe.throw("预付款科目未明确配置，不会猜测费用或科目")
    account = expenses._account(values["advance_account"], doc.company)
    mapping = {"company": doc.company}
    party = (values["party_type"], values["party"]) if account.account_type in {"Payable", "Receivable"} else None
    rows = [expenses._line(account, payment.amount, "debit", mapping, values["source_exchange_rate"], party=party, cost_center=values.get("cost_center"), project=values.get("project")),
            expenses._line(bank, payment.bank_amount, "credit", mapping, values["bank_exchange_rate"])]
    difference = money(rows[1]["credit"]) - money(rows[0]["debit"])
    if difference:
        fx = expenses._account(values.get("exchange_difference_account"), doc.company)
        base = expenses._read("Company", doc.company, {"default_currency"}).default_currency
        if fx.account_currency != base or fx.root_type not in {"Income", "Expense"}:
            frappe.throw("汇兑差额科目必须为本位币损益科目")
        rows.append(expenses._line(fx, str(abs(difference)), "debit" if difference > 0 else "credit", mapping, "1", cost_center=values.get("cost_center")))
    expenses._balanced(rows)
    evidence = next((row for row in item["payments"] if row["source_id"] == payment_id), None)
    if not evidence:
        frappe.throw("实际付款证据已撤回")
    return {"event_key": expenses._event_key(doc, payment_id), "fingerprint": digest({"expense": expense_facts(item), "payment": payment_facts(evidence), "advance_terms": values}),
            "source_version": item["version"], "company": doc.company, "posting_date": str(payment.payment_date), "accounts": rows,
            "recognition": None, "settlement_state": "预付款 · 未核销", "base_rounding": []}
