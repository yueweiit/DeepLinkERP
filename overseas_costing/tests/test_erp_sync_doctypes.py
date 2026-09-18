from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIRROR_ROOT = ROOT / "overseas_costing"


def _doctype(name: str) -> dict:
    path = ROOT / "doctype" / name / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_erp_site_credentials_are_not_readable_by_cost_user() -> None:
    site = _doctype("overseas_cost_erp_site")
    fields = {row["fieldname"]: row for row in site["fields"]}
    permissions = {row["role"]: row for row in site["permissions"]}

    assert fields["authorization"]["fieldtype"] == "Password"
    assert not permissions.get("海外成本核算用户", {}).get("read")


def test_sync_request_has_unique_idempotency_key() -> None:
    request = _doctype("overseas_cost_erp_sync_request")
    fields = {row["fieldname"]: row for row in request["fields"]}

    assert fields["request_id"]["unique"] == 1


def test_item_has_explicit_erp_route_fields() -> None:
    item = _doctype("overseas_cost_item")
    fields = {row["fieldname"]: row for row in item["fields"]}

    assert fields["erp_site_code"]["fieldtype"] == "Data"
    assert fields["route_status"]["options"] == "UNRESOLVED\nRESOLVED\nOVERRIDDEN\nCONFLICT"


def test_erp_sync_doctypes_are_valid_json() -> None:
    for name in (
        "overseas_cost_erp_site",
        "overseas_cost_project_route",
        "overseas_cost_erp_document_link",
        "overseas_cost_erp_sync_request",
    ):
        assert _doctype(name)["doctype"] == "DocType"


def test_erp_sync_doctype_mirrors_match_packaged_definitions() -> None:
    for name in (
        "overseas_cost_erp_site",
        "overseas_cost_project_route",
        "overseas_cost_erp_document_link",
        "overseas_cost_erp_sync_request",
    ):
        source = _doctype(name)
        mirror_path = MIRROR_ROOT / "doctype" / name / f"{name}.json"
        mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
        assert mirror == source
