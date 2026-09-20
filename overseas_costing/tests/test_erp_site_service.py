import json

from overseas_costing.services import erp_site_service as sites


class _FakeDoc:
    def __init__(self):
        self.values = {
            "site_code": "MX-TEST",
            "label": "墨西哥测试 ERP",
            "base_url": "https://erp.example.com/api/resource",
            "push_mode": "standard_purchase",
            "company": "MX Company",
            "default_supplier": "Default Supplier",
            "cost_center": "Main - MX",
            "default_currency": "CNY",
            "stock_uom": "Nos",
        }
        self.writes = []

    def get(self, fieldname):
        return self.values.get(fieldname)

    @staticmethod
    def get_password(fieldname, raise_exception=False):
        assert fieldname == "authorization"
        return "token hidden-secret"

    def db_set(self, fieldname, value, update_modified=False):
        self.writes.append((fieldname, value, update_modified))


class _FakeFrappe:
    def __init__(self, doc):
        self.doc = doc
        self.only_for_calls = []
        self.utils = type("Utils", (), {"now_datetime": staticmethod(lambda: "2026-09-16 09:00:00")})

    def only_for(self, role):
        self.only_for_calls.append(role)

    def get_doc(self, doctype, site_code):
        assert doctype == "Overseas Cost ERP Site"
        assert site_code == "MX-TEST"
        return self.doc


def test_verify_site_records_only_safe_summary(monkeypatch) -> None:
    doc = _FakeDoc()
    fake = _FakeFrappe(doc)
    monkeypatch.setattr(sites, "frappe", fake)

    result = sites.verify_and_record_site_capability(
        "MX-TEST",
        metadata_reader=lambda config, doctypes: {
            "ok": False,
            "metadata": {},
            "errors": {"Purchase Order": {"http_status": 403, "message": "forbidden", "response": {"token": "hidden-secret"}}},
            "request": {"authorization_configured": True},
            "message": "ERP 元数据读取失败。",
        },
    )

    summary_text = next(value for field, value, _ in doc.writes if field == "capability_summary_json")
    assert fake.only_for_calls == ["System Manager"]
    assert result["capability_status"] == "FAILED"
    assert result["errors"]["Purchase Order"] == {"http_status": 403, "message": "forbidden"}
    assert "hidden-secret" not in summary_text
    assert json.loads(summary_text)["request"] == {"authorization_configured": True}


def test_get_site_push_config_is_server_side_and_includes_password(monkeypatch) -> None:
    doc = _FakeDoc()
    monkeypatch.setattr(sites, "frappe", _FakeFrappe(doc))

    config = sites.get_site_push_config("MX-TEST")

    assert config["authorization"] == "token hidden-secret"
    assert config["supplier"] == "Default Supplier"
