"""多站点 ERP 路由和同步账本 DocType 契约测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _doctype(name: str, *, mirrored: bool = False) -> dict:
    prefix = ROOT / ("overseas_costing/doctype" if mirrored else "doctype")
    return json.loads((prefix / name / f"{name}.json").read_text(encoding="utf-8"))


def _fields(meta: dict) -> dict[str, dict]:
    return {row["fieldname"]: row for row in meta["fields"]}


def test_erp_site_credentials_are_not_readable_by_cost_user() -> None:
    site = _doctype("overseas_cost_erp_site")
    fields = _fields(site)
    permissions = {row["role"]: row for row in site["permissions"]}

    assert fields["site_code"]["unique"] == 1
    assert fields["authorization"]["fieldtype"] == "Password"
    assert not permissions.get("海外成本核算用户", {}).get("read")
    assert fields["cost_update_mode"]["options"].splitlines() == ["DISABLED", "MANUAL", "DRAFT_PURCHASE_ORDER"]


def test_project_route_and_item_hold_explicit_route_state() -> None:
    route = _fields(_doctype("overseas_cost_project_route"))
    item = _fields(_doctype("overseas_cost_item"))

    assert {"project_collection", "subsidiary_code", "erp_site", "enabled", "valid_from", "valid_to", "revision"} <= route.keys()
    assert {"subsidiary_code", "erp_site_code", "route_status", "route_revision"} <= item.keys()
    assert item["route_status"]["options"].splitlines() == ["UNRESOLVED", "RESOLVED", "OVERRIDDEN", "CONFLICT"]


def test_sync_request_has_unique_idempotency_key_and_safe_snapshots() -> None:
    request = _fields(_doctype("overseas_cost_erp_sync_request"))

    assert request["request_id"]["unique"] == 1
    assert request["operation"]["options"].splitlines() == ["CREATE", "UPDATE_COST", "VERIFY"]
    assert request["status"]["options"].splitlines() == [
        "PENDING", "RUNNING", "SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED", "SUPERSEDED"
    ]
    assert {"cost_result_hash", "payload_hash", "safe_payload_json", "safe_response_json", "attempt_count"} <= request.keys()


def test_document_link_uses_stable_line_and_remote_row_identity() -> None:
    link = _fields(_doctype("overseas_cost_erp_document_link"))

    assert {"batch", "stable_line_key", "site_code", "business_key", "remote_doctype", "remote_document", "remote_row", "remote_docstatus", "last_cost_result_hash", "last_payload_hash", "verified_at"} <= link.keys()


def test_new_erp_doctypes_are_byte_identical_to_deployment_mirrors() -> None:
    for name in (
        "overseas_cost_erp_site",
        "overseas_cost_project_route",
        "overseas_cost_erp_document_link",
        "overseas_cost_erp_sync_request",
    ):
        for filename in ("__init__.py", f"{name}.json", f"{name}.py"):
            assert (ROOT / "doctype" / name / filename).read_bytes() == (
                ROOT / "overseas_costing" / "doctype" / name / filename
            ).read_bytes()
