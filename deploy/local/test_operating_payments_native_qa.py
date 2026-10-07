"""ERP registration/ownership integration on the dedicated site, rollback every test."""
import copy
import json
import unittest
from unittest.mock import patch
import frappe


class OperatingPaymentNativeQA(unittest.TestCase):
    def setUp(self):
        if frappe.local.site != "operating-expenses-qa.localhost" or frappe.conf.db_host != "db":
            raise RuntimeError("Dedicated synthetic operating site only")
        frappe.set_user("Administrator")
        from deeplinkerp_branding.services import operating_expenses as expenses
        self.expenses = expenses
        template = frappe.get_doc("Operating Expense Source", "1001").as_dict()
        self.source = frappe.get_doc({**template,"name":"qa-native-payment","source_id":"qa-native-payment"})
        self.raw = json.loads(self.source.source_json)
        self.raw["source_id"] = self.source.name
        self.raw.update(amount="100.00", currency="CNY", paid_amount="30.00", pending_amount="70.00",
                        payment_evidence_status="recorded", source_conflict=False, currency_conflict=False)
        self.raw["payments"] = [{"source_id": "history-1", "amount": "30.00", "currency": "CNY",
                                 "payment_date": "2026-10-02", "evidence_status": "recorded"}]
        self.raw["approvals"] = {"eligibility": "eligible", "raw": {"status": "COMPLETED", "result": "agree"}}
        self.raw["version"] = "qa-payment-version"
        self.source.source_json=json.dumps(self.raw)
        with expenses.managed_write():
            self.source.insert(ignore_permissions=True)
        self.patch = patch.object(expenses, "_fresh", side_effect=lambda doc, **kwargs: copy.deepcopy(self.raw))
        self.patch.start()
        self.bank = frappe.db.get_value("Account", {"company": self.source.company, "account_type": "Cash", "is_group": 0}, "name")
        self.assertTrue(self.bank)
        self.before_gl = frappe.db.count("GL Entry")
        self.before_pe = frappe.db.count("Payment Entry")

    def tearDown(self):
        self.patch.stop()
        frappe.db.rollback()
        frappe.set_user("Administrator")

    def service(self):
        from pathlib import Path
        self.assertTrue(Path(frappe.get_app_path("deeplinkerp_branding", "services", "operating_payment_service.py")).is_file(), "Managed payment service must exist")
        from deeplinkerp_branding.services import operating_payment_service
        return operating_payment_service

    def takeover(self):
        service = self.service()
        from deeplinkerp_branding.services.operating_expense_contract import digest, expense_facts
        with self.expenses.managed_write():
            frappe.get_doc({"doctype": service.TAKEOVER, "source": self.source.name,
                           "company": self.source.company, "history_json": json.dumps(self.raw),
                           "claim_token": "qa-frozen-claim", "history_fingerprint": digest(self.raw),
                           "expense_fingerprint": digest(expense_facts(self.raw)), "claimed_by": "Administrator"}).insert(ignore_permissions=True)
        return service

    def values(self, amount="20.00"):
        return {"amount": amount, "bank_amount": amount, "payment_date": "2026-10-07",
                "bank_account": self.bank, "party_type": "Supplier", "party": "QA Operating Supplier",
                "bank_reference": "synthetic-no-transfer", "remark": "QA only, rolled back"}

    def test_metadata_and_service_exist(self):
        service = self.service()
        self.assertTrue(frappe.db.exists("DocType", service.PAYMENT))
        self.assertTrue(frappe.db.exists("DocType", service.TAKEOVER))

    def test_proof_upload_is_private_and_rejects_remote_and_unsupported_files(self):
        from types import SimpleNamespace
        service = self.takeover()
        self.assertTrue(callable(getattr(service, "upload_payment_proof", None)), "Private proof upload must exist")
        result = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-first")
        with patch.object(service, "_save_proof", return_value=SimpleNamespace(name="qa-proof", file_name="qa.pdf", file_url="/private/files/qa.pdf")) as save:
            with patch.multiple(frappe.local, uploaded_file=b"%PDF-1.4\nqa", uploaded_filename="qa.pdf", uploaded_file_url=None, create=True):
                service.upload_payment_proof(self.source.name, result["payment_id"])
            save.assert_called_once()
        for filename, content, remote in (("qa.html", b"<script>", None), ("qa.pdf", b"not pdf", None), ("qa.pdf", b"%PDF-x", "https://example.com/file.pdf")):
            with patch.multiple(frappe.local, uploaded_file=content, uploaded_filename=filename, uploaded_file_url=remote, create=True):
                with self.assertRaises(frappe.ValidationError):
                    service.upload_payment_proof(self.source.name, result["payment_id"])

    def test_native_uploader_keeps_managed_payment_read_only_and_checks_parent_on_server(self):
        from types import SimpleNamespace
        from frappe.handler import check_write_permission
        service=self.takeover()
        result=service.register_payment(self.source.name,self.values(),self.raw["version"],"qa-uploader")
        frappe.set_user("operating-browser-china@example.invalid")
        with self.assertRaises(frappe.PermissionError):
            check_write_permission(service.PAYMENT,result["payment_id"])
        # The uploader delegates its untrusted docname to the specialized service,
        # never to the general editable-document upload branch.
        check_write_permission(None,result["payment_id"])
        with patch.object(service,"_save_proof",return_value=SimpleNamespace(name="qa-proof",file_name="qa.pdf")) as save:
            with patch.object(frappe.local,"form_dict",frappe._dict(docname=result["payment_id"])), patch.multiple(frappe.local,uploaded_file=b"%PDF-1.4\nqa",uploaded_filename="qa.pdf",uploaded_file_url=None,create=True):
                uploaded=service.upload_payment_proof()
            self.assertEqual(uploaded["is_private"],1)
            save.assert_called_once()
            with patch.object(frappe.local,"form_dict",frappe._dict(doctype="Purchase Order",docname=result["payment_id"])), self.assertRaises(frappe.ValidationError):
                service.upload_payment_proof()

    def test_invalid_pdf_returns_validation_message_before_creating_any_file(self):
        service=self.takeover()
        result=service.register_payment(self.source.name,self.values(),self.raw["version"],"qa-invalid-proof")
        count=frappe.db.count("File",{"attached_to_doctype":service.PAYMENT,"attached_to_name":result["payment_id"]})
        with patch.multiple(frappe.local,uploaded_file=b"%PDF-1.4\nnot a complete PDF\n%%EOF",uploaded_filename="qa-invalid-proof.pdf",uploaded_file_url=None,create=True):
            with self.assertRaisesRegex(frappe.ValidationError,"文件.*损坏|无法读取"):
                service.upload_payment_proof(self.source.name,result["payment_id"])
        self.assertEqual(frappe.db.count("File",{"attached_to_doctype":service.PAYMENT,"attached_to_name":result["payment_id"]}),count)

    def test_real_private_file_save_and_download_apply_native_parent_permissions(self):
        from io import BytesIO
        from pypdf import PdfWriter
        service=self.takeover()
        result=service.register_payment(self.source.name,self.values(),self.raw["version"],"qa-real-proof")
        writer=PdfWriter()
        writer.add_blank_page(width=100,height=100)
        writer.add_metadata({"/Title":"Synthetic rollback-only proof "+frappe.generate_hash(length=12)})
        stream=BytesIO();writer.write(stream)
        frappe.set_user("operating-browser-china@example.invalid")
        with patch.multiple(frappe.local,uploaded_file=stream.getvalue(),uploaded_filename="qa-native-private-proof.pdf",uploaded_file_url=None,create=True):
            uploaded=service.upload_payment_proof(self.source.name,result["payment_id"])
        file=frappe.get_doc("File",uploaded["name"])
        try:
            self.assertEqual(file.is_private,1)
            self.assertEqual(file.attached_to_name,result["payment_id"])
            self.assertEqual(file.get_content(encodings=[]),stream.getvalue())
            service.download_payment_proof(self.source.name,result["payment_id"],file.name)
            self.assertEqual(frappe.response.filecontent,stream.getvalue())
            frappe.set_user("Administrator")
            other_user="qa-proof-mexico@example.invalid"
            self.assertFalse(frappe.db.exists("User",other_user))
            frappe.get_doc({"doctype":"User","email":other_user,"first_name":"Synthetic proof scope",
                            "user_type":"System User","send_welcome_email":0,
                            "roles":[{"role":"Accounts User"}]}).insert(ignore_permissions=True)
            frappe.get_doc({"doctype":"User Permission","user":other_user,"allow":"Company",
                            "for_value":"QA Operating Mexico","apply_to_all_doctypes":1}).insert(ignore_permissions=True)
            frappe.set_user(other_user)
            self.assertIn("Accounts User",frappe.get_roles())
            with self.assertRaises(frappe.PermissionError):
                service.download_payment_proof(self.source.name,result["payment_id"],file.name)
        finally:
            frappe.set_user("Administrator")
            with self.expenses.managed_write():
                frappe.delete_doc("File",file.name,ignore_permissions=True)

    def test_no_registration_before_verified_takeover(self):
        service = self.service()
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-first")

    def test_mismatched_original_amount_cannot_contact_takeover_writer(self):
        self.raw["original_source_amount"]="200.00"
        with patch.object(self.expenses,"_request") as request, self.assertRaises(frappe.ValidationError):
            self.service().preview_takeover(self.source.name)
        request.assert_not_called()

    def test_registration_rejects_other_bank_as_advance_and_invalid_accounting_rates(self):
        service=self.takeover()
        parent=frappe.db.get_value("Account",{"company":self.source.company,"root_type":"Asset","is_group":1},"name")
        other=frappe.get_doc({"doctype":"Account","account_name":"QA Other Payment Bank","company":self.source.company,"parent_account":parent,"account_type":"Bank","account_currency":"CNY","is_group":0}).insert()
        for extras in ({"advance_account":other.name,"source_exchange_rate":"1","bank_exchange_rate":"1"},
                       {"bank_exchange_rate":"2"},{"source_exchange_rate":"2"},
                       {"exchange_difference_account":self.bank}):
            with self.subTest(extras=extras), self.assertRaises(frappe.ValidationError):
                service.register_payment(self.source.name,{**self.values(),**extras},self.raw["version"],"qa-invalid-config")

    def test_explicit_advance_generates_only_one_unposted_native_draft_without_expense_recognition(self):
        service = self.takeover()
        self.assertTrue(callable(getattr(service, "advance_preview", None)), "Explicit advance preview must exist")
        values = {**self.values(), "advance_account": frappe.db.get_value("Account", {"company":self.source.company,"account_type":"Payable","is_group":0},"name"), "source_exchange_rate":"1", "bank_exchange_rate":"1"}
        result = service.register_payment(self.source.name, values, self.raw["version"], "qa-advance")
        payment_source = "erp-payment:" + result["payment_id"]
        source = service.merge_source(self.source, copy.deepcopy(self.raw))
        preview = service.advance_preview(self.source, source, payment_source)
        self.assertEqual(preview["recognition"], None)
        self.assertEqual(preview["settlement_state"], "预付款 · 未核销")
        self.assertEqual(preview["accounts"][0]["account"], values["advance_account"])
        with patch.object(self.expenses,"_fresh",return_value=source):
            draft = self.expenses.create_voucher_draft(self.source.name, preview["fingerprint"], payment_source)
            again = self.expenses.create_voucher_draft(self.source.name, preview["fingerprint"], payment_source)
        self.assertEqual(draft["journal_entry"], again["journal_entry"])
        self.assertEqual(frappe.db.get_value("Journal Entry",draft["journal_entry"],"docstatus"),0)
        self.assertEqual(frappe.db.count("GL Entry"),self.before_gl)
        with self.assertRaises(frappe.ValidationError):
            service.reverse_payment(self.source.name,result["payment_id"],"QA","qa-reverse-advance")
        service.reverse_payment(self.source.name,result["payment_id"],"QA","qa-reverse-advance",discard_drafts=True)
        self.assertFalse(frappe.db.exists("Journal Entry",draft["journal_entry"]))
        event=frappe.get_doc(self.expenses.EVENT,preview["event_key"])
        self.assertEqual(json.loads(event.provenance_json)["voided_draft"]["journal_entry"],draft["journal_entry"])
        self.assertEqual(frappe.db.get_value(service.PAYMENT,result["payment_id"],"status"),"Reversed")
        self.assertEqual(frappe.db.count("GL Entry"),self.before_gl)
        mapping={"company":self.source.company,"party_type":"Supplier","party":"QA Operating Supplier",
                 "payable_account":"Creditors - QOC","payable_exchange_rate":"1","posting_date":"2026-10-07",
                 "actual_incurred":True,"no_existing_erp_coverage":True,
                 "expense_lines":[{"account":"Administrative Expenses - QOC","source_amount":"100","amount":"100","exchange_rate":"1","cost_center":frappe.db.get_value("Company",self.source.company,"cost_center")}],"payments":{}}
        # Voided payment audit must not lock the first later expense mapping.
        self.expenses.save_mapping(self.source.name,mapping,self.raw["version"])
        self.assertTrue(frappe.db.exists(self.expenses.MAPPING,self.source.name))

    def test_partial_payment_is_idempotent_and_changes_no_posted_finance(self):
        service = self.takeover()
        result = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-first")
        again = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-first")
        self.assertEqual(result["payment_id"], again["payment_id"])
        self.assertEqual(service.payment_detail(self.source)["balance"]["pending_amount"], "50.00")
        self.assertEqual(frappe.db.count(service.PAYMENT, {"source": self.source.name}), 1)
        self.assertEqual(frappe.db.count("GL Entry"), self.before_gl)
        self.assertEqual(frappe.db.count("Payment Entry"), self.before_pe)
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values("21"), self.raw["version"], "qa-first")

    def test_external_draft_dependency_rolls_back_reversal_without_losing_association(self):
        service=self.takeover()
        values={**self.values(),"advance_account":"Creditors - QOC","source_exchange_rate":"1","bank_exchange_rate":"1"}
        result=service.register_payment(self.source.name,values,self.raw["version"],"qa-external-link")
        merged=service.merge_source(self.source,copy.deepcopy(self.raw))
        preview=service.advance_preview(self.source,merged,"erp-payment:"+result["payment_id"])
        with patch.object(self.expenses,"_fresh",return_value=merged):
            draft=self.expenses.create_voucher_draft(self.source.name,preview["fingerprint"],"erp-payment:"+result["payment_id"])
        original=frappe.get_doc(self.expenses.EVENT,preview["event_key"])
        other=frappe.copy_doc(frappe.get_doc("Journal Entry",draft["journal_entry"]))
        other.update({"custom_operating_event_key":None,"custom_operating_source":None,"custom_operating_fingerprint":None,"custom_operating_recognition":draft["journal_entry"]})
        with self.expenses.managed_write():
            other.insert()
        frappe.db.savepoint("external_link")
        with self.assertRaises(frappe.LinkExistsError):
            service.reverse_payment(self.source.name,result["payment_id"],"QA linked draft","qa-external-reverse",discard_drafts=True)
        frappe.db.rollback(save_point="external_link")
        self.assertTrue(frappe.db.exists("Journal Entry",draft["journal_entry"]))
        self.assertEqual(frappe.db.get_value(self.expenses.EVENT,original.name,"journal_entry"),draft["journal_entry"])
        self.assertEqual(frappe.db.get_value(service.PAYMENT,result["payment_id"],"status"),"Registered")
        self.assertEqual(service.payment_detail(self.source)["balance"]["pending_amount"],"50.00")

    def test_overpay_and_stale_facts_are_rejected(self):
        service = self.takeover()
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values("70.01"), self.raw["version"], "qa-over")
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values(), "stale", "qa-stale")

    def test_takeover_transport_version_change_does_not_require_waiting_for_scheduled_sync(self):
        service=self.takeover()
        displayed=self.raw["version"]
        self.source.source_version=displayed
        with self.expenses.managed_write():
            self.source.save(ignore_permissions=True)
        self.raw["version"]="new-transport-version-after-ownership"
        result=service.register_payment(self.source.name,self.values(),displayed,"qa-version-after-claim")
        self.assertEqual(result["balance"]["pending_amount"],"50.00")
        self.assertEqual(frappe.db.get_value(service.PAYMENT,result["payment_id"],"source_version"),self.raw["version"])

    def test_reversal_preserves_record_and_releases_balance_once(self):
        service = self.takeover()
        result = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-first")
        service.reverse_payment(self.source.name, result["payment_id"], "QA wrong entry", "qa-reverse")
        service.reverse_payment(self.source.name, result["payment_id"], "QA wrong entry", "qa-reverse")
        detail = service.payment_detail(self.source)
        self.assertEqual(detail["balance"]["pending_amount"], "70.00")
        self.assertEqual(detail["payments"][0]["status"], "Reversed")
        self.assertEqual(frappe.db.get_value(service.PAYMENT, result["payment_id"], "reversal_reason"), "QA wrong entry")

    def test_direct_managed_record_edits_are_blocked(self):
        service = self.takeover()
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(service.TAKEOVER, self.source.name).save(ignore_permissions=True)

    def test_invisible_local_payment_cannot_inflate_pending_balance(self):
        service=self.takeover()
        service.register_payment(self.source.name,self.values(),self.raw["version"],"qa-first")
        original=frappe.get_list
        def hidden_payments(dt,*args,**kwargs):
            if dt!=service.PAYMENT or kwargs.get("ignore_permissions"):
                return original(dt,*args,**kwargs)
            if not kwargs.get("run",True):
                return original(dt,*args,**{**kwargs,"filters":{"name":"no-visible-qa-payment"}})
            return []
        with patch.object(frappe,"get_list",side_effect=hidden_payments):
            self.assertIsNone(service.payment_detail(self.source)["balance"])
            with self.assertRaises(frappe.ValidationError):
                service.register_payment(self.source.name,self.values(),self.raw["version"],"qa-hidden-second")

    def test_settlement_reuses_registered_bank_amount_and_party_not_editable_mapping(self):
        service=self.takeover()
        result=service.register_payment(self.source.name,self.values(),self.raw["version"],"qa-first")
        mapping={"company":self.source.company,"party_type":"Supplier","party":"QA Operating Supplier","payable_exchange_rate":"1","payments":{"erp-payment:"+result["payment_id"]:{"bank_account":"wrong-bank","bank_amount":"99","bank_exchange_rate":"1","exchange_difference_account":"Exchange Gain/Loss - QOC"}}}
        with patch.object(self.expenses,"_mapping",return_value=mapping):
            actual=service.voucher_mapping(self.source,"erp-payment:"+result["payment_id"])
        self.assertEqual(actual["payments"]["erp-payment:"+result["payment_id"]]["bank_account"],self.bank)
        self.assertEqual(actual["payments"]["erp-payment:"+result["payment_id"]]["bank_amount"],"20.00")
        self.assertEqual(actual["payments"]["erp-payment:"+result["payment_id"]]["exchange_difference_account"],"Exchange Gain/Loss - QOC")
        self.assertEqual(mapping["payments"]["erp-payment:"+result["payment_id"]]["bank_amount"],"99")
        with patch.object(self.expenses,"_mapping",return_value={**mapping,"party":"another-supplier"}):
            with self.assertRaises(frappe.ValidationError):
                service.voucher_mapping(self.source,"erp-payment:"+result["payment_id"])

    def test_source_fact_change_retains_payments_but_blocks_further_registration(self):
        service = self.takeover()
        result = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-first")
        self.raw["amount"] = "101.00"
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-second")
        self.assertTrue(frappe.db.exists(service.PAYMENT, result["payment_id"]))

    def test_changed_source_and_corrupt_history_retain_audit_but_disable_new_payment(self):
        service = self.takeover()
        result = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-first")
        changed = copy.deepcopy(self.raw)
        changed["amount"] = "101"
        self.source.source_json = json.dumps(changed)
        detail = service.payment_detail(self.source)
        self.assertIsNone(detail["balance"])
        self.assertEqual(detail["payments"][0]["name"], result["payment_id"])
        self.assertEqual(service.merge_source(self.source, changed)["pending_amount"], None)
        with self.expenses.managed_write():
            claim=frappe.get_doc(service.TAKEOVER,self.source.name)
            claim.history_json="invalid-json"
            claim.save(ignore_permissions=True)
        detail=service.payment_detail(self.source)
        self.assertIsNone(detail["balance"])
        self.assertEqual(detail["payments"][0]["name"],result["payment_id"])

    def test_other_company_cannot_read_history_payments_or_proofs(self):
        service=self.takeover()
        service.register_payment(self.source.name,self.values(),self.raw["version"],"qa-first")
        email="qa-other-payment-company@example.invalid"
        frappe.flags.mute_emails=True
        frappe.get_doc({"doctype":"User","email":email,"first_name":"QA Other","send_welcome_email":0,"roles":[{"role":"Accounts User"}]}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype":"User Permission","user":email,"allow":"Company","for_value":"QA Operating Mexico","apply_to_all_doctypes":1}).insert(ignore_permissions=True)
        frappe.clear_cache(user=email)
        frappe.set_user(email)
        with self.assertRaises(frappe.PermissionError):
            self.expenses.get_operating_expense_detail(self.source.name)
        rows=self.expenses.get_operating_expenses()["rows"]
        self.assertTrue(all(row["company"]=="QA Operating Mexico" for row in rows))
