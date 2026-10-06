"""China 2026 original applications, with separately proven cashier evidence.

Pure normalization lives here; the existing OA connection and authenticated
cashier transport are supplied by the service. No accounting or source writes.
"""
from __future__ import annotations

import base64
import copy
import json
import re
from urllib.parse import urlencode
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from .operating_expense_contract import digest, money

SOURCE_SYSTEM = "dingtalk-oa"
PROCESS_CODES = (
    "PROC-0DC5DE17-A29A-497C-8A1F-1324298A04AA", "PROC-E7BC3316-E618-4812-BDCC-7A655A7C694B",
    "PROC-39D6CE87-6F84-40B1-A3EB-B96F363CE8F8", "PROC-CCB314E9-1458-4D53-9EF2-F68A21EA018D",
    "PROC-D3ED660B-A5D4-4516-BC82-D83E52B5FEF8", "PROC-618F58F6-A68C-4BFE-A92B-49B3CD9B79DD",
    "PROC-75FEF975-C79F-44A3-A02C-21734C2DBC49",
)
START = datetime(2025, 12, 31, 16, tzinfo=timezone.utc)
END = datetime(2026, 12, 31, 16, tzinfo=timezone.utc)
COMPANY_BRIDGES = {
    "悦为智能 YW Tech_Ai": "悦为智能技术（东莞）有限公司",
    "拉丁购": "拉丁购国际电子商务（东莞）有限公司",
    "凌翔产品&开发": "广州凌翔电子产品有限公司",
    "凌翔供应链及采购执行单元": "广州凌翔电子产品有限公司",
    "星铭HR人力资源中心": "东莞市星铭贸易有限公司",
    "星铭FC财务中心": "东莞市星铭贸易有限公司",
}
TYPES = {"付款申请solicitud de pago": "payment", "付款申请 solicitud de pago": "payment",
         "付款申请": "payment", "solicitud de pago": "payment",
         "费用报销reembolso de gastos": "reimbursement", "费用报销 reembolso de gastos": "reimbursement",
         "费用报销": "reimbursement", "reembolso de gastos": "reimbursement"}
CURRENCIES = {"人民币": "CNY", "人民币cny": "CNY", "人民币rmb": "CNY", "cny": "CNY", "美元": "USD", "usd": "USD", "美元usd": "USD", "美元dólar": "USD",
              "比索": "MXN", "mxn": "MXN", "peso": "MXN", "pesos": "MXN"}
_FORM_ALIASES = {"申请类型": "type", "执行地区": "region", "金额": "amount", "币种": "currency",
                 "事项说明": "summary", "收款人": "payee", "付款日期": "needed_date"}
# Contains matching conservatively retains names with Unicode prefix whitespace;
# fields() remains authoritative. Keep every occurrence, JSON type and order.
_OPERATING_FORM_VALUES = (
    "(CASE WHEN jsonb_typeof(form_component_values)='array' THEN "
    "(SELECT COALESCE(jsonb_agg(jsonb_build_object('name',component->'name','value',component->'value') ORDER BY ordinal),'[]'::jsonb) "
    "FROM jsonb_array_elements(form_component_values) WITH ORDINALITY AS form(component,ordinal) "
    "WHERE jsonb_typeof(component)='object' AND component->>'name' ~ '"
    + "|".join(re.escape(prefix) for prefix in _FORM_ALIASES).replace("'", "''")
    + "') ELSE form_component_values END)"
)


def timestamp(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Source timestamp must carry timezone")
    return parsed.astimezone(timezone.utc)


def fields(row):
    components = row.get("form_component_values") or []
    if isinstance(components, str):
        components = json.loads(components, parse_float=Decimal)
    result = {}
    if not isinstance(components, list):
        return result
    for component in components:
        if not isinstance(component, dict):
            continue
        name = str(component.get("name") or "").strip()
        for prefix, key in _FORM_ALIASES.items():
            if name.startswith(prefix):
                # Duplicate components are ambiguous, not last-value-wins.
                result[key] = None if key in result else component.get("value")
                break
    return result


def normalized(value):
    return " ".join(str(value or "").split()).casefold()


def in_scope(row):
    form = fields(row)
    try:
        return (row.get("process_code") in PROCESS_CODES and START <= timestamp(row.get("create_time")) < END
                and normalized(form.get("region")) in {"中国", "中国china", "中国 china", "china"}
                and normalized(form.get("type")) in TYPES)
    except (ValueError, TypeError):
        return False


def application_id(row):
    if not row.get("corp_id") or not row.get("process_instance_id"):
        raise ValueError("OA identity missing")
    return "oa:" + digest([str(row["corp_id"]), str(row["process_instance_id"])])


def matches(row, cashier):
    if cashier.get("identity_conflict") or cashier.get("approval_identity_status") == "conflict":
        return False
    if cashier.get("corp_id") and cashier["corp_id"] != row["corp_id"]:
        return False
    instance = cashier.get("process_instance_id")
    if instance:
        return instance == row["process_instance_id"]
    return (row.get("business_count", 1) == 1 and cashier.get("approval_identity_status") == "explicit" and bool(row.get("business_id"))
            and cashier.get("approval_no") == row["business_id"])


def exact_amount(value):
    try:
        return str(money(value))
    except ValueError:
        return None


def resolution_applicant(row, cashier_items):
    candidates = [item for item in cashier_items if matches(row, item)]
    identity = candidates[0].get("applicant_identity") or {} if len(candidates) == 1 else {}
    if identity.get("status") == "ambiguous":
        return {"user_id": "", "employee_name": ""}
    if identity.get("manual_applicant_override"):
        return {"user_id": identity.get("user_id") or "", "employee_name": identity.get("employee_name") or ""}
    return {"user_id": row.get("originator_user_id") or "", "employee_name": row.get("originator_user_name") or ""}


def withdrawn_source(raw, row=None):
    item = copy.deepcopy(raw)
    item.update(approvals={"eligibility": "blocked", "raw": {"status": (row or {}).get("status"), "result": (row or {}).get("result"), "scope": "withdrawn"}},
                source_conflict=True, paid_amount=None, pending_amount=None, source_status="付款待核对")
    item["version"] = digest({k: v for k, v in item.items() if k != "version"})
    return item


def merge_application(row, cashier_items, company_resolution):
    form = fields(row)
    candidates = [item for item in cashier_items if matches(row, item)]
    cashier = candidates[0] if len(candidates) == 1 else None
    conflict = len(candidates) > 1
    amount, currency = exact_amount(form.get("amount")), CURRENCIES.get(normalized(form.get("currency")))
    if cashier:
        conflict |= (cashier.get("source_conflict") or cashier.get("currency_conflict") or
                     amount is None or exact_amount(cashier.get("amount")) is None or
                     money(amount) != money(cashier["amount"]) or currency != cashier.get("currency"))
    approval = {"eligibility": "eligible" if row.get("status") == "COMPLETED" and row.get("result") == "agree"
                and not row.get("deleted_at") and in_scope(row) else "blocked",
                "raw": {"status": row.get("status"), "result": row.get("result"), "deleted_at": str(row.get("deleted_at") or "")}}
    if cashier and not conflict:
        for key, value in (cashier.get("approvals", {}).get("raw") or {}).items():
            if key in {"owner_confirmation", "finance_review", "finance_manager_approval", "general_manager_approval", "status", "result"}:
                approval["raw"]["cashier_" + key] = value
    # A cashier manual applicant override is authoritative for organization resolution,
    # never silently reattached to the old originator UserID.
    identity = (cashier.get("applicant_identity") or {}) if cashier else {}
    resolution = ({"status": "ambiguous", "ambiguity_reason": identity.get("ambiguity_reason")} if identity.get("status") == "ambiguous" else company_resolution) or {}
    verified = bool(cashier and not conflict and cashier.get("payment_evidence_status") == "recorded")
    paid = exact_amount(cashier.get("paid_amount")) if verified else None
    pending = exact_amount(cashier.get("pending_amount")) if verified and approval["eligibility"] == "eligible" else None
    item = {"source_system": SOURCE_SYSTEM, "source_id": application_id(row),
            "oa_identity": {"corp_id": row["corp_id"], "process_instance_id": row["process_instance_id"]},
            "approval_no": row.get("business_id"), "dingding_id": row["process_instance_id"],
            "cashier_source_id": cashier.get("source_id") if cashier else None,
            "source_company": resolution.get("assigned_department") if resolution.get("status") == "matched" else None,
            "company_resolution": copy.deepcopy(resolution), "source_sheet": resolution.get("assigned_department"),
            "application_type": TYPES.get(normalized(form.get("type")), "unclassified"), "application_type_raw": form.get("type"),
            "applicant": identity.get("employee_name") if identity.get("manual_applicant_override") else row.get("originator_user_name") or row.get("originator_user_id"),
            "payee_name": form.get("payee"), "summary": form.get("summary"),
            "request_date": timestamp(row["create_time"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "needed_payment_date": form.get("needed_date"), "amount": amount, "currency": currency,
            "original_source_amount": amount, "original_source_currency": currency,
            "paid_amount": paid, "pending_amount": pending, "source_status": cashier.get("source_status") if verified else "付款待核对",
            "cashier_reported_payment_status": cashier.get("source_status") if cashier else None,
            "source_conflict": bool(conflict), "payment_evidence_status": "recorded" if verified else "unknown",
            "approvals": approval, "payments": copy.deepcopy(cashier.get("payments", [])) if cashier and not conflict else [],
            "attachments": copy.deepcopy(cashier.get("attachments", [])) if cashier and not conflict else [],
            "updated_at": timestamp(row.get("updated_at") or row["create_time"]).isoformat(),
            "original_url": "https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm?" + urlencode({"procInstId": row["process_instance_id"]})}
    item["version"] = digest(item)
    return item


def archive_attachments(row, manifests):
    result = {}
    for manifest in manifests:
        if (manifest.get("corp_id"), manifest.get("process_instance_id")) != (row["corp_id"], row["process_instance_id"]) or not manifest.get("file_id"):
            continue
        identity = {k: str(manifest[k]) for k in ("corp_id", "process_instance_id", "file_id")}
        token = digest(identity)
        value = {"source_id": "oa-attachment:" + token, "url": "/oa-archive/" + token, "archive_identity": identity,
                 "filename": str(manifest.get("file_name") or manifest["file_id"]), "archive_status": manifest.get("archive_status")}
        value["version"] = digest({**value, "sha256": manifest.get("sha256"), "actual_size": manifest.get("actual_size")})
        result[value["source_id"]] = value
    return list(result.values())


def archive_integrity(manifest):
    """An archived flag alone is not proof of a complete download manifest."""
    sha, size = manifest.get("sha256"), manifest.get("actual_size")
    if (manifest.get("archive_status") != "archived" or not isinstance(sha, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", sha) or isinstance(size, bool)
            or not isinstance(size, (int, str)) or not re.fullmatch(r"[0-9]+", str(size))):
        raise ValueError("归档校验信息缺失或无效，请在钉钉原单核对")
    return sha.lower(), int(size)


def encode_cursor(until, corp, instance):
    return base64.urlsafe_b64encode(json.dumps([until, corp, instance]).encode()).decode()


def decode_cursor(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("Invalid OA cursor")
    try:
        decoded = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(decoded, list) or len(decoded) != 3 or not all(isinstance(v, str) and 0 < len(v) <= 300 for v in decoded):
            raise ValueError()
        timestamp(decoded[0])
        return tuple(decoded)
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("Invalid OA cursor") from None


def read_page(connection_factory, limit, until, cursor=None, identity=None, *, process_codes=PROCESS_CODES):
    """Keyset pagination with projected JSON text; reuse OA read-only connection."""
    limit = int(limit)
    if not 1 <= limit <= 500:
        raise ValueError("Invalid source page size")
    timestamp(until)
    after = decode_cursor(cursor) if cursor else None
    if after and after[0] != until:
        raise ValueError("OA snapshot mismatch")
    conditions = ["process_code = ANY(%s)", "create_time >= %s", "create_time < %s", "updated_at <= %s"]
    params = [list(process_codes), START, END, timestamp(until)]
    if after:
        conditions.append("(corp_id, process_instance_id) > (%s, %s)"); params.extend(after[1:])
    if identity:
        conditions.append("corp_id=%s AND process_instance_id=%s"); params.extend([identity["corp_id"], identity["process_instance_id"]])
    # Do not SELECT *: raw_payload is large and unnecessary for this projection.
    # Bound the projection first; count only its business numbers across the entire source.
    # A collision outside this page, company, year or template still blocks fallback joins.
    count_instances = tuple(process_codes) != PROCESS_CODES
    form_values = "form_component_values" if count_instances else _OPERATING_FORM_VALUES
    sql = (
        "WITH page AS MATERIALIZED (SELECT corp_id,process_instance_id,business_id,process_code,status,result,"
        "originator_user_id,originator_user_name,create_time,updated_at,deleted_at,"
        + form_values + "::text AS form_component_values FROM costing_read.approval_instances_v2 WHERE "
        + " AND ".join(conditions)
        + " ORDER BY corp_id,process_instance_id LIMIT %s), "
        "counts AS MATERIALIZED (SELECT business_id,count(*) AS business_count FROM costing_read.approval_instances_v2 "
        "WHERE business_id IN (SELECT business_id FROM page WHERE NULLIF(business_id,'') IS NOT NULL) "
        "GROUP BY business_id) "
        # Materialize global duplicate counts once, not once per joined page row.
        # Do not apply the page's year/company/template scope to this check.
        + (", instance_counts AS MATERIALIZED (SELECT process_instance_id,count(*) AS instance_count "
           "FROM costing_read.approval_instances_v2 WHERE process_instance_id IN "
           "(SELECT process_instance_id FROM page) GROUP BY process_instance_id) " if count_instances else "")
        + "SELECT page.*,COALESCE(counts.business_count,0) AS business_count "
        + (",COALESCE(instance_counts.instance_count,0) AS instance_count " if count_instances else "")
        + "FROM page LEFT JOIN counts USING(business_id) "
        + ("LEFT JOIN instance_counts USING(process_instance_id) " if count_instances else "")
        + "ORDER BY page.corp_id,page.process_instance_id"
    )
    params.append(limit + 1)
    with connection_factory() as connection:
        with connection.cursor() as query:
            query.execute(sql, tuple(params)); rows = [dict(r) for r in query.fetchall()]
    more = len(rows) > limit
    selected = rows[:limit]
    next_cursor = encode_cursor(until, str(selected[-1]["corp_id"]), str(selected[-1]["process_instance_id"])) if more else None
    return selected, next_cursor
