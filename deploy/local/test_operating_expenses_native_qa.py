"""Dedicated-site native integration checks. Every transaction is rolled back."""
import json
import unittest
import frappe
from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile


class OperatingExpenseNativeQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if frappe.local.site != "operating-expenses-qa.localhost" or frappe.conf.db_host != "db":
            raise RuntimeError("Dedicated QA site only")
        frappe.set_user("Administrator")
        if frappe.db.count("GL Entry") or frappe.db.count("Payment Entry"):
            raise RuntimeError("QA must remain unposted")

    def tearDown(self):
        frappe.db.rollback()
        frappe.set_user("Administrator")

    def test_cache_and_mapping_cannot_be_faked_through_native_documents(self):
        self.assertTrue(frappe.db.exists("DocType", "Operating Expense Source"), "Source model is missing")
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc({"doctype": "Operating Expense Source", "source_id": "fake", "source_json": "{}"}).insert(ignore_permissions=True)

    def test_settings_disabled_and_secret_not_exposed(self):
        from deeplinkerp_branding.services import operating_expenses as service
        self.assertFalse(service.get_sync_settings()["enabled"])
        self.assertNotIn("api_token", service.get_sync_settings())

    def _sync(self):
        from deeplinkerp_branding.services import operating_expenses as service
        service.save_sync_settings({"QA Operating China": "QA Operating China", "QA Operating Mexico": "QA Operating Mexico"}, "operating-source-qa-only")
        preview = service.preview_sync()
        service.enable_sync(preview["preview_fingerprint"])
        service.sync_operating_expenses()
        return service

    def _supplier(self):
        return frappe.db.get_value("Supplier", {"supplier_name": "QA Operating Supplier"}, "name") or frappe.get_doc({"doctype": "Supplier", "supplier_name": "QA Operating Supplier", "supplier_type": "Company", "supplier_group": "All Supplier Groups"}).insert().name

    def _mapping(self, amount="100", party_type="Supplier", party=None, company="QA Operating China", suffix="QOC"):
        return {"company": company, "party_type": party_type, "party": party or self._supplier(),
            "payable_account": "Creditors - " + suffix, "payable_exchange_rate": "1", "posting_date": "2026-10-01",
            "actual_incurred": True, "no_existing_erp_coverage": True, "classification": "office",
            "expense_lines": [{"account": "Administrative Expenses - " + suffix, "source_amount": amount,
                "amount": amount, "exchange_rate": "1", "cost_center": frappe.db.get_value("Company", company, "cost_center")}],
            "payments": {root: {"bank_account": "Cash - " + suffix, "bank_amount": value, "payable_exchange_rate": "1", "bank_exchange_rate": "1"} for root, value in (("2001", "20"), ("2002", "30"), ("2003", "200"))}}

    def test_real_source_pagination_totals_types_and_invalid_rows_stay_visible(self):
        service = self._sync()
        result = service.get_operating_expenses(page_length=20)
        self.assertEqual(result["total_count"], 130)
        self.assertEqual(len(result["rows"]), 20)
        self.assertEqual(set(result["currency_totals"]), {"CNY", "MXN"})
        self.assertEqual(service.get_operating_expense_detail("1001")["source"]["application_type"], "payment")
        self.assertEqual(service.get_operating_expense_detail("1002")["source"]["application_type"], "reimbursement")
        self.assertIn("金额必须大于零", service.get_operating_expense_detail("1007")["issues"])
        self.assertIsNone(service.get_operating_expense_detail("1005")["company"])
        service.save_source_company("1005", "QA Operating China", service.get_operating_expense_detail("1005")["source"]["version"])
        self.assertEqual(service.get_operating_expense_detail("1005")["company"], "QA Operating China")

    def test_native_expense_and_partial_settlement_drafts_idempotent_without_gl(self):
        service = self._sync()
        item = service.get_operating_expense_detail("1001")["source"]
        service.save_mapping("1001", self._mapping(), item["version"])
        preview = service.preview_voucher("1001")
        expense = service.create_voucher_draft("1001", preview["fingerprint"])
        self.assertEqual(expense["docstatus"], 0)
        self.assertTrue(service.create_voucher_draft("1001", preview["fingerprint"])["existing"])
        wrong_date = frappe.get_doc("Journal Entry", expense["journal_entry"])
        wrong_date.posting_date = "2026-10-03"
        with self.assertRaises(frappe.ValidationError):
            wrong_date.save()
        for payment_id in ("2001", "2002"):
            settlement = service.preview_voucher("1001", payment_id)
            created = service.create_voucher_draft("1001", settlement["fingerprint"], payment_id)
            self.assertEqual(created["settlement_state"], "尚未核销")
            journal = frappe.get_doc("Journal Entry", created["journal_entry"])
            self.assertEqual(journal.docstatus, 0)
            self.assertFalse(any(r.reference_name for r in journal.accounts))
            self.assertFalse(any(r.account == "Administrative Expenses - QOC" for r in journal.accounts))
            journal.docstatus = 1
            with self.assertRaises(frappe.ValidationError):
                service.validate_operating_journal(journal)
        self.assertEqual(frappe.db.count("GL Entry"), 0)
        self.assertEqual(frappe.db.count("Payment Entry"), 0)

    def test_fresh_withdrawal_and_financial_change_block_draft_but_copy_does_not(self):
        service = self._sync()
        item = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        service.save_mapping("1001", self._mapping(), item["version"])
        preview = service.preview_voucher("1001")
        with patch.object(service, "_request", return_value={"items": [], "end": True}):
            with self.assertRaises(frappe.ValidationError):
                service.create_voucher_draft("1001", preview["fingerprint"])
        changed = dict(item, amount="101")
        with patch.object(service, "_request", return_value={"items": [changed], "end": True}):
            with self.assertRaises(frappe.ValidationError):
                service.create_voucher_draft("1001", preview["fingerprint"])
        copied = dict(item, version="technical-copy", source_request_id="99999", source_sheet="next-week")
        copied["payments"] = item["payments"] + [{"source_id": "2009", "amount": "10", "currency": "CNY", "payment_date": "2026-10-03", "evidence_status": "recorded"}]
        with patch.object(service, "_request", return_value={"items": [copied], "end": True}):
            self.assertEqual(service.create_voucher_draft("1001", preview["fingerprint"])["docstatus"], 0)

    def test_reimbursement_uses_native_employee_and_unknown_type_blocks(self):
        service = self._sync()
        if not frappe.db.exists("Gender", "Male"):
            frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
        employee = frappe.get_doc({"doctype": "Employee", "first_name": "QA Employee", "company": "QA Operating China",
            "gender": "Male", "date_of_birth": "1990-01-01", "date_of_joining": "2026-01-01", "status": "Active"}).insert()
        item = service.get_operating_expense_detail("1002")["source"]
        mapping = self._mapping("200", "Employee", employee.name)
        service.save_mapping("1002", mapping, item["version"])
        preview = service.preview_voucher("1002")
        created = service.create_voucher_draft("1002", preview["fingerprint"])
        journal = frappe.get_doc("Journal Entry", created["journal_entry"])
        self.assertEqual(journal.accounts[-1].party_type, "Employee")
        with self.assertRaises(frappe.ValidationError):
            service.save_mapping("1003", self._mapping("300"), service.get_operating_expense_detail("1003")["source"]["version"])

    def test_manual_classification_and_strict_finance_confirmation(self):
        service = self._sync()
        item = service.get_operating_expense_detail("1003")["source"]
        mapping = self._mapping("300")
        for field in ("actual_incurred", "no_existing_erp_coverage"):
            with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
                service.save_mapping("1003", {**mapping, "application_type": "payment", field: "false"}, item["version"])
        mapping["application_type"] = "payment"
        service.save_mapping("1003", mapping, item["version"])
        preview = service.preview_voucher("1003")
        self.assertEqual(service.create_voucher_draft("1003", preview["fingerprint"])["docstatus"], 0)
        self.assertEqual(service.get_operating_expense_detail("1003")["source"]["application_type"], "unclassified")
        self.assertEqual(service.get_operating_expenses(filters={"application_type": "unclassified"})["total_count"], 0)
        self.assertEqual(service.get_operating_expenses(filters={"application_type": "payment"})["total_count"], 129)

    def test_explicit_existing_native_recognition_does_not_require_false_no_coverage(self):
        service = self._sync()
        item = service.get_operating_expense_detail("1001")["source"]
        mapping = self._mapping()
        mapping.update(recognition_mode="existing", existing_erp_coverage_confirmed=True, no_existing_erp_coverage=False)
        service.save_mapping("1001", mapping, item["version"])
        preview = service.preview_voucher("1001")
        with self.assertRaises(frappe.ValidationError):
            service.create_voucher_draft("1001", preview["fingerprint"])
        journal = frappe.get_doc({"doctype": "Journal Entry", "company": "QA Operating China", "posting_date": "2026-10-01", "accounts": preview["accounts"]}).insert()
        wrong_date = frappe.get_doc({"doctype": "Journal Entry", "company": "QA Operating China", "posting_date": "2026-10-02", "accounts": preview["accounts"]}).insert()
        with self.assertRaises(frappe.ValidationError):
            service.link_existing("1001", wrong_date.name, preview["fingerprint"])
        result = service.link_existing("1001", journal.name, preview["fingerprint"])
        self.assertEqual(result["journal_entry"], journal.name)
        self.assertEqual(service.preview_voucher("1001", "2001")["settlement_state"], "尚未核销")
        self.assertFalse(journal.get("custom_operating_event_key"))
        journal.posting_date = "2026-10-03"
        with self.assertRaises(frappe.ValidationError):
            journal.save()
        journal.docstatus = 1  # Guard only: never call submit or write posted state.
        with self.assertRaises(frappe.ValidationError):
            service.validate_operating_journal(journal)
        journal.posting_date = "2026-10-01"
        service.validate_operating_journal(journal)
        journal.accounts[0].debit_in_account_currency += 1
        with self.assertRaises(frappe.ValidationError):
            service.validate_operating_journal(journal)
        journal.accounts[0].debit_in_account_currency -= 1
        changed = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        changed["payee_name"] = "Changed finance identity"
        with patch.object(service, "_fresh", return_value=changed):
            with self.assertRaises(frappe.ValidationError):
                service.validate_operating_journal(journal)
        self.assertFalse(frappe.db.get_value("Journal Entry", journal.name, "custom_operating_event_key"))

    def test_all_recorded_payments_must_be_positive_before_totaling(self):
        service = self._sync()
        item = service.get_operating_expense_detail("1001")["source"]
        service.save_mapping("1001", self._mapping(), item["version"])
        preview = service.preview_voucher("1001")
        service.create_voucher_draft("1001", preview["fingerprint"])
        original = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        for first, second in (("200", "-100"), ("20", "0"), ("20", "-1"), ("20", "NaN")):
            changed = json.loads(json.dumps(original))
            changed["payments"][0]["amount"], changed["payments"][1]["amount"] = first, second
            service._upsert(changed, service._maps(service._settings()))
            self.assertIn("付款金额", service.get_operating_expense_detail("1001")["issues"])
            count = frappe.db.count("Journal Entry")
            with patch.object(service, "_fresh", return_value=changed):
                with self.assertRaises(frappe.ValidationError):
                    service.preview_voucher("1001", "2001")
                with self.assertRaises(frappe.ValidationError):
                    service.create_voucher_draft("1001", "not-authorized", "2001")
            self.assertEqual(frappe.db.count("Journal Entry"), count)

    def test_detail_source_projection_honors_every_index_field_scope(self):
        service = self._sync()
        user = frappe.get_doc({"doctype": "User", "email": "operating-qa-projection@example.invalid", "first_name": "QA Projection", "send_welcome_email": 0, "roles": [{"role": "Accounts User"}]}).insert()
        original = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        original["opaque_private_party"] = "must-not-leak"
        original["payments"][0]["opaque_private_party"] = "must-not-leak"
        original["approvals"]["raw"]["opaque_private_party"] = "must-not-leak"
        service._upsert(original, service._maps(service._settings()))
        detail = service.get_operating_expense_detail("1001")["source"]
        self.assertNotIn("opaque_private_party", detail)
        self.assertNotIn("opaque_private_party", detail["payments"][0])
        self.assertNotIn("opaque_private_party", detail["approvals"]["raw"])
        self.assertEqual(detail["version"], original["version"])
        for field in sorted(service.SOURCE_FIELDS):
            frappe.db.set_value("DocField", {"parent": service.SOURCE, "fieldname": field}, "permlevel", 1)
            frappe.clear_cache(doctype=service.SOURCE)
            frappe.set_user(user.name)
            try:
                with self.assertRaises(frappe.PermissionError):
                    service.get_operating_expense_detail("1001")
                from frappe import client
                with self.assertRaises(frappe.PermissionError):
                    client.get(service.SOURCE, "1001")
            finally:
                frappe.set_user("Administrator")
                frappe.db.set_value("DocField", {"parent": service.SOURCE, "fieldname": field}, "permlevel", 0)
                frappe.clear_cache(doctype=service.SOURCE)
        service.save_mapping("1001", self._mapping(), original["version"])
        for mutation in ({"approvals": ["bad"]}, {"approvals": {"eligibility": "eligible", "raw": ["bad"]}},
                         {"payments": ["bad"]}, {"attachments": ["bad"]}, {"payments": "bad"}, {"attachments": "bad"}):
            with self.subTest(mutation=mutation):
                changed = {**original, **mutation}
                service._upsert(changed, service._maps(service._settings()))
                detail = service.get_operating_expense_detail("1001")
                self.assertIn("来源数据无效", detail["issues"])
                self.assertEqual(json.loads(frappe.get_doc(service.SOURCE, "1001").source_json), changed)
                if "approvals" in mutation:
                    self.assertIsNone(detail["source"]["approvals"]["eligibility"])
                for key in ("payments", "attachments"):
                    if key in mutation:
                        self.assertEqual(detail["source"][key], [])
                with patch.object(service, "_fresh", return_value=changed):
                    with self.assertRaises(frappe.ValidationError):
                        service.preview_voucher("1001")

    def test_export_all_filtered_records_numeric_cells_literal_formulas(self):
        service = self._sync()
        item = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        service._upsert({**item, "summary": "=SUM(A1:A2)"}, service._maps(service._settings()))
        service.export_operating_expenses(columns=["source_id", "summary", "amount", "paid_amount", "pending_amount", "currency"])
        with ZipFile(BytesIO(frappe.response["filecontent"])) as workbook:
            xml = workbook.read("xl/worksheets/sheet1.xml").decode()
            self.assertNotIn("<f>", xml)
            self.assertIn("=SUM(A1:A2)", xml)
            self.assertEqual(xml.count("<row "), 131)
            self.assertIn('<c r="C2" s="1"><v>', xml)
            self.assertIn('formatCode="0.00"', workbook.read("xl/styles.xml").decode())

    def test_company_permissions_lists_details_exports_and_unmapped_are_restricted(self):
        service = self._sync()
        user = frappe.get_doc({"doctype": "User", "email": "operating-qa-finance@example.invalid", "first_name": "QA Finance", "send_welcome_email": 0,
            "roles": [{"role": "Accounts User"}]}).insert()
        frappe.get_doc({"doctype": "User Permission", "user": user.name, "allow": "Company", "for_value": "QA Operating China", "apply_to_all_doctypes": 1}).insert()
        frappe.set_user(user.name)
        rows = service.get_operating_expenses(page_length=2500)
        self.assertEqual(rows["total_count"], 128)
        self.assertTrue(all(row["company"] == "QA Operating China" for row in rows["rows"]))
        for name in ("1005", "1006"):
            with self.subTest(name=name), self.assertRaises(frappe.PermissionError):
                service.get_operating_expense_detail(name)
        with self.assertRaises(frappe.PermissionError):
            service.get_sync_settings()
        with self.assertRaises(frappe.PermissionError):
            service.sync_operating_expenses()
        service.export_operating_expenses()
        with ZipFile(BytesIO(frappe.response["filecontent"])) as workbook:
            self.assertEqual(workbook.read("xl/worksheets/sheet1.xml").decode().count("<row "), 129)

    def test_fractional_fx_native_rounding_and_explicit_exchange_difference(self):
        service = self._sync()
        account = frappe.get_doc({"doctype": "Account", "account_name": "QA CNY Payable", "parent_account": "Current Liabilities - QOM", "company": "QA Operating Mexico", "account_currency": "CNY", "account_type": "Payable", "root_type": "Liability"}).insert()
        item = json.loads(frappe.get_doc("Operating Expense Source", "1006").source_json)
        item.update(currency="CNY", amount="100", source_id="fx-qa", version="fx-v1")
        item["payments"] = [{"source_id": "fx-p1", "amount": "20", "currency": "CNY", "payment_date": "2026-10-02", "evidence_status": "recorded"}]
        service._upsert(item, {"QA Operating Mexico": "QA Operating Mexico"})
        mapping = self._mapping("100", company="QA Operating Mexico", suffix="QOM")
        mapping.update(payable_account=account.name, payable_exchange_rate="1.234567", payments={"fx-p1": {"bank_account": "Cash - QOM", "bank_amount": "25.00", "bank_exchange_rate": "1", "payable_exchange_rate": "1.234567", "exchange_difference_account": "Exchange Gain/Loss - QOM", "cost_center": mapping["expense_lines"][0]["cost_center"]}})
        mapping["expense_lines"][0]["amount"] = "123.46"
        with patch.object(service, "_request", return_value={"items": [item], "end": True}):
            service.save_mapping("fx-qa", mapping, "fx-v1")
            preview = service.preview_voucher("fx-qa")
            self.assertEqual(preview["accounts"][-1]["credit"], "123.46")
            service.create_voucher_draft("fx-qa", preview["fingerprint"])
            settlement = service.preview_voucher("fx-qa", "fx-p1")
            self.assertEqual(settlement["accounts"][-1]["debit"], "0.31")
            self.assertEqual(service.create_voucher_draft("fx-qa", settlement["fingerprint"], "fx-p1")["docstatus"], 0)

    def test_approval_block_missing_mapping_precision_and_unknown_party_never_create(self):
        service = self._sync()
        with self.assertRaises(frappe.ValidationError):
            service.preview_voucher("1001")
        for root, amount in (("1004", "400"), ("1007", "0")):
            with self.subTest(root=root), self.assertRaises(frappe.ValidationError):
                service.save_mapping(root, self._mapping(amount), service.get_operating_expense_detail(root)["source"]["version"])
        item = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        exact = {**item, "amount": "100.001"}
        with patch.object(service, "_request", return_value={"items": [exact], "end": True}), self.assertRaises(ValueError):
            service.save_mapping("1001", self._mapping("100.001"), exact["version"])
        bad_party = self._mapping()
        bad_party["party"] = "Does Not Exist"
        with self.assertRaises(frappe.DoesNotExistError):
            service.save_mapping("1001", bad_party, item["version"])
        self.assertEqual(frappe.db.count("Operating Expense Event"), 0)

    def test_pagination_watermark_resumes_only_after_end(self):
        service = self._sync()
        settings = service._settings()
        before = settings.changed_since
        first = {"schema_version": 1, "source_system": "cashier-payment-archive", "items": [], "until": "2026-10-05T01:00:00Z", "next_cursor": "opaque-cursor", "end": False}
        with patch.object(service, "_request", return_value=first):
            service.sync_operating_expenses()
        self.assertEqual(service._settings().changed_since, before)
        self.assertEqual(service._settings().cursor, "opaque-cursor")
        with patch.object(service, "_request", return_value={**first, "end": True, "next_cursor": None}) as request:
            service.sync_operating_expenses()
        self.assertEqual(request.call_args.args[1]["cursor"], "opaque-cursor")
        self.assertEqual(service._settings().changed_since, first["until"])
        self.assertFalse(service._settings().cursor)

    def test_attachment_proxy_uses_only_authorized_fresh_typed_path(self):
        service = self._sync()
        item = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        item["attachments"] = [{"source_id": "attachment:qa", "version": "proof-v1", "filename": "../safe.pdf", "url": "/api/integrations/erp/attachments/12"}]
        service._upsert(item, service._maps(service._settings()))
        copied = {**item, "attachments": [{**item["attachments"][0], "url": "/api/integrations/erp/attachments/99"}]}
        with patch.object(service, "_request", side_effect=[{"items": [copied], "end": True}, b"QA proof"]) as request:
            service.download_operating_expense_attachment("1001", "attachment:qa")
            self.assertEqual(request.call_args.args[0], "/api/integrations/erp/attachments/99")
            self.assertEqual(frappe.response["filename"], "safe.pdf")
        copied["attachments"][0]["url"] = "https://evil.invalid/proof"
        with patch.object(service, "_request", return_value={"items": [copied], "end": True}), self.assertRaises(ValueError):
            service.download_operating_expense_attachment("1001", "attachment:qa")

    def test_native_source_field_permissions_deny_detail_and_financial_actions(self):
        service = self._sync()
        user = frappe.get_doc({"doctype": "User", "email": "operating-qa-fields@example.invalid", "first_name": "QA Restricted", "send_welcome_email": 0,
            "roles": [{"role": "Accounts User"}]}).insert()
        frappe.db.set_value("DocField", {"parent": "Operating Expense Source", "fieldname": "amount"}, "permlevel", 1)
        frappe.clear_cache(doctype="Operating Expense Source")
        frappe.set_user(user.name)
        try:
            with self.assertRaises(frappe.PermissionError):
                service.get_operating_expense_detail("1001")
            with self.assertRaises(frappe.PermissionError):
                service.preview_voucher("1001")
        finally:
            frappe.set_user("Administrator")
            frappe.db.set_value("DocField", {"parent": "Operating Expense Source", "fieldname": "amount"}, "permlevel", 0)
            frappe.clear_cache(doctype="Operating Expense Source")

    def test_long_source_text_preserves_original_and_quarantines_invalid_fields(self):
        service = self._sync()
        item = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        legal = "法律公司" * 40
        service.save_sync_settings({legal: "QA Operating China"})
        preview = service.preview_sync()
        service.enable_sync(preview["preview_fingerprint"])
        changed = {**item, "source_company": legal, "applicant": "长" * 200, "payee_name": "P" * 200, "version": "v" * 200, "source_id": "long-text-qa"}
        cached = service._upsert(changed, service._maps(service._settings()))
        self.assertEqual(cached.company, "QA Operating China")
        self.assertEqual(cached.source_company, legal)
        self.assertIn("来源数据无效", cached.issues)
        self.assertEqual(json.loads(cached.source_json)["payee_name"], "P" * 200)
        self.assertEqual(len(cached.payee_name), 140)
        healthy = service._upsert(item, {"QA Operating China": "QA Operating China"})
        self.assertFalse(healthy.issues)

    def test_missing_actual_payment_date_is_visible_and_never_defaults_to_today(self):
        service = self._sync()
        item = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        service.save_mapping("1001", self._mapping(), item["version"])
        preview = service.preview_voucher("1001")
        service.create_voucher_draft("1001", preview["fingerprint"])
        item["payments"][0]["payment_date"] = None
        cached = service._upsert(item, service._maps(service._settings()))
        self.assertIn("实际付款日期缺失", cached.issues)
        with patch.object(service, "_request", return_value={"items": [item], "end": True}), self.assertRaises(frappe.ValidationError):
            service.preview_voucher("1001", "2001")
        self.assertEqual(frappe.db.count("Operating Expense Event"), 1)

    def test_native_generic_audit_and_mapping_reads_cannot_bypass_journal_scope(self):
        from frappe import client
        service = self._sync()
        item = service.get_operating_expense_detail("1001")["source"]
        service.save_mapping("1001", self._mapping(), item["version"])
        created = service.create_voucher_draft("1001", service.preview_voucher("1001")["fingerprint"])
        event_name = frappe.db.get_value("Operating Expense Event", {"source": "1001"}, "name")
        user = frappe.get_doc({"doctype": "User", "email": "operating-qa-audit@example.invalid", "first_name": "QA Audit", "send_welcome_email": 0, "roles": [{"role": "Accounts User"}]}).insert()
        frappe.get_doc({"doctype": "Custom DocPerm", "parent": "Journal Entry", "parenttype": "DocType", "parentfield": "permissions", "role": "Accounts User", "permlevel": 0, "read": 0}).insert(ignore_permissions=True)
        frappe.clear_cache(doctype="Journal Entry")
        frappe.set_user(user.name)
        try:
            with self.assertRaises(frappe.PermissionError):
                client.get("Journal Entry", created["journal_entry"])
            generic = client.get("Operating Expense Event", event_name)
            self.assertFalse(generic.get("journal_entry"), "Generic native event read leaks inaccessible journal name")
            self.assertFalse(generic.get("provenance_json"), "Generic native event read leaks full audit mapping")
            try:
                rows = client.get_list("Operating Expense Event", fields=["name", "journal_entry", "provenance_json"])
            except frappe.PermissionError:
                rows = []
            self.assertTrue(all(not row.get("journal_entry") and not row.get("provenance_json") for row in rows))
            mapping = client.get("Operating Expense Mapping", "1001")
            self.assertFalse(mapping.get("mapping_json"), "Generic native mapping read exposes opaque private references")
            detail = service.get_operating_expense_detail("1001")
            self.assertNotIn(created["journal_entry"], json.dumps(detail["events"]))
            self.assertIn("关联凭证缺失或无权读取", json.dumps(detail["events"], ensure_ascii=False))
        finally:
            frappe.set_user("Administrator")
            frappe.clear_cache(doctype="Journal Entry")

    def test_native_source_json_cannot_bypass_private_scalar_field_permissions(self):
        from frappe import client
        service = self._sync()
        user = frappe.get_doc({"doctype": "User", "email": "operating-qa-scalar@example.invalid", "first_name": "QA Scalar", "send_welcome_email": 0, "roles": [{"role": "Accounts User"}]}).insert()
        frappe.db.set_value("DocField", {"parent": "Operating Expense Source", "fieldname": "amount"}, "permlevel", 1)
        frappe.clear_cache(doctype="Operating Expense Source")
        frappe.set_user(user.name)
        try:
            with self.assertRaises(frappe.PermissionError):
                client.get("Operating Expense Source", "1001")
        finally:
            frappe.set_user("Administrator")
            frappe.db.set_value("DocField", {"parent": "Operating Expense Source", "fieldname": "amount"}, "permlevel", 0)
            frappe.clear_cache(doctype="Operating Expense Source")

    def test_journal_child_field_permissions_mask_associations(self):
        service = self._sync()
        item = service.get_operating_expense_detail("1001")["source"]
        service.save_mapping("1001", self._mapping(), item["version"])
        created = service.create_voucher_draft("1001", service.preview_voucher("1001")["fingerprint"])
        user = frappe.get_doc({"doctype": "User", "email": "operating-qa-ledger-fields@example.invalid", "first_name": "QA Ledger", "send_welcome_email": 0, "roles": [{"role": "Accounts User"}]}).insert()
        frappe.db.set_value("DocField", {"parent": "Journal Entry Account", "fieldname": "debit_in_account_currency"}, "permlevel", 1)
        frappe.clear_cache(doctype="Journal Entry Account")
        frappe.set_user(user.name)
        try:
            self.assertTrue(frappe.has_permission("Journal Entry", "read", doc=created["journal_entry"]))
            detail = service.get_operating_expense_detail("1001")
            self.assertNotIn(created["journal_entry"], json.dumps(detail["events"]))
            rows = service.get_operating_expenses(filters={"keyword": "001"})["rows"]
            self.assertNotIn(created["journal_entry"], json.dumps(rows, default=str))
        finally:
            frappe.set_user("Administrator")
            frappe.db.set_value("DocField", {"parent": "Journal Entry Account", "fieldname": "debit_in_account_currency"}, "permlevel", 0)
            frappe.clear_cache(doctype="Journal Entry Account")

    def test_amount_sort_is_numeric_stable_and_shared_with_export(self):
        import xml.etree.ElementTree as ET
        service = self._sync()
        source = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        for root, value in (("sort-qa-1", "10"), ("sort-qa-2", "2"), ("sort-qa-3", "100"), ("sort-qa-4", "NaN")):
            service._upsert({**source, "source_id": root, "amount": value, "summary": "numeric-sort-qa"}, service._maps(service._settings()))
        filters = {"keyword": "numeric-sort-qa"}
        rows = service.get_operating_expenses(filters=filters, order_by="amount asc")["rows"]
        self.assertEqual([row["amount"] for row in rows], ["2", "10", "100", "NaN"])
        self.assertEqual([row["amount"] for row in service.get_operating_expenses(filters=filters, order_by="amount desc")["rows"]], ["100", "10", "2", "NaN"])
        service.export_operating_expenses(filters=filters, order_by="amount asc", columns=["source_id", "amount"])
        with ZipFile(BytesIO(frappe.response["filecontent"])) as workbook:
            xml = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            ids = [row.find("m:c/m:is/m:t", ns).text for row in xml.findall("m:sheetData/m:row", ns)[1:]]
            self.assertEqual(ids, [row["source_id"] for row in rows])


def run():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OperatingExpenseNativeQA)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    frappe.db.rollback()
    return {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "gl_entries": frappe.db.count("GL Entry"), "payment_entries": frappe.db.count("Payment Entry")}


def run_concurrency():
    """Two separate MariaDB transactions, one native draft; remove exact QA fixtures."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from deeplinkerp_branding.services import operating_expenses as service
    OperatingExpenseNativeQA.setUpClass()
    if frappe.db.count("Operating Expense Source") or frappe.db.count("Operating Expense Mapping") or frappe.db.count("Operating Expense Event"):
        raise RuntimeError("Concurrency QA requires empty dedicated operating fixtures")
    settings_before = service._settings().as_dict()
    token_before = service._settings().get_password("api_token", raise_exception=False)
    harness = OperatingExpenseNativeQA()
    service = harness._sync()
    mapping = harness._mapping()
    supplier = mapping["party"]
    version = service.get_operating_expense_detail("1001")["source"]["version"]
    service.save_mapping("1001", mapping, version)
    preview = service.preview_voucher("1001")
    source_names = frappe.get_all("Operating Expense Source", pluck="name", limit_page_length=0)
    frappe.db.commit()
    barrier = Barrier(2)
    def worker():
        frappe.init(site="operating-expenses-qa.localhost", sites_path="/home/frappe/frappe-bench/sites")
        frappe.connect()
        try:
            OperatingExpenseNativeQA.setUpClass()
            barrier.wait(timeout=10)
            result = service.create_voucher_draft("1001", preview["fingerprint"])
            frappe.db.commit()
            return result
        finally:
            frappe.db.rollback()
            frappe.destroy()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result(timeout=40) for future in futures]
        frappe.db.rollback()
        assert results[0]["journal_entry"] == results[1]["journal_entry"], results
        assert sum(bool(result["existing"]) for result in results) == 1, results
        assert frappe.db.count("Operating Expense Event") == 1
        assert frappe.db.count("GL Entry") == 0 and frappe.db.count("Payment Entry") == 0
        return {"transactions": 2, "drafts": 1, "same_event": True, "gl_entries": 0, "payment_entries": 0}
    finally:
        frappe.db.rollback()
        events = frappe.get_all("Operating Expense Event", fields=["name", "journal_entry"])
        with service.managed_write():
            for event in events:
                journal = frappe.get_doc("Journal Entry", event.journal_entry)
                if journal.docstatus != 0:
                    raise RuntimeError("Never remove submitted QA transactions")
                frappe.delete_doc("Operating Expense Event", event.name)
                frappe.delete_doc("Journal Entry", journal.name)
            frappe.delete_doc("Operating Expense Mapping", "1001")
            for name in source_names:
                frappe.delete_doc("Operating Expense Source", name)
            frappe.delete_doc("Supplier", supplier)
            restored = service._settings()
            restored.update({key: settings_before.get(key) for key in ("enabled", "company_mappings", "changed_since", "until", "cursor", "last_sync_at", "last_error", "preview_fingerprint")})
            restored.api_token = token_before or ""
            restored.save(ignore_permissions=True)
        frappe.db.commit()


def recover_concurrency_fixtures():
    """Recover only the known fixture after a test failure; exact site and roots."""
    from deeplinkerp_branding.services import operating_expenses as service
    OperatingExpenseNativeQA.setUpClass()
    sources = frappe.get_all("Operating Expense Source", pluck="name", limit_page_length=0)
    if set(sources) != {str(i) for i in range(1001, 1131)}:
        raise RuntimeError("Unexpected QA fixture roots; do not clean up")
    events = frappe.get_all("Operating Expense Event", fields=["name", "source", "journal_entry"])
    if any(event.source != "1001" for event in events):
        raise RuntimeError("Unexpected QA event source")
    with service.managed_write():
        for event in events:
            journal = frappe.get_doc("Journal Entry", event.journal_entry)
            if journal.docstatus != 0 or journal.custom_operating_source != "1001":
                raise RuntimeError("Unexpected QA journal; never remove")
            frappe.delete_doc("Operating Expense Event", event.name)
            frappe.delete_doc("Journal Entry", journal.name)
        frappe.delete_doc("Operating Expense Mapping", "1001")
        for name in sources:
            frappe.delete_doc("Operating Expense Source", name)
        supplier = frappe.db.get_value("Supplier", {"supplier_name": "QA Operating Supplier"}, "name")
        if supplier:
            frappe.delete_doc("Supplier", supplier)
        settings = service._settings()
        settings.update({key: None for key in ("changed_since", "until", "cursor", "last_sync_at", "last_error", "preview_fingerprint")})
        settings.enabled = 0
        settings.api_token = ""
        settings.company_mappings = []
        settings.save(ignore_permissions=True)
    frappe.db.commit()
    return {"removed_synthetic_sources": len(sources), "removed_drafts": len(events), "gl_entries": frappe.db.count("GL Entry"), "payment_entries": frappe.db.count("Payment Entry")}
