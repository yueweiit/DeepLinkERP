from __future__ import annotations

from overseas_costing.services import erp_client


def test_get_erp_push_config_prefers_single_settings(monkeypatch) -> None:
    class FakeSettings:
        def get(self, fieldname, default=None):
            return {
                "enabled": 1,
                "base_url": "https://erp.example.com/api/resource",
                "authorization": "token abc:def",
                "target_doctype": "Overseas Cost Push",
                "http_method": "post",
                "timeout": 30,
                "payload_field": "payload_json",
                "field_map_json": "{\"name\": \"batch_name\"}",
            }.get(fieldname, default)

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
    assert config["method"] == "POST"
    assert config["timeout"] == 30
    assert config["field_map"] == {"name": "batch_name"}
    assert config["payload_field"] == "payload_json"
