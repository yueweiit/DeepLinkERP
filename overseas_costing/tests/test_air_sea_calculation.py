"""Air/sea HTML parity and incomplete-input behavior."""
import copy
from decimal import Decimal

import pytest

from overseas_costing.services import air_sea_calculation as calc


def sample():
    row = [""] * 30
    for index, value in {0: "202510231037000496405", 1: "FL002788", 4: "PZ", 20: "50400", 23: "515.2", 24: "1.0805676", 25: "1.0449", 26: "366237.45"}.items():
        row[index] = value
    return {"rows": [row], "parameters": {}, "currencies": {}}


def test_html_sample_actual_formula_not_static_markup():
    result = calc.calculate(sample())
    assert result["status"] == "Ready"
    assert Decimal(result["oceanTotal"]) == Decimal("71504.68287568")
    assert Decimal(result["airTotal"]) == Decimal("92973.8233928448")
    assert Decimal(result["v"]["declaredValue"]) == Decimal("52662.96")
    assert result["unit"] == "件"


@pytest.mark.parametrize("value", ["", "-1", "NaN", "Infinity", "12bad", "1/2"])
def test_bad_active_parameter_is_draft_not_zero(value):
    payload = sample()
    payload["parameters"]["airKgRate"] = value
    result = calc.calculate(payload)
    assert result["status"] == "Draft"
    assert result["airTotal"] is None
    assert result["issues"]


def test_missing_declaration_does_not_become_free_goods():
    payload = sample()
    payload["rows"][0][25] = payload["rows"][0][26] = ""
    assert calc.calculate(payload)["status"] == "Draft"
    payload["rows"][0][25] = "0"
    assert calc.calculate(payload)["status"] == "Ready"


def test_explicit_zero_unit_price_has_priority_over_total():
    payload = sample()
    payload["rows"][0][25] = "0"
    result = calc.calculate(payload)
    assert Decimal(result["v"]["declaredValue"]) == 0


def test_used_fx_must_be_positive_but_unused_fx_is_not_required():
    payload = sample()
    payload["parameters"].update({"oceanRate": "0", "airRateFx": "0", "mxnToCny": "0"})
    assert calc.calculate(payload)["status"] == "Draft"
    payload["currencies"] = {key: "CNY" for key in calc.CURRENCY_DEFAULTS}
    assert calc.calculate(payload)["status"] == "Ready"


def test_snapshot_totals_count_once_and_manual_edits_are_independent():
    payload = sample()
    payload["rows"] *= 2
    payload["totals_override"] = {"grossWeight": "4197.4", "volume": "8.7403305"}
    before = copy.deepcopy(payload)
    result = calc.calculate(payload)
    assert Decimal(result["v"]["grossWeight"]) == Decimal("4197.4")
    assert Decimal(result["v"]["volume"]) == Decimal("8.7403305")
    assert payload == before


def test_mixed_units_allow_totals_but_not_average():
    payload = sample()
    other = payload["rows"][0].copy()
    other[4] = "套"
    payload["rows"].append(other)
    result = calc.calculate(payload)
    assert result["status"] == "Ready"
    assert result["mixedUnits"] is True
    assert result["oceanAvg"] is result["airAvg"] is None


def test_empty_rows_draft_and_scientific_number_exact():
    assert calc.calculate({"rows": []})["status"] == "Draft"
    payload = sample()
    payload["rows"][0][25] = "1e-3"
    assert Decimal(calc.calculate(payload)["v"]["declaredValue"]) == Decimal("50.4")


def test_zero_shipped_rows_do_not_require_declaration():
    payload = sample()
    empty = [""] * 30
    empty[1], empty[20] = "NOT-SHIPPED", "0"
    payload["rows"].append(empty)
    assert calc.calculate(payload)["status"] == "Ready"


def test_fee_difference_can_have_both_signs_or_be_zero():
    payload = sample()
    payload["currencies"] = {key: "CNY" for key in calc.CURRENCY_DEFAULTS}
    payload["parameters"].update({"airKgRate": "0", "airFixedFee": "3482.575"})
    result = calc.calculate(payload)
    assert Decimal(result["airTotal"]) == Decimal(result["oceanTotal"])
    payload["parameters"]["airFixedFee"] = "0"
    result = calc.calculate(payload)
    assert Decimal(result["airTotal"]) < Decimal(result["oceanTotal"])


def test_pasted_affixes_and_missing_summary_values():
    payload = sample()
    payload["rows"][0][20] = "50,400 件"
    payload["rows"][0][23] = "515.2 kg"
    payload["rows"][0][25] = "USD 1.0449"
    payload["rows"][0][24] = ""
    result = calc.calculate(payload)
    assert result["status"] == "Ready"
    assert result["v"]["volume"] is None
    assert Decimal(result["airTotal"]) == Decimal("92973.8233928448")


def test_unused_numeric_columns_still_reject_malformed_values():
    payload = sample()
    payload["rows"][0][12] = "wrong"
    assert calc.calculate(payload)["status"] == "Draft"


def test_numeric_precision_and_exponents_cannot_expand_unbounded_output():
    for value in ("1e-1000000", "1e-31", "0e1000000", "0." + "0" * 31 + "1", "0" * 129):
        assert calc.number(value) is None
        payload = sample()
        payload["parameters"]["oceanRate"] = value[:100]
        result = calc.calculate(payload)
        assert result["status"] == "Draft"
        assert len(str(result)) < 10000
    assert calc.number("1e-30") == Decimal("1e-30")
    assert calc.number("1.234567") == Decimal("1.234567")
