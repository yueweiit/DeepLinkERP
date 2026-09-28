"""费用页的派生待办状态；不落库生成费用完结状态。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from overseas_costing.services import fee_allocation_service


TODO_DEFINITIONS = {
    "DUPLICATE_LOGICAL_FEE": ("error", "review_duplicate_fee", "费用重复，请核对并停用重复记录"),
    "AMOUNT_REQUIRED": ("error", "enter_amount", "补充费用金额"),
    "ACTUAL_AMOUNT_REQUIRED": ("warning", "enter_actual", "补充实际费用"),
    "ALLOCATION_REQUIRED": ("error", "fix_allocation", "完成费用分摊"),
    "FX_RATE_MISSING": ("error", "enter_fx_rate", "补充批次汇率后试算"),
    "CURRENCY_UNSUPPORTED": ("error", "enter_currency", "请选择人民币、比索或美金"),
    "FEE_AMOUNT_INVALID": ("error", "enter_amount", "请修正费用金额"),
    "EVIDENCE_REQUIRED": ("warning", "link_evidence", "关联最终凭证"),
    "EVIDENCE_VALIDATION_REQUIRED": ("warning", "validate_evidence", "校验最终凭证"),
    # ERP 站点回执侧：与上面的费用待办是两条独立的线，只描述「远端单据是否已同步到位」。
    "ERP_SYNC_REQUIRED": ("warning", "preview_site_sync", "该站点还没有推送当前计算结果"),
    "ERP_RECONCILE_REQUIRED": ("error", "reconcile_erp", "该站点的同步结果未确定，请核对远端"),
    "ERP_MANUAL_REQUIRED": ("error", "review_erp_document", "该站点的同步请求需要人工处理"),
    "ERP_UPDATE_REQUIRED": ("warning", "review_erp_document", "该站点已同步的不是当前计算结果"),
}


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value) -> str:
    number = _decimal(value)
    if number is None:
        return ""
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _normalize(value):
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple, set)):
        normalized = [_normalize(row) for row in value]
        return sorted(normalized, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return _decimal_text(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return format(Decimal(stripped).normalize(), "f") if stripped else ""
        except (InvalidOperation, ValueError):
            return stripped
    return str(value)


def _hash(payload: dict) -> str:
    canonical = json.dumps(
        _normalize(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_fee_input_hash(
    fee: dict,
    *,
    items: list[dict] | None = None,
    fx_context: dict | None = None,
) -> str:
    scope_keys = fee_allocation_service._scope_keys(fee)
    item_revisions = [
        {
            "stable_line_key": row.get("stable_line_key") or row.get("name") or row.get("row_no"),
            "quantity_revision": row.get("actual_shipped_qty_source_revision") or "",
            "effective_quantity": row.get("actual_shipped_qty") or row.get("quantity") or "",
            "goods_value": row.get("goods_value") or "",
            "gross_weight_kg": row.get("gross_weight_kg") or "",
            "volume_m3": row.get("volume_m3") or "",
            "chargeable_weight_kg": row.get("chargeable_weight_kg") or "",
        }
        for row in (items or [])
    ]
    return _hash(
        {
            "fee_key": fee.get("logical_fee_key") or fee.get("rule_code") or fee.get("fee_key") or "",
            "amount": fee.get("amount") or "",
            "currency": str(fee.get("currency") or "").upper(),
            "amount_status": fee_allocation_service.amount_status(fee),
            "amount_revision": fee.get("amount_revision") or "",
            "allocation_basis": fee.get("allocation_basis") or fee.get("basis_field") or "goods_value",
            "scope_type": fee.get("scope_type") or "ALL_ITEMS",
            "scope_item_keys": scope_keys,
            "scope_revision": fee.get("scope_revision") or "",
            "included_in_fee_key": fee.get("included_in_fee_key") or "",
            "fx": fx_context or {},
            "items": item_revisions,
        }
    )


def _todo(code: str) -> dict:
    severity, action, label = TODO_DEFINITIONS[code]
    return {"code": code, "severity": severity, "action": action, "label": label}


def build_fee_status(
    *,
    fee: dict,
    allocation: dict | None,
    evidence: list[dict] | None,
    calculation: dict | None = None,
) -> dict:
    amount_state = fee_allocation_service.amount_status(fee)
    allocation_state = str((allocation or {}).get("status") or "NOT_ALLOCATED")
    required_role = str(fee.get("required_evidence_role") or "").strip()
    matching_evidence = [
        row
        for row in (evidence or [])
        if not required_role or str(row.get("evidence_role") or "") == required_role
    ]
    validation_states = {str(row.get("validation_status") or "PENDING").upper() for row in matching_evidence}
    if amount_state in {"NOT_INCURRED", "INCLUDED"}:
        evidence_state = "NOT_REQUIRED"
    elif not required_role:
        evidence_state = "NOT_REQUIRED"
    elif "VALID" in validation_states:
        evidence_state = "VALID"
    elif "INVALID" in validation_states:
        evidence_state = "INVALID"
    elif validation_states.intersection({"PENDING"}):
        evidence_state = "PENDING"
    else:
        evidence_state = "MISSING"

    todos = []
    if fee.get("duplicate_rule_names") or (allocation or {}).get("code") == "DUPLICATE_LOGICAL_FEE":
        todos.append(_todo("DUPLICATE_LOGICAL_FEE"))
    if amount_state == "MISSING":
        todos.append(_todo("AMOUNT_REQUIRED"))
    elif amount_state == "ESTIMATED":
        todos.append(_todo("ACTUAL_AMOUNT_REQUIRED"))
    if amount_state in fee_allocation_service.COUNTED_AMOUNT_STATUSES and allocation_state != "ALLOCATED" and not fee.get("duplicate_rule_names"):
        code = (allocation or {}).get("code")
        todos.append(_todo(code if code in {"FX_RATE_MISSING", "CURRENCY_UNSUPPORTED", "FEE_AMOUNT_INVALID"} else "ALLOCATION_REQUIRED"))
    if evidence_state in {"MISSING", "INVALID"}:
        todos.append(_todo("EVIDENCE_REQUIRED"))
    elif evidence_state == "PENDING":
        todos.append(_todo("EVIDENCE_VALIDATION_REQUIRED"))
    current_input_hash = str((calculation or {}).get("input_hash") or "")

    return {
        "fee_key": fee.get("logical_fee_key") or fee.get("rule_code") or fee.get("fee_key") or "",
        "expense_category": fee.get("expense_category") or "",
        "amount_state": amount_state,
        "allocation_state": allocation_state,
        "evidence_state": evidence_state,
        "currency": str(fee.get("currency") or "").upper(),
        "amount": "" if fee.get("amount") in (None, "") else _decimal_text(fee.get("amount")),
        "required_evidence_role": required_role,
        "input_hash": current_input_hash,
        "todos": todos,
    }


def summarize_fee_statuses(statuses: list[dict]) -> dict:
    unallocated: dict[str, Decimal] = {}
    estimated: dict[str, Decimal] = {}
    todo_count = 0
    for status in statuses or []:
        codes = {str(todo.get("code") or "") for todo in status.get("todos") or []}
        currency = str(status.get("currency") or "").upper() or "UNKNOWN"
        amount = _decimal(status.get("amount"))
        if amount is not None and codes.intersection({"ALLOCATION_REQUIRED", "FX_RATE_MISSING", "CURRENCY_UNSUPPORTED"}) and status.get("amount_state") in {"ESTIMATED", "ACTUAL"}:
            unallocated[currency] = unallocated.get(currency, Decimal("0")) + amount
        if amount is not None and status.get("amount_state") == "ESTIMATED":
            estimated[currency] = estimated.get(currency, Decimal("0")) + amount
        todo_count += len(status.get("todos") or [])

    return {
        "fee_count": len(statuses or []),
        "affected_fee_count": sum(1 for status in statuses or [] if status.get("todos")),
        "todo_count": todo_count,
        "missing_amount_fee_count": sum(
            1 for status in statuses or [] if status.get("amount_state") == "MISSING"
        ),
        "estimated_fee_count": sum(
            1 for status in statuses or [] if status.get("amount_state") == "ESTIMATED"
        ),
        "unallocated_fee_count": sum(
            1
            for status in statuses or []
            if any(
                str(todo.get("code") or "") in {"ALLOCATION_REQUIRED", "FX_RATE_MISSING", "CURRENCY_UNSUPPORTED", "FEE_AMOUNT_INVALID"}
                for todo in status.get("todos") or []
            )
        ),
        "missing_evidence_fee_count": sum(
            1 for status in statuses or [] if status.get("evidence_state") in {"MISSING", "INVALID"}
        ),
        "pending_evidence_fee_count": sum(
            1 for status in statuses or [] if status.get("evidence_state") == "PENDING"
        ),
        "unallocated_by_currency": {
            currency: _decimal_text(amount) for currency, amount in sorted(unallocated.items())
        },
        "estimated_by_currency": {
            currency: _decimal_text(amount) for currency, amount in sorted(estimated.items())
        },
        "all_requirements_satisfied": not any(status.get("todos") for status in statuses or []),
    }


ERP_WORK_SITE_STATES = (
    "SYNCED",
    "UPDATE_REQUIRED",
    "IN_PROGRESS",
    "ATTENTION_REQUIRED",
    "NOT_PUSHED",
)

# 站点状态 → 待办码。没有条目的状态表示「不用人管」。
# ATTENTION_REQUIRED 不在表里：它下面 FAILED/UNCERTAIN 走核对、MANUAL_REQUIRED 走人工，
# 待办码必须按账本状态分开（见 build_erp_site_state）。
_ERP_SITE_TODO_CODES = {
    "NOT_PUSHED": "ERP_SYNC_REQUIRED",
    "UPDATE_REQUIRED": "ERP_UPDATE_REQUIRED",
}


def _erp_text(value) -> str:
    return "" if value in (None, "") else str(value).strip()


def latest_site_request(rows: list[dict]) -> dict | None:
    """某站点账本里最新一次同步请求。

    排序用 ``creation`` 而不是 ``modified``：迟到的旧回执（H1 推送失败、很久以后才核对成
    功）会在 ``modified`` 上排到最前，拿它当「该站点当前状态」会让旧成本的成功回执
    关闭新版本的待办。``creation`` 才是「这次请求是为哪一份成本结果开的」。
    """

    candidates = [row for row in (rows or []) if isinstance(row, dict)]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (_erp_text(row.get("creation")), _erp_text(row.get("name"))))


def build_erp_site_state(latest: dict | None, *, current_hash: str = "") -> tuple[str, str]:
    """把某站点最新一次请求折算成（状态, 待办码）；待办码为空表示无需处理。"""

    if latest is None:
        return "NOT_PUSHED", _ERP_SITE_TODO_CODES["NOT_PUSHED"]
    status = _erp_text(latest.get("status")).upper()
    hash_value = _erp_text(latest.get("cost_result_hash"))
    current = _erp_text(current_hash)
    if status in {"PENDING", "RUNNING"}:
        return "IN_PROGRESS", ""
    if status == "SUCCESS":
        # 只有「最新一次成功回执的成本结果 hash 就是当前结果」才算真的同步到位。
        if current and hash_value != current:
            return "UPDATE_REQUIRED", _ERP_SITE_TODO_CODES["UPDATE_REQUIRED"]
        return "SYNCED", ""
    # FAILED / UNCERTAIN 是服务端唯一允许核对的两种状态（RECONCILABLE_STATUSES），
    # 因此这里给的是「核对远端」；MANUAL_REQUIRED 及认不出的状态只能交给人。
    if status in {"FAILED", "UNCERTAIN"}:
        return "ATTENTION_REQUIRED", "ERP_RECONCILE_REQUIRED"
    if status == "SUPERSEDED":
        return "NOT_PUSHED", _ERP_SITE_TODO_CODES["NOT_PUSHED"]
    return "ATTENTION_REQUIRED", "ERP_MANUAL_REQUIRED"


def _erp_work_overall(counts: dict) -> str:
    total = sum(counts.values())
    if total == 0:
        return "EMPTY"
    if counts["ATTENTION_REQUIRED"]:
        return "ATTENTION_REQUIRED"
    if counts["NOT_PUSHED"] == total:
        return "NOT_STARTED"
    if counts["NOT_PUSHED"]:
        return "PARTIAL"
    if counts["IN_PROGRESS"]:
        return "IN_PROGRESS"
    if counts["UPDATE_REQUIRED"]:
        return "UPDATE_REQUIRED"
    return "SYNCED"


def build_erp_work_state(
    *,
    current_hash: str = "",
    sites: list[dict] | None = None,
    planned_sites: list[str] | None = None,
) -> dict:
    """按站点汇总 ERP 回执，输出站点级状态与待办。

    ``sites`` 是同步请求账本行（``site_code`` / ``status`` / ``cost_result_hash`` / ``error_code``
    / ``error_message`` / ``creation``），只读 ERP 侧事实，**不读任何费用状态**：费用是否齐备由
    :func:`build_fee_status` 单独判定，两条线不互相关闭对方的待办。

    ``planned_sites`` 是当前计算结果会推到的站点（来自分站点计划）。账本里没有请求的站点
    只有靠它才能报出来 —— 「哪个站点根本没同步过」本身就是这批信息里最要紧的一条。

    ``current_hash`` 是当前计算结果的结果哈希。它没有落库，只能在真正算过分站点计划的地方
    （``preview_site_sync_plan``）传进来；拿不到时留空，此时站点状态退化成「有没有推送成功」，
    不会凭空报 ``UPDATE_REQUIRED``。

    批次级 ``writeback_status`` 只是这套站点状态的历史投影，不在这里读写 —— 它被计算与物流
    结算多处当作锁定判据，不能从派生函数里回写。
    """

    grouped: dict[str, list[dict]] = {}
    for row in sites or []:
        if not isinstance(row, dict):
            continue
        site_code = _erp_text(row.get("site_code"))
        if site_code:
            grouped.setdefault(site_code, []).append(dict(row))
    for site_code in planned_sites or []:
        code = _erp_text(site_code)
        if code:
            grouped.setdefault(code, [])

    counts = {state: 0 for state in ERP_WORK_SITE_STATES}
    work_sites = []
    for site_code in sorted(grouped):
        latest = latest_site_request(grouped[site_code])
        state, todo_code = build_erp_site_state(latest, current_hash=current_hash)
        counts[state] += 1
        work_sites.append(
            {
                "site_code": site_code,
                "state": state,
                # 该站点当前持有的成本结果哈希（可能是旧的，见 state=UPDATE_REQUIRED）。
                "cost_result_hash": _erp_text((latest or {}).get("cost_result_hash")),
                "request_id": _erp_text((latest or {}).get("request_id")),
                "status": _erp_text((latest or {}).get("status")).upper(),
                "attempt_count": int((latest or {}).get("attempt_count") or 0),
                "error_code": _erp_text((latest or {}).get("error_code")),
                "error_message": _erp_text((latest or {}).get("error_message")),
                "todo": _todo(todo_code) if todo_code else None,
            }
        )

    return {
        "overall": _erp_work_overall(counts),
        "current_cost_result_hash": _erp_text(current_hash),
        "sites": work_sites,
        "counts": counts,
        "todo_count": sum(1 for row in work_sites if row.get("todo")),
    }
