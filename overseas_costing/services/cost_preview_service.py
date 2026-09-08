"""综合成本统一计算；只读预览和保存试算共用同一分摊结果。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json

try:
    import frappe
except Exception:  # pragma: no cover - pure tests do not require Frappe
    frappe = None

from overseas_costing.services import fee_allocation_service, fee_service
from overseas_costing.services.material_input_service import present_material_row
from overseas_costing.services.transport_fee_service import assert_no_duplicate_fees, fee_is_active, mark_duplicate_fees


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), ".2f")


def _unit_money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), ".6f")


def _item_key(item: dict) -> str:
    return str(item.get("stable_line_key") or item.get("name") or item.get("row_no") or "")


def _fee_key(fee: dict) -> str:
    return str(fee.get("logical_fee_key") or fee.get("rule_code") or fee.get("name") or "")


def convert_fee_amount_to_rmb(fee: dict, fx_context: dict) -> dict:
    amount = _decimal(fee.get("amount"))
    if amount is None or amount < 0:
        return {"ok": False, "reason_code": "FEE_AMOUNT_INVALID"}
    currency = str(fee.get("currency") or "RMB").strip().upper()
    if currency not in {"RMB", "CNY", "USD", "MXN"}:
        return {"ok": False, "reason_code": "CURRENCY_UNSUPPORTED", "currency": currency}
    if amount == 0:
        return {"ok": True, "amount_rmb": amount, "rate": None}
    if currency in {"RMB", "CNY"}:
        return {"ok": True, "amount_rmb": amount, "rate": Decimal("1")}
    if currency == "USD":
        rate = _decimal((fx_context or {}).get("fx_usd_to_rmb"))
        if rate is not None and rate > 0:
            return {"ok": True, "amount_rmb": amount * rate, "rate": rate}
    elif currency == "MXN":
        rmb_to_mxn = _decimal((fx_context or {}).get("fx_rmb_to_mxn"))
        if rmb_to_mxn is not None and rmb_to_mxn > 0:
            return {"ok": True, "amount_rmb": amount / rmb_to_mxn, "rate": Decimal("1") / rmb_to_mxn}
    return {"ok": False, "reason_code": "FX_RATE_MISSING", "currency": currency}


def preview_comprehensive_cost_data(items: list[dict], fees: list[dict], fx_context: dict) -> dict:
    """Calculate a transparent preview from caller-provided snapshots only."""

    presented_items = [present_material_row(dict(row or {})) for row in (items or [])]
    item_costs: dict[str, dict] = {}
    incomplete_reasons = []
    if not presented_items:
        incomplete_reasons.append({"reason_code": "MATERIAL_ITEMS_REQUIRED", "message": "当前批次没有物料，请先补充物料数据。"})
    goods_total = Decimal("0")
    for row in presented_items:
        key = _item_key(row)
        goods_value = _decimal(row.get("goods_value"))
        if goods_value is None or goods_value <= 0:
            incomplete_reasons.append(
                {
                    "reason_code": "GOODS_VALUE_MISSING",
                    "item_key": key,
                    "field": "goods_value",
                    "message": "采购货值缺失，该行试算不完整。",
                }
            )
            goods_value = Decimal("0")
        goods_total += goods_value
        item_costs[key] = {
            "goods_value_rmb": goods_value,
            "direct_fees_rmb": Decimal("0"),
            "allocated_fees_rmb": Decimal("0"),
        }

    direct_total = Decimal("0")
    allocated_total = Decimal("0")
    included_fees = []
    excluded_fees = []
    ignored_fees = []
    estimated_fee_count = 0
    for raw_fee in mark_duplicate_fees(fees):
        fee = dict(raw_fee or {})
        if not fee_is_active(fee):
            continue
        status = fee_allocation_service.amount_status(fee)
        identity = _fee_key(fee)
        common = {
            "rule_name": str(fee.get("name") or ""),
            "fee_key": identity,
            "expense_category": str(fee.get("expense_category") or ""),
            "amount_status": status,
            "currency": str(fee.get("currency") or "RMB").upper(),
            "amount": "" if fee.get("amount") in (None, "") else str(fee.get("amount")),
        }
        if fee.get("duplicate_rule_names"):
            excluded_fees.append({**common, "reason_code": "DUPLICATE_LOGICAL_FEE",
                                  "duplicate_rule_names": fee["duplicate_rule_names"]})
            continue
        if status == "MISSING":
            excluded_fees.append({**common, "reason_code": "AMOUNT_MISSING"})
            continue
        if status in {"NOT_INCURRED", "INCLUDED"}:
            ignored_fees.append({**common, "reason_code": status})
            continue
        if status not in fee_allocation_service.COUNTED_AMOUNT_STATUSES:
            excluded_fees.append({**common, "reason_code": "AMOUNT_STATUS_INVALID"})
            continue

        allocation = allocate_fee_in_rmb(fee, presented_items, fx_context or {})
        if allocation.get("status") != "ALLOCATED":
            excluded_fees.append(
                {
                    **common,
                    "reason_code": allocation.get("code") or "ALLOCATION_REQUIRED",
                    "allocation": allocation,
                }
            )
            continue

        amount_rmb = Decimal(allocation["amount"])
        is_direct = str(fee.get("scope_type") or "ALL_ITEMS").upper() == "DIRECT_ITEM"
        bucket = "direct_fees_rmb" if is_direct else "allocated_fees_rmb"
        for item_key, amount_text in (allocation.get("allocations") or {}).items():
            if item_key in item_costs:
                item_costs[item_key][bucket] += Decimal(str(amount_text or "0"))
        if is_direct:
            direct_total += amount_rmb.quantize(Decimal("0.01"))
        else:
            allocated_total += amount_rmb.quantize(Decimal("0.01"))
        if status == "ESTIMATED":
            estimated_fee_count += 1
            incomplete_reasons.append(
                {
                    "reason_code": "ESTIMATED_AMOUNT",
                    "fee_key": identity,
                    "message": "费用仍为暂估，已计入预览但不是完整成本。",
                }
            )
        included_fees.append(
            {
                **common,
                "amount_rmb": _money(amount_rmb),
                "scope_type": str(fee.get("scope_type") or "ALL_ITEMS").upper(),
                "allocation_basis": allocation.get("basis") or "",
                "preferred_basis": allocation.get("preferred_basis") or "",
                "fallback_reason": allocation.get("fallback_reason") or "",
                "allocations": allocation.get("allocations") or {},
            }
        )

    for row in excluded_fees:
        incomplete_reasons.append(
            {
                "reason_code": row["reason_code"],
                "fee_key": row.get("fee_key") or "",
                "message": "该费用未计入本次试算。",
            }
        )

    # Reconcile sub-cent purchase values once so persisted SKU totals conserve
    # the rounded batch amount. Source goods values remain untouched.
    rounded_goods = {key: Decimal(_money(costs["goods_value_rmb"])) for key, costs in item_costs.items()}
    remainder = Decimal(_money(goods_total)) - sum(rounded_goods.values(), Decimal("0"))
    direction = Decimal("0.01") if remainder > 0 else Decimal("-0.01")
    ordered_keys = sorted(item_costs, key=lambda key: (
        -(item_costs[key]["goods_value_rmb"] - rounded_goods[key]) if remainder > 0
        else item_costs[key]["goods_value_rmb"] - rounded_goods[key], key))
    for index in range(int(abs(remainder) / Decimal("0.01"))):
        rounded_goods[ordered_keys[index % len(ordered_keys)]] += direction
    preview_items = []
    for row in presented_items:
        key = _item_key(row)
        costs = item_costs[key]
        total = rounded_goods[key] + costs["direct_fees_rmb"] + costs["allocated_fees_rmb"]
        effective = row.get("effective_shipping") or {}
        shipped_quantity = _decimal(effective.get("quantity"))
        shipped_uom = str(effective.get("uom") or "").strip()
        shipping_unit_cost = None
        if shipped_quantity is not None and shipped_quantity > 0 and shipped_uom:
            shipping_unit_cost = {"amount_rmb": _unit_money(total / shipped_quantity), "uom": shipped_uom}
        else:
            incomplete_reasons.append(
                {
                    "reason_code": "SHIPPING_UNIT_REQUIRED",
                    "item_key": key,
                    "field": "actual_shipped_qty",
                    "message": "发货数量或单位缺失，无法展示每发货单位成本。",
                }
            )

        purchase_quantity = _decimal(row.get("quantity"))
        purchase_uom = str(row.get("purchase_uom") or row.get("unit") or "").strip()
        pricing_uom = str(row.get("unit_price_uom") or "").strip()
        purchase_pricing_unit_cost = None
        if (
            purchase_quantity is not None
            and purchase_quantity > 0
            and pricing_uom
            and purchase_uom
            and pricing_uom == purchase_uom
        ):
            purchase_pricing_unit_cost = {
                "amount_rmb": _unit_money(total / purchase_quantity),
                "uom": pricing_uom,
            }
        preview_items.append(
            {
                "name": row.get("name") or "",
                "stable_line_key": key,
                "material_code": row.get("material_code") or "",
                "product_name": row.get("product_name") or "",
                "goods_value_rmb": _money(rounded_goods[key]),
                "direct_fees_rmb": _money(costs["direct_fees_rmb"]),
                "allocated_fees_rmb": _money(costs["allocated_fees_rmb"]),
                "total_cost_rmb": _money(total),
                "shipping_unit_cost": shipping_unit_cost,
                "purchase_pricing_unit_cost": purchase_pricing_unit_cost,
                "quantity_source_badge": row.get("quantity_source_badge") or "",
                "shipping_quantity_difference": str(shipped_quantity - purchase_quantity) if shipped_quantity is not None and purchase_quantity is not None and shipped_uom == purchase_uom else None,
            }
        )

    summary = {
        "purchase_goods_value_rmb": _money(goods_total),
        "direct_fees_rmb": _money(direct_total),
        "allocated_fees_rmb": _money(allocated_total),
        "total_cost_rmb": _money(goods_total + direct_total + allocated_total),
        "included_fee_count": len(included_fees),
        "excluded_fee_count": len(excluded_fees),
        "is_complete": not incomplete_reasons,
    }
    if estimated_fee_count:
        summary["estimated_fee_count"] = estimated_fee_count
    return {
        "ok": True,
        "read_only": True,
        "summary": summary,
        "items": preview_items,
        "included_fees": included_fees,
        "excluded_fees": excluded_fees,
        "ignored_fees": ignored_fees,
        "incomplete_reasons": incomplete_reasons,
    }


def allocate_fee_in_rmb(fee: dict, items: list[dict], fx_context: dict) -> dict:
    """Share currency validation and allocation between fee status and cost preview."""

    if not fee_allocation_service.is_counted_fee(fee):
        return fee_allocation_service.allocate_fee(fee, items)
    converted = convert_fee_amount_to_rmb(fee, fx_context)
    if not converted["ok"]:
        return {
            "status": "BLOCKED",
            "code": converted["reason_code"],
            "allocations": {},
            "allocated_total": "0.00",
        }
    allocation_fee = {**fee, "amount": format(converted["amount_rmb"], "f"), "currency": "RMB"}
    return {**fee_allocation_service.allocate_fee(allocation_fee, items), "currency": "RMB"}


def preview_comprehensive_cost(batch_name: str, version_name: str | None = None) -> dict:
    """Load snapshots and preview without calling insert, set_value, save or commit."""

    if frappe is None:
        return {"ok": True, "dry_run": True, "read_only": True, "batch_name": batch_name}
    version = version_name or frappe.db.get_value("Overseas Cost Batch", batch_name, "current_version")
    if not version:
        raise ValueError("当前批次没有可用成本版本。")
    if frappe.db.get_value("Overseas Cost Version", version, "batch") != batch_name:
        raise ValueError("成本版本不属于当前批次。")
    transport_mode = frappe.db.get_value("Overseas Cost Batch", batch_name, "transport_mode") or ""
    raw_items = frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_name, "version": version},
        fields=COST_INPUT_FIELDS,
        order_by="row_no asc, name asc",
        limit_page_length=10000,
    )
    rules = fee_service.compose_fee_worklist_rows(
        fee_service._query_rules(batch_name, version),
        transport_mode,
    )
    version_row = frappe.db.get_value(
        "Overseas Cost Version",
        version,
        ["fx_usd_to_rmb", "fx_rmb_to_mxn"],
        as_dict=True,
    ) or {}
    result = preview_comprehensive_cost_data(raw_items, rules, version_row)
    result.update(
        {
            "batch_name": batch_name,
            "version_name": version,
            "transport_mode": transport_mode,
            "fx_context": {
                "fx_usd_to_rmb": version_row.get("fx_usd_to_rmb"),
                "fx_rmb_to_mxn": version_row.get("fx_rmb_to_mxn"),
            },
        }
    )
    return result


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def cost_input_hash(items, fees, fx_context, transport_mode) -> str:
    return hashlib.sha256(_json([items, fees, fx_context, transport_mode]).encode()).hexdigest()


def build_saved_cost_data(items: list[dict], fees: list[dict], fx_context: dict, transport_mode: str) -> dict:
    """Project one preview into stored result fields without mutating source facts."""
    transport_mode = fee_service.resolve_transport_mode(transport_mode)
    fees = fee_service._decorate_historical_rules(fees, transport_mode)
    assert_no_duplicate_fees(fees)
    result = preview_comprehensive_cost_data(items, fees, fx_context)
    raw_by_key = {_item_key(present_material_row(row)): row for row in items}
    fx = _decimal(fx_context.get("fx_rmb_to_mxn"))
    fx = fx if fx is not None and fx > 0 else None
    goods_total = Decimal(result["summary"]["purchase_goods_value_rmb"])
    gross_total = sum((_decimal(row.get("gross_weight_kg")) or Decimal("0") for row in items), Decimal("0"))
    updates = []
    for row in result["items"]:
        key = row["stable_line_key"]
        raw = raw_by_key[key]
        allocations = []
        freight = customs = tax = other = Decimal("0")
        for fee in result["included_fees"]:
            amount = Decimal(fee.get("allocations", {}).get(key, "0"))
            fee_key = fee["fee_key"]
            if fee_key == "customs_clearance_fee":
                customs += amount
            elif fee_key == "import_tax":
                tax += amount
            elif fee_key.startswith("international_") or fee_key in {"sea_port_forwarder_surcharge", "air_forwarder_surcharge", "express_surcharge"}:
                freight += amount
            else:
                other += amount
            allocations.append({
                "rule_code": fee_key, "expense_category": fee["expense_category"],
                "amount_rmb": fee["amount_rmb"], "allocated_rmb": _money(amount),
                "allocated_mxn": _money(amount * fx) if fx else None,
                "basis": fee["allocation_basis"], "scope_type": fee["scope_type"],
                "fallback_reason": fee["fallback_reason"],
            })
        extras = Decimal(row["direct_fees_rmb"]) + Decimal(row["allocated_fees_rmb"])
        shipping = row.get("shipping_unit_cost")
        effective = present_material_row(raw).get("effective_shipping") or {}
        qty = _decimal(effective.get("quantity"))
        derived = {
            "calculation_schema": 2, "allocated_rules": allocations,
            "fx_rmb_to_mxn": str(fx) if fx else None,
            "fx_usd_to_rmb": fx_context.get("fx_usd_to_rmb"),
            "mexico_customs_rmb": _money(customs),
            "mexico_customs_mxn": _money(customs * fx) if fx else None,
            "allocated_other_rmb": _money(tax + other),
            "tax_allocated_rmb": _money(tax),
            "direct_fees_rmb": row["direct_fees_rmb"],
            "allocated_fees_rmb": row["allocated_fees_rmb"],
            "shipping_unit_cost": shipping,
            "purchase_pricing_unit_cost": row.get("purchase_pricing_unit_cost"),
            "shipping_quantity": str(qty) if qty else None,
            "purchase_quantity": raw.get("quantity"),
        }
        updates.append({
            "name": raw["name"], "transport_mode": transport_mode,
            "goods_value_ratio": _unit_money(Decimal(row["goods_value_rmb"]) / goods_total * 100) if goods_total else "0",
            "weight_ratio": _unit_money((_decimal(raw.get("gross_weight_kg")) or Decimal("0")) / gross_total * 100) if gross_total else "0",
            "freight_alloc_rmb": _money(freight),
            "freight_alloc_mxn": _money(freight * fx) if fx else None,
            "total_logistics_mxn": _money(extras * fx) if fx else None,
            "alloc_price_mxn": _unit_money(extras * fx / qty) if fx and qty and qty > 0 else None,
            "total_cost_rmb": row["total_cost_rmb"],
            "total_unit_rmb": shipping["amount_rmb"] if shipping else None,
            "derived_json": _json(derived),
        })
    summary = {
        **result["summary"], "calculation_schema": 2,
        "input_hash": cost_input_hash(items, fees, fx_context, transport_mode),
        "total_goods_value": result["summary"]["purchase_goods_value_rmb"],
        "total_gross_weight_kg": str(gross_total),
        "total_volume_m3": str(sum((_decimal(row.get("volume_m3")) or Decimal("0") for row in items), Decimal("0"))),
        "fee_pool_rmb": _money(Decimal(result["summary"]["direct_fees_rmb"]) + Decimal(result["summary"]["allocated_fees_rmb"])),
        "item_count": len(items), "rule_count": len(result["included_fees"]),
        "comprehensive_cost": result,
    }
    return {**result, "item_updates": updates, "summary_snapshot": summary}


class FrappeCostRepository:
    def lock_and_load(self, batch_name, version_name, *, edit_token, expected_modified, trusted=False):
        from overseas_costing.services import batch_service, edit_session_service
        name = batch_service._resolve_batch_name(batch_name)
        if not name:
            raise ValueError("未找到当前批次。")
        if trusted:
            edit_session_service._lock_row(name)
        else:
            edit_session_service.assert_batch_write(name, edit_token=edit_token, expected_modified=expected_modified)
        batch = frappe.db.get_value("Overseas Cost Batch", name,
            ["name", "current_version", "modified", "status", "confirm_status", "is_locked", "transport_mode", "source_approval_status", "extra_json"], as_dict=True)
        version = version_name or batch.get("current_version")
        frappe.db.sql("SELECT name FROM `tabOverseas Cost Version` WHERE name=%s AND batch=%s FOR UPDATE", (version, name))
        version_row = frappe.db.get_value("Overseas Cost Version", version,
            ["name", "batch", "status", "modified", "fx_usd_to_rmb", "fx_rmb_to_mxn"], as_dict=True) or {}
        if version_row.get("batch") != name:
            raise ValueError("成本版本不属于当前批次。")
        for doctype in ("Overseas Cost Item", "Overseas Cost Allocation Rule"):
            frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE batch=%s AND version=%s ORDER BY name FOR UPDATE", (name, version))
        items = frappe.get_all("Overseas Cost Item", filters={"batch": name, "version": version},
            fields=COST_INPUT_FIELDS, order_by="row_no asc, name asc", limit_page_length=10000)
        invalid = batch_service._build_invalid_business_state(batch, items)
        if invalid.get("invalid"):
            raise ValueError(invalid.get("message") or "当前批次审批已被排除，不能计算。")
        mode = fee_service.resolve_transport_mode(batch.get("transport_mode"))
        if not mode:
            raise ValueError("请先确认批次运输方式。")
        fees = fee_service.compose_fee_worklist_rows(fee_service._query_rules(name, version), mode)
        fx = {key: version_row.get(key) for key in ("fx_usd_to_rmb", "fx_rmb_to_mxn")}
        context = {**batch, "transport_mode": mode, "batch": name, "version": version, "batch_modified": str(batch["modified"]),
                   "version_modified": str(version_row["modified"]), "version_status": version_row["status"]}
        return context, items, fees, fx

    def assert_unchanged(self, context):
        current = frappe.db.get_value("Overseas Cost Batch", context["batch"], ["modified", "current_version"], as_dict=True)
        if str(current["modified"]) != context["batch_modified"] or current["current_version"] != context["version"]:
            raise RuntimeError("试算期间批次数据已变化，请重新试算。")

    def save(self, context, result):
        from overseas_costing.services import calculate_service
        now = frappe.utils.now()
        snapshot = result["summary_snapshot"]
        snapshot["calculated_at"] = now
        for row in result["item_updates"]:
            frappe.db.set_value("Overseas Cost Item", row["name"], {k: v for k, v in row.items() if k != "name"}, update_modified=False)
        frappe.db.set_value("Overseas Cost Version", context["version"], {
            "summary_snapshot_json": _json(snapshot), "rule_snapshot_json": _json(result["included_fees"]), "calculated_at": now,
        }, update_modified=True)
        frappe.db.set_value("Overseas Cost Batch", context["batch"], {
            "status": "Calculated", "estimated_total_cost_rmb": snapshot["total_cost_rmb"],
            "total_goods_value": snapshot["total_goods_value"], "total_gross_weight_kg": snapshot["total_gross_weight_kg"],
            "item_count": snapshot["item_count"],
        }, update_modified=True)
        calculate_service._insert_audit_log(batch_doc_name=context["batch"], version_name=context["version"],
            action_type="RECALCULATE", action_remark=f"统一试算已保存：RMB {snapshot['total_cost_rmb']}；输入 {snapshot['input_hash']}")
        return str(frappe.db.get_value("Overseas Cost Batch", context["batch"], "modified"))

    def commit(self):
        frappe.db.commit()

    def rollback(self):
        frappe.db.rollback()


COST_INPUT_FIELDS = [
    "name", "row_no", "stable_line_key", "material_code", "product_name", "unit", "purchase_uom",
    "unit_price_uom", "quantity", "actual_shipped_qty", "actual_shipped_qty_mode",
    "actual_shipped_qty_source_revision", "shipped_uom", "goods_value", "gross_weight_kg", "volume_m3",
    "volume_weight_kg", "chargeable_weight_kg", "project_collection", "dingtalk_instance_id", "source_type",
]


def calculate_comprehensive_cost(batch_name, version_name=None, *, edit_token=None, expected_modified=None,
                                 repository=None, trusted=False, commit_after_calculate=True):
    """Save a trial atomically; never confirms a version or sends an ERP request."""
    repo = repository or FrappeCostRepository()
    try:
        context, items, fees, fx = repo.lock_and_load(batch_name, version_name, edit_token=edit_token,
            expected_modified=expected_modified, trusted=trusted)
        if context.get("current_version") != context["version"]:
            raise ValueError("只能试算当前版本，请刷新批次。")
        if context.get("version_status") in {"Confirmed", "Archived"} or context.get("confirm_status") == "Confirmed" or context.get("is_locked"):
            raise PermissionError("已确认或归档版本不能覆盖，请先创建调整版本。")
        result = build_saved_cost_data(items, fees, fx, context["transport_mode"])
        repo.assert_unchanged(context)
        modified = repo.save(context, result)
        if commit_after_calculate:
            repo.commit()
        result.pop("item_updates", None)
        return {**result, "ok": True, "saved": True, "read_only": False, "batch_name": context["batch"],
                "version_name": context["version"], "batch_modified": modified,
                "transport_mode": context["transport_mode"], "message": "试算完成，已同步总览与 SKU 明细。"}
    except Exception:
        repo.rollback()
        raise
