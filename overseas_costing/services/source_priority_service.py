"""
中文用途：统一维护海外成本核算的数据来源优先级。

这个模块只定义口径，不直接修改业务数据。后续导入、试算、前端提示都从这里取同一套规则。
"""

from __future__ import annotations

from copy import deepcopy
import re


SOURCE_PRIORITY_RULES = {
    "tax_fee": {
        "label": "税费",
        "authoritative_source": "完税凭证",
        "fallback_sources": ["国际物流 OA", "OA 附件/清关资料", "OCR/文本解析候选", "人工补录"],
        "summary": "税费以完税凭证为最终权威；凭证未到前，只能按 OA 或附件做暂估。",
    },
    "purchase_price": {
        "label": "采购价/货值",
        "authoritative_source": "支付申请的有效字段证据",
        "fallback_sources": ["国际物流审批及附件", "商品采购支出及附件", "其他合法证据", "人工补录"],
        "summary": "采购价、币种和货值按支付申请、国际物流、商品采购顺序逐字段默认选择；低优先级合法值仍可改选。国际物流正文及对应附件、评论行的专用货值列为采购行总额，仅该字段缺币种时默认人民币。",
    },
    "logistics_fee": {
        "label": "物流费/清关费/杂费",
        "authoritative_source": "已通过且已关联的物流结算采购支出 OA",
        "fallback_sources": ["OA 附件/货代账单/费用清单", "OCR/文本解析候选", "人工补录"],
        "summary": "物流结算采购支出覆盖的费用采用最终金额；国际物流用于初始暂估，未覆盖费用保留独立来源。",
    },
    "attachment_candidate": {
        "label": "附件解析候选",
        "authoritative_source": "OA 附件中的结构化表",
        "fallback_sources": ["OCR/文本解析候选", "人工复核"],
        "summary": "附件解析结果必须能追溯到原附件；非结构化 OCR 只作为候选，不直接当最终口径。",
    },
    "manual_override": {
        "label": "人工调整",
        "authoritative_source": "人工确认记录",
        "fallback_sources": [],
        "summary": "人工调整用于缺失、异常或差异处理，必须保留修改记录。",
    },
}


def get_source_priority_policy() -> dict:
    """返回前后端共享的数据来源优先级口径。"""

    order = ["tax_fee", "purchase_price", "logistics_fee", "attachment_candidate", "manual_override"]
    rules = [dict(SOURCE_PRIORITY_RULES[key], code=key, priority=index + 1) for index, key in enumerate(order)]
    return {
        "order": order,
        "rules": rules,
        "workflow_order": list(WORKFLOW_RANKS),
        "defaults_only": True,
        "preserve_manual_choices": True,
        "short_summary": "逐字段默认按支付申请、国际物流、商品采购顺序选择；低优先级合法值保留可选，缺失字段继续补充，人工选择保持不变；税费最终依据和来源校验继续有效。",
    }


def get_source_priority_summary() -> str:
    return get_source_priority_policy()["short_summary"]


def get_field_source_label(field_group: str) -> str:
    rule = SOURCE_PRIORITY_RULES.get(field_group)
    if not rule:
        return "按来源优先级取数"
    return f"{rule['label']}：{rule['authoritative_source']}优先"


ACTUAL_PACKING_MATCH_STATUSES = frozenset({"matched", "none", "ambiguous", "stale", "invalid"})
WORKFLOW_RANKS = {
    "payment": 0,
    "international_logistics": 1,
    "purchase": 2,
    "other": 3,
}
EVIDENCE_RANKS = {
    "dedicated_attachment": 0,
    "approval_form": 1,
    "attachment": 2,
    "comment": 3,
    "other": 4,
}
WORKFLOW_LABELS = {
    "payment": "支付申请",
    "international_logistics": "国际物流审批",
    "purchase": "商品采购支出",
    "other": "其他来源",
}
# 采购、费用申请、国际物流三流程的资料都可被关联解析，且都保留各自的金额候选：
# 来源优先级（见 docs/source-field-priority.md）只决定逐字段默认值，低优先级来源的
# 合法值始终保留为候选供人工改选。这里的集合仅用于判定“是否属于本次核算可采用的
# 流程范围”，不用于剥夺任何流程的金额候选。
SELECTABLE_SOURCE_STAGES = frozenset({"payment", "international_logistics", "purchase"})
EVIDENCE_LABELS = {
    "dedicated_attachment": "专用附件",
    "approval_form": "审批正文",
    "attachment": "其他相关附件",
    "comment": "评论",
    "other": "其他证据",
}


def is_selectable_source_stage(workflow_stage: str | None) -> bool:
    """Return whether a workflow stage is one of the three pullable processes.

    The stage vocabulary is shared with :func:`classify_workflow_stage`. An
    unknown or missing stage is not selectable, so a browser cannot promote an
    unclassified attachment by omitting the field.
    """

    return str(workflow_stage or "").strip() in SELECTABLE_SOURCE_STAGES

_PAYMENT_TITLE_MARKERS = (
    "运营支出", "月结付款", "月结", "费用支出", "付款申请", "支付申请", "报销",
)
_TRANSPORT_PAYMENT_MARKERS = (
    "运输", "物流", "运费", "海运", "空运", "快递", "dhl", "fedex", "ups", "清关", "关税", "完税",
)


def _packing_field_name(value: object) -> str:
    return re.sub(r"[\s（）()_\-]+", "", str(value or "")).casefold()


def is_workflow_packing_attachment(source: dict) -> bool:
    """Recognize the workflow component, independent of the attachment filename."""

    source = source or {}
    if str(source.get("source_kind") or "") != "approval_attachment":
        return False
    field = _packing_field_name(
        source.get("source_field")
        or source.get("workflow_field_name")
        or source.get("flow_field_name")
    )
    return "装箱单附件" in field and ("excel" in field or field == "装箱单附件")


def _source_business_text(source: dict) -> str:
    fields = source.get("form_fields") if isinstance(source.get("form_fields"), dict) else {}
    parts = [
        source.get("approval_title"), source.get("process_title"), source.get("process_name"),
        source.get("source_label"), source.get("expense_type"), source.get("approval_role"),
        *(f"{key}:{value}" for key, value in fields.items()),
    ]
    return _packing_field_name(" ".join(str(value or "") for value in parts))


def _workflow_identity_text(source: dict) -> str:
    """Return process identity without linked-record values from the form."""

    return _packing_field_name(" ".join(str(source.get(key) or "") for key in (
        "approval_title", "process_title", "process_name", "source_label", "expense_type",
    )))


def _purchase_expense_type_text(source: dict) -> str:
    fields = source.get("form_fields") if isinstance(source.get("form_fields"), dict) else {}
    typed_values = [
        value for key, value in fields.items()
        if any(marker in _packing_field_name(key) for marker in ("类型", "类别", "科目", "支出分类"))
    ]
    return _packing_field_name(" ".join(str(value or "") for value in (
        source.get("approval_title"), source.get("process_title"), source.get("process_name"),
        source.get("source_label"), source.get("expense_type"), *typed_values,
    )))


def classify_workflow_stage(source: dict) -> str:
    """Classify business authority; a transport-flavoured purchase is a payment."""

    source = source or {}
    role = str(source.get("approval_role") or "").strip().casefold()
    identity_text = _workflow_identity_text(source)
    text = _source_business_text(source)
    # Only a relation already confirmed by the settlement workflow is payment
    # authority here.  A pending recommendation cannot be adopted atomically by
    # the AI preview confirmation path, so it remains outside the stage until
    # the existing "actual payment / packing change" workflow confirms it.
    if source.get("actual_packing_source"):
        return (
            "payment"
            if str(source.get("actual_packing_match_status") or "").lower() == "matched"
            else "other"
        )
    if role in {"logistics_expense", "payment", "expense", "settlement"}:
        return "payment"
    if any(_packing_field_name(marker) in identity_text for marker in _PAYMENT_TITLE_MARKERS):
        return "payment"
    # A logistics approval often links purchase-expense records inside its
    # form.  Those related values describe dependencies, not the authority of
    # the current workflow, so explicit logistics identity must win first.
    if role == "international_logistics" or "国际物流" in identity_text or is_workflow_packing_attachment(source):
        return "international_logistics"
    if role == "purchase" or "采购支出" in identity_text or "采购支出" in text:
        typed_text = _purchase_expense_type_text(source)
        return "payment" if any(_packing_field_name(marker) in typed_text for marker in _TRANSPORT_PAYMENT_MARKERS) else "purchase"
    if "国际物流" in text:
        return "international_logistics"
    return "other"


def classify_evidence_kind(source: dict) -> str:
    source = source or {}
    kind = str(source.get("source_kind") or "").strip().casefold()
    if (
        source.get("actual_packing_source")
        and str(source.get("actual_packing_match_status") or "").lower() == "matched"
    ) or is_workflow_packing_attachment(source):
        return "dedicated_attachment"
    if kind == "approval_form":
        return "approval_form"
    if kind == "approval_comment":
        return "comment"
    if kind in {"approval_attachment", "manual_attachment", "wiki_sheet", "attachment"}:
        return "attachment"
    return "other"


def annotate_source_priority(source: dict) -> dict:
    row = deepcopy(source or {})
    workflow_stage = classify_workflow_stage(row)
    evidence_kind = classify_evidence_kind(row)
    row.update(
        workflow_stage=workflow_stage,
        workflow_rank=WORKFLOW_RANKS[workflow_stage],
        evidence_kind=evidence_kind,
        evidence_rank=EVIDENCE_RANKS[evidence_kind],
    )
    return row


def _actual_match_identity(source: dict) -> str:
    return str(
        source.get("actual_packing_match_id")
        or source.get("logical_source_id")
        or source.get("source_id")
        or ""
    )


def _global_actual_match_status(sources: list[dict]) -> tuple[str, str]:
    actual = [source for source in sources if source.get("actual_packing_source")]
    valid = [
        source
        for source in actual
        if str(source.get("actual_packing_match_status") or "").lower() == "matched"
        and bool(source.get("available", True))
        and not bool(source.get("excluded"))
    ]
    identities = {_actual_match_identity(source) for source in valid if _actual_match_identity(source)}
    if len(identities) == 1:
        return "matched", next(iter(identities))
    if len(identities) > 1 or any(
        str(source.get("actual_packing_match_status") or "").lower() == "ambiguous"
        for source in actual
    ):
        return "ambiguous", ""
    statuses = [str(source.get("actual_packing_match_status") or "").lower() for source in actual]
    if "stale" in statuses:
        return "stale", ""
    if "invalid" in statuses:
        return "invalid", ""
    return "none", ""


def rank_material_packing_sources(sources: list[dict]) -> list[dict]:
    """Apply one server-owned, explainable priority order to material sources."""

    rows = [annotate_source_priority(source or {}) for source in sources or []]
    status, matched_identity = _global_actual_match_status(rows)
    for row in rows:
        workflow_attachment = is_workflow_packing_attachment(row)
        dedicated = bool(
            row.get("dedicated_packing_attachment")
            or row.get("dedicated_packing")
            or workflow_attachment
        )
        row["dedicated_packing_attachment"] = dedicated
        row["dedicated_packing"] = dedicated
        row["actual_packing_match_status"] = status
        is_matched = bool(
            status == "matched"
            and row.get("actual_packing_source")
            and _actual_match_identity(row) == matched_identity
            and bool(row.get("available", True))
            and not bool(row.get("excluded"))
        )
        if row.get("actual_packing_source") and not is_matched:
            row.update(
                workflow_stage="other",
                workflow_rank=WORKFLOW_RANKS["other"],
                evidence_kind="other",
                evidence_rank=EVIDENCE_RANKS["other"],
            )
        if status == "ambiguous" and row.get("actual_packing_source"):
            row.update(
                analysis_allowed=False,
                selectable=False,
                needs_selection=True,
                analysis_code="ACTUAL_PACKING_MATCH_AMBIGUOUS",
                analysis_reason="多个实际装箱候选匹配当前单据，请先完成唯一匹配后重新预览。",
                adoption_allowed=False,
                adoption_restriction="实际装箱来源尚未唯一确认。",
                workflow_stage="other",
                workflow_rank=WORKFLOW_RANKS["other"],
                evidence_kind="other",
                evidence_rank=EVIDENCE_RANKS["other"],
            )
        if is_matched:
            reason = "实际运费／装箱变更已匹配当前单据"
        elif workflow_attachment:
            reason = (
                "实际装箱匹配未提供的字段由流程装箱单附件补充"
                if status == "matched"
                else "当前无有效实际装箱匹配，采用流程装箱单附件"
            )
        else:
            if row["workflow_stage"] == "other":
                reason = "按服务端资料源顺序补充高优先级缺失字段"
            else:
                reason = (
                    f"{WORKFLOW_LABELS[row['workflow_stage']]} · {EVIDENCE_LABELS[row['evidence_kind']]}；"
                    "优先级仅决定逐字段默认值，低优先级合法值仍可改选。"
                )
        row["source_priority_rank"] = row["workflow_rank"] * 10 + row["evidence_rank"]
        row["priority_reason"] = reason

    ordered = sorted(rows, key=material_packing_source_priority)
    priorities: dict[str, int] = {}
    for row in ordered:
        identity = str(row.get("parent_source_id") or row.get("logical_source_id") or row.get("source_id") or "")
        if identity not in priorities:
            priorities[identity] = len(priorities) + 1
        row["priority"] = priorities[identity]
    return ordered


def material_packing_source_priority(source: dict) -> tuple[int, int, str, str]:
    """Deterministic material/packing evidence order shared by listing and review."""

    source = source or {}
    annotated = annotate_source_priority(source)
    workflow_rank = int(source.get("workflow_rank") if source.get("workflow_rank") is not None else annotated["workflow_rank"])
    evidence_rank = int(source.get("evidence_rank") if source.get("evidence_rank") is not None else annotated["evidence_rank"])
    return (
        workflow_rank,
        evidence_rank,
        str(source.get("source_id") or ""),
        str(source.get("sheet_name") or ""),
    )
