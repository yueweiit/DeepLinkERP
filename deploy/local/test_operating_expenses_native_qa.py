"""Dedicated-site native integration checks. Every transaction is rolled back."""
import json
import unittest
import frappe
from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile
from decimal import Decimal


WORKFLOW_PATH = "/api/integrations/erp/operating-expenses/workflow"


def workflow_fixture(row, *, originator=None, current_tasks=None, can_register_payment=True):
    """One schema-2 authoritative workflow for the exact original OA identity."""
    from deeplinkerp_branding.services import operating_oa_source as oa
    from deeplinkerp_branding.services.operating_expense_contract import digest
    originator = originator or {"id": "u1", "name": "Alice"}
    tasks = current_tasks or []
    evidence = {"source_id": oa.application_id(row), "corp_id": row["corp_id"],
        "process_instance_id": row["process_instance_id"], "lookup_status": "found",
        "approval_status": row["status"], "approval_result": row["result"],
        "originator": originator, "current_tasks": tasks,
        "source_updated_at": "2026-10-07T01:00:00Z", "last_synced_at": "2026-10-07T01:02:00Z",
        "original_url": "https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm?procInstId=" + row["process_instance_id"],
        "events": [{"id": "submit", "stage": "发起申请", "operator": originator["name"],
                    "time": "2026-01-01T00:00:00Z", "result": "NONE"},
                   {"id": "business", "stage": "业务审批", "operator": "QA Approver",
                    "time": "2026-01-01T01:00:00Z", "result": "AGREE"}]}
    evidence["payment_eligibility"] = {"can_register_payment": can_register_payment,
        "reason": "business_approved_cashier_executing" if can_register_payment else "business_approval_pending",
        "notice": "业务审批已完成，出纳执行中" if tasks and can_register_payment else "",
        "policy_version": "operating-payment-eligibility-v1", "evidence_fingerprint": digest(evidence)}
    return evidence


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

    def setUp(self):
        # Preserve the committed browser takeover/payments, but isolate this
        # pre-takeover regression suite inside its rolled-back transaction.
        for dt in ("Operating Expense Payment","Operating Expense Takeover"):
            if frappe.db.exists("DocType",dt):
                rows=frappe.get_all(dt,filters={"source":["in",["1001","1002"]]},fields=["name","company"])
                if any(row.company not in {"QA Operating China","QA Operating Mexico"} for row in rows):
                    raise RuntimeError("Unexpected QA company; do not isolate")
                if rows:
                    frappe.db.delete(dt,{"name":["in",[row.name for row in rows]]})
        frappe.db.set_single_value("Operating Expense Sync Settings","enabled",0)
        # The browser demo contains draft fixtures. Remove only their associations
        # inside each rolled-back test transaction, so every case has a clean start.
        events = frappe.get_all("Operating Expense Event", fields=["name", "source", "journal_entry"], limit_page_length=0)
        if events:
            if any(e.source not in {"1001", "1002"} for e in events):
                raise RuntimeError("Unexpected QA finance activity; do not isolate")
            journals = frappe.get_all("Journal Entry", filters={"name": ["in", [e.journal_entry for e in events]]}, fields=["name", "docstatus", "custom_operating_source", "custom_operating_event_key"], limit_page_length=0)
            if len(journals) != len(events) or any(j.docstatus != 0 or j.custom_operating_source not in {"1001", "1002"} for j in journals):
                raise RuntimeError("Unexpected QA journals; do not isolate")
            frappe.db.delete("Operating Expense Event", {"name": ["in", [e.name for e in events]]})
            frappe.db.delete("Operating Expense Mapping", {"source": ["in", [e.source for e in events]]})
            for journal in journals:
                if journal.custom_operating_event_key not in {e.name for e in events}:
                    raise RuntimeError("Unexpected QA journal event identity")
                frappe.db.set_value("Journal Entry", journal.name, "custom_operating_event_key", None, update_modified=False)

    def test_oa_provider_reuses_company_resolution_and_does_not_invent_unpaid(self):
        from deeplinkerp_branding.services import operating_expenses as service
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        self.assertTrue(hasattr(service, "_source_page"), "Unified source-page dispatcher missing")
        responses = {
            "/api/integrations/erp/operating-expenses": {"items": [], "end": True},
            "/api/integrations/erp/resolve-applicant-companies": {"items": [{"corp_id":"corp", "user_id": "u1", "employee_name": "Alice", "status": "matched", "assigned_department": "拉丁购"}]},
            WORKFLOW_PATH: {"schema_version": 2, "items": [workflow_fixture(approval())]},
        }
        with patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([approval()], None)), patch.object(service, "_request", side_effect=lambda path, *a, **k: responses[path]):
            result = service._source_page({"limit": 100})
        self.assertEqual(result["items"][0]["source_company"], "拉丁购")
        self.assertIsNone(result["items"][0]["paid_amount"])
        self.assertEqual(result["items"][0]["source_status"], "付款待核对")

    def test_cached_oa_root_survives_missing_ambiguous_and_new_cashier_matches(self):
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        service = self._sync()
        row = approval()
        cashier = {"source_id": "legacy-root", "corp_id": row["corp_id"], "process_instance_id": row["process_instance_id"], "amount": "100", "currency": "CNY",
                   "paid_amount": "0", "pending_amount": "100", "source_status": "未付款", "payment_evidence_status": "recorded", "payments": [], "attachments": []}
        resolution = {"corp_id":row["corp_id"], "user_id": "u1", "employee_name": "Alice", "status": "matched", "assigned_department": "QA Operating China"}
        item = oa.merge_application(row, [cashier], resolution)
        item["source_id"] = cashier["source_id"]
        service._upsert(item, service._maps(service._settings()))
        new_cashier_cache = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        new_cashier_cache["source_id"] = "new-root"
        service._upsert(new_cashier_cache, service._maps(service._settings()))
        responses = {"/api/integrations/erp/operating-expenses": {"items": [cashier], "end": True},
                     "/api/integrations/erp/resolve-applicant-companies": {"items": [resolution]},
                     WORKFLOW_PATH: {"schema_version": 2, "items": [workflow_fixture(row)]}}
        with patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([row], None)), patch.object(service, "_request", side_effect=lambda path, *a, **k: responses[path]):
            service.save_mapping("legacy-root", self._mapping(), service._fresh(service._source("legacy-root"))["version"])
            preview = service.preview_voucher("legacy-root")
            draft = service.create_voucher_draft("legacy-root", preview["fingerprint"])
            mapping_before = frappe.get_doc(service.MAPPING, "legacy-root").mapping_json
            events_before = frappe.get_all(service.EVENT, filters={"source": "legacy-root"}, fields=["name", "source", "journal_entry", "fingerprint"])
            for candidates in ([], [cashier, {**cashier, "source_id": "new-root"}], [{**cashier, "source_id": "new-root"}]):
                with self.subTest(cashier_roots=[c["source_id"] for c in candidates]):
                    responses["/api/integrations/erp/operating-expenses"]["items"] = candidates
                    fresh = service._fresh(service._source("legacy-root"))
                    current = service._source_page({"limit": 100})["items"][0]
                    self.assertEqual(current["source_id"], "legacy-root")
                    self.assertEqual(fresh["source_id"], current["source_id"])
                    if len(candidates) != 1:
                        self.assertIsNone(current["paid_amount"])
                        self.assertIsNone(current["pending_amount"])
                        self.assertEqual(current["payment_evidence_status"], "unknown")
                    service._upsert(current, service._maps(service._settings()))
                    self.assertEqual(frappe.get_doc(service.MAPPING, "legacy-root").mapping_json, mapping_before)
                    self.assertEqual(frappe.get_all(service.EVENT, filters={"source": "legacy-root"}, fields=["name", "source", "journal_entry", "fingerprint"]), events_before)
                    self.assertEqual(frappe.get_doc("Journal Entry", draft["journal_entry"]).docstatus, 0)
                    cached = frappe.get_all(service.SOURCE, filters={"source_system": oa.SOURCE_SYSTEM}, fields=["name", "source_json"])
                    self.assertEqual([d.name for d in cached if json.loads(d.source_json)["oa_identity"] == item["oa_identity"]], ["legacy-root"])

    def test_oa_identity_collision_and_duplicate_cache_fail_closed(self):
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        service = self._sync()
        row = approval()
        other = approval(); other["process_instance_id"] = "other-instance"
        resolution = {"corp_id":row["corp_id"], "user_id": "u1", "employee_name": "Alice", "status": "matched", "assigned_department": "QA Operating China"}
        occupied = oa.merge_application(other, [], resolution)
        occupied["source_id"] = "legacy-root"
        service._upsert(occupied, service._maps(service._settings()))
        responses = {"/api/integrations/erp/operating-expenses": {"items": [{"source_id": "legacy-root", "corp_id": row["corp_id"], "process_instance_id": row["process_instance_id"], "amount": "100", "currency": "CNY"}], "end": True},
                     "/api/integrations/erp/resolve-applicant-companies": {"items": [resolution]},
                     WORKFLOW_PATH: {"schema_version": 2, "items": [workflow_fixture(row)]}}
        with patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([row], None)), patch.object(service, "_request", side_effect=lambda path, *a, **k: responses[path]):
            with self.subTest(case="different_cached_identity"):
                current = service._source_page({"limit": 100})["items"][0]
                self.assertEqual(current["source_id"], oa.application_id(row))
                self.assertEqual(json.loads(frappe.get_doc(service.SOURCE, "legacy-root").source_json)["oa_identity"], occupied["oa_identity"])
            collision = {**occupied, "source_id": oa.application_id(row), "oa_identity": {"corp_id": "other-corp", "process_instance_id": "other-instance"}}
            service._upsert(collision, service._maps(service._settings()))
            responses["/api/integrations/erp/operating-expenses"]["items"][0]["source_id"] = collision["source_id"]
            with self.subTest(case="generated_root_collision"), self.assertRaisesRegex(frappe.ValidationError, "身份不符"):
                service._source_page({"limit": 100})
            current = oa.merge_application(row, [], resolution)
            service._upsert(current, service._maps(service._settings()))
            duplicate = {**current, "source_id": "duplicate-root"}
            service._upsert(duplicate, service._maps(service._settings()))
            with self.subTest(case="duplicate_page"), self.assertRaisesRegex(frappe.ValidationError, "身份重复"):
                service._source_page({"limit": 100})
            for name in (current["source_id"], "duplicate-root"):
                with self.subTest(source=name), self.assertRaisesRegex(frappe.ValidationError, "身份重复"):
                    service._fresh(service._source(name))

    def test_oa_cache_identity_lookup_has_a_bounded_limit(self):
        from deeplinkerp_branding.services import operating_expenses as service
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        with patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(frappe, "get_all", return_value=[None] * 20001), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([], None)), patch.object(service, "_cashier_snapshot", return_value=[]):
            with self.assertRaisesRegex(frappe.ValidationError, "上限"):
                service._source_page({"limit": 100})

    def test_legacy_cashier_identity_conflicts_block_migration_and_preserve_links(self):
        from copy import deepcopy
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        service = self._sync()
        row = approval()
        legacy = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        legacy["source_id"] = "legacy-root"
        for key in ("oa_identity", "corp_id", "process_instance_id", "approval_no", "approval_identity_status", "identity_conflict"):
            legacy.pop(key, None)
        maps = service._maps(service._settings())
        service._upsert(legacy, maps)
        with patch.object(service, "_request", return_value={"items": [legacy], "end": True}):
            service.save_mapping("legacy-root", self._mapping(), legacy["version"])
            preview = service.preview_voucher("legacy-root")
            draft = service.create_voucher_draft("legacy-root", preview["fingerprint"])
        mapping_before = frappe.get_doc(service.MAPPING, "legacy-root").as_dict()
        event_before = frappe.get_doc(service.EVENT, preview["event_key"]).as_dict()
        journal_before = frappe.get_doc("Journal Entry", draft["journal_entry"]).as_dict()
        resolution = {"corp_id":row["corp_id"], "user_id": "u1", "employee_name": "Alice", "status": "matched", "assigned_department": "QA Operating China"}
        current_cashier = {**legacy, "corp_id": row["corp_id"], "process_instance_id": row["process_instance_id"],
                           "approval_no": row["business_id"], "approval_identity_status": "explicit"}
        responses = {"/api/integrations/erp/operating-expenses": {"items": [current_cashier], "end": True},
                     "/api/integrations/erp/resolve-applicant-companies": {"items": [resolution]},
                     WORKFLOW_PATH: {"schema_version": 2, "items": [workflow_fixture(row)]}}
        with patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([row], None)), patch.object(service, "_request", side_effect=lambda path, *a, **k: responses[path]):
            conflicts = ({"corp_id": "old-corp"}, {"process_instance_id": "old-instance"}, {"approval_no": "old-approval"},
                         {"corp_id": "old-corp", "process_instance_id": "old-instance", "approval_no": "old-approval"},
                         {"process_instance_id": row["process_instance_id"], "approval_no": "old-approval"}, {"identity_conflict": True})
            for evidence in conflicts:
                with self.subTest(cached_evidence=evidence):
                    service._upsert({**legacy, **evidence}, maps)
                    source_before = frappe.get_doc(service.SOURCE, "legacy-root").as_dict()
                    with self.assertRaisesRegex(frappe.ValidationError, "旧出纳来源身份冲突"):
                        service._source_page({"limit": 100})
                    self.assertEqual(frappe.get_doc(service.SOURCE, "legacy-root").as_dict(), source_before)
                    self.assertEqual(frappe.get_doc(service.MAPPING, "legacy-root").as_dict(), mapping_before)
                    self.assertEqual(frappe.get_doc(service.EVENT, preview["event_key"]).as_dict(), event_before)
                    self.assertEqual(frappe.get_doc("Journal Entry", draft["journal_entry"]).as_dict(), journal_before)
            for evidence in ({}, {"corp_id": row["corp_id"], "process_instance_id": row["process_instance_id"], "approval_no": row["business_id"], "approval_identity_status": "explicit"}):
                with self.subTest(compatible_evidence=evidence):
                    service._upsert({**legacy, **evidence}, maps)
                    self.assertEqual(service._source_page({"limit": 100})["items"][0]["source_id"], "legacy-root")
            service._upsert(legacy, maps)
            responses["/api/integrations/erp/operating-expenses"]["items"] = [deepcopy(legacy)]
            self.assertEqual(service._source_page({"limit": 100})["items"][0]["source_id"], oa.application_id(row))
            self.assertNotIn("oa_identity", json.loads(frappe.get_doc(service.SOURCE, "legacy-root").source_json))
            self.assertEqual(frappe.get_doc(service.MAPPING, "legacy-root").as_dict(), mapping_before)
            self.assertEqual(frappe.get_doc(service.EVENT, preview["event_key"]).as_dict(), event_before)
            self.assertEqual(frappe.get_doc("Journal Entry", draft["journal_entry"]).as_dict(), journal_before)

    def test_oa_cashier_supplement_keeps_existing_expense_draft_valid(self):
        from copy import deepcopy
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        service = self._sync()
        row = approval()
        cashier = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        cashier["corp_id"] = row["corp_id"]
        cashier["process_instance_id"] = row["process_instance_id"]
        cashier["payment_evidence_status"] = "recorded"
        cashier["approvals"]["raw"]["finance_review"] = "待付款"
        resolution = {"corp_id":row["corp_id"], "user_id": "u1", "employee_name": "Alice", "status": "matched", "assigned_department": "QA Operating China"}
        item = oa.merge_application(row, [cashier], resolution)
        item["source_id"] = "1001"
        service._upsert(item, service._maps(service._settings()))
        responses = {"/api/integrations/erp/operating-expenses": {"items": [cashier], "end": True},
                     "/api/integrations/erp/resolve-applicant-companies": {"items": [resolution]},
                     WORKFLOW_PATH: {"schema_version": 2, "items": [workflow_fixture(row)]}}
        with patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([row], None)), patch.object(service, "_request", side_effect=lambda path, *a, **k: responses[path]):
            service.save_mapping("1001", self._mapping(), service._fresh(service._source("1001"))["version"])
            before = service.preview_voucher("1001")
            draft = service.create_voucher_draft("1001", before["fingerprint"])
            cashier["approvals"]["raw"]["finance_review"] = "已付款"
            payment = deepcopy(cashier["payments"][0]); payment.update(source_id="2009", amount="10", payment_date="2026-10-03")
            cashier["payments"].append(payment)
            cashier.update(paid_amount="60", pending_amount="40")
            current = service._source_page({"limit": 100})["items"][0]
            self.assertEqual(current["cashier_source_id"], "1001")
            self.assertEqual((Decimal(current["paid_amount"]), Decimal(current["pending_amount"])), (Decimal("60"), Decimal("40")))
            service._upsert(current, service._maps(service._settings()))
            self.assertNotIn("财务确认后的来源事实已变化", frappe.get_doc(service.SOURCE, "1001").issues)
            self.assertEqual(service.preview_voucher("1001")["fingerprint"], before["fingerprint"])
            existing = service.create_voucher_draft("1001", before["fingerprint"])
            self.assertTrue(existing["existing"])
            self.assertEqual(existing["journal_entry"], draft["journal_entry"])
            journal = frappe.get_doc("Journal Entry", draft["journal_entry"])
            service.validate_operating_journal(journal)
            self.assertEqual(journal.docstatus, 0)

    def test_blocked_requests_remain_visible_and_keep_known_pending_balance_in_totals(self):
        service = self._sync()
        baseline = service.get_operating_expenses()["currency_totals"]["CNY"]
        item = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        item.update(source_id="blocked-original-test", source_system="dingtalk-oa", amount="500", paid_amount="0", pending_amount="500",
                    approvals={"eligibility": "blocked", "raw": {"status": "RUNNING", "result": "agree"}})
        service._upsert(item, {item["source_company"]: "QA Operating China"})
        result = service.get_operating_expenses(page_length=500)
        self.assertEqual(result["total_count"], 131)
        bucket = result["currency_totals"]["CNY"]
        baseline_known = baseline["pending_amount"] if baseline["pending_amount"] is not None else baseline["known_totals"]["pending_amount"]
        actual_known = bucket["pending_amount"] if bucket["pending_amount"] is not None else bucket["known_totals"]["pending_amount"]
        self.assertEqual(Decimal(actual_known), Decimal(baseline_known) + Decimal("500"))
        self.assertEqual(bucket["pending_amount"] is None, baseline["pending_amount"] is None)
        blocked = next(row for row in result["rows"] if row["source_id"] == "blocked-original-test")
        self.assertEqual(Decimal(blocked["pending_amount"]), Decimal("500"))
        self.assertFalse(blocked["payment_eligibility"]["can_register_payment"])

    def test_workflow_batch_uses_exact_identities_and_corrected_originators_before_company_resolution(self):
        from deeplinkerp_branding.services import operating_expenses as service
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        first, second = approval(), approval()
        first.update(status="RUNNING", result="NONE", originator_user_id="stale-manager", originator_user_name="Cached Manager")
        second.update(process_instance_id="instance-2", business_id="20260101002", status="RUNNING", result="NONE",
                      originator_user_id="stale-finance", originator_user_name="Cached Finance")
        workflows = [workflow_fixture(first, current_tasks=[{"id": "cashier-task", "stage": "出纳", "status": "RUNNING",
                        "activity_id": "CashierActivity", "entered_at": "2026-10-07T01:00:00Z", "assignees": [{"id": "cashier", "name": "QA Cashier"}]}]),
                     workflow_fixture(second, originator={"id": "u2", "name": "Bob"}, can_register_payment=False,
                        current_tasks=[{"id": "manager-task", "stage": "主管", "status": "RUNNING",
                            "activity_id": "ManagerActivity", "entered_at": "2026-10-07T01:00:00Z", "assignees": [{"id": "manager", "name": "QA Manager"}]}])]
        calls = []
        def respond(path, *args, **kwargs):
            calls.append((path, kwargs))
            if path == "/api/integrations/erp/operating-expenses":
                return {"items": [], "end": True}
            if path == WORKFLOW_PATH:
                self.assertEqual(kwargs["data"]["identities"], [{"corp_id": row["corp_id"], "process_instance_id": row["process_instance_id"], "source_id": oa.application_id(row)} for row in (first, second)])
                return {"schema_version": 2, "items": workflows}
            self.assertEqual(path, "/api/integrations/erp/resolve-applicant-companies")
            self.assertEqual(kwargs["data"]["applicants"], [{"corp_id": first["corp_id"], "user_id": "u1", "employee_name": "Alice"}, {"corp_id": second["corp_id"], "user_id": "u2", "employee_name": "Bob"}])
            return {"schema_version": 2, "items": [{"corp_id": first["corp_id"], "user_id": "u1", "employee_name": "Alice", "status": "matched", "assigned_department": "QA Operating China"},
                              {"corp_id": second["corp_id"], "user_id": "u2", "employee_name": "Bob", "status": "matched", "assigned_department": "QA Operating Mexico"}]}
        with patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([first, second], None)), patch.object(service, "_request", side_effect=respond):
            result = service._source_page({"limit": 100})
        self.assertEqual(sum(path == WORKFLOW_PATH for path, _ in calls), 1)
        self.assertLess([path for path, _ in calls].index(WORKFLOW_PATH), [path for path, _ in calls].index("/api/integrations/erp/resolve-applicant-companies"))
        for index, (row, applicant, approver, allowed) in enumerate(((first, "Alice", "QA Cashier", True), (second, "Bob", "QA Manager", False))):
            with self.subTest(instance=row["process_instance_id"]):
                item = result["items"][index]
                self.assertEqual(item["source_id"], oa.application_id(row))
                self.assertEqual(item["applicant"], applicant)
                self.assertEqual(item["current_approver"], approver)
                self.assertEqual(item["approvals"]["raw"]["status"], "RUNNING")
                self.assertEqual(item["approval_state"], "pending")
                self.assertEqual(item["payment_eligibility"]["can_register_payment"], allowed)
                self.assertIsNone(item["cashier_source_id"])
                self.assertIsNone(item["paid_amount"])
                self.assertIsNone(item["pending_amount"])

        # Same corp-local user IDs must never consume another corporation's
        # globally resolved company, nor a legacy response without corp evidence.
        for untrusted_corp in (None, "different-corp"):
            def mismatch(path, *args, **kwargs):
                response = respond(path, *args, **kwargs)
                if path == "/api/integrations/erp/resolve-applicant-companies":
                    response["items"][0]["corp_id"] = untrusted_corp
                return response
            with self.subTest(untrusted_corp=untrusted_corp), patch.dict(frappe.conf, operating_expense_source_mode="oa_cashier"), patch.object(service, "_oa_connection", return_value=None), patch.object(oa, "read_page", return_value=([first, second], None)), patch.object(service, "_request", side_effect=mismatch):
                with self.assertRaisesRegex(frappe.ValidationError, "申请人归属返回身份不符"):
                    service._source_page({"limit": 100})

    def _exported_rows(self, service, filters, columns):
        import xml.etree.ElementTree as ET
        service.export_operating_expenses(filters=filters, order_by="source_id asc", columns=columns)
        with ZipFile(BytesIO(frappe.response["filecontent"])) as workbook:
            xml = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        result = []
        for row in xml.findall("m:sheetData/m:row", ns)[1:]:
            values = [None] * len(columns)
            for cell in row.findall("m:c", ns):
                letters = "".join(char for char in cell.attrib["r"] if char.isalpha())
                index = 0
                for letter in letters:
                    index = index * 26 + ord(letter) - ord("A") + 1
                text = cell.find("m:is/m:t", ns) if cell.attrib.get("t") == "inlineStr" else cell.find("m:v", ns)
                values[index - 1] = text.text if text is not None else None
            result.append(values)
        return result

    def test_virtual_approval_filters_quick_tabs_and_export_share_company_number_and_balances(self):
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        service = self._sync()
        marker = "qa-workflow-filter-contract"
        specs = [("cashier", "RUNNING", "NONE", True, "30", "70", "pending", "QA Operating China"),
                 ("manager", "RUNNING", "NONE", False, "0", "100", "pending", "QA Operating China"),
                 ("paid", "COMPLETED", "agree", True, "100", "0", "approved", "QA Operating China"),
                 ("history-unknown", "COMPLETED", "agree", True, None, None, "approved", "QA Operating China"),
                 ("rejected", "COMPLETED", "refuse", False, "0", "100", "rejected", "QA Operating China"),
                 ("terminated", "TERMINATED", "agree", False, "0", "100", "terminated", "QA Operating China"),
                 ("scope-removed", "COMPLETED", "agree", True, None, None, "unknown", "QA Operating China"),
                 ("unknown", "UNKNOWN", "NONE", False, "0", "100", "unknown", "QA Operating China"),
                 ("mexico", "RUNNING", "NONE", True, "40", "60", "pending", "QA Operating Mexico")]
        expected = {}
        for key, status, result, allowed, paid, pending, state, company in specs:
            row = approval()
            row.update(process_instance_id="qa-workflow-" + key, business_id="QA-ORIGINAL-" + key, status=status, result=result)
            row["form_component_values"][4]["value"] = marker
            row["form_component_values"].append({"name": "归属项目", "value": "QA项目-" + key})
            if company == "QA Operating Mexico":
                row["form_component_values"][3]["value"] = "比索"
            tasks = [{"id": key, "stage": "出纳" if allowed else "主管", "status": "RUNNING", "assignees": [{"id": key, "name": "QA Cashier" if allowed else "QA Manager"}]}] if status == "RUNNING" else []
            current = oa.with_workflow(row, workflow_fixture(row, current_tasks=tasks, can_register_payment=allowed))
            currency = "MXN" if company == "QA Operating Mexico" else "CNY"
            cashier = [] if paid is None else [{"source_id": "qa-cashier-" + key, "corp_id": row["corp_id"], "process_instance_id": row["process_instance_id"],
                "amount": "100", "currency": currency, "paid_amount": paid, "pending_amount": pending,
                "source_status": "已付款" if pending == "0" else "部分付款" if paid != "0" else "未付款",
                "payment_evidence_status": "recorded", "payments": [], "attachments": []}]
            item = oa.merge_application(current, cashier, {"status": "matched", "assigned_department": company})
            if key == "scope-removed":
                item = oa.withdrawn_source(item, row)
            service._upsert(item, service._maps(service._settings()))
            expected[key] = {"source_id": item["source_id"], "approval_no": row["business_id"], "state": state,
                "paid": paid, "pending": pending, "company": company}
        scope = {"keyword": marker, "company": "QA Operating China"}
        all_rows = service.get_operating_expenses(filters=scope, order_by="source_id asc", page_length=500)
        projected = {row["source_id"]: row for row in all_rows["rows"]}
        self.assertEqual(all_rows["total_count"], 8)
        for key, facts in expected.items():
            if facts["company"] == "QA Operating China":
                self.assertEqual(projected[facts["source_id"]]["approval_state"], facts["state"])
        self.assertEqual(projected[expected["cashier"]["source_id"]]["current_approver"], "QA Cashier")
        self.assertEqual(projected[expected["manager"]["source_id"]]["current_approver"], "QA Manager")
        self.assertTrue(projected[expected["cashier"]["source_id"]]["payment_eligibility"]["can_register_payment"])
        self.assertFalse(projected[expected["manager"]["source_id"]]["payment_eligibility"]["can_register_payment"])
        self.assertFalse(projected[expected["scope-removed"]["source_id"]]["payment_eligibility"]["can_register_payment"])
        self.assertIsNone(all_rows["currency_totals"]["CNY"]["paid_amount"])
        self.assertIsNone(all_rows["currency_totals"]["CNY"]["pending_amount"])
        self.assertEqual(next(row for row in all_rows["rows"] if row["name"] == expected["history-unknown"]["source_id"])["source_status"], "付款待核对")
        self.assertEqual(all_rows["currency_totals"]["CNY"]["incomplete_fields"], ["paid_amount", "pending_amount"])
        self.assertEqual({field: Decimal(value) for field, value in all_rows["currency_totals"]["CNY"]["known_totals"].items()}, {"paid_amount": Decimal("130"), "pending_amount": Decimal("470")})
        self.assertTrue(all_rows["currency_totals"]["CNY"]["incomplete"])
        both_companies = service.get_operating_expenses(filters={"keyword": marker}, page_length=500)
        self.assertEqual(both_companies["total_count"], 9)
        self.assertIsNone(both_companies["currency_totals"]["CNY"]["pending_amount"])
        self.assertEqual(Decimal(both_companies["currency_totals"]["CNY"]["known_totals"]["pending_amount"]), Decimal("470"))
        self.assertEqual(Decimal(both_companies["currency_totals"]["MXN"]["pending_amount"]), Decimal("60"))
        self.assertFalse(both_companies["currency_totals"]["MXN"]["incomplete"])
        for tab, keys in (("all", [key for key, value in expected.items() if value["company"] == "QA Operating China"]),
                          ("pending_payment", ["cashier"]), ("approvals_running", ["cashier", "manager"]),
                          ("paid", ["paid"]), ("reconciliation", ["history-unknown", "scope-removed", "unknown"])):
            with self.subTest(tab=tab):
                predicates = {**scope, "quick_tab": tab}
                result = service.get_operating_expenses(filters=predicates, order_by="source_id asc", page_length=20)
                self.assertEqual(result["total_count"], len(keys))
                self.assertEqual({row["source_id"] for row in result["rows"]}, {expected[key]["source_id"] for key in keys})
                exported = self._exported_rows(service, predicates, ["display_source_id", "approval_state", "current_approver", "pending_amount", "project", "source_system"])
                self.assertEqual([row[0] for row in exported], [row["approval_no"] for row in result["rows"]])
                self.assertEqual([row[1] for row in exported], [row["approval_state"] for row in result["rows"]])
                self.assertEqual([row[2] or "" for row in exported], [row["current_approver"] for row in result["rows"]])
                self.assertEqual([Decimal(row[3]) if row[3] is not None else None for row in exported], [Decimal(row["pending_amount"]) if row["pending_amount"] is not None else None for row in result["rows"]])
                self.assertEqual([row[4] for row in exported], ["QA项目-" + key for row in result["rows"] for key in keys if expected[key]["source_id"] == row["source_id"]])
                self.assertEqual([row[5] for row in exported], [oa.SOURCE_SYSTEM] * len(keys))
                known = sum((Decimal(expected[key]["pending"]) for key in keys if expected[key]["pending"] is not None), Decimal(0))
                bucket = result["currency_totals"]["CNY"]
                if any(expected[key]["pending"] is None for key in keys):
                    self.assertIsNone(bucket["pending_amount"])
                    self.assertEqual(Decimal(bucket["known_totals"]["pending_amount"]), known)
                else:
                    self.assertEqual(Decimal(bucket["pending_amount"]), known)
        for state in ("pending", "approved", "rejected", "terminated", "withdrawn", "unknown"):
            with self.subTest(approval_state=state):
                result = service.get_operating_expenses(filters={**scope, "approval_state": state}, page_length=500)
                self.assertEqual({row["source_id"] for row in result["rows"]}, {facts["source_id"] for facts in expected.values() if facts["state"] == state and facts["company"] == "QA Operating China"})
        for legacy, keys in (("eligible", ["cashier", "paid", "history-unknown"]), ("blocked", ["manager", "rejected", "terminated", "scope-removed", "unknown"])):
            with self.subTest(legacy_approval_filter=legacy):
                result = service.get_operating_expenses(filters={**scope, "approval_state": legacy}, page_length=500)
                self.assertEqual({row["source_id"] for row in result["rows"]}, {expected[key]["source_id"] for key in keys})
        number = expected["cashier"]["approval_no"]
        numbered = service.get_operating_expenses(filters={"keyword": number, "company": "QA Operating China", "quick_tab": "pending_payment", "approval_state": "pending"})
        self.assertEqual([row["source_id"] for row in numbered["rows"]], [expected["cashier"]["source_id"]])
        self.assertEqual(self._exported_rows(service, {"keyword": number, "company": "QA Operating China", "quick_tab": "pending_payment", "approval_state": "pending"}, ["display_source_id"]), [[number]])
        uncertain = service.get_operating_expenses(filters={"keyword": expected["history-unknown"]["approval_no"], "company": "QA Operating China"})["currency_totals"]["CNY"]
        self.assertEqual(Decimal(uncertain["amount"]), Decimal("100"))
        self.assertIsNone(uncertain["paid_amount"])
        self.assertIsNone(uncertain["pending_amount"])
        self.assertEqual(uncertain["known_totals"], {})
        self.assertEqual(uncertain["incomplete_fields"], ["paid_amount", "pending_amount"])

    def test_cache_and_mapping_cannot_be_faked_through_native_documents(self):
        self.assertTrue(frappe.db.exists("DocType", "Operating Expense Source"), "Source model is missing")
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc({"doctype": "Operating Expense Source", "source_id": "fake", "source_json": "{}"}).insert(ignore_permissions=True)

    def test_settings_disabled_and_secret_not_exposed(self):
        from deeplinkerp_branding.services import operating_expenses as service
        self.assertFalse(service.get_sync_settings()["enabled"])
        self.assertNotIn("api_token", service.get_sync_settings())

    def test_original_approval_number_is_projected_without_raw_json_or_identity_change(self):
        service = self._sync()
        item = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        item["approval_no"] = "20260101-readable"
        service._upsert(item, {item["source_company"]: "QA Operating China"})
        row = next(row for row in service.get_operating_expenses(page_length=500)["rows"] if row["source_id"] == "1001")
        self.assertEqual(row["approval_no"], "20260101-readable")
        self.assertNotIn("source_json", row)
        # Exercise the chunk boundary with authorized source handles, without
        # creating hundreds of otherwise identical native documents.
        with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
            projected = [{"name": "1001", "source_system": item["source_system"]} for _ in range(501)]
            service._readable_source_numbers(projected)
        projections = [call for call in sql.call_args_list if isinstance(call.args[0], str) and call.args[0].startswith("SELECT name,JSON_EXTRACT")]
        self.assertEqual([len(call.args[1]["names"]) for call in projections], [500, 1])
        self.assertEqual({row["approval_no"] for row in projected}, {"20260101-readable"})
        for call in projections:
            self.assertEqual(call.args[0].count("JSON_EXTRACT"), 7)
            self.assertNotIn("$.payments", call.args[0])
            self.assertNotIn("$.attachments", call.args[0])

    def test_removed_oa_application_stays_auditable_but_not_payable(self):
        from deeplinkerp_branding.services import operating_oa_source as oa
        from tests.test_operating_oa_source import approval
        service = self._sync()
        item = oa.merge_application(approval(), [], {"status": "matched", "assigned_department": "QA Operating China"})
        item.update(paid_amount="0", pending_amount="100", source_status="未付款")
        service._upsert(item, service._maps(service._settings()))
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return self
            def execute(self, *args): pass
            def fetchall(self): return []
            def _connection(self): return self
        with patch.object(service, "_oa_connection", return_value=Connection()):
            self.assertEqual(service._reconcile_oa_cache("2026-10-06T00:00:00Z", service._maps(service._settings())), 1)
            self.assertEqual(service._reconcile_oa_cache("2026-10-06T00:00:00Z", service._maps(service._settings())), 0)
        doc = frappe.get_doc(service.SOURCE, item["source_id"])
        self.assertEqual(doc.approval_state, "blocked")
        self.assertIsNone(doc.pending_amount)

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
        original["approvals"]["raw"].update(cashier_general_manager_approval="同意付款", cashier_finance_review="已付款", cashier_opaque_private_party="must-not-leak")
        service._upsert(original, service._maps(service._settings()))
        detail = service.get_operating_expense_detail("1001")["source"]
        self.assertNotIn("opaque_private_party", detail)
        self.assertNotIn("opaque_private_party", detail["payments"][0])
        self.assertNotIn("opaque_private_party", detail["approvals"]["raw"])
        self.assertNotIn("cashier_opaque_private_party", detail["approvals"]["raw"])
        self.assertEqual(detail["approvals"]["raw"].get("cashier_general_manager_approval"), "同意付款")
        self.assertEqual(detail["approvals"]["raw"].get("cashier_finance_review"), "已付款")
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
        from xlsxwriter.worksheet import Worksheet
        service = self._sync()
        item = json.loads(frappe.get_doc("Operating Expense Source", "1001").source_json)
        service._upsert({**item, "summary": "=SUM(A1:A2)"}, service._maps(service._settings()))
        columns = ["source_id", "summary", "amount", "paid_amount", "pending_amount", "currency", "request_date"]
        authorized_rows = service._list_rows()
        written_row = -1
        original_write, case = Worksheet.write, self
        class StreamingRow(dict):
            def __init__(self, row, index):
                super().__init__(row)
                self.index = index
            def get(self, key, default=None):
                if key in columns:
                    case.assertLessEqual(self.index, written_row + 1, "Write rows directly; do not prepare a second full export table")
                return super().get(key, default)
        def tracked_write(sheet, row, column, *args, **kwargs):
            nonlocal written_row
            self.assertGreaterEqual(row, written_row)
            result = original_write(sheet, row, column, *args, **kwargs)
            written_row = row
            return result
        rows = [StreamingRow(row, index) for index, row in enumerate(authorized_rows, 1)]
        with patch.object(service, "_list_rows", return_value=rows), patch.object(Worksheet, "write", new=tracked_write), \
             patch.object(frappe.permissions, "can_export", side_effect=lambda doctype, **kwargs: kwargs.get("is_owner", False)), \
             patch.object(service, "_source", wraps=service._source) as source:
            service.export_operating_expenses(columns=columns)
        self.assertEqual([call.args[0] for call in source.call_args_list], [row["name"] for row in authorized_rows])
        with ZipFile(BytesIO(frappe.response["filecontent"])) as workbook:
            xml = workbook.read("xl/worksheets/sheet1.xml").decode()
            self.assertNotIn("<f>", xml)
            self.assertIn("=SUM(A1:A2)", xml)
            self.assertEqual(xml.count("<row "), 131)
            self.assertIn('<c r="C2" s="1"><v>', xml)
            self.assertIn('formatCode="0.00"', workbook.read("xl/styles.xml").decode())
            self.assertIn('formatCode="yyyy-mm-dd"', workbook.read("xl/styles.xml").decode())
            self.assertIn('<c r="G2" s="2"><v>', xml)
        with patch.object(service, "_source", side_effect=AssertionError("Native full export authority must keep its lazy shortcut")):
            service.export_operating_expenses(columns=columns)
        frappe.db.set_value(service.SOURCE, "1001", "owner", "qa-export-nonowner@example.invalid", update_modified=False)
        with patch.object(frappe.permissions, "can_export", side_effect=lambda doctype, **kwargs: kwargs.get("is_owner", False)), \
             patch.object(Worksheet, "write") as write, self.assertRaises(frappe.PermissionError):
            service.export_operating_expenses(columns=columns)
        write.assert_not_called()

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

    def test_oa_archive_checks_current_hash_again_before_download(self):
        from types import SimpleNamespace
        from deeplinkerp_branding.services import operating_oa_source as oa
        service = self._sync()
        item = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
        item["oa_identity"] = {"corp_id": "corp", "process_instance_id": "i"}
        manifest = {**item["oa_identity"], "file_id": "f", "file_name": "invoice.pdf", "archive_status": "archived", "sha256": "a" * 64, "actual_size": 20}
        item["attachments"] = oa.archive_attachments(item["oa_identity"], [manifest])
        service._upsert(item, service._maps(service._settings()))
        with patch.object(service, "_fresh", return_value=item), patch.object(service, "_oa_connection", return_value=SimpleNamespace(get_attachment_manifest=lambda *a: {**manifest, "sha256": "b" * 64})):
            with self.assertRaisesRegex(frappe.ValidationError, "附件已变化"):
                service.download_operating_expense_attachment("1001", item["attachments"][0]["source_id"])

        for invalid in ({"sha256": None}, {"sha256": "not-a-hash"}, {"actual_size": None}, {"actual_size": -1}):
            invalid_manifest = {**manifest, **invalid}
            item["attachments"] = oa.archive_attachments(item["oa_identity"], [invalid_manifest])
            service._upsert(item, service._maps(service._settings()))
            with patch.object(service, "_fresh", return_value=item), patch.object(service, "_oa_connection", return_value=SimpleNamespace(get_attachment_manifest=lambda *a: invalid_manifest)), patch("overseas_costing.services.import_service._get_minio_archive_client", side_effect=AssertionError("Invalid archive must not download")):
                with self.assertRaisesRegex(frappe.ValidationError, "归档校验信息"):
                    service.download_operating_expense_attachment("1001", item["attachments"][0]["source_id"])
        import hashlib
        content = b"QA archived proof"
        manifest.update(sha256=hashlib.sha256(content).hexdigest(), actual_size=len(content))
        item["attachments"] = oa.archive_attachments(item["oa_identity"], [manifest])
        service._upsert(item, service._maps(service._settings()))
        with patch.object(service, "_fresh", return_value=item), patch.object(service, "_oa_connection", return_value=SimpleNamespace(get_attachment_manifest=lambda *a: manifest)), patch("overseas_costing.services.import_service._get_minio_archive_client", return_value=SimpleNamespace(download=lambda m: (content, "application/pdf"))):
            service.download_operating_expense_attachment("1001", item["attachments"][0]["source_id"])
            self.assertEqual(frappe.response["filecontent"], content)
        with patch.object(service, "_fresh", return_value=item), patch.object(service, "_oa_connection", return_value=SimpleNamespace(get_attachment_manifest=lambda *a: manifest)), patch("overseas_costing.services.import_service._get_minio_archive_client", return_value=SimpleNamespace(download=lambda m: (b"tampered proof", "application/pdf"))):
            with self.assertRaisesRegex(frappe.ValidationError, "校验不一致"):
                service.download_operating_expense_attachment("1001", item["attachments"][0]["source_id"])

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
