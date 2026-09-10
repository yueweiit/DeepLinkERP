"""Record validation, server calculation and concurrency rules."""
import copy
import json
from decimal import Decimal

import pytest

from overseas_costing.services import air_sea_records as records
from overseas_costing.tests.test_air_sea_calculation import sample


def test_saved_result_is_recalculated_instead_of_trusting_browser(monkeypatch):
    monkeypatch.setattr(records.air_sea_batch, "validate_source", lambda source, **kwargs: source)
    payload = sample()
    payload["result"] = {"airTotal": "1"}
    values = records.prepare_values("试算", payload)
    assert Decimal(json.loads(values["result_json"])["airTotal"]) == Decimal("92973.8233928448")
    assert "result" not in json.loads(values["payload_json"])
    assert values["formula_version"] == "air-sea-html-1"


def test_blank_title_rejected_and_incomplete_payload_can_be_saved(monkeypatch):
    monkeypatch.setattr(records.air_sea_batch, "validate_source", lambda source, **kwargs: source)
    with pytest.raises(ValueError):
        records.prepare_values(" ", sample())
    assert records.prepare_values("草稿", {"rows": []})["status"] == "Draft"


def test_conflict_rejects_stale_or_missing_modified():
    records.check_revision("2026-09-10 10:00:01.123456", "2026-09-10 10:00:01.123456")
    for stale in (None, "", "2026-09-10 10:00:01.123455"):
        with pytest.raises(ValueError, match="其他成员"):
            records.check_revision("2026-09-10 10:00:01.123456", stale)


def test_request_digest_detects_mutated_input():
    payload = sample()
    first = records.request_digest("记录", payload)
    changed = copy.deepcopy(payload)
    changed["rows"][0][20] = "50"
    assert records.request_digest("记录", changed) != first
    assert records.request_digest("记录", payload) == first


def test_source_must_be_validated_before_persistence(monkeypatch):
    def denied(_source, **kwargs):
        raise PermissionError("no batch read")
    monkeypatch.setattr(records.air_sea_batch, "validate_source", denied)
    payload = sample()
    payload["source"] = {"batch": "private"}
    with pytest.raises(PermissionError):
        records.prepare_values("来源", payload)


def test_request_ids_are_bounded_and_validate_uuid():
    records.validate_request_id("9d1dcdf5-610e-46b2-b33c-580b89cfa123")
    for value in ("", "bad", "a" * 200):
        with pytest.raises(ValueError):
            records.validate_request_id(value)
