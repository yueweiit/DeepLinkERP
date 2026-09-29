from pathlib import Path
from types import SimpleNamespace

from overseas_costing.overseas_costing.report.inventory_on_hand import inventory_on_hand


def test_columns_match_the_approved_business_view() -> None:
    assert [column["fieldname"] for column in inventory_on_hand.get_columns()] == [
        "item_code",
        "item_name",
        "warehouse",
        "original_location",
        "item_group",
        "actual_qty",
        "stock_uom",
        "dpci",
        "external_code",
        "original_identifier_alias",
    ]


def test_quantity_precision_uses_zero_for_whole_count_units_and_two_for_continuous_units() -> None:
    assert inventory_on_hand.get_quantity_display(3300, "包：paquete") == (0, "")
    assert inventory_on_hand.get_quantity_display(55, "个：pieza") == (0, "")
    assert inventory_on_hand.get_quantity_display(19.6, "kg") == (2, "")
    assert inventory_on_hand.get_quantity_display(1.5, "个：pieza") == (
        2,
        "计数单位存在小数库存",
    )


def test_js_formatter_uses_integer_fieldtype_for_zero_decimal_count_units() -> None:
    source = Path(
        inventory_on_hand.__file__.replace(".py", ".js")
    ).read_text(encoding="utf-8")

    assert 'fieldtype: "Int"' in source
    assert 'precision: 2' in source


def test_get_data_uses_actual_nonzero_bin_balances_and_bound_filters(monkeypatch) -> None:
    class FakeDB:
        def __init__(self) -> None:
            self.query = ""
            self.params = {}

        def sql(self, query, params, as_dict):
            self.query = query
            self.params = params
            assert as_dict is True
            return [
                {
                    "item_code": "FL007979",
                    "item_name": "蓝色色母粒 / MASTERBATCH AZUL",
                    "warehouse": "综合仓库 - YWFM",
                    "original_location": "AI-4-C01",
                    "item_group": "FL Suministros Auxiliares辅料",
                    "actual_qty": 19.6,
                    "stock_uom": "kg",
                    "dpci": "",
                    "external_code": "FL000164",
                    "original_identifier_alias": "FL000164",
                }
            ]

    fake_db = FakeDB()
    monkeypatch.setattr(inventory_on_hand, "frappe", SimpleNamespace(db=fake_db))

    rows = inventory_on_hand.get_data(
        {
            "company": "YW Fabricación MX 核心制造",
            "warehouse": "综合仓库 - YWFM",
            "original_location": "AI-4",
            "item_code": "FL007979",
            "item_group": "FL Suministros Auxiliares辅料",
        }
    )

    compact_query = " ".join(fake_db.query.split())
    assert "FROM `tabBin` bin" in compact_query
    assert "INNER JOIN `tabItem` item" in compact_query
    assert "INNER JOIN `tabWarehouse` warehouse" in compact_query
    assert "bin.actual_qty != 0" in compact_query
    assert "bin.actual_qty AS actual_qty" in compact_query
    assert "bin.projected_qty" not in compact_query
    assert "item.disabled" not in compact_query
    assert "item.is_stock_item" not in compact_query
    assert fake_db.params == {
        "company": "YW Fabricación MX 核心制造",
        "warehouse": "综合仓库 - YWFM",
        "original_location": "%AI-4%",
        "item_code": "FL007979",
        "item_group": "FL Suministros Auxiliares辅料",
    }
    assert rows[0]["quantity_precision"] == 2
    assert rows[0]["quantity_warning"] == ""


def test_execute_returns_rows_with_hidden_display_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        inventory_on_hand,
        "frappe",
        SimpleNamespace(_dict=lambda value: value),
    )
    monkeypatch.setattr(
        inventory_on_hand,
        "get_data",
        lambda filters: [
            {
                "actual_qty": 7,
                "stock_uom": "卷：rollo",
                "quantity_precision": 0,
                "quantity_warning": "",
            }
        ],
    )

    columns, rows = inventory_on_hand.execute({"company": "YWFM"})

    assert len(columns) == 10
    assert rows == [
        {
            "actual_qty": 7,
            "stock_uom": "卷：rollo",
            "quantity_precision": 0,
            "quantity_warning": "",
        }
    ]
