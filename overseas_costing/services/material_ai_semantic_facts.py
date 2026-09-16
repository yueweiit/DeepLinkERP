"""Fixed semantic-fact policies for material AI payment evidence.

This module intentionally is not a rule language.  It converts server-owned
monthly-payment rows into a small, stable vocabulary before any model sees
the evidence.  Matching is limited to the current material baseline.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import unicodedata

from .logistics_settlement.model import digest


POLICY = "material-ai-semantic-facts-1"
PHYSICAL_FIELDS = (
    "package_count",
    "gross_weight_kg",
    "chargeable_weight_kg",
    "volume_m3",
)


def _identity(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def _decimal_text(value: object) -> str:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if not number.is_finite():
        return ""
    return format(number.normalize(), "f")


def _material_key(item: dict) -> str:
    return str(
        item.get("stable_line_key")
        or (f"legacy:{item.get('name')}" if item.get("name") else "")
    ).strip()


def _target(item: dict) -> dict:
    return {
        "item_name": str(item.get("name") or ""),
        "material_key": _material_key(item),
        "material_code": str(item.get("material_code") or "").strip(),
        "product_name": str(item.get("product_name") or "").strip(),
    }


def _provenance(source: dict, line: dict) -> dict:
    evidence = line.get("evidence") if isinstance(line.get("evidence"), dict) else {}
    return {
        "source_id": str(source.get("id") or source.get("source_id") or ""),
        "document_id": str(evidence.get("document_id") or ""),
        "file_name": str(evidence.get("file_name") or ""),
        "sheet": str(evidence.get("sheet") or ""),
        "row": evidence.get("row"),
        "line_id": str(line.get("id") or ""),
        "line_key": str(line.get("line_key") or ""),
    }


def _dedupe_key(source: dict, line: dict) -> tuple[str, str, str, str]:
    evidence = line.get("evidence") if isinstance(line.get("evidence"), dict) else {}
    document_identity = str(
        evidence.get("document_id")
        or evidence.get("file_id")
        or evidence.get("sha256")
        or evidence.get("file_name")
        or source.get("snapshot")
        or source.get("id")
        or ""
    )
    business_identifier = str(
        line.get("waybill")
        or line.get("line_key")
        or line.get("approval_no")
        or line.get("charge_key")
        or ""
    )
    return (
        _identity(document_identity),
        _identity(evidence.get("sheet")),
        str(evidence.get("row") or ""),
        _identity(business_identifier),
    )


def _stable_row_identity(source: dict, line: dict, provenance: dict) -> dict:
    """Identity survives archive/internal row-ID rewrites."""

    return {
        "source_id": _identity(source.get("id") or source.get("source_id")),
        "document_id": _identity(provenance.get("document_id") or provenance.get("file_name")),
        "sheet": _identity(provenance.get("sheet")),
        "row": str(provenance.get("row") or ""),
        "business_identifier": _identity(
            line.get("waybill")
            or line.get("line_key")
            or line.get("approval_no")
            or line.get("charge_key")
            or ""
        ),
    }
def _line_goods(line: dict) -> list[dict]:
    goods = [deepcopy(row) for row in line.get("goods") or [] if isinstance(row, dict)]
    if goods:
        return goods
    cargo_text = str(line.get("cargo_text") or "").strip()
    if not cargo_text:
        return []
    try:
        from .logistics_settlement.freight_packing import text_goods

        return text_goods(cargo_text, deepcopy(line.get("evidence") or {}))
    except (TypeError, ValueError):
        return []


def _match_targets(items: list[dict], line: dict) -> tuple[list[dict], str, str]:
    from .logistics_settlement.freight_lines import packing_for_line

    packing = packing_for_line(line)
    goods = _line_goods(line)
    raw_codes = [
        *(packing.get("material_code_hints") or []),
        line.get("material_code"),
        *(row.get("material_code") for row in goods),
    ]
    code_index: dict[str, list[dict]] = {}
    for item in items:
        code = _identity(item.get("material_code"))
        if code:
            code_index.setdefault(code, []).append(item)
    matched_by_code = []
    seen_keys = set()
    for raw_code in raw_codes:
        for item in code_index.get(_identity(raw_code), []):
            key = _material_key(item)
            if key and key not in seen_keys:
                matched_by_code.append(item)
                seen_keys.add(key)
    if matched_by_code:
        if len(matched_by_code) == 1:
            return matched_by_code, "exact_code", "精确物料编码命中当前批次基线。"
        return matched_by_code, "exact_code", "同一证据行命中多个当前物料编码，需要核对共享包装。"
    if any(_identity(value) for value in raw_codes):
        return [], "foreign_code", "证据行已提供物料编码，但未命中当前批次基线；不使用名称降级放宽。"

    name_index: dict[str, list[dict]] = {}
    for item in items:
        name = _identity(item.get("product_name"))
        if name:
            name_index.setdefault(name, []).append(item)
    raw_names = [line.get("product_name"), *(row.get("product_name") for row in goods)]
    name_matches = []
    ambiguous_name = False
    for raw_name in raw_names:
        candidates = name_index.get(_identity(raw_name), [])
        if len(candidates) == 1:
            item = candidates[0]
            if _material_key(item) not in {_material_key(row) for row in name_matches}:
                name_matches.append(item)
        elif len(candidates) > 1:
            ambiguous_name = True
    if len(name_matches) == 1 and not ambiguous_name:
        return name_matches, "unique_name", "未提供物料编码，规范化物料名称在当前批次中唯一。"
    if ambiguous_name or len(name_matches) > 1:
        return name_matches, "ambiguous_name", "规范化物料名称不唯一，不自动归属。"
    return [], "no_baseline_match", "证据行未精确命中当前批次的物料编码或唯一物料名称。"


def _physical(line: dict) -> dict:
    from .logistics_settlement.freight_lines import packing_for_line

    packing = packing_for_line(line)
    values = {}
    for field in PHYSICAL_FIELDS:
        value = _decimal_text(packing.get(field))
        if value:
            values[field] = value
    dimensions = [_decimal_text(value) for value in packing.get("dimensions_cm") or []]
    if len(dimensions) == 3 and all(dimensions):
        values["dimensions_cm"] = dimensions
    return values


def _resolved_by_item_identifier(item: dict, facts: list[dict]) -> bool:
    identifiers = {
        _identity(item.get(field))
        for field in ("waybill", "tracking_no", "tracking_number", "awb")
        if _identity(item.get(field))
    }
    if not identifiers:
        try:
            metadata = json.loads(str(item.get("extra_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        identifiers = {
            _identity(metadata.get(field))
            for field in ("waybill", "tracking_no", "tracking_number", "awb")
            if _identity(metadata.get(field))
        }
    return bool(identifiers) and sum(_identity(fact.get("waybill")) in identifiers for fact in facts) == 1


def build_payment_facts(items: list[dict], source: dict, lines: list[dict]) -> list[dict]:
    """Normalize selected payment rows against the current material baseline."""

    baseline = [row for row in items or [] if not int(row.get("is_excluded") or 0)]
    unique_lines = {}
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        unique_lines.setdefault(_dedupe_key(source, line), line)
    ordered_lines = sorted(
        unique_lines.values(),
        key=lambda line: (
            str((line.get("evidence") or {}).get("document_id") or ""),
            str((line.get("evidence") or {}).get("sheet") or ""),
            int((line.get("evidence") or {}).get("row") or 0),
            str(line.get("waybill") or ""),
        ),
    )
    physical_facts = []
    component_facts = []
    for line in ordered_lines:
        targets, match_method, reason = _match_targets(baseline, line)
        if len(targets) == 1:
            scope_status = "in_scope"
        elif len(targets) > 1:
            scope_status = "ambiguous"
        elif match_method == "ambiguous_name":
            scope_status = "ambiguous"
        else:
            scope_status = "out_of_scope"
        provenance = _provenance(source, line)
        stable_row_identity = _stable_row_identity(source, line, provenance)
        material_targets = [_target(item) for item in targets]
        waybill = str(line.get("waybill") or "").strip()
        package_identity = (
            f"waybill:{_identity(waybill)}"
            if _identity(waybill)
            else digest(POLICY, "package", stable_row_identity)
        )
        process = {
            "source_id": str(source.get("id") or source.get("source_id") or ""),
            "process_instance_id": str(source.get("instance") or source.get("process_instance_id") or ""),
            "approval_no": str(source.get("approval_no") or ""),
            "title": str(source.get("title") or source.get("source_label") or ""),
        }
        evidence_chain = [
            {"kind": "selected_payment_process", **process},
            {"kind": "structured_workbook_row", **provenance},
        ]
        physical = _physical(line)
        if physical:
            fact_id = digest(
                POLICY,
                "payment_physical",
                process,
                stable_row_identity,
                package_identity,
                material_targets,
                physical,
            )
            allowed_actions = []
            if scope_status == "in_scope" and len(material_targets) == 1:
                allowed_actions = [
                    {
                        "action": "item_update",
                        "target_item_name": material_targets[0]["item_name"],
                        "material_key": material_targets[0]["material_key"],
                        "fieldname": field,
                        "value": value,
                    }
                    for field, value in physical.items()
                    if field in PHYSICAL_FIELDS
                ]
            physical_facts.append(
                {
                    "fact_id": fact_id,
                    "fact_kind": "payment_physical",
                    "workflow_stage": "payment",
                    "process": process,
                    "provenance": provenance,
                    "waybill": waybill,
                    "package_identity": package_identity,
                    "material_targets": material_targets,
                    "scope_status": scope_status,
                    "default_eligible": scope_status == "in_scope",
                    "match_method": match_method,
                    "physical": physical,
                    "monetary": {},
                    "evidence_chain": evidence_chain,
                    "reason": reason,
                    "allowed_actions": allowed_actions,
                }
            )
        amount = _decimal_text(line.get("amount"))
        currency = str(line.get("currency") or source.get("currency") or "").strip().upper()
        if amount and currency and scope_status == "in_scope":
            component_id = digest(
                POLICY, "payment_freight_component", process, stable_row_identity,
                package_identity, amount, currency
            )
            component_facts.append(
                {
                    "fact_id": component_id,
                    "fact_kind": "payment_freight_component",
                    "workflow_stage": "payment",
                    "process": process,
                    "provenance": provenance,
                    "waybill": waybill,
                    "package_identity": package_identity,
                    "material_targets": material_targets,
                    "scope_status": "in_scope",
                    "default_eligible": False,
                    "read_only": True,
                    "selection_role": "component",
                    "match_method": match_method,
                    "physical": {},
                    "monetary": {"amount": amount, "currency": currency},
                    "evidence_chain": evidence_chain,
                    "reason": "已选付款工作簿的单行运费组件，仅用于合计。",
                    "allowed_actions": [],
                }
            )

    by_target: dict[str, list[dict]] = {}
    items_by_name = {str(item.get("name") or ""): item for item in baseline}
    for fact in physical_facts:
        if fact["scope_status"] != "in_scope" or len(fact["material_targets"]) != 1:
            continue
        by_target.setdefault(fact["material_targets"][0]["item_name"], []).append(fact)
    for item_name, target_facts in by_target.items():
        if len({fact["package_identity"] for fact in target_facts}) <= 1:
            continue
        if _resolved_by_item_identifier(items_by_name.get(item_name) or {}, target_facts):
            for fact in target_facts:
                if _identity(fact.get("waybill")) != _identity(
                    (items_by_name.get(item_name) or {}).get("waybill")
                ):
                    fact.update(scope_status="out_of_scope", default_eligible=False, allowed_actions=[])
            continue
        for fact in target_facts:
            fact.update(
                scope_status="ambiguous",
                default_eligible=False,
                allowed_actions=[],
                reason="同一当前物料匹配到多个不同运单/包装行，需要人工确认。",
            )

    # If ambiguity invalidated a target, its monetary rows cannot contribute
    # to a default total either.
    eligible_packages = {
        fact["package_identity"]
        for fact in physical_facts
        if fact["scope_status"] == "in_scope" and fact["default_eligible"]
    }
    component_facts = [
        fact for fact in component_facts if fact["package_identity"] in eligible_packages
    ]
    totals = []
    components_by_currency: dict[str, list[dict]] = {}
    for fact in component_facts:
        components_by_currency.setdefault(fact["monetary"]["currency"], []).append(fact)
    for currency, components in sorted(components_by_currency.items()):
        amount = sum((Decimal(fact["monetary"]["amount"]) for fact in components), Decimal("0"))
        component_ids = [fact["fact_id"] for fact in components]
        total_id = digest(POLICY, "payment_freight_total", process, currency, component_ids, amount)
        totals.append(
            {
                "fact_id": total_id,
                "fact_kind": "payment_freight_total",
                "workflow_stage": "payment",
                "process": deepcopy(components[0]["process"]),
                "provenance": {
                    "source_id": components[0]["provenance"]["source_id"],
                    "document_id": components[0]["provenance"]["document_id"],
                    "file_name": components[0]["provenance"]["file_name"],
                    "sheet": components[0]["provenance"]["sheet"],
                    "row": None,
                    "line_id": "",
                    "line_key": "",
                },
                "waybill": "",
                "package_identity": "",
                "material_targets": [
                    target
                    for fact in components
                    for target in fact["material_targets"]
                ],
                "scope_status": "in_scope",
                "default_eligible": True,
                "read_only": False,
                "selection_role": "primary_total",
                "physical": {},
                "monetary": {"amount": format(amount.normalize(), "f"), "currency": currency},
                "component_fact_ids": component_ids,
                "evidence_chain": [
                    evidence
                    for fact in components
                    for evidence in fact["evidence_chain"][-1:]
                ],
                "reason": "同一已选付款工作簿内、同币种的本批次运费行只汇总一次。",
                # Mapping a transport-mode-specific logical fee key belongs to
                # the existing fee policy layer.  Until that layer consumes
                # this fact, the total is authoritative/readable but cannot be
                # applied by model output.
                "allowed_actions": [],
            }
        )
    return [*physical_facts, *component_facts, *totals]


def eligible_physical_facts(facts: list[dict]) -> list[dict]:
    return [
        fact
        for fact in facts or []
        if fact.get("fact_kind") == "payment_physical"
        and fact.get("scope_status") == "in_scope"
        and fact.get("default_eligible")
        and len(fact.get("material_targets") or []) == 1
    ]
