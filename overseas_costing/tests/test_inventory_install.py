from types import SimpleNamespace

from overseas_costing import install


def test_inventory_trace_fields_extend_existing_custom_field_map() -> None:
    fields = install.get_inventory_trace_custom_fields()

    assert fields == {
        "Item": [
            {
                "fieldname": "custom_original_identifier_alias",
                "label": "原始标识/别名",
                "fieldtype": "Small Text",
                "insert_after": "custom_external_code",
            }
        ],
        "Bin": [
            {
                "fieldname": "custom_original_location",
                "label": "原始库位",
                "fieldtype": "Data",
                "insert_after": "warehouse",
                "read_only": 1,
            }
        ],
    }


def test_update_stock_workspace_link_reuses_current_available_quantity_link() -> None:
    row = SimpleNamespace(
        label="可用数量",
        link_to="Stock Projected Qty",
        link_type="Report",
        report_ref_doctype="Item",
    )
    workspace = SimpleNamespace(
        get=lambda fieldname: [row] if fieldname == "links" else []
    )

    assert install._update_stock_workspace_inventory_link(workspace) is True
    assert row.link_to == "Inventory On Hand"
    assert row.link_type == "Report"
    assert row.report_ref_doctype == "Item"


def test_update_stock_workspace_link_is_idempotent() -> None:
    row = SimpleNamespace(
        label="可用数量",
        link_to="Inventory On Hand",
        link_type="Report",
        report_ref_doctype="Item",
    )
    workspace = SimpleNamespace(
        get=lambda fieldname: [row] if fieldname == "links" else []
    )

    assert install._update_stock_workspace_inventory_link(workspace) is False


def test_update_stock_workspace_link_does_not_replace_unrelated_links() -> None:
    row = SimpleNamespace(
        label="其他报表",
        link_to="Stock Projected Qty",
        link_type="Report",
        report_ref_doctype="Item",
    )
    workspace = SimpleNamespace(
        get=lambda fieldname: [row] if fieldname == "links" else []
    )

    assert install._update_stock_workspace_inventory_link(workspace) is False
    assert row.link_to == "Stock Projected Qty"
