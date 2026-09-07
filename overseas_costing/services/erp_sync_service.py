"""Idempotent ERP synchronization identities, ledger states and reconciliation."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation


ALLOWED_TRANSITIONS = {
    "PENDING": {"RUNNING", "SUPERSEDED"},
    "RUNNING": {"SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED", "SUPERSEDED"},
    "FAILED": {"RUNNING", "SUPERSEDED"},
    "UNCERTAIN": {"SUCCESS", "FAILED", "MANUAL_REQUIRED", "SUPERSEDED"},
    "SUCCESS": set(),
    "MANUAL_REQUIRED": set(),
    "SUPERSEDED": set(),
}

SECRET_KEYS = frozenset({"authorization", "password", "token", "api_key", "api_secret"})


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def payload_hash(payload: dict) -> str:
    return _hash(payload or {})


def purchase_business_key(*, batch: str, site: str, group, version: str = "") -> str:
    """Return a purchase identity that intentionally excludes the cost version."""

    del version
    group_identity = group if isinstance(group, str) else _canonical(group)
    identity = "\x1f".join((str(batch or "").strip(), str(site or "").strip(), str(group_identity or "").strip()))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def build_request_id(
    *, operation: str, site_code: str, business_key: str, cost_result_hash: str, intent_key: str
) -> str:
    return _hash(
        {
            "operation": str(operation or "").upper(),
            "site_code": str(site_code or "").strip(),
            "business_key": str(business_key or "").strip(),
            "cost_result_hash": str(cost_result_hash or "").strip(),
            "intent_key": str(intent_key or "").strip(),
        }
    )


def redact_secrets(value):
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).casefold() in SECRET_KEYS else redact_secrets(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def prepare_sync_request(
    existing_requests: list[dict],
    *,
    operation: str,
    batch: str,
    version: str,
    cost_result_hash: str,
    site_code: str,
    business_key: str,
    payload: dict,
    intent_key: str,
) -> dict:
    operation = str(operation or "").upper()
    digest = payload_hash(payload)
    request_id = build_request_id(
        operation=operation,
        site_code=site_code,
        business_key=business_key,
        cost_result_hash=cost_result_hash,
        intent_key=intent_key,
    )
    for saved in existing_requests or []:
        if str(saved.get("request_id") or "") == request_id:
            return {"action": "REPLAY", "request": saved}
    for saved in existing_requests or []:
        if (
            str(saved.get("operation") or "").upper() == operation
            and str(saved.get("site_code") or "") == str(site_code or "")
            and str(saved.get("business_key") or "") == str(business_key or "")
            and str(saved.get("payload_hash") or "") == digest
            and str(saved.get("status") or "").upper() == "SUCCESS"
        ):
            return {"action": "NOOP", "request": saved}
    request = {
        "request_id": request_id,
        "operation": operation,
        "batch": str(batch or ""),
        "version": str(version or ""),
        "cost_result_hash": str(cost_result_hash or ""),
        "site_code": str(site_code or ""),
        "business_key": str(business_key or ""),
        "payload_hash": digest,
        "status": "PENDING",
        "attempt_count": 0,
        "safe_payload": redact_secrets(payload or {}),
        "safe_response": {},
    }
    return {"action": "EXECUTE", "request": request}


def transition_request(request: dict, target_status: str, **changes) -> dict:
    current = str(request.get("status") or "PENDING").upper()
    target = str(target_status or "").upper()
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"INVALID_SYNC_TRANSITION:{current}->{target}")
    updated = {**request, **changes, "status": target}
    if target == "RUNNING":
        updated["attempt_count"] = int(request.get("attempt_count") or 0) + 1
    return updated


def apply_sync_response(request: dict, response: dict, *, latest_cost_result_hash: str) -> dict:
    if str(request.get("cost_result_hash") or "") != str(latest_cost_result_hash or ""):
        return {
            "applied": False,
            "request": transition_request(request, "SUPERSEDED", safe_response=redact_secrets(response or {})),
        }
    status = str((response or {}).get("status") or "FAILED").upper()
    if status in {"CREATED", "EXISTS", "UPDATED", "NOOP"}:
        status = "SUCCESS"
    if status not in {"SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED"}:
        status = "FAILED"
    return {
        "applied": True,
        "request": transition_request(request, status, safe_response=redact_secrets(response or {})),
    }


def plan_uncertain_retry(request: dict, lookup_result: dict) -> dict:
    if str(request.get("status") or "").upper() != "UNCERTAIN":
        raise ValueError("REQUEST_IS_NOT_UNCERTAIN")
    if lookup_result.get("ambiguous"):
        return {"action": "MANUAL_REQUIRED", "code": "AMBIGUOUS_REMOTE_BUSINESS_KEY"}
    if lookup_result.get("found"):
        return {
            "action": "RECONCILE_SUCCESS",
            "remote_document": str(lookup_result.get("name") or ""),
        }
    return {"action": "RETRY", "request_id": str(request.get("request_id") or "")}


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _item_quantities(items: list[dict]) -> dict[str, Decimal]:
    return {
        str(row.get("stable_line_key") or ""): _decimal(
            row.get("effective_shipped_qty") or row.get("actual_shipped_qty") or row.get("quantity")
        )
        for row in items or []
        if row.get("stable_line_key")
    }


def verify_legacy_document_candidates(candidates: list[dict], expected_items: list[dict]) -> dict:
    """Fail closed unless exactly one historical document has matching row identities and quantities."""

    if not candidates:
        return {"status": "CREATE_CANDIDATE"}
    if len(candidates) != 1:
        return {"status": "MANUAL_REQUIRED", "code": "AMBIGUOUS_LEGACY_DOCUMENTS"}
    candidate = candidates[0]
    if _item_quantities(candidate.get("items") or []) != _item_quantities(expected_items):
        return {"status": "MANUAL_REQUIRED", "code": "LEGACY_LINE_MISMATCH"}
    return {"status": "VERIFIED", "remote_document": str(candidate.get("name") or "")}


class InMemorySyncStore:
    """Small transaction-shaped store used by deterministic orchestration tests."""

    def __init__(self, requests: list[dict] | None = None, links: list[dict] | None = None):
        self.requests = list(requests or [])
        self.links = list(links or [])
        self.commit_count = 0

    def save_request(self, request: dict) -> None:
        for index, current in enumerate(self.requests):
            if current.get("request_id") == request.get("request_id"):
                self.requests[index] = dict(request)
                return
        self.requests.append(dict(request))

    def save_link(self, link: dict) -> None:
        identity = (link.get("site_code"), link.get("stable_line_key"), link.get("business_key"))
        for index, current in enumerate(self.links):
            if (current.get("site_code"), current.get("stable_line_key"), current.get("business_key")) == identity:
                self.links[index] = dict(link)
                return
        self.links.append(dict(link))

    def commit(self) -> None:
        self.commit_count += 1


def _config_map(site_configs) -> dict[str, dict]:
    if isinstance(site_configs, dict):
        return {str(key): dict(value or {}) for key, value in site_configs.items()}
    return {
        str(row.get("site_code") or ""): dict(row)
        for row in (site_configs or [])
        if row.get("site_code")
    }


def _purchase_item(row: dict, group: dict) -> dict:
    quantity = row.get("effective_shipped_qty")
    if quantity in (None, ""):
        quantity = row.get("actual_shipped_qty") or row.get("quantity") or 0
    goods = row.get("goods_value") or 0
    total = row.get("total_cost_rmb") or 0
    return {
        **row,
        "stable_line_key": str(row.get("stable_line_key") or ""),
        "source_quantity": quantity,
        "purchase_currency": row.get("purchase_currency") or group.get("currency") or "CNY",
        "original_unit_price": row.get("unit_price") or 0,
        "comprehensive_unit_price": row.get("total_unit_rmb") or 0,
        "cost_formula": {
            "quantity": quantity,
            "goods_value": goods,
            "total_cost": total,
            "original_unit_price": row.get("unit_price") or 0,
            "comprehensive_unit_price": row.get("total_unit_rmb") or 0,
        },
    }


def _group_payload(
    *, batch: str, version: str, cost_result_hash: str, site: dict, group: dict, business_key: str
) -> dict:
    items = [_purchase_item(row, group) for row in group.get("items") or []]
    return {
        "batch_no": batch,
        "version_name": version,
        "cost_result_hash": cost_result_hash,
        "business_key": business_key,
        "site_code": site.get("site_code") or "",
        "subsidiary_code": (site.get("subsidiary_codes") or [""])[0],
        "supplier": group.get("supplier") or "",
        "currency": group.get("currency") or "CNY",
        "stock_uom": group.get("stock_uom") or "",
        "fee_total_rmb": group.get("allocated_fee_rmb") or "0.00",
        "total_cost_rmb": group.get("total_cost_rmb") or "0.00",
        "estimated_fee_keys": list(group.get("estimated_fee_keys") or []),
        "amount_status": "ESTIMATED" if group.get("estimated_fee_keys") else "ACTUAL",
        "items": items,
    }


def verify_remote_purchase_state(payload: dict, remote_state: dict) -> dict:
    data = (remote_state or {}).get("data") if isinstance(remote_state, dict) else None
    if not isinstance(data, dict):
        data = remote_state if isinstance(remote_state, dict) else {}
    if str(data.get("custom_overseas_business_key") or "") != str(payload.get("business_key") or ""):
        return {"ok": False, "code": "REMOTE_BUSINESS_KEY_MISMATCH"}
    remote_by_key = {
        str(row.get("custom_overseas_stable_line_key") or ""): row
        for row in data.get("items") or []
        if row.get("custom_overseas_stable_line_key")
    }
    for row in payload.get("items") or []:
        key = str(row.get("stable_line_key") or "")
        remote = remote_by_key.get(key)
        if not remote:
            return {"ok": False, "code": "REMOTE_LINE_MISSING", "stable_line_key": key}
        if _decimal(remote.get("qty")) != _decimal(row.get("source_quantity")):
            return {"ok": False, "code": "REMOTE_QUANTITY_MISMATCH", "stable_line_key": key}
        remote_cost = _decimal(remote.get("custom_overseas_comprehensive_amount")).quantize(Decimal("0.01"))
        expected_cost = _decimal((row.get("cost_formula") or {}).get("total_cost")).quantize(Decimal("0.01"))
        if remote_cost != expected_cost:
            return {"ok": False, "code": "REMOTE_COST_MISMATCH", "stable_line_key": key}
    return {"ok": True, "data": data, "remote_items": remote_by_key}


def _synced_links(store, *, site_code: str, business_key: str, stable_keys: list[str], cost_hash: str) -> bool:
    linked = {
        str(row.get("stable_line_key") or "")
        for row in store.links
        if str(row.get("site_code") or "") == site_code
        and str(row.get("business_key") or "") == business_key
        and str(row.get("last_cost_result_hash") or "") == cost_hash
        and str(row.get("status") or "").upper() == "SUCCESS"
    }
    return bool(stable_keys) and set(stable_keys) <= linked


def _summary_status(groups: list[dict]) -> str:
    statuses = [str(row.get("status") or "") for row in groups]
    success_count = sum(status == "SUCCESS" for status in statuses)
    if statuses and success_count == len(statuses):
        return "SUCCESS"
    if success_count:
        return "PARTIAL"
    return "FAILED"


def execute_site_pushes(
    *,
    batch: str,
    version: str,
    cost_result_hash: str,
    preview: dict,
    site_configs,
    intent_key: str,
    client,
    store,
) -> dict:
    """Execute each site/group independently and retain successful siblings on failure."""

    config_by_site = _config_map(site_configs)
    group_results = []
    for site in preview.get("sites") or []:
        site_code = str(site.get("site_code") or "")
        for group in site.get("groups") or []:
            group_key = group.get("group_key") or {
                "supplier": group.get("supplier"),
                "currency": group.get("currency"),
                "stock_uom": group.get("stock_uom"),
                "stable_line_keys": sorted(
                    str(row.get("stable_line_key") or "") for row in group.get("items") or []
                ),
            }
            business_key = purchase_business_key(batch=batch, site=site_code, group=group_key)
            stable_keys = [str(row.get("stable_line_key") or "") for row in group.get("items") or []]
            if _synced_links(
                store,
                site_code=site_code,
                business_key=business_key,
                stable_keys=stable_keys,
                cost_hash=cost_result_hash,
            ):
                group_results.append({"site_code": site_code, "business_key": business_key, "status": "SUCCESS", "noop": True})
                continue

            payload = _group_payload(
                batch=batch,
                version=version,
                cost_result_hash=cost_result_hash,
                site=site,
                group=group,
                business_key=business_key,
            )
            prepared = prepare_sync_request(
                store.requests,
                operation="CREATE",
                batch=batch,
                version=version,
                cost_result_hash=cost_result_hash,
                site_code=site_code,
                business_key=business_key,
                payload=payload,
                intent_key=intent_key,
            )
            if prepared["action"] in {"REPLAY", "NOOP"} and str(prepared["request"].get("status") or "") == "SUCCESS":
                group_results.append({"site_code": site_code, "business_key": business_key, "status": "SUCCESS", "noop": True})
                continue
            request = prepared["request"]
            store.save_request(request)
            store.commit()
            running = transition_request(request, "RUNNING")
            store.save_request(running)
            store.commit()
            config = config_by_site.get(site_code)
            if not config:
                response = {"status": "FAILED", "code": "ERP_SITE_CONFIG_REQUIRED"}
            else:
                try:
                    response = client.create_purchase(payload, config)
                except (TimeoutError, ConnectionError) as exc:
                    response = {"status": "UNCERTAIN", "code": type(exc).__name__}
                except Exception as exc:
                    response = {"status": "FAILED", "code": type(exc).__name__}

            verification = {}
            if response.get("ok") and response.get("erp_target_doc") and config:
                remote_document = str(response.get("erp_target_doc") or "")
                try:
                    remote_state = client.read_purchase_state(
                        {"remote_doctype": "Purchase Order", "remote_document": remote_document},
                        config,
                    )
                    verification = verify_remote_purchase_state(payload, remote_state)
                except Exception as exc:
                    verification = {"ok": False, "code": type(exc).__name__}
                if not verification.get("ok"):
                    response = {"status": "MANUAL_REQUIRED", **verification}
                else:
                    response = {**response, "status": "SUCCESS"}

            applied = apply_sync_response(running, response, latest_cost_result_hash=cost_result_hash)
            completed = applied["request"]
            store.save_request(completed)
            if completed.get("status") == "SUCCESS":
                data = verification["data"]
                remote_items = verification["remote_items"]
                for key in stable_keys:
                    remote_row = remote_items.get(key) or {}
                    store.save_link(
                        {
                            "batch": batch,
                            "stable_line_key": key,
                            "site_code": site_code,
                            "business_key": business_key,
                            "remote_doctype": "Purchase Order",
                            "remote_document": str(data.get("name") or response.get("erp_target_doc") or ""),
                            "remote_row": str(remote_row.get("name") or ""),
                            "remote_docstatus": int(data.get("docstatus") or 0),
                            "status": "SUCCESS",
                            "last_cost_result_hash": cost_result_hash,
                            "last_payload_hash": completed.get("payload_hash") or "",
                        }
                    )
            store.commit()
            group_results.append(
                {
                    "site_code": site_code,
                    "business_key": business_key,
                    "request_id": completed.get("request_id") or "",
                    "status": completed.get("status") or "FAILED",
                }
            )
    return {
        "status": _summary_status(group_results),
        "groups": group_results,
        "site_count": len({row.get("site_code") for row in group_results}),
    }


COST_COMPARE_FIELDS = (
    "goods_value",
    "total_cost_rmb",
    "total_unit_rmb",
    "freight_alloc_rmb",
    "clearance_alloc_rmb",
    "tax_alloc_rmb",
)


def _site(row: dict) -> str:
    return str(row.get("site_code") or row.get("erp_site_code") or "")


def preview_cost_updates(
    *, old_links: list[dict], new_items: list[dict], from_hash: str, to_hash: str
) -> dict:
    """Compare immutable cost snapshots without turning business changes into cost updates."""

    old_by_key = {str(row.get("stable_line_key") or ""): row for row in old_links or []}
    new_by_key = {str(row.get("stable_line_key") or ""): row for row in new_items or []}
    blocking = []
    if set(old_by_key) != set(new_by_key):
        blocking.append(
            {
                "code": "BUSINESS_CHANGE_REQUIRED",
                "reason": "MATERIAL_SET_CHANGED",
                "old_item_keys": sorted(old_by_key),
                "new_item_keys": sorted(new_by_key),
            }
        )

    changes_by_site: dict[str, list[dict]] = {}
    noop_sites = set()
    for key in sorted(set(old_by_key) & set(new_by_key)):
        old = old_by_key[key]
        new = new_by_key[key]
        old_quantity = _decimal(old.get("quantity") or old.get("effective_shipped_qty"))
        new_quantity = _decimal(new.get("effective_shipped_qty") or new.get("quantity"))
        if (
            _site(old) != _site(new)
            or str(old.get("subsidiary_code") or "") != str(new.get("subsidiary_code") or "")
            or old_quantity != new_quantity
        ):
            blocking.append(
                {
                    "code": "BUSINESS_CHANGE_REQUIRED",
                    "reason": "ROUTE_OR_QUANTITY_CHANGED",
                    "stable_line_key": key,
                }
            )
            continue
        changed_fields = [
            fieldname
            for fieldname in COST_COMPARE_FIELDS
            if _decimal(old.get(fieldname)) != _decimal(new.get(fieldname))
        ]
        if str(old.get("amount_status") or "") != str(new.get("amount_status") or ""):
            changed_fields.append("amount_status")
        site_code = _site(new)
        if changed_fields:
            changes_by_site.setdefault(site_code, []).append(
                {
                    "stable_line_key": key,
                    "remote_document": old.get("remote_document") or "",
                    "remote_row": old.get("remote_row") or "",
                    "quantity": str(new_quantity),
                    "old": {fieldname: old.get(fieldname) for fieldname in (*COST_COMPARE_FIELDS, "amount_status")},
                    "new": {fieldname: new.get(fieldname) for fieldname in (*COST_COMPARE_FIELDS, "amount_status")},
                    "changed_fields": changed_fields,
                }
            )
        else:
            noop_sites.add(site_code)
    changed_sites = set(changes_by_site)
    return {
        "ready": not blocking,
        "from_hash": str(from_hash or ""),
        "to_hash": str(to_hash or ""),
        "blocking": blocking,
        "sites": [
            {"site_code": site_code, "operation": "UPDATE_COST", "items": changes_by_site[site_code]}
            for site_code in sorted(changes_by_site)
        ],
        "noop_site_codes": sorted(noop_sites - changed_sites),
    }


def _update_link_cost_snapshot(link: dict, item: dict, *, cost_hash: str) -> dict:
    return {
        **link,
        **{fieldname: item.get(fieldname) for fieldname in COST_COMPARE_FIELDS},
        "quantity": item.get("effective_shipped_qty") or item.get("quantity") or 0,
        "amount_status": item.get("amount_status") or "",
        "last_cost_result_hash": cost_hash,
        "status": "SUCCESS",
    }


def execute_cost_updates(
    *,
    batch: str,
    version: str,
    from_hash: str,
    to_hash: str,
    new_items: list[dict],
    site_configs,
    intent_key: str,
    client,
    store,
) -> dict:
    """Apply only cost deltas; equivalent sites advance their links without remote writes."""

    old_links = list(store.links)
    preview = preview_cost_updates(
        old_links=old_links,
        new_items=new_items,
        from_hash=from_hash,
        to_hash=to_hash,
    )
    if not preview.get("ready"):
        return {"status": "BLOCKED", "groups": [], "preview": preview}
    old_by_key = {str(row.get("stable_line_key") or ""): row for row in old_links}
    new_by_key = {str(row.get("stable_line_key") or ""): row for row in new_items or []}
    changed_keys = {
        str(item.get("stable_line_key") or "")
        for site in preview.get("sites") or []
        for item in site.get("items") or []
    }
    for key in sorted(set(new_by_key) - changed_keys):
        store.save_link(_update_link_cost_snapshot(old_by_key[key], new_by_key[key], cost_hash=to_hash))
    if set(new_by_key) - changed_keys:
        store.commit()

    config_by_site = _config_map(site_configs)
    results = []
    for site in preview.get("sites") or []:
        site_code = str(site.get("site_code") or "")
        for change in site.get("items") or []:
            key = str(change.get("stable_line_key") or "")
            old_link = old_by_key[key]
            new_item = {**new_by_key[key], "cost_result_hash": to_hash}
            same_document_items = [
                row
                for item_key, row in new_by_key.items()
                if str(old_by_key[item_key].get("remote_document") or "")
                == str(old_link.get("remote_document") or "")
            ]
            document_total = sum((_decimal(row.get("total_cost_rmb")) for row in same_document_items), Decimal("0"))
            amount_status = (
                "ACTUAL"
                if same_document_items
                and all(str(row.get("amount_status") or "").upper() == "ACTUAL" for row in same_document_items)
                else "ESTIMATED"
            )
            payload = {
                "batch_no": batch,
                "version_name": version,
                "version_code": version,
                "cost_result_hash": to_hash,
                "business_key": old_link.get("business_key") or "",
                "document_total_cost_rmb": format(document_total, "f"),
                "amount_status": amount_status,
                "items": [new_item],
            }
            prepared = prepare_sync_request(
                store.requests,
                operation="UPDATE_COST",
                batch=batch,
                version=version,
                cost_result_hash=to_hash,
                site_code=site_code,
                business_key=str(old_link.get("business_key") or ""),
                payload=payload,
                intent_key=intent_key,
            )
            if prepared["action"] in {"REPLAY", "NOOP"} and str(prepared["request"].get("status") or "") == "SUCCESS":
                store.save_link(_update_link_cost_snapshot(old_link, new_item, cost_hash=to_hash))
                results.append({"site_code": site_code, "stable_line_key": key, "status": "SUCCESS", "noop": True})
                continue
            request = prepared["request"]
            store.save_request(request)
            store.commit()
            running = transition_request(request, "RUNNING")
            store.save_request(running)
            store.commit()
            config = config_by_site.get(site_code)
            if not config:
                response = {"status": "FAILED", "code": "ERP_SITE_CONFIG_REQUIRED"}
            else:
                try:
                    response = client.update_purchase_cost(payload, old_link, config)
                except (TimeoutError, ConnectionError) as exc:
                    response = {"status": "UNCERTAIN", "code": type(exc).__name__}
                except Exception as exc:
                    response = {"status": "FAILED", "code": type(exc).__name__}
            completed = apply_sync_response(
                running,
                response,
                latest_cost_result_hash=to_hash,
            )["request"]
            store.save_request(completed)
            if completed.get("status") == "SUCCESS":
                store.save_link(_update_link_cost_snapshot(old_link, new_item, cost_hash=to_hash))
            store.commit()
            results.append(
                {
                    "site_code": site_code,
                    "stable_line_key": key,
                    "request_id": completed.get("request_id") or "",
                    "status": completed.get("status") or "FAILED",
                }
            )
    return {
        "status": _summary_status(results) if results else "SUCCESS",
        "groups": results,
        "preview": preview,
    }
