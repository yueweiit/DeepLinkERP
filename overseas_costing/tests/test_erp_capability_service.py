from overseas_costing.services.erp_capability_service import (
    build_erpnext_standard_field_spec,
    build_safe_site_summary,
    evaluate_erpnext_metadata,
    verify_erpnext_site,
)


def test_site_config_is_explicit_and_secret_is_redacted() -> None:
    result = build_safe_site_summary(
        {"site_code": "S1", "label": "生产ERP", "authorization": "token secret", "base_url": "https://erp.example.com"}
    )

    assert result["site_code"] == "S1"
    assert "authorization" not in result
    assert "secret" not in str(result)
    assert "base_url" not in result


def test_erpnext_custom_fields_include_stable_business_links() -> None:
    fields = build_erpnext_standard_field_spec()

    assert "custom_overseas_business_key" in {row["fieldname"] for row in fields["Purchase Order"]}
    assert "custom_overseas_stable_line_key" in {row["fieldname"] for row in fields["Purchase Order Item"]}


def test_metadata_check_reports_only_missing_contract_fields() -> None:
    fields = build_erpnext_standard_field_spec()
    metadata = {
        doctype: {"fields": [{"fieldname": row["fieldname"]} for row in rows]}
        for doctype, rows in fields.items()
    }

    assert evaluate_erpnext_metadata(metadata)["ok"] is True

    metadata["Purchase Order"]["fields"].pop()
    result = evaluate_erpnext_metadata(metadata)
    assert result["ok"] is False
    assert result["capability_status"] == "FAILED"


def test_verify_site_returns_verified_when_reader_returns_full_metadata() -> None:
    fields = build_erpnext_standard_field_spec()
    metadata = {
        doctype: {"fields": [{"fieldname": row["fieldname"]} for row in rows]}
        for doctype, rows in fields.items()
    }

    result = verify_erpnext_site(
        {"site_code": "MX"},
        metadata_reader=lambda config, doctypes: {
            "ok": True,
            "metadata": metadata,
            "errors": {},
            "request": {"site_code": config["site_code"]},
        },
    )

    assert result["ok"] is True
    assert result["capability_status"] == "VERIFIED"
    assert result["metadata_read"]["request"]["site_code"] == "MX"


def test_verify_site_keeps_read_failure_without_evaluating_metadata() -> None:
    result = verify_erpnext_site(
        {"site_code": "MX"},
        metadata_reader=lambda config, doctypes: {
            "ok": False,
            "metadata": {},
            "errors": {"config": ["缺少鉴权"]},
            "message": "ERP 元数据读取配置未完成：缺少鉴权",
        },
    )

    assert result["ok"] is False
    assert result["capability_status"] == "FAILED"
    assert result["missing_fields"] == {}
    assert result["metadata_read"]["errors"] == {"config": ["缺少鉴权"]}


def test_verify_site_reports_missing_fields_from_successful_read() -> None:
    result = verify_erpnext_site(
        {"site_code": "MX"},
        metadata_reader=lambda config, doctypes: {
            "ok": True,
            "metadata": {"Purchase Order": {"fields": []}, "Purchase Order Item": {"fields": []}},
            "errors": {},
        },
    )

    assert result["ok"] is False
    assert result["capability_status"] == "FAILED"
    assert "Purchase Order" in result["missing_fields"]
