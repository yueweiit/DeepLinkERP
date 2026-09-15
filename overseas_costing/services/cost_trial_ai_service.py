"""AI 选择试算口径，服务器保有金额计算权。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
from typing import Any

from overseas_costing.services import allocation_service, cost_preview_service, fee_allocation_service

try:
    import frappe
except Exception:  # pragma: no cover - pure tests do not need Frappe
    frappe = None


BASIS_ORDER = ("goods_value", "gross_weight", "volume", "chargeable_weight")
BASIS_LABELS = {
    "goods_value": "货值",
    "gross_weight": "毛重",
    "volume": "体积",
    "chargeable_weight": "计费重",
}
BASIS_FIELDS = {
    "goods_value": "goods_value",
    "gross_weight": "gross_weight_kg",
    "volume": "volume_m3",
    "chargeable_weight": "chargeable_weight_kg",
}
EVIDENCE_PRIORITY_FEES = frozenset({"import_tax", "customs_clearance_fee"})
INPUT_SCHEMA_VERSION = 2
PROMPT_VERSION = "cost-trial-v2"


def cost_trial_ai_enabled() -> bool:
    """Allow an emergency rollback without removing the compatibility calculator."""

    value = os.getenv("OVERSEAS_COST_AI_TRIAL_ENABLED")
    if frappe is not None:
        conf = getattr(frappe, "conf", None)
        try:
            configured = conf.get("overseas_cost_ai_trial_enabled") if conf and hasattr(conf, "get") else None
        except Exception:
            configured = None
        if configured not in (None, ""):
            value = configured
    if value in (None, ""):
        return True
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _preview_token_secret() -> bytes:
    """Return a server-only signing key; browsers must not be able to mint previews."""

    value = os.getenv("OVERSEAS_COST_PREVIEW_TOKEN_SECRET")
    if frappe is not None:
        conf = getattr(frappe, "conf", None)
        try:
            value = value or (conf.get("encryption_key") if conf and hasattr(conf, "get") else None)
        except Exception:
            value = value or None
        if not value:
            raise RuntimeError("站点缺少 encryption_key，无法签发试算预览令牌。")
    # Pure unit tests run without a Frappe site. Production always takes the branch above.
    return str(value or "overseas-cost-trial-unit-test-only").encode("utf-8")


def _sign_preview(payload: dict) -> str:
    return hmac.new(_preview_token_secret(), _json(payload).encode("utf-8"), hashlib.sha256).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _fee_key(fee: dict) -> str:
    return str(fee.get("logical_fee_key") or fee.get("rule_code") or fee.get("name") or "")


def requires_ai_allocation(fee: dict) -> bool:
    """Return whether a fee needs an AI-selected allocation basis."""

    amount = _decimal(fee.get("amount"))
    return fee_allocation_service.is_counted_fee(fee) and amount is not None and amount != 0


def _item_key(item: dict) -> str:
    return str(item.get("stable_line_key") or item.get("name") or item.get("row_no") or "")


def _basis_value(item: dict, basis: str) -> Decimal | None:
    return fee_allocation_service.basis_decimal(item, basis)


def _basis_profile(fee: dict, items: list[dict], basis: str) -> dict:
    eligible = fee_allocation_service.resolve_eligible_items(fee, items)
    values = [_basis_value(row, basis) for row in eligible]
    missing = [row for row, value in zip(eligible, values) if value is None or value <= 0]
    denominator = sum((value or Decimal("0") for value in values), Decimal("0"))
    return {
        "basis": basis,
        "label": BASIS_LABELS[basis],
        "field": BASIS_FIELDS[basis],
        "available": bool(eligible) and not missing and denominator > 0,
        "missing_count": len(missing),
        "missing_item_keys": [_item_key(row) for row in missing],
        "denominator": format(denominator, "f"),
    }


def _alternative_profile(fee: dict, items: list[dict], fx_context: dict, profile: dict) -> dict:
    result = dict(profile)
    allocation = cost_preview_service.allocate_fee_in_rmb(
        {**fee, "trial_allocation_basis": profile["basis"]}, items, fx_context or {}
    )
    allocations = allocation.get("allocations") or {}
    result["allocation_preview"] = [
        {"item_key": _item_key(item), "amount_rmb": str(allocations.get(_item_key(item)) or "0.00")}
        for item in fee_allocation_service.resolve_eligible_items(fee, items)
    ] if allocation.get("status") == "ALLOCATED" else []
    return result


def _component_rows(fee: dict, components: list[dict]) -> list[dict]:
    key = _fee_key(fee)
    name = str(fee.get("name") or "")
    return [
        dict(row)
        for row in components or []
        if bool(row.get("is_active", 1))
        and str(row.get("status") or "").upper() == "CONFIRMED"
        and str(row.get("cost_effect") or "COST").upper() == "COST"
        and (str(row.get("fee_rule") or "") == name or str(row.get("logical_fee_key") or "") == key)
    ]


def _evidence_profile(fee: dict, components: list[dict], fx_context: dict, items: list[dict]) -> dict:
    if _fee_key(fee) not in EVIDENCE_PRIORITY_FEES:
        return {"locked": False, "rows": [], "amount_rmb": Decimal("0"), "issue": ""}
    rows = _component_rows(fee, components)
    amounts = [_decimal(row.get("amount_rmb")) for row in rows]
    if not rows or any(value is None or value < 0 for value in amounts):
        return {"locked": False, "rows": rows, "amount_rmb": Decimal("0"), "issue": "AMOUNT_INVALID" if rows else ""}
    valid_keys = {_item_key(row) for row in items or []}
    names = {str(row.get("name") or ""): _item_key(row) for row in items or []}
    matched_keys = [
        str(row.get("stable_line_key") or "")
        if str(row.get("stable_line_key") or "") in valid_keys
        else names.get(str(row.get("item") or ""), "")
        for row in rows
    ]
    if any(not key or key not in valid_keys for key in matched_keys):
        return {"locked": False, "rows": rows, "amount_rmb": sum(amounts, Decimal("0")), "issue": "SKU_MATCH_INVALID"}
    converted = cost_preview_service.convert_fee_amount_to_rmb(fee, fx_context or {})
    fee_total = _decimal(converted.get("amount_rmb")) if converted.get("ok") else None
    component_total = sum((value or Decimal("0") for value in amounts), Decimal("0"))
    locked = fee_total is not None and abs(fee_total - component_total) <= Decimal("0.005")
    return {"locked": locked, "rows": rows, "amount_rmb": component_total,
            "issue": "" if locked else "TOTAL_MISMATCH"}


def _suggestion_id(fingerprint: str, fee_key: str) -> str:
    return "trial:" + hashlib.sha256(f"{fingerprint}:{fee_key}".encode("utf-8")).hexdigest()[:24]


def build_input_fingerprint(*, context: dict, items: list[dict], fees: list[dict], fx_context: dict,
                            fee_components: list[dict] | None = None) -> str:
    payload = {
        "schema": INPUT_SCHEMA_VERSION,
        "context": context,
        "items": items,
        "fees": fees,
        "fx_context": fx_context,
        "fee_components": fee_components or [],
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def build_cost_trial_review_draft(
    *,
    items: list[dict],
    fees: list[dict],
    fx_context: dict,
    context: dict,
    fee_components: list[dict] | None = None,
    ai_result: dict | None = None,
) -> dict:
    """Build the browser-safe proposal. AI chooses bases; it never supplies allocations."""

    components = list(fee_components or [])
    fingerprint = build_input_fingerprint(
        context=context,
        items=items,
        fees=fees,
        fx_context=fx_context,
        fee_components=components,
    )
    counted = [fee for fee in fees or [] if requires_ai_allocation(fee)]
    ai = ai_result if ai_result is not None else allocation_service.suggest_allocation_rules_with_ai(
        items=items,
        candidate_rules=counted,
        context={
            **context,
            "retrieval_context": [],
            "retrieval_version": "",
        },
    )
    ai_by_key = {_fee_key(row): row for row in (ai.get("rules") or [])}
    suggestions = []
    for fee in counted:
        key = _fee_key(fee)
        recommended = str((ai_by_key.get(key) or fee).get("allocation_basis") or "goods_value")
        if recommended not in BASIS_ORDER:
            recommended = "goods_value"
        profiles = {basis: _basis_profile(fee, items, basis) for basis in BASIS_ORDER}
        evidence = _evidence_profile(fee, components, fx_context, items)
        evidence_blocks = evidence.get("issue") in {"SKU_MATCH_INVALID", "AMOUNT_INVALID"}
        available = [
            _alternative_profile(fee, items, fx_context, profiles[basis])
            for basis in BASIS_ORDER
            if profiles[basis]["available"]
        ]
        recommendation_available = profiles[recommended]["available"]
        ai_row = ai_by_key.get(key) or {}
        evidence_summary = [
            {
                "component_id": str(row.get("name") or ""),
                "evidence": str(row.get("evidence") or ""),
                "attachment": str(row.get("attachment") or ""),
                "stable_line_key": str(row.get("stable_line_key") or ""),
                "tax_code": str(row.get("tax_code") or ""),
                "hs_code": str(row.get("hs_code") or ""),
                "amount_rmb": format(_decimal(row.get("amount_rmb")) or Decimal("0"), ".2f"),
                "source_evidence": _json_dict(row.get("source_evidence_json")),
            }
            for row in evidence["rows"]
        ]
        suggestions.append(
            {
                "suggestion_id": _suggestion_id(fingerprint, key),
                "fee_key": key,
                "rule_name": str(fee.get("name") or ""),
                "expense_category": str(fee.get("expense_category") or key),
                "currency": str(fee.get("currency") or "RMB"),
                "amount": str(fee.get("amount") or "0"),
                "scope_type": str(fee.get("scope_type") or "ALL_ITEMS").upper(),
                "scope_item_keys": [_item_key(row) for row in fee_allocation_service.resolve_eligible_items(fee, items)],
                "recommended_basis": recommended,
                "recommended_basis_label": BASIS_LABELS[recommended],
                "recommended_basis_available": recommendation_available,
                "confidence": str(ai_row.get("ai_confidence") or ai_row.get("confidence") or "0"),
                "reason": str(ai_row.get("remark") or ai_row.get("reason") or ai.get("reason") or ""),
                "basis_profiles": list(profiles.values()),
                "available_alternatives": available,
                "missing_fields": [] if recommendation_available else [profiles[recommended]["field"]],
                "requires_temporary_basis": not evidence["locked"] and not recommendation_available and bool(available),
                "requires_user_choice": not evidence["locked"] and not evidence_blocks,
                "blocked": evidence_blocks or (not evidence["locked"] and not available),
                "evidence_locked": evidence["locked"],
                "evidence_component_count": len(evidence["rows"]),
                "evidence_amount_rmb": format(evidence["amount_rmb"], ".2f"),
                "evidence_issue": evidence.get("issue") or "",
                "evidence_summary": evidence_summary,
            }
        )
    return {
        "schema_version": 1,
        "input_fingerprint": fingerprint,
        "model": str(ai.get("model") or ""),
        "ai_status": str(ai.get("action") or ("suggested" if ai.get("ok") else "failed")),
        "ai_ok": bool(ai.get("ok")),
        "ai_warning": "" if ai.get("ok") else str(ai.get("reason") or "AI 未完成建议。"),
        "summary": str(ai.get("summary") or ""),
        "fee_suggestions": suggestions,
        "trial_context": {
            "transport_mode": str(context.get("transport_mode") or ""),
            "project": str(context.get("project") or context.get("project_collection")
                           or next((row.get("project_collection") for row in items if row.get("project_collection")), "")),
            "supplier": str(context.get("supplier") or context.get("vendor")
                            or next((row.get("supplier") for row in items if row.get("supplier")), "")),
        },
        "retrieval_context": [],
        "retrieval_version": "",
    }


def _selection_map(draft: dict, selections: Any) -> dict[str, dict]:
    if isinstance(selections, str):
        try:
            selections = json.loads(selections or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("试算选择格式无效。") from exc
    if not isinstance(selections, list):
        raise ValueError("试算选择格式无效。")
    proposals = {row["suggestion_id"]: row for row in draft.get("fee_suggestions") or []}
    invalid_evidence = next(
        (row for row in proposals.values() if row.get("evidence_issue") == "SKU_MATCH_INVALID"),
        None,
    )
    if invalid_evidence:
        raise ValueError(f"费用“{invalid_evidence['expense_category']}”的凭证 SKU 匹配无效，请先完成人工匹配。")
    invalid_amount = next(
        (row for row in proposals.values() if row.get("evidence_issue") == "AMOUNT_INVALID"),
        None,
    )
    if invalid_amount:
        raise ValueError(f"费用“{invalid_amount['expense_category']}”的凭证金额无效，请先处理凭证。")
    selected: dict[str, dict] = {}
    for raw in selections:
        row = dict(raw or {})
        proposal = proposals.get(str(row.get("suggestion_id") or ""))
        if not proposal:
            raise ValueError("试算建议已失效，请重新运行 AI。")
        basis = str(row.get("basis") or "")
        available = {value["basis"] for value in proposal.get("available_alternatives") or []}
        if basis not in available:
            raise ValueError(f"分摊口径 {basis or '-'} 当前不可用。")
        reason = str(row.get("reason") or "").strip()[:500]
        modified = basis != proposal["recommended_basis"]
        if modified and not reason:
            raise ValueError(f"修改费用“{proposal['expense_category']}”的 AI 建议时必须填写原因。")
        selected[proposal["fee_key"]] = {
            "suggestion_id": proposal["suggestion_id"],
            "fee_key": proposal["fee_key"],
            "expense_category": proposal["expense_category"],
            "basis": basis,
            "reason": reason,
            "temporary": modified and not bool(proposal.get("recommended_basis_available")),
            "modified_ai_suggestion": modified,
            "ai_recommended_basis": proposal["recommended_basis"],
            "ai_confidence": proposal.get("confidence") or "0",
        }
    for proposal in proposals.values():
        if proposal.get("evidence_locked"):
            selected[proposal["fee_key"]] = {
                "suggestion_id": proposal["suggestion_id"],
                "fee_key": proposal["fee_key"],
                "expense_category": proposal["expense_category"],
                "basis": next((row["basis"] for row in proposal.get("available_alternatives") or []), "goods_value"),
                "reason": "税费／清关凭证已提供逐 SKU 分项，凭证优先。",
                "temporary": False,
                "evidence_locked": True,
                "ai_recommended_basis": proposal["recommended_basis"],
                "ai_confidence": proposal.get("confidence") or "0",
            }
        elif proposal.get("requires_user_choice") and proposal["fee_key"] not in selected:
            raise ValueError(f"请确认费用“{proposal['expense_category']}”的分摊口径。")
    return selected


def project_fees_for_trial(fees: list[dict], choices: dict[str, dict], *, for_save: bool = False) -> list[dict]:
    projected = []
    for source in fees or []:
        fee = dict(source or {})
        choice = choices.get(_fee_key(fee))
        if not choice or choice.get("evidence_locked"):
            projected.append(fee)
        elif for_save and not choice.get("temporary"):
            projected.append({**fee, "allocation_basis": choice["basis"], "basis_field": choice["basis"]})
        else:
            projected.append({**fee, "trial_allocation_basis": choice["basis"]})
    return projected


def annotate_saved_trial_result(result: dict, trial_review: dict) -> dict:
    """Attach the auditable AI decision and preserve temporary-result restrictions."""

    result["trial_review"] = trial_review
    temporary = bool(trial_review.get("is_temporary"))
    result.setdefault("summary", {})["is_temporary"] = temporary
    snapshot = result.setdefault("summary_snapshot", {})
    snapshot["ai_cost_trial"] = trial_review
    snapshot["is_temporary"] = temporary
    comprehensive = snapshot.setdefault("comprehensive_cost", {})
    comprehensive["trial_review"] = trial_review
    if temporary:
        reason = {
            "reason_code": "TEMPORARY_ALLOCATION_BASIS",
            "message": "本次使用暂行分摊口径，补齐资料后需按 AI 建议重新试算。",
        }
        incomplete = result.setdefault("incomplete_reasons", [])
        if not any(row.get("reason_code") == reason["reason_code"] for row in incomplete):
            incomplete.append(reason)
        result["summary"]["is_complete"] = False
        snapshot["formal_confirmation_blocked"] = True
        snapshot["formal_confirmation_block_reason"] = reason["reason_code"]
    return result


def preview_selected_cost_trial(
    *,
    items: list[dict],
    fees: list[dict],
    fx_context: dict,
    fee_components: list[dict],
    draft: dict,
    selections: Any,
) -> dict:
    choices = _selection_map(draft, selections)
    projected_fees = project_fees_for_trial(fees, choices)
    result = cost_preview_service.preview_comprehensive_cost_data(
        items,
        projected_fees,
        fx_context,
        fee_components=fee_components,
    )
    selected_rows = [choices[key] for key in sorted(choices)]
    temporary = any(row.get("temporary") for row in selected_rows)
    if temporary:
        result["incomplete_reasons"].append(
            {
                "reason_code": "TEMPORARY_ALLOCATION_BASIS",
                "message": "本次使用暂行分摊口径，补齐资料后需按 AI 建议重新试算。",
            }
        )
        result["summary"]["is_complete"] = False
    result["trial_review"] = {
        "schema_version": 1,
        "input_fingerprint": draft.get("input_fingerprint") or "",
        "model": draft.get("model") or "",
        "fee_choices": selected_rows,
        "evidence_locks": [
            {
                "suggestion_id": proposal.get("suggestion_id") or "",
                "fee_key": proposal.get("fee_key") or "",
                "amount_rmb": proposal.get("evidence_amount_rmb") or "0.00",
                "component_count": int(proposal.get("evidence_component_count") or 0),
                "components": proposal.get("evidence_summary") or [],
            }
            for proposal in (draft.get("fee_suggestions") or [])
            if proposal.get("evidence_locked")
        ],
        "is_temporary": temporary,
        "retrieval_context": draft.get("retrieval_context") or [],
        "retrieval_version": draft.get("retrieval_version") or "",
    }
    result["preview_token"] = _sign_preview(
        {"fingerprint": draft.get("input_fingerprint"), "choices": selected_rows}
    )
    return result


def _repo(repository: Any | None):
    return repository or FrappeCostTrialAIRepository()


def _default_enqueue(run_id: str) -> None:
    if frappe is None:
        raise RuntimeError("当前未连接 Frappe 长任务队列。")
    frappe.enqueue(
        "overseas_costing.services.cost_trial_ai_service.execute_cost_trial_ai_review",
        queue="long",
        enqueue_after_commit=True,
        job_name=f"cost-trial-ai:{run_id}",
        run_id=run_id,
    )


def _input_fingerprint(inputs: dict) -> str:
    return build_input_fingerprint(
        context=inputs["context"],
        items=inputs["items"],
        fees=inputs["fees"],
        fx_context=inputs["fx_context"],
        fee_components=inputs.get("fee_components") or [],
    )


def start_cost_trial_ai_review(
    batch_name: str,
    version_name: str | None = None,
    *,
    edit_token: str = "",
    expected_modified: str = "",
    force: bool = False,
    repository: Any | None = None,
    enqueue: Any | None = None,
) -> dict:
    if not cost_trial_ai_enabled():
        raise RuntimeError("AI 成本试算功能开关未启用，请暂用兼容计算接口。")
    repo = _repo(repository)
    try:
        inputs = repo.load_trial_inputs(
            str(batch_name), str(version_name or "") or None,
            edit_token=edit_token, expected_modified=expected_modified, write=True,
        )
        fingerprint = _input_fingerprint(inputs)
        context = inputs["context"]
        batch = str(context.get("batch_name") or context.get("batch") or batch_name)
        version = str(context.get("version_name") or context.get("version") or version_name or "")
        active = repo.find_active(batch, version, fingerprint)
        if active:
            repo.commit()
            return {
                "ok": True,
                "run_id": str(active.get("name") or ""),
                "status": str(active.get("status") or ""),
                "reused": True,
                "reuse_reason": "RUNNING",
                "progress_revision": int(active.get("progress_revision") or 0),
            }
        reusable = None if force else repo.find_reusable(batch, version, fingerprint)
        if reusable:
            repo.commit()
            return {
                "ok": True,
                "run_id": str(reusable.get("name") or ""),
                "status": str(reusable.get("status") or "READY"),
                "reused": True,
                "reuse_reason": "SAME_INPUT",
                "progress_revision": int(reusable.get("progress_revision") or 0),
            }
        created = repo.create_run(
            {
                "batch": batch,
                "version": version,
                "operator_name": _session_user(),
                "status": "QUEUED",
                "input_fingerprint": fingerprint,
                "progress_revision": 0,
                "progress_step": "等待 AI 分析",
                "progress_percent": 0,
                "model": "",
                "prompt_version": PROMPT_VERSION,
                "draft_json": {},
                "error_message": "",
            }
        )
        run_id = str(created.get("name") or "")
        (enqueue or _default_enqueue)(run_id)
        repo.commit()
        return {"ok": True, "run_id": run_id, "status": "QUEUED", "reused": False, "progress_revision": 0}
    except Exception:
        repo.rollback()
        raise


def execute_cost_trial_ai_review(
    run_id: str,
    *,
    repository: Any | None = None,
    ai_suggester: Any | None = None,
) -> dict:
    repo = _repo(repository)
    run = repo.get_run(str(run_id or ""))
    if str(run.get("status") or "") not in {"QUEUED", "RUNNING"}:
        return {"ok": True, "run_id": str(run_id), "status": str(run.get("status") or "")}
    try:
        repo.save_run(str(run_id), status="RUNNING", progress_step="DeepSeek 正在分析费用口径", progress_percent=30)
        inputs = repo.load_trial_inputs(
            str(run.get("batch") or ""), str(run.get("version") or "") or None,
            write=False, trusted=True,
        )
        if _input_fingerprint(inputs) != str(run.get("input_fingerprint") or ""):
            repo.save_run(str(run_id), status="STALE", progress_step="试算输入已变化", progress_percent=100)
            repo.commit()
            return {"ok": False, "run_id": str(run_id), "status": "STALE"}
        # Do not keep cost rows locked while waiting for the external model.
        repo.commit()
        candidate_fees = [fee for fee in inputs["fees"] if requires_ai_allocation(fee)]
        suggester = ai_suggester or allocation_service.suggest_allocation_rules_with_ai
        ai = suggester(
            items=inputs["items"],
            candidate_rules=candidate_fees,
            context={
                **inputs["context"],
                "retrieval_context": [],
                "retrieval_version": "",
            },
        )
        draft = build_cost_trial_review_draft(
            items=inputs["items"], fees=inputs["fees"], fx_context=inputs["fx_context"],
            context=inputs["context"], fee_components=inputs.get("fee_components") or [], ai_result=ai,
        )
        refreshed = repo.load_trial_inputs(
            str(run.get("batch") or ""), str(run.get("version") or "") or None,
            write=False, trusted=True,
        )
        if _input_fingerprint(refreshed) != str(run.get("input_fingerprint") or ""):
            repo.save_run(str(run_id), status="STALE", progress_step="试算输入已变化", progress_percent=100)
            repo.commit()
            return {"ok": False, "run_id": str(run_id), "status": "STALE"}
        repo.save_run(
            str(run_id), status="READY", progress_step="AI 试算建议已生成", progress_percent=100,
            model=draft.get("model") or "", draft_json=draft, error_message="", completed_at=_now(),
        )
        repo.commit()
        return {"ok": True, "run_id": str(run_id), "status": "READY"}
    except Exception as exc:
        repo.rollback()
        try:
            repo.save_run(str(run_id), status="FAILED", progress_step="AI 试算失败", progress_percent=100,
                          error_message=str(exc)[:2000])
            repo.commit()
        except Exception:
            repo.rollback()
        return {"ok": False, "run_id": str(run_id), "status": "FAILED", "message": str(exc)}


def get_cost_trial_ai_review_status(
    batch_name: str,
    run_id: str,
    *,
    after_revision: int | None = None,
    repository: Any | None = None,
) -> dict:
    run = _repo(repository).get_run(str(run_id or ""))
    if str(run.get("batch") or "") != str(batch_name or ""):
        raise ValueError("AI 试算任务不属于当前批次。")
    revision = int(run.get("progress_revision") or 0)
    status = str(run.get("status") or "")
    if after_revision is not None and int(after_revision) == revision and status in {"QUEUED", "RUNNING"}:
        return {"ok": True, "run_id": run_id, "status": status, "progress_revision": revision, "unchanged": True}
    return {
        "ok": True,
        "run_id": str(run.get("name") or run_id),
        "batch_name": str(run.get("batch") or ""),
        "version_name": str(run.get("version") or ""),
        "status": status,
        "progress_revision": revision,
        "progress_step": str(run.get("progress_step") or ""),
        "progress_percent": int(run.get("progress_percent") or 0),
        "model": str(run.get("model") or ""),
        "prompt_version": str(run.get("prompt_version") or ""),
        "error_message": str(run.get("error_message") or ""),
        "draft": _json_dict(run.get("draft_json")),
        "unchanged": False,
    }


def _load_current_run_inputs(repo: Any, batch_name: str, run: dict, *, write: bool = False,
                             edit_token: str = "", expected_modified: str = "") -> dict:
    inputs = repo.load_trial_inputs(
        str(batch_name), str(run.get("version") or "") or None,
        edit_token=edit_token, expected_modified=expected_modified, write=write, trusted=not write,
    )
    if _input_fingerprint(inputs) != str(run.get("input_fingerprint") or ""):
        repo.save_run(str(run.get("name") or ""), status="STALE", progress_step="试算输入已变化", progress_percent=100)
        repo.commit()
        raise ValueError("试算输入已变化，请重新运行 AI。")
    return inputs


def preview_cost_trial(
    batch_name: str,
    run_id: str,
    selections: Any,
    *,
    repository: Any | None = None,
) -> dict:
    repo = _repo(repository)
    run = repo.get_run(str(run_id or ""))
    if str(run.get("batch") or "") != str(batch_name or ""):
        raise ValueError("AI 试算任务不属于当前批次。")
    if str(run.get("status") or "") != "READY":
        raise ValueError("AI 试算建议尚未就绪。")
    inputs = _load_current_run_inputs(repo, batch_name, run)
    preview = preview_selected_cost_trial(
        items=inputs["items"], fees=inputs["fees"], fx_context=inputs["fx_context"],
        fee_components=inputs.get("fee_components") or [], draft=_json_dict(run.get("draft_json")), selections=selections,
    )
    preview["run_id"] = str(run_id)
    return preview


def confirm_cost_trial(
    batch_name: str,
    run_id: str,
    preview_token: str,
    selections: Any,
    *,
    edit_token: str,
    expected_modified: str,
    repository: Any | None = None,
) -> dict:
    repo = _repo(repository)
    run = repo.get_run(str(run_id or ""))
    if str(run.get("batch") or "") != str(batch_name or ""):
        raise ValueError("AI 试算任务不属于当前批次。")
    if str(run.get("status") or "") != "READY":
        raise ValueError("AI 试算建议已不可确认。")
    try:
        inputs = _load_current_run_inputs(
            repo, batch_name, run, write=True,
            edit_token=edit_token, expected_modified=expected_modified,
        )
        preview = preview_selected_cost_trial(
            items=inputs["items"], fees=inputs["fees"], fx_context=inputs["fx_context"],
            fee_components=inputs.get("fee_components") or [], draft=_json_dict(run.get("draft_json")), selections=selections,
        )
        if not hmac.compare_digest(str(preview.get("preview_token") or ""), str(preview_token or "")):
            raise ValueError("试算预览已失效，请重新预览。")
        trial_review = {**preview["trial_review"], "run_id": str(run_id), "confirmed_by": _session_user()}
        saved = repo.save_calculation(inputs, preview, trial_review)
        saved["trial_review"] = trial_review
        repo.save_run(str(run_id), status="CONFIRMED", progress_step="AI 试算已确认", progress_percent=100,
                      selection_json=trial_review, confirmed_at=_now())
        repo.commit()
        return saved
    except Exception:
        repo.rollback()
        raise


def discard_cost_trial_ai_review(
    batch_name: str,
    run_id: str,
    *,
    repository: Any | None = None,
) -> dict:
    repo = _repo(repository)
    run = repo.get_run(str(run_id or ""))
    if str(run.get("batch") or "") != str(batch_name or ""):
        raise ValueError("AI 试算任务不属于当前批次。")
    status = str(run.get("status") or "")
    if status == "CONFIRMED":
        return {"ok": True, "run_id": str(run_id), "status": "CONFIRMED"}
    if status != "DISCARDED":
        repo.save_run(str(run_id), status="DISCARDED", progress_step="已放弃试算", progress_percent=100)
        repo.commit()
    return {"ok": True, "run_id": str(run_id), "status": "DISCARDED"}


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _session_user() -> str:
    return str(getattr(getattr(frappe, "session", None), "user", "") or "") if frappe is not None else ""


def _now() -> str:
    if frappe is not None:
        return str(frappe.utils.now())
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class FrappeCostTrialAIRepository:  # pragma: no cover - exercised in Frappe integration
    RUN_DOCTYPE = "Overseas Cost Trial AI Run"
    RUN_FIELDS = [
        "name", "batch", "version", "operator_name", "status", "input_fingerprint",
        "prompt_version", "model", "progress_revision", "progress_step", "progress_percent",
        "draft_json", "selection_json", "error_message", "started_at", "completed_at", "confirmed_at",
    ]

    def __init__(self):
        if frappe is None:
            raise RuntimeError("当前未连接 Frappe 数据库。")

    def load_trial_inputs(self, batch_name, version_name, *, edit_token="", expected_modified="",
                          write=False, trusted=False):
        cost_repo = cost_preview_service.FrappeCostRepository()
        context, items, fees, fx_context = cost_repo.lock_and_load(
            batch_name, version_name,
            edit_token=edit_token, expected_modified=expected_modified,
            trusted=bool(trusted or not write),
        )
        public_context = {
            "batch_name": context["batch"],
            "version_name": context["version"],
            "transport_mode": context.get("transport_mode") or "",
            "batch_modified": context.get("batch_modified") or "",
            "version_modified": context.get("version_modified") or "",
            "fx_usd_to_rmb": fx_context.get("fx_usd_to_rmb"),
            "fx_rmb_to_mxn": fx_context.get("fx_rmb_to_mxn"),
        }
        return {
            "context": {**context, **public_context},
            "items": items,
            "fees": fees,
            "fx_context": fx_context,
            "fee_components": cost_repo.load_fee_components(context),
        }

    def find_active(self, batch_name, version_name, fingerprint):
        rows = frappe.get_all(
            self.RUN_DOCTYPE,
            filters={"batch": batch_name, "version": version_name, "input_fingerprint": fingerprint,
                     "status": ["in", ["QUEUED", "RUNNING"]]},
            fields=self.RUN_FIELDS, order_by="creation desc", limit_page_length=1,
        )
        return self._present(rows[0]) if rows else None

    def find_reusable(self, batch_name, version_name, fingerprint):
        rows = frappe.get_all(
            self.RUN_DOCTYPE,
            filters={"batch": batch_name, "version": version_name, "input_fingerprint": fingerprint, "status": "READY"},
            fields=self.RUN_FIELDS, order_by="creation desc", limit_page_length=1,
        )
        return self._present(rows[0]) if rows else None

    def create_run(self, values):
        payload = {key: _json(value) if key.endswith("_json") and not isinstance(value, str) else value
                   for key, value in values.items()}
        payload.setdefault("started_at", _now())
        doc = frappe.get_doc({"doctype": self.RUN_DOCTYPE, **payload})
        doc.insert(ignore_permissions=True)
        return self.get_run(doc.name)

    def get_run(self, run_id):
        row = frappe.db.get_value(self.RUN_DOCTYPE, run_id, self.RUN_FIELDS, as_dict=True)
        if not row:
            raise ValueError("未找到 AI 试算任务。")
        return self._present(row)

    def save_run(self, run_id, **values):
        locked = frappe.db.sql(
            f"SELECT name,progress_revision FROM `tab{self.RUN_DOCTYPE}` WHERE name=%s FOR UPDATE",
            (run_id,), as_dict=True,
        )
        if not locked:
            raise ValueError("未找到 AI 试算任务。")
        payload = {key: _json(value) if key.endswith("_json") and not isinstance(value, str) else value
                   for key, value in values.items()}
        payload["progress_revision"] = int(locked[0].get("progress_revision") or 0) + 1
        frappe.db.set_value(self.RUN_DOCTYPE, run_id, payload, update_modified=True)
        return self.get_run(run_id)

    def save_calculation(self, inputs, preview, trial_review):
        choices = {row["suggestion_id"]: row for row in trial_review.get("fee_choices") or []}
        draft = _json_dict(self.get_run(trial_review["run_id"]).get("draft_json"))
        proposal_by_id = {row["suggestion_id"]: row for row in draft.get("fee_suggestions") or []}
        fee_choice_by_key = {}
        for suggestion_id, choice in choices.items():
            proposal = proposal_by_id.get(suggestion_id) or {}
            if proposal.get("fee_key"):
                fee_choice_by_key[proposal["fee_key"]] = choice
        projected_fees = project_fees_for_trial(inputs["fees"], fee_choice_by_key, for_save=True)
        result = cost_preview_service.build_saved_cost_data(
            inputs["items"], projected_fees, inputs["fx_context"], inputs["context"]["transport_mode"],
            fee_components=inputs.get("fee_components") or [],
        )
        annotate_saved_trial_result(result, trial_review)
        cost_repo = cost_preview_service.FrappeCostRepository()
        cost_repo.assert_unchanged(inputs["context"])
        modified = cost_repo.save(inputs["context"], result)
        for fee_key, choice in fee_choice_by_key.items():
            if choice.get("temporary") or choice.get("evidence_locked"):
                continue
            fee = next((row for row in inputs["fees"] if _fee_key(row) == fee_key), None)
            if fee and fee.get("name"):
                frappe.db.set_value(
                    "Overseas Cost Allocation Rule", fee["name"],
                    {"allocation_basis": choice["basis"], "remark": f"AI 试算确认：{choice.get('reason') or ''}"[:500]},
                    update_modified=False,
                )
        result.pop("item_updates", None)
        return {
            **result, "ok": True, "saved": True, "read_only": False,
            "batch_name": inputs["context"]["batch"], "version_name": inputs["context"]["version"],
            "batch_modified": modified, "transport_mode": inputs["context"]["transport_mode"],
            "message": "AI 口径已确认，试算结果已保存。",
        }

    def commit(self):
        frappe.db.commit()

    def rollback(self):
        frappe.db.rollback()

    @staticmethod
    def _present(row):
        result = dict(row or {})
        result["draft_json"] = _json_dict(result.get("draft_json"))
        result["selection_json"] = _json_dict(result.get("selection_json"))
        return result
