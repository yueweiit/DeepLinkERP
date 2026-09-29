from copy import deepcopy
from pathlib import Path

from overseas_costing.services.inventory_trace_service import apply_inventory_trace


class FakeRepository:
    def __init__(self, bins, items):
        self.bins = deepcopy(bins)
        self.items = deepcopy(items)
        self.locked = False
        self.bin_writes = []
        self.item_writes = []

    def lock_targets(self, rows):
        assert rows
        self.locked = True

    def get_bin(self, item_code, warehouse):
        return self.bins.get((item_code, warehouse))

    def get_item_alias(self, item_code):
        return self.items.get(item_code)

    def set_bin_location(self, name, value):
        assert self.locked
        self.bin_writes.append((name, value))
        for row in self.bins.values():
            if row["name"] == name:
                row["custom_original_location"] = value

    def set_item_alias(self, item_code, value):
        assert self.locked
        self.item_writes.append((item_code, value))
        self.items[item_code] = value


def make_repository(location="", alias=""):
    return FakeRepository(
        {
            ("FL007979", "综合仓库 - YWFM"): {
                "name": "BIN-A",
                "actual_qty": 19.6,
                "custom_original_location": location,
            }
        },
        {"FL007979": alias},
    )


def rows():
    return [
        {
            "item_code": "FL007979",
            "warehouse": "综合仓库 - YWFM",
            "original_location": "AI-4-C01",
            "original_identifier_alias": "FL000164",
        }
    ]


def test_dry_run_does_not_write_and_apply_is_locked_and_idempotent():
    repository = make_repository()
    dry_run = apply_inventory_trace(rows(), repository=repository)
    first = apply_inventory_trace(rows(), dry_run=False, repository=repository)
    second = apply_inventory_trace(rows(), dry_run=False, repository=repository)

    assert dry_run["pending_bin_updates"] == 1
    assert dry_run["pending_item_updates"] == 1
    assert first["updated_bins"] == 1
    assert first["updated_items"] == 1
    assert repository.bin_writes == [("BIN-A", "AI-4-C01")]
    assert repository.item_writes == [("FL007979", "FL000164")]
    assert second["conflicts"] == []
    assert second["unchanged_rows"] == 1


def test_existing_different_values_stop_the_entire_batch():
    repository = make_repository(location="OTHER", alias="OTHER")

    result = apply_inventory_trace(rows(), dry_run=False, repository=repository)

    assert result["applied"] is False
    assert len(result["conflicts"]) == 2
    assert repository.bin_writes == []
    assert repository.item_writes == []


def test_aliases_are_unioned_across_warehouses_before_write():
    repository = FakeRepository(
        {
            ("FL100001", "综合仓库 - YWFM"): {
                "name": "BIN-A",
                "actual_qty": 3,
                "custom_original_location": "",
            },
            ("FL100001", "OEM 仓库 - YWFM"): {
                "name": "BIN-B",
                "actual_qty": 5,
                "custom_original_location": "",
            },
        },
        {"FL100001": ""},
    )
    source_rows = [
        {
            "item_code": "FL100001",
            "warehouse": "综合仓库 - YWFM",
            "original_location": "A-01",
            "original_identifier_alias": "OLD-A",
        },
        {
            "item_code": "FL100001",
            "warehouse": "OEM 仓库 - YWFM",
            "original_location": "A-02",
            "original_identifier_alias": "OLD-B / OLD-A",
        },
    ]

    first = apply_inventory_trace(
        source_rows, dry_run=False, repository=repository
    )
    second = apply_inventory_trace(
        source_rows, dry_run=False, repository=repository
    )

    assert first["applied"] is True
    assert repository.item_writes == [("FL100001", "OLD-A / OLD-B")]
    assert second["conflicts"] == []
    assert second["unchanged_rows"] == 2


def test_mutating_api_is_post_only():
    source = (Path(__file__).parents[1] / "api" / "inventory_trace.py").read_text()
    assert '@frappe.whitelist(methods=["POST"])' in source
