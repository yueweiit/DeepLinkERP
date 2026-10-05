"""Financial identity must survive archival copies without tolerating changed facts."""
import copy
import unittest

try:
    from deeplinkerp_branding.services import operating_expense_contract as contract
except ImportError:
    contract = None


def source():
    return {"source_system": "cashier-payment-archive", "source_id": "root-1", "version": "v1",
        "updated_at": "2026-10-01T00:00:00Z", "application_type": "payment", "source_company": "legal-1",
        "source_sheet": "weekly", "amount": "100.00", "currency": "CNY", "request_date": "2026-10-01",
        "payee_name": "Vendor", "applicant": "Person", "approvals": {"eligibility": "eligible", "raw": {"status": "COMPLETED", "result": "agree"}},
        "payments": [{"source_id": "p1", "amount": "20", "currency": "CNY", "payment_date": "2026-10-02", "evidence_status": "recorded"}],
        "attachments": [{"source_id": "a1", "version": "a-v1", "filename": "invoice.pdf", "url": "/api/integrations/erp/attachments/12"}]}


class OperatingExpenseContractTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(contract, "operating expense contract is missing")

    def test_technical_copy_and_new_payment_do_not_change_expense_identity(self):
        before = source()
        after = copy.deepcopy(before)
        after.update(version="v2", updated_at="2026-10-03T00:00:00Z", source_request_id="999", source_sheet="next-week")
        after["payments"].append({"source_id": "p2", "amount": "30", "currency": "CNY"})
        after["attachments"][0].update(url="/api/integrations/erp/attachments/999", provenance=[{"url": "x"}])
        self.assertEqual(contract.expense_facts(before), contract.expense_facts(after))
        after["amount"] = "101"
        self.assertNotEqual(contract.expense_facts(before), contract.expense_facts(after))

    def test_payment_copy_identity_excludes_timestamps_but_retains_evidence(self):
        payment = source()["payments"][0]
        copied = {**payment, "version": "weekly", "updated_at": "later", "source_request_id": "888", "provenance": []}
        self.assertEqual(contract.payment_facts(payment), contract.payment_facts(copied))
        copied["evidence_status"] = "conflict"
        self.assertNotEqual(contract.payment_facts(payment), contract.payment_facts(copied))

    def test_money_rejects_nonfinite_missing_float_and_excess_precision(self):
        for value in (None, "", "NaN", "Infinity", 0.1, "0.001", "1e100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                contract.money(value, precision=2)
        self.assertEqual(str(contract.money("12.30", precision=2)), "12.30")

    def test_source_validation_rejects_conflicts_and_duplicate_payment_roots(self):
        for mutation in ({"amount": "NaN"}, {"currency": "unknown"}, {"source_id": ""}, {"application_type": "invented"},
                         {"approvals": ["bad"]}, {"approvals": {"eligibility": "eligible", "raw": ["bad"]}},
                         {"payments": ["bad"]}, {"attachments": ["bad"]}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                contract.validate_source({**source(), **mutation})
        duplicate = source()
        duplicate["payments"] *= 2
        with self.assertRaises(ValueError):
            contract.validate_source(duplicate)
        self.assertEqual(contract.validate_source(source())["source_id"], "root-1")

    def test_typed_attachment_paths_do_not_accept_arbitrary_urls(self):
        self.assertEqual(contract.attachment_path("/api/integrations/erp/payment-vouchers/12"), "/api/integrations/erp/payment-vouchers/12")
        for path in ("https://evil.test/a", "//127.0.0.1/a", "/api/integrations/erp/attachments/12?token=x", "/api/integrations/erp/attachments/../12"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contract.attachment_path(path)

    def test_financial_fingerprint_normalizes_decimal_formatting(self):
        before = source()
        after = {**before, "amount": "100"}
        mapping = {"party": "Supplier", "expense_lines": [{"amount": "100", "source_amount": "100", "exchange_rate": "1"}]}
        formatted = {"party": "Supplier", "expense_lines": [{"amount": "100.00", "source_amount": "100.0", "exchange_rate": "1.0"}]}
        self.assertEqual(contract.event_fingerprint(before, mapping), contract.event_fingerprint(after, formatted))


if __name__ == "__main__":
    unittest.main()
