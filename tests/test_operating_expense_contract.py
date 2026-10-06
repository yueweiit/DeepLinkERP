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

    def test_oa_cashier_updates_preserve_expense_confirmation_and_event(self):
        before = source()
        before["source_system"] = "dingtalk-oa"
        before["approvals"]["raw"]["cashier_finance_review"] = "待付款"
        mapping = {"party": "Supplier", "payments": {"p1": {"bank_amount": "20"}, "p2": {"bank_amount": "30"}}}
        after = copy.deepcopy(before)
        after["approvals"]["raw"].update(cashier_finance_review="已付款", cashier_general_manager_approval="同意付款")
        after["payments"].append({"source_id": "p2", "amount": "30", "currency": "CNY", "payment_date": "2026-10-03", "evidence_status": "recorded"})
        self.assertEqual(contract.expense_facts(before), contract.expense_facts(after))
        self.assertEqual(contract.event_fingerprint(before, mapping), contract.event_fingerprint(after, mapping))
        self.assertEqual(contract.event_fingerprint(before, mapping, "p1"), contract.event_fingerprint(after, mapping, "p1"))
        after["payments"][0]["bank_reference"] = "new-bank-proof"
        self.assertEqual(contract.expense_facts(before), contract.expense_facts(after))
        self.assertNotEqual(contract.event_fingerprint(before, mapping, "p1"), contract.event_fingerprint(after, mapping, "p1"))
        self.assertEqual(before["approvals"]["raw"]["cashier_finance_review"], "待付款")
        self.assertEqual(after["approvals"]["raw"]["cashier_finance_review"], "已付款")

    def test_original_oa_changes_and_legacy_cashier_approvals_still_invalidate_expense(self):
        before = source()
        before["source_system"] = "dingtalk-oa"
        for field, value in (("amount", "101"), ("source_company", "legal-2"), ("approvals", {"eligibility": "blocked", "raw": {"status": "COMPLETED", "result": "refuse"}}),
                             ("approvals", {"eligibility": "eligible", "raw": {"status": "COMPLETED", "result": "agree", "finance_review": "changed-original"}})):
            with self.subTest(field=field, value=value):
                after = {**before, field: value}
                self.assertNotEqual(contract.expense_facts(before), contract.expense_facts(after))
                self.assertNotEqual(contract.event_fingerprint(before, {}), contract.event_fingerprint(after, {}))
        legacy = source()
        after = copy.deepcopy(legacy)
        after["approvals"]["raw"]["cashier_finance_review"] = "changed-legacy"
        self.assertNotEqual(contract.expense_facts(legacy), contract.expense_facts(after))
        self.assertNotEqual(contract.event_fingerprint(legacy, {}), contract.event_fingerprint(after, {}))

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

    def test_original_oa_contract_and_scoped_archive_token_are_supported(self):
        item = source(); item["source_system"] = "dingtalk-oa"
        self.assertEqual(contract.validate_source(item)["source_system"], "dingtalk-oa")
        self.assertEqual(contract.attachment_path("/oa-archive/" + "a" * 64), "/oa-archive/" + "a" * 64)

    def test_financial_fingerprint_normalizes_decimal_formatting(self):
        before = source()
        after = {**before, "amount": "100"}
        mapping = {"party": "Supplier", "expense_lines": [{"amount": "100", "source_amount": "100", "exchange_rate": "1"}]}
        formatted = {"party": "Supplier", "expense_lines": [{"amount": "100.00", "source_amount": "100.0", "exchange_rate": "1.0"}]}
        self.assertEqual(contract.event_fingerprint(before, mapping), contract.event_fingerprint(after, formatted))


if __name__ == "__main__":
    unittest.main()
