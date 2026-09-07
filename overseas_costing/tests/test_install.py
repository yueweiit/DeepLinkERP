"""Installation field specification tests."""

from overseas_costing.install import build_erpnext_standard_field_spec


def test_erpnext_custom_fields_include_stable_business_links() -> None:
    fields = build_erpnext_standard_field_spec()

    assert "custom_overseas_business_key" in {row["fieldname"] for row in fields["Purchase Order"]}
    assert "custom_overseas_cost_result_hash" in {row["fieldname"] for row in fields["Purchase Order"]}
    assert "custom_overseas_amount_status" in {row["fieldname"] for row in fields["Purchase Order"]}
    assert "custom_overseas_stable_line_key" in {
        row["fieldname"] for row in fields["Purchase Order Item"]
    }
