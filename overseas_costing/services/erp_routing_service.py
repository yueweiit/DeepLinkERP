"""ERP 行级路由、整柜快捷归属与费用范围冻结规则。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime


READY_ROUTE_STATES = frozenset({"RESOLVED", "OVERRIDDEN"})


def normalize_project(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _route_is_active(route: dict, as_of: date | str | None = None) -> bool:
    if not int(route.get("enabled", 1) or 0):
        return False
    day = _date(as_of) or date.today()
    valid_from = _date(route.get("valid_from"))
    valid_to = _date(route.get("valid_to"))
    return not ((valid_from and valid_from > day) or (valid_to and valid_to < day))


def active_routes_by_project(routes: list[dict], *, as_of: date | str | None = None) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for route in routes or []:
        if _route_is_active(route, as_of):
            grouped[normalize_project(route.get("project_collection"))].append(route)
    return grouped


def _route_revision(route: dict) -> str:
    explicit = str(route.get("route_revision") or route.get("revision") or "").strip()
    if explicit:
        return explicit
    canonical = json.dumps(
        {
            "project": normalize_project(route.get("project_collection")),
            "subsidiary": str(route.get("subsidiary_code") or ""),
            "site": str(route.get("site_code") or route.get("erp_site_code") or route.get("erp_site") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _route_state(status: str, code: str = "", route: dict | None = None, item: dict | None = None) -> dict:
    route = route or {}
    item = item or {}
    return {
        "status": status,
        "code": code,
        "project_collection": item.get("project_collection") or route.get("project_collection") or "",
        "subsidiary_code": route.get("subsidiary_code") or "",
        "site_code": route.get("site_code") or route.get("erp_site_code") or route.get("erp_site") or "",
        "route_revision": _route_revision(route) if route else "",
    }


def resolve_item_routes(
    items: list[dict],
    routes: list[dict],
    *,
    as_of: date | str | None = None,
) -> dict:
    by_project = active_routes_by_project(routes, as_of=as_of)
    result = {}
    for item in items or []:
        item_key = str(item.get("stable_line_key") or item.get("name") or "").strip()
        if not item_key:
            continue
        if str(item.get("route_status") or "").upper() == "OVERRIDDEN":
            result[item_key] = _route_state("OVERRIDDEN", route=item, item=item)
            continue
        project = str(item.get("project_collection") or "").strip()
        matches = by_project.get(normalize_project(project), [])
        if not project:
            resolved = _route_state("UNRESOLVED", "PROJECT_REQUIRED", item=item)
        elif not matches:
            resolved = _route_state("UNRESOLVED", "ROUTE_NOT_CONFIGURED", item=item)
        elif len(matches) != 1:
            resolved = _route_state("CONFLICT", "MULTIPLE_ACTIVE_ROUTES", item=item)
        else:
            resolved = _route_state("RESOLVED", route=matches[0], item=item)
        result[item_key] = resolved
    return {
        "by_item": result,
        "ready": bool(result) and all(row["status"] in READY_ROUTE_STATES for row in result.values()),
        "blocking": [
            {"stable_line_key": key, **row}
            for key, row in result.items()
            if row["status"] not in READY_ROUTE_STATES
        ],
    }


def _preview_revision(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def preview_bulk_route(items: list[dict], *, target_site: str, target_subsidiary: str = "") -> dict:
    site = str(target_site or "").strip()
    subsidiary = str(target_subsidiary or "").strip()
    if not site:
        raise ValueError("TARGET_SITE_REQUIRED")
    changed = []
    updates = {}
    overwritten = []
    unchanged = []
    for item in items or []:
        key = str(item.get("stable_line_key") or item.get("name") or "").strip()
        if not key:
            continue
        current_site = str(item.get("erp_site_code") or item.get("site_code") or "").strip()
        current_subsidiary = str(item.get("subsidiary_code") or "").strip()
        if current_site == site and (not subsidiary or current_subsidiary == subsidiary):
            unchanged.append(key)
            continue
        changed.append(key)
        if current_site and current_site != site:
            overwritten.append(key)
        updates[key] = {
            "subsidiary_code": subsidiary,
            "erp_site_code": site,
            "route_status": "OVERRIDDEN",
        }
    body = {
        "target_site": site,
        "target_subsidiary": subsidiary,
        "changed_item_keys": sorted(changed),
        "overwritten_item_keys": sorted(overwritten),
        "unchanged_item_keys": sorted(unchanged),
        "updates": {key: updates[key] for key in sorted(updates)},
    }
    return {
        **body,
        "requires_confirmation": bool(overwritten),
        "preview_revision": _preview_revision(body),
    }


def resolve_subsidiary_scope(*, subsidiary_code: str, item_routes: dict[str, dict]) -> dict:
    target = str(subsidiary_code or "").strip()
    keys = sorted(
        key
        for key, route in (item_routes or {}).items()
        if route.get("status") in READY_ROUTE_STATES
        and str(route.get("subsidiary_code") or "").strip() == target
    )
    revisions = [str((item_routes.get(key) or {}).get("route_revision") or "") for key in keys]
    return {
        "scope_type": "ITEMS",
        "scope_item_keys": keys,
        "scope_revision": _preview_revision({"subsidiary_code": target, "items": list(zip(keys, revisions))}),
        "ready": bool(keys),
    }
