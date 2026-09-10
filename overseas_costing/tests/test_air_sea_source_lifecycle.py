"""Comparison references survive workbench deletion and concurrent source removal."""
from types import SimpleNamespace

import pytest

from overseas_costing.services import access_control, air_sea_batch, calculate_service


class LifecycleDB:
    def __init__(self, *, referenced=False, installed=True, batch_exists=True):
        self.referenced = referenced
        self.installed = installed
        self.batch_exists = batch_exists
        self.reads = []
        self.deleted = []
        self.commits = 0

    def get_value(self, doctype, filters, fieldname, *, for_update=False):
        self.reads.append((doctype, filters, for_update))
        if doctype == "Overseas Cost Batch":
            return "BATCH" if self.batch_exists else None
        assert doctype == "Overseas Air Sea Comparison"
        assert self.installed
        # A reference committed while deletion waited for the batch lock is absent
        # from an older REPEATABLE READ snapshot, but visible to a current read.
        return "COMPARISON" if self.referenced and for_update else None

    def table_exists(self, doctype):
        assert doctype == "Overseas Air Sea Comparison"
        return self.installed

    def delete(self, doctype, filters):
        self.deleted.append((doctype, filters))

    def commit(self):
        self.commits += 1


def deletion_runtime(monkeypatch, **options):
    db = LifecycleDB(**options)
    runtime = SimpleNamespace(db=db, get_all=lambda *args, **kwargs: [])
    monkeypatch.setattr(calculate_service, "_frappe", runtime)
    monkeypatch.setattr(calculate_service, "_resolve_batch_name", lambda name: "BATCH")
    return db


def test_referenced_batch_is_not_deleted_even_when_reference_is_newer_than_snapshot(monkeypatch):
    db = deletion_runtime(monkeypatch, referenced=True)
    result = calculate_service.delete_batch("BATCH")
    assert result["ok"] is False
    assert "测算" in result["message"]
    assert db.deleted == [] and db.commits == 0
    assert db.reads == [
        ("Overseas Cost Batch", "BATCH", True),
        ("Overseas Air Sea Comparison", {"source_batch": "BATCH"}, True),
    ]


@pytest.mark.parametrize("installed", [True, False])
def test_unreferenced_batch_can_be_deleted_before_and_after_schema_migration(monkeypatch, installed):
    db = deletion_runtime(monkeypatch, installed=installed)
    result = calculate_service.delete_batch("BATCH")
    assert result["ok"] is True
    assert db.deleted == [("Overseas Cost Batch", {"name": "BATCH"})]
    assert db.commits == 1
    assert db.reads[0] == ("Overseas Cost Batch", "BATCH", True)


def test_batch_removed_while_waiting_for_lock_is_not_deleted_again(monkeypatch):
    db = deletion_runtime(monkeypatch, batch_exists=False)
    result = calculate_service.delete_batch("BATCH")
    assert result["ok"] is False
    assert db.deleted == [] and db.commits == 0


@pytest.mark.parametrize("exists", [True, False])
def test_source_save_checks_current_existence_under_batch_lock(monkeypatch, exists):
    db = LifecycleDB(batch_exists=exists)
    monkeypatch.setattr(air_sea_batch, "frappe", SimpleNamespace(db=db))
    monkeypatch.setattr(air_sea_batch, "_signature", lambda source: "signed")
    monkeypatch.setattr(access_control, "require_batch_permission", lambda *args: "BATCH")
    source = {"batch": "BATCH", "token": "signed"}
    if exists:
        assert air_sea_batch.validate_source(source, for_update=True) is source
    else:
        with pytest.raises(ValueError, match="删除|不存在"):
            air_sea_batch.validate_source(source, for_update=True)
    assert db.reads == [("Overseas Cost Batch", "BATCH", True)]


def test_reading_source_does_not_take_write_lock(monkeypatch):
    db = LifecycleDB()
    monkeypatch.setattr(air_sea_batch, "frappe", SimpleNamespace(db=db))
    monkeypatch.setattr(air_sea_batch, "_signature", lambda source: "signed")
    monkeypatch.setattr(access_control, "require_batch_permission", lambda *args: "BATCH")
    source = {"batch": "BATCH", "token": "signed"}
    assert air_sea_batch.validate_source(source) is source
    assert db.reads == []
