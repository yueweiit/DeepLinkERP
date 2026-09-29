from copy import deepcopy

from overseas_costing.services.inventory_trace_service import apply_inventory_trace


class FakeInventoryTraceRepository:
    def __init__(self, *, bins=None, items=None) -> None:
        self.bins = deepcopy(bins or {})
        self.items = deepcopy(items or {})
        self.bin_writes = []
        self.item_writes = []

    def get_bin(self, item_code: str, warehouse: str):
        return self.bins.get((item_code, warehouse))

    def get_item_alias(self, item_code: str):
        if item_code not in self.items:
            return None
        return self.items[item_code]

    def set_bin_location(self, bin_name: str, value: str) -> None:
        self.bin_writes.append((bin_name, value))
        for row in self.bins.values():
            if row["name"] == bin_name:
                row["custom_original_location"] = value

    def set_item_alias(self, item_code: str, value: str) -> None:
        self.item_writes.append((item_code, value))
        self.items[item_code] = value


def make_repository(location="", alias="") -> FakeInventoryTraceRepository:
    return FakeInventoryTraceRepository(
        bins={
            ("FL007979", "综合仓库 - YWFM"): {
                "name": "BIN-FL007979",
                "actual_qty": 19.6,
                "custom_original_location": location,
            }
        },
        items={"FL007979": alias},
    )


def trace_rows():
    return [
        {
            "item_code": " FL007979 ",
            "warehouse": "综合仓库 - YWFM",
            "original_location": " AI-4-C01 ",
            "original_identifier_alias": " FL000164 ",
        }
    ]


def test_dry_run_reports_pending_writes_without_mutating_repository() -> None:
    repository = make_repository()

    result = apply_inventory_trace(trace_rows(), dry_run=True, repository=repository)

    assert result["pending_bin_updates"] == 1
    assert result["pending_item_updates"] == 1
    assert result["updated_bins"] == 0
    assert result["updated_items"] == 0
    assert result["conflicts"] == []
    assert result["missing"] == []
    assert repository.bin_writes == []
    assert repository.item_writes == []


def test_apply_writes_trace_fields_and_second_apply_is_idempotent() -> None:
    repository = make_repository()

    first = apply_inventory_trace(trace_rows(), dry_run=False, repository=repository)
    second = apply_inventory_trace(trace_rows(), dry_run=False, repository=repository)

    assert first["applied"] is True
    assert first["updated_bins"] == 1
    assert first["updated_items"] == 1
    assert repository.bin_writes == [("BIN-FL007979", "AI-4-C01")]
    assert repository.item_writes == [("FL007979", "FL000164")]
    assert second["pending_bin_updates"] == 0
    assert second["pending_item_updates"] == 0
    assert second["updated_bins"] == 0
    assert second["updated_items"] == 0
    assert second["unchanged_rows"] == 1


def test_conflicting_existing_values_are_never_overwritten() -> None:
    repository = make_repository(location="AI-OLD", alias="OTHER-CODE")

    result = apply_inventory_trace(trace_rows(), dry_run=False, repository=repository)

    assert result["applied"] is False
    assert len(result["conflicts"]) == 2
    assert repository.bin_writes == []
    assert repository.item_writes == []


def test_missing_item_or_bin_prevents_partial_batch_writes() -> None:
    repository = FakeInventoryTraceRepository(
        bins={
            ("FL007979", "综合仓库 - YWFM"): {
                "name": "BIN-FL007979",
                "actual_qty": 19.6,
                "custom_original_location": "",
            }
        },
        items={},
    )

    result = apply_inventory_trace(trace_rows(), dry_run=False, repository=repository)

    assert result["applied"] is False
    assert result["missing"] == [
        {"item_code": "FL007979", "target": "Item"}
    ]
    assert repository.bin_writes == []
    assert repository.item_writes == []


def test_corrected_black_masterbatch_code_targets_final_item_and_bin() -> None:
    repository = FakeInventoryTraceRepository(
        bins={
            ("YL001974", "IML 仓库 - YWFM"): {
                "name": "BIN-YL001974",
                "actual_qty": 7.51,
                "custom_original_location": "",
            }
        },
        items={"YL001974": ""},
    )
    rows = [
        {
            "item_code": "YL001974",
            "warehouse": "IML 仓库 - YWFM",
            "original_location": "AI-4-C01",
            "original_identifier_alias": "YL000115",
        }
    ]

    result = apply_inventory_trace(rows, dry_run=False, repository=repository)

    assert result["applied"] is True
    assert repository.bin_writes == [("BIN-YL001974", "AI-4-C01")]
    assert repository.item_writes == [("YL001974", "YL000115")]


def test_zero_balance_bin_is_not_backfilled() -> None:
    repository = make_repository()
    repository.bins[("FL007979", "综合仓库 - YWFM")]["actual_qty"] = 0

    result = apply_inventory_trace(trace_rows(), dry_run=False, repository=repository)

    assert result["applied"] is False
    assert result["conflicts"] == [
        {
            "item_code": "FL007979",
            "warehouse": "综合仓库 - YWFM",
            "field": "actual_qty",
            "existing": 0,
            "requested": "nonzero balance",
        }
    ]
    assert repository.bin_writes == []
    assert repository.item_writes == []
