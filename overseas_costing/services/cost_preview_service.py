"""只读综合成本试算：不创建版本、不改写 SKU 结果、不触发 ERP。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

try:
    import frappe
except Exception:  # pragma: no cover - pure tests do not require Frappe
    frappe = None

from overseas_costing.services import fee_allocation_service, fee_service
from overseas_costing.services.material_input_service import present_material_row


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
    for raw_fee in fees or []:
        fee = dict(raw_fee or {})
        status = fee_allocation_service.amount_status(fee)
        identity = _fee_key(fee)
        common = {
            "fee_key": identity,
            "expense_category": str(fee.get("expense_category") or ""),
            "amount_status": status,
            "currency": str(fee.get("currency") or "RMB").upper(),
            "amount": "" if fee.get("amount") in (None, "") else str(fee.get("amount")),
        }
        if status == "MISSING":
            excluded_fees.append({**common, "reason_code": "AMOUNT_MISSING"})
            continue
        if status in {"NOT_INCURRED", "INCLUDED"}:
            ignored_fees.append({**common, "reason_code": status})
            continue
        if status not in fee_allocation_service.COUNTED_AMOUNT_STATUSES:
            excluded_fees.append({**common, "reason_code": "AMOUNT_STATUS_INVALID"})
            continue

        converted = convert_fee_amount_to_rmb(fee, fx_context or {})
        if not converted.get("ok"):
            excluded_fees.append({**common, **converted})
            continue
        amount_rmb = converted["amount_rmb"]
        allocation_fee = {**fee, "amount": format(amount_rmb, "f"), "currency": "RMB"}
        allocation = fee_allocation_service.allocate_fee(allocation_fee, presented_items)
        if allocation.get("status") != "ALLOCATED":
            excluded_fees.append(
                {
                    **common,
                    "reason_code": allocation.get("code") or "ALLOCATION_REQUIRED",
                    "allocation": allocation,
                }
            )
            continue

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

    preview_items = []
    for row in presented_items:
        key = _item_key(row)
        costs = item_costs[key]
        total = costs["goods_value_rmb"] + costs["direct_fees_rmb"] + costs["allocated_fees_rmb"]
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
                "goods_value_rmb": _money(costs["goods_value_rmb"]),
                "direct_fees_rmb": _money(costs["direct_fees_rmb"]),
                "allocated_fees_rmb": _money(costs["allocated_fees_rmb"]),
                "total_cost_rmb": _money(total),
                "shipping_unit_cost": shipping_unit_cost,
                "purchase_pricing_unit_cost": purchase_pricing_unit_cost,
                "quantity_source_badge": row.get("quantity_source_badge") or "",
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


def preview_comprehensive_cost(batch_name: str, version_name: str | None = None) -> dict:
    """Load snapshots and preview without calling insert, set_value, save or commit."""

    if frappe is None:
        return {"ok": True, "dry_run": True, "read_only": True, "batch_name": batch_name}
    version = version_name or frappe.db.get_value("Overseas Cost Batch", batch_name, "current_version")
    if not version:
        raise ValueError("当前批次没有可用成本版本。")
    if frappe.db.get_value("Overseas Cost Version", version, "batch") != batch_name:
        raise ValueError("成本版本不属于当前批次。")
    transport_mode = frappe.db.get_value("Overseas Cost Batch", batch_name, "transport_mode") or "SEA"
    raw_items = frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_name, "version": version},
        fields=[
            "name",
            "row_no",
            "stable_line_key",
            "material_code",
            "product_name",
            "unit",
            "purchase_uom",
            "unit_price_uom",
            "quantity",
            "actual_shipped_qty",
            "actual_shipped_qty_mode",
            "actual_shipped_qty_source_revision",
            "shipped_uom",
            "goods_value",
            "gross_weight_kg",
            "volume_m3",
            "chargeable_weight_kg",
            "project_collection",
        ],
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
