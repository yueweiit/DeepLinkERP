"""Idempotent ERP synchronization identities, ledger states and reconciliation."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

try:
    import frappe
except Exception:  # pragma: no cover - pure tests run without Frappe
    frappe = None


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


def filter_retry_preview(preview: dict, *, batch: str, version: str, request: dict) -> dict:
    """Freeze a retry to the one site/group represented by the failed request."""

    requested_site = str(request.get("site_code") or "")
    requested_business_key = str(request.get("business_key") or "")
    sites = []
    for site in (preview or {}).get("sites") or []:
        site_code = str(site.get("site_code") or "")
        if site_code != requested_site:
            continue
        groups = [
            group
            for group in site.get("groups") or []
            if purchase_business_key(
                batch=batch,
                site=site_code,
                group=group.get("group_key") or "",
                version=version,
            )
            == requested_business_key
        ]
        if groups:
            sites.append({**site, "groups": groups, "group_count": len(groups)})
    return {**(preview or {}), "sites": sites, "site_count": len(sites), "group_count": sum(len(site["groups"]) for site in sites)}


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


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class FrappeSyncStore(InMemorySyncStore):
    """Persist each synchronization state independently in Frappe."""

    REQUEST_FIELDS = (
        "request_id", "operation", "batch", "version", "cost_result_hash", "site_code",
        "business_key", "payload_hash", "status", "attempt_count", "safe_payload_json",
        "safe_response_json", "error_code", "error_message", "started_at", "finished_at",
    )
    LINK_FIELDS = (
        "name", "batch", "stable_line_key", "site_code", "business_key", "remote_doctype",
        "remote_document", "remote_row", "remote_docstatus", "status", "last_cost_result_hash",
        "last_payload_hash", "verified_at", "remark",
    )

    def __init__(self, batch: str):
        if frappe is None:
            raise RuntimeError("当前未连接 Frappe。")
        request_rows = frappe.get_all(
            "Overseas Cost ERP Sync Request",
            filters={"batch": batch},
            fields=list(self.REQUEST_FIELDS),
            order_by="modified desc",
            limit_page_length=10000,
        )
        requests = []
        for row in request_rows:
            requests.append(
                {
                    **row,
                    "safe_payload": _json_object(row.get("safe_payload_json")),
                    "safe_response": _json_object(row.get("safe_response_json")),
                }
            )
        links = frappe.get_all(
            "Overseas Cost ERP Document Link",
            filters={"batch": batch},
            fields=list(self.LINK_FIELDS),
            order_by="modified desc",
            limit_page_length=10000,
        )
        super().__init__(requests=requests, links=links)

    def save_request(self, request: dict) -> None:
        super().save_request(request)
        values = {
            key: request.get(key)
            for key in self.REQUEST_FIELDS
            if key not in {"safe_payload_json", "safe_response_json"}
        }
        values["safe_payload_json"] = _canonical(redact_secrets(request.get("safe_payload") or {}))
        values["safe_response_json"] = _canonical(redact_secrets(request.get("safe_response") or {}))
        response = request.get("safe_response") or {}
        values["error_code"] = request.get("error_code") or response.get("code") or ""
        values["error_message"] = request.get("error_message") or response.get("message") or ""
        existing = frappe.db.exists("Overseas Cost ERP Sync Request", request["request_id"])
        if existing:
            frappe.db.set_value("Overseas Cost ERP Sync Request", existing, values)
        else:
            frappe.get_doc({"doctype": "Overseas Cost ERP Sync Request", **values}).insert(ignore_permissions=True)

    def save_link(self, link: dict) -> None:
        super().save_link(link)
        values = {key: link.get(key) for key in self.LINK_FIELDS if key != "name"}
        existing = link.get("name") or frappe.db.exists(
            "Overseas Cost ERP Document Link",
            {
                "batch": link.get("batch"),
                "site_code": link.get("site_code"),
                "stable_line_key": link.get("stable_line_key"),
                "business_key": link.get("business_key"),
            },
        )
        if existing:
            frappe.db.set_value("Overseas Cost ERP Document Link", existing, values)
        else:
            frappe.get_doc({"doctype": "Overseas Cost ERP Document Link", **values}).insert(ignore_permissions=True)

    def commit(self) -> None:
        super().commit()
        frappe.db.commit()


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
    accepted_site_codes: list[str] | None = None,
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
    accepted = set(accepted_site_codes or [])
    for site in preview.get("sites") or []:
        site_code = str(site.get("site_code") or "")
        if accepted and site_code not in accepted:
            continue
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


def _require_frappe() -> None:
    if frappe is None:
        raise RuntimeError("当前未连接 Frappe。")


def _resolved_version(batch_name: str, version_name: str | None = None) -> str:
    from overseas_costing.services import batch_service

    return str(batch_service._resolve_version_name(batch_name, version_name) or "")


def _route_items(batch_name: str, version_name: str | None = None) -> tuple[str, list[dict]]:
    _require_frappe()
    version = _resolved_version(batch_name, version_name)
    filters = {"batch": batch_name}
    if version:
        filters["version"] = version
    rows = frappe.get_all(
        "Overseas Cost Item",
        filters=filters,
        fields=[
            "name", "stable_line_key", "project_collection", "subsidiary_code", "erp_site_code",
            "route_status", "route_revision",
        ],
        order_by="row_no asc",
        limit_page_length=10000,
    )
    return version, rows


def get_route_preview(batch_name: str, version_name: str | None = None) -> dict:
    from overseas_costing.services import erp_routing_service

    version, items = _route_items(batch_name, version_name)
    routes = frappe.get_all(
        "Overseas Cost Project Route",
        fields=["project_collection", "subsidiary_code", "erp_site", "enabled", "valid_from", "valid_to", "revision"],
        limit_page_length=10000,
    )
    normalized_routes = [
        {**row, "site_code": row.get("erp_site") or "", "route_revision": row.get("revision") or ""}
        for row in routes
    ]
    result = erp_routing_service.resolve_item_routes(items, normalized_routes)
    site_options = frappe.get_all(
        "Overseas Cost ERP Site",
        fields=["site_code", "label", "subsidiary_code", "enabled", "capability_status"],
        order_by="site_code asc",
        limit_page_length=1000,
    )
    return {
        "ok": True,
        "batch_name": batch_name,
        "version_name": version,
        "site_options": site_options,
        **result,
    }


def preview_bulk_route(batch_name: str, target_site_code: str) -> dict:
    from overseas_costing.services import erp_routing_service

    _version, items = _route_items(batch_name)
    site = frappe.db.get_value(
        "Overseas Cost ERP Site",
        {"site_code": target_site_code},
        ["site_code", "subsidiary_code", "label", "enabled", "capability_status"],
        as_dict=True,
    )
    if not site or not int(site.get("enabled", 1) or 0):
        raise ValueError("ERP_SITE_NOT_AVAILABLE")
    result = erp_routing_service.preview_bulk_route(
        items,
        target_site=str(site.get("site_code") or target_site_code),
        target_subsidiary=str(site.get("subsidiary_code") or ""),
    )
    result["preview_revision"] = f"{target_site_code}:{result['preview_revision']}"
    result["site"] = {
        "site_code": site.get("site_code") or "",
        "label": site.get("label") or "",
        "subsidiary_code": site.get("subsidiary_code") or "",
        "capability_status": site.get("capability_status") or "UNVERIFIED",
    }
    return {"ok": True, "batch_name": batch_name, **result}


def apply_bulk_route(
    *, batch_name: str, preview_revision: str, edit_token: str, expected_modified: str
) -> dict:
    from overseas_costing.services import batch_service, edit_session_service, erp_routing_service

    if ":" not in str(preview_revision or ""):
        raise ValueError("ROUTE_PREVIEW_EXPIRED")
    target_site, expected_revision = str(preview_revision).split(":", 1)
    preview = preview_bulk_route(batch_name, target_site)
    actual_revision = str(preview.get("preview_revision") or "").split(":", 1)[-1]
    if actual_revision != expected_revision:
        raise RuntimeError("ROUTE_PREVIEW_STALE")
    edit_session_service.assert_batch_write(
        batch_name,
        edit_token=edit_token,
        expected_modified=expected_modified,
    )
    _version, items = _route_items(batch_name)
    preview_body = erp_routing_service.preview_bulk_route(
        items,
        target_site=target_site,
        target_subsidiary=str((preview.get("site") or {}).get("subsidiary_code") or ""),
    )
    names_by_key = {str(row.get("stable_line_key") or row.get("name") or ""): row.get("name") for row in items}
    for stable_key, updates in preview_body.get("updates", {}).items():
        item_name = names_by_key.get(stable_key)
        if not item_name:
            continue
        frappe.db.set_value(
            "Overseas Cost Item",
            item_name,
            {**updates, "route_revision": expected_revision, "manual_override_flag": 1},
        )
    batch_service._insert_batch_audit_log(
        batch_name,
        _resolved_version(batch_name),
        "ERP_ROUTE_OVERRIDE",
        "erp_site_code",
        new_value=target_site,
        action_remark=f"整批归属 {target_site}，变更 {len(preview_body.get('changed_item_keys') or [])} 行。",
    )
    frappe.db.commit()
    return {"ok": True, "changed_item_keys": preview_body.get("changed_item_keys") or [], "route_revision": expected_revision}


def preview_erp_sync(batch_name: str, version_name: str | None = None) -> dict:
    from overseas_costing.services import batch_service

    detail = batch_service.get_batch_detail(batch_name, version_name)
    if not detail.get("ok"):
        return detail
    return {
        "ok": True,
        "batch_name": detail.get("batch_name") or batch_name,
        "version_name": detail.get("version_name") or version_name,
        "erp_push": detail.get("erp_push") or {},
        "erp_work": detail.get("erp_work") or {},
    }


def _site_configs(site_codes: list[str]) -> dict[str, dict]:
    _require_frappe()
    rows = frappe.get_all(
        "Overseas Cost ERP Site",
        filters={"site_code": ["in", site_codes]},
        fields=[
            "name", "site_code", "subsidiary_code", "enabled", "base_url", "push_mode", "company",
            "default_supplier", "cost_center", "default_currency", "stock_uom", "cost_update_mode",
            "capability_status",
        ],
        limit_page_length=len(site_codes) or 1,
    )
    configs = {}
    for row in rows:
        document = frappe.get_doc("Overseas Cost ERP Site", row.get("name") or row.get("site_code"))
        authorization = document.get_password("authorization", raise_exception=False)
        base_url = str(row.get("base_url") or "").rstrip("/")
        if base_url and "/api/resource" not in base_url:
            base_url = f"{base_url}/api/resource"
        configs[str(row.get("site_code") or "")] = {
            **row,
            "base_url": base_url,
            "authorization": authorization,
            "push_mode": "standard_purchase",
            "supplier": row.get("default_supplier") or "",
            "item_group": "All Item Groups",
            "timeout": 20,
        }
    return configs


def start_erp_create(*, batch_name: str, cost_result_hash: str, request_key: str) -> dict:
    from overseas_costing.services import erp_client

    preview_result = preview_erp_sync(batch_name)
    push = preview_result.get("erp_push") or {}
    if str(push.get("cost_result_hash") or "") != str(cost_result_hash or ""):
        return {"ok": False, "code": "COST_RESULT_STALE", "message": "成本结果已变更，请重新预览。"}
    if not push.get("ready"):
        return {"ok": False, "code": "ERP_PUSH_BLOCKED", "blocking": push.get("blocking") or []}
    site_codes = list(push.get("referenced_sites") or [])
    configs = _site_configs(site_codes)
    if any(str(config.get("capability_status") or "").upper() != "VERIFIED" for config in configs.values()):
        return {"ok": False, "code": "ERP_SITE_UNVERIFIED"}
    store = FrappeSyncStore(batch_name)
    result = execute_site_pushes(
        batch=batch_name,
        version=str(preview_result.get("version_name") or ""),
        cost_result_hash=cost_result_hash,
        preview=push.get("preview") or {},
        site_configs=configs,
        intent_key=request_key,
        client=erp_client,
        store=store,
    )
    return {"ok": result.get("status") == "SUCCESS", **result}


def _current_cost_items(push: dict) -> list[dict]:
    rows = []
    for site in (push.get("preview") or {}).get("sites") or []:
        for group in site.get("groups") or []:
            for item in group.get("items") or []:
                rows.append(
                    {
                        **item,
                        "site_code": site.get("site_code") or "",
                        "erp_site_code": site.get("site_code") or "",
                        "amount_status": "ESTIMATED" if item.get("estimated_fee_keys") else "ACTUAL",
                        "cost_result_hash": push.get("cost_result_hash") or "",
                    }
                )
    return rows


def _enriched_links(store: FrappeSyncStore) -> list[dict]:
    enriched = []
    for link in store.links:
        saved_payload = {}
        for request in store.requests:
            if (
                str(request.get("business_key") or "") == str(link.get("business_key") or "")
                and str(request.get("status") or "").upper() == "SUCCESS"
            ):
                saved_payload = request.get("safe_payload") or {}
                break
        item = next(
            (
                row for row in saved_payload.get("items") or []
                if str(row.get("stable_line_key") or "") == str(link.get("stable_line_key") or "")
            ),
            {},
        )
        formula = item.get("cost_formula") or {}
        logistics = (item.get("expense_detail") or {}).get("logistics") or {}
        customs = (item.get("expense_detail") or {}).get("clearance_and_tax") or {}
        enriched.append(
            {
                **link,
                "subsidiary_code": saved_payload.get("subsidiary_code") or "",
                "quantity": item.get("source_quantity") or formula.get("quantity") or 0,
                "goods_value": item.get("goods_value") or formula.get("goods_value") or 0,
                "total_cost_rmb": item.get("total_cost_rmb") or formula.get("total_cost") or 0,
                "total_unit_rmb": item.get("total_unit_rmb") or formula.get("comprehensive_unit_price") or 0,
                "freight_alloc_rmb": item.get("freight_alloc_rmb") or logistics.get("freight_alloc_rmb") or 0,
                "clearance_alloc_rmb": item.get("clearance_alloc_rmb") or customs.get("clearance_alloc_rmb") or 0,
                "tax_alloc_rmb": item.get("tax_alloc_rmb") or customs.get("tax_alloc_rmb") or 0,
                "amount_status": saved_payload.get("amount_status") or "ACTUAL",
            }
        )
    return enriched


def preview_erp_updates(*, batch_name: str, from_hash: str, to_hash: str) -> dict:
    preview_result = preview_erp_sync(batch_name)
    push = preview_result.get("erp_push") or {}
    if str(push.get("cost_result_hash") or "") != str(to_hash or ""):
        return {"ok": False, "code": "COST_RESULT_STALE"}
    store = FrappeSyncStore(batch_name)
    result = preview_cost_updates(
        old_links=_enriched_links(store),
        new_items=_current_cost_items(push),
        from_hash=from_hash,
        to_hash=to_hash,
    )
    result["preview_revision"] = _hash(result)
    return {"ok": result.get("ready", False), **result}


def start_erp_updates(
    *, batch_name: str, to_hash: str, accepted_site_codes: list[str], request_key: str
) -> dict:
    from overseas_costing.services import erp_client

    store = FrappeSyncStore(batch_name)
    old_links = _enriched_links(store)
    old_hashes = sorted({str(row.get("last_cost_result_hash") or "") for row in old_links if row.get("last_cost_result_hash")})
    from_hash = old_hashes[0] if len(old_hashes) == 1 else ""
    preview = preview_erp_updates(batch_name=batch_name, from_hash=from_hash, to_hash=to_hash)
    allowed_sites = {str(row.get("site_code") or "") for row in preview.get("sites") or []}
    accepted = set(accepted_site_codes or [])
    if not accepted or not accepted <= allowed_sites:
        return {"ok": False, "code": "SITE_SELECTION_STALE", "allowed_site_codes": sorted(allowed_sites)}
    push = (preview_erp_sync(batch_name).get("erp_push") or {})
    new_items = _current_cost_items(push)
    configs = _site_configs(sorted(accepted))
    result = execute_cost_updates(
        batch=batch_name,
        version="",
        from_hash=from_hash,
        to_hash=to_hash,
        new_items=new_items,
        site_configs=configs,
        intent_key=request_key,
        client=erp_client,
        store=store,
        accepted_site_codes=sorted(accepted),
    )
    return {"ok": result.get("status") == "SUCCESS", **result}


def get_erp_sync_status(batch_name: str) -> dict:
    result = preview_erp_sync(batch_name)
    return {"ok": result.get("ok", False), "batch_name": batch_name, "erp_work": result.get("erp_work") or {}}


def retry_erp_request(*, batch_name: str, request_id: str) -> dict:
    store = FrappeSyncStore(batch_name)
    request = next((row for row in store.requests if str(row.get("request_id") or "") == str(request_id or "")), None)
    if not request:
        return {"ok": False, "code": "ERP_REQUEST_NOT_FOUND"}
    if str(request.get("status") or "").upper() not in {"FAILED", "UNCERTAIN"}:
        return {"ok": False, "code": "ERP_REQUEST_NOT_RETRYABLE"}
    retry_key = f"retry:{request_id}:{int(request.get('attempt_count') or 0) + 1}"
    if str(request.get("operation") or "") == "CREATE":
        from overseas_costing.services import erp_client

        preview_result = preview_erp_sync(batch_name)
        push = preview_result.get("erp_push") or {}
        request_hash = str(request.get("cost_result_hash") or "")
        if request_hash != str(push.get("cost_result_hash") or ""):
            return {"ok": False, "code": "COST_RESULT_STALE", "message": "成本结果已变更，请重新预览。"}
        version = str(preview_result.get("version_name") or request.get("version") or "")
        retry_preview = filter_retry_preview(
            push.get("preview") or {}, batch=batch_name, version=version, request=request
        )
        if not retry_preview.get("sites"):
            return {"ok": False, "status": "MANUAL_REQUIRED", "code": "RETRY_GROUP_STALE"}
        result = execute_site_pushes(
            batch=batch_name,
            version=version,
            cost_result_hash=request_hash,
            preview=retry_preview,
            site_configs=_site_configs([str(request.get("site_code") or "")]),
            intent_key=retry_key,
            client=erp_client,
            store=store,
        )
        return {"ok": result.get("status") == "SUCCESS", **result}
    return {"ok": False, "status": "MANUAL_REQUIRED", "code": "UPDATE_RETRY_PREVIEW_REQUIRED"}
