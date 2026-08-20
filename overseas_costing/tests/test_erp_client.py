from __future__ import annotations

import json

from overseas_costing.services import erp_client


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
