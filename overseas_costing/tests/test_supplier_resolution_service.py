"""供应商解析必须在服务端收口：精确匹配才可自动写入，模糊结果只供人工选择。"""

import json


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
