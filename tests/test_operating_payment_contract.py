from copy import deepcopy
from decimal import Decimal
import importlib.util
from pathlib import Path
import pytest

path = Path(__file__).parents[1] / "deeplinkerp_branding/services/operating_payment_contract.py"


def module():
    assert path.exists(), "ERP operating payment contract has not been implemented"
    spec = importlib.util.spec_from_file_location("payment_contract", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def source():
    return {"source_id": "1001", "amount": "100.00", "currency": "CNY",
            "payment_evidence_status": "recorded", "paid_amount": "30", "pending_amount": "70",
            "payments": [{"source_id": "10", "amount": "30", "currency": "CNY", "evidence_status": "recorded"}]}


def test_frozen_history_and_local_partial_payment_are_counted_once_without_mutation():
    c = module()
    s = source(); before = deepcopy(s)
    rows = [{"name": "erp-1", "amount": "20", "status": "Registered"},
            {"name": "erp-2", "amount": "5", "status": "Reversed"}]
    result = c.balance(s, rows)
    assert result == {"paid_amount": "50.00", "pending_amount": "50.00", "source_status": "部分付款"}
    assert s == before


@pytest.mark.parametrize("changes", [
    {"payment_evidence_status": "unknown"}, {"paid_amount": None},
    {"payments": [{"source_id": "10", "amount": "30", "currency": "USD", "evidence_status": "recorded"}]},
    {"payments": [{"source_id": "10", "amount": "30", "currency": "CNY", "evidence_status": "conflict"}]},
    {"paid_amount": "35"}, {"pending_amount": "80"},
    {"payments": [{"source_id": "10", "amount": "-30", "currency": "CNY", "evidence_status": "recorded"}]},
])
def test_uncertain_or_inconsistent_history_is_not_zero_or_payable(changes):
    c = module(); s = source(); s.update(changes)
    with pytest.raises(ValueError):
        c.balance(s, [])


def test_confirmed_zero_history_and_full_payment_have_correct_status():
    c = module(); s = source(); s.update(payments=[], paid_amount="0", pending_amount="100")
    assert c.balance(s, []) ["source_status"] == "未付款"
    assert c.balance(s, [{"name": "erp-1", "amount": "100", "status": "Registered"}])["source_status"] == "已付款"


@pytest.mark.parametrize("amount", ["0", "-1", "70.01", "1.001", "NaN", True, 1.1])
def test_registration_amount_is_exact_positive_and_not_above_balance(amount):
    c = module()
    with pytest.raises(ValueError):
        c.registration({"amount": amount, "payment_date": "2026-10-07", "bank_amount": "20"}, "70", same_currency=True)


def test_registration_preserves_exact_currency_amounts_and_rejects_same_currency_difference():
    c = module()
    values = {"amount": "20.00", "payment_date": "2026-10-07", "bank_amount": "20.00"}
    assert c.registration(values, "70", same_currency=True)["amount"] == "20.00"
    with pytest.raises(ValueError):
        c.registration({**values, "bank_amount": "19"}, "70", same_currency=True)
    assert c.registration({**values, "bank_amount": "2.5"}, "70", same_currency=False)["bank_amount"] == "2.50"


def test_duplicate_local_identifiers_and_overpayment_fail_closed():
    c = module()
    with pytest.raises(ValueError):
        c.balance(source(), [{"name": "x", "amount": "20", "status": "Registered"}] * 2)
    with pytest.raises(ValueError):
        c.balance(source(), [{"name": "x", "amount": "71", "status": "Registered"}])
