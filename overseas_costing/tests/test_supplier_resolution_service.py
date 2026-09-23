"""供应商解析必须在服务端收口：精确匹配才可自动写入，模糊结果只供人工选择。"""

import json
from types import SimpleNamespace

import pytest


def _service():
    from overseas_costing.services import supplier_resolution_service

    return supplier_resolution_service


def test_exact_match_uses_normalized_name_or_supplier_name_and_skips_disabled() -> None:
    service = _service()
    suppliers = [
        {"name": "SUP-001", "supplier_name": "东莞　悦为", "disabled": 0},
        {"name": "SUP-DISABLED", "supplier_name": "东莞悦为", "disabled": 1},
    ]

    result = service.resolve_supplier_reference("  东莞 悦为  ", suppliers=suppliers)

    assert result["status"] == "EXACT"
    assert result["canonical_supplier"] == "SUP-001"
    assert result["candidates"] == []


def test_cross_field_exact_matches_are_ambiguous_for_raw_supplier_text() -> None:
    service = _service()
    suppliers = [
        {"name": "SUP-WRONG", "supplier_name": "Acme", "disabled": 0},
        {"name": "ACME", "supplier_name": "Acme Manufacturing", "disabled": 0},
    ]

    result = service.resolve_supplier_reference("ACME", suppliers=suppliers)

    assert result["status"] == "AMBIGUOUS"
    assert result["canonical_supplier"] == ""
    assert {candidate["name"] for candidate in result["candidates"]} == {"ACME", "SUP-WRONG"}


def test_canonical_supplier_validation_uses_only_active_supplier_document_name() -> None:
    service = _service()
    suppliers = [
        {"name": "SUP-WRONG", "supplier_name": "ACME", "disabled": 0},
        {"name": "ACME", "supplier_name": "Acme Manufacturing", "disabled": 0},
        {"name": "DISABLED", "supplier_name": "Disabled Supplier", "disabled": 1},
    ]

    assert service.validate_canonical_supplier("ACME", suppliers=suppliers) == "ACME"
    try:
        service.validate_canonical_supplier("Disabled Supplier", suppliers=suppliers)
    except ValueError as error:
        assert "ERP 供应商列表" in str(error)
    else:
        raise AssertionError("停用 Supplier 不得通过规范 ID 校验")


def test_duplicate_supplier_name_is_ambiguous_and_never_auto_canonicalized() -> None:
    service = _service()
    suppliers = [
        {"name": "SUP-ACME-CN", "supplier_name": "Acme", "disabled": 0},
        {"name": "SUP-ACME-MX", "supplier_name": "ACME", "disabled": 0},
    ]

    result = service.resolve_supplier_reference("acme", suppliers=suppliers)

    assert result["status"] == "AMBIGUOUS"
    assert result["canonical_supplier"] == ""
    assert [candidate["name"] for candidate in result["candidates"]] == [
        "SUP-ACME-CN",
        "SUP-ACME-MX",
    ]
    assert all(candidate["score"] == 1 for candidate in result["candidates"])
    assert all(candidate["high_confidence"] is False for candidate in result["candidates"])


def test_fuzzy_match_returns_at_most_five_candidates_but_never_canonicalizes() -> None:
    service = _service()
    suppliers = [
        {"name": "SUP-ALPHA", "supplier_name": "Alpha Trading Mexico", "disabled": 0},
        {"name": "SUP-ALPHA-IND", "supplier_name": "Alpha Industrial Supply", "disabled": 0},
        {"name": "SUP-ALPHA-LOG", "supplier_name": "Alpha Logistics", "disabled": 0},
        {"name": "SUP-ALPHA-TECH", "supplier_name": "Alpha Technology", "disabled": 0},
        {"name": "SUP-ALPHA-TOOLS", "supplier_name": "Alpha Tools", "disabled": 0},
        {"name": "SUP-ALPHA-PACK", "supplier_name": "Alpha Packaging", "disabled": 0},
        {"name": "SUP-UNRELATED", "supplier_name": "Completely Different", "disabled": 0},
    ]

    result = service.resolve_supplier_reference("Alpha Tradng Mexico", suppliers=suppliers)

    assert result["status"] == "SUGGESTED"
    assert result["canonical_supplier"] == ""
    assert 1 <= len(result["candidates"]) <= 5
    assert result["candidates"][0]["name"] == "SUP-ALPHA"
    assert result["candidates"][0]["score"] >= 0.90
    assert result["candidates"][0]["high_confidence"] is True
    assert all(candidate["score"] >= 0.72 for candidate in result["candidates"])
    assert "SUP-UNRELATED" not in {candidate["name"] for candidate in result["candidates"]}


def test_low_similarity_and_empty_input_have_no_candidates() -> None:
    service = _service()
    suppliers = [{"name": "SUP-ONE", "supplier_name": "Proveedor Uno", "disabled": 0}]

    unresolved = service.resolve_supplier_reference("完全无关的名称", suppliers=suppliers)
    empty = service.resolve_supplier_reference("", suppliers=suppliers)

    assert unresolved == {
        "raw_value": "完全无关的名称",
        "status": "UNRESOLVED",
        "canonical_supplier": "",
        "candidates": [],
    }
    assert empty == {
        "raw_value": "",
        "status": "EMPTY",
        "canonical_supplier": "",
        "candidates": [],
    }


def test_supplier_provenance_distinguishes_new_template_from_legacy_default() -> None:
    service = _service()

    unresolved = service.supplier_provenance_state(
        {"supplier": "", "extra_json": json.dumps({
            "supplier_field_present": True,
            "supplier_raw_value": "Alpha Tradng Mexico",
            "supplier_match_status": "SUGGESTED",
        })}
    )
    legacy = service.supplier_provenance_state({"supplier": "", "extra_json": "{}"})
    resolved = service.supplier_provenance_state(
        {"supplier": "SUP-ALPHA", "extra_json": json.dumps({"supplier_field_present": True})}
    )

    assert unresolved["requires_explicit_supplier"] is True
    assert unresolved["legacy_default_allowed"] is False
    assert legacy["requires_explicit_supplier"] is False
    assert legacy["legacy_default_allowed"] is True
    assert "历史兼容默认供应商" in legacy["warning"]
    assert resolved["requires_explicit_supplier"] is False
    assert resolved["legacy_default_allowed"] is False


@pytest.mark.parametrize("supplier_name", ["", "   ", "-", "—", "－", "x" * 141])
def test_create_supplier_rejects_blank_placeholder_and_overlong_names(supplier_name: str) -> None:
    service = _service()

    with pytest.raises(service.SupplierCreationError) as captured:
        service.create_supplier(supplier_name, suppliers=[], supplier_group="All Supplier Groups")

    assert captured.value.code == "INVALID_SUPPLIER_NAME"


def test_create_supplier_reuses_one_active_exact_match_without_inserting() -> None:
    service = _service()
    calls = []

    result = service.create_supplier(
        " Alpha Trading ",
        suppliers=[{"name": "SUP-001", "supplier_name": "Alpha Trading", "disabled": 0}],
        supplier_group="All Supplier Groups",
        document_factory=lambda payload: calls.append(payload),
    )

    assert result == {
        "ok": True,
        "created": False,
        "supplier": "SUP-001",
        "supplier_name": "Alpha Trading",
        "supplier_group": "",
    }
    assert calls == []


def test_create_supplier_blocks_disabled_and_ambiguous_exact_matches() -> None:
    service = _service()

    with pytest.raises(service.SupplierCreationError) as disabled:
        service.create_supplier(
            "Dormant Supplier",
            suppliers=[{"name": "SUP-OFF", "supplier_name": "Dormant Supplier", "disabled": 1}],
            supplier_group="All Supplier Groups",
        )
    assert disabled.value.code == "DISABLED_SUPPLIER_EXISTS"

    with pytest.raises(service.SupplierCreationError) as ambiguous:
        service.create_supplier(
            "ACME",
            suppliers=[
                {"name": "SUP-ACME-CN", "supplier_name": "ACME", "disabled": 0},
                {"name": "SUP-ACME-MX", "supplier_name": "Acme", "disabled": 0},
            ],
            supplier_group="All Supplier Groups",
        )
    assert ambiguous.value.code == "AMBIGUOUS_SUPPLIER"


def test_create_supplier_requires_confirmation_for_high_confidence_then_uses_safe_fields() -> None:
    service = _service()
    suppliers = [{"name": "SUP-ALPHA", "supplier_name": "Alpha Trading Mexico", "disabled": 0}]

    with pytest.raises(service.SupplierCreationError) as confirmation:
        service.create_supplier(
            "Alpha Tradng Mexico",
            suppliers=suppliers,
            supplier_group="All Supplier Groups",
        )
    assert confirmation.value.code == "SIMILAR_SUPPLIER_CONFIRMATION_REQUIRED"
    assert confirmation.value.candidates[0]["name"] == "SUP-ALPHA"

    created_payload = {}

    class _SupplierDoc:
        name = "SUP-NEW"
        supplier_name = "Alpha Tradng Mexico"
        supplier_group = "All Supplier Groups"

        def insert(self, *, ignore_permissions=False):
            created_payload["ignore_permissions"] = ignore_permissions

    def factory(payload):
        created_payload.update(payload)
        return _SupplierDoc()

    result = service.create_supplier(
        "  Alpha Tradng Mexico  ",
        confirm_similar=True,
        suppliers=suppliers,
        supplier_group="All Supplier Groups",
        document_factory=factory,
    )

    assert result["created"] is True
    assert result["supplier"] == "SUP-NEW"
    assert created_payload == {
        "doctype": "Supplier",
        "supplier_name": "Alpha Tradng Mexico",
        "supplier_group": "All Supplier Groups",
        "supplier_type": "Company",
        "disabled": 0,
        "ignore_permissions": True,
    }


def test_create_supplier_requires_default_group_and_recovers_concurrent_insert() -> None:
    service = _service()

    with pytest.raises(service.SupplierCreationError) as missing_group:
        service.create_supplier("New Supplier", suppliers=[], supplier_group="")
    assert missing_group.value.code == "SUPPLIER_GROUP_REQUIRED"

    supplier_snapshots = iter([
        [],
        [{"name": "SUP-RACE", "supplier_name": "Race Supplier", "disabled": 0}],
    ])

    class _RacingDoc:
        def insert(self, *, ignore_permissions=False):
            raise RuntimeError("duplicate entry")

    result = service.create_supplier(
        "Race Supplier",
        supplier_loader=lambda: next(supplier_snapshots),
        supplier_group="All Supplier Groups",
        document_factory=lambda _payload: _RacingDoc(),
    )

    assert result["created"] is False
    assert result["supplier"] == "SUP-RACE"


def test_default_supplier_group_prefers_configured_value_then_root(monkeypatch) -> None:
    service = _service()
    available = {"Preferred Suppliers", "All Supplier Groups"}
    fake_frappe = SimpleNamespace(
        get_meta=lambda _doctype: SimpleNamespace(
            get_field=lambda _fieldname: SimpleNamespace(default="Preferred Suppliers")
        ),
        db=SimpleNamespace(exists=lambda _doctype, name: name in available),
    )
    monkeypatch.setattr(service, "frappe", fake_frappe)

    assert service._default_supplier_group() == "Preferred Suppliers"

    fake_frappe.get_meta = lambda _doctype: SimpleNamespace(
        get_field=lambda _fieldname: SimpleNamespace(default="Missing Group")
    )
    assert service._default_supplier_group() == "All Supplier Groups"
