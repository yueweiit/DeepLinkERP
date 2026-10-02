from __future__ import annotations

from types import SimpleNamespace

import pytest

from overseas_costing.services import company_inventory_transfer_service as service


def _warehouse(name: str, *, parent: str | None = None, is_group: int = 0) -> dict:
    return {
        "name": name,
        "warehouse_name": name.removesuffix(" - YC"),
        "parent_warehouse": parent,
        "is_group": is_group,
        "disabled": 0,
        "warehouse_type": None,
        "lft": 1,
    }


def _balance(
    item_code: str = "FL000001",
    warehouse: str = "AI-1-A01 ALMACEN IML - YC",
    qty: float = 12,
    valuation_rate: float = 0,
    *,
    has_serial_no: int = 0,
    has_batch_no: int = 0,
) -> dict:
    return {
        "item_code": item_code,
        "warehouse": warehouse,
        "actual_qty": qty,
        "valuation_rate": valuation_rate,
        "stock_value": qty * valuation_rate,
        "stock_uom": "个：pieza",
        "has_serial_no": has_serial_no,
        "has_batch_no": has_batch_no,
    }


def test_target_warehouse_name_changes_only_the_approved_company_suffix() -> None:
    assert service.target_warehouse_name("墨西哥仓库 - YC") == "墨西哥仓库 - YWFM"
    assert (
        service.target_warehouse_name("AI-1-A01 ALMACEN IML - YC")
        == "AI-1-A01 ALMACEN IML - YWFM"
    )

    with pytest.raises(service.CompanyInventoryTransferError, match="suffix"):
        service.target_warehouse_name("Unrelated Warehouse")


def test_build_transfer_snapshot_preserves_tree_qty_value_and_precision() -> None:
    warehouses = [
        _warehouse("墨西哥仓库 - YC", is_group=1),
        _warehouse(
            "ALMACEN IML - YC",
            parent="墨西哥仓库 - YC",
            is_group=1,
        ),
        _warehouse(
            "AI-1-A01 ALMACEN IML - YC",
            parent="ALMACEN IML - YC",
        ),
    ]
    balances = [
        _balance(qty=12.3456),
        _balance(
            item_code="FL000901",
            warehouse="AI-1-A01 ALMACEN IML - YC",
            qty=10,
            valuation_rate=110,
        ),
    ]

    snapshot = service.build_transfer_snapshot(
        warehouses=warehouses,
        balances=balances,
        existing_warehouse_names={"All Warehouses - YWFM"},
    )

    assert snapshot["ok"] is True
    assert snapshot["warehouse_count"] == 3
    assert snapshot["balance_count"] == 2
    assert snapshot["total_qty"] == pytest.approx(22.3456)
    assert snapshot["total_stock_value"] == pytest.approx(1100)
    assert snapshot["warehouses"][1]["target_parent_warehouse"] == "墨西哥仓库 - YWFM"
    assert snapshot["balances"][0]["target_warehouse"].endswith(" - YWFM")
    assert len(snapshot["snapshot_hash"]) == 64


@pytest.mark.parametrize(
    ("balance", "message"),
    [
        (_balance(qty=-1), "negative"),
        (_balance(has_serial_no=1), "serial"),
        (_balance(has_batch_no=1), "batch"),
    ],
)
def test_build_transfer_snapshot_blocks_unsafe_stock(balance: dict, message: str) -> None:
    warehouses = [
        _warehouse("墨西哥仓库 - YC", is_group=1),
        _warehouse("AI-1-A01 ALMACEN IML - YC", parent="墨西哥仓库 - YC"),
    ]

    with pytest.raises(service.CompanyInventoryTransferError, match=message):
        service.build_transfer_snapshot(
            warehouses=warehouses,
            balances=[balance],
            existing_warehouse_names=set(),
        )


def test_build_transfer_snapshot_blocks_target_name_collisions() -> None:
    warehouses = [_warehouse("墨西哥仓库 - YC", is_group=1)]

    with pytest.raises(service.CompanyInventoryTransferError, match="already exists"):
        service.build_transfer_snapshot(
            warehouses=warehouses,
            balances=[],
            existing_warehouse_names={"墨西哥仓库 - YWFM"},
        )


def test_reconciliation_batches_are_deterministic_and_paired() -> None:
    rows = [_balance(item_code=f"FL{i:06d}") for i in range(5)]
    rows = [
        {
            **row,
            "target_warehouse": service.target_warehouse_name(row["warehouse"]),
        }
        for row in rows
    ]

    batches = service.build_reconciliation_batches(rows, chunk_size=2)

    assert [batch["index"] for batch in batches] == [1, 2, 3]
    assert [len(batch["rows"]) for batch in batches] == [2, 2, 1]
    assert batches[0]["target_name"] == "MAT-RECO-YWC-YMX-20261002-T-001"
    assert batches[0]["source_name"] == "MAT-RECO-YWC-YMX-20261002-S-001"


def test_reconciliation_batch_size_must_be_bounded() -> None:
    with pytest.raises(service.CompanyInventoryTransferError, match="chunk_size"):
        service.build_reconciliation_batches([], chunk_size=0)
    with pytest.raises(service.CompanyInventoryTransferError, match="chunk_size"):
        service.build_reconciliation_batches([], chunk_size=101)


def test_default_batches_stay_within_erpnext_synchronous_submission_limit() -> None:
    rows = [_balance(item_code=f"FL{i:06d}") for i in range(201)]

    batches = service.build_reconciliation_batches(rows)

    assert [len(batch["rows"]) for batch in batches] == [100, 100, 1]


def test_submit_pair_refuses_queued_drafts_and_rolls_back(monkeypatch) -> None:
    events = []
    docs = {
        name: SimpleNamespace(docstatus=0, submit=lambda name=name: events.append(name))
        for name in ("target", "source")
    }
    monkeypatch.setattr(service, "frappe", SimpleNamespace(
        get_doc=lambda _doctype, name: docs[name],
        db=SimpleNamespace(commit=lambda: events.append("commit"), rollback=lambda: events.append("rollback")),
    ))

    with pytest.raises(service.CompanyInventoryTransferError, match="not submitted"):
        service._submit_reconciliation_pair({"target_name": "target", "source_name": "source", "rows": []})

    assert "commit" not in events
    assert events[-1] == "rollback"


def test_submit_pair_commits_only_after_both_documents_are_submitted(monkeypatch) -> None:
    events = []

    class FakeDocument:
        docstatus = 0
        def __init__(self, name):
            self.name = name
        def submit(self):
            events.append(self.name)
            self.docstatus = 1

    docs = {name: FakeDocument(name) for name in ("target", "source")}
    monkeypatch.setattr(service, "frappe", SimpleNamespace(
        get_doc=lambda _doctype, name: docs[name],
        db=SimpleNamespace(commit=lambda: events.append("commit"), rollback=lambda: events.append("rollback")),
    ))

    service._submit_reconciliation_pair({"target_name": "target", "source_name": "source", "rows": []})

    assert events == ["target", "source", "commit"]


def test_create_target_tree_uses_unsuffixed_warehouse_title_even_when_source_title_contains_suffix(
    monkeypatch,
) -> None:
    created = []

    class FakeWarehouse:
        def __init__(self, values: dict):
            created.append(values)
            self.name = f"{values['warehouse_name']} - YWFM"

        def insert(self, *, ignore_permissions: bool) -> None:
            assert ignore_permissions is True

    monkeypatch.setattr(
        service,
        "frappe",
        SimpleNamespace(
            db=SimpleNamespace(exists=lambda *_args, **_kwargs: False),
            get_doc=lambda values: FakeWarehouse(values),
        ),
    )

    service._create_target_warehouse_tree(
        [
            {
                "source_name": "P17R25S INVENTARIO SEMITERMINADO - YC",
                "target_name": "P17R25S INVENTARIO SEMITERMINADO - YWFM",
                "warehouse_name": "P17R25S INVENTARIO SEMITERMINADO - YC",
                "target_parent_warehouse": "墨西哥仓库 - YWFM",
                "is_group": 0,
                "warehouse_type": None,
            }
        ]
    )

    assert created[0]["warehouse_name"] == "P17R25S INVENTARIO SEMITERMINADO"
