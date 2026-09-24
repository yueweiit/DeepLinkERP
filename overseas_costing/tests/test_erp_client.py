from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from overseas_costing.services import erp_client


class _JsonResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_read_erpnext_doctype_metadata_rejects_incomplete_config_without_leaking_secret() -> None:
    result = erp_client.read_erpnext_doctype_metadata(
        {"base_url": "https://erp.example.com/api/resource", "authorization": ""},
        ["Purchase Order"],
    )

    assert result["ok"] is False
    assert result["request"]["authorization_configured"] is False
    assert "缺少 DeepLinkERP 鉴权配置" in result["errors"]["config"]


def test_metadata_config_rejects_authorization_without_scheme() -> None:
    """裸 key:secret 会被 ERPNext 当作匿名请求返回 403，必须提前拦下。"""

    result = erp_client.read_erpnext_doctype_metadata(
        {"base_url": "https://erp.example.com/api/resource", "authorization": "abc:def"},
        ["Purchase Order"],
    )

    assert result["ok"] is False
    assert "鉴权配置格式应为 token <api_key>:<api_secret>" in result["errors"]["config"]


def test_read_erpnext_doctype_metadata_reads_each_doctype_with_get(monkeypatch) -> None:
    captured = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def read():
            return b'{"data":{"fields":[{"fieldname":"custom_field"}]}}'

    def fake_urlopen(request, timeout):
        captured.append({"url": request.full_url, "method": request.get_method(), "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)
    result = erp_client.read_erpnext_doctype_metadata(
        {"base_url": "https://erp.example.com/api/resource", "authorization": "token abc:def", "timeout": 7},
        ["Purchase Order", "Purchase Order Item"],
    )

    assert result["ok"] is True
    assert [row["method"] for row in captured] == ["GET", "GET"]
    assert captured[0]["url"].endswith("/DocType/Purchase%20Order")
    assert captured[1]["url"].endswith("/DocType/Purchase%20Order%20Item")
    assert result["metadata"]["Purchase Order"]["fields"][0]["fieldname"] == "custom_field"


def test_read_erpnext_doctype_metadata_returns_structured_http_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise HTTPError(request.full_url, 403, "Forbidden", None, io.BytesIO(b'{"exc":"forbidden"}'))

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)
    result = erp_client.read_erpnext_doctype_metadata(
        {"base_url": "https://erp.example.com/api/resource", "authorization": "token abc:def"},
        ["Purchase Order"],
    )

    assert result["ok"] is False
    assert result["errors"]["Purchase Order"]["http_status"] == 403
    assert result["errors"]["Purchase Order"]["response"] == {"exc": "forbidden"}


def test_get_erp_push_config_prefers_single_settings(monkeypatch) -> None:
    class FakeSettings:
        def get(self, fieldname, default=None):
            return {
                "enabled": 1,
                "base_url": "https://erp.example.com/api/resource",
                "target_doctype": "Overseas Cost Push",
                "http_method": "post",
                "timeout": 30,
                "payload_field": "payload_json",
                "field_map_json": "{\"name\": \"batch_name\"}",
            }.get(fieldname, default)

        @staticmethod
        def get_password(fieldname, raise_exception=False):
            assert fieldname == "authorization"
            return "token abc:def"

    class FakeDB:
        @staticmethod
        def exists(doctype, name):
            return doctype == "DocType" and name == "Overseas Cost ERP Settings"

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_single(doctype):
            assert doctype == "Overseas Cost ERP Settings"
            return FakeSettings()

    monkeypatch.setattr(erp_client, "frappe", FakeFrappe)
    monkeypatch.setattr(erp_client.os.environ, "get", lambda key, default=None: None)

    config = erp_client.get_erp_push_config()

    assert config["base_url"] == "https://erp.example.com/api/resource"
    assert config["authorization"] == "token abc:def"
    assert config["target_doctype"] == "Overseas Cost Push"
    assert config["push_mode"] == "standard_purchase"
    assert config["method"] == "POST"
    assert config["timeout"] == 30
    assert config["field_map"] == {"name": "batch_name"}
    assert config["payload_field"] == "payload_json"


def test_check_erp_connection_uses_get_without_writing(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "target_doctype": "Overseas Cost Push",
            "method": "POST",
            "timeout": 30,
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def read():
            return json.dumps({"data": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.check_erp_connection()

    assert result["ok"] is True
    assert captured == {
        "url": "https://erp.example.com/api/resource/Overseas%20Cost%20Push?limit_page_length=1",
        "method": "GET",
        "timeout": 30,
    }


def test_check_erp_connection_ignores_push_only_gaps(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "supplier": "",
            "item_group": "",
            "stock_uom": "",
            "timeout": 30,
            "target_doctype": "",
            "method": "POST",
            "field_map": {},
            "payload_field": "payload_json",
        },
    )
    requested = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def read():
            return json.dumps({"data": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.check_erp_connection()

    assert result["ok"] is True
    assert result["config_ready"] is True
    assert len(requested) == 2


def test_push_standard_purchase_flow_creates_item_and_purchase_order(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "company": "Empresas Mexico",
            "supplier": "Default Supplier",
            "cost_center": "Main - EM",
            "item_group": "Products",
            "stock_uom": "Nos",
            "default_currency": "CNY",
            "schedule_date": "2026-08-20",
            "target_doctype": "",
            "method": "POST",
            "timeout": 30,
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    captured = []

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        captured.append({"url": request.full_url, "method": request.get_method(), "body": body, "timeout": timeout})
        if request.get_method() == "GET" and "/Purchase%20Order?" in request.full_url:
            return FakeResponse({"data": []})
        if request.get_method() == "GET" and request.full_url.endswith("/Purchase%20Order/PO-0001"):
            return FakeResponse({"data": {"name": "PO-0001", "docstatus": 0}})
        if request.get_method() == "GET" and "/Item/YL000001" in request.full_url:
            raise HTTPError(request.full_url, 404, "Not Found", None, io.BytesIO(b"{}"))
        if request.get_method() == "POST" and request.full_url.endswith("/Item"):
            return FakeResponse({"data": {"name": "YL000001"}})
        if request.get_method() == "POST" and request.full_url.endswith("/Purchase%20Order"):
            return FakeResponse({"data": {"name": "PO-0001"}})
        if request.get_method() == "POST" and request.full_url.endswith("/frappe.client.submit"):
            return FakeResponse({"message": "submitted"})
        raise AssertionError(f"unexpected request {request.get_method()} {request.full_url}")

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.push_overseas_cost_payload(
        {
            "batch_no": "BATCH-001",
            "version_code": "V1",
            "subsidiary_code": "Empresas Mexico",
            "warehouse": "Stores - EM",
            "total_cost_rmb": 25,
            "items": [
                {
                    "material_code": "YL000001",
                    "material_name": "太阳眼镜",
                    "supplier": "HUAFON",
                    "purchase_currency": "RMB",
                    "source_quantity": 2,
                    "original_unit_price": 8,
                    "comprehensive_unit_price": 12.5,
                    "cost_formula": {
                        "goods_value": 16,
                        "total_cost": 25,
                        "allocated_logistics_cost": 6,
                    },
                    "expense_detail": {
                        "logistics": {"freight_alloc_rmb": 6},
                        "clearance_and_tax": {"clearance_alloc_rmb": 2, "tax_alloc_rmb": 1},
                    },
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["erp_target_doc"] == "PO-0001"
    assert result["submit"]["docstatus"] == 1
    item_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/Item"))
    po_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/Purchase%20Order"))
    submit_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/frappe.client.submit"))
    assert submit_body == {"doc": {"doctype": "Purchase Order", "name": "PO-0001"}}
    assert item_body["item_code"] == "YL000001"
    assert item_body["stock_uom"] == "Nos"
    assert result["response"]["items"][0]["uom_source"] == "local"
    assert item_body["custom_overseas_supplier"] == "HUAFON"
    assert item_body["custom_overseas_comprehensive_unit_price"] == 12.5
    assert po_body["company"] == "Empresas Mexico"
    assert po_body["supplier"] == "HUAFON"
    assert po_body["custom_overseas_supplier_source"] == "item"
    assert po_body["currency"] == "CNY"
    assert po_body["items"][0]["rate"] == 8
    assert po_body["items"][0]["warehouse"] == "Stores - EM"
    assert po_body["items"][0]["custom_overseas_comprehensive_amount"] == 25
    assert po_body["items"][0]["custom_overseas_freight_alloc_amount"] == 6
    assert po_body["items"][0]["custom_overseas_clearance_alloc_amount"] == 2
    assert po_body["items"][0]["custom_overseas_tax_alloc_amount"] == 1
    assert po_body["items"][0]["custom_overseas_cost_center"] == "Main - EM"
    assert all("valuation_rate" not in (row["body"] or {}) for row in captured)


def test_purchase_order_item_reconciles_displayed_cost_amounts() -> None:
    row = erp_client._build_purchase_order_item(
        {
            "material_code": "YL000001",
            "cost_formula": {"goods_value": 107968.413496, "total_cost": 146743.38825},
            "expense_detail": {
                "logistics": {"freight_alloc_rmb": 9619.873947},
                "clearance_and_tax": {"clearance_alloc_rmb": 29155.100807, "tax_alloc_rmb": 0},
            },
        },
        {"batch_no": "BATCH-001"},
        {"stock_uom": "Nos"},
        "2026-09-01",
    )

    assert row["custom_overseas_comprehensive_amount"] == 146743.39
    assert row["custom_overseas_clearance_alloc_amount"] == 29155.11
    assert sum(
        row[fieldname]
        for fieldname in (
            "custom_overseas_original_amount",
            "custom_overseas_freight_alloc_amount",
            "custom_overseas_clearance_alloc_amount",
            "custom_overseas_tax_alloc_amount",
        )
    ) == row["custom_overseas_comprehensive_amount"]


def test_existing_purchase_order_is_checked_before_any_item_write(monkeypatch) -> None:
    writes = []
    submitted = []
    monkeypatch.setattr(
        erp_client,
        "lookup_purchase_by_business_key",
        lambda payload, config: {"found": True, "name": "PO-1"},
    )
    monkeypatch.setattr(erp_client, "_ensure_item", lambda item, payload, config: writes.append(item))
    monkeypatch.setattr(
        erp_client,
        "_submit_purchase_order",
        lambda docname, config: submitted.append(docname) or {"ok": True, "docstatus": 1, "message": "已提交。"},
    )

    result = erp_client.create_purchase(
        {"business_key": "BK1", "items": [{"material_code": "M1"}]},
        {"base_url": "https://erp.invalid/api/resource", "authorization": "token hidden", "timeout": 1},
    )

    assert result["status"] == "EXISTS"
    assert result["ok"] is True
    assert writes == []
    assert submitted == ["PO-1"]


def test_standard_group_push_deduplicates_by_company_scoped_business_key(monkeypatch) -> None:
    looked_up = []
    monkeypatch.setattr(
        erp_client,
        "_find_existing_purchase_order_by_business_key",
        lambda payload, config: looked_up.append(payload["business_key"]) or "PO-EXISTING",
    )
    monkeypatch.setattr(
        erp_client,
        "_find_existing_purchase_order",
        lambda payload, config: (_ for _ in ()).throw(AssertionError("must not use batch-level lookup")),
    )
    monkeypatch.setattr(
        erp_client,
        "_ensure_item",
        lambda item, payload, config: (_ for _ in ()).throw(AssertionError("existing purchase must not write items")),
    )
    submitted = []
    monkeypatch.setattr(
        erp_client,
        "_submit_purchase_order",
        lambda docname, config: submitted.append(docname) or {"ok": True, "docstatus": 1, "message": "已提交"},
    )
    config = {
        "enabled": True,
        "base_url": "https://erp.example.com/api/resource",
        "authorization": "token abc:def",
        "push_mode": "standard_purchase",
        "supplier": "SUP",
        "item_group": "Products",
        "stock_uom": "Nos",
        "timeout": 30,
    }

    first = erp_client.push_overseas_cost_payload_with_config(
        {
            "batch_no": "B1",
            "subsidiary_code": "Company A",
            "business_key": "PURCHASE:B1:Company A:SUP:CNY:Nos",
            "items": [{"material_code": "M1"}],
        },
        config,
    )
    second = erp_client.push_overseas_cost_payload_with_config(
        {
            "batch_no": "B1",
            "subsidiary_code": "Company B",
            "business_key": "PURCHASE:B1:Company B:SUP:CNY:Nos",
            "items": [{"material_code": "M2"}],
        },
        config,
    )

    assert first["erp_target_doc"] == "PO-EXISTING"
    assert second["erp_target_doc"] == "PO-EXISTING"
    assert looked_up == [
        "PURCHASE:B1:Company A:SUP:CNY:Nos",
        "PURCHASE:B1:Company B:SUP:CNY:Nos",
    ]
    assert submitted == ["PO-EXISTING", "PO-EXISTING"]


def test_standard_group_push_propagates_unknown_network_outcome(monkeypatch) -> None:
    monkeypatch.setattr(erp_client, "_find_existing_purchase_order_by_business_key", lambda payload, config: "")
    monkeypatch.setattr(erp_client, "_ensure_item", lambda item, payload, config: {"ok": True})
    monkeypatch.setattr(
        erp_client,
        "_request_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("response lost after POST")),
    )
    config = {
        "enabled": True,
        "base_url": "https://erp.example.com/api/resource",
        "authorization": "token abc:def",
        "push_mode": "standard_purchase",
        "supplier": "SUP",
        "item_group": "Products",
        "stock_uom": "Nos",
        "timeout": 30,
    }

    with pytest.raises(TimeoutError, match="response lost after POST"):
        erp_client.push_overseas_cost_payload_with_config(
            {
                "batch_no": "B1",
                "subsidiary_code": "Company A",
                "business_key": "PURCHASE:B1:Company A:SUP:CNY:Nos",
                "items": [{"material_code": "M1"}],
            },
            config,
        )


def test_explicit_purchase_body_carries_stable_sync_fields() -> None:
    body = erp_client._build_purchase_order_body(
        {
            "batch_no": "B1",
            "business_key": "BK1",
            "cost_result_hash": "H1",
            "amount_status": "ESTIMATED",
            "items": [{"material_code": "M1", "stable_line_key": "L1"}],
        },
        {"stock_uom": "Nos", "default_currency": "CNY"},
    )

    assert body["custom_overseas_business_key"] == "BK1"
    assert body["custom_overseas_cost_result_hash"] == "H1"
    assert body["items"][0]["custom_overseas_stable_line_key"] == "L1"


def test_routed_payload_company_overrides_legacy_global_default() -> None:
    body = erp_client._build_purchase_order_body(
        {
            "batch_no": "B1",
            "subsidiary_code": "YW MOLDES MX模具",
            "items": [{"material_code": "M1", "stable_line_key": "L1", "supplier": "SUP"}],
        },
        {"company": "LEGACY DEFAULT", "stock_uom": "Nos", "default_currency": "CNY"},
    )

    assert body["company"] == "YW MOLDES MX模具"


def test_purchase_order_and_item_use_real_material_uom_before_global_default() -> None:
    payload = {
        "batch_no": "B1",
        "erp_stock_uom": "kg",
        "items": [
            {
                "material_code": "M1",
                "purchase_uom": "kg",
                "source_quantity": 2,
            }
        ],
    }

    item_body = erp_client._build_item_body(payload["items"][0], payload, {"stock_uom": "Nos"})
    purchase_body = erp_client._build_purchase_order_body(payload, {"stock_uom": "Nos", "default_currency": "CNY"})

    assert item_body["stock_uom"] == "kg"
    assert purchase_body["items"][0]["uom"] == "kg"
    assert purchase_body["items"][0]["stock_uom"] == "kg"


def test_standard_purchase_flow_uses_default_supplier_when_item_suppliers_conflict(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "company": "Empresas Mexico",
            "supplier": "Default Supplier",
            "cost_center": "",
            "item_group": "Products",
            "stock_uom": "Nos",
            "default_currency": "CNY",
            "schedule_date": "2026-08-20",
            "target_doctype": "",
            "method": "POST",
            "timeout": 30,
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    captured = []

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        captured.append({"url": request.full_url, "method": request.get_method(), "body": body})
        if request.get_method() == "GET" and "/Purchase%20Order?" in request.full_url:
            return FakeResponse({"data": []})
        if request.get_method() == "GET" and request.full_url.endswith("/Purchase%20Order/PO-0002"):
            return FakeResponse({"data": {"name": "PO-0002", "docstatus": 0}})
        if request.get_method() == "GET" and "/Item/" in request.full_url:
            raise HTTPError(request.full_url, 404, "Not Found", None, io.BytesIO(b"{}"))
        if request.get_method() == "POST" and request.full_url.endswith("/Item"):
            return FakeResponse({"data": {"name": body["item_code"]}})
        if request.get_method() == "POST" and request.full_url.endswith("/Purchase%20Order"):
            return FakeResponse({"data": {"name": "PO-0002"}})
        if request.get_method() == "POST" and request.full_url.endswith("/frappe.client.submit"):
            return FakeResponse({"message": "submitted"})
        raise AssertionError(f"unexpected request {request.get_method()} {request.full_url}")

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.push_overseas_cost_payload(
        {
            "batch_no": "BATCH-002",
            "version_code": "V1",
            "subsidiary_code": "Empresas Mexico",
            "items": [
                {"material_code": "A001", "material_name": "A", "supplier": "Supplier A", "source_quantity": 1, "original_unit_price": 1},
                {"material_code": "B001", "material_name": "B", "supplier": "Supplier B", "source_quantity": 1, "original_unit_price": 1},
            ],
        }
    )

    po_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/Purchase%20Order"))
    assert result["ok"] is True
    assert po_body["supplier"] == "Default Supplier"
    assert po_body["custom_overseas_supplier_source"] == "config"


def test_existing_erp_item_uses_remote_uom_without_overwriting_it(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "company": "",
            "supplier": "",
            "cost_center": "",
            "item_group": "Products",
            "stock_uom": "Nos",
            "default_currency": "CNY",
            "schedule_date": "2026-08-20",
            "target_doctype": "",
            "method": "POST",
            "timeout": 30,
            "field_map": {},
            "payload_field": "payload_json",
        },
    )
    captured = []

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        captured.append({"url": request.full_url, "method": request.get_method(), "body": body})
        if request.get_method() == "GET" and "/Purchase%20Order?" in request.full_url:
            return FakeResponse({"data": []})
        if request.get_method() == "GET" and request.full_url.endswith("/Purchase%20Order/PO-0002"):
            return FakeResponse({"data": {"name": "PO-0002", "docstatus": 0}})
        if request.get_method() == "GET" and "/Item/YL000001" in request.full_url:
            return FakeResponse({"data": {"name": "YL000001", "stock_uom": "个：pieza"}})
        if request.get_method() == "PUT" and "/Item/YL000001" in request.full_url:
            return FakeResponse({"data": {"name": "YL000001"}})
        if request.get_method() == "POST" and request.full_url.endswith("/Purchase%20Order"):
            return FakeResponse({"data": {"name": "PO-0002"}})
        if request.get_method() == "POST" and request.full_url.endswith("/frappe.client.submit"):
            return FakeResponse({"message": "submitted"})
        raise AssertionError(f"unexpected request {request.get_method()} {request.full_url}")

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client.push_overseas_cost_payload(
        {
            "batch_no": "BATCH-002",
            "version_code": "V1",
            "subsidiary_code": "Empresas Mexico",
            "business_key": "PURCHASE:BATCH-002:Empresas Mexico:HUAFON:CNY:个",
            "items": [
                {
                    "material_code": "YL000001",
                    "material_name": "太阳眼镜",
                    "supplier": "HUAFON",
                    "unit": "个",
                    "purchase_currency": "RMB",
                    "source_quantity": 2,
                    "original_unit_price": 8,
                }
            ],
        }
    )

    item_body = next(row["body"] for row in captured if row["method"] == "PUT" and row["url"].endswith("/Item/YL000001"))
    po_body = next(row["body"] for row in captured if row["method"] == "POST" and row["url"].endswith("/Purchase%20Order"))

    assert result["ok"] is True
    assert "stock_uom" not in item_body
    assert result["items"][0]["action"] == "updated"
    assert result["items"][0]["uom"] == "个：pieza"
    assert result["items"][0]["uom_source"] == "erp"
    assert po_body["items"][0]["uom"] == "个：pieza"
    assert po_body["items"][0]["stock_uom"] == "个：pieza"


def test_validate_payload_for_push_accepts_missing_default_stock_uom(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "supplier": "HUAFON",
            "item_group": "Products",
            "stock_uom": "",
            "timeout": 30,
            "target_doctype": "",
            "method": "POST",
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    result = erp_client.validate_payload_for_push({"items": [{"material_code": "A001"}]})

    assert result["ok"] is True
    assert result["blocking_reasons"] == []


def test_validate_payload_for_push_blocks_missing_supplier_in_standard_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "supplier": "",
            "item_group": "Products",
            "stock_uom": "Nos",
            "timeout": 30,
            "target_doctype": "",
            "method": "POST",
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    result = erp_client.validate_payload_for_push({"items": [{"material_code": "A001"}]})

    assert result["ok"] is False
    assert result["config_ready"] is False
    assert "缺少默认供应商配置" in result["blocking_reasons"]
    assert result["request"]["authorization_configured"] is True


def test_validate_payload_for_push_accepts_payload_supplier_in_standard_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        erp_client,
        "get_erp_push_config",
        lambda: {
            "enabled": True,
            "base_url": "https://erp.example.com/api/resource",
            "authorization": "token abc:def",
            "push_mode": "standard_purchase",
            "supplier": "",
            "item_group": "Products",
            "stock_uom": "Nos",
            "timeout": 30,
            "target_doctype": "",
            "method": "POST",
            "field_map": {},
            "payload_field": "payload_json",
        },
    )

    result = erp_client.validate_payload_for_push({"supplier": "HUAFON", "items": [{"material_code": "A001"}]})

    assert result["ok"] is True
    assert result["config_ready"] is True
    assert result["blocking_reasons"] == []


def test_normalize_currency_accepts_historical_chinese_labels() -> None:
    assert erp_client._normalize_currency("人民币RMB") == "CNY"
    assert erp_client._normalize_currency("美元 USD") == "USD"
    assert erp_client._normalize_currency("墨西哥比索MXN") == "MXN"


def test_method_url_replaces_the_resource_prefix() -> None:
    assert erp_client._build_method_url(
        {"base_url": "https://erp.example.com/api/resource"}, "frappe.client.submit"
    ) == "https://erp.example.com/api/method/frappe.client.submit"


def test_purchase_order_item_carries_the_route_warehouse() -> None:
    row = erp_client._build_purchase_order_item(
        {"material_code": "M1"},
        {"warehouse": "仓库 - 拉丁购"},
        {"stock_uom": "Nos"},
        "2026-09-24",
    )

    assert row["warehouse"] == "仓库 - 拉丁购"


def test_submit_is_skipped_when_the_purchase_order_is_already_submitted(monkeypatch) -> None:
    """已提交的采购单不再提交，避免重试时重复提交。"""

    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.get_method(), request.full_url))
        return _JsonResponse({"data": {"name": "PO-9", "docstatus": 1}})

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client._submit_purchase_order(
        "PO-9",
        {"base_url": "https://erp.example.com/api/resource", "authorization": "token abc:def", "timeout": 5},
    )

    assert result["ok"] is True
    assert result["already_submitted"] is True
    assert requests == [("GET", "https://erp.example.com/api/resource/Purchase%20Order/PO-9")]


def test_submit_failure_keeps_the_created_purchase_order_retryable(monkeypatch) -> None:
    """提交失败必须如实返回失败，让账本把该组记为可重试，而不是留下无法察觉的草稿。"""

    def fake_urlopen(request, timeout):
        if request.get_method() == "GET":
            return _JsonResponse({"data": {"name": "PO-9", "docstatus": 0}})
        raise HTTPError(request.full_url, 403, "Forbidden", None, io.BytesIO(b'{"exc":"no submit permission"}'))

    monkeypatch.setattr(erp_client, "urlopen", fake_urlopen)

    result = erp_client._submit_purchase_order(
        "PO-9",
        {"base_url": "https://erp.example.com/api/resource", "authorization": "token abc:def", "timeout": 5},
    )

    assert result["ok"] is False
    assert result["http_status"] == 403
    assert "已创建，但提交失败" in result["message"]


def test_created_purchase_order_is_submitted_through_the_method_endpoint(monkeypatch) -> None:
    """创建成功后必须提交，且提交走 /api/method 而不是资源端点。"""

    monkeypatch.setattr(erp_client, "lookup_purchase_by_business_key", lambda payload, config: {"found": False, "name": ""})
    monkeypatch.setattr(erp_client, "_ensure_item", lambda item, payload, config: {"ok": True})
    monkeypatch.setattr(
        erp_client,
        "_read_remote_document",
        lambda config, doctype, docname: {"name": docname, "docstatus": 0},
    )
    calls = []

    def fake_request_json(config, *, method, url, body=None):
        calls.append((method, url, body))
        if url.endswith("/Purchase%20Order"):
            return {"data": {"name": "PO-NEW"}}
        return {"message": "submitted"}

    monkeypatch.setattr(erp_client, "_request_json", fake_request_json)
    config = {
        "enabled": True,
        "base_url": "https://erp.example.com/api/resource",
        "authorization": "token abc:def",
        "push_mode": "standard_purchase",
        "supplier": "SUP",
        "item_group": "Products",
        "stock_uom": "Nos",
        "timeout": 30,
    }

    result = erp_client.push_overseas_cost_payload_with_config(
        {
            "batch_no": "B1",
            "subsidiary_code": "Company A",
            "warehouse": "仓库 - 拉丁购",
            "business_key": "PURCHASE:B1:Company A:SUP:CNY:Nos",
            "items": [{"material_code": "M1"}],
        },
        config,
    )

    assert result["ok"] is True
    assert result["status"] == "SUBMITTED"
    assert result["erp_target_doc"] == "PO-NEW"
    assert result["submit"]["docstatus"] == 1
    assert [url for _method, url, _body in calls] == [
        "https://erp.example.com/api/resource/Purchase%20Order",
        "https://erp.example.com/api/method/frappe.client.submit",
    ]
    assert calls[0][2]["items"][0]["warehouse"] == "仓库 - 拉丁购"
    assert calls[1][2] == {"doc": {"doctype": "Purchase Order", "name": "PO-NEW"}}
