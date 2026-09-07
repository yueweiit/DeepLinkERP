"""Safe per-site ERP capability checks."""

from overseas_costing.services.erp_capability_service import (
    build_safe_site_summary,
    verify_site_capabilities,
)


def test_site_config_is_explicit_and_secret_is_redacted() -> None:
    result = build_safe_site_summary(
        {"site_code": "S1", "base_url": "https://private", "authorization": "token secret"}
    )

    assert result["site_code"] == "S1"
    assert "authorization" not in result
    assert "base_url" not in result
    assert "secret" not in str(result)


def test_capability_verification_is_read_only_and_reports_missing_fields() -> None:
    calls = []

    def load_metadata(doctype, config):
        calls.append(("GET", doctype, config["site_code"]))
        fields = {
            "Purchase Order": ["custom_overseas_business_key", "custom_overseas_cost_result_hash"],
            "Purchase Order Item": ["custom_overseas_stable_line_key"],
        }
        return {"fields": [{"fieldname": value} for value in fields[doctype]]}

    result = verify_site_capabilities(
        {"site_code": "S1", "enabled": 1, "authorization": "token secret"},
        metadata_loader=load_metadata,
    )

    assert result["status"] == "FAILED"
    assert "Purchase Order.custom_overseas_amount_status" in result["missing_capabilities"]
    assert {method for method, _, _ in calls} == {"GET"}
    assert "secret" not in str(result)


def test_capability_verification_passes_when_every_stable_link_field_exists() -> None:
    def load_metadata(doctype, _config):
        fields = {
            "Purchase Order": [
                "custom_overseas_business_key",
                "custom_overseas_cost_result_hash",
                "custom_overseas_amount_status",
            ],
            "Purchase Order Item": ["custom_overseas_stable_line_key"],
        }
        return {"fields": [{"fieldname": value} for value in fields[doctype]]}

    result = verify_site_capabilities({"site_code": "S1", "enabled": 1}, metadata_loader=load_metadata)

    assert result["status"] == "VERIFIED"
    assert result["missing_capabilities"] == []
