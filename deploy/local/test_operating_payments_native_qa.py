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

    def oa_source(self, *, cashier_root=None):
        from deeplinkerp_branding.services.operating_expense_contract import digest
        identity = {"corp_id": "qa-corp", "process_instance_id": "qa-instance"}
        self.raw.update(source_system="dingtalk-oa", source_id="oa:" + digest(list(identity.values())),
                        oa_identity=identity, applicant_user_id="qa-originator", cashier_source_id=cashier_root,
                        paid_amount=None, pending_amount=None, payments=[], payment_evidence_status="unknown",
                        approvals={"eligibility": "blocked", "raw": {"status": "RUNNING", "result": "NONE"}},
                        payment_eligibility={"can_register_payment": True, "reason": "", "notice": "QA verified cashier execution",
                                             "policy_version": "qa-policy-1", "evidence_fingerprint": digest([identity, "cashier"])})
        self.raw.update(identity)
        self.source = frappe.get_doc({**self.source.as_dict(), "name": self.raw["source_id"],
                                     "source_system": "dingtalk-oa", "source_id": self.raw["source_id"],
                                     "source_version": self.raw["version"], "source_json": json.dumps(self.raw)})
        with self.expenses.managed_write():
            self.source.insert(ignore_permissions=True)
        history = copy.deepcopy(self.raw)
        history.update(version="qa-history-version", source_request_id=cashier_root, paid_amount="0.00", pending_amount="100.00",
                       payment_evidence_status="recorded", source_status="未付款",
                       zero_history_attestation={"method": "explicit_erp_finance_confirmation", "confirmed_by": "Administrator", "verified_zero": True},
                       takeover={"owner": "deeplinkerp", "claim_token": "qa-oa-token", "history_fingerprint": digest(identity)})
        return history

    def claim_oa(self, service, history):
        with patch.object(self.expenses, "_request", return_value={"schema_version": 2, "source_system": "cashier-payment-archive", "items": [history]}):
            return service.claim_takeover(self.source.name, self.raw["version"], history["version"], "qa-oa-claim",
                                          zero_history_confirmed=True,
                                          expected_eligibility_fingerprint=self.raw["payment_eligibility"]["evidence_fingerprint"])

    def test_oa_only_requires_explicit_zero_history_confirmation(self):
        self.oa_source()
        service = self.service()
        detail = service.payment_detail(self.source)
        self.assertTrue(detail["needs_zero_history_confirmation"])
        with patch.object(self.expenses, "_request") as request, self.assertRaises(frappe.ValidationError):
            service.preview_takeover(self.source.name)
        request.assert_not_called()
        self.raw["payments"] = [{"source_id": "history-1", "amount": "30", "currency": "CNY", "payment_date": "2026-10-02", "evidence_status": "recorded"}]
        self.source.source_json = json.dumps(self.raw)
        self.assertFalse(service.payment_detail(self.source)["needs_zero_history_confirmation"])

    def test_oa_only_claim_partial_payments_survive_cashier_workflow_completion(self):
        from deeplinkerp_branding.services.operating_expense_contract import digest, payment_intent_facts
        history = self.oa_source()
        service = self.service()
        response = {"schema_version": 2, "source_system": "cashier-payment-archive", "items": [history]}
        with patch.object(self.expenses, "_request", return_value=response) as request:
            preview = service.preview_takeover(self.source.name, zero_history_confirmed=True)
            self.assertEqual(preview["payment_eligibility"], self.raw["payment_eligibility"])
            self.assertEqual(preview["eligibility_fingerprint"], self.raw["payment_eligibility"]["evidence_fingerprint"])
            payload = request.call_args.kwargs["data"]
            self.assertEqual(payload["source_id"], self.raw["source_id"])
            self.assertEqual(payload["corp_id"], "qa-corp")
            self.assertEqual(payload["process_instance_id"], "qa-instance")
            self.assertEqual(payload["confirmed_by"], "Administrator")
        self.claim_oa(service, history)
        self.assertEqual(frappe.db.get_value(service.TAKEOVER, self.source.name, "expense_fingerprint"), digest(payment_intent_facts(self.raw)))
        first = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-oa-first")
        displayed = self.raw["version"]
        self.raw.update(version="qa-workflow-completed", approvals={"eligibility": "eligible", "raw": {"status": "COMPLETED", "result": "agree"}})
        self.raw["payment_eligibility"]["evidence_fingerprint"] = digest(["completed"])
        second = service.register_payment(self.source.name, self.values("25"), displayed, "qa-oa-second")
        self.assertNotEqual(first["payment_id"], second["payment_id"])
        self.assertEqual(second["balance"]["paid_amount"], "45.00")
        self.assertEqual(second["balance"]["pending_amount"], "55.00")
        self.assertEqual(frappe.db.count("GL Entry"), self.before_gl)
        self.assertEqual(frappe.db.count("Payment Entry"), self.before_pe)

    def test_oa_history_retains_numeric_cashier_root_with_exact_oa_identity(self):
        history = self.oa_source(cashier_root="1001")
        history.update(payments=[{"source_id": "history-1", "amount": "30.00", "currency": "CNY", "payment_date": "2026-10-02", "evidence_status": "recorded"}],
                       paid_amount="30.00", pending_amount="70.00", source_status="部分付款")
        history.pop("zero_history_attestation")
        with patch.object(self.expenses, "_request", return_value={"schema_version": 2, "source_system": "cashier-payment-archive", "items": [history]}) as request:
            self.service().preview_takeover(self.source.name)
        self.assertEqual(request.call_args.kwargs["data"]["source_id"], "1001")
        self.assertEqual(request.call_args.kwargs["data"]["corp_id"], "qa-corp")

    def test_oa_preview_rejects_cross_instance_schema_or_cashier_history_binding(self):
        history = self.oa_source(cashier_root="1001")
        for field, value in (("source_id", "oa:" + "0" * 64), ("oa_identity", {"corp_id": "other-corp", "process_instance_id": "qa-instance"}), ("source_request_id", "1002")):
            wrong = {**history, field: value}
            with self.subTest(field=field), patch.object(self.expenses, "_request", return_value={"schema_version": 2, "source_system": "cashier-payment-archive", "items": [wrong]}), self.assertRaises(frappe.ValidationError):
                self.service().preview_takeover(self.source.name, zero_history_confirmed=True)
        with patch.object(self.expenses, "_request", return_value={"schema_version": 1, "source_system": "cashier-payment-archive", "items": [history]}), self.assertRaises(frappe.ValidationError):
            self.service().preview_takeover(self.source.name, zero_history_confirmed=True)

    def test_oa_claim_rejects_missing_stale_or_invalid_eligibility_fingerprint_before_request(self):
        history = self.oa_source()
        service = self.service()
        for fingerprint in (None, "wrong", "0" * 64):
            with self.subTest(fingerprint=fingerprint), patch.object(self.expenses, "_request") as request, self.assertRaises(frappe.ValidationError):
                service.claim_takeover(self.source.name, self.raw["version"], history["version"], "qa-stale-policy",
                                       zero_history_confirmed=True, expected_eligibility_fingerprint=fingerprint)
            request.assert_not_called()
        self.assertFalse(frappe.db.exists(service.TAKEOVER, self.source.name))
        with patch.object(self.expenses, "_request") as request, self.assertRaises(frappe.ValidationError):
            service.claim_takeover(self.source.name, "stale-source-version", history["version"], "qa-stale-source",
                                   zero_history_confirmed=True,
                                   expected_eligibility_fingerprint=self.raw["payment_eligibility"]["evidence_fingerprint"])
        request.assert_not_called()

    def test_oa_rejected_unknown_policy_or_changed_identity_blocks_new_payment(self):
        history = self.oa_source()
        service = self.service()
        self.claim_oa(service, history)
        allowed = copy.deepcopy(self.raw["payment_eligibility"])
        for decision in (None, {**allowed, "can_register_payment": False, "reason": "QA rejected"}):
            self.raw["payment_eligibility"] = decision
            with self.subTest(decision=decision), self.assertRaises(frappe.ValidationError):
                service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-rejected")
        self.raw["payment_eligibility"] = allowed
        self.raw["oa_identity"]["process_instance_id"] = "qa-other-instance"
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-wrong-identity")
        self.assertEqual(frappe.db.count(service.PAYMENT, {"source": self.source.name}), 0)

    def test_oa_changed_financial_facts_and_old_strict_claims_are_not_rebound(self):
        history = self.oa_source()
        service = self.service()
        self.claim_oa(service, history)
        service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-oa-existing")
        self.raw["payee_name"] = "Different payee"
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-changed-payee")
        self.assertEqual(len(service.payment_detail(self.source)["payments"]), 1)
        from deeplinkerp_branding.services.operating_expense_contract import digest, expense_facts
        original = json.loads(self.source.source_json)
        frappe.db.set_value(service.TAKEOVER, self.source.name, "expense_fingerprint", digest(expense_facts(original)))
        self.raw.clear(); self.raw.update(original)
        self.raw["approvals"] = {"eligibility": "eligible", "raw": {"status": "COMPLETED", "result": "agree"}}
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-old-claim-changed")

    def test_oa_workflow_without_cashier_root_preserves_event_order_and_current_tasks(self):
        self.oa_source()
        row = {"source_id": self.raw["source_id"], **self.raw["oa_identity"], "oa_identity": self.raw["oa_identity"],
               "lookup_status": "found", "approval_status": "RUNNING", "approval_result": "NONE", "originator": {"id": "qa-originator", "name": "QA Applicant"},
               "events": [{"id": "second", "stage": "会计", "time": "2026-10-02", "private_raw": "omit"}, {"id": "first", "stage": "主管", "time": "2026-10-01"}],
               "current_tasks": [{"id": "qa-task", "activity_id": "qa-node", "stage": "出纳", "entered_at": "2026-10-03", "status": "RUNNING", "assignees": [{"id": "qa-cashier", "name": "QA Cashier"}]}],
               "source_updated_at": "2026-10-03", "last_synced_at": "2026-10-04", "original_url": "https://aflow.dingtalk.com/qa",
               "payment_eligibility": self.raw["payment_eligibility"], "private_payload": "omit"}
        with patch.object(self.expenses, "_request", return_value={"schema_version": 2, "source_system": "cashier-payment-archive", "items": [row]}) as request:
            timeline = self.service().get_approval_timeline(self.source.name)
        self.assertEqual(request.call_args.kwargs["params"], {"source_id": self.raw["source_id"], **self.raw["oa_identity"]})
        self.assertEqual([event["id"] for event in timeline["events"]], ["second", "first"])
        self.assertEqual(timeline["current_tasks"], row["current_tasks"])
        self.assertEqual(timeline["originator"], row["originator"])
        self.assertEqual(timeline["payment_eligibility"], row["payment_eligibility"])
        self.assertNotIn("private_payload", timeline)
        self.assertNotIn("private_raw", timeline["events"][0])
        row["corp_id"] = "qa-other-corp"
        with patch.object(self.expenses, "_request", return_value={"schema_version": 2, "source_system": "cashier-payment-archive", "items": [row]}), self.assertRaises(frappe.ValidationError):
            self.service().get_approval_timeline(self.source.name)

    def test_persisted_oa_alias_can_read_workflow_when_cashier_root_is_missing_but_cannot_claim_zero(self):
        history = self.oa_source()
        canonical = self.raw["source_id"]
        self.raw["source_id"] = "qa-stable-oa-alias"
        self.source = frappe.get_doc({**self.source.as_dict(), "name": self.raw["source_id"], "source_id": self.raw["source_id"], "source_json": json.dumps(self.raw)})
        with self.expenses.managed_write():
            self.source.insert(ignore_permissions=True)
        row = {"source_id": canonical, **self.raw["oa_identity"], "oa_identity": self.raw["oa_identity"],
               "lookup_status": "found", "events": [], "current_tasks": []}
        service = self.service()
        with patch.object(self.expenses, "_request", return_value={"schema_version": 2, "source_system": "cashier-payment-archive", "items": [row]}) as request:
            timeline = service.get_approval_timeline(self.source.name)
        self.assertEqual(timeline["lookup_status"], "found")
        self.assertEqual(request.call_args.kwargs["params"]["source_id"], canonical)
        self.assertEqual(service._fresh_base(self.source)["oa_identity"], self.raw["oa_identity"])
        with patch.object(self.expenses, "_request") as request, self.assertRaises(frappe.ValidationError):
            service.preview_takeover(self.source.name, zero_history_confirmed=True)
        request.assert_not_called()
        with self.assertRaises(frappe.ValidationError):
            service._oa_identity({**history, "source_id": "qa-unpersisted-alias"}, self.source)

    def test_payment_account_choices_use_one_permission_scoped_query_without_per_account_reads(self):
        service = self.service()
        with patch.object(self.expenses, "_account", side_effect=AssertionError("Account choices must not issue per-account reads")):
            choices = service.get_payment_accounts(self.source.name)
        self.assertTrue(choices)
        self.assertIn(self.bank, {choice["name"] for choice in choices})

    def test_payment_account_choices_are_company_native_readable_and_friendly(self):
        service = self.service()
        choices = service.get_payment_accounts(self.source.name)
        self.assertTrue(choices)
        for choice in choices:
            account = frappe.get_doc("Account", choice["name"])
            self.assertEqual(set(choice), {"name", "label", "currency"})
            self.assertEqual(account.company, self.source.company)
            self.assertEqual(choice["label"], account.account_name)
            self.assertIn(account.account_type, {"Bank", "Cash"})
            self.assertFalse(account.is_group or account.disabled)
        other = frappe.get_doc({**self.source.as_dict(), "name": "qa-native-mexico", "source_id": "qa-native-mexico", "company": "QA Operating Mexico"})
        with self.expenses.managed_write():
            other.insert(ignore_permissions=True)
        frappe.set_user("operating-browser-china@example.invalid")
        self.assertTrue(service.get_payment_accounts(self.source.name))
        self.assertNotEqual(other.company, self.source.company)
        with self.assertRaises(frappe.PermissionError):
            service.get_payment_accounts(other.name)

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

    def test_post_write_balance_failure_rejects_and_rolls_back_each_financial_operation(self):
        service = self.service()
        real_balance = service.balance
        history = {**copy.deepcopy(self.raw), "takeover": {"owner": "deeplinkerp", "claim_token": "qa-claim", "history_fingerprint": "qa-history"}}
        for operation in ("claim", "register", "reverse"):
            with self.subTest(operation=operation):
                frappe.db.savepoint("operation_fixture")
                payment_id = None
                try:
                    if operation != "claim":
                        self.takeover()
                    if operation == "reverse":
                        payment_id = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-check-first")["payment_id"]
                    before = service.payment_detail(self.source)
                    frappe.db.savepoint("financial_write")
                    def fail_after_write(frozen, records):
                        written = (bool(frappe.db.exists(service.TAKEOVER, self.source.name)) if operation == "claim"
                                   else any(row["status"] == ("Reversed" if operation == "reverse" else "Registered") for row in records))
                        if written:
                            raise ValueError("QA post-write balance failure")
                        return real_balance(frozen, records)
                    with patch.object(service, "balance", side_effect=fail_after_write), patch.object(self.expenses, "_request", return_value={"schema_version": 1, "items": [history]}):
                        with self.assertRaisesRegex(frappe.ValidationError, "QA post-write balance failure"):
                            if operation == "claim":
                                service.claim_takeover(self.source.name, self.raw["version"], history["version"], "qa-check-claim")
                            elif operation == "register":
                                service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-check-register")
                            else:
                                service.reverse_payment(self.source.name, payment_id, "QA rollback", "qa-check-reverse")
                    # Same rollback boundary as an unsuccessful Frappe POST.
                    frappe.db.rollback(save_point="financial_write")
                    after = service.payment_detail(self.source)
                    self.assertEqual(after["balance"], before["balance"])
                    self.assertEqual([(row["name"], row["status"]) for row in after["payments"]], [(row["name"], row["status"]) for row in before["payments"]])
                    self.assertEqual(after["managed"], before["managed"])
                finally:
                    frappe.db.rollback(save_point="operation_fixture")
        self.assertEqual((frappe.db.count("GL Entry"), frappe.db.count("Payment Entry")), (self.before_gl, self.before_pe))

    def test_native_insert_hook_cannot_change_registered_financial_facts(self):
        from frappe.model.document import Document
        service = self.takeover()
        original = Document.run_method
        for field, value in (("amount", "21.00"), ("status", "Reversed"), ("bank_account", "wrong-bank"), ("source", "1001")):
            with self.subTest(field=field):
                frappe.db.savepoint("payment_hook")
                def changed(document, method, *args, **kwargs):
                    result = original(document, method, *args, **kwargs)
                    if document.doctype == service.PAYMENT and method == "after_insert":
                        frappe.db.set_value(service.PAYMENT, document.name, field, value, update_modified=False)
                    return result
                try:
                    with patch.object(Document, "run_method", new=changed), self.assertRaises(frappe.ValidationError):
                        service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-hook-payment")
                finally:
                    frappe.db.rollback(save_point="payment_hook")
                self.assertEqual(frappe.db.count(service.PAYMENT, {"source": self.source.name}), 0)
                self.assertEqual(service.payment_detail(self.source)["balance"]["pending_amount"], "70.00")

    def test_idempotent_returns_still_reject_corrupt_history_and_changed_payment(self):
        service = self.takeover()
        result = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-idempotent-check")
        frappe.db.set_value(service.PAYMENT, result["payment_id"], "amount", "21.00", update_modified=False)
        with self.assertRaises(frappe.ValidationError):
            service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-idempotent-check")
        frappe.db.set_value(service.PAYMENT, result["payment_id"], "amount", "20.00", update_modified=False)
        service.reverse_payment(self.source.name, result["payment_id"], "QA reversed", "qa-idempotent-reverse")
        frappe.db.set_value(service.TAKEOVER, self.source.name, "history_json", "invalid-json", update_modified=False)
        for operation in ("claim", "register", "reverse"):
            with self.subTest(operation=operation), self.assertRaises(frappe.ValidationError):
                if operation == "claim":
                    service.claim_takeover(self.source.name, self.raw["version"], "ignored-existing", "qa-idempotent-claim")
                elif operation == "register":
                    service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-idempotent-check")
                else:
                    service.reverse_payment(self.source.name, result["payment_id"], "QA reversed", "qa-idempotent-reverse")
        self.assertEqual(frappe.db.get_value(service.PAYMENT, result["payment_id"], "status"), "Reversed")

    def test_reversal_can_correct_registered_fact_after_source_changes_without_hiding_notice(self):
        service = self.takeover()
        result = service.register_payment(self.source.name, self.values(), self.raw["version"], "qa-changed-reversal")
        changed = {**self.raw, "amount": "101.00", "approvals": {"eligibility": "blocked", "raw": {"status": "COMPLETED", "result": "refuse"}}}
        frappe.db.set_value(self.expenses.SOURCE, self.source.name, "source_json", json.dumps(changed), update_modified=False)
        detail = service.reverse_payment(self.source.name, result["payment_id"], "QA fact correction", "qa-changed-reverse")
        self.assertEqual(frappe.db.get_value(service.PAYMENT, result["payment_id"], "status"), "Reversed")
        self.assertIsNone(detail["balance"])
        self.assertIn("财务事实已变化", detail["notice"])

    def test_takeover_retry_after_local_postcheck_failure_keeps_same_upstream_claim_identity(self):
        history = self.oa_source()
        service = self.service()
        real_balance = service.balance
        response = {"schema_version": 2, "source_system": "cashier-payment-archive", "items": [history]}
        frappe.db.savepoint("claim_retry")
        def failed_local_result(frozen, records):
            if frappe.db.exists(service.TAKEOVER, self.source.name):
                raise ValueError("QA local claim postcheck failed")
            return real_balance(frozen, records)
        with patch.object(self.expenses, "_request", return_value=response) as request:
            with patch.object(service, "balance", side_effect=failed_local_result), self.assertRaises(frappe.ValidationError):
                service.claim_takeover(self.source.name, self.raw["version"], history["version"], "qa-failed-attempt", zero_history_confirmed=True, expected_eligibility_fingerprint=self.raw["payment_eligibility"]["evidence_fingerprint"])
            # Upstream remains frozen after a local rollback, never auto-unlocked.
            frappe.db.rollback(save_point="claim_retry")
            first = service.claim_takeover(self.source.name, self.raw["version"], history["version"], "qa-retry-one", zero_history_confirmed=True, expected_eligibility_fingerprint=self.raw["payment_eligibility"]["evidence_fingerprint"])
            again = service.claim_takeover(self.source.name, self.raw["version"], history["version"], "qa-retry-two", zero_history_confirmed=True, expected_eligibility_fingerprint=self.raw["payment_eligibility"]["evidence_fingerprint"])
        self.assertTrue(first["managed"])
        self.assertTrue(again["existing"])
        self.assertEqual(frappe.db.count(service.TAKEOVER, {"source": self.source.name}), 1)
        self.assertEqual(len(request.call_args_list), 2)
        self.assertEqual({call.args[0] for call in request.call_args_list}, {service.CLAIM_PATH + "takeover-claim"})
        self.assertEqual(request.call_args_list[0].kwargs["data"]["request_id"], request.call_args_list[1].kwargs["data"]["request_id"])

    def test_financial_audit_logs_ids_amounts_and_result_without_payment_private_text(self):
        service = self.takeover()
        values = {**self.values(), "remark": "private-person-name", "bank_reference": "private-bank-reference"}
        with patch.object(frappe, "logger") as logger:
            result = service.register_payment(self.source.name, values, self.raw["version"], "qa-audit-safe")
            service.reverse_payment(self.source.name, result["payment_id"], "private-reversal-note", "qa-audit-reverse")
            real_balance = service.balance
            def failed_result(history, records):
                if len(records) > 1:
                    raise ValueError("private-error-person-bank-form-secret")
                return real_balance(history, records)
            frappe.db.savepoint("audit_failure")
            try:
                with patch.object(service, "balance", side_effect=failed_result), self.assertRaises(frappe.ValidationError):
                    service.register_payment(self.source.name, values, self.raw["version"], "qa-audit-failed")
            finally:
                frappe.db.rollback(save_point="audit_failure")
            service.reverse_payment(self.source.name, result["payment_id"], "private-reversal-note", "qa-audit-reverse")
        logs = [call.args[0] for call in logger.return_value.info.call_args_list if call.args and isinstance(call.args[0], dict)]
        self.assertTrue(logs)
        self.assertIn({"operation": "register", "source": self.source.name, "document": result["payment_id"], "amount": "20.00", "result": "validated"}, logs)
        self.assertEqual(logs.count({"operation": "reverse", "source": self.source.name, "document": result["payment_id"], "amount": "20.00", "result": "validated"}), 2)
        rejected = next(row for row in logs if row["result"] == "rejected")
        self.assertEqual({key: rejected.get(key) for key in ("error_type", "error_code", "stage")},
                         {"error_type": "ValidationError", "error_code": "financial_postcondition_failed", "stage": "payment_context"})
        serialized = json.dumps(logs)
        for private in (values["remark"], values["bank_reference"], values["party"], values["bank_account"], "private-reversal-note", "private-error-person-bank-form-secret"):
            self.assertNotIn(private, serialized)

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

    def test_reversal_rejects_inconsistent_events_and_native_hooks_without_losing_draft(self):
        from frappe.model.document import Document
        service = self.takeover()
        values = {**self.values(), "advance_account": "Creditors - QOC", "source_exchange_rate": "1", "bank_exchange_rate": "1"}
        result = service.register_payment(self.source.name, values, self.raw["version"], "qa-reversal-postcheck")
        merged = service.merge_source(self.source, copy.deepcopy(self.raw))
        preview = service.advance_preview(self.source, merged, "erp-payment:" + result["payment_id"])
        with patch.object(self.expenses, "_fresh", return_value=merged):
            draft = self.expenses.create_voucher_draft(self.source.name, preview["fingerprint"], "erp-payment:" + result["payment_id"])
        initial = frappe.get_doc(self.expenses.EVENT, preview["event_key"])
        original = Document.run_method
        changes = {"source": "1001", "company": "wrong-company", "operation": "expense", "payment_source_id": "other-payment"}
        for scenario in [*changes, "relink_after_delete", "restore_native_after_delete", "delete_event_after_delete", "missing_voided_docstatus"]:
            with self.subTest(scenario=scenario):
                frappe.db.savepoint("reverse_association")
                try:
                    if scenario in changes:
                        frappe.db.set_value(self.expenses.EVENT, initial.name, scenario, changes[scenario], update_modified=False)
                    def inconsistent(doc, method, *args, **kwargs):
                        value = original(doc, method, *args, **kwargs)
                        if doc.doctype == "Journal Entry" and doc.name == draft["journal_entry"] and method == "after_delete":
                            if scenario == "relink_after_delete":
                                frappe.db.set_value(self.expenses.EVENT, initial.name, "journal_entry", doc.name, update_modified=False)
                            elif scenario == "restore_native_after_delete":
                                doc.db_insert()
                                for child in doc.get_all_children():
                                    child.db_insert()
                            elif scenario == "delete_event_after_delete":
                                frappe.db.delete(self.expenses.EVENT, {"name": initial.name})
                            elif scenario == "missing_voided_docstatus":
                                provenance = json.loads(frappe.db.get_value(self.expenses.EVENT, initial.name, "provenance_json"))
                                del provenance["voided_draft"]["document"]["docstatus"]
                                frappe.db.set_value(self.expenses.EVENT, initial.name, "provenance_json", json.dumps(provenance), update_modified=False)
                        return value
                    with patch.object(Document, "run_method", new=inconsistent), self.assertRaises(frappe.ValidationError):
                        service.reverse_payment(self.source.name, result["payment_id"], "QA hook rollback", "qa-postcheck-reverse", discard_drafts=True)
                finally:
                    frappe.db.rollback(save_point="reverse_association")
                restored = frappe.get_doc(self.expenses.EVENT, initial.name)
                self.assertEqual((restored.source, restored.company, restored.operation, restored.payment_source_id, restored.journal_entry, restored.provenance_json),
                                 (initial.source, initial.company, initial.operation, initial.payment_source_id, initial.journal_entry, initial.provenance_json))
                self.assertEqual(frappe.db.get_value(service.PAYMENT, result["payment_id"], "status"), "Registered")
                self.assertEqual(frappe.db.get_value("Journal Entry", draft["journal_entry"], "docstatus"), 0)
                self.assertEqual(service.payment_detail(self.source)["balance"]["pending_amount"], "50.00")
        service.reverse_payment(self.source.name, result["payment_id"], "QA hook rollback", "qa-postcheck-reverse", discard_drafts=True)
        for field, value in changes.items():
            with self.subTest(idempotent_field=field):
                frappe.db.savepoint("reverse_idempotent")
                try:
                    frappe.db.set_value(self.expenses.EVENT, initial.name, field, value, update_modified=False)
                    with self.assertRaises(frappe.ValidationError):
                        service.reverse_payment(self.source.name, result["payment_id"], "QA hook rollback", "qa-postcheck-reverse", discard_drafts=True)
                finally:
                    frappe.db.rollback(save_point="reverse_idempotent")
        self.assertEqual((frappe.db.count("GL Entry"), frappe.db.count("Payment Entry")), (self.before_gl, self.before_pe))

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
