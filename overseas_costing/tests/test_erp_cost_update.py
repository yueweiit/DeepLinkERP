"""Provisional-to-actual ERP cost update safety tests."""

import pytest

from overseas_costing.services import erp_client
from overseas_costing.services.erp_sync_service import (
    InMemorySyncStore,
    execute_cost_updates,
    preview_cost_updates,
)


def _new_cost(**overrides) -> dict:
    row = {
        "stable_line_key": "P1",
        "site_code": "PROD",
        "subsidiary_code": "PROD_CO",
        "effective_shipped_qty": "34",
        "goods_value": "15300",
        "total_cost_rmb": "17000",
        "total_unit_rmb": "500",
        "freight_alloc_rmb": "900",
        "clearance_alloc_rmb": "500",
        "tax_alloc_rmb": "300",
        "cost_result_hash": "H2",
        "amount_status": "ACTUAL",
    }
    row.update(overrides)
    return row


def test_cost_update_payload_never_changes_quantity() -> None:
    body = erp_client.build_draft_purchase_cost_update(
        old_link={"remote_row": "POI-1", "stable_line_key": "P1", "quantity": "34"},
        new_cost=_new_cost(),
    )

    assert "qty" not in body
    assert "quantity" not in body
    assert body["custom_overseas_comprehensive_amount"] == "17000"
    assert body["custom_overseas_amount_status"] == "ACTUAL"


def test_quantity_change_requires_a_separate_business_change() -> None:
    with pytest.raises(ValueError, match="BUSINESS_CHANGE_REQUIRED"):
        erp_client.build_draft_purchase_cost_update(
            old_link={"stable_line_key": "P1", "quantity": "35"},
            new_cost=_new_cost(),
        )


def test_preview_detects_amount_or_nature_change_only_for_affected_site() -> None:
    old_links = [
        {
            "stable_line_key": "P1", "site_code": "PROD", "subsidiary_code": "PROD_CO",
            "quantity": "34", "total_cost_rmb": "16000", "total_unit_rmb": "470.59",
            "goods_value": "15300", "amount_status": "ESTIMATED", "remote_document": "PO-P",
        },
        {
            "stable_line_key": "E1", "site_code": "ECOM", "subsidiary_code": "ECOM_CO",
            "quantity": "10", "total_cost_rmb": "1000", "total_unit_rmb": "100",
            "goods_value": "900", "amount_status": "ESTIMATED", "remote_document": "PO-E",
        },
    ]
    new_rows = [
        _new_cost(),
        {
            "stable_line_key": "E1", "site_code": "ECOM", "subsidiary_code": "ECOM_CO",
            "effective_shipped_qty": "10", "total_cost_rmb": "1000", "total_unit_rmb": "100",
            "goods_value": "900", "amount_status": "ESTIMATED",
        },
    ]

    result = preview_cost_updates(old_links=old_links, new_items=new_rows, from_hash="H1", to_hash="H2")

    assert result["ready"] is True
    assert [site["site_code"] for site in result["sites"]] == ["PROD"]
    assert set(result["sites"][0]["items"][0]["changed_fields"]) >= {"total_cost_rmb", "amount_status"}
    assert result["noop_site_codes"] == ["ECOM"]


def test_equal_amounts_still_update_when_estimate_becomes_actual() -> None:
    old = [{
        "stable_line_key": "P1", "site_code": "PROD", "subsidiary_code": "PROD_CO",
        "quantity": "34", "goods_value": "15300", "total_cost_rmb": "17000",
        "total_unit_rmb": "500", "freight_alloc_rmb": "900", "clearance_alloc_rmb": "500",
        "tax_alloc_rmb": "300", "amount_status": "ESTIMATED", "remote_document": "PO-P",
    }]

    result = preview_cost_updates(old_links=old, new_items=[_new_cost()], from_hash="H1", to_hash="H2")

    assert result["sites"][0]["items"][0]["changed_fields"] == ["amount_status"]


def test_route_or_quantity_change_is_not_treated_as_cost_update() -> None:
    old = [{
        "stable_line_key": "P1", "site_code": "PROD", "subsidiary_code": "PROD_CO",
        "quantity": "34", "goods_value": "15300", "total_cost_rmb": "17000",
        "total_unit_rmb": "500", "amount_status": "ESTIMATED", "remote_document": "PO-P",
    }]

    result = preview_cost_updates(
        old_links=old,
        new_items=[_new_cost(site_code="ECOM", effective_shipped_qty="35")],
        from_hash="H1",
        to_hash="H2",
    )

    assert result["ready"] is False
    assert result["blocking"][0]["code"] == "BUSINESS_CHANGE_REQUIRED"


def test_draft_purchase_update_writes_only_cost_fields_and_header_markers(monkeypatch) -> None:
    requests = []
    monkeypatch.setattr(
        erp_client,
        "read_purchase_state",
        lambda link, config: {
            "data": {
                "docstatus": 0,
                "per_received": 0,
                "items": [{
                    "name": "POI-1",
                    "custom_overseas_stable_line_key": "P1",
                    "qty": "34",
                }],
            }
        },
    )
    monkeypatch.setattr(
        erp_client,
        "_request_json",
        lambda config, **kwargs: requests.append(kwargs) or {"data": {"name": "OK"}},
    )
    payload = {
        "version_code": "V2",
        "cost_result_hash": "H2",
        "document_total_cost_rmb": "17000",
        "items": [_new_cost()],
    }

    result = erp_client.update_purchase_cost(
        payload,
        {"remote_doctype": "Purchase Order", "remote_document": "PO-1", "remote_row": "POI-1", "stable_line_key": "P1"},
        {"base_url": "https://erp/api/resource", "authorization": "token hidden", "cost_update_mode": "DRAFT_PURCHASE_ORDER"},
    )

    assert result["status"] == "UPDATED"
    assert [request["method"] for request in requests] == ["PUT", "PUT"]
    item_body, header_body = [request["body"] for request in requests]
    assert not ({"qty", "supplier", "company", "project"} & set(item_body))
    assert set(header_body) == {
        "custom_overseas_cost_version",
        "custom_overseas_cost_result_hash",
        "custom_overseas_total_cost_rmb",
        "custom_overseas_amount_status",
    }


@pytest.mark.parametrize(
    ("mode", "docstatus", "per_received", "code"),
    [
        ("DISABLED", 0, 0, "UPDATE_MODE_UNAVAILABLE"),
        ("MANUAL", 0, 0, "MANUAL_COST_UPDATE_REQUIRED"),
        ("DRAFT_PURCHASE_ORDER", 1, 0, "DOCUMENT_NOT_DRAFT"),
        ("DRAFT_PURCHASE_ORDER", 0, 25, "DOCUMENT_HAS_RECEIPTS"),
    ],
)
def test_unsupported_or_consumed_documents_fail_closed(monkeypatch, mode, docstatus, per_received, code) -> None:
    monkeypatch.setattr(
        erp_client,
        "read_purchase_state",
        lambda link, config: {"data": {"docstatus": docstatus, "per_received": per_received, "items": []}},
    )

    result = erp_client.update_purchase_cost(
        {"items": [_new_cost()]},
        {"remote_doctype": "Purchase Order", "remote_document": "PO-1", "stable_line_key": "P1"},
        {"cost_update_mode": mode},
    )

    assert result["status"] == "MANUAL_REQUIRED"
    assert result["code"] == code


def test_cost_update_request_advances_only_the_affected_site_link() -> None:
    links = [
        {
            "stable_line_key": "P1", "site_code": "PROD", "subsidiary_code": "PROD_CO",
            "business_key": "BK-P", "remote_doctype": "Purchase Order", "remote_document": "PO-P",
            "remote_row": "POI-P", "quantity": "34", "goods_value": "15300",
            "total_cost_rmb": "16000", "total_unit_rmb": "470.59", "amount_status": "ESTIMATED",
            "last_cost_result_hash": "H1", "status": "SUCCESS",
        },
        {
            "stable_line_key": "E1", "site_code": "ECOM", "subsidiary_code": "ECOM_CO",
            "business_key": "BK-E", "remote_doctype": "Purchase Order", "remote_document": "PO-E",
            "remote_row": "POI-E", "quantity": "10", "goods_value": "900",
            "total_cost_rmb": "1000", "total_unit_rmb": "100", "amount_status": "ESTIMATED",
            "last_cost_result_hash": "H1", "status": "SUCCESS",
        },
    ]
    new_items = [
        _new_cost(),
        {
            "stable_line_key": "E1", "site_code": "ECOM", "subsidiary_code": "ECOM_CO",
            "effective_shipped_qty": "10", "goods_value": "900", "total_cost_rmb": "1000",
            "total_unit_rmb": "100", "amount_status": "ESTIMATED",
        },
    ]

    class FakeClient:
        calls = []

        @classmethod
        def update_purchase_cost(cls, payload, link, config):
            cls.calls.append((config["site_code"], link["stable_line_key"], payload))
            return {"ok": True, "status": "UPDATED"}

    store = InMemorySyncStore(links=links)
    result = execute_cost_updates(
        batch="B1", version="V2", from_hash="H1", to_hash="H2", new_items=new_items,
        site_configs={"PROD": {"site_code": "PROD", "cost_update_mode": "DRAFT_PURCHASE_ORDER"}},
        intent_key="UPDATE-1", client=FakeClient, store=store,
    )

    assert result["status"] == "SUCCESS"
    assert [(site, key) for site, key, _ in FakeClient.calls] == [("PROD", "P1")]
    assert next(row for row in store.links if row["stable_line_key"] == "P1")["last_cost_result_hash"] == "H2"
    assert next(row for row in store.links if row["stable_line_key"] == "E1")["last_cost_result_hash"] == "H2"
    assert {row["operation"] for row in store.requests} == {"UPDATE_COST"}
