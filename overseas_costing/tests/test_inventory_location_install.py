"""库存库位页面 DocType、追溯字段和库存侧边栏安装测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from overseas_costing import install


ROOT = Path(__file__).resolve().parents[1]


class FakeSidebar:
    def __init__(self) -> None:
        self.items = [
            SimpleNamespace(
                label="可用数量",
                link_type="Report",
                link_to="Stock Projected Qty",
                icon="package",
                idx=1,
            ),
            SimpleNamespace(
                label="储位",
                link_type="DocType",
                link_to="Bin",
                icon="warehouse",
                idx=2,
            ),
        ]

    def get(self, fieldname: str):
        assert fieldname == "items"
        return self.items

    def append(self, fieldname: str, values: dict):
        assert fieldname == "items"
        row = SimpleNamespace(**values)
        self.items.append(row)
        return row


def test_stock_sidebar_adds_independent_page_after_available_quantity_without_replacing_it() -> None:
    sidebar = FakeSidebar()

    assert install._upsert_stock_sidebar_inventory_location(sidebar) is True
    assert [(row.label, row.link_type, row.link_to, row.idx) for row in sidebar.items] == [
        ("可用数量", "Report", "Stock Projected Qty", 1),
        ("物料库存明细", "Page", "inventory-location-detail", 2),
        ("半成品库存明细", "Page", "semi-finished-inventory-detail", 3),
        ("成品库存明细", "Page", "finished-goods-inventory-detail", 4),
        ("模具库存明细", "Page", "mold-inventory-detail", 5),
        ("储位", "DocType", "Bin", 6),
    ]
    assert install._upsert_stock_sidebar_inventory_location(sidebar) is False


def test_inventory_trace_fields_are_code_managed_on_item_only() -> None:
    fields = install.get_inventory_trace_custom_fields()

    assert set(fields) == {"Item"}
    assert {row["fieldname"] for row in fields["Item"]} == {
        "custom_dpci",
        "custom_external_code",
        "custom_original_identifier_alias",
    }


def test_inventory_location_snapshot_doctype_is_mirrored_and_importable() -> None:
    relative = Path(
        "doctype/inventory_original_location_snapshot/"
        "inventory_original_location_snapshot.json"
    )
    source = ROOT / relative
    mirror = ROOT / "overseas_costing" / relative

    assert source.read_bytes() == mirror.read_bytes()
    definition = json.loads(source.read_text(encoding="utf-8"))
    assert definition["name"] == "Inventory Original Location Snapshot"
    assert definition["track_changes"] == 1
    assert definition["allow_import"] == 1
    assert definition["autoname"] == "field:idempotency_key"
    fields = {row["fieldname"]: row for row in definition["fields"]}
    assert fields["idempotency_key"]["unique"] == 1
    assert not fields["idempotency_key"].get("read_only")
    assert not fields["source_filename"].get("read_only")
    assert not fields["source_file_hash"].get("read_only")
    assert fields["source_rows"]["fieldtype"] == "Small Text"
    assert fields["source_codes"]["fieldtype"] == "Small Text"
    assert fields["location_qty"]["fieldtype"] == "Float"

    permissions = {row["role"]: row for row in definition["permissions"]}
    assert permissions["System Manager"]["create"] == 1
    assert permissions["System Manager"]["import"] == 1
    assert permissions["Stock Manager"]["create"] == 1
    assert permissions["Stock Manager"]["import"] == 1
    assert permissions["Stock User"]["read"] == 1
    assert not permissions["Stock User"].get("write")


def test_legacy_inventory_report_is_removed_only_after_new_page_exists(monkeypatch) -> None:
    deleted: list[tuple] = []

    class FakeDB:
        @staticmethod
        def exists(doctype, name):
            return (doctype, name) in {
                ("Page", "inventory-location-detail"),
                ("Report", "Inventory On Hand"),
            }

        @staticmethod
        def commit():
            deleted.append(("commit",))

    fake_frappe = SimpleNamespace(
        db=FakeDB(),
        delete_doc=lambda *args, **kwargs: deleted.append((*args, kwargs)),
    )
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)

    assert install.retire_legacy_inventory_report() == {
        "ok": True,
        "removed": True,
        "report": "Inventory On Hand",
    }
    assert deleted[0][:2] == ("Report", "Inventory On Hand")
    assert deleted[-1] == ("commit",)
