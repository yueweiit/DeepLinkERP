"""Pure validation and stable financial facts for the read-only cashier contract."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

SOURCE_SYSTEM = "cashier-payment-archive"
SOURCE_URL = "https://payment.yueweiportal.com"
MAX_JSON_BYTES = 5 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def money(value, precision=None, positive=False):
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool) or value == "":
        raise ValueError("金额必须是精确十进制字符串")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) >= Decimal("1e14") or (positive and result <= 0):
            raise ValueError("金额无效")
        if precision is not None and result != result.quantize(Decimal(1).scaleb(-int(precision))):
            raise ValueError("金额精度不能由原生凭证完整表示，请先核查")
        return result
    except InvalidOperation:
        raise ValueError("金额无效") from None


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,140}", value):
        raise ValueError("来源标识无效")
    return value


def attachment_path(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:/api/integrations/erp/(attachments|payment-vouchers)/[1-9][0-9]{0,18}|/oa-archive/[0-9a-f]{64})", value):
        raise ValueError("附件下载路径无效")
    return value


def currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("来源币种无效，请核查")
    return value


def validate_source(item):
    if not isinstance(item, dict) or len(json.dumps(item).encode()) > MAX_JSON_BYTES:
        raise ValueError("来源数据过大或格式无效")
    if item.get("source_system") not in {SOURCE_SYSTEM, "dingtalk-oa"} or item.get("application_type") not in {"payment", "reimbursement", "unclassified"}:
        raise ValueError("来源协议无效")
    identifier(item.get("source_id"))
    identifier(item.get("version"))
    currency(item.get("currency"))
    money(item.get("amount"))
    if item.get("request_date"):
        date.fromisoformat(item["request_date"])
    if not isinstance(item.get("approvals"), dict) or item["approvals"].get("eligibility") not in {"eligible", "blocked"} or not isinstance(item["approvals"].get("raw", {}), dict):
        raise ValueError("审批信息缺失")
    for key in ("payments", "attachments"):
        if not isinstance(item.get(key), list) or len(item[key]) > 5000:
            raise ValueError("来源明细无效")
        ids = set()
        for row in item[key]:
            if not isinstance(row, dict):
                raise ValueError("来源明细格式无效")
            root = identifier(row.get("source_id"))
            if root in ids:
                raise ValueError("来源明细标识重复")
            ids.add(root)
            if key == "payments":
                money(row.get("amount"))
                currency(row.get("currency"))
                if row.get("payment_date"):
                    date.fromisoformat(row["payment_date"])
            else:
                identifier(row.get("version"))
                attachment_path(row.get("url"))
    return item


def attachment_facts(rows):
    return sorted([{key: row.get(key) for key in ("source_id", "version", "filename", "payment_source_id")} for row in rows], key=lambda r: r["source_id"])


def expense_facts(item):
    attachments=item.get("attachments",[])
    if not isinstance(attachments,list) or any(not isinstance(row,dict) for row in attachments):
        raise ValueError("来源附件事实格式无效，请核对原单")
    facts = {key: item.get(key) for key in ("source_system", "source_id", "source_company", "application_type", "application_type_raw", "applicant", "payee_name", "summary", "request_date", "currency", "original_source_amount", "original_source_currency", "storage_precision_warning", "source_conflict", "currency_conflict", "approvals")}
    if item.get("source_system") == "dingtalk-oa" and isinstance(facts["approvals"], dict):
        approvals = facts["approvals"]
        if isinstance(approvals.get("raw"), dict):
            facts["approvals"] = {**approvals, "raw": {key: value for key, value in approvals["raw"].items() if not key.startswith("cashier_")}}
    facts["amount"] = format(money(item["amount"]).normalize(), "f")
    facts["attachments"] = attachment_facts([row for row in attachments if not row.get("payment_source_id")])
    return facts


def payment_facts(payment):
    facts = {key: payment.get(key) for key in ("source_id", "currency", "payment_date", "payment_account", "bank_reference", "payer", "remark", "source_type", "evidence_status")}
    facts["amount"] = format(money(payment["amount"]).normalize(), "f")
    return facts


def event_fingerprint(item, mapping, payment_id=None):
    facts = {"expense": expense_facts(item), "mapping": {k: v for k, v in mapping.items() if k not in {"payments", "approved_by", "approved_at", "source_version", "expense_fingerprint"}}}
    if payment_id:
        payment = next((p for p in item["payments"] if p["source_id"] == payment_id), None)
        if payment is None:
            raise ValueError("来源付款已撤回")
        facts["payment"] = payment_facts(payment)
        facts["payment_mapping"] = mapping.get("payments", {}).get(payment_id)
        facts["evidence"] = attachment_facts([a for a in item["attachments"] if a.get("payment_source_id") == payment_id])
    return digest(_normalize_financial_numbers(facts))


def _normalize_financial_numbers(value):
    if isinstance(value, list):
        return [_normalize_financial_numbers(item) for item in value]
    if isinstance(value, dict):
        monetary = {"amount", "source_amount", "exchange_rate", "payable_exchange_rate", "bank_amount", "bank_exchange_rate"}
        return {key: format(money(item).normalize(), "f") if key in monetary and item is not None else _normalize_financial_numbers(item) for key, item in value.items()}
    return value
